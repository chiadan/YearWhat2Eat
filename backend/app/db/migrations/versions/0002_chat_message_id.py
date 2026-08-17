"""chat_messages 增加 message_id 列（SSE 幂等去重，§9.1 要点 7）

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("message_id", sa.String(64), nullable=True))
    op.create_index("ix_chat_messages_message_id", "chat_messages", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_message_id", table_name="chat_messages")
    op.drop_column("chat_messages", "message_id")
