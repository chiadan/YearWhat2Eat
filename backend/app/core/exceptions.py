"""统一异常体系（§9.5 错误码规范）。

错误码段：400 参数 / 401 未认证 / 403 无权限 / 404 不存在 / 409 冲突 / 429 限流 / 500 内部。
"""
from typing import Any


class AppError(Exception):
    """业务异常基类，携带 HTTP 状态码与可读信息。"""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "服务内部错误", *, payload: Any = None, trace_id: str = ""):
        super().__init__(message)
        self.message = message
        self.payload = payload
        self.trace_id = trace_id


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class ConcurrencyLimitError(AppError):
    status_code = 429
    code = "CONCURRENCY_LIMIT"


class LLMError(AppError):
    """LLM 调用失败（超时/限流/余额不足等），SSE 场景映射为 error 帧。"""

    status_code = 500
    code = "LLM_ERROR"

    def __init__(self, message: str, *, retryable: bool = True, payload: Any = None, trace_id: str = ""):
        super().__init__(message, payload=payload, trace_id=trace_id)
        self.retryable = retryable
