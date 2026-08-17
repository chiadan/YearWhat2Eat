"""依赖注入（§11 铁律 3）：get_settings / get_current_user / require_admin，测试可 mock。"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.db.models import User
from app.services.auth_service import get_user_from_token

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep() -> Settings:
    return get_settings()


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """Bearer access token -> User（§9.2；游客也是 User，role=user）。"""
    if cred is None:
        raise UnauthorizedError("未登录")
    return get_user_from_token(cred.credentials)


def get_current_user_optional(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User | None:
    """可选鉴权：有 token 返回 User，无 token 返回 None（匿名可用，§9.2）。"""
    if cred is None:
        return None
    try:
        return get_user_from_token(cred.credentials)
    except UnauthorizedError:
        return None


def require_admin(user: User = Depends(get_current_user)) -> None:
    """admin 角色校验（§12.6 第 9 条）：/api/v1/admin/* 统一依赖。"""
    if user.role != "admin":
        raise ForbiddenError("需要 admin 权限")
