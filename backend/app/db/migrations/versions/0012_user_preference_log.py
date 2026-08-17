"""user_profiles 增加 preference_log（§8.5 对话偏好提取来源日志）。

JSON 字段：默认 '[]'，SQLite 存 TEXT、PostgreSQL 存 JSON 类型（同 avoid_list/tools 惯例）。
SQLite 直接 ADD COLUMN 即可（带默认值）；PG 用 JSON 类型列。

Revision ID: 0012
Revises: 0011
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    col_type = sa.JSON() if dialect == "postgresql" else sa.Text()
    op.add_column(
        "user_profiles",
        sa.Column("preference_log", col_type, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "preference_log")
