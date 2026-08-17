"""FastAPI 应用入口（§9 / §12.5 端口约定）。

- lifespan：日志初始化 + alembic 自动迁移（§4.3）
- 统一异常处理（§9.5 错误码规范）
- 单 worker 部署（§12.4）：uvicorn app.main:app --port 8000 --workers 1
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, setup_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    logger = get_logger("app")
    try:
        from app.db.session import run_migrations

        run_migrations()
        logger.info("数据库迁移完成（alembic upgrade head）")
    except Exception:  # noqa: BLE001
        logger.exception("数据库迁移失败，请检查 SQLITE_PATH 配置")
    yield


app = FastAPI(
    title="是啊吃什么",
    description="千人千面菜谱推荐 RAG Agent（设计文档见 design/设计文档.md）",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    body = {"code": exc.code, "message": exc.message}
    if exc.payload is not None:
        body["data"] = exc.payload
    if exc.trace_id:
        body["trace_id"] = exc.trace_id
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    get_logger("app").exception("未处理异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误"},
    )


app.include_router(router)

# 菜谱成品图静态托管（§12.5 部署注意 5）：/static/dishes/{相对路径}
# 数据源只读（§3）；生产由 nginx 反代（frontend/nginx.conf /static/）
_static_dir = settings.data_source_root / "dishes"
if _static_dir.is_dir():
    app.mount("/static/dishes", StaticFiles(directory=str(_static_dir)), name="dishes-static")
