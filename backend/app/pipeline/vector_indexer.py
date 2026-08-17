"""Qdrant 向量索引（§5 Step5 / §4.2 集合设计 / §4.4 分片策略）。

- 三集合：dishes（整菜）/ chunks（步骤块）/ tips（技巧块）
- 统一 BAAI/bge-small-zh-v1.5（512 维，cosine）；payload 索引见 §4.4
- 幂等：rebuild 先删集合再建（ETL 可重建，§3 原则）
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.clients.embedding import EmbeddingClient
from app.core.clients.factory import build_vector_store
from app.core.clients.base import GraphStoreClient, VectorStoreClient
from app.core.config import Settings
from app.pipeline.parser import DishRecord, ParsedCorpus
from app.pipeline.tagger import DishTags

DISH_PAYLOAD_INDEXES = [
    ("category", "keyword"),
    ("difficulty", "integer"),
    ("meal_type", "keyword"),
]
CHUNK_PAYLOAD_INDEXES = [
    ("dish_id", "keyword"),
    ("category", "keyword"),
]
TIPS_PAYLOAD_INDEXES = [
    ("category", "keyword"),
]


@dataclass
class VectorStats:
    dishes: int = 0
    chunks: int = 0
    tips: int = 0


def _dish_vector_text(d: DishRecord, tag: DishTags) -> str:
    steps_summary = "；".join(s.text[:80] for s in d.steps[:8])
    diff = f"{d.difficulty}/5" if d.difficulty else "未知"
    return (
        f"{d.name}。{(d.intro or '')[:200]}。难度：{diff}。"
        f"原料：{'、'.join(d.required_raw[:10])}。"
        f"标签：{'、'.join(tag.cuisines + tag.flavors + tag.techniques)}。"
        f"步骤：{steps_summary}"
    )


def _build_points(
    dishes: list[DishRecord],
    tags: dict[str, DishTags],
    corpus: ParsedCorpus,
) -> tuple[list[dict], list[dict], list[dict]]:
    dish_points: list[dict] = []
    chunk_points: list[dict] = []
    tip_points: list[dict] = []

    for d in dishes:
        tag = tags.get(d.dish_id, DishTags(dish_id=d.dish_id))
        text = _dish_vector_text(d, tag)
        dish_points.append(
            {
                "id": int(d.dish_id, 16) % (2**63),  # 稳定数值 id
                "vector": [],  # 待填充
                "payload": {
                    "dish_id": d.dish_id,
                    "name": d.name,
                    "category": d.category,
                    "difficulty": d.difficulty,
                    "cuisines": tag.cuisines,
                    "flavors": tag.flavors,
                    "techniques": tag.techniques,
                    "main_ingredients": tag.main_ingredients,
                    "meal_type": tag.meal_types,
                    "text": text,  # 原文（reranker 精排拼接用，§6.5）
                },
                "_text": text,
            }
        )
        for idx, step in enumerate(d.steps[:30]):
            step_text = f"{d.name} 步骤{idx + 1}（{step.version}）：{step.text[:500]}"
            chunk_points.append(
                {
                    "id": (int(d.dish_id, 16) * 31 + idx) % (2**63),
                    "vector": [],
                    "payload": {
                        "dish_id": d.dish_id,
                        "dish_name": d.name,
                        "chunk_type": "step",
                        "chunk_index": idx,
                        "category": d.category,
                        "text": step_text,
                    },
                    "_text": step_text,
                }
            )

    for i, tip in enumerate(corpus.tips):
        for j, chunk in enumerate(tip.chunks):
            tip_text = f"{tip.title}。{chunk[:500]}"
            tip_points.append(
                {
                    "id": (int(tip.tip_id, 16) * 17 + j) % (2**63),
                    "vector": [],
                    "payload": {
                        "tip_id": tip.tip_id,
                        "title": tip.title,
                        "category": tip.category,
                        "text": tip_text,
                    },
                    "_text": tip_text,
                }
            )

    return dish_points, chunk_points, tip_points


async def rebuild_indexes(
    client: VectorStoreClient,
    embedding: EmbeddingClient,
    settings: Settings,
    dishes: list[DishRecord],
    tags: dict[str, DishTags],
    corpus: ParsedCorpus,
    *,
    reset: bool = False,
) -> VectorStats:
    """重建三集合（reset=True 时先删集合，§4.4 扩展路径）。"""
    if reset:
        for name in (settings.collection_dishes, settings.collection_chunks, settings.collection_tips):
            # 经 VectorStoreClient 接口（§12 存储可替换：勿用实现私有属性）
            if client.collection_exists(name):
                client.delete_collection(name)

    client.ensure_collection(
        settings.collection_dishes,
        vector_size=settings.embedding_dim,
        payload_indexes=DISH_PAYLOAD_INDEXES,
    )
    client.ensure_collection(
        settings.collection_chunks,
        vector_size=settings.embedding_dim,
        payload_indexes=CHUNK_PAYLOAD_INDEXES,
    )
    client.ensure_collection(
        settings.collection_tips,
        vector_size=settings.embedding_dim,
        payload_indexes=TIPS_PAYLOAD_INDEXES,
    )

    dish_points, chunk_points, tip_points = _build_points(dishes, tags, corpus)

    # 批量 embedding（同步推理 -> to_thread 包装，避免阻塞事件循环）
    texts = [p["_text"] for p in dish_points + chunk_points + tip_points]
    vectors: list[list[float]] = []
    for i in range(0, len(texts), 64):
        batch = await asyncio.to_thread(embedding.encode, texts[i : i + 64])
        vectors.extend(batch)

    for points in (dish_points, chunk_points, tip_points):
        for p in points:
            p["vector"] = vectors.pop(0)
            p.pop("_text", None)

    client.upsert_points(settings.collection_dishes, dish_points)
    client.upsert_points(settings.collection_chunks, chunk_points)
    client.upsert_points(settings.collection_tips, tip_points)

    return VectorStats(
        dishes=len(dish_points),
        chunks=len(chunk_points),
        tips=len(tip_points),
    )
