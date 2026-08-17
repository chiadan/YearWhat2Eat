"""首页规则推荐服务（§10 推荐界面，无 LLM）：千人千面规则匹配，毫秒级响应。

链路（纯规则，不调 LLM / 不检索向量 / 不精排）：
  全量菜谱（SQLite dish_meta，§3 业务真源）
  -> apply_hard_filters（§6.5 召回③：忌口/素食/难度/时长/工具/近7天做过，画像+请求约束合并）
  -> personal_score 千人千面打分（§6.5 personal：口味/难度/工具/目标，画像动态配置）
  -> 约束口味匹配加权 + 换一批探索采样
  -> plan_menu 荤素规划（§6.5 三：荤素公式 + 动物多样 + MMR）
  -> plan + sources（可点击跳详情）

画像来源（§8）：用户问卷 + 行为学习（personalization 规则），随用户配置动态生效。
"""
from __future__ import annotations

import random

from app.db.json_utils import json_load
from app.db.models import DishMeta
from app.db.session import get_engine
from app.rag.nodes.rule_filter import _load_catalog
from app.rag.rule_engine import apply_hard_filters, plan_menu, recent_made_ids
from app.services import profile_service
from app.services.personalization import personal_score
from sqlmodel import Session, select


def _load_profile_dict(user_id: str | None) -> dict | None:
    """画像 dict（§8）；游客/无画像 -> None（中性打分）。"""
    if not user_id or not user_id.isdigit():
        return None
    try:
        return profile_service.profile_to_dict(profile_service.get_profile(int(user_id)))
    except Exception:  # noqa: BLE001
        return None


def recommend_by_rules(
    *,
    people: int,
    meal_time: str,
    flavors: list[str],
    max_time_min: int,
    want_soup: bool,
    user_id: str | None,
    diversity: bool,
) -> dict:
    """规则推荐（§10）：返回 {plan, sources, reason}。

    diversity=true（换一批）：对候选池做随机偏移采样，同约束下产出不同结果。
    """
    catalog = _load_catalog()
    profile_obj = _load_profile_dict(user_id)
    profile = profile_obj or {}  # 游客：空画像（中性打分 + 仅请求约束）

    # 千人千面硬过滤（§6.5 召回③）：画像（忌口/素食/技能/工具/近7天做过）+ 请求约束（时长/口味）
    rule_hits, _hard_filtered = apply_hard_filters(
        catalog,
        avoids=profile.get("avoid_list") or [],
        diet_type=profile.get("diet_type"),
        skill_level=profile.get("skill_level", "新手"),
        tools=set(profile.get("tools") or []),
        made_ids=recent_made_ids(user_id),
        max_time_min=max_time_min or None,
        flavors=flavors,
    )
    if not rule_hits:
        # 约束过严：放宽到仅忌口过滤，保证有推荐
        rule_hits, _ = apply_hard_filters(
            catalog,
            avoids=profile.get("avoid_list") or [],
            diet_type=None,
            skill_level=None,
            tools=set(),
            made_ids=set(),
            max_time_min=None,
            flavors=[],
        )

    # 千人千面打分（§6.5 personal + 请求口味匹配）
    for d in rule_hits:
        personal = personal_score(d, profile_obj)
        flavor_hit = 0.0
        if flavors:
            dish_flavors = set(d.get("flavors") or [])
            hit = sum(1.0 for f in flavors if f in dish_flavors)
            flavor_hit = 1.0 if hit > 0 else -1.0  # 请求口味命中 +1 / 完全不沾 -1
        time_hit = 0.0
        if max_time_min and d.get("time_est") is not None:
            time_hit = 0.5 if d["time_est"] <= max_time_min else -1.0
        # 综合分：千人千面（0.6）+ 请求约束匹配（0.4）
        d["rule_score"] = 0.6 * personal + 0.4 * (1.0 + flavor_hit + time_hit) / 3.0

    rule_hits.sort(key=lambda x: x["rule_score"], reverse=True)

    # 换一批（§10）：候选池随机偏移，70% 概率调整排名（避免每次都相同）
    if diversity and len(rule_hits) > 5:
        for _ in range(2):
            a, b = random.randint(0, min(len(rule_hits) - 1, 19)), random.randint(0, min(len(rule_hits) - 1, 19))
            rule_hits[a], rule_hits[b] = rule_hits[b], rule_hits[a]

    plan = plan_menu(rule_hits, max(people, 1), want_soup=want_soup, score_key="rule_score")

    # 参考菜谱（§9.1 通用引用）：今日菜单中的菜
    sources = [
        {"ref": i, "dish_id": d["dish_id"], "name": d["name"], "source": "rule", "score": 0}
        for i, d in enumerate(
            list(plan["meat"]) + list(plan["veg"]) + list(plan["soup"]),
            start=1,
        )
    ]
    reason = (
        f"根据你的口味偏好（{'、'.join(flavors) if flavors else '均衡'}）与画像"
        f"（{profile.get('skill_level', '新手') if profile else '默认'}水平），"
        f"从 {len(rule_hits)} 道符合约束的菜中选出今日菜单。"
    )
    return {"plan": plan, "sources": sources, "reason": reason}
