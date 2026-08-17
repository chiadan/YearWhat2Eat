"""SQLite 表模型（§4.3）。

- 业务真源（唯一需备份），Neo4j/Qdrant 均可由 ETL 重建
- 表结构演进走 alembic（app/db/migrations/），禁止手改库
- dish_id = 相对路径 sha1 前 12 位（§2.2 同名菜冲突）
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int = Field(primary_key=True)
    username: str = Field(sa_column=Column(String(64), unique=True, index=True, nullable=False))
    password_hash: str = Field(sa_column=Column(String(128), nullable=False))
    role: str = Field(default="user", sa_column=Column(String(16), nullable=False))  # user | admin
    token_version: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))  # §9.2 失效联动
    # BYOK（§10）：用户自定义 DeepSeek Key 的 Fernet 密文；NULL = 使用系统 .env Key
    deepseek_api_key_enc: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    # 多 Provider（§10）：自定义接入配置列表 [{name, provider_type, base_url, api_key_enc, models}]（JSON）
    ai_providers: str | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: int = Field(primary_key=True)
    user_id: int = Field(sa_column=Column(Integer, index=True, nullable=False))
    token_hash: str = Field(sa_column=Column(String(128), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    revoked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class UserProfile(SQLModel, table=True):
    """画像（§8.1）：1~5 口味维度；JSON 字段存文本。"""

    __tablename__ = "user_profiles"

    user_id: int = Field(sa_column=Column(Integer, primary_key=True, nullable=False))
    flavor_spicy: int = Field(default=3)
    flavor_sweet: int = Field(default=3)
    flavor_sour: int = Field(default=3)
    flavor_light: int = Field(default=3)
    avoid_list: str = Field(default="[]", sa_column=Column(JSON, nullable=False))
    diet_type: str = Field(default="无限制")          # 无限制 | 素食 | 减脂 | 清真
    skill_level: str = Field(default="新手")          # 新手 | 进阶 | 熟练
    tools: str = Field(default="[]", sa_column=Column(JSON, nullable=False))
    family_size: int = Field(default=2)
    budget_level: str = Field(default="中等")
    goal: str = Field(default="均衡")                 # 快手 | 省事 | 大餐 | 健康
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class DishMeta(SQLModel, table=True):
    """菜谱元数据镜像（SQLite 真源之一，ETL 写入）。"""

    __tablename__ = "dish_meta"

    dish_id: str = Field(sa_column=Column(String(32), primary_key=True, nullable=False))  # 路径 hash
    name: str = Field(sa_column=Column(String(128), index=True, nullable=False))
    category: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    path: str = Field(sa_column=Column(String(256), nullable=False))
    difficulty: int | None = Field(default=None)      # 1~5 星
    intro: str | None = Field(default=None)
    time_est: int | None = Field(default=None)        # 分钟（LLM 打标）
    main_ingredients: str = Field(default="[]", sa_column=Column(JSON, nullable=False))
    tags: str = Field(default="{}", sa_column=Column(JSON, nullable=False))  # cuisines/flavors/techniques
    # 完整内容（与数据源 md 一致，§2.2 章节结构；ETL 写入）
    content: str | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # 图片（相对 dishes/ 的路径，经 /static/dishes 托管，§12.5）
    image: str | None = Field(default=None, sa_column=Column(String(256), nullable=True))
    images: str = Field(default="[]", sa_column=Column(JSON, nullable=False))
    vector_status: str = Field(default="pending", sa_column=Column(String(16), nullable=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class UserFavorite(SQLModel, table=True):
    __tablename__ = "user_favorites"
    __table_args__ = (UniqueConstraint("user_id", "dish_id", name="uq_fav_user_dish"),)

    id: int = Field(primary_key=True)
    user_id: int = Field(sa_column=Column(Integer, index=True, nullable=False))
    dish_id: str = Field(sa_column=Column(String(32), index=True, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class UserFeedback(SQLModel, table=True):
    """行为流水（§8.2）：view/like/dislike/rating/made，画像聚合的唯一输入。"""

    __tablename__ = "user_feedback"

    id: int = Field(primary_key=True)
    user_id: int = Field(sa_column=Column(Integer, index=True, nullable=False))
    dish_id: str = Field(sa_column=Column(String(32), index=True, nullable=False))
    action: str = Field(sa_column=Column(String(16), nullable=False))  # view|like|dislike|rating|made
    rating: int | None = Field(default=None)          # 1~5，action=rating 时有效
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    id: int = Field(primary_key=True)
    user_id: int = Field(sa_column=Column(Integer, index=True, nullable=False))
    title: str = Field(default="新会话")
    # title_auto=1：标题由 AI 自动总结并可自动更新；手动改名后置 0 不再覆盖（§9）
    title_auto: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, default=True))
    summary: str = Field(default="", sa_column=Column(String(4096), nullable=False))  # 滚动摘要（§6.2）
    archived: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))  # 归档对话（§9）
    # 会话分组（§16 决策 17）：NULL = 默认分组；分组为派生字段，无独立表
    group: str | None = Field(default=None, sa_column=Column(String(40), index=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: int = Field(primary_key=True)
    session_id: int = Field(sa_column=Column(Integer, index=True, nullable=False))
    role: str = Field(sa_column=Column(String(16), nullable=False))  # user | assistant
    content: str = Field(sa_column=Column(String(16384), nullable=False))
    sources: str = Field(default="[]", sa_column=Column(JSON, nullable=False))
    message_id: str | None = Field(default=None, sa_column=Column(String(64), index=True))  # SSE 幂等（§9.1）
    # 软删除（§9 删除单轮问答）：1=聊天界面隐藏（user+assistant 成对），历史数据保留
    hidden: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class AnswerCache(SQLModel, table=True):
    """问答缓存（§9.3），多进程共享。"""

    __tablename__ = "answer_cache"

    cache_key: str = Field(sa_column=Column(String(64), primary_key=True, nullable=False))
    user_id: int | None = Field(default=None, sa_column=Column(Integer, index=True))
    answer: str = Field(sa_column=Column(String(16384), nullable=False))
    sources: str = Field(default="[]", sa_column=Column(JSON, nullable=False))
    plan: str = Field(default="{}", sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, index=True, nullable=False))


class LLMUsage(SQLModel, table=True):
    """LLM 成本统计（§7）：每次调用一行，每日聚合成本报表。"""

    __tablename__ = "llm_usage"

    id: int = Field(primary_key=True)
    user_id: int | None = Field(default=None, sa_column=Column(Integer, index=True))
    session_id: int | None = Field(default=None)
    node: str = Field(default="", sa_column=Column(String(64), nullable=False))  # tagger/intent/...
    model: str = Field(default="", sa_column=Column(String(64), nullable=False))
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, index=True, nullable=False))


class IngestRun(SQLModel, table=True):
    """ETL 运行记录（§5）：状态机 running/done/failed，支持重建窗口降级与并发互斥。"""

    __tablename__ = "ingest_runs"

    id: int = Field(primary_key=True)
    started_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))
    finished_at: datetime | None = Field(default=None)
    dish_count: int = Field(default=0)
    status: str = Field(default="running", sa_column=Column(String(16), index=True, nullable=False))
    log: str = Field(default="", sa_column=Column(String(8192), nullable=False))
    schema_version: str = Field(default="1", sa_column=Column(String(16), nullable=False))
