"""聊天接口（§9.1）：SSE 流式主入口 + 历史会话列表/消息（§9 聊天界面）+ 规则推荐（§10 首页）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import get_current_user, get_current_user_optional, get_settings_dep
from app.core.config import Settings
from app.core.exceptions import AppError, BadRequestError, NotFoundError
from app.db.models import User
from app.db.session import get_session
from app.schemas.chat import ChatStreamRequest, MessageUpdateRequest, SessionUpdateRequest
from app.services import chat_service, recommend_service

router = APIRouter()


class RecommendRequest(BaseModel):
    """规则推荐请求（§10 首页推荐，无 LLM）：与首页选项一一对应。"""

    people: int = Field(default=2, ge=1, le=10)
    meal_time: str = Field(default="晚餐", max_length=16)
    flavors: list[str] = Field(default_factory=list, max_length=8)
    max_time_min: int = Field(default=30, ge=0, le=600)
    want_soup: bool = False
    diversity: bool = False  # 换一批（§10）：同约束下探索采样


@router.post("/recommend")
def rule_recommend(
    body: RecommendRequest,
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    """首页规则推荐（§10，无 LLM / 无向量检索，毫秒级）：千人千面规则打分 + 荤素规划。"""
    return recommend_service.recommend_by_rules(
        people=body.people,
        meal_time=body.meal_time,
        flavors=body.flavors,
        max_time_min=body.max_time_min,
        want_soup=body.want_soup,
        user_id=str(user.id) if user else None,
        diversity=body.diversity,
    )


def _error_frame(code: str, message: str, retryable: bool) -> str:
    payload = json.dumps(
        {"code": code, "message": message, "retryable": retryable},
        ensure_ascii=False,
    )
    return f"event: error\ndata: {payload}\n\n"


@router.get("/chat/sessions")
def list_sessions(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """历史会话列表（§9 聊天界面：左侧会话栏）。"""
    return {"items": chat_service.list_sessions(session, str(user.id))}


@router.get("/chat/sessions/{session_id}/messages")
def get_session_messages(
    session_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """会话消息历史（校验归属，§9）。"""
    items = chat_service.get_session_messages(session, session_id, str(user.id))
    if items is None:
        raise NotFoundError("会话不存在或无权访问")
    return {"items": items}


@router.patch("/chat/messages/{message_id}")
def patch_message(
    message_id: int,
    body: MessageUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """软删除/恢复一组问答（§9 删除单轮问答）：聊天界面隐藏（user+assistant 成对），历史数据保留。

    body.hidden=true 隐藏、false 恢复；入口传该轮任意一条消息 id（数据库 id）。
    """
    if not chat_service.hide_turn(session, message_id, str(user.id), body.hidden):
        raise NotFoundError("消息不存在或无权访问")
    return {"id": message_id}


@router.patch("/chat/sessions/{session_id}")
def patch_session(
    session_id: int,
    body: SessionUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """会话更新（§9）：归档 / 手动重命名（改名后 AI 不再自动覆盖标题）/ 移动分组（§16 决策 17）。"""
    if body.archived is not None and not chat_service.set_session_archived(
        session, session_id, str(user.id), body.archived
    ):
        raise NotFoundError("会话不存在或无权访问")
    if body.title is not None and not chat_service.rename_session(
        session, session_id, str(user.id), body.title
    ):
        raise NotFoundError("会话不存在或无权访问")
    # 显式提供 group（含 null=默认分组）才更新；model_fields_set 区分"未传"与"显式 null"
    if "group" in body.model_fields_set and not chat_service.set_session_group(
        session, session_id, str(user.id), body.group
    ):
        raise NotFoundError("会话不存在或无权访问")
    return {"id": session_id}


@router.post("/chat/sessions/{session_id}/fork")
def fork_session(
    session_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """分叉会话（§9）：复制会话与历史消息为新会话，继续在分支上对话。"""
    new_id = chat_service.fork_session(session, session_id, str(user.id))
    if new_id is None:
        raise NotFoundError("会话不存在或无权访问")
    return {"id": new_id}


@router.get("/chat/sessions/{session_id}/export")
def export_session(
    session_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """会话导出为 Markdown 附件（§10 可选扩展 4）。"""
    from fastapi.responses import Response

    result = chat_service.export_session_markdown(session, session_id, str(user.id))
    if result is None:
        raise NotFoundError("会话不存在或无权访问")
    md_text, filename = result
    return Response(
        content=md_text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    user: User | None = Depends(get_current_user_optional),
):
    message = body.message.strip()
    if not message:
        raise BadRequestError("消息不能为空")
    # 鉴权优先（§9.2）：Bearer token -> 真实 user_id（画像生效）；否则用 body.user_id
    effective_user_id = str(user.id) if user is not None else body.user_id

    async def gen():
        # 兜底 error 帧：响应头已发出后生成器内任何异常都转成 SSE error，
        # 避免浏览器 ERR_INCOMPLETE_CHUNKED_ENCODING（§9.1 错误语义）
        try:
            async for ev in chat_service.stream_agent(
                message,
                user_id=effective_user_id,
                session_id=body.session_id,
                message_id=body.message_id,
                model=body.model,
                strength=body.strength,
                provider=body.provider,
                group=body.group,
                persist=body.persist,
                diversity=body.diversity,
                settings=settings,
                db_session=session,
            ):
                payload = json.dumps(ev["data"], ensure_ascii=False)
                yield f"event: {ev['event']}\ndata: {payload}\n\n"
        except AppError as exc:
            yield _error_frame(exc.code, exc.message, getattr(exc, "retryable", False))
        except Exception as exc:  # noqa: BLE001
            yield _error_frame("INTERNAL_ERROR", f"处理失败: {type(exc).__name__}: {exc}", True)
        finally:
            # §8.5 对话偏好提取：流结束后后台触发（不阻塞响应、失败静默、可配置关闭）
            if settings.preference_extract_enabled and effective_user_id and effective_user_id.isdigit():
                from app.services import preference_extractor
                from app.services.chat_service import get_llm

                preference_extractor.schedule_extract(get_llm(settings), int(effective_user_id))

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 防中间层缓冲（§9.1）
        },
    )
