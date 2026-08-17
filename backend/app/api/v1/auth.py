"""认证接口（§9.2）：注册/登录/游客/刷新/登出/转正。"""
from fastapi import APIRouter

from app.schemas.auth import (
    LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest,
    TokenResponse, UpgradeRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest):
    return auth_service.register(body.username, body.password)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    return auth_service.login(body.username, body.password)


@router.post("/guest", response_model=TokenResponse)
def guest():
    """游客会话（§9.2 决策 4 OK）：行为数据在 upgrade 时合并进新账号。"""
    return auth_service.create_guest()


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest):
    return auth_service.refresh_tokens(body.refresh_token)


@router.post("/logout", status_code=204)
def logout(body: LogoutRequest):
    auth_service.logout(body.refresh_token)


@router.post("/upgrade", response_model=TokenResponse)
def upgrade(body: UpgradeRequest):
    """游客转正：游客数据（行为/收藏/会话）合并进新账号（§9.2）。"""
    return auth_service.upgrade_guest(body.guest_token, body.username, body.password)
