"""API v1 路由汇总注册。"""
from fastapi import APIRouter

from app.api.v1 import admin, auth, chat, dishes, health, users

router = APIRouter(prefix="/api/v1")
router.include_router(health.router, tags=["health"])
router.include_router(auth.router, tags=["auth"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(chat.router, tags=["chat"])
router.include_router(dishes.router, tags=["dishes"])
router.include_router(users.router, tags=["users"])
