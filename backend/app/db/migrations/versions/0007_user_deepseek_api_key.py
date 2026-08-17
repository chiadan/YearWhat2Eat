"""users 增加 BYOK 加密 Key 列（§10：用户自定义 DeepSeek API Key，Fernet 加密存储）。

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deepseek_api_key_enc", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "deepseek_api_key_enc")
