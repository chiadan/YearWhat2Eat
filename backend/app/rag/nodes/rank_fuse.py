"""融合打分节点（§6.3 / §6.5）：final_score 合成 + MMR 多样化 + 10% 探索。

final_score(d) = 0.45 × relevance(d)          # 0.7×rerank + 0.3×norm(RRF)
               + 0.25 × personal(d)            # 真实画像（§8，M4）
               - 0.15 × recency_penalty(d)     # 近 7 天做过（M4）
               + 0.15 × novelty(d)             # MMR λ=0.7（category/meat_attr 近似相似度）
探索：10% 概率从 6~15 档随机采样一道（§6.3 探索与利用）
"""
from __future__ import annotations

import random

from app.services.personalization import personal_score
from app.rag.rule_engine import _similarity
from app.rag.state import AgentState, RetrievalState


def _norm(values: list[float]) -> dict[int, float]:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    return {i: (v - lo) / span for i, v in enumerate(values)}


def _personal_score(item: dict, profile: dict | None) -> float:
    """§6.5 personal 子项（真实画像，M4）；无画像 -> 中性 0.5。"""
    return personal_score(item, profile)


def _disliked_ids(user_id: str | None) -> set[str]:
    """用户 👎 过的菜（§8.2 反馈闭环：主动 👎 -> 该菜立即降权）。"""
    if not user_id or not user_id.isdigit():
        return set()
    from sqlmodel import Session, select

    from app.db.models import UserFeedback
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        rows = session.exec(
            select(UserFeedback).where(
                UserFeedback.user_id == int(user_id),
                UserFeedback.action == "dislike",
            )
        ).all()
    return {r.dish_id for r in rows}


def rank_fuse(explore: bool = True) -> object:
    async def _node(state: AgentState) -> dict:
        retrieval: RetrievalState = state["retrieval"]
        items = list(retrieval.reranked)
        constraints = state["query"].constraints
        profile = state["context"].profile  # 画像 dict（M4）

        if not items:
            return {"retrieval": RetrievalState(
                vector_hits=retrieval.vector_hits, graph_hits=retrieval.graph_hits,
                rule_hits=retrieval.rule_hits, hard_filtered=retrieval.hard_filtered,
                reranked=retrieval.reranked, fused=[],
            )}

        # 相关度合成（§6.5）：relevance = 0.7×rerank + 0.3×norm(RRF)
        rerank_scores = [i["rerank_score"] for i in items]
        rrf_scores = [i["rrf_score"] for i in items]
        norm_rerank = _norm(rerank_scores)
        norm_rrf = _norm(rrf_scores)

        # MMR 贪心（§6.3 novelty，λ=0.7）
        disliked = _disliked_ids(state["input"].user_id)
        selected: list[dict] = []
        remaining = list(items)
        while remaining and len(selected) < len(items):
            best_idx = 0
            best_val = -1e9
            for idx, item in enumerate(remaining):
                novelty = 0.0
                if selected:
                    novelty = max(_similarity(item, s) for s in selected)
                base = (
                    0.45 * (0.7 * norm_rerank[items.index(item)] + 0.3 * norm_rrf[items.index(item)])
                    + 0.25 * _personal_score(item, profile)
                    - (1.0 if item["dish_id"] in disliked else 0.0)  # §8.2 👎 降权
                )
                value = 0.7 * base - 0.3 * novelty  # λ=0.7
                if value > best_val:
                    best_val, best_idx = value, idx
            item = remaining.pop(best_idx)
            item["final_score"] = round(best_val, 4)
            item["personal"] = round(_personal_score(item, profile), 4)
            selected.append(item)

        # 10% 探索：从 6~15 档随机采样（§6.3 探索与利用）；
        # 换一批（diversity=true，§10）：探索率提升到 70%，同约束下产出明显不同结果
        explore_rate = 0.7 if state["query"].diversity else 0.1
        if explore and len(selected) > 5 and random.random() < explore_rate:
            idx = random.randint(5, min(len(selected) - 1, 14))
            selected.insert(0, selected.pop(idx))

        return {"retrieval": RetrievalState(
            vector_hits=retrieval.vector_hits, graph_hits=retrieval.graph_hits,
            rule_hits=retrieval.rule_hits, hard_filtered=retrieval.hard_filtered,
            reranked=retrieval.reranked, fused=selected,
        )}

    return _node
