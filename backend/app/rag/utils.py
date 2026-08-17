"""菜名工具（§6.5 召回④）：dish_meta 全量菜名加载与匹配，供意图/扩写节点共用。

- load_dish_names：懒加载 + 按长度降序（最长匹配优先，防子串误判）
- named_dishes(text)：文本中出现的具体菜名（去重，按匹配顺序）
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import DishMeta
from app.db.session import get_engine

_catalog_names: list[str] | None = None


def load_dish_names() -> list[str]:
    """全量菜名（懒加载缓存 + 按长度降序）。"""
    global _catalog_names
    if _catalog_names is None:
        with Session(get_engine()) as session:
            rows = session.exec(select(DishMeta)).all()
        _catalog_names = sorted((r.name for r in rows if r.name), key=len, reverse=True)
    return _catalog_names


def named_dishes(text: str) -> list[str]:
    """文本中出现的具体菜名（§6.5 召回④）：dish_meta 全量菜名子串匹配，去重、按出现顺序。"""
    found: list[str] = []
    for name in load_dish_names():
        if name and name in text and name not in found:
            found.append(name)
    return found
