"""约束解析（§6.2 query_analyzer）：自然语言 -> DishConstraints 结构化约束。

- LLM 结构化输出（temperature=0.1，§7.3）；失败/超时走规则兜底
- 上轮约束继承（§6.2 第 7 条）：prompt 携带最近 2 轮 user 消息，LLM 合并延续
"""
from __future__ import annotations

import re

from app.core.clients.llm import LLMClient
from app.core.exceptions import LLMError
from app.rag.state import AgentState, DishConstraints, QueryState

_PEOPLE_RE = re.compile(r"([\d一二两三四五六七八九十]+)\s*[个人位]")
_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _parse_people(raw: str) -> int | None:
    """解析人数（支持阿拉伯数字与中文数字：两/三/十几/二十几）。"""
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if "十" in raw:
        head, _, tail = raw.partition("十")
        tens = _CN_NUM.get(head, 1) * 10
        ones = _CN_NUM.get(tail, 0)
        return tens + ones
    return _CN_NUM.get(raw)
_TIME_RE = re.compile(r"(\d+)\s*分钟")
_AVOID_WORDS = ["香菜", "内脏", "海鲜", "羊肉", "芹菜", "韭菜", "苦瓜", "生姜", "大蒜", "葱", "辣", "肥肉"]
_FLAVOR_WORDS = {
    "辣": ["辣", "麻辣", "香辣"],
    "清淡": ["清淡", "不油腻", "清爽"],
    "甜": ["甜"],
    "酸": ["酸"],
    "咸鲜": ["咸鲜", "下饭"],
}
_MEAL_WORDS = {"早餐": ["早餐", "早饭"], "午餐": ["午餐", "午饭", "中午"], "晚餐": ["晚餐", "晚饭", "晚上"], "夜宵": ["夜宵", "深夜", "宵夜"]}

_CONSTRAINTS_PROMPT = """你是菜单规划师。从用户需求中提取结构化约束，只输出 JSON：
{{"people": 人数(整数或null), "meal_time": "早餐|午餐|晚餐|夜宵|null", "max_time_min": 最大制作分钟(整数或null),
  "flavors": [口味数组，如 辣/清淡/甜/酸/咸鲜], "avoids": [忌口食材数组], "tools": [可用厨具数组],
  "skill_level": "新手|进阶|熟练|null", "diet_type": "素食|减脂|清真|null",
  "want_meat": true或false或null, "use_ingredients": [想用的食材数组]}}

规则：
1. 只提取明确表达的信息，不确定的置 null/空数组
2. "不吃X"进 avoids；"想吃X"进 flavors 或 use_ingredients
3. 对话历史中的约束应延续（用户上一轮说"不吃辣"，本轮默认可继承）

对话历史（最近2轮）：
{history}

用户需求：{query}
"""


def _rule_constraints(query: str, history: list[dict]) -> DishConstraints:
    """规则兜底（LLM 不可用时，§7.3 错误降级联动）。"""
    text = query + " " + " ".join(h.get("content", "") for h in history[-2:])

    people_m = _PEOPLE_RE.search(text)
    time_m = _TIME_RE.search(text)

    avoids = [w for w in _AVOID_WORDS if f"不{w}" in text or f"不吃{w}" in text or f"不要{w}" in text]
    flavors = [f for f, kws in _FLAVOR_WORDS.items() if any(k in text for k in kws)]
    meal_time = next((m for m, kws in _MEAL_WORDS.items() if any(k in text for k in kws)), None)

    diet_type = None
    if any(k in text for k in ("减肥", "减脂", "低卡")):
        diet_type = "减脂"
    elif "素食" in text:
        diet_type = "素食"

    return DishConstraints(
        people=_parse_people(people_m.group(1)) if people_m else None,
        meal_time=meal_time,
        max_time_min=int(time_m.group(1)) if time_m else None,
        flavors=flavors,
        avoids=avoids,
        diet_type=diet_type,
    )


def query_analyzer(llm: LLMClient) -> object:
    async def _node(state: AgentState) -> dict:
        query = state["input"].query
        history = state["context"].session_history[-4:]  # 最近 2 轮（user+assistant 成对）
        current: QueryState = state["query"]
        constraints = _rule_constraints(query, history)

        try:
            hist_text = "\n".join(f"{h.get('role')}: {str(h.get('content'))[:150]}" for h in history)
            # 滚动摘要（§6.2 第 7 条）：早期约束（忌口/人数等）随摘要继承
            summary = (state["context"].summary or "").strip()
            hist_for_prompt = summary[:600] + "\n\n" + hist_text if summary else hist_text
            result = await llm.complete(
                _CONSTRAINTS_PROMPT.format(history=hist_for_prompt or "（无）", query=query[:200])
            )
            data = llm._extract_json(result.content)
            if isinstance(data, dict):
                constraints = DishConstraints(
                    people=data.get("people"),
                    meal_time=data.get("meal_time"),
                    max_time_min=data.get("max_time_min"),
                    flavors=list(data.get("flavors") or []),
                    avoids=list(data.get("avoids") or []),
                    tools=list(data.get("tools") or []),
                    skill_level=data.get("skill_level"),
                    diet_type=data.get("diet_type"),
                    want_meat=data.get("want_meat"),
                    use_ingredients=list(data.get("use_ingredients") or []),
                )
        except (LLMError, ValueError, TypeError):
            pass  # 规则兜底

        return {"query": current.model_copy(update={"constraints": constraints})}

    return _node
