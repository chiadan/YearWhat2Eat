"""users 增加 ai_providers JSON 列（§10 多 Provider：OpenAI 兼容 / Anthropic 自定义接入）。

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ai_providers", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ai_providers")
