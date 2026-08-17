"""规则引擎（§6.5 召回③/三）：硬过滤 + 菜单规划，供 rag 节点与规则推荐服务共用。

单一实现，两处消费：
  - rag/nodes/rule_filter.py（Agent 检索链路）
  - services/recommend_service.py（首页规则推荐，无 LLM）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.rag.tools import ANIMAL_KEYWORDS, calculate_menu_ratio

_SKILL_MAX_DIFFICULTY = {"新手": 3, "进阶": 4, "熟练": 5}
_SPECIAL_TOOLS = ["微波炉", "空气炸锅", "电饭煲", "烤箱", "高压锅"]


def _similarity(a: dict, b: dict) -> float:
    """MMR 相似度近似（§6.5 novelty）：同分类 0.5 / 同荤素 0.3 / 同菜 1。"""
    if a["dish_id"] == b["dish_id"]:
        return 1.0
    s = 0.0
    if a.get("category") and a["category"] == b.get("category"):
        s += 0.5
    if a.get("meat_attr") and a["meat_attr"] == b.get("meat_attr"):
        s += 0.3
    return s


def apply_hard_filters(
    catalog: list[dict],
    *,
    avoids: list[str],
    diet_type: str | None,
    skill_level: str | None,
    tools: set[str],
    made_ids: set[str],
    max_time_min: int | None = None,
    flavors: list[str] | None = None,
    use_ingredients: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """规则硬过滤（§6.5 召回③）：返回 (rule_hits, hard_filtered)。

    约束违反即剔除：忌口食材 / 素食排除荤菜 / 难度超技能 / 时长超预算 / 特殊工具不具备 / 近 7 天做过。
    """
    skill_max = _SKILL_MAX_DIFFICULTY.get(skill_level, 5) if skill_level else 5
    hard_filtered: list[dict] = []
    rule_hits: list[dict] = []
    for d in catalog:
        reasons: list[str] = []
        if avoids:
            hit_avoid = [a for a in avoids if a in d["name"] or any(a in i for i in d.get("main_ingredients", []))]
            if hit_avoid:
                reasons.append(f"忌口食材: {'、'.join(hit_avoid)}")
        if diet_type == "素食" and d["meat_attr"] in ("荤", "水产"):
            reasons.append("饮食类型: 素食")
        if d["difficulty"] is not None and d["difficulty"] > skill_max:
            reasons.append(f"难度 {d['difficulty']}/5 超过技能上限")
        if max_time_min and d["time_est"] is not None and d["time_est"] > max_time_min:
            reasons.append(f"预估 {d['time_est']} 分钟超时")
        if tools:
            need = [t for t in d["techniques"] if t in _SPECIAL_TOOLS]
            missing = [t for t in need if t not in tools]
            if missing:
                reasons.append(f"需要工具: {'、'.join(missing)}")
        if d["dish_id"] in made_ids:
            reasons.append("近 7 天做过")
        if reasons:
            hard_filtered.append({"dish_id": d["dish_id"], "name": d["name"], "reason": "；".join(reasons[:2])})
            continue
        # 约束匹配分（规则召回排序，§6.5：口味交集 + 想用食材命中）
        s = 0.0
        if flavors:
            dish_flavors = set(d.get("flavors") or [])
            s += sum(1.0 for f in flavors if f in dish_flavors)
        if use_ingredients:
            s += sum(
                2.0 for i in use_ingredients
                if i in d["name"] or any(i in ing for ing in d.get("main_ingredients", []))
            )
        d["match_score"] = s
        rule_hits.append(d)
    rule_hits.sort(key=lambda x: (x["match_score"], -(x.get("time_est") or 0)), reverse=True)
    return rule_hits, hard_filtered


def _animal_of(item: dict) -> str | None:
    text = item.get("name", "") + "".join(item.get("main_ingredients") or [])
    for animal in ANIMAL_KEYWORDS:
        if animal in text:
            return animal
    return None


def plan_menu(pool: list[dict], people: int, *, want_soup: bool = False, score_key: str = "final_score") -> dict:
    """荤素菜单规划（§6.5 三）：荤素公式 + 动物多样 + MMR。

    输入候选池已按 score_key 降序；输出 plan {ratio, meat[], veg[], soup[]}（每项 {dish_id, name}）。
    """
    ratio = calculate_menu_ratio(people)

    meat_cands = [d for d in pool if d.get("meat_attr") in ("荤", "水产")]
    veg_cands = [d for d in pool if d.get("meat_attr") == "素" or d.get("category") == "vegetable_dish"]
    soup_cands = [d for d in pool if d.get("category") == "soup"]

    selected_meat: list[dict] = []
    used_animals: set[str] = set()
    for item in meat_cands:
        if len(selected_meat) >= ratio["meat"]:
            break
        animal = _animal_of(item)
        if animal and animal in used_animals:
            continue
        if animal:
            used_animals.add(animal)
        selected_meat.append(item)

    selected_veg: list[dict] = []
    meat_categories = {d.get("category") for d in selected_meat}
    for item in veg_cands:
        if len(selected_veg) >= ratio["veg"]:
            break
        if item.get("category") in meat_categories:
            continue
        if any(_similarity(item, m) >= 0.8 for m in selected_meat + selected_veg):
            continue
        selected_veg.append(item)

    selected_soup: list[dict] = []
    if want_soup and soup_cands:
        selected_soup = [soup_cands[0]]

    return {
        "ratio": ratio,
        "meat": [{"dish_id": d["dish_id"], "name": d["name"]} for d in selected_meat],
        "veg": [{"dish_id": d["dish_id"], "name": d["name"]} for d in selected_veg],
        "soup": [{"dish_id": d["dish_id"], "name": d["name"]} for d in selected_soup],
    }


def recent_made_ids(user_id: str | None, days: int = 7) -> set[str]:
    """用户近 N 天做过（§8.1 硬过滤）。"""
    from sqlmodel import Session, select

    from app.db.models import UserFeedback
    from app.db.session import get_engine

    if not user_id or not user_id.isdigit():
        return set()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with Session(get_engine()) as session:
        rows = session.exec(
            select(UserFeedback).where(
                UserFeedback.user_id == int(user_id),
                UserFeedback.action == "made",
                UserFeedback.created_at >= cutoff,
            )
        ).all()
    return {r.dish_id for r in rows}
