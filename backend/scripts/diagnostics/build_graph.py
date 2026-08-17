# -*- coding: utf-8 -*-
"""LangGraph 图构建冒烟 + 意图/场景判定用例（诊断工具，§6.2/§6.5 决策 16）。

用法：
    python scripts/diagnostics/build_graph.py

检查点：
  1. 图构建成功、节点与边齐全（intent_router -> query_rewriter -> ... -> generate）
  2. 意图/场景判定（规则兜底路径，不依赖 LLM）：
     - rule_personalize：点名菜 -> False（全量检索）；recommend -> True（千人千面）
     - named_dishes：query 点名菜提取
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.clients.embedding import build_embedding_client
from app.core.clients.llm import LLMClient
from app.core.clients.neo4j import Neo4jClient
from app.core.clients.qdrant import QdrantClient
from app.core.clients.reranker import build_reranker_client
from app.core.config import get_settings
from app.rag.graph import GraphDeps, build_graph
from app.rag.nodes.intent_router import named_dishes, rule_personalize


def _check_graph() -> None:
    print("1) LangGraph 图构建")
    settings = get_settings()
    deps = GraphDeps(
        settings=settings,
        llm=LLMClient(settings),
        embedding=build_embedding_client(settings),
        qdrant=QdrantClient(settings),
        neo4j=Neo4jClient(settings),
        reranker=build_reranker_client(settings),
    )
    g = build_graph(deps)
    nodes = list(g.get_graph().nodes.keys())
    print(f"   节点: {nodes}")
    expected = ["intent_router", "query_rewriter", "query_analyzer", "retrieve", "rerank", "rank_fuse", "generate"]
    missing = [n for n in expected if n not in nodes]
    if missing:
        print(f"   [FAIL] 缺少节点: {missing}")
        sys.exit(1)
    print("   OK")


def _check_scenario() -> None:
    print("2) 意图/场景判定（规则兜底）")
    cases = [
        ("宫保鸡丁怎么做", "recommend", False, ["宫保鸡丁"]),
        ("想吃宫保鸡丁", "recommend", False, ["宫保鸡丁"]),
        ("今晚吃什么推荐一下", "recommend", True, []),
        ("两个人晚餐推荐", "recommend", True, []),
        ("焯水要多久", "tips_qa", False, []),
        ("你好", "chitchat", False, []),
    ]
    failed = 0
    for query, intent, expect_p, expect_names in cases:
        p = rule_personalize(query, intent)
        names = named_dishes(query)
        ok = p is expect_p and set(names) == set(expect_names)
        mark = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"   [{mark}] {query!r} intent={intent} -> personalize={p}（期望 {expect_p}）named={names}")
    if failed:
        print(f"   [FAIL] {failed} 例未通过")
        sys.exit(1)
    print("   OK")


def main() -> None:
    _check_graph()
    print()
    _check_scenario()


if __name__ == "__main__":
    main()
