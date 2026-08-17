"""图检索节点（§6.5 召回②）：Neo4j 预置模板 T1~T4，参数填充，按命中维度加权。

- T1 同主料（权重 3）：entities.ingredients
- T2 同标签（权重 2）：entities.cuisines/techniques/flavors
- T3 用户偏好扩散（权重 2）：M4 启用（用户偏好镜像），M3 无 user 图数据时跳过
- T4 相克检查（硬过滤辅助）：返回冲突组合供 rule_filter 剔除
产出 graph_hits=[{dish_id, weight}]；weight = Σ 模板权重 × 命中数（§6.5）
"""
from __future__ import annotations

from app.core.clients.factory import build_graph_store
from app.rag.state import AgentState, RetrievalState

# §6.5 预置 Cypher 模板（LLM 只填参数，禁止自由写 Cypher——§11 铁律 5）
_T1_SAME_INGREDIENT = """
MATCH (d:Dish)-[:REQUIRES]->(i:Ingredient)
WHERE i.name IN $ingredients
RETURN d.id AS dish_id, count(*) AS w
ORDER BY w DESC LIMIT 20
"""
_T2_SAME_TAGS = """
MATCH (d:Dish)-[:HAS_CUISINE|HAS_TECHNIQUE|HAS_FLAVOR]->(t)
WHERE t.name IN $tags
RETURN d.id AS dish_id, count(DISTINCT t) AS w
ORDER BY w DESC LIMIT 20
"""
_T3_USER_PREF = """
MATCH (u:User {id:$user_id})-[:LIKES|MADE]->(seed:Dish)-[:RELATED_TO]->(d:Dish)
RETURN d.id AS dish_id, count(*) AS w
ORDER BY w DESC LIMIT 20
"""
_T4_CONFLICTS = """
MATCH (i1:Ingredient)-[:CONFLICTS_WITH]->(i2:Ingredient)
WHERE i1.name IN $ingredients
RETURN i1.name AS a, i2.name AS b
"""

_WEIGHTS = {"T1": 3, "T2": 2, "T3": 2}


async def execute(neo4j: GraphStoreClient, state: AgentState) -> RetrievalState:
    """图检索核心（供 retrieve 节点并行调用，§6.5 召回②）。"""
    entities = state["query"].entities or {}
    user_id = state["input"].user_id
    retrieval: RetrievalState = state["retrieval"]
    weights: dict[str, int] = {}

    def _merge(dish_id: str, w: int) -> None:
        weights[dish_id] = weights.get(dish_id, 0) + w

    # T1 同主料
    ingredients = [str(x) for x in (entities.get("ingredients") or [])]
    if ingredients:
        for row in await _run(neo4j, _T1_SAME_INGREDIENT, ingredients=ingredients):
            _merge(row["dish_id"], _WEIGHTS["T1"] * int(row.get("w") or 1))

    # T2 同标签
    tags = [str(x) for x in (entities.get("cuisines") or []) + (entities.get("techniques") or []) + (entities.get("flavors") or [])]
    if tags:
        for row in await _run(neo4j, _T2_SAME_TAGS, tags=tags):
            _merge(row["dish_id"], _WEIGHTS["T2"] * int(row.get("w") or 1))

    # T3 用户偏好扩散（M4 用户镜像启用后生效）
    if user_id and user_id.isdigit():
        for row in await _run(neo4j, _T3_USER_PREF, user_id=int(user_id)):
            _merge(row["dish_id"], _WEIGHTS["T3"] * int(row.get("w") or 1))

    graph_hits = [{"dish_id": k, "weight": v} for k, v in weights.items()]
    graph_hits.sort(key=lambda r: r["weight"], reverse=True)

    return RetrievalState(
        vector_hits=retrieval.vector_hits,
        graph_hits=graph_hits,
        rule_hits=retrieval.rule_hits,
        hard_filtered=retrieval.hard_filtered,
        reranked=retrieval.reranked,
        fused=retrieval.fused,
    )


def graph_search(neo4j: GraphStoreClient) -> object:
    async def _node(state: AgentState) -> dict:
        return {"retrieval": await execute(neo4j, state)}

    return _node


async def _run(neo4j: GraphStoreClient, query: str, **params) -> list[dict]:
    """Cypher 在独立线程执行（同步 driver），失败返回空（图库不可用不阻塞）。"""
    import asyncio

    try:
        return await asyncio.to_thread(neo4j.run, query, **params)
    except Exception:  # noqa: BLE001
        return []
