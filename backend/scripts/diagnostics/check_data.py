# -*- coding: utf-8 -*-
"""数据完整性检查（诊断工具，§12.5/§5）：dish_meta 图片覆盖 / md 链接残留 / content 完整性 / ingest_runs 日志。

用法：
    python scripts/diagnostics/check_data.py

输出为面向人的验收报告（scripts/ 允许 print，AGENTS.md 约束 11）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import get_settings
from app.db.json_utils import json_load
from app.db.models import ChatSession, DishMeta, IngestRun
from app.db.session import get_engine
from sqlmodel import Session, select


def main() -> None:
    settings = get_settings()
    print(f"SQLite: {settings.sqlite_file}")
    print("=" * 60)
    with Session(get_engine()) as session:
        metas = session.exec(select(DishMeta)).all()
        print(f"dish_meta 总数: {len(metas)}（期望 357）")
        with_img = sum(1 for m in metas if m.image)
        print(f"有主图: {with_img}（数据源有图菜约 170 道；文件数 332）")
        bad = [m.dish_id for m in metas if m.image and ("http" in m.image or "![" in m.image or "./" in m.image)]
        print(f"md 链接残留: {len(bad)}（应为 0）")
        if bad:
            print("  残留样例:", [m.image for m in metas if m.dish_id in bad[:3]])
        no_content = [m.dish_id for m in metas if not json_load(m.content, {})]
        print(f"content 为空: {len(no_content)}（应为 0）")
        empty_tags = [m.dish_id for m in metas if not (json_load(m.tags, {}) or {}).get("cuisines")]
        print(f"标签为空（cuisines）: {len(empty_tags)}（打标后应为 0）")

        print("-" * 60)
        runs = session.exec(select(IngestRun).order_by(IngestRun.id.desc()).limit(3)).all()
        for r in runs:
            status = getattr(r, "status", "?")
            print(f"ingest_runs #{getattr(r, 'id', '?')} status={status}")
            log = (getattr(r, "log", "") or "")
            for line in log.splitlines()[-6:]:
                print(f"  | {line}")

        print("-" * 60)
        sessions = session.exec(select(ChatSession)).all()
        print(f"会话总数: {len(sessions)}")


if __name__ == "__main__":
    main()
