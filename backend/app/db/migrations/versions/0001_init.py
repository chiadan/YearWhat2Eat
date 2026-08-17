"""初始建表：§4.3 全部 11 张表（与 app/db/models.py 一一对应）

Revision ID: 0001
Revises:
Create Date: 2025-01-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("flavor_spicy", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("flavor_sweet", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("flavor_sour", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("flavor_light", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("avoid_list", sa.JSON(), nullable=False),
        sa.Column("diet_type", sa.String(32), nullable=False, server_default="无限制"),
        sa.Column("skill_level", sa.String(16), nullable=False, server_default="新手"),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("family_size", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("budget_level", sa.String(16), nullable=False, server_default="中等"),
        sa.Column("goal", sa.String(16), nullable=False, server_default="均衡"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "dish_meta",
        sa.Column("dish_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("path", sa.String(256), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("intro", sa.Text(), nullable=True),
        sa.Column("time_est", sa.Integer(), nullable=True),
        sa.Column("main_ingredients", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("vector_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dish_meta_name", "dish_meta", ["name"])
    op.create_index("ix_dish_meta_category", "dish_meta", ["category"])

    op.create_table(
        "user_favorites",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "dish_id", name="uq_fav_user_dish"),
    )
    op.create_index("ix_user_favorites_user_id", "user_favorites", ["user_id"])
    op.create_index("ix_user_favorites_dish_id", "user_favorites", ["dish_id"])

    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_feedback_user_id", "user_feedback", ["user_id"])
    op.create_index("ix_user_feedback_dish_id", "user_feedback", ["dish_id"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(128), nullable=False, server_default="新会话"),
        sa.Column("summary", sa.String(4096), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.String(16384), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "answer_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("answer", sa.String(16384), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_answer_cache_user_id", "answer_cache", ["user_id"])
    op.create_index("ix_answer_cache_expires_at", "answer_cache", ["expires_at"])

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("node", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])

    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("dish_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("log", sa.String(8192), nullable=False, server_default=""),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="1"),
    )
    op.create_index("ix_ingest_runs_status", "ingest_runs", ["status"])


def downgrade() -> None:
    for table in (
        "users",
        "refresh_tokens",
        "user_profiles",
        "dish_meta",
        "user_favorites",
        "user_feedback",
        "chat_sessions",
        "chat_messages",
        "answer_cache",
        "llm_usage",
        "ingest_runs",
    ):
        op.drop_table(table)
