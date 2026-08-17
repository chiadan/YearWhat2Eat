"""用户与画像接口（§9）：me / profile / feedback / favorites / history / 注销 / 用量统计 / BYOK Key。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.exceptions import NotFoundError
from app.db.models import ChatMessage, ChatSession, LLMUsage, RefreshToken, User, UserFavorite, UserFeedback, UserProfile
from app.db.session import get_engine, get_session
from app.schemas.user import FeedbackRequest, ProfileUpdateRequest
from app.services import feedback_service, profile_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/me/profile")
def get_my_profile(user: User = Depends(get_current_user)) -> dict:
    profile = profile_service.get_profile(user.id)
    return profile_service.profile_to_dict(profile)


@router.put("/me/profile")
def put_my_profile(
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
) -> dict:
    data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    profile = profile_service.update_profile(user.id, data)
    return profile_service.profile_to_dict(profile)


@router.post("/me/feedback")
def post_feedback(
    body: FeedbackRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """行为流水（§8.2）：view/like/dislike/rating/made -> 画像聚合 + Neo4j 镜像 + 缓存失效。"""
    return feedback_service.record_feedback(user.id, body.dish_id, body.action, body.rating)


@router.get("/me/feedback")
def get_feedback(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
) -> dict:
    return feedback_service.list_feedback(user.id, page, min(page_size, 100))


@router.get("/me/favorites")
def get_favorites(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
) -> dict:
    return feedback_service.list_favorites(user.id, page, min(page_size, 100))


@router.post("/me/favorites/{dish_id}")
def add_favorite(dish_id: str, user: User = Depends(get_current_user)) -> dict:
    return feedback_service.add_favorite(user.id, dish_id)


@router.delete("/me/favorites/{dish_id}")
def delete_favorite(dish_id: str, user: User = Depends(get_current_user)) -> dict:
    return feedback_service.remove_favorite(user.id, dish_id)


@router.get("/me/history")
def get_history(limit: int = 50, user: User = Depends(get_current_user)) -> dict:
    return feedback_service.list_history(user.id, min(limit, 200))


@router.get("/me/usage")
def get_usage(user: User = Depends(get_current_user)) -> dict:
    """AI 用量统计（§9 Profile AI 配置）：今日 / 近 7 天 / 累计 token，按模型与节点拆分。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)

    def agg_since(cutoff: datetime) -> dict:
        rows = session_exec_usage(cutoff, user.id)
        return {
            "prompt_tokens": sum(r.prompt_tokens for r in rows),
            "completion_tokens": sum(r.completion_tokens for r in rows),
        }

    def session_exec_usage(cutoff: datetime, uid: int):
        with Session(get_engine()) as s:
            return s.exec(
                select(LLMUsage).where(
                    LLMUsage.user_id == uid,
                    LLMUsage.created_at >= cutoff,
                )
            ).all()

    today = agg_since(today_start)
    week_rows = session_exec_usage(week_start, user.id)
    all_rows = session_exec_usage(datetime(2000, 1, 1), user.id)

    # 近 7 天按日聚合
    by_day: dict[str, int] = {((today_start - timedelta(days=i)).strftime("%m-%d")): 0 for i in range(6, -1, -1)}
    for r in week_rows:
        key = r.created_at.strftime("%m-%d")
        if key in by_day:
            by_day[key] += r.prompt_tokens + r.completion_tokens

    # 按模型 / 按节点
    by_model: dict[str, dict] = {}
    by_node: dict[str, dict] = {}
    for r in all_rows:
        m = by_model.setdefault(r.model or "unknown", {"prompt_tokens": 0, "completion_tokens": 0})
        m["prompt_tokens"] += r.prompt_tokens
        m["completion_tokens"] += r.completion_tokens
        n = by_node.setdefault(r.node or "unknown", {"prompt_tokens": 0, "completion_tokens": 0})
        n["prompt_tokens"] += r.prompt_tokens
        n["completion_tokens"] += r.completion_tokens

    return {
        "today": today,
        "week_total": {"prompt_tokens": sum(r.prompt_tokens for r in week_rows),
                       "completion_tokens": sum(r.completion_tokens for r in week_rows)},
        "total": {"prompt_tokens": sum(r.prompt_tokens for r in all_rows),
                  "completion_tokens": sum(r.completion_tokens for r in all_rows)},
        "by_day": [{"date": d, "tokens": v} for d, v in by_day.items()],
        "by_model": [{"model": k, **v} for k, v in by_model.items()],
        "by_node": [{"node": k, **v} for k, v in by_node.items()],
    }


# ── BYOK（§10）：用户自定义 DeepSeek API Key ────────────────

class AiKeySetRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)


@router.get("/me/ai-key")
def get_ai_key(user: User = Depends(get_current_user)) -> dict:
    """查询 BYOK 状态（§10）：只返回 has_custom_key，绝不返回明文。"""
    from app.services import auth_service

    return {"has_custom_key": auth_service.has_user_api_key(user.id)}


@router.put("/me/ai-key")
def put_ai_key(body: AiKeySetRequest, user: User = Depends(get_current_user)) -> dict:
    """设置用户自定义 DeepSeek API Key（§10 BYOK，Fernet 加密存储）。"""
    from app.services import auth_service

    auth_service.set_user_api_key(user.id, body.api_key.strip())
    return {"has_custom_key": True}


@router.delete("/me/ai-key", status_code=200)
def delete_ai_key(user: User = Depends(get_current_user)) -> dict:
    """清除自定义 Key，回退系统 .env Key（§10 BYOK）。"""
    from app.services import auth_service

    auth_service.clear_user_api_key(user.id)
    return {"has_custom_key": False}


class AiProvidersRequest(BaseModel):
    """多 Provider 接入配置（§10）：api_key 提交时加密存储，回显脱敏。"""

    providers: list[dict] = Field(default_factory=list)


@router.get("/me/ai-providers")
def get_ai_providers(user: User = Depends(get_current_user)) -> dict:
    """查询自定义接入配置（§10 多 Provider，脱敏返回）。"""
    from app.services import auth_service

    return {"providers": auth_service.get_user_providers(user.id)}


@router.put("/me/ai-providers")
def put_ai_providers(body: AiProvidersRequest, user: User = Depends(get_current_user)) -> dict:
    """保存自定义接入配置（§10：OpenAI 兼容 / Anthropic；api_key 加密存储）。"""
    from app.services import auth_service

    return {"providers": auth_service.set_user_providers(user.id, body.providers)}


@router.delete("/me", status_code=204)
def delete_me(user: User = Depends(get_current_user)) -> None:
    """注销账号（§9 个保法）：删除画像/行为/收藏/会话/消息/refresh token。"""
    with Session(get_engine()) as session:
        uid = user.id
        for model in (UserProfile, UserFeedback, UserFavorite, RefreshToken):
            for row in session.exec(select(model).where(model.user_id == uid)).all():
                session.delete(row)
        for sess in session.exec(select(ChatSession).where(ChatSession.user_id == uid)).all():
            for msg in session.exec(select(ChatMessage).where(ChatMessage.session_id == sess.id)).all():
                session.delete(msg)
            session.delete(sess)
        session.delete(session.get(User, uid))
        session.commit()
