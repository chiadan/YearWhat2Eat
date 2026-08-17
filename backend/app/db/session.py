"""数据库会话管理（§4.3 / §12 存储可替换）：关系型统一入口。

- 默认 SQLite：WAL 模式 + 外键 + 启动自动迁移
- 可替换 PostgreSQL 等：settings.database_url 填 SQLAlchemy URL 即切换
  （如 postgresql+psycopg2://user:pass@host:5432/db，需 pip install psycopg2-binary；
  表结构经 alembic 迁移，JSON 列 SQLAlchemy 自动映射 JSON/JSONB）
- 写操作由调用方串行化（单写者队列 / asyncio.Lock，§4.3）
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.core.config import get_settings

_engine: Engine | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - 事件回调
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine() -> Engine:
    """关系型引擎：database_url 优先（PG 等），否则默认 SQLite（§12 存储可替换）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url.strip()
        if url:
            # 用户显式指定 SQLAlchemy URL（postgresql+psycopg2://...）
            _engine = create_engine(url, pool_pre_ping=True)
        else:
            settings.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(
                f"sqlite:///{settings.sqlite_file}",
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
            event.listen(_engine, "connect", _sqlite_pragmas)
    return _engine


def database_url() -> str:
    """当前数据库 URL（供 alembic 迁移同步，§12）。"""
    settings = get_settings()
    url = settings.database_url.strip()
    if url:
        return url
    return f"sqlite:///{settings.sqlite_file}"


def run_migrations() -> None:
    """程序化执行 alembic 迁移（§4.3：启动自动应用未应用迁移）。"""
    from alembic import command
    from alembic.config import Config

    from app.core.config import PROJECT_ROOT

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url())
    command.upgrade(cfg, "head")


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def create_tables_direct() -> None:  # 仅测试用（测试环境不走 alembic）
    from app.db import models as _models  # noqa: F401  确保注册

    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(get_engine())
