"""菜单规划节点（§6.5 三，仅 recommend / plan_menu 模式）：荤素公式 + 动物多样 + MMR。

核心算法在 app/rag/rule_engine.py::plan_menu（与规则推荐服务共用，单一实现）；
本节点负责：候选池组装（fused 精排优先 + rule_hits 兜底）+ 口味惩罚排序 -> 调 plan_menu。
"""
from __future__ import annotations

from app.rag.rule_engine import plan_menu
from app.rag.state import AgentState, PlanningState


def planner() -> object:
    async def _node(state: AgentState) -> dict:
        fused = state["retrieval"].fused
        rule_hits = state["retrieval"].rule_hits
        constraints = state["query"].constraints
        query = state["input"].query

        if not fused and not rule_hits:
            return {"planning": PlanningState(plan=None)}

        people = constraints.people or 2

        # 候选池：fused（精排）优先，rule_hits（全量硬约束通过）补齐（§6.5 规则召回兜底）
        def _score(item: dict) -> float:
            base = float(item.get("final_score") or item.get("match_score") or 0.0)
            # 口味惩罚（§8 千人千面雏形）：约束明确要求某口味而菜不符 -> 降权
            if constraints.flavors:
                text = str(item.get("text") or "") + "".join(item.get("flavors") or [])
                hit = any(f in text for f in constraints.flavors)
                if not hit:
                    base -= 1.0
            return base

        pool: list[dict] = []
        seen: set[str] = set()
        for item in list(fused) + list(rule_hits):
            if item.get("dish_id") in seen:
                continue
            seen.add(item["dish_id"])
            pool.append(item)
        pool.sort(key=_score, reverse=True)

        plan = plan_menu(pool, people, want_soup="汤" in query, score_key="final_score")
        return {"planning": PlanningState(
            ratio=plan["ratio"],
            meat_candidates=[d for d in pool if d.get("meat_attr") in ("荤", "水产")][:10],
            veg_candidates=[d for d in pool if d.get("meat_attr") == "素" or d.get("category") == "vegetable_dish"][:10],
            plan=plan,
        )}

    return _node
