"""Neo4j 图谱写入（§5 Step4 / §4.1 图模型）。

- 建约束/索引（幂等 IF NOT EXISTS）
- 节点：Dish / Ingredient / Tool / Step / Category / FlavorTag / Cuisine / Technique / MealType
- 关系：BELONGS_TO / REQUIRES{optional} / USES{optional} / HAS_STEP{order} /
        HAS_FLAVOR / HAS_CUISINE / HAS_TECHNIQUE / HAS_MEAL_TYPE /
        RELATED_TO{reason=同主料} / CONFLICTS_WITH（食材相克映射表）
- 幂等：全部 MERGE，可重复执行
"""
from __future__ import annotations

from collections import defaultdict

from app.core.clients.neo4j import Neo4jClient
from app.pipeline.parser import DishRecord
from app.pipeline.tagger import DishTags

# 工具词表（必备原料里的工具识别；§2.2 模板把工具与原料混在"必备原料和工具"）
_TOOL_WORDS = {
    "锅", "炒锅", "蒸锅", "高压锅", "电饭煲", "烤箱", "空气炸锅", "微波炉",
    "菜刀", "砧板", "炒勺", "铲子", "筷子", "碗", "盘子", "打蛋器",
    "保鲜膜", "厨房纸", "筛网", "漏勺", "蒸屉", "烤盘", "油纸", "破壁机", "料理机",
}

# 食材相克映射（来源：tips/食材相克与禁忌.md，§4.1 CONFLICTS_WITH）
CONFLICT_PAIRS: list[tuple[str, str]] = [
    ("菠菜", "豆腐"),
    ("胡萝卜", "白萝卜"),
    ("柿子", "螃蟹"),
    ("牛奶", "巧克力"),
    ("豆浆", "鸡蛋"),
    ("黄瓜", "西红柿"),
    ("羊肉", "西瓜"),
    ("猪肉", "茶"),
    ("蜂蜜", "豆腐"),
]


def _clean_ingredient(raw: str) -> str:
    """原料清洗：去括号备选、去量词、去推荐语。"""
    name = raw.split("（")[0].split("(")[0]
    name = name.split("（推荐")[0]
    name = re_sub_units(name)
    return name.strip(" -、，,。")

def re_sub_units(name: str) -> str:
    """去掉行尾量词/单位（如 '2 个'、'10g'、'1 根'）。"""
    import re

    return re.sub(r"[\d\s]*[g克千克公斤毫升升mlML个根只支片条块斤两]+\s*$", "", name).strip()


def _split_ingredients(raw_items: list[str]) -> tuple[list[str], list[str]]:
    """把"必备原料和工具"拆分为 原料 / 工具。"""
    ingredients: list[str] = []
    tools: list[str] = []
    for item in raw_items:
        cleaned = _clean_ingredient(item)
        if not cleaned:
            continue
        if any(t in item for t in _TOOL_WORDS):
            tools.append(cleaned)
        else:
            ingredients.append(cleaned)
    return ingredients, tools


def _ensure_schema(client: Neo4jClient) -> None:
    constraints = [
        "CREATE CONSTRAINT dish_id IF NOT EXISTS FOR (d:Dish) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT ingredient_name IF NOT EXISTS FOR (i:Ingredient) REQUIRE i.name IS UNIQUE",
        "CREATE CONSTRAINT tool_name IF NOT EXISTS FOR (t:Tool) REQUIRE t.name IS UNIQUE",
        "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT flavor_name IF NOT EXISTS FOR (f:FlavorTag) REQUIRE f.name IS UNIQUE",
        "CREATE CONSTRAINT cuisine_name IF NOT EXISTS FOR (c:Cuisine) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT technique_name IF NOT EXISTS FOR (t:Technique) REQUIRE t.name IS UNIQUE",
        "CREATE CONSTRAINT mealtype_name IF NOT EXISTS FOR (m:MealType) REQUIRE m.name IS UNIQUE",
    ]
    for q in constraints:
        client.run(q)

    for q in (
        "CREATE INDEX dish_category IF NOT EXISTS FOR (d:Dish) ON (d.category)",
        "CREATE INDEX ingredient_name_idx IF NOT EXISTS FOR (i:Ingredient) ON (i.name)",
    ):
        client.run(q)


def write_graph(
    client: Neo4jClient,
    dishes: list[DishRecord],
    tags: dict[str, DishTags],
    *,
    reset: bool = False,
) -> dict[str, int]:
    """写入图谱，返回计数统计。

    - reset=True：先清空**菜谱子图**（Dish/Ingredient/Tool/Step/Category/标签族），
      再全量 MERGE 重灌——清除陈旧/残留节点（数据源中已删除的菜），保证全量重建干净（§3 可重建原则）。
      User 节点保留（M4 用户偏好边随 Dish 删除自然断开，可由 SQLite 行为流水重放重建，§4.1）。
    - reset=False：纯 MERGE 增量（不产生重复，但不会清理陈旧节点）。
    """
    if reset:
        client.run(
            """
            MATCH (n)
            WHERE n:Dish OR n:Ingredient OR n:Tool OR n:Step OR n:Category
               OR n:FlavorTag OR n:Cuisine OR n:Technique OR n:MealType
            DETACH DELETE n
            """
        )
    _ensure_schema(client)

    stats = {"dishes": 0, "ingredients": 0, "tools": 0, "steps": 0, "relations": 0}
    dish_ingredients: dict[str, list[str]] = {}   # dish_id -> 主料（RELATED_TO 用）

    for d in dishes:
        tag = tags.get(d.dish_id, DishTags(dish_id=d.dish_id))
        ingredients, tools = _split_ingredients(d.required_raw)

        client.run(
            """
            MERGE (cat:Category {name: $category})
            MERGE (d:Dish {id: $id})
            SET d.name = $name, d.category = $category, d.path = $path,
                d.difficulty = $difficulty, d.intro = $intro, d.time_est = $time_est
            MERGE (d)-[:BELONGS_TO]->(cat)
            """,
            id=d.dish_id, name=d.name, category=d.category, path=d.rel_path,
            difficulty=d.difficulty, intro=d.intro, time_est=tag.time_est_min,
        )
        stats["dishes"] += 1
        stats["relations"] += 1

        for ing in ingredients:
            client.run(
                """
                MERGE (i:Ingredient {name: $name})
                WITH i
                MATCH (d:Dish {id: $id})
                MERGE (d)-[:REQUIRES]->(i)
                """,
                name=ing, id=d.dish_id,
            )
            stats["ingredients"] += 1
            stats["relations"] += 1

        for tool in tools:
            client.run(
                """
                MERGE (t:Tool {name: $name})
                WITH t
                MATCH (d:Dish {id: $id})
                MERGE (d)-[:USES]->(t)
                """,
                name=tool, id=d.dish_id,
            )
            stats["tools"] += 1
            stats["relations"] += 1

        for idx, step in enumerate(d.steps):
            client.run(
                """
                MATCH (d:Dish {id: $id})
                MERGE (s:Step {dish_id: $id, order: $order})
                SET s.text = $text, s.version = $version
                MERGE (d)-[:HAS_STEP]->(s)
                """,
                id=d.dish_id, order=idx + 1, text=step.text[:500], version=step.version[:50],
            )
            stats["steps"] += 1
            stats["relations"] += 1

        # 标签关系（§4.1 语义标签）
        for flavor in tag.flavors:
            client.run(
                """
                MERGE (f:FlavorTag {name: $name})
                WITH f
                MATCH (d:Dish {id: $id})
                MERGE (d)-[:HAS_FLAVOR]->(f)
                """,
                name=flavor, id=d.dish_id,
            )
        for cuisine in tag.cuisines:
            client.run(
                """
                MERGE (c:Cuisine {name: $name})
                WITH c
                MATCH (d:Dish {id: $id})
                MERGE (d)-[:HAS_CUISINE]->(c)
                """,
                name=cuisine, id=d.dish_id,
            )
        for technique in tag.techniques:
            client.run(
                """
                MERGE (t:Technique {name: $name})
                WITH t
                MATCH (d:Dish {id: $id})
                MERGE (d)-[:HAS_TECHNIQUE]->(t)
                """,
                name=technique, id=d.dish_id,
            )
        for meal in tag.meal_types:
            client.run(
                """
                MERGE (m:MealType {name: $name})
                WITH m
                MATCH (d:Dish {id: $id})
                MERGE (d)-[:HAS_MEAL_TYPE]->(m)
                """,
                name=meal, id=d.dish_id,
            )
        stats["relations"] += len(tag.flavors) + len(tag.cuisines) + len(tag.techniques) + len(tag.meal_types)

        dish_ingredients[d.dish_id] = ingredients[:5]

    # RELATED_TO：同主料两两连接（reason=同主料，§4.1 图扩散推荐）
    by_ingredient: dict[str, list[str]] = defaultdict(list)
    for dish_id, ings in dish_ingredients.items():
        for ing in ings:
            by_ingredient[ing].append(dish_id)
    related = 0
    for dish_ids in by_ingredient.values():
        uniq = sorted(set(dish_ids))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                client.run(
                    """
                    MATCH (a:Dish {id: $a}), (b:Dish {id: $b})
                    MERGE (a)-[:RELATED_TO {reason: '同主料'}]->(b)
                    MERGE (b)-[:RELATED_TO {reason: '同主料'}]->(a)
                    """,
                    a=uniq[i], b=uniq[j],
                )
                related += 1
    stats["relations"] += related

    # 食材相克（§4.1 CONFLICTS_WITH）
    for a, b in CONFLICT_PAIRS:
        client.run(
            """
            MERGE (i1:Ingredient {name: $a})
            MERGE (i2:Ingredient {name: $b})
            MERGE (i1)-[:CONFLICTS_WITH]->(i2)
            MERGE (i2)-[:CONFLICTS_WITH]->(i1)
            """,
            a=a, b=b,
        )
    stats["relations"] += len(CONFLICT_PAIRS) * 2

    return stats
