"""ETL 管道编排（§5 Step1~7 + 并发互斥 + 重建窗口降级标记 + 校验报告）。

用法：
  python -m app.pipeline.runner              # 全量重建（默认 reset 向量库）
  python -m app.pipeline.runner --no-reset   # 增量模式：不删向量集合

流程：解析 -> LLM 打标（规则兜底）-> SQLite dish_meta + llm_usage -> Neo4j 图谱
     -> Qdrant 三集合 -> 别名表 -> 校验报告
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.core.clients.embedding import build_embedding_client
from app.core.clients.llm import LLMClient
from app.core.clients.factory import build_graph_store
from app.core.clients.factory import build_vector_store
from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError
from app.core.logging import get_logger
from app.db.json_utils import json_load
from app.db.models import DishMeta, IngestRun, LLMUsage
from app.db.session import get_engine
from app.pipeline import graph_builder, parser, tagger, vector_indexer

logger = get_logger("pipeline.runner")

# 陈旧 running 记录判定阈值：超过该时长仍未完成，视为上次进程被中断的残留（§5 中断恢复）
STALE_RUN_MINUTES = 30


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Git LFS 指针文件标记：真实图片未随数据源下载（§12.5 数据源说明），
# 内容是 131 字节文本而非图片，浏览器解码失败（请求 200 但不显示）
_LFS_MARK = b"version https://git-lfs.github.com/spec/v1"


def _is_lfs_pointer(path: Path) -> bool:
    """Git LFS 指针检测：文件头为 LFS spec 标记 -> 非真实图片，跳过。"""
    try:
        with path.open("rb") as fh:
            return fh.read(64).startswith(_LFS_MARK)
    except OSError:
        return True  # 读取失败按无效处理


def _scan_dish_images(settings: Settings, rel_path: str) -> tuple[list[str], str | None]:
    """扫描菜谱图片（§12.5）：返回 (全部图片相对路径, 主图相对路径)。

    数据源结构：图片可能在 md 同目录，也可能在"与菜名同名"的子目录
    （如 dishes/aquatic/小炒黄牛肉.md + dishes/aquatic/小炒黄牛肉/成品.jpg），
    两者都扫描；Git LFS 指针文件（真实内容未下载）自动跳过；
    主图优先选择文件名包含菜名的图片，否则取第一张。
    """
    dishes_root = settings.data_source_root / "dishes"
    dish_file = dishes_root / rel_path
    folder = dish_file.parent
    if not folder.is_dir():
        return [], None
    stem = Path(rel_path).stem
    scan_dirs = [folder]
    named_dir = folder / stem
    if named_dir.is_dir():
        scan_dirs.append(named_dir)
    imgs = sorted(
        {
            p.relative_to(dishes_root).as_posix()
            for d in scan_dirs
            for p in d.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTS and not _is_lfs_pointer(p)
        }
    )
    if not imgs:
        return [], None
    main = next((i for i in imgs if stem in Path(i).stem), imgs[0])
    return imgs, main


def _active_run(session: Session) -> IngestRun | None:
    return session.exec(select(IngestRun).where(IngestRun.status == "running")).first()


def _tags_backup_path(settings: Settings) -> Path:
    """打标结果即时落盘（§5 崩溃保护）：Step2 完成后立即写入，--skip-tag 优先恢复。"""
    return settings.sqlite_file.parent / "tags_backup.json"


def _dump_tags(settings: Settings, tags: dict[str, tagger.DishTags]) -> None:
    """打标结果持久化（防止后续步骤崩溃丢失 LLM 标签，§5 断点续跑）。"""
    try:
        _tags_backup_path(settings).write_text(
            json.dumps(
                {
                    did: {
                        "cuisines": t.cuisines,
                        "flavors": t.flavors,
                        "techniques": t.techniques,
                        "meat_attr": t.meat_attr,
                        "main_ingredients": t.main_ingredients,
                        "time_est_min": t.time_est_min,
                        "meal_types": t.meal_types,
                    }
                    for did, t in tags.items()
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 —— 备份失败不阻塞主流程
        logger.warning("tags 备份写入失败，忽略（%s）", _tags_backup_path(settings))


def _load_tags_backup(settings: Settings) -> dict[str, tagger.DishTags] | None:
    """从备份恢复打标结果；无备份/损坏返回 None。"""
    path = _tags_backup_path(settings)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {
            did: tagger.DishTags(dish_id=did, **data)
            for did, data in raw.items()
        }
    except Exception:  # noqa: BLE001
        return None


def _recover_stale_runs(session: Session, *, force: bool = False) -> None:
    """中断恢复（§5）：把残留的 running 记录标记为 failed。

    原因：进程被 Ctrl+C / kill 后，ingest_runs 会残留 status=running 记录，
    若不清理会触发并发互斥（409）导致无法重跑。ETL 全程幂等
    （SQLite upsert / Neo4j MERGE / Qdrant 重建），中断后的半成品数据
    会被下一次完整运行覆盖，无需手工清理数据。

    force=True（--force）：清理全部 running 记录（用户确认旧进程已死）
    force=False：仅清理超过 STALE_RUN_MINUTES 的陈旧记录（防御自动恢复）
    """
    if force:
        stale = session.exec(select(IngestRun).where(IngestRun.status == "running")).all()
        note = "[--force] 清理全部残留 running 记录（用户确认旧进程已退出），可安全重跑"
    else:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=STALE_RUN_MINUTES)
        stale = session.exec(
            select(IngestRun).where(
                IngestRun.status == "running",
                IngestRun.started_at < cutoff,
            )
        ).all()
        note = f"[自动恢复] 检测到陈旧 running 记录（> {STALE_RUN_MINUTES} 分钟，疑似中断残留），已标记 failed，可安全重跑"
    for run in stale:
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.log = (run.log + f"\n{note}").strip()
        session.add(run)
    if stale:
        session.commit()


def _write_alias_table(settings: Settings, corpus: parser.ParsedCorpus) -> None:
    """§5 Step7：菜名/食材别名表（query_rewriter 兜底，§6.4）。"""
    target = settings.sqlite_file.parent.parent / "app" / "rag" / "data" / "alias_table.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(corpus.alias_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_tags_from_db(engine, corpus: parser.ParsedCorpus) -> dict[str, tagger.DishTags]:
    """--skip-tag：从 SQLite dish_meta 恢复 LLM 打标结果（§5 断点续跑）。"""
    tags: dict[str, tagger.DishTags] = {}
    with Session(engine) as session:
        for d in corpus.dishes:
            row = session.get(DishMeta, d.dish_id)
            if row is None or not row.tags:
                tags[d.dish_id] = tagger._rule_fallback(d)
                continue
            try:
                t = json_load(row.tags, {})
                tags[d.dish_id] = tagger.DishTags(
                    dish_id=d.dish_id,
                    cuisines=t.get("cuisines") or [],
                    flavors=t.get("flavors") or [],
                    techniques=t.get("techniques") or [],
                    meat_attr=t.get("meat_attr") or "其他",
                    main_ingredients=json_load(row.main_ingredients, []),
                    time_est_min=row.time_est,
                    meal_types=t.get("meal_types") or [],
                )
            except (ValueError, TypeError):
                tags[d.dish_id] = tagger._rule_fallback(d)
    return tags


def _validate(settings: Settings, corpus: parser.ParsedCorpus, stats: vector_indexer.VectorStats | None) -> list[str]:
    """§5 Step6：校验报告条目。stats=None 表示 --sqlite-only（未构建向量）。"""
    lines: list[str] = []
    lines.append(f"解析菜谱: {len(corpus.dishes)} 道（期望 357）")
    lines.append(f"解析技巧: {len(corpus.tips)} 篇（期望 18）")
    if stats is not None:
        lines.append(f"Qdrant 向量: dishes={stats.dishes}, chunks={stats.chunks}, tips={stats.tips}")
    else:
        lines.append("Qdrant 向量: 未构建（--sqlite-only 跳过）")
    if len(corpus.dishes) != 357:
        lines.append(f"[WARN] 菜谱数量与期望不符（{len(corpus.dishes)} != 357），请检查数据源")
    if len(corpus.tips) != 18:
        lines.append(f"[WARN] 技巧数量与期望不符（{len(corpus.tips)} != 18），请检查数据源")
    return lines


async def run_ingest(
    settings: Settings | None = None,
    *,
    reset: bool = True,
    run_id: int | None = None,
    force: bool = False,
    skip_tag: bool = False,
    sqlite_only: bool = False,
) -> int:
    """执行完整 ETL，返回 ingest_runs.id。

    - run_id=None：CLI/直接调用，先做互斥检查并创建 run 记录（§5）
    - run_id=给定：API 触发路径（调用方已创建记录），跳过互斥检查
    - force=True：清理全部残留 running 记录后执行（中断恢复，--force）
    - skip_tag=True：跳过 LLM 打标，从 SQLite dish_meta 恢复标签（断点续跑，--skip-tag）
    - sqlite_only=True：仅更新 SQLite dish_meta（content/image，§2.2/§12.5），跳过图谱与向量（秒级增量，--sqlite-only）
    """
    settings = settings or get_settings()
    engine = get_engine()

    if run_id is None:
        with Session(engine) as session:
            _recover_stale_runs(session, force=force)  # §5 中断恢复：清理残留 running 记录
            if _active_run(session):
                raise ConflictError("已有 ETL 管道正在运行，请等待完成（§5 ingest 并发互斥）")
            run = IngestRun(status="running", log="")
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

    log_lines: list[str] = []
    corpus = parser.ParsedCorpus(dishes=[], tips=[])
    usages: list[LLMUsage] = []
    try:
        # Step1 解析
        log_lines.append("Step1 解析 md ...")
        corpus = parser.parse_corpus(settings.data_source_root)
        log_lines.append(f"  -> 菜谱 {len(corpus.dishes)} 道，技巧 {len(corpus.tips)} 篇")

        # Step2 LLM 打标（规则兜底）或 --skip-tag 恢复（备份优先，§5 崩溃保护）
        if skip_tag:
            backup = _load_tags_backup(settings)
            if backup:
                log_lines.append("Step2 跳过 LLM 打标（--skip-tag，从 tags_backup.json 恢复标签）...")
                tags = backup
            else:
                log_lines.append("Step2 跳过 LLM 打标（--skip-tag，从 SQLite dish_meta 恢复标签）...")
                tags = _load_tags_from_db(engine, corpus)
        else:
            log_lines.append("Step2 LLM 打标 ...")
            llm = LLMClient(settings)
            total = len(corpus.dishes)

            def _progress(done: int, total: int) -> None:
                log_lines.append(f"  - 打标进度 {done}/{total}")
                logger.info("打标进度 %s/%s", done, total)

            tags, usages = await tagger.tag_batch(corpus.dishes, llm, on_batch=_progress)
            fallback_count = sum(
                1 for d in corpus.dishes if not tags.get(d.dish_id, tagger.DishTags(dish_id="")).cuisines
            )
            log_lines.append(f"  -> 打标完成，规则兜底 {fallback_count} 道")
            # 即时落盘：后续步骤崩溃不再丢失 LLM 标签（§5 崩溃保护）
            _dump_tags(settings, tags)

        # Step3 SQLite：dish_meta + llm_usage
        log_lines.append("Step3 写 SQLite ...")
        with Session(engine) as session:
            for d in corpus.dishes:
                t = tags.get(d.dish_id, tagger.DishTags(dish_id=d.dish_id))
                existing = session.get(DishMeta, d.dish_id)
                row = existing or DishMeta(dish_id=d.dish_id)
                row.name = d.name
                row.category = d.category
                row.path = d.rel_path
                row.difficulty = d.difficulty
                row.intro = d.intro
                row.time_est = t.time_est_min
                # JSON 列统一存 Python 对象（SQLAlchemy 自动序列化），读取用 json_load（§4.3）
                row.main_ingredients = t.main_ingredients
                row.tags = {
                    "cuisines": t.cuisines, "flavors": t.flavors, "techniques": t.techniques,
                    "meal_types": t.meal_types, "meat_attr": t.meat_attr,
                }
                # 完整内容（与数据源 md 一致，§2.2）+ 图片扫描（§12.5 静态托管）
                row.content = {
                    "required_raw": d.required_raw,
                    "optional_raw": d.optional_raw,
                    "calculation_raw": d.calculation_raw,
                    "steps": [{"version": s.version, "order": s.order, "text": s.text} for s in d.steps],
                    "notes": d.notes,
                }
                images, main_image = _scan_dish_images(settings, d.rel_path)
                row.images = images
                row.image = main_image
                row.vector_status = "indexed"
                session.add(row)
            for u in usages:
                session.add(
                    LLMUsage(node="tagger", model=settings.llm_model,
                             prompt_tokens=u.prompt_tokens, completion_tokens=u.completion_tokens)
                )
            session.commit()

        # Step4 Neo4j 图谱（--sqlite-only 跳过；reset=True 时先清空菜谱子图再重灌，§3）
        if not sqlite_only:
            log_lines.append("Step4 写 Neo4j ...")
            neo4j = build_graph_store(settings)
            try:
                gstats = graph_builder.write_graph(neo4j, corpus.dishes, tags, reset=reset)
                log_lines.append(f"  -> {gstats}")
            finally:
                neo4j.close()

        # Step5 Qdrant 三集合（--sqlite-only 跳过）
        vstats = None
        if not sqlite_only:
            log_lines.append("Step5 写 Qdrant ...（首次运行会自动下载 bge-small-zh-v1.5 模型，约 100MB）")
            logger.info("Step5 写 Qdrant ...（首次运行会自动下载 bge-small-zh-v1.5 模型，约 100MB）")
            qdrant = build_vector_store(settings)
            embedding = build_embedding_client(settings)
            vstats = await vector_indexer.rebuild_indexes(
                qdrant, embedding, settings, corpus.dishes, tags, corpus, reset=reset
            )
            log_lines.append(f"  -> {vstats}")

        # Step7 别名表（§5 Step7）
        _write_alias_table(settings, corpus)

        # Step6 校验报告
        if sqlite_only:
            log_lines.append("--sqlite-only 模式：跳过图谱与向量（content/image 已更新）")
        log_lines.extend(_validate(settings, corpus, vstats))
        status = "done"
    except Exception as exc:  # noqa: BLE001 —— 失败记录进 run.log
        log_lines.append(f"ERROR: {type(exc).__name__}: {exc}")
        status = "failed"
        raise
    finally:
        with Session(engine) as session:
            run = session.get(IngestRun, run_id)
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.dish_count = len(corpus.dishes)
            run.log = "\n".join(log_lines)[-8000:]
            session.add(run)
            session.commit()

    return run_id


def main() -> None:
    """CLI 入口：python -m app.pipeline.runner [--no-reset]"""
    import argparse

    from app.core.logging import setup_logging
    from app.db.session import run_migrations

    setup_logging()
    run_migrations()  # CLI 路径也要先建表（§4.3：首次建库 = alembic upgrade head；API 路径由 main.py lifespan 执行）
    parser_args = argparse.ArgumentParser(description="ETL 数据管道（§5）")
    parser_args.add_argument("--no-reset", action="store_true", help="不重建 Qdrant 集合（增量模式）")
    parser_args.add_argument(
        "--force", action="store_true",
        help="清理残留 running 记录后强制执行（中断恢复：上次进程被 Ctrl+C 后使用）",
    )
    parser_args.add_argument(
        "--skip-tag", action="store_true",
        help="跳过 LLM 打标，从 SQLite dish_meta 恢复标签（打标已完成时的断点续跑）",
    )
    parser_args.add_argument(
        "--sqlite-only", action="store_true",
        help="仅更新 SQLite dish_meta（content/image，§2.2/§12.5），跳过图谱与向量（秒级增量）",
    )
    args = parser_args.parse_args()

    run_id = asyncio.run(run_ingest(
        reset=not args.no_reset, force=args.force, skip_tag=args.skip_tag, sqlite_only=args.sqlite_only,
    ))
    logger.info("ETL 完成，run_id=%s（查看 backend/data/yeahwhat2eat.db ingest_runs 表日志）", run_id)


if __name__ == "__main__":
    main()
