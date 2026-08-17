"""精排节点（§6.5 融合②）：三路召回 -> RRF 混合（k=60）-> bge-reranker 精排 top-15。

- RRF：score_rrf(d) = Σ_src 1 / (60 + rank_src(d))（§6.5）
- 文档文本：向量路用 payload.text；规则路用 name+标签 构造
- M3 无用户偏好镜像，T3 不参与；M4 接入
"""
from __future__ import annotations

import asyncio

from app.core.clients.reranker import RerankerClient
from app.core.config import Settings
from app.rag.state import AgentState, RetrievalState

RRF_K = 60


def _iter_dish_id(hit: dict, src: str) -> str | None:
    if src == "vector":
        return (hit.get("payload") or {}).get("dish_id")
    return hit.get("dish_id")


def rerank(reranker: RerankerClient, settings: Settings) -> object:
    async def _node(state: AgentState) -> dict:
        retrieval: RetrievalState = state["retrieval"]
        rrf: dict[str, float] = {}
        info: dict[str, dict] = {}

        for src, hits in (
            ("vector", retrieval.vector_hits),
            ("graph", retrieval.graph_hits),
            ("rule", retrieval.rule_hits),
        ):
            for rank, h in enumerate(hits[:50]):
                did = _iter_dish_id(h, src)
                if not did:
                    continue
                rrf[did] = rrf.get(did, 0.0) + 1.0 / (RRF_K + rank + 1)
                meta = info.setdefault(
                    did,
                    {"dish_id": did, "sources": set(), "score": 0.0, "text": "",
                     "name": "", "category": "", "difficulty": None, "time_est": None,
                     "meat_attr": "", "techniques": [], "main_ingredients": []},
                )
                meta["sources"].add(src)
                meta["score"] = max(meta["score"], float(h.get("score") or 0))
                payload = h.get("payload") or {}
                if src == "vector":
                    src_coll = h.get("source") or ""  # dishes | chunks | tips（§6.5 召回①）
                    text = payload.get("text") or ""
                    # text 选取：dishes 集合（完整菜谱摘要）优先于 chunks（步骤片段），
                    # 避免具体问答时步骤片段覆盖完整做法（§6.5 引用完整性，决策 16 回归点）
                    if text and (src_coll == "dishes" or not meta["text"]):
                        meta["text"] = text
                    meta["name"] = payload.get("dish_name") or payload.get("name") or meta["name"]
                    meta["category"] = payload.get("category") or meta["category"]
                    # difficulty 仅 dishes 携带；chunks 为 None，无条件赋值会覆盖真值
                    if payload.get("difficulty") is not None:
                        meta["difficulty"] = payload["difficulty"]
                elif src == "rule":
                    for key in ("name", "category", "difficulty", "time_est", "meat_attr", "techniques", "main_ingredients"):
                        if h.get(key) is not None:
                            meta[key] = h[key]

        if not rrf:
            return {"retrieval": RetrievalState(
                vector_hits=retrieval.vector_hits, graph_hits=retrieval.graph_hits,
                rule_hits=retrieval.rule_hits, hard_filtered=retrieval.hard_filtered,
                reranked=[], fused=retrieval.fused,
            )}

        # RRF top-30 -> reranker 精排 -> top-15（§6.5）
        ordered = sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)[:30]
        query = state["query"].rewritten or state["input"].query

        docs: list[tuple[str, dict, str]] = []
        for did, rrf_score in ordered:
            m = info[did]
            text = m["text"] or (
                f"{m['name']}。{m['meat_attr'] or '家常'}类菜"
                f"（难度 {m['difficulty'] or 0}/5，预估 {m['time_est'] or '?'} 分钟）。"
                f"标签：{'、'.join((m['techniques'] or [])[:3])}"
            )
            docs.append((did, m, text))
            m["rrf_score"] = rrf_score

        if len(docs) > settings.rerank_top_k:
            scores = await asyncio.to_thread(
                reranker.rerank, query, [d[2] for d in docs]
            )
            for (did, m, _text), s in zip(docs, scores):
                m["rerank_score"] = float(s)
        else:
            for _did, m, _text in docs:
                m["rerank_score"] = m["rrf_score"]

        docs.sort(key=lambda d: d[1]["rerank_score"], reverse=True)
        reranked = [
            {
                "dish_id": did,
                "name": m["name"],
                "category": m["category"],
                "difficulty": m["difficulty"],
                "time_est": m["time_est"],
                "meat_attr": m["meat_attr"],
                "techniques": m["techniques"],
                "main_ingredients": m["main_ingredients"],
                "sources": sorted(m["sources"]),
                "score": m["score"],
                "rrf_score": round(m["rrf_score"], 4),
                "rerank_score": round(m["rerank_score"], 4),
                "text": m["text"],
            }
            for did, m, _text in docs[: settings.rerank_top_k]
        ]

        return {"retrieval": RetrievalState(
            vector_hits=retrieval.vector_hits, graph_hits=retrieval.graph_hits,
            rule_hits=retrieval.rule_hits, hard_filtered=retrieval.hard_filtered,
            reranked=reranked, fused=retrieval.fused,
        )}

    return _node
