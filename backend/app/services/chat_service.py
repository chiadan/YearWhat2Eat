"""聊天服务（§9.1 / §9.2 会话）：会话管理、SSE 事件流、message_id 幂等、并发控制。

事件映射（§9.1）：
  status -> sources -> text* -> done | error
  - status: 节点阶段推进（intent/analyze/retrieve/rerank/generate）
  - sources: 检索精排命中（generate 节点产出，正文前先渲染卡片）
  - text: LLM token 增量（stream_mode="custom"）
  - done: {trace_id, session_id, message_id, sources, duration_ms}
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator

from sqlmodel import Session, select

from app.core.clients.embedding import build_embedding_client
from app.core.clients.llm import LLMClient
from app.core.clients.factory import build_graph_store
from app.core.clients.factory import build_vector_store
from app.core.clients.reranker import build_reranker_client
from app.core.config import Settings, get_settings
from app.core.exceptions import ConcurrencyLimitError
from app.db.json_utils import json_load
from app.db.models import ChatMessage, ChatSession
from app.rag.graph import GraphDeps, build_graph
from app.rag.state import (
    ContextState, InputState, OutputState, PlanningState, QueryState, RetrievalState,
)

# 每用户并发上限（§9.1 要点 8：同一用户同时最多 2 个流式请求）
USER_CONCURRENCY = 2
# 会话历史最近轮数（§6.2 上下文管理：最近 10 轮全文）
HISTORY_TURNS = 10

# 强度档位映射（§9 模型强度选择）：温度越低越严谨、max_tokens 越大输出越长
STRENGTH_PARAMS = {
    "fast": {"temperature": 0.7, "max_tokens": 2048},
    "balanced": {"temperature": 0.5, "max_tokens": 2048},
    "deep": {"temperature": 0.3, "max_tokens": 3072},
}

_graph_instance = None
_llm_instance = None
_user_sems: dict[str, asyncio.Semaphore] = {}


def get_graph(settings: Settings | None = None):
    """graph 单例（懒构建；模型在 clients 内懒加载，§12.4）。

    注意：编译后的 CompiledStateGraph 不保留 deps —— LLM 实例单独缓存（get_llm）。
    """
    global _graph_instance, _llm_instance
    if _graph_instance is None:
        settings = settings or get_settings()
        _llm_instance = LLMClient(settings)
        deps = GraphDeps(
            settings=settings,
            llm=_llm_instance,
            embedding=build_embedding_client(settings),
            qdrant=build_vector_store(settings),
            neo4j=build_graph_store(settings),
            reranker=build_reranker_client(settings),
        )
        _graph_instance = build_graph(deps)
    return _graph_instance


def get_llm(settings: Settings | None = None) -> LLMClient:
    """LLM 单例（§9 模型/强度选择 + AI 标题总结共用同一实例）。"""
    global _llm_instance
    if _llm_instance is None:
        get_graph(settings)
    return _llm_instance


def _user_semaphore(user_id: str) -> asyncio.Semaphore:
    sem = _user_sems.get(user_id)
    if sem is None:
        sem = asyncio.Semaphore(USER_CONCURRENCY)
        _user_sems[user_id] = sem
    return sem


def _load_history(session: Session, session_id: int) -> list[dict]:
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.hidden == False)  # noqa: E712 —— 软删除轮次不进上下文（§9）
        .order_by(ChatMessage.id.desc())
        .limit(HISTORY_TURNS * 2)
    ).all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def _load_summary(session: Session, session_id: int) -> str:
    """会话滚动摘要（§6.2 第 7 条）：更早轮次经 LLM 压缩，加载时随最近 10 轮全文一起注入。"""
    row = session.get(ChatSession, session_id)
    return (row.summary or "").strip() if row else ""


def _should_roll_summary(session: Session, session_id: int) -> bool:
    """是否触发滚动摘要（§6.2）：消息数超过最近 10 轮窗口，且按 4 条节流（与标题总结同节奏）。"""
    count = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    ).all()
    return len(count) > HISTORY_TURNS * 2 and len(count) % 4 == 0


async def _roll_summary(llm: object, session_id: int) -> None:
    """滚动摘要（§6.2 第 7 条）：把"最近 10 轮窗口之外"的最旧消息 + 旧摘要压缩成新摘要。

    - 由 stream_agent done 后 create_task 后台执行（独立 Session）；失败静默（保持原摘要）
    - 不删除消息行（聊天历史展示保持完整）；加载时用 summary + 最近 10 轮全文
    """
    try:
        from app.db.session import get_engine

        engine = get_engine()
        with Session(engine) as db:
            rows = db.exec(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.asc())
            ).all()
            if len(rows) <= HISTORY_TURNS * 2:
                return
            sess = db.get(ChatSession, session_id)
            old = (sess.summary or "").strip() if sess else ""
            batch = rows[: len(rows) - HISTORY_TURNS * 2]  # 窗口外的最旧消息
            lines = [f"{r.role}: {r.content[:120]}" for r in batch]
            prompt = (
                "你是会话摘要器。把以下对话（含已有摘要与新增的早期对话）压缩成 200 字以内的中文摘要，"
                "保留：用户口味偏好、忌口、人数/场景约束、已讨论过的菜与结论、未完成的请求。"
                "直接输出摘要文本，不要标题、不要解释：\n"
                + (f"已有摘要：\n{old}\n\n" if old else "")
                + "\n".join(lines)
            )
            result = await llm.complete(prompt, temperature=0.1)
            summary = (result.content or "").strip()[:2000]
            if summary and sess is not None:
                sess.summary = summary
                db.add(sess)
                db.commit()
    except Exception:  # noqa: BLE001 —— 摘要失败不影响主流程
        logger.warning("滚动摘要失败，跳过 | session=%s", session_id)


def _message_exists(session: Session, message_id: str | None) -> bool:
    if not message_id:
        return False
    return session.exec(
        select(ChatMessage).where(ChatMessage.message_id == message_id).limit(1)
    ).first() is not None


def save_message(
    session: Session,
    *,
    session_id: int,
    role: str,
    content: str,
    sources: list | None = None,
    message_id: str | None = None,
) -> ChatMessage:
    """保存消息（message_id 幂等：已存在则跳过，§9.1 要点 7）。

    标题由 AI 自动总结（§9，见 stream_agent done 后的 _auto_title 触发）。
    """
    if _message_exists(session, message_id):
        return session.exec(
            select(ChatMessage).where(ChatMessage.message_id == message_id)
        ).first()
    row = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        sources=json.dumps(sources or [], ensure_ascii=False),
        message_id=message_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def _auto_title(llm: object, session_id: int) -> None:
    """AI 自动总结会话标题（§9）：最近 6 条对话 -> 12 字以内标题。

    由 stream_agent done 后 create_task 后台执行（独立 Session，不依赖请求生命周期）；
    失败静默（标题保持原样）。
    """
    try:
        from app.db.session import get_engine

        engine = get_engine()
        with Session(engine) as db:
            rows = db.exec(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())
                .limit(6)
            ).all()
            lines = [f"{r.role}: {r.content[:100]}" for r in reversed(rows)]
            if not lines:
                return
            prompt = (
                "根据以下对话内容，给这次会话起一个 12 字以内的简短标题，"
                "直接输出标题文本，不要引号、标点、解释：\n" + "\n".join(lines)
            )
            result = await llm.complete(prompt, temperature=0.1)
            title = result.content.strip().strip('"“”').splitlines()[0][:12].strip()
            if not title:
                return
            sess = db.get(ChatSession, session_id)
            if sess is not None:
                sess.title = title
                db.add(sess)
                db.commit()
    except Exception:  # noqa: BLE001 —— 标题总结失败不影响主流程
        pass


def _should_auto_title(db_session: Session, session_id: int, sess_row: ChatSession) -> bool:
    """是否触发标题自动总结：AI 仅首轮命名一次（§9 更新）。

    首轮（user + assistant 落库）后触发一次精炼总结（覆盖"提问即命名"的默认标题）；
    此后 title_auto 置 0 锁定——后续标题由用户手动修改，AI 不再自动覆盖。
    """
    if not sess_row.title_auto:
        return False
    count = db_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    ).all()
    if len(count) <= 2:  # 首轮消息（user + assistant）
        return True
    # 非首轮：锁定为手动管理，AI 不再更新标题
    sess_row.title_auto = False
    db_session.add(sess_row)
    db_session.commit()
    return False


def rename_session(session: Session, session_id: int, user_id: str | None, title: str) -> bool:
    """手动重命名会话（§9）：改名后 title_auto=0，AI 不再自动覆盖。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    sess = session.get(ChatSession, session_id)
    if sess is None or sess.user_id != uid:
        return False
    sess.title = title.strip()[:40] or sess.title
    sess.title_auto = False
    session.add(sess)
    session.commit()
    return True


def ensure_session(
    session: Session,
    user_id: str | None,
    session_id: int | None,
    group: str | None = None,
) -> ChatSession:
    """获取/创建会话。创建时可用 group 指定分组（§16 决策 17：分组内新建会话）；已有会话忽略。"""
    if session_id is not None:
        row = session.get(ChatSession, session_id)
        if row is not None:
            return row
    value = (group or "").strip()[:40] or None
    row = ChatSession(user_id=int(user_id) if user_id and user_id.isdigit() else 0, title="新会话", group=value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_sessions(session: Session, user_id: str | None) -> list[dict]:
    """历史会话列表（§9 聊天界面左侧栏）：含最后消息摘要、归档标记与分组（§16 决策 17）。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    rows = session.exec(
        select(ChatSession)
        .where(ChatSession.user_id == uid)
        .order_by(ChatSession.id.desc())
        .limit(100)
    ).all()
    items: list[dict] = []
    for r in rows:
        last = session.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == r.id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).first()
        msg_count = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == r.id)
        ).all()
        items.append(
            {
                "id": r.id,
                "title": r.title,
                "archived": bool(r.archived),
                "group": r.group,  # NULL = 默认分组（§16 决策 17）
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_message": last.content[:40] if last else None,
                "message_count": len(msg_count),
            }
        )
    return items


def set_session_group(
    session: Session,
    session_id: int,
    user_id: str | None,
    group: str | None,
) -> bool:
    """移动会话到分组（§16 决策 17）：group=None 移回默认分组；空串视为 None。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    sess = session.get(ChatSession, session_id)
    if sess is None or sess.user_id != uid:
        return False
    value = (group or "").strip()[:40] or None
    sess.group = value
    session.add(sess)
    session.commit()
    return True


def set_session_archived(
    session: Session,
    session_id: int,
    user_id: str | None,
    archived: bool,
) -> bool:
    """归档/取消归档会话（归属校验，§9 归档对话）。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    sess = session.get(ChatSession, session_id)
    if sess is None or sess.user_id != uid:
        return False
    sess.archived = archived
    session.add(sess)
    session.commit()
    return True


def fork_session(session: Session, session_id: int, user_id: str | None) -> int | None:
    """分叉会话（§9 分叉会话）：复制会话与全部历史消息为新会话，返回新 id。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    src = session.get(ChatSession, session_id)
    if src is None or src.user_id != uid:
        return None
    new = ChatSession(user_id=uid, title=f"{src.title}（分叉）", group=src.group)
    session.add(new)
    session.commit()
    session.refresh(new)
    msgs = session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == src.id)
        .order_by(ChatMessage.id.asc())
    ).all()
    for m in msgs:
        session.add(
            ChatMessage(
                session_id=new.id,
                role=m.role,
                content=m.content,
                sources=m.sources,
                message_id=None,  # 新消息 id（幂等键不复用）
                created_at=m.created_at,
            )
        )
    session.commit()
    return new.id


def get_session_messages(session: Session, session_id: int, user_id: str | None) -> list[dict] | None:
    """会话消息历史（校验归属，§9）；不存在或非本人返回 None。软删除（hidden）的轮次不返回。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    sess = session.get(ChatSession, session_id)
    if sess is None or sess.user_id != uid:
        return None
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.hidden == False)  # noqa: E712
        .order_by(ChatMessage.id.asc())
        .limit(200)
    ).all()
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "sources": json_load(r.sources, []),
        }
        for r in rows
    ]


def hide_turn(
    session: Session,
    message_id: int,
    user_id: str | None,
    hidden: bool,
) -> bool:
    """软删除/恢复一组问答（§9）：user 消息与其配对 assistant 消息成对隐藏。

    聊天界面不显示（加载/上下文均排除），数据库行保留（历史与导出仍可见）。
    入口传任意一条消息 id：user 消息 -> 配对下一条 assistant；assistant -> 配对上一条 user。
    """
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    msg = session.get(ChatMessage, message_id)
    if msg is None:
        return False
    sess = session.get(ChatSession, msg.session_id)
    if sess is None or sess.user_id != uid:
        return False
    pair_ids = [msg.id]
    # 配对消息：同 session 内相邻的另一半
    if msg.role == "user":
        partner = session.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == msg.session_id, ChatMessage.id > msg.id)
            .order_by(ChatMessage.id.asc())
            .limit(1)
        ).first()
    else:
        partner = session.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == msg.session_id, ChatMessage.id < msg.id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).first()
    if partner is not None and partner.role != msg.role:
        pair_ids.append(partner.id)
    for pid in pair_ids:
        row = session.get(ChatMessage, pid)
        if row is not None:
            row.hidden = hidden
            session.add(row)
    session.commit()
    return True


def export_session_markdown(
    session: Session,
    session_id: int,
    user_id: str | None,
) -> tuple[str, str] | None:
    """会话导出为 Markdown（§10 可选扩展 4）：返回 (markdown 文本, 文件名)；归属校验失败返回 None。"""
    uid = int(user_id) if user_id and user_id.isdigit() else 0
    sess = session.get(ChatSession, session_id)
    if sess is None or sess.user_id != uid:
        return None
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
    ).all()

    lines = [
        f"# {sess.title}",
        "",
        f"> 创建时间：{sess.created_at.strftime('%Y-%m-%d %H:%M') if sess.created_at else '-'} · 共 {len(rows)} 条消息",
        "",
    ]
    for r in rows:
        lines.append(f"## {'用户' if r.role == 'user' else '助手'}")
        lines.append("")
        lines.append(r.content)
        sources = json_load(r.sources, [])
        if sources:
            names = "、".join(str(s.get("dish_name") or s.get("name") or s.get("dish_id")) for s in sources[:10])
            lines.append("")
            lines.append(f"*参考菜谱：{names}*")
        lines.append("")

    date = sess.created_at.strftime("%Y%m%d") if sess.created_at else "chat"
    return "\n".join(lines), f"chat-{session_id}-{date}.md"


def _load_profile(session: Session, user_id: str | None) -> dict | None:
    """加载画像（§8，M4）：ContextState.profile 供 rank_fuse / rule_filter 使用。"""
    if not user_id or not user_id.isdigit():
        return None
    from app.services import profile_service

    try:
        return profile_service.profile_to_dict(profile_service.get_profile(int(user_id)))
    except Exception:  # noqa: BLE001
        return None


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": data}


def _output_as_dict(output) -> dict:
    """兼容 dict 与 Pydantic 实例（节点 update 的 output 可能是 OutputState）。"""
    if output is None:
        return {}
    if isinstance(output, dict):
        return output
    return output.model_dump() if hasattr(output, "model_dump") else dict(output)


async def stream_agent(
    query: str,
    *,
    user_id: str | None = None,
    session_id: int | None = None,
    message_id: str | None = None,
    model: str | None = None,
    strength: str | None = None,
    provider: str | None = None,
    group: str | None = None,
    persist: bool = True,
    diversity: bool = False,
    settings: Settings | None = None,
    db_session: Session | None = None,
) -> AsyncIterator[dict]:
    """运行 Agent 并产出 SSE 事件（§9.1）。db_session 由调用方提供（FastAPI 依赖）。

    model/strength（§9 模型/强度选择）：作用于生成路径（LLMClient.set_generation），
    结构化节点（意图/扩写/约束）不受影响。
    provider（§10 多 Provider）：deepseek=默认（系统/BYOK Key）；其他=用户自定义接入配置。
    group（§16 决策 17）：新建会话（session_id 为空）时指定分组，null=默认分组。
    persist（§10 首页推荐）：false=一次性查询——不创建会话、不落库、无历史（done 帧 session_id=None）。
    diversity（§10 换一批）：true 时 rank_fuse 探索率提升，同约束下产出不同结果。
    """
    settings = settings or get_settings()
    trace_id = uuid.uuid4().hex[:12]
    started = time.monotonic()

    # BYOK（§10）：该用户配置了自定义 DeepSeek Key 则本请求使用之（contextvars 按请求隔离）
    from app.core.clients.llm import (
        reset_request_api_key,
        reset_request_provider,
        set_request_api_key,
        set_request_provider,
    )
    from app.services import auth_service

    _key_token = None
    _provider_token = None
    if user_id and user_id.isdigit():
        uid = int(user_id)
        # 自定义 Provider（§10）：非 deepseek 名称 -> 用户接入配置
        if provider and provider != "deepseek":
            cfg = auth_service.get_user_provider(uid, provider)
            if cfg:
                _provider_token = set_request_provider(cfg)
        # DeepSeek：BYOK 自定义 Key
        user_key = auth_service.get_user_api_key_decrypted(uid)
        if user_key:
            _key_token = set_request_api_key(user_key)

    # 模型/强度 -> 生成参数（§9）
    if model or strength:
        params = STRENGTH_PARAMS.get(strength or "", {})
        get_llm(settings).set_generation(
            model=model,
            temperature=params.get("temperature"),
            max_tokens=params.get("max_tokens"),
        )

    # 并发控制（§9.1 要点 8）：非阻塞获取，占满即 429
    # 注意：不能用 wait_for(acquire(), timeout=0) —— timeout=0 会立即超时导致误报 429；
    # 单事件循环内检查 _value 后 acquire 无竞态（同线程无抢占）
    sem = _user_semaphore(user_id or "anonymous")
    acquired = False
    if sem._value <= 0:  # noqa: SLF001
        raise ConcurrencyLimitError("同时进行的对话过多，请稍后再试")
    await sem.acquire()
    acquired = True  # acquire 被取消（客户端断开）时不 release，避免信号量泄漏

    try:
        # 会话与历史（group 仅新建会话生效，§16 决策 17）
        # persist=false（一次性查询，§10 首页推荐）：不创建会话、无历史
        chat_session = None
        history: list[dict] = []
        summary_text = ""
        if persist:
            chat_session = ensure_session(db_session, user_id, session_id, group=group)
            history = _load_history(db_session, chat_session.id)
            summary_text = _load_summary(db_session, chat_session.id)

        # 幂等：该 message_id 已处理过则直接返回（§9.1 要点 7；一次性查询不校验）
        if persist and _message_exists(db_session, message_id):
            yield _sse("status", {"trace_id": trace_id, "stage": "intent"})
            yield _sse("error", {"code": "DUPLICATE_MESSAGE", "message": "该消息已处理过", "retryable": False})
            return

        init = {
            "input": InputState(query=query, user_id=user_id, session_id=str(chat_session.id) if chat_session else None, message_id=message_id),
            "context": ContextState(
                session_history=history,
                summary=summary_text,  # 滚动摘要（§6.2 第 7 条）
                profile=_load_profile(db_session, user_id),
            ),
            "query": QueryState(diversity=diversity),
            "retrieval": RetrievalState(),
            "planning": PlanningState(),
            "output": OutputState(),
        }

        graph = get_graph(settings)
        last_output: dict | None = None
        first_token = True
        try:
            async for mode, chunk in graph.astream(
                init,
                stream_mode=["updates", "custom"],
                config={"recursion_limit": 25},
            ):
                if mode == "custom":
                    if first_token:
                        yield _sse("status", {"trace_id": trace_id, "stage": "generate"})
                        first_token = False
                    yield _sse("text", {"delta": chunk})
                    continue

                # updates：节点级事件
                for node, update in chunk.items():
                    stage = {
                        "intent_router": "intent",
                        "query_analyzer": "analyze",
                        "retrieve": "retrieve",
                        "rerank": "rerank",
                        "planner": "plan",
                    }.get(node)
                    if stage:
                        yield _sse("status", {"trace_id": trace_id, "stage": stage})
                    if node == "generate":
                        output = _output_as_dict(update.get("output"))
                        last_output = output
                        for ev in output.get("events") or []:
                            if ev.get("type") == "sources":
                                yield _sse("sources", {"items": ev.get("items", [])})
                            elif ev.get("type") == "plan":
                                yield _sse("plan", {"plan": ev.get("plan")})

            output = last_output or {}
            answer = output.get("answer") or ""
            sources = output.get("sources") or []
            duration_ms = int((time.monotonic() - started) * 1000)

            # 落库（user + assistant，message_id 幂等；id 供前端软删除本组问答，§9）
            # 落库（user + assistant，message_id 幂等；id 供前端软删除本组问答，§9）
            # persist=false（一次性查询，§10 首页推荐）：不落库、不命名、不总结
            user_msg = None
            assistant_msg = None
            sess_row = None
            if persist:
                user_msg = save_message(db_session, session_id=chat_session.id, role="user",
                                         content=query, message_id=message_id)
                assistant_msg = save_message(db_session, session_id=chat_session.id, role="assistant",
                                              content=answer, sources=sources)

                # 首条消息默认标题（§9 提问即命名）：新会话未命名时用首条消息内容（前 20 字），
                # 前端立即可见有意义的标题；AI 总结（_auto_title）异步覆盖
                sess_row = db_session.get(ChatSession, chat_session.id)
                if sess_row is not None and sess_row.title_auto and sess_row.title == "新会话":
                    sess_row.title = query.strip()[:20] or "新会话"
                    db_session.add(sess_row)
                    db_session.commit()

                # AI 自动总结标题（§9）：仅首轮命名一次（_should_auto_title 判定），
                # 此后 title_auto=0 锁定，标题由用户手动管理；后台任务不阻塞 SSE
                if sess_row is not None and _should_auto_title(db_session, chat_session.id, sess_row):
                    asyncio.create_task(_auto_title(get_llm(settings), chat_session.id))

                # 滚动摘要（§6.2 第 7 条）：消息数超窗口后，最旧批次压缩进 summary（后台、失败静默）
                if _should_roll_summary(db_session, chat_session.id):
                    asyncio.create_task(_roll_summary(get_llm(settings), chat_session.id))

            yield _sse("done", {
                "trace_id": trace_id,
                "session_id": chat_session.id if chat_session else None,
                "message_id": message_id,
                "sources": sources,
                "plan": output.get("plan"),
                # 本轮问答的数据库 id（§9 软删除入口：前端删除本组问答用）
                "message_ids": {
                    "user": user_msg.id if user_msg else None,
                    "assistant": assistant_msg.id if assistant_msg else None,
                },
                "duration_ms": duration_ms,
            })
        except Exception as exc:  # noqa: BLE001 —— SSE 场景统一 error 帧
            import traceback

            traceback.print_exc()
            yield _sse("error", {
                "code": "INTERNAL_ERROR",
                "message": f"处理失败: {type(exc).__name__}: {exc}",
                "retryable": True,
            })
    finally:
        # 客户端断开（GeneratorExit）也会走到这里，仅释放实际持有的信号量（§9.1 要点 8）
        if acquired:
            sem.release()
        # BYOK / 多 Provider（§10）：恢复请求级上下文
        if _key_token is not None:
            reset_request_api_key(_key_token)
        if _provider_token is not None:
            reset_request_provider(_provider_token)
