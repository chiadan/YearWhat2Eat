"""RAG 检索评测（§13.2/§13.3）：Recall@5 / MRR@10。

用法：python -m tests.eval.run_eval [--top-k 10] [--limit 0]
依赖：Neo4j/Qdrant 容器在跑 + embedding 模型已下载（§12.5）。
报告输出 tests/eval/reports/retrieval-{timestamp}.json。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.core.clients.embedding import build_embedding_client  # noqa: E402
from app.core.clients.qdrant import QdrantClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.rag.retrievers.vector_retriever import VectorRetriever  # noqa: E402

TYPE_TO_INTENT = {"recommend": "recommend", "dish_qa": "dish_qa", "tips_qa": "tips_qa"}


def expected_id(ref_doc: str) -> str:
    """golden 的 ref_doc（dishes/... 或 tips/...）→ 向量 payload 中的 id 字段值。"""
    if ref_doc.startswith("dishes/"):
        rel = ref_doc[len("dishes/") :]
        return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
    if ref_doc.startswith("tips/"):
        return hashlib.sha1(ref_doc.encode("utf-8")).hexdigest()[:12]
    return ref_doc


def hit_field(hit: dict) -> str | None:
    """从命中 payload 取匹配字段（chunks→dish_id，dishes→dish_id，tips→tip_id）。"""
    payload = hit.get("payload") or {}
    return payload.get("dish_id") or payload.get("tip_id")


async def run_retrieval_eval(top_k: int = 10, limit: int = 0) -> dict:
    settings = get_settings()
    qdrant = QdrantClient(settings)
    embedding = build_embedding_client(settings)
    retriever = VectorRetriever(qdrant, embedding, settings)

    golden_path = Path(__file__).parent / "golden_qa.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    items = golden["items"]
    if limit > 0:
        items = items[:limit]

    results: list[dict] = []
    for item in items:
        intent = TYPE_TO_INTENT.get(item["type"], "dish_qa")
        expect = item.get("expect") or {}
        ref_doc = expect.get("ref_doc")
        if not ref_doc:
            continue  # recommend 类无引用，跳过检索指标
        want = expected_id(ref_doc)

        hits = await retriever.retrieve(item["query"], top_k=top_k, intent=intent)
        rank = None
        for idx, h in enumerate(hits[:top_k]):
            if hit_field(h) == want:
                rank = idx + 1
                break
        results.append(
            {
                "id": item.get("id"),
                "type": item["type"],
                "query": item["query"],
                "expect": ref_doc,
                "rank": rank,
            }
        )

    # 指标（§13.2：Recall@5 ≥ 0.8、MRR@10 ≥ 0.7）
    n = len(results)
    recall5 = sum(1 for r in results if r["rank"] and r["rank"] <= 5) / n if n else 0
    mrr10 = sum(1.0 / r["rank"] for r in results if r["rank"] and r["rank"] <= 10) / n if n else 0

    # 推荐类硬约束满足率（§13.2：100%）——用规则路径（不调 LLM，快速回归）
    constraint = await run_constraint_eval(items)
    # 画像回归（§13.2 千人千面：同 query 不同画像 → 推荐差异）
    profile_regression = run_profile_regression()

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "golden_version": golden.get("version"),
        "items_evaluated": n,
        "recall_at_5": round(recall5, 4),
        "mrr_at_10": round(mrr10, 4),
        "targets": {"recall_at_5": 0.8, "mrr_at_10": 0.7},
        "constraint_pass_rate": constraint["pass_rate"],
        "constraint_detail": constraint["detail"],
        "profile_regression": profile_regression,
        "misses": [r for r in results if r["rank"] is None][:20],
        "results": results,
    }
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    out = reports_dir / f"retrieval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"golden={golden.get('version')} items={n}")
    print(f"Recall@5 = {recall5:.4f}  (目标 ≥ 0.8)  {'PASS' if recall5 >= 0.8 else 'FAIL'}")
    print(f"MRR@10  = {mrr10:.4f}  (目标 ≥ 0.7)  {'PASS' if mrr10 >= 0.7 else 'FAIL'}")
    print(f"约束满足 = {constraint['pass_rate']:.4f}  (目标 1.0)  {'PASS' if constraint['pass_rate'] >= 1.0 else 'FAIL'}")
    print(f"画像回归 = {'PASS (两个画像推荐不同)' if profile_regression['differ'] else 'FAIL (推荐无差异)'}")
    print(f"report -> {out}")
    return report


def run_profile_regression() -> dict:
    """画像回归（§13.2）：同一批候选，辣党 vs 清淡党打分排序应不同。纯逻辑，不调 LLM。"""
    from app.services.personalization import personal_score

    candidates = [
        {"dish_id": "a", "name": "辣子鸡", "category": "meat_dish", "difficulty": 3, "time_est": 30,
         "meat_attr": "荤", "text": "辣子鸡。麻辣鲜香。", "flavors": ["辣"]},
        {"dish_id": "b", "name": "清蒸鲈鱼", "category": "aquatic", "difficulty": 2, "time_est": 20,
         "meat_attr": "水产", "text": "清蒸鲈鱼。清淡鲜美。", "flavors": ["清淡"]},
        {"dish_id": "c", "name": "麻婆豆腐", "category": "meat_dish", "difficulty": 3, "time_est": 25,
         "meat_attr": "荤", "text": "麻婆豆腐。麻辣下饭。", "flavors": ["辣"]},
    ]
    base = {"flavor_sweet": 3, "flavor_sour": 3, "flavor_light": 3, "avoid_list": [],
            "diet_type": "无限制", "skill_level": "进阶", "tools": [], "goal": "均衡"}
    p_spicy = dict(base, flavor_spicy=5)
    p_mild = dict(base, flavor_spicy=1)

    rank_a = sorted(candidates, key=lambda x: personal_score(x, p_spicy), reverse=True)
    rank_b = sorted(candidates, key=lambda x: personal_score(x, p_mild), reverse=True)
    return {
        "differ": rank_a[0]["dish_id"] != rank_b[0]["dish_id"],
        "spicy_top": rank_a[0]["name"],
        "mild_top": rank_b[0]["name"],
    }


async def run_constraint_eval(items: list[dict]) -> dict:
    """推荐类硬约束满足率（§13.2）：规则约束解析 + rule_filter 候选不违反 expect。"""
    from app.rag.nodes.query_analyzer import _rule_constraints
    from app.rag.nodes.rule_filter import execute as rule_execute
    from app.rag.state import AgentState, ContextState, InputState, QueryState, RetrievalState

    detail: list[dict] = []
    passed = 0
    total = 0
    for item in items:
        if item["type"] != "recommend":
            continue
        total += 1
        expect = item.get("expect") or {}
        constraints = _rule_constraints(item["query"], [])
        issues: list[str] = []

        if expect.get("people") and constraints.people != expect["people"]:
            issues.append(f"people: expect {expect['people']} got {constraints.people}")
        if expect.get("meal_type") and constraints.meal_time != expect["meal_type"]:
            issues.append(f"meal_type: expect {expect['meal_type']} got {constraints.meal_time}")
        if expect.get("max_time_min") and constraints.max_time_min != expect["max_time_min"]:
            issues.append(f"max_time: expect {expect['max_time_min']} got {constraints.max_time_min}")
        for f in expect.get("flavors") or []:
            if f not in constraints.flavors:
                issues.append(f"flavor {f} 未解析出")
        for a in expect.get("avoids") or []:
            if a not in constraints.avoids:
                issues.append(f"avoid {a} 未解析出")

        if not issues:
            # 规则过滤不违反硬约束（候选不应含忌口食材）
            state: AgentState = {
                "input": InputState(query=item["query"]),
                "context": ContextState(),
                "query": QueryState(constraints=constraints),
                "retrieval": RetrievalState(),
                "planning": None,  # type: ignore[assignment]
                "output": None,  # type: ignore[assignment]
            }
            retr = await rule_execute(state)
            for a in expect.get("avoids") or []:
                for hit in retr.rule_hits:
                    if a in hit["name"] or any(a in ing for ing in hit.get("main_ingredients") or []):
                        issues.append(f"候选含忌口 {a}: {hit['name']}")
                        break

        ok = not issues
        passed += int(ok)
        detail.append({"id": item.get("id"), "query": item["query"], "ok": ok, "issues": issues[:4]})

    return {
        "pass_rate": (passed / total) if total else 1.0,
        "total": total,
        "passed": passed,
        "detail": detail,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0, help="只评测前 N 条（调试用）")
    args = parser.parse_args()
    asyncio.run(run_retrieval_eval(top_k=args.top_k, limit=args.limit))
