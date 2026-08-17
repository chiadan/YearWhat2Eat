"""检索节点（§6.5 召回）：三路并行（向量 + 图 + 规则）-> 合并写入 RetrievalState。

§6.2 图中 retrieve 的 fan-out 在此用 asyncio.gather 并行执行（行为等价 Send API）。
"""
from __future__ import annotations

import asyncio

from app.core.clients.factory import build_graph_store
from app.rag.nodes import graph_search, rule_filter
from app.rag.retrievers.vector_retriever import VectorRetriever
from app.rag.state import AgentState, RetrievalState


def retrieve(retriever: VectorRetriever, neo4j: GraphStoreClient) -> object:
    async def _node(state: AgentState) -> dict:
        query = state["query"]

        vector_task = retriever.retrieve(
            query.rewritten or state["input"].query,
            top_k=15,
            intent=query.intent,
        )

        async def _graph() -> RetrievalState:
            return await graph_search.execute(neo4j, state)

        async def _rule() -> RetrievalState:
            return await rule_filter.execute(state)

        results = await asyncio.gather(vector_task, _graph(), _rule())

        vector_hits = results[0]
        graph_hits = results[1].graph_hits
        rule_hits = results[2].rule_hits

        # 三路合并写入（§6.5 融合①：合并去重交给 rerank 的 RRF）
        return {
            "retrieval": RetrievalState(
                vector_hits=vector_hits,
                graph_hits=graph_hits,
                rule_hits=rule_hits,
                hard_filtered=results[2].hard_filtered,
            )
        }

    return _node
