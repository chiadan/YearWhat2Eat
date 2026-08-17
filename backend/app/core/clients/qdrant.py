"""Qdrant 向量库实现（§4.2 / §4.4）：集合创建（含 payload 索引/HNSW）、写入、检索原语。

实现 VectorStoreClient 接口（app/core/clients/base.py），经 build_vector_store 工厂按
settings.vector_store_provider 选择（§12 存储可替换：qdrant | milvus | ...）。
"""
from __future__ import annotations

from typing import Any, Sequence

from app.core.clients.base import VectorStoreClient
from app.core.config import Settings


class QdrantClient(VectorStoreClient):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient as _QdrantClient
            from qdrant_client.http import models

            self._models = models
            # Lite 模式（§12 M6 部署）：qdrant_local_path 非空 -> 本地文件嵌入（无需服务器）；
            # 否则连接远程服务（企业级/开发）
            if self.settings.qdrant_local_path:
                self._client = _QdrantClient(path=self.settings.qdrant_local_path)
            else:
                self._client = _QdrantClient(url=self.settings.qdrant_url)
        return self._client

    # ── 集合管理（§4.4 分片与容量策略） ──────────────────
    def ensure_collection(
        self,
        name: str,
        *,
        vector_size: int,
        payload_indexes: list[tuple[str, str]] | None = None,
        shard_number: int = 1,
        replicas: int = 1,
    ) -> None:
        """单节点单分片（当前最优，§4.4）；扩展时重建集合并调大 shard_number。"""
        client = self.client  # 先触发初始化（含 _models）
        models = self._models
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                    hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
                ),
                shard_number=shard_number,
                replication_factor=replicas,
            )
            for field, field_type in payload_indexes or []:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD
                    if field_type == "keyword"
                    else models.PayloadSchemaType.INTEGER,
                )

    def upsert_points(self, collection: str, points: list[dict], batch_size: int = 500) -> None:
        """points: [{id, vector, payload}]；分批上传避免单请求 payload 超限（33MB）。"""
        if not points:
            return
        client = self.client  # 先触发初始化（含 _models）
        models = self._models
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            client.upsert(
                collection_name=collection,
                points=[
                    models.PointStruct(id=p["id"], vector=p["vector"], payload=p.get("payload") or {})
                    for p in batch
                ],
            )

    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int = 10,
        score_threshold: float | None = None,
        payload_filter: dict | None = None,
    ) -> list[dict]:
        client = self.client  # 先触发初始化（含 _models）
        models = self._models
        flt = models.Filter(**payload_filter) if payload_filter else None
        hits = client.search(
            collection_name=collection,
            query_vector=vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=flt,
        )
        return [{"id": h.id, "score": h.score, "payload": h.payload} for h in hits]

    def count(self, collection: str) -> int:
        return self.client.count(collection_name=collection).count

    def scroll(
        self,
        collection: str,
        *,
        payload_filter: dict | None = None,
        limit: int = 10,
    ) -> list[dict]:
        client = self.client  # 先触发初始化（含 _models）
        models = self._models
        flt = models.Filter(**payload_filter) if payload_filter else None
        hits, _next = client.scroll(
            collection_name=collection,
            scroll_filter=flt,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [{"id": h.id, "payload": h.payload} for h in hits]

    def collection_exists(self, name: str) -> bool:
        return self.client.collection_exists(name)

    def delete_collection(self, name: str) -> None:
        self.client.delete_collection(collection_name=name)

    def health(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False
