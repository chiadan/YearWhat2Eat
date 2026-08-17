"""菜谱浏览接口（§9）：列表 / 详情 / 相关菜 / 热门。"""
from fastapi import APIRouter, Query

from app.core.exceptions import NotFoundError
from app.services import dish_service

router = APIRouter()


@router.get("/dishes/hot")
def hot_dishes(
    limit: int = Query(default=12, ge=1, le=50, description="返回条数"),
) -> list[dict]:
    """热门菜谱（§8.3 热度公式聚合行为流水；冷启动返回入库序兜底）。"""
    return dish_service.hot_dishes(limit=limit)


@router.get("/dishes")
def list_dishes(
    category: str | None = Query(default=None, description="分类目录，如 vegetable_dish"),
    difficulty: int | None = Query(default=None, ge=1, le=5, description="最大难度（≤）"),
    flavor: str | None = Query(default=None, description="口味标签，如 辣"),
    keyword: str | None = Query(default=None, description="搜索菜名/食材"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> dict:
    return dish_service.list_dishes(
        category=category,
        difficulty=difficulty,
        flavor=flavor,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/dishes/names")
def list_dish_names() -> dict:
    """全量菜名映射（§10 正文菜名链接化）：[{name, dish_id}]，轻量无分页。"""
    return {"items": dish_service.dish_names()}


@router.get("/dishes/{dish_id}")
def get_dish(dish_id: str) -> dict:
    detail = dish_service.get_detail(dish_id)
    if detail is None:
        raise NotFoundError(f"菜谱 {dish_id} 不存在")
    return detail


@router.get("/dishes/{dish_id}/related")
def get_related(dish_id: str) -> list[dict]:
    return dish_service.get_related(dish_id)
