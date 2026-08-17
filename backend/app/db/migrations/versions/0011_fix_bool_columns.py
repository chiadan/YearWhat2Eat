"""bool 字段统一为 Boolean 类型（§4.3 跨方言修复：SQLite 存 INTEGER 0/1，PostgreSQL 原生 BOOLEAN）。

此前 revoked/archived/title_auto/hidden 硬编码 Integer——SQLite 侥幸可用，
PG 下插入 Python bool 报 DatatypeMismatch。
方言差异：PG 需先 DROP DEFAULT 再 ALTER TYPE（USING 显式转换）再 SET DEFAULT false；
SQLite 无 ALTER TYPE，用 batch 重建表（Boolean 在 SQLite 即 0/1）。

Revision ID: 0011
Revises: 0010
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BOOL_COLUMNS = [
    ("refresh_tokens", "revoked"),
    ("chat_sessions", "archived"),
    ("chat_sessions", "title_auto"),
    ("chat_messages", "hidden"),
]


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _pg_alter(table: str, column: str, to_bool: bool) -> None:
    """PG：先删默认值 -> ALTER TYPE（USING 显式转换）-> 设新默认值。"""
    op.execute(f'ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT')
    if to_bool:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN {column} TYPE BOOLEAN USING {column}::boolean')
        op.execute(f'ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT false')
    else:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN {column} TYPE INTEGER USING ({column}::int)')
        op.execute(f'ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT 0')


def upgrade() -> None:
    for table, column in _BOOL_COLUMNS:
        if _is_pg():
            _pg_alter(table, column, to_bool=True)
        else:
            # SQLite：batch 重建表（Boolean 存 0/1，兼容现有数据）
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    column,
                    type_=sa.Boolean(),
                    existing_type=sa.Integer(),
                    existing_nullable=False,
                    server_default=sa.text("0"),
                )


def downgrade() -> None:
    for table, column in _BOOL_COLUMNS:
        if _is_pg():
            _pg_alter(table, column, to_bool=False)
        else:
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    column,
                    type_=sa.Integer(),
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                    server_default=sa.text("0"),
                )
