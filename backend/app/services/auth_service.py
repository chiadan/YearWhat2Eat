"""认证服务（§9.2）：JWT access/refresh + bcrypt + 游客转正。

- Access Token：HS256，2h，claims {sub, role, token_version, exp}
- Refresh Token：7d，服务端存哈希（refresh_tokens 表），支持吊销/旋转
- 游客：临时 User（username=guest_xxx），upgrade 时行为数据合并进新账号后删除
- token_version 失效联动：修改密码/禁用时递增，旧 access 立即失效（§9.2）
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.db.models import ChatSession, RefreshToken, User, UserFavorite, UserFeedback
from app.db.session import get_engine

TOKEN_ISSUER = "yeahwhat2eat"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    """passlib bcrypt 哈希（依赖组合：passlib==1.7.4 + bcrypt==4.0.1，见 requirements）。"""
    from passlib.context import CryptContext

    return CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    from passlib.context import CryptContext

    try:
        return CryptContext(schemes=["bcrypt"], deprecated="auto").verify(password, password_hash)
    except Exception:  # noqa: BLE001
        return False


def _create_tokens(user: User, settings: Settings) -> dict:
    import jwt

    now = _now()
    access_payload = {
        "sub": str(user.id),
        "role": user.role,
        "token_version": user.token_version,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_access_ttl),
        "iss": TOKEN_ISSUER,
    }
    access = jwt.encode(access_payload, settings.jwt_secret, algorithm="HS256")

    refresh = uuid.uuid4().hex + uuid.uuid4().hex
    with Session(get_engine()) as session:
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=_refresh_hash(refresh),
                expires_at=now + timedelta(seconds=settings.jwt_refresh_ttl),
                revoked=False,
            )
        )
        session.commit()
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


def register(username: str, password: str) -> dict:
    settings = get_settings()
    with Session(get_engine()) as session:
        if session.exec(select(User).where(User.username == username)).first():
            raise ConflictError("用户名已存在")
        user = User(username=username, password_hash=hash_password(password), role="user")
        session.add(user)
        session.commit()
        session.refresh(user)
        return _create_tokens(user, settings)


def login(username: str, password: str) -> dict:
    settings = get_settings()
    with Session(get_engine()) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("用户名或密码错误")
        return _create_tokens(user, settings)


def create_guest() -> dict:
    """游客会话（§9.2）：临时 User，upgrade 时合并数据。"""
    settings = get_settings()
    with Session(get_engine()) as session:
        user = User(username=f"guest_{uuid.uuid4().hex[:12]}", password_hash="", role="user")
        session.add(user)
        session.commit()
        session.refresh(user)
        return _create_tokens(user, settings)


def refresh_tokens(refresh_token: str) -> dict:
    settings = get_settings()
    token_hash = _refresh_hash(refresh_token)
    with Session(get_engine()) as session:
        row = session.exec(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).first()
        if row is None or row.revoked or row.expires_at < _now():
            raise UnauthorizedError("refresh token 无效或已过期")
        # 旋转：旧 refresh 吊销，发新 token 对
        row.revoked = True
        session.add(row)
        user = session.get(User, row.user_id)
        if user is None:
            raise UnauthorizedError("用户不存在")
        # 必须先提交吊销，释放 SQLite 写锁（§4.3 单写者），
        # 否则 _create_tokens 新开 Session 写 refresh_tokens 会 database is locked
        session.commit()
        return _create_tokens(user, settings)


def logout(refresh_token: str) -> None:
    token_hash = _refresh_hash(refresh_token)
    with Session(get_engine()) as session:
        row = session.exec(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).first()
        if row is not None:
            row.revoked = True
            session.add(row)
            session.commit()


def upgrade_guest(guest_token: str, username: str, password: str) -> dict:
    """游客转正（§9.2）：游客行为/收藏/会话合并进新账号，删除游客账号。"""
    settings = get_settings()
    guest = get_user_from_token(guest_token)
    with Session(get_engine()) as session:
        if session.exec(select(User).where(User.username == username)).first():
            raise ConflictError("用户名已存在")
        user = User(username=username, password_hash=hash_password(password), role="user")
        session.add(user)
        session.commit()
        session.refresh(user)

        # 合并游客数据（§9.2 upgrade：行为流水/收藏/会话 user_id 迁移）
        for model in (UserFeedback, UserFavorite, ChatSession):
            for row in session.exec(select(model).where(model.user_id == guest.id)).all():
                row.user_id = user.id
                session.add(row)
        session.commit()

        session.delete(session.get(User, guest.id))
        session.commit()
        return _create_tokens(user, settings)


def get_user_from_token(access_token: str) -> User:
    """解析 access token -> User（校验签名/过期/token_version，§9.2 失效联动）。"""
    import jwt

    settings = get_settings()
    try:
        payload = jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"], issuer=TOKEN_ISSUER)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("access token 无效或已过期") from exc
    with Session(get_engine()) as session:
        user = session.get(User, int(payload.get("sub", 0)))
        if user is None:
            raise UnauthorizedError("用户不存在")
        if payload.get("token_version", 0) != user.token_version:
            raise UnauthorizedError("登录状态已失效，请重新登录")
        return user


def invalidate_user_tokens(user_id: int) -> None:
    """修改密码/禁用时调用：递增 token_version + 吊销全部 refresh（§9.2）。"""
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        user.token_version += 1
        session.add(user)
        for row in session.exec(select(RefreshToken).where(RefreshToken.user_id == user_id)).all():
            row.revoked = True
            session.add(row)
        session.commit()


# ── BYOK（§10）：用户自定义 DeepSeek API Key ────────────────

def set_user_api_key(user_id: int, api_key: str) -> None:
    """加密存储用户自定义 Key（BYOK，§10）；前端只读 has_custom_key，明文不返回。"""
    from app.core.crypto import encrypt_secret

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        user.deepseek_api_key_enc = encrypt_secret(api_key)
        session.add(user)
        session.commit()


def clear_user_api_key(user_id: int) -> None:
    """清除自定义 Key，回退系统 .env Key（BYOK，§10）。"""
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        user.deepseek_api_key_enc = None
        session.add(user)
        session.commit()


def has_user_api_key(user_id: int) -> bool:
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        return bool(user and user.deepseek_api_key_enc)


def get_user_api_key_decrypted(user_id: int) -> str | None:
    """解密用户自定义 Key；未配置/解密失败返回 None（调用方回退系统 Key，§7.3）。"""
    from app.core.crypto import decrypt_secret

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None or not user.deepseek_api_key_enc:
            return None
    return decrypt_secret(user.deepseek_api_key_enc)


# ── 多 Provider（§10）：OpenAI 兼容 / Anthropic 自定义接入 ────

_PROVIDER_TYPES = ("openai", "anthropic")


def get_user_providers(user_id: int) -> list[dict]:
    """返回脱敏后的接入配置列表（key 不回显，仅 has_key）。"""
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        raw = user.ai_providers if user else None
    providers = raw or []
    return [
        {
            "name": p.get("name", ""),
            "provider_type": p.get("provider_type", "openai"),
            "base_url": p.get("base_url", ""),
            "has_key": bool(p.get("api_key_enc")),
            "models": p.get("models") or [],
        }
        for p in providers
    ]


def set_user_providers(user_id: int, providers: list[dict]) -> list[dict]:
    """保存接入配置（§10）：api_key 字段加密存储（api_key_enc），空 key 保留原密文。"""
    from app.core.crypto import encrypt_secret

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        existing = {p.get("name"): p for p in (user.ai_providers or [])}
        cleaned: list[dict] = []
        for p in providers:
            name = str(p.get("name", "")).strip()
            ptype = str(p.get("provider_type", "openai"))
            if not name or ptype not in _PROVIDER_TYPES:
                continue
            entry = {
                "name": name,
                "provider_type": ptype,
                "base_url": str(p.get("base_url", "")).strip(),
                "models": [str(m).strip() for m in (p.get("models") or []) if str(m).strip()],
            }
            new_key = str(p.get("api_key") or "").strip()
            if new_key:
                entry["api_key_enc"] = encrypt_secret(new_key)
            else:
                old = existing.get(name) or {}
                if old.get("api_key_enc"):
                    entry["api_key_enc"] = old["api_key_enc"]
            cleaned.append(entry)
        user.ai_providers = cleaned
        session.add(user)
        session.commit()
    return get_user_providers(user_id)


def get_user_provider(user_id: int, name: str) -> dict | None:
    """运行时解析指定接入配置（解密 key，供 LLMClient 使用）。"""
    from app.core.crypto import decrypt_secret

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        raw = user.ai_providers if user else None
    for p in raw or []:
        if p.get("name") == name:
            enc = p.get("api_key_enc")
            return {
                "provider_type": p.get("provider_type", "openai"),
                "base_url": p.get("base_url", ""),
                "api_key": decrypt_secret(enc) if enc else None,
                "models": p.get("models") or [],
            }
    return None
