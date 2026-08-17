"""chat_sessions 增加 group 分组列（§16 决策 17 会话分组：NULL=默认分组，分组为派生字段无独立表）。

Revision ID: 0009
Revises: 0008
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("group", sa.String(length=40), nullable=True))
    op.create_index("ix_chat_sessions_group", "chat_sessions", ["group"])


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_group", table_name="chat_sessions")
    op.drop_column("chat_sessions", "group")
