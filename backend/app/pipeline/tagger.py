"""LLM 打标（§5 Step2）：菜系/口味/技法/荤素/主料/时长/餐次。

- 批量调用 DeepSeek（temperature=0.1，§7.3），一次输出 JSON 数组
- LLM 失败时规则兜底（分类推断荤素 + 步骤关键词推断技法），保证管道可完成
- 每次调用返回 LLMUsage，由 runner 写入 llm_usage 表（§4.3 / §7 成本统计）
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.core.clients.llm import LLMClient, LLMUsage
from app.core.exceptions import LLMError
from app.pipeline.parser import DishRecord

# 分类 -> 荤素兜底（soup 等混合类默认"其他"，tagger 结果优先）
_CATEGORY_MEAT = {
    "meat_dish": "荤",
    "aquatic": "水产",
    "vegetable_dish": "素",
    "semi-finished": "其他",
    "breakfast": "其他",
    "staple": "其他",
    "soup": "其他",
    "drink": "其他",
    "condiment": "其他",
    "dessert": "其他",
}

_TECHNIQUE_KEYWORDS: dict[str, list[str]] = {
    "炒": ["炒", "翻炒", "爆炒"],
    "蒸": ["蒸"],
    "煮": ["煮", "焯", "汆"],
    "炖": ["炖", "焖"],
    "炸": ["炸"],
    "煎": ["煎"],
    "烤": ["烤"],
    "凉拌": ["凉拌", "拌"],
    "微波炉": ["微波炉"],
    "空气炸锅": ["空气炸锅"],
    "电饭煲": ["电饭煲"],
}

_TIME_RE = re.compile(r"(\d+)\s*[-~至到]?\s*(\d+)?\s*分钟")

# 菜系关键词推断（规则兜底；LLM 打标成功时以其结果为准）
_CUISINE_KEYWORDS: dict[str, list[str]] = {
    "川菜": ["花椒", "豆瓣", "麻婆", "回锅", "宫保", "水煮", "麻辣", "川"],
    "湘菜": ["剁椒", "湘", "小米辣", "擂椒", "辣炒"],
    "粤菜": ["清蒸", "白灼", "煲", "豉汁", "烧腊", "叉烧", "广式"],
    "家常": ["家常", "小炒", "快手"],
    "西式": ["黄油", "芝士", "奶油", "意面", "牛排", "披萨", "沙拉", "烤箱"],
    "日式": ["照烧", "丼", "味噌", "寿司", "日式", "肥牛"],
    "韩式": ["泡菜", "韩式", "石锅"],
    "东南亚": ["咖喱", "椰浆", "冬阴功"],
    "西北": ["油泼", "拉面", "肉夹馍", "凉皮", "孜然"],
}

# 口味关键词推断
_FLAVOR_KEYWORDS: dict[str, list[str]] = {
    "辣": ["辣", "辣椒", "花椒", "豆瓣", "剁椒", "麻"],
    "甜": ["糖", "冰糖", "蜂蜜", "蜜", "甜", "椰浆", "奶油"],
    "酸": ["醋", "柠檬", "酸", "番茄"],
    "咸鲜": ["酱油", "蚝油", "生抽", "老抽", "盐", "酱", "豉"],
    "清淡": ["清蒸", "白灼", "焯", "凉拌", "水煮蛋", "粥"],
    "香辣": ["香辣", "麻辣", "干锅", "孜然"],
    "麻": ["花椒", "麻油", "藤椒"],
}


@dataclass
class DishTags:
    dish_id: str
    cuisines: list[str] = field(default_factory=list)
    flavors: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    meat_attr: str = "其他"              # 荤 | 素 | 水产 | 其他
    main_ingredients: list[str] = field(default_factory=list)
    time_est_min: int | None = None
    meal_types: list[str] = field(default_factory=list)


def _build_prompt(dishes: list[DishRecord]) -> str:
    lines = ["请为以下菜谱批量打标，严格输出 JSON 数组，不要任何额外文字。", "["]
    for d in dishes:
        steps_summary = "；".join(s.text[:60] for s in d.steps[:5])
        lines.append(
            json.dumps(
                {
                    "dish_id": d.dish_id,
                    "name": d.name,
                    "category": d.category,
                    "intro": (d.intro or "")[:100],
                    "required_ingredients": d.required_raw[:10],
                    "steps_summary": steps_summary,
                },
                ensure_ascii=False,
            )
            + ","
        )
    lines.append("]")
    lines.append(
        "每项输出: {\"dish_id\": string, \"cuisines\": [菜系如 川菜/粤菜/家常/西式], "
        "\"flavors\": [口味如 辣/甜/酸/咸鲜/清淡/麻/香辣], "
        "\"techniques\": [技法如 炒/蒸/煮/炖/炸/煎/烤/凉拌/微波炉/空气炸锅], "
        "\"meat_attr\": \"荤|素|水产|其他\", "
        "\"main_ingredients\": [主要食材，去量词，最多 5 个], "
        "\"time_est_min\": 预估制作分钟数(整数或 null), "
        "\"meal_types\": [早餐/午餐/晚餐/夜宵/加餐]}"
    )
    return "\n".join(lines)


def _rule_fallback(dish: DishRecord) -> DishTags:
    """规则兜底（LLM 不可用时，§7.3 错误降级联动）。"""
    text = " ".join(dish.required_raw) + " " + (dish.calculation_raw or "") + " " + " ".join(
        s.text for s in dish.steps
    )
    techniques = [t for t, kws in _TECHNIQUE_KEYWORDS.items() if any(k in text for k in kws)]

    main_ingredients: list[str] = []
    for item in dish.required_raw:
        cleaned = re.sub(r"^[（(【\[].*?[）)】\]]\s*", "", item)
        cleaned = re.sub(r"\s*[（(【\[]?.*?[）)】\]]\s*$", "", cleaned)
        cleaned = re.sub(r"[=＝].*$", "", cleaned)
        cleaned = cleaned.strip(" -")
        if cleaned and len(cleaned) <= 12:
            main_ingredients.append(cleaned)
        if len(main_ingredients) >= 5:
            break

    time_est: int | None = None
    m = _TIME_RE.search(text)
    if m:
        time_est = int(m.group(1)) + (int(m.group(2)) - int(m.group(1))) // 2 if m.group(2) else int(m.group(1))

    # 菜系/口味关键词推断（避免 LLM 打标失败时图谱缺 HAS_CUISINE/HAS_FLAVOR 关系）
    search_text = f"{dish.name} {dish.intro or ''} {text}"
    cuisines = [c for c, kws in _CUISINE_KEYWORDS.items() if any(k in search_text for k in kws)]
    flavors = [f for f, kws in _FLAVOR_KEYWORDS.items() if any(k in search_text for k in kws)]
    if not flavors:
        # 口味兜底：宁可给最常见默认，也不留空（§8 口味匹配依赖该字段，空 = 推荐失效）
        flavors = ["咸鲜"]

    return DishTags(
        dish_id=dish.dish_id,
        cuisines=cuisines[:3],
        flavors=flavors[:4],
        techniques=techniques[:4],
        meat_attr=_CATEGORY_MEAT.get(dish.category, "其他"),
        main_ingredients=main_ingredients,
        time_est_min=time_est,
    )


def _needs_llm(t: DishTags) -> bool:
    """低置信判定（方案 B：规则优先，只对难例送 LLM）：
    菜系/口味是千人千面打分核心维度且规则易误判——任一为空即送 LLM 精修。
    """
    return not t.cuisines or not t.flavors


def _merge_tags(llm_tags: DishTags | None, rule_tags: DishTags) -> DishTags:
    """合并：LLM 字段优先，空字段回落规则（保证标签永不缺字段）。"""
    if llm_tags is None:
        return rule_tags
    return DishTags(
        dish_id=llm_tags.dish_id,
        cuisines=llm_tags.cuisines or rule_tags.cuisines,
        flavors=llm_tags.flavors or rule_tags.flavors,
        techniques=llm_tags.techniques or rule_tags.techniques,
        meat_attr=llm_tags.meat_attr or rule_tags.meat_attr,
        main_ingredients=llm_tags.main_ingredients or rule_tags.main_ingredients,
        time_est_min=llm_tags.time_est_min or rule_tags.time_est_min,
        meal_types=llm_tags.meal_types or rule_tags.meal_types,
    )


async def _llm_tag_batch(batch: list[DishRecord], llm: LLMClient) -> tuple[dict[str, DishTags], LLMUsage | None]:
    """LLM 打一批难例；失败返回空 dict（保留规则标签，§7.3 错误降级）。"""
    try:
        data, usage = await llm.complete_json(_build_prompt(batch))
    except LLMError:
        return {}, None
    result: dict[str, DishTags] = {}
    items = data.get("items") or data.get("data") or (
        [data] if isinstance(data, dict) and "dish_id" in data else []
    )
    for item in items:
        try:
            result[item["dish_id"]] = DishTags(
                dish_id=item["dish_id"],
                cuisines=list(item.get("cuisines") or [])[:4],
                flavors=list(item.get("flavors") or [])[:4],
                techniques=list(item.get("techniques") or [])[:4],
                meat_attr=str(item.get("meat_attr") or "其他"),
                main_ingredients=list(item.get("main_ingredients") or [])[:5],
                time_est_min=item.get("time_est_min"),
                meal_types=list(item.get("meal_types") or [])[:3],
            )
        except (KeyError, TypeError):
            continue
    return result, usage


async def tag_batch(
    dishes: list[DishRecord],
    llm: LLMClient,
    *,
    batch_size: int = 20,
    on_batch: object | None = None,
) -> tuple[dict[str, DishTags], list[LLMUsage]]:
    """打标（方案 B：规则优先 + LLM 只补难例，§5 打标低成本改造）。

    - 全量 357 道先走规则（秒级、0 token）
    - 仅"菜系或口味为空"的低置信难例送 DeepSeek（预计 1/3~1/2 的量，成本与时间降 50%+）
    - 难例批次间并行（LLMClient 信号量已限流）；LLM 字段优先、空字段回落规则
    - 返回 (dish_id -> DishTags, 累计用量)
    """
    import asyncio

    # Step1：规则全量打标（0 成本）
    rule_tags = {d.dish_id: _rule_fallback(d) for d in dishes}

    # Step2：难例筛选（菜系或口味为空）
    hard = [d for d in dishes if _needs_llm(rule_tags[d.dish_id])]

    # Step3：LLM 只打难例（批次并行）
    usages: list[LLMUsage] = []
    llm_results: dict[str, DishTags] = {}
    if hard:
        batches = [hard[i : i + batch_size] for i in range(0, len(hard), batch_size)]
        outcomes = await asyncio.gather(
            *(_llm_tag_batch(b, llm) for b in batches),
            return_exceptions=True,
        )
        for idx, outcome in enumerate(outcomes):
            if isinstance(outcome, BaseException):
                continue
            tags_map, usage = outcome
            if usage is not None:
                usages.append(usage)
            llm_results.update(tags_map)
            if on_batch is not None:
                done = min((idx + 1) * batch_size, len(hard))
                on_batch(done, len(hard))

    # Step4：合并（LLM 优先，空字段回落规则）
    result = {
        d.dish_id: _merge_tags(llm_results.get(d.dish_id), rule_tags[d.dish_id])
        for d in dishes
    }
    return result, usages
