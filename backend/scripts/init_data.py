# -*- coding: utf-8 -*-
"""容器数据初始化（§12 M6 部署）：dish_meta 为空时自动执行 ETL。

- 有 tags_backup.json（此前打标结果）-> skip_tag 秒级重建（SQLite + 向量 + 图谱）
- 无备份 -> 完整 ETL（LLM 打标，需 DEEPSEEK_API_KEY）
- dish_meta 已有数据 -> 跳过（幂等）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.models import DishMeta
from app.db.session import get_engine
from app.pipeline import runner
from sqlmodel import Session, select


def main() -> None:
    settings = get_settings()
    with Session(get_engine()) as session:
        count = len(session.exec(select(DishMeta)).all())
    if count > 0:
        print("[init_data] dish_meta 已有数据，跳过 ETL")
        return
    backup = settings.sqlite_file.parent / "tags_backup.json"
    skip_tag = backup.exists()
    print(f"[init_data] dish_meta 为空，执行 ETL（skip_tag={skip_tag}）")
    asyncio.run(runner.run_ingest(force=True, skip_tag=skip_tag))


if __name__ == "__main__":
    main()
