"""alembic 环境：元数据来自 app.db.models（SQLModel.metadata），URL 来自 settings。"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import context
from sqlmodel import SQLModel

# 确保 backend/ 在 sys.path（直接运行 alembic 命令时）
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import get_settings  # noqa: E402
from app.db import models as _models  # noqa: F401,E402  # 注册全部表
from app.db.session import database_url  # noqa: E402

config = context.config
# 注意：不用 alembic.ini 的 logging 配置（fileConfig 会覆盖应用日志级别，
# 导致 ETL 的 Step1~Step5 进度日志被 WARNING 压制）；日志统一由 app.core.logging 管理。

# 数据库 URL：settings.database_url 优先（PG 等），否则默认 SQLite（§12 存储可替换）
config.set_main_option("sqlalchemy.url", database_url())
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from app.db.session import get_engine

    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
