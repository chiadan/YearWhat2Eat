"""LangGraph 图构建与编译（§6.2 Mermaid 全图）：节点组装、条件边、依赖注入。

节点 = app/rag/nodes/ 一个文件；条件边与节点实现分离（§6.2 对应关系表）。
流式：astream(stream_mode=["updates", "custom"]) —— updates=节点事件，custom=LLM token。
"""
from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from app.core.clients.embedding import EmbeddingClient
from app.core.clients.llm import LLMClient
from app.core.clients.factory import build_graph_store
from app.core.clients.factory import build_vector_store
from app.core.clients.base import GraphStoreClient, VectorStoreClient
from app.core.clients.reranker import RerankerClient
from app.core.config import Settings
from app.rag.nodes import (
    generate, graph_search, intent_router, planner, query_analyzer,
    query_rewriter, rank_fuse, rerank, retrieve, rule_filter,
)
from app.rag.retrievers.vector_retriever import VectorRetriever
from app.rag.state import AgentState


@dataclass
class GraphDeps:
    settings: Settings
    llm: LLMClient
    embedding: EmbeddingClient
    qdrant: VectorStoreClient
    neo4j: GraphStoreClient
    reranker: RerankerClient


def _route_intent(state: AgentState) -> str:
    """§6.2 条件边①：chitchat 短路直答，其余进入检索链路。"""
    return "chitchat" if state["query"].intent == "chitchat" else "rag"


def _route_after_fuse(state: AgentState) -> str:
    """§6.2 条件边②：推荐/规划进 planner，问答/技巧/购物清单直通 generate。"""
    return "plan" if state["query"].intent in ("recommend", "plan_menu") else "generate"


def build_graph(deps: GraphDeps):
    retriever = VectorRetriever(deps.qdrant, deps.embedding, deps.settings)

    # 嵌套通道方案（state["input"]/["output"]/...）不指定 input/output schema（§6.1 命名空间化）
    g = StateGraph(AgentState)
    g.add_node("intent_router", intent_router.intent_router(deps.llm))
    g.add_node("query_rewriter", query_rewriter.query_rewriter(deps.llm))
    g.add_node("query_analyzer", query_analyzer.query_analyzer(deps.llm))
    g.add_node("retrieve", retrieve.retrieve(retriever, deps.neo4j))
    g.add_node("rerank", rerank.rerank(deps.reranker, deps.settings))
    g.add_node("rank_fuse", rank_fuse.rank_fuse())
    g.add_node("planner", planner.planner())
    g.add_node("generate", generate.generate(deps.llm))

    g.add_edge(START, "intent_router")
    g.add_conditional_edges(
        "intent_router",
        _route_intent,
        {"chitchat": "generate", "rag": "query_rewriter"},
    )
    g.add_edge("query_rewriter", "query_analyzer")
    g.add_edge("query_analyzer", "retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_edge("rerank", "rank_fuse")
    g.add_conditional_edges(
        "rank_fuse",
        _route_after_fuse,
        {"plan": "planner", "generate": "generate"},
    )
    g.add_edge("planner", "generate")
    g.add_edge("generate", END)

    return g.compile()
