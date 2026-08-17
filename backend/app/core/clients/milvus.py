"""Milvus 向量库实现（§12 存储可替换）：pymilvus 适配 VectorStoreClient 接口。

依赖：pymilvus（requirements.txt 已锁定）；连接参数：settings.milvus_uri（如
http://localhost:19530）与 milvus_token（可选）。

注：Milvus 的 payload 过滤语法与 Qdrant 不同（expr 字符串），本实现把接口的
payload_filter（Qdrant Filter dict）映射为 Milvus expr——当前仅支持
"field == value" 与 "field in [..]" 两种最常用形式，复杂过滤按需扩展。
"""
from __future__ import annotations

from typing import Any

from app.core.clients.base import VectorStoreClient
from app.core.config import Settings


class MilvusVectorStore(VectorStoreClient):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._connected = False

    def _connect(self):
        if self._connected:
            return
        from pymilvus import connections

        connections.connect(
            alias="default",
            uri=self.settings.milvus_uri,
            token=self.settings.milvus_token or None,
        )
        self._connected = True

    @staticmethod
    def _expr_from_filter(payload_filter: dict | None) -> str:
        """Qdrant Filter dict -> Milvus expr（支持 must 单层: field==value / field in [...]）。"""
        if not payload_filter:
            return ""
        parts: list[str] = []
        for cond in payload_filter.get("must") or []:
            key = cond.get("key", "")
            m = cond.get("match") or {}
            if "value" in m:
                v = m["value"]
                parts.append(f"{key} == {v!r}" if isinstance(v, str) else f"{key} == {v}")
            else:
                vals = m.get("values") or []
                parts.append(f"{key} in {list(vals)!r}")
        return " and ".join(parts)

    # ── VectorStoreClient ─────────────────────────────────
    def ensure_collection(
        self,
        name: str,
        *,
        vector_size: int,
        payload_indexes: list[tuple[str, str]] | None = None,
    ) -> None:
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

        self._connect()
        if utility.has_collection(name):
            return
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=False),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=vector_size),
            FieldSchema(name="payload", dtype=DataType.JSON),
        ]
        schema = CollectionSchema(fields, description=name)
        collection = Collection(name, schema, consistency_level="Bounded")
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection.create_index("vector", index_params)
        # payload 字段建索引（keyword -> VARCHAR；integer -> INT64）
        for field, field_type in payload_indexes or []:
            dtype = DataType.VARCHAR if field_type == "keyword" else DataType.INT64
            max_len = 256 if dtype == DataType.VARCHAR else None
            try:
                collection.create_index(
                    field,
                    {
                        "index_type": "INVERTED" if dtype == DataType.VARCHAR else "STL_SORT",
                        "params": {"max_length": max_len} if max_len else {},
                    },
                )
            except Exception:  # noqa: BLE001 —— payload 索引失败不阻塞写入
                pass

    def upsert_points(self, collection: str, points: list[dict], batch_size: int = 500) -> None:
        if not points:
            return
        from pymilvus import Collection

        self._connect()
        col = Collection(collection)
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            col.upsert(
                [
                    [p["id"] for p in batch],
                    [p["vector"] for p in batch],
                    [p.get("payload") or {} for p in batch],
                ]
            )
        col.flush()

    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int = 10,
        score_threshold: float | None = None,
        payload_filter: dict | None = None,
    ) -> list[dict]:
        from pymilvus import Collection

        self._connect()
        col = Collection(collection)
        col.load()
        expr = self._expr_from_filter(payload_filter)
        results = col.search(
            data=[vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=expr or None,
            output_fields=["payload"],
        )
        hits = []
        for hit in results[0]:
            score = hit.distance
            if score_threshold is not None and score < score_threshold:
                continue
            hits.append({"id": hit.id, "score": score, "payload": hit.entity.get("payload") or {}})
        return hits

    def scroll(
        self,
        collection: str,
        *,
        payload_filter: dict | None = None,
        limit: int = 10,
    ) -> list[dict]:
        from pymilvus import Collection

        self._connect()
        col = Collection(collection)
        col.load()
        expr = self._expr_from_filter(payload_filter)
        results = col.query(expr=expr or None, output_fields=["id", "payload"], limit=limit)
        return [{"id": r["id"], "payload": r.get("payload") or {}} for r in results]

    def count(self, collection: str) -> int:
        from pymilvus import Collection

        self._connect()
        return Collection(collection).num_entities

    def collection_exists(self, name: str) -> bool:
        from pymilvus import utility

        self._connect()
        return utility.has_collection(name)

    def delete_collection(self, name: str) -> None:
        from pymilvus import utility

        self._connect()
        utility.drop_collection(name)

    def health(self) -> bool:
        try:
            from pymilvus import utility

            self._connect()
            utility.list_collections()
            return True
        except Exception:  # noqa: BLE001
            return False
