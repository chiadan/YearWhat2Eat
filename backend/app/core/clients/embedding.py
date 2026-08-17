"""Embedding 客户端（§7.1）：抽象接口 + 本地 sentence-transformers 实现（§12.4）。

- 默认本地部署：BAAI/bge-small-zh-v1.5（512 维）
- device=auto：torch.cuda.is_available() 为真用 cuda，否则 cpu
- 模型懒加载（首个请求初始化），避免冷启动拖慢 healthcheck
- SiliconFlow 远程实现保留为可切换备选（EMBEDDING_PROVIDER=siliconflow）
"""
from __future__ import annotations

from typing import Protocol

from app.core.config import Settings


class EmbeddingClient(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbeddingClient:
    """sentence-transformers 本地实现（CUDA/CPU 自动，§16 决策 1 OK）。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.dim = settings.embedding_dim
        self._model = None

    def _resolve_device(self) -> str:
        device = self.settings.embedding_device
        if device == "auto":
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self.settings.embedding_cache.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(
                self.settings.embedding_model,
                device=self._resolve_device(),
                cache_folder=str(self.settings.embedding_cache),
            )
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]


class SiliconFlowEmbeddingClient:
    """SiliconFlow 远程实现（备选，配置切换即可，§16 决策 1）。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.dim = settings.embedding_dim
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.embedding_api_key,
                base_url=self.settings.embedding_base_url,
            )
        return self._client

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._ensure_client()
        resp = client.embeddings.create(model=self.settings.embedding_model, input=texts)
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in ordered]


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.embedding_provider == "siliconflow":
        return SiliconFlowEmbeddingClient(settings)
    return LocalEmbeddingClient(settings)
