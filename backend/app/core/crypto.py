"""对称加密工具（§10 BYOK）：用户自定义 API Key 加密存储。

- Fernet（AES-128-CBC + HMAC），加密密钥派生自 JWT_SECRET（sha256 -> urlsafe base64）
- 换 JWT_SECRET 后旧密文不可解密（视为未配置，回退系统 Key）
"""
from __future__ import annotations

import base64
import hashlib

from app.core.config import get_settings


def _fernet():
    from cryptography.fernet import Fernet

    settings = get_settings()
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    """加密（BYOK，§10）：返回 Fernet token 字符串。"""
    if not plain:
        raise ValueError("密钥不能为空")
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str | None:
    """解密；密钥不匹配/损坏返回 None（调用方回退系统 Key，§7.3 降级）。"""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
