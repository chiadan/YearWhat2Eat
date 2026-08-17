"""对话偏好提取（§8.5 进阶版）：聊天 -> LLM 结构化信号 -> 合并画像（带来源与置信度）。

触发：/chat/stream 回答流结束后后台任务调用 extract_from_recent_chat（不阻塞、失败静默）；
开关：PREFERENCE_EXTRACT_ENABLED（.env，默认 true）。
信号类型：avoid / flavor / cuisine / tool / diet / skill；confidence < 0.6 丢弃；
合并幂等：已有同 type+value 信号不重复写入；avoid/tool 并集、flavor 维度微调、
diet/skill 高置信（>=0.8）覆盖、cuisine 仅记日志（personal_score 菜系加分消费）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db.json_utils import json_load
from app.db.models import AnswerCache, ChatMessage, ChatSession, UserProfile
from app.db.session import get_engine
from app.rag.prompts import get_prompt

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.6
HIGH_CONFIDENCE = 0.8
MSG_LIMIT = 10
_FLAVOR_FIELDS = {"辣": "flavor_spicy", "甜": "flavor_sweet", "酸": "flavor_sour", "清淡": "flavor_light"}
_VALID_TYPES = {"avoid", "flavor", "cuisine", "tool", "diet", "skill"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _profile_summary(profile: UserProfile) -> dict:
    """画像摘要（给 LLM 去重用，§8.5）。"""
    return {
        "avoid_list": json_load(profile.avoid_list, []),
        "flavor": {k: getattr(profile, v, 3) for k, v in _FLAVOR_FIELDS.items()},
        "diet_type": profile.diet_type,
        "skill_level": profile.skill_level,
        "tools": json_load(profile.tools, []),
        "preference_log": json_load(profile.preference_log, []),
    }


def _recent_user_messages(user_id: int, limit: int = MSG_LIMIT) -> list[str]:
    """最近 N 条用户消息（排除软删除，按时间先后返回）。"""
    with Session(get_engine()) as session:
        rows = session.exec(
            select(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.hidden == False,  # noqa: E712
            )
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        ).all()
    return [r.content.strip() for r in reversed(rows) if r.content.strip()]


def _parse_signals(raw: dict) -> list[dict]:
    """LLM 输出 -> 合法信号（type 白名单 + 置信度阈值）。"""
    signals: list[dict] = []
    for s in raw.get("signals") or []:
        if not isinstance(s, dict):
            continue
        stype = str(s.get("type") or "").strip()
        value = str(s.get("value") or "").strip()
        if stype not in _VALID_TYPES or not value:
            continue
        try:
            conf = float(s.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < CONFIDENCE_THRESHOLD:
            continue
        signals.append(
            {
                "type": stype,
                "value": value,
                "direction": str(s.get("direction") or "").strip() or None,
                "confidence": round(min(conf, 1.0), 2),
                "reason": str(s.get("reason") or "")[:100],
            }
        )
    return signals


def merge_signals(profile: UserProfile, signals: list[dict]) -> int:
    """信号合并（幂等，§8.5 合并规则）；返回新增信号数。直接修改传入 profile（未落库）。"""
    avoids = json_load(profile.avoid_list, []) or []
    tools = json_load(profile.tools, []) or []
    log = json_load(profile.preference_log, []) or []
    known = {(e.get("type"), e.get("value")) for e in log if isinstance(e, dict)}
    merged = 0
    for s in signals:
        key = (s["type"], s["value"])
        if key in known:  # 已记录过，不重复
            continue
        if s["type"] == "avoid" and s["value"] not in avoids:
            avoids.append(s["value"])
        elif s["type"] == "flavor":
            field = _FLAVOR_FIELDS.get(s["value"])
            if field:
                cur = int(getattr(profile, field, 3))
                step = 1 if s["direction"] == "up" else -1
                new = max(1, min(5, cur + step))
                if new != cur:
                    setattr(profile, field, new)
        elif s["type"] == "tool" and s["value"] not in tools:
            tools.append(s["value"])
        elif s["type"] == "diet" and s["confidence"] >= HIGH_CONFIDENCE and s["value"] != profile.diet_type:
            profile.diet_type = s["value"]
        elif s["type"] == "skill" and s["confidence"] >= HIGH_CONFIDENCE and s["value"] != profile.skill_level:
            profile.skill_level = s["value"]
        # cuisine 与其余类型：写入来源日志供打分消费
        log.append({**s, "source": "chat", "created_at": _now_iso()})
        known.add(key)
        merged += 1
    profile.avoid_list = avoids
    profile.tools = tools
    profile.preference_log = log
    return merged


def _invalidate_cache(user_id: int) -> None:
    """画像更新后清除该用户回答缓存（§9.3 失效与新鲜度 1）。"""
    with Session(get_engine()) as session:
        for row in session.exec(select(AnswerCache).where(AnswerCache.user_id == user_id)).all():
            session.delete(row)
        session.commit()


async def extract_from_recent_chat(llm: object, user_id: int) -> int:
    """后台任务入口：最近消息 -> LLM 提取 -> 合并画像 -> 缓存失效。返回合并信号数；失败静默。"""
    try:
        messages = _recent_user_messages(user_id)
        if not messages:
            return 0
        with Session(get_engine()) as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id)
                session.add(profile)
                session.commit()
                session.refresh(profile)
            summary = _profile_summary(profile)
        prompt = get_prompt("preference_extract").format(
            profile=json.dumps(summary, ensure_ascii=False),
            messages="\n".join(f"- {m[:200]}" for m in messages[-MSG_LIMIT:]),
        )
        raw, _usage = await llm.complete_json(prompt, temperature=0.1)  # 结构化，温度固定 0.1（§7.3）
        signals = _parse_signals(raw)
        if not signals:
            return 0
        with Session(get_engine()) as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return 0
            merged = merge_signals(profile, signals)
            if merged:
                profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(profile)
                session.commit()
        if merged:
            _invalidate_cache(user_id)
        logger.info("preference_extract user=%s merged=%d", user_id, merged)
        return merged
    except Exception:  # noqa: BLE001 —— 提取失败不影响主流程
        logger.warning("preference_extract user=%s failed", user_id, exc_info=True)
        return 0


def schedule_extract(llm: object, user_id: int) -> asyncio.Task:
    """chat API 后台触发（不阻塞 SSE 响应）。"""
    return asyncio.create_task(extract_from_recent_chat(llm, user_id))
