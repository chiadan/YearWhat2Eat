# -*- coding: utf-8 -*-
"""检索链路调试（诊断工具，§6.5）：向量召回 -> rerank 合并（RRF + text 选取规则）验证。

用法：
    python scripts/diagnostics/debug_retrieve.py "宫保鸡丁怎么做"
    python scripts/diagnostics/debug_retrieve.py --intent recommend "两个人晚餐想吃辣的"

检查点：
  1. 向量命中：目标菜是否进入 top-N、相似度
  2. rerank 合并：同一菜多路命中（chunks + dishes）时 text 是否为完整摘要
     （§6.5 契约：dishes 集合完整文本优先于 chunks 步骤片段）
  3. 输出前若干候选的 RRF 排序与 text 头部
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.clients.embedding import build_embedding_client
from app.core.clients.qdrant import QdrantClient
from app.core.config import get_settings
from app.rag.nodes.rerank import RRF_K
from app.rag.retrievers.vector_retriever import VectorRetriever

VALID_INTENTS = ("dish_qa", "tips_qa", "recommend")


def _merge_rerank(hits: list[dict]) -> tuple[dict, list[tuple[str, float]]]:
    """复刻 rerank 节点的 RRF 合并 + text 选取规则（§6.5 融合②），供诊断比对。"""
    rrf: dict[str, float] = {}
    info: dict[str, dict] = {}
    for rank, h in enumerate(hits[:50]):
        did = (h.get("payload") or {}).get("dish_id")
        if not did:
            continue
        rrf[did] = rrf.get(did, 0.0) + 1.0 / (RRF_K + rank + 1)
        m = info.setdefault(did, {"text": "", "name": "", "source_set": set()})
        m["source_set"].add(h.get("source"))
        payload = h.get("payload") or {}
        src_coll = h.get("source") or ""
        text = payload.get("text") or ""
        if text and (src_coll == "dishes" or not m["text"]):
            m["text"] = text
        m["name"] = payload.get("dish_name") or payload.get("name") or m["name"]
    ordered = sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)
    return info, ordered


async def main(query: str, intent: str, show: int) -> None:
    settings = get_settings()
    qdrant = QdrantClient(settings)
    embedding = build_embedding_client(settings)
    retriever = VectorRetriever(qdrant, embedding, settings)

    print(f"query={query!r} intent={intent}")
    print("=" * 60)
    hits = await retriever.retrieve(query, top_k=15, intent=intent)
    print(f"向量命中: {len(hits)} 条")
    for h in hits[:5]:
        p = h.get("payload") or {}
        print(f"  [{h.get('score'):.4f}] {p.get('dish_id')} {p.get('dish_name') or p.get('name')} src={h.get('source')}")

    info, ordered = _merge_rerank(hits)
    print("-" * 60)
    print(f"RRF 合并后候选: {len(ordered)} 道（前 {min(show, len(ordered))} 展示）")
    for did, score in ordered[:show]:
        m = info[did]
        head = m["text"][:60].replace("\n", " ")
        print(f"  {did} {m['name']} rrf={score:.4f} src={sorted(m['source_set'])} text_len={len(m['text'])}")
        print(f"      text_head: {head}")
        if m["text"] and len(m["text"]) < 80:
            print("      [WARN] text 过短，可能被步骤片段占据（应为 dishes 完整摘要）")


def _parse_args() -> tuple[str, str, int]:
    query = "宫保鸡丁怎么做"
    intent = "dish_qa"
    show = 6
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--intent" and i + 1 < len(argv):
            intent = argv[i + 1]
            i += 2
        elif argv[i] == "--show" and i + 1 < len(argv):
            show = int(argv[i + 1])
            i += 2
        else:
            query = argv[i]
            i += 1
    if intent not in VALID_INTENTS:
        print(f"intent 必须是 {VALID_INTENTS}，收到 {intent!r}")
        sys.exit(1)
    return query, intent, show


if __name__ == "__main__":
    asyncio.run(main(*_parse_args()))
