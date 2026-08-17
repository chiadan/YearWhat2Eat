"""存储工厂（§12 存储可替换）：按 settings.provider 返回向量库/图库实现。

新数据库接入：
  1. 继承 app/core/clients/base.py 的 VectorStoreClient / GraphStoreClient 接口
  2. 在下方 _VECTOR_STORES / _GRAPH_STORES 注册 provider 名
  3. .env 配置 provider 名即切换，业务层零改动
"""
from __future__ import annotations

from app.core.clients.base import GraphStoreClient, VectorStoreClient
from app.core.config import Settings


def build_vector_store(settings: Settings) -> VectorStoreClient:
    """向量库工厂：qdrant（默认）| milvus | 自定义注册实现。"""
    provider = settings.vector_store_provider
    if provider == "qdrant":
        from app.core.clients.qdrant import QdrantClient

        return QdrantClient(settings)
    if provider == "milvus":
        from app.core.clients.milvus import MilvusVectorStore

        return MilvusVectorStore(settings)
    raise ValueError(
        f"未知向量库 provider={provider!r}（支持: qdrant, milvus；自定义请继承 VectorStoreClient 并注册）"
    )


def build_graph_store(settings: Settings) -> GraphStoreClient:
    """图库工厂：neo4j（默认）| kuzu（嵌入式，langchain-kuzu 集成、Cypher 兼容）| 自定义。"""
    provider = settings.graph_store_provider
    if provider == "neo4j":
        from app.core.clients.neo4j import Neo4jClient

        return Neo4jClient(settings)
    if provider == "kuzu":
        from app.core.clients.kuzu import KuzuGraphStore

        return KuzuGraphStore(settings)
    raise ValueError(
        f"未知图库 provider={provider!r}（支持: neo4j, kuzu；自定义请继承 GraphStoreClient 并注册）"
    )
