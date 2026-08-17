"""行为流水服务（§8.2 / §9.3）：反馈写入 + Neo4j 偏好镜像 + 缓存失效 + 画像重算。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.clients.factory import build_graph_store
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models import AnswerCache, DishMeta, UserFavorite, UserFeedback
from app.db.session import get_engine
from app.services import profile_service

VALID_ACTIONS = {"view", "like", "dislike", "rating", "made"}

# 行为 -> Neo4j 用户偏好关系权重（§4.1 用户偏好镜像）
_ACTION_EDGE = {"like": ("LIKES", 1.0), "made": ("MADE", 1.0), "dislike": ("LIKES", -1.0)}


def _mirror_to_neo4j(user_id: int, dish_id: str, action: str) -> None:
    """用户偏好镜像（§4.1）：MERGE User 节点 + LIKES/MADE 边（幂等累积）。"""
    edge, delta = _ACTION_EDGE.get(action, (None, 0.0))
    if edge is None:
        return
    try:
        neo4j = build_graph_store(get_settings())
        neo4j.run(
            f"""
            MATCH (d:Dish {{id: $dish_id}})
            MERGE (u:User {{id: $user_id}})
            MERGE (u)-[r:{edge}]->(d)
            ON CREATE SET r.score = $delta, r.count = 1
            ON MATCH SET r.score = coalesce(r.score, 0) + $delta, r.count = coalesce(r.count, 0) + 1
            """,
            user_id=user_id, dish_id=dish_id, delta=delta,
        )
    except Exception:  # noqa: BLE001 —— 镜像失败不影响主流程
        pass


def _invalidate_user_cache(user_id: int) -> None:
    """反馈后立即清除该用户缓存（§9.3 失效与新鲜度 1）。"""
    with Session(get_engine()) as session:
        for row in session.exec(select(AnswerCache).where(AnswerCache.user_id == user_id)).all():
            session.delete(row)
        session.commit()


def record_feedback(user_id: int, dish_id: str, action: str, rating: int | None = None) -> dict:
    if action not in VALID_ACTIONS:
        raise BadRequestError(f"action 必须为 {sorted(VALID_ACTIONS)}")
    if action == "rating" and (rating is None or not 1 <= rating <= 5):
        raise BadRequestError("rating 需为 1~5")

    with Session(get_engine()) as session:
        if session.get(DishMeta, dish_id) is None:
            raise NotFoundError(f"菜谱 {dish_id} 不存在")
        row = UserFeedback(user_id=user_id, dish_id=dish_id, action=action, rating=rating)
        session.add(row)
        session.commit()
        session.refresh(row)

    _mirror_to_neo4j(user_id, dish_id, action)
    _invalidate_user_cache(user_id)
    profile_service.recompute_from_feedback(user_id)  # §8.2 隐式信号聚合
    return {"id": row.id, "user_id": user_id, "dish_id": dish_id, "action": action, "rating": rating}


def list_feedback(user_id: int, page: int = 1, page_size: int = 20) -> dict:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(UserFeedback)
            .where(UserFeedback.user_id == user_id)
            .order_by(UserFeedback.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        total = len(session.exec(select(UserFeedback).where(UserFeedback.user_id == user_id)).all())
    return {
        "items": [{"id": r.id, "dish_id": r.dish_id, "action": r.action, "rating": r.rating,
                   "created_at": r.created_at.isoformat()} for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


def add_favorite(user_id: int, dish_id: str) -> dict:
    with Session(get_engine()) as session:
        if session.get(DishMeta, dish_id) is None:
            raise NotFoundError(f"菜谱 {dish_id} 不存在")
        exists = session.exec(
            select(UserFavorite).where(
                UserFavorite.user_id == user_id, UserFavorite.dish_id == dish_id
            )
        ).first()
        if exists is None:
            session.add(UserFavorite(user_id=user_id, dish_id=dish_id))
            session.commit()
    record_feedback(user_id, dish_id, "like")  # 收藏即 like 信号（§8.2）
    return {"dish_id": dish_id, "favorited": True}


def remove_favorite(user_id: int, dish_id: str) -> dict:
    with Session(get_engine()) as session:
        exists = session.exec(
            select(UserFavorite).where(
                UserFavorite.user_id == user_id, UserFavorite.dish_id == dish_id
            )
        ).first()
        if exists is not None:
            session.delete(exists)
            session.commit()
    record_feedback(user_id, dish_id, "dislike")  # 取消收藏即 dislike 信号（§8.2 对称）
    return {"dish_id": dish_id, "favorited": False}


def is_favorite(user_id: int, dish_id: str) -> bool:
    """当前用户是否已收藏（§10 详情页收藏状态初始化）。"""
    with Session(get_engine()) as session:
        return (
            session.exec(
                select(UserFavorite).where(
                    UserFavorite.user_id == user_id, UserFavorite.dish_id == dish_id
                )
            ).first()
            is not None
        )


def list_favorites(user_id: int, page: int = 1, page_size: int = 20) -> dict:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(UserFavorite)
            .where(UserFavorite.user_id == user_id)
            .order_by(UserFavorite.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        total = len(session.exec(select(UserFavorite).where(UserFavorite.user_id == user_id)).all())
        names = {}
        for r in rows:
            m = session.get(DishMeta, r.dish_id)
            names[r.dish_id] = m.name if m else r.dish_id
    return {
        "items": [{"dish_id": r.dish_id, "name": names.get(r.dish_id), "created_at": r.created_at.isoformat()} for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


def list_history(user_id: int, limit: int = 50) -> dict:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(UserFeedback)
            .where(UserFeedback.user_id == user_id, UserFeedback.action.in_(["view", "made"]))
            .order_by(UserFeedback.id.desc())
            .limit(limit)
        ).all()
    return {
        "items": [{"dish_id": r.dish_id, "action": r.action, "created_at": r.created_at.isoformat()} for r in rows],
    }
