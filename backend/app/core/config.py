"""全局配置：pydantic-settings 读取 .env（§12.2）。

约定：所有配置键与 backend/.env.example 一一对应；新增配置需同步两处。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── DeepSeek（§7.3） ──────────────────────────────
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_timeout: float = 30.0
    llm_max_retries: int = 2
    llm_temperature_struct: float = 0.1
    llm_temperature_gen: float = 0.7
    llm_max_tokens: int = 2048
    llm_concurrency: int = 8
    max_tool_rounds: int = 5

    # ── Embedding / Reranker（§7.1 / §12.4） ──────────
    embedding_provider: str = "local"          # local | siliconflow
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "auto"             # auto | cuda | cpu
    embedding_cache_dir: str = "./models"
    embedding_dim: int = 512

    reranker_provider: str = "local"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "auto"
    reranker_cache_dir: str = "./models"

    # ── Neo4j / Kùzu / 可替换存储（§12 存储可替换） ──
    # 图库：neo4j（默认）| kuzu（嵌入式，langchain-kuzu 集成、Cypher 兼容）
    graph_store_provider: str = "neo4j"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"
    kuzu_db_path: str = "./data/kuzu"      # graph_store_provider=kuzu：嵌入式存储目录
    # 向量库：qdrant | milvus（继承 VectorStoreClient 注册）
    vector_store_provider: str = "qdrant"
    qdrant_url: str = "http://localhost:6333"
    # Lite 模式（§12 M6 部署）：非空 = Qdrant 本地文件嵌入（QdrantClient(path=...)，无需服务器）
    qdrant_local_path: str = ""
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""

    # ── 关系型数据库（§12 存储可替换） ─────────────────
    # 空 = 默认 SQLite（sqlite_path）；填 SQLAlchemy URL 即切换，如
    # postgresql+psycopg2://user:pass@localhost:5432/yeahwhat2eat（需 pip install psycopg2-binary）
    database_url: str = ""

    # ── SQLite ───────────────────────────────────────
    sqlite_path: str = "./data/yeahwhat2eat.db"

    # ── 数据源（ETL，只读） ──────────────────────────
    data_source_dir: str = "../data/HowToCook-1.6.0"

    # ── 检索参数（§6.5） ─────────────────────────────
    # 对话偏好提取（§8.5）：聊天结束后 LLM 提取偏好信号写画像；false 关闭（节省调用）
    preference_extract_enabled: bool = True
    retrieve_top_k: int = 30
    rerank_top_k: int = 15
    collection_dishes: str = "dishes"
    collection_chunks: str = "chunks"
    collection_tips: str = "tips"

    # ── 缓存（§9.3） ─────────────────────────────────
    cache_enabled: bool = True
    cache_answer_ttl: int = 1800
    cache_retrieve_ttl: int = 600

    # ── 认证与安全（§9.2 / §12.6） ───────────────────
    jwt_secret: str = "change-me-to-random-32+bytes"
    jwt_access_ttl: int = 7200
    jwt_refresh_ttl: int = 604800
    admin_token: str = "change-me-admin-token"
    rate_limit_chat: str = "10/minute"
    rate_limit_login: str = "5/minute"
    max_input_length: int = 2000

    # ── 服务 ─────────────────────────────────────────
    app_env: str = "dev"                       # dev | prod
    log_level: str = "INFO"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # ── 派生属性 ─────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_file(self) -> Path:
        p = Path(self.sqlite_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def data_source_root(self) -> Path:
        p = Path(self.data_source_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def embedding_cache(self) -> Path:
        p = Path(self.embedding_cache_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def reranker_cache(self) -> Path:
        p = Path(self.reranker_cache_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
