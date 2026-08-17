"""检索器抽象基类。"""
from __future__ import annotations

from typing import Protocol


class Retriever(Protocol):
    """检索器接口：输入查询文本，返回统一 hit 结构 [{id, score, payload, source}]。"""

    async def retrieve(self, query: str, top_k: int = 10) -> list[dict]: ...
