"""画像服务（§8）：读写问卷画像 + 行为聚合重算（§8.2 隐式信号）。

sqlmodel 依赖函数内懒加载，保证 DEFAULT_PROFILE 等纯逻辑可独立单测（§13.4）。
"""
from __future__ import annotations

from app.core.exceptions import NotFoundError
from app.db.json_utils import json_load

# §8.1 问卷默认值
DEFAULT_PROFILE = {
    "flavor_spicy": 3, "flavor_sweet": 3, "flavor_sour": 3, "flavor_light": 3,
    "avoid_list": [], "diet_type": "无限制", "skill_level": "新手",
    "tools": [], "family_size": 2, "budget_level": "中等", "goal": "均衡",
}


def get_profile(user_id: int) -> UserProfile:
    from sqlmodel import Session

    from app.db.models import UserProfile
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        row = session.get(UserProfile, user_id)
        if row is None:
            row = UserProfile(user_id=user_id)
            session.add(row)
            session.commit()
            session.refresh(row)
        return row


def update_profile(user_id: int, data: dict) -> UserProfile:
    """更新画像（§8.1 问卷字段白名单）。"""
    from sqlmodel import Session

    from app.db.models import UserProfile
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        row = session.get(UserProfile, user_id)
        if row is None:
            row = UserProfile(user_id=user_id)
            session.add(row)
        allowed = {
            "flavor_spicy", "flavor_sweet", "flavor_sour", "flavor_light",
            "avoid_list", "diet_type", "skill_level", "tools",
            "family_size", "budget_level", "goal",
        }
        for key, value in data.items():
            if key in allowed:
                setattr(row, key, value)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def profile_to_dict(profile: UserProfile) -> dict:
    return {
        "flavor_spicy": profile.flavor_spicy,
        "flavor_sweet": profile.flavor_sweet,
        "flavor_sour": profile.flavor_sour,
        "flavor_light": profile.flavor_light,
        "avoid_list": json_load(profile.avoid_list, []),
        "diet_type": profile.diet_type,
        "skill_level": profile.skill_level,
        "tools": json_load(profile.tools, []),
        "family_size": profile.family_size,
        "budget_level": profile.budget_level,
        "goal": profile.goal,
        # §8.5 对话偏好提取来源日志（[{type, value, confidence, source, created_at}]）
        "preference_log": json_load(profile.preference_log, []),
    }


def recompute_from_feedback(user_id: int) -> None:
    """行为聚合（§8.2）：最近 30 天行为 -> 调整口味/菜系权重（轻量版，M4）。

    简化实现：高频"辣"相关行为上调 spicy 1 档（上限 5）；👎 下调。
    完整版（菜系偏好/衰减）在 M4 后按行为流水扩展。
    """
    from sqlmodel import Session, select

    from app.db.models import UserFeedback, UserProfile
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        rows = session.exec(
            select(UserFeedback).where(UserFeedback.user_id == user_id)
        ).all()
        profile = session.get(UserProfile, user_id)
        if profile is None or not rows:
            return
        # 简化：like/made 与 dislike 计数驱动口味微调（占位实现，M4 后细化）
        likes = sum(1 for r in rows if r.action in ("like", "made"))
        dislikes = sum(1 for r in rows if r.action == "dislike")
        if likes >= 3 and profile.flavor_spicy < 5:
            profile.flavor_spicy += 1
        if dislikes >= 3 and profile.flavor_spicy > 1:
            profile.flavor_spicy -= 1
        session.add(profile)
        session.commit()


def ensure_user(user_id: int) -> UserProfile:
    return get_profile(user_id)
