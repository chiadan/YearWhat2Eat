"""SQLAlchemy JSON 列读写兼容工具（§4.3）。

SQLAlchemy 的 JSON 类型在读取时**自动反序列化**为 list/dict；
但历史/部分写入方可能存过 json.dumps 后的 str。
统一用 json_load() 读取：list/dict 直接返回，str 解析，None 给默认值。
"""
from __future__ import annotations

import json
from typing import Any


def json_load(value: Any, default: Any = None) -> Any:
    """读取 JSON 列：兼容 list/dict（已反序列化）、str（未反序列化）、None。"""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return value
