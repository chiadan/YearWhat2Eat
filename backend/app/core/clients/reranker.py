"""Reranker 客户端（§7.1）：抽象接口 + 本地 sentence-transformers 交叉编码实现。

- BAAI/bge-reranker-v2-m3，device=auto（CUDA/CPU，§16 决策 1 OK）
- 懒加载；rerank(query, documents) -> 每条打分（sigmoid 概率）
"""
from __future__ import annotations

from typing import Protocol

from app.core.config import Settings


class RerankerClient(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


class LocalRerankerClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    def _resolve_device(self) -> str:
        device = self.settings.reranker_device
        if device == "auto":
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def _ensure_model(self):
        if self._model is None:
            import os

            from sentence_transformers import CrossEncoder

            cache = self.settings.reranker_cache
            cache.mkdir(parents=True, exist_ok=True)
            # CrossEncoder 不支持 cache_folder 参数（区别于 SentenceTransformer），
            # 用 HF_HOME 把模型缓存落到项目目录（§12.4 缓存卷复用）
            os.environ.setdefault("HF_HOME", str(cache))
            self._model = CrossEncoder(
                self.settings.reranker_model,
                device=self._resolve_device(),
            )
        return self._model

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        model = self._ensure_model()
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)
        return [float(s) for s in scores]


def build_reranker_client(settings: Settings) -> RerankerClient:
    return LocalRerankerClient(settings)
