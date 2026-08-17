"""菜谱查询服务（§9 菜谱浏览）：列表 / 详情 / 相关菜 / 热门。

- 列表：SQLite dish_meta 为业务真源（§3），全量加载后内存过滤（357 条规模，§4.4）
- 详情：SQLite 完整内容（content 与数据源 md 一致，§2.2）+ 图片（§12.5）
- 相关菜：Neo4j RELATED_TO 一跳；图不可用时降级为同分类（§7.3 错误降级）
- 热门：§8.3 热度公式 hot(d) = Σ action_weight × exp(-Δt/30d)，聚合行为流水
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.core.clients.factory import build_graph_store
from app.core.config import Settings, get_settings
from app.db.json_utils import json_load
from app.db.models import DishMeta, UserFeedback
from app.db.session import get_engine

# 行为权重（§8.3 热门榜口径）
_ACTION_WEIGHT = {"view": 1, "like": 3, "rating": 2, "made": 5, "dislike": -3}
_HOT_WINDOW_DAYS = 30


def _meta_to_summary(m: DishMeta) -> dict:
    tags = json_load(m.tags, {})
    return {
        "dish_id": m.dish_id,
        "name": m.name,
        "category": m.category,
        "difficulty": m.difficulty,
        "time_est": m.time_est,
        "meat_attr": tags.get("meat_attr", "其他"),
        "cuisines": tags.get("cuisines") or [],
        "flavors": tags.get("flavors") or [],
        "techniques": tags.get("techniques") or [],
        "image": m.image,
    }


def list_dishes(
    *,
    category: str | None = None,
    difficulty: int | None = None,
    flavor: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 24,
) -> dict:
    """菜谱列表（分类 / 难度上限 / 口味 / 关键词过滤 + 分页）。"""
    with Session(get_engine()) as session:
        rows = session.exec(select(DishMeta)).all()

    items: list[dict] = []
    for m in rows:
        summary = _meta_to_summary(m)
        if category and m.category != category:
            continue
        if difficulty and m.difficulty is not None and m.difficulty > difficulty:
            continue
        if flavor and flavor not in (summary["flavors"] or []):
            continue
        if keyword:
            kw = keyword.strip()
            if kw and kw not in m.name and not any(kw in ing for ing in json_load(m.main_ingredients, [])):
                continue
        items.append(summary)

    items.sort(key=lambda x: x["name"])
    total = len(items)
    start = (max(page, 1) - 1) * max(page_size, 1)
    return {
        "items": items[start : start + max(page_size, 1)],
        "total": total,
        "page": max(page, 1),
        "page_size": max(page_size, 1),
    }


def get_detail(dish_id: str) -> dict | None:
    """菜谱详情：SQLite 完整内容（与数据源 md 一致，§2.2）+ 图片（§12.5）。"""
    with Session(get_engine()) as session:
        m = session.get(DishMeta, dish_id)
        if m is None:
            return None
        summary = _meta_to_summary(m)
        main_ingredients = json_load(m.main_ingredients, [])
        content = json_load(m.content, {}) or {}
        images = json_load(m.images, [])

    return {
        **summary,
        "path": m.path,
        "intro": m.intro,
        "main_ingredients": main_ingredients,
        "ingredients": content.get("required_raw") or main_ingredients,
        "optional_ingredients": content.get("optional_raw") or [],
        "calculation": content.get("calculation_raw"),
        "steps": content.get("steps") or [],
        "notes": content.get("notes"),
        "image": m.image,
        "images": images,
    }


def dish_names() -> list[dict]:
    """全量菜名映射（菜名 -> dish_id，§10 正文菜名链接化；轻量，无分页，357 条）。"""
    with Session(get_engine()) as session:
        rows = session.exec(select(DishMeta)).all()
    return [{"name": r.name, "dish_id": r.dish_id} for r in rows]


def hot_dishes(*, limit: int = 12) -> list[dict]:
    """热门菜谱（§8.3）：最近 30 天行为按权重 + 时间衰减聚合；无行为时按入库序兜底。"""
    with Session(get_engine()) as session:
        rows = session.exec(select(DishMeta)).all()
        meta = {m.dish_id: m for m in rows}

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=_HOT_WINDOW_DAYS)
        feedbacks = session.exec(
            select(UserFeedback).where(UserFeedback.created_at >= cutoff)
        ).all()

    if feedbacks:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        scores: dict[str, float] = {}
        for f in feedbacks:
            w = _ACTION_WEIGHT.get(f.action, 0)
            if w == 0 or f.dish_id not in meta:
                continue
            delta_days = max((now - f.created_at).total_seconds() / 86400, 0.0)
            scores[f.dish_id] = scores.get(f.dish_id, 0.0) + w * math.exp(-delta_days / _HOT_WINDOW_DAYS)
        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        items = [_meta_to_summary(meta[did]) for did, _ in ordered if did in meta]
        if items:
            return items

    # 兜底：无行为数据时返回前 limit 条（§8.3 冷启动）
    return [_meta_to_summary(m) for m in rows[:limit]]


def get_related(dish_id: str, *, limit: int = 12) -> list[dict]:
    """相关菜（§4.1 RELATED_TO 同主料扩散）；图不可用时按同分类降级。"""
    try:
        neo4j = build_graph_store(get_settings())
        try:
            rows = neo4j.run(
                """
                MATCH (d:Dish {id:$id})-[:RELATED_TO]->(r:Dish)
                RETURN r.id AS dish_id, r.name AS name, r.category AS category,
                       r.difficulty AS difficulty, r.time_est AS time_est
                LIMIT $limit
                """,
                id=dish_id, limit=limit,
            )
            if rows:
                return [dict(r) for r in rows]
        finally:
            neo4j.close()
    except Exception:  # noqa: BLE001 —— 图降级
        pass

    # 降级：同分类推荐（§7.3）
    with Session(get_engine()) as session:
        m = session.get(DishMeta, dish_id)
        if m is None:
            return []
        same = session.exec(
            select(DishMeta).where(DishMeta.category == m.category, DishMeta.dish_id != dish_id).limit(limit)
        ).all()
        return [_meta_to_summary(r) for r in same]
