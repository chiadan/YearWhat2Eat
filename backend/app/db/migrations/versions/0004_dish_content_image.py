"""dish_meta 增加完整内容与图片字段（§4.3 扩展）：content / image / images。

- content: 与数据源 md 一致的完整结构化内容（required_raw/optional_raw/calculation_raw/steps/notes）
- image: 主图相对路径（/static/dishes/{image} 访问，§12.5 静态托管）
- images: 同目录全部图片相对路径

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dish_meta", sa.Column("content", sa.JSON(), nullable=True))
    op.add_column("dish_meta", sa.Column("image", sa.String(256), nullable=True))
    op.add_column("dish_meta", sa.Column("images", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("dish_meta", "images")
    op.drop_column("dish_meta", "image")
    op.drop_column("dish_meta", "content")
