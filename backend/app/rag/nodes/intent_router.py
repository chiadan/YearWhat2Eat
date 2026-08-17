"""意图路由（§6.4 语义路由）：LLM agent 精判 + 规则兜底。

LLM 一次调用输出 {intent, confidence, personalize}（temperature=0.1）：
- intent: dish_qa | tips_qa | recommend | chitchat（走哪条链路）
- personalize: 是否应用千人千面硬过滤（§6.5 召回④ / 决策 16）——
    true  = 开放式推荐请求（"今天吃什么"），千人千面硬过滤生效
    false = 具体内容查询（点名具体菜/做法/技巧/闲聊），全量检索不拦截
  LLM 负责理解复合语义（如"除了宫保鸡丁还有什么推荐的" -> intent=recommend + personalize=true，
  点名菜由检索实体处理，推荐仍走千人千面）
- 规则兜底：LLM 失败/输出非法时——
  点名具体菜名（匹配 dish_meta 全量菜名，最长优先）-> personalize=false（必召回）；
  否则按 intent：recommend/plan_menu -> true，其余 -> false
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.core.clients.llm import LLMClient, LLMResult
from app.core.exceptions import LLMError
from app.rag.state import AgentState, Intent, QueryState
from app.rag.utils import named_dishes

_TIPS_KEYWORDS = [
    "焯水", "油温", "去腥", "糖色", "食品安全", "微波炉", "空气炸锅", "高压锅",
    "腌制", "腌", "凉拌", "技巧", "方法", "怎么判断", "多久", "注意事项", "保存",
]
_CHITCHAT_KEYWORDS = ["你好", "您好", "谢谢", "感谢", "你是谁", "早上好", "晚上好", "再见", "拜拜", "hi", "hello"]
_RECOMMEND_KEYWORDS = ["想吃", "推荐", "吃什么", "来点", "整点", "晚饭", "午餐", "早餐", "夜宵", "人", "菜单", "搭配"]

# 推荐场景意图：千人千面硬过滤生效（规则兜底用）
_PERSONALIZE_INTENTS = ("recommend", "plan_menu")


def _rule_intent(query: str) -> tuple[Intent, float]:
    q = query.lower()
    if any(k in q for k in _CHITCHAT_KEYWORDS) and len(query) <= 12:
        return "chitchat", 0.9
    if any(k in q for k in _TIPS_KEYWORDS):
        return "tips_qa", 0.7
    if any(k in q for k in _RECOMMEND_KEYWORDS):
        return "recommend", 0.6
    if any(k in q for k in ["怎么做", "怎么", "如何", "步骤", "做法", "要多久", "多少时间"]):
        return "dish_qa", 0.7
    return "dish_qa", 0.4  # 默认低置信度 dish_qa


def rule_personalize(query: str, intent: str) -> bool:
    """规则兜底场景判定（§6.5 召回④）：点名具体菜名 -> 全量必召回；否则按意图。"""
    if named_dishes(query):
        return False
    return intent in _PERSONALIZE_INTENTS


_INTENT_PROMPT = """你是「是啊吃什么」的意图分类器。请判断用户输入，只输出 JSON：
{{"intent": "dish_qa|tips_qa|recommend|chitchat", "confidence": 0.0~1.0, "personalize": true|false}}

- intent 含义：
  - dish_qa: 询问某道菜的做法/步骤/细节
  - tips_qa: 询问通用烹饪技巧（焯水、油温、去腥等）
  - recommend: 请求推荐菜/菜单/吃什么
  - chitchat: 寒暄闲聊，与菜谱无关
- personalize 含义（是否对该请求应用"千人千面"个性化硬过滤，如忌口/难度/工具）：
  - true: 开放式推荐请求（如"今天吃什么""推荐几道下饭菜""两人晚餐"）——按用户画像过滤
  - false: 用户指定了具体内容（点名某道菜/问做法/问技巧/闲聊）——不要按画像过滤，全量检索
  - 复合请求按主导意图判定：如"除了宫保鸡丁还有什么推荐的" -> intent=recommend, personalize=true
    （点名菜交给检索，推荐本身仍按画像过滤）；"宫保鸡丁怎么做" -> intent=dish_qa, personalize=false

用户输入：{query}
"""


def intent_router(llm: LLMClient) -> object:
    async def _node(state: AgentState) -> dict:
        query = state["input"].query
        intent, confidence = _rule_intent(query)
        personalize = rule_personalize(query, intent)
        # 点名菜检测（§6.5 召回④）：供 dish_qa 聚焦引用
        dishes = named_dishes(query)

        # LLM 精判（失败/超时不影响流程，用规则结果；输出非法字段同样回退）
        try:
            result: LLMResult = await llm.complete(_INTENT_PROMPT.format(query=query[:200]))
            # _extract_json 内部已 json.loads，直接返回 dict（§llm.py）
            data = llm._extract_json(result.content)
            if data.get("intent") in ("dish_qa", "tips_qa", "recommend", "chitchat"):
                intent = data["intent"]
                confidence = float(data.get("confidence", confidence))
                if isinstance(data.get("personalize"), bool):
                    personalize = data["personalize"]
        except (LLMError, ValueError, TypeError):
            pass

        return {"query": QueryState(
            intent=intent, confidence=confidence, personalize=personalize, named_dishes=dishes,
        )}

    return _node
