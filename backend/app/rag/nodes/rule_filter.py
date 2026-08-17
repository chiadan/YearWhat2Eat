"""规则召回/硬过滤节点（§6.5 召回③）：全量菜谱过硬约束 -> 候选集 + 过滤记录。

核心逻辑在 app/rag/rule_engine.py（与规则推荐服务共用，单一实现）：
  本节点负责：加载画像约束（会话 + 画像合并，personalize 场景分流）-> 调 apply_hard_filters
产出 rule_hits（候选）+ hard_filtered（[{dish_id, name, reason}]，保证可解释）。

场景分流（§6.5 召回④ / 决策 16）：是否应用千人千面由 intent_router 判定
（QueryState.personalize）——推荐场景=True（画像 + 会话显式约束合并硬过滤）；
具体内容查询=False（仅会话显式约束，保证指定菜必召回）。本节点只消费标志，不自行判定。
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.db.json_utils import json_load
from app.db.models import DishMeta
from app.db.session import get_engine
from app.rag.rule_engine import apply_hard_filters, recent_made_ids
from app.rag.state import AgentState, RetrievalState


def _load_catalog() -> list[dict]:
    """从 SQLite dish_meta 读全量菜谱（业务真源，§3）。"""
    rows = []
    with Session(get_engine()) as session:
        for m in session.exec(select(DishMeta)).all():
            tags = json_load(m.tags, {})
            rows.append(
                {
                    "dish_id": m.dish_id,
                    "name": m.name,
                    "category": m.category,
                    "difficulty": m.difficulty,
                    "time_est": m.time_est,
                    "meat_attr": tags.get("meat_attr", "其他"),
                    "techniques": tags.get("techniques") or [],
                    "flavors": tags.get("flavors") or [],
                    "main_ingredients": json_load(m.main_ingredients, []),
                }
            )
    return rows


def rule_filter() -> object:
    async def _node(state: AgentState) -> dict:
        return {"retrieval": await execute(state)}

    return _node


async def execute(state: AgentState) -> RetrievalState:
    """规则硬过滤核心（§6.5 召回③）。

    约束 = 会话约束（query_analyzer）∪ 画像（§8.1，M4：忌口/工具/技能/饮食类型）；
    是否合并画像由 intent_router 判定的 QueryState.personalize 决定（§6.5 召回④）。
    """
    constraints = state["query"].constraints
    profile = state["context"].profile or {}
    personalize = state["query"].personalize

    avoids = list(constraints.avoids or [])
    diet_type = constraints.diet_type
    skill_level = constraints.skill_level
    tools = set(constraints.tools or [])
    if personalize:
        avoids = list(set(avoids) | set(profile.get("avoid_list") or []))
        diet_type = diet_type or profile.get("diet_type")
        skill_level = skill_level or profile.get("skill_level", "新手")
        tools = tools | set(profile.get("tools") or [])

    catalog = _load_catalog()
    made_ids = recent_made_ids(state["input"].user_id) if personalize else set()
    rule_hits, hard_filtered = apply_hard_filters(
        catalog,
        avoids=avoids,
        diet_type=diet_type,
        skill_level=skill_level,
        tools=tools,
        made_ids=made_ids,
        max_time_min=constraints.max_time_min,
        flavors=constraints.flavors,
        use_ingredients=constraints.use_ingredients,
    )

    retrieval: RetrievalState = state["retrieval"]
    return RetrievalState(
        vector_hits=retrieval.vector_hits,
        graph_hits=retrieval.graph_hits,
        rule_hits=rule_hits,
        hard_filtered=hard_filtered,
        reranked=retrieval.reranked,
        fused=retrieval.fused,
    )
