"""向量检索器（§6.5 召回①）：Qdrant 三集合 cosine 检索，得分阈值 ≥0.35。

- dish_qa  -> 优先 chunks（步骤级） + dishes（菜名级）
- tips_qa  -> tips
- recommend -> dishes
- 通用兜底 -> 三集合都查
- embedding 走 core.clients（本地 sentence-transformers，§12.4）
"""
from __future__ import annotations

import asyncio

from app.core.clients.embedding import EmbeddingClient
from app.core.clients.factory import build_vector_store
from app.core.clients.base import GraphStoreClient, VectorStoreClient
from app.core.config import Settings

SCORE_THRESHOLD = 0.35  # §6.5：低于视为不相关


class VectorRetriever:
    def __init__(self, qdrant: VectorStoreClient, embedding: EmbeddingClient, settings: Settings):
        self.qdrant = qdrant
        self.embedding = embedding
        self.settings = settings

    def _collections_for_intent(self, intent: str) -> list[str]:
        if intent == "dish_qa":
            return [self.settings.collection_chunks, self.settings.collection_dishes]
        if intent == "tips_qa":
            return [self.settings.collection_tips]
        if intent == "recommend":
            return [self.settings.collection_dishes]
        return [self.settings.collection_dishes, self.settings.collection_chunks, self.settings.collection_tips]

    async def retrieve(self, query: str, top_k: int = 10, intent: str = "dish_qa") -> list[dict]:
        vector = (await asyncio.to_thread(self.embedding.encode, [query]))[0]
        collections = self._collections_for_intent(intent)
        per_collection = max(top_k, 30) if intent == "dish_qa" else top_k
        # 推荐意图是"需求描述"（无菜名实体），语义匹配天然偏低——放宽阈值扩大召回，
        # 质量交给 rerank + rule 路约束匹配兜底（§6.5）
        threshold = 0.2 if intent == "recommend" else SCORE_THRESHOLD

        results: list[dict] = []
        for name in collections:
            hits = await asyncio.to_thread(
                self.qdrant.search,
                name,
                vector,
                top_k=per_collection,
                score_threshold=threshold,
            )
            for h in hits:
                payload = h.get("payload") or {}
                results.append(
                    {
                        "id": h["id"],
                        "score": h["score"],
                        "payload": payload,
                        "source": name,  # dishes | chunks | tips
                    }
                )

        # 按相似度降序
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[: max(top_k * 3, 30)]
