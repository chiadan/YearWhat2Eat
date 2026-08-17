"""DeepSeek LLM 客户端（§7.1 后端技术栈 / §7.3 参数与错误处理）。

- 统一入口：complete() 返回文本，complete_json() 返回结构化 dict（含容错 JSON 提取），stream() 流式
- 动态生成参数（前端模型/强度选择，§9 聊天）：set_generation(model/temperature/max_tokens)，
  影响 complete/stream 的生成路径；结构化调用（complete_json）不受影响
- 重试：指数退避（1s -> 2s），LLM_MAX_RETRIES 次；402 余额不足 / 401 密钥失效不重试
- 并发：asyncio.Semaphore(LLM_CONCURRENCY) 限流
- 用量：每次调用返回 LLMUsage（prompt/completion tokens），由调用方写入 llm_usage 表（§4.3）
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.exceptions import LLMError

_JSON_PATTERN = re.compile(r"\{.*\}", re.S)

# BYOK（§10）：请求级 API Key 上下文——每个 asyncio Task 独立，
# stream_agent 设置、子任务（_auto_title 等）自动继承，无并发竞态。
_request_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_request_api_key", default=None
)
# 多 Provider（§10）：请求级接入配置（openai 兼容 / anthropic），优先于 api_key 上下文
_request_provider: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "llm_request_provider", default=None
)


def set_request_api_key(api_key: str | None) -> contextvars.Token:
    """设置当前请求的 API Key（BYOK；None = 系统 .env Key）。返回恢复用 Token。"""
    return _request_api_key.set(api_key)


def reset_request_api_key(token: contextvars.Token) -> None:
    _request_api_key.reset(token)


def set_request_provider(cfg: dict | None) -> contextvars.Token:
    """设置当前请求的接入配置（§10 多 Provider）：{"type": openai|anthropic, "base_url", "api_key"}。"""
    return _request_provider.set(cfg)


def reset_request_provider(token: contextvars.Token) -> None:
    _request_provider.reset(token)


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LLMResult:
    content: str
    usage: LLMUsage


class LLMClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.llm_concurrency)
        # 生成路径动态参数（§9 模型/强度选择；set_generation 修改）
        self._model = settings.llm_model
        self._gen_temperature = settings.llm_temperature_gen
        self._gen_max_tokens = settings.llm_max_tokens

    # ── 动态参数 ──────────────────────────────────────────
    def set_generation(
        self,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """设置生成路径参数（前端模型/强度选择，§9）。传 None 保持当前值。"""
        if model:
            self._model = model
        if temperature is not None:
            self._gen_temperature = temperature
        if max_tokens is not None:
            self._gen_max_tokens = max_tokens

    @property
    def active_model(self) -> str:
        return self._model

    # ── 内部 ──────────────────────────────────────────────
    def _resolve_api_key(self) -> str:
        """请求级 BYOK Key 优先，否则系统 .env Key（§10）。"""
        return _request_api_key.get() or self._settings.deepseek_api_key

    def _build_chat(self, temperature: float, *, max_tokens: int | None = None):
        """每次新建实例（实例化无网络开销），保证 model/temperature/max_tokens 动态生效。

        多 Provider（§10）：请求级配置优先——anthropic 走 ChatAnthropic，
        openai 兼容（DeepSeek/自定义 base_url）走 ChatOpenAI。
        """
        provider = _request_provider.get()
        if provider and provider.get("type") == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=self._model,
                api_key=provider.get("api_key") or self._resolve_api_key(),
                base_url=provider.get("base_url"),
                temperature=temperature,
                timeout=self._settings.llm_timeout,
                max_retries=0,
                max_tokens=max_tokens or self._gen_max_tokens,
            )

        from langchain_openai import ChatOpenAI

        base_url = (provider or {}).get("base_url") or self._settings.deepseek_base_url
        return ChatOpenAI(
            model=self._model,
            api_key=(provider or {}).get("api_key") or self._resolve_api_key(),
            base_url=base_url,
            temperature=temperature,
            timeout=self._settings.llm_timeout,
            max_retries=0,  # 自管重试（区分错误码）
            max_tokens=max_tokens or self._gen_max_tokens,
        )

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从模型输出中容错提取 JSON（可能被 markdown 代码块包裹）。"""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        m = _JSON_PATTERN.search(text)
        if not m:
            raise ValueError(f"输出中未找到 JSON: {text[:200]}")
        return json.loads(m.group(0))

    async def _call(self, prompt: str, temperature: float, *, max_tokens: int | None = None) -> LLMResult:
        async with self._semaphore:
            last_err: Exception | None = None
            for attempt in range(self._settings.llm_max_retries + 1):
                try:
                    chat = self._build_chat(temperature, max_tokens=max_tokens)
                    resp = await chat.ainvoke([("user", prompt)])
                    meta = resp.response_metadata or {}
                    usage = meta.get("token_usage") or meta.get("usage") or {}
                    return LLMResult(
                        content=resp.content if isinstance(resp.content, str) else str(resp.content),
                        usage=LLMUsage(
                            prompt_tokens=int(usage.get("prompt_tokens", 0)),
                            completion_tokens=int(usage.get("completion_tokens", 0)),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 —— 统一转 LLMError
                    last_err = exc
                    message = str(exc)
                    # 余额不足 / 密钥失效：不重试
                    if any(k in message for k in ("402", "insufficient", "余额", "Insufficient")):
                        raise LLMError("DeepSeek API 额度不足，请充值后重试", retryable=False) from exc
                    if any(k in message for k in ("401", "invalid api key", "Authentication")):
                        raise LLMError("DeepSeek API 密钥无效，请检查 .env 配置", retryable=False) from exc
                    if attempt < self._settings.llm_max_retries:
                        await asyncio.sleep(2**attempt)
                        continue
            raise LLMError(f"DeepSeek 调用失败: {last_err}", retryable=True) from last_err

    # ── 对外 ──────────────────────────────────────────────
    async def complete(self, prompt: str, *, temperature: float | None = None) -> LLMResult:
        """普通文本生成（生成路径参数，§9 强度选择）。"""
        temp = temperature if temperature is not None else self._gen_temperature
        return await self._call(prompt, temp)

    async def stream(self, prompt: str, *, temperature: float | None = None) -> object:
        """流式生成（§9.1 SSE text 帧来源）：async iterator of str token。"""
        temp = temperature if temperature is not None else self._gen_temperature
        async with self._semaphore:
            chat = self._build_chat(temp)
            async for chunk in chat.astream([("user", prompt)]):
                if chunk.content:
                    yield chunk.content if isinstance(chunk.content, str) else str(chunk.content)

    async def complete_json(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        attempts: int = 2,
    ) -> tuple[dict, LLMUsage]:
        """结构化 JSON 输出（温度默认 0.1，§7.3；不受强度选择影响）；JSON 解析失败时重试。"""
        temp = temperature if temperature is not None else self._settings.llm_temperature_struct
        last_err: Exception | None = None
        for _ in range(max(attempts, 1)):
            result = await self._call(prompt, temp, max_tokens=self._settings.llm_max_tokens)
            try:
                data = self._extract_json(result.content)
                if isinstance(data, dict):
                    return data, result.usage
                raise ValueError("JSON 根节点不是对象")
            except (ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                continue
        raise LLMError(f"结构化输出解析失败: {last_err}", retryable=True) from last_err
