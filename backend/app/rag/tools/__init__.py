"""Agent 工具（§6.2 工具清单，M3 以函数库形式供 planner 调用；LLM 工具循环 M5 扩展）。

- calculate_menu_ratio(people)：荤素公式（§2.3 如何选择现在吃什么）
- get_dish_detail(dish_id)：菜谱基本信息（SQLite dish_meta）
- check_conflicts(a, b)：食材相克检查（Neo4j CONFLICTS_WITH）
- scale_ingredients / build_shopping_list：定量换算与购物清单（M5 结合 API 完善，§9.4）

db/外部依赖均为函数内懒加载，保证纯逻辑可独立单测（§13.4）。
"""
from __future__ import annotations

import math

# 动物词表（§6.5 荤菜动物多样轮选）
ANIMAL_KEYWORDS = ["猪", "鸡", "牛", "羊", "鸭", "鱼", "虾", "蟹", "蛙", "兔", "鹅", "鳝", "鲍", "参"]


def calculate_menu_ratio(people: int) -> dict:
    """§2.3 公式：菜数 = 人数+1；a≤b≤a+1 -> veg=floor((N+1)/2), meat=ceil((N+1)/2)。"""
    n = max(people, 1)
    veg = math.floor((n + 1) / 2)
    meat = math.ceil((n + 1) / 2)
    return {"veg": veg, "meat": meat, "people": n}


def get_dish_detail(dish_id: str) -> dict | None:
    from sqlmodel import Session

    from app.db.json_utils import json_load
    from app.db.models import DishMeta
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        row = session.get(DishMeta, dish_id)
        if row is None:
            return None
        tags = json_load(row.tags, {})
        return {
            "dish_id": row.dish_id,
            "name": row.name,
            "category": row.category,
            "difficulty": row.difficulty,
            "time_est": row.time_est,
            "meat_attr": tags.get("meat_attr", "其他"),
            "cuisines": tags.get("cuisines") or [],
        }


def check_conflicts(ingredient_a: str, ingredient_b: str) -> bool:
    """食材相克检查（Neo4j CONFLICTS_WITH，§4.1）；图库不可用返回 False。"""
    try:
        from app.core.clients.factory import build_graph_store
        from app.core.config import get_settings

        neo4j = build_graph_store(get_settings())
        rows = neo4j.run(
            "MATCH (a:Ingredient {name:$a})-[:CONFLICTS_WITH]->(b:Ingredient {name:$b}) RETURN 1",
            a=ingredient_a, b=ingredient_b,
        )
        return bool(rows)
    except Exception:  # noqa: BLE001
        return False


def build_shopping_list(dish_ids: list[str], people: int) -> dict:
    """购物清单（§9.4 导出接口复用）：按菜名聚合；定量换算 M5 结合计算章节完善。"""
    from sqlmodel import Session

    from app.db.models import DishMeta
    from app.db.session import get_engine

    items: list[str] = []
    with Session(get_engine()) as session:
        for did in dish_ids:
            row = session.get(DishMeta, did)
            if row:
                items.append(f"{row.name}（{people} 人份）")
    return {"people": people, "dishes": dish_ids, "items": items}
