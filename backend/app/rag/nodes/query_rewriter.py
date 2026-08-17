"""查询扩写（§6.4）：口语 -> 检索语言 + 实体抽取；LLM 失败用原文兜底。

指代解析（§6.4 扩展 / 决策 16）："这三个菜""它们"等指代 -> 从最近一轮助手消息提取具体菜名，
拼入检索查询并回写 QueryState.named_dishes（generate 聚焦引用），解决多轮追问场景检索失败。
"""
from __future__ import annotations

from app.core.clients.llm import LLMClient
from app.core.exceptions import LLMError
from app.rag.state import AgentState, QueryState
from app.rag.utils import named_dishes

# 指代词（命中任一即尝试从历史解析菜名）
_REFER_KEYWORDS = ["这三个菜", "这些菜", "这个菜", "这两个菜", "上面", "刚才", "前面", "上述", "这些", "它们", "它们几个", "这几道", "这道菜", "那几道"]

_REWRITE_PROMPT = """你是菜谱搜索助手。把用户口语改写成更适合语义检索的查询，并抽取实体。
只输出 JSON：{{"rewritten_query": "扩写后的检索查询", "entities": {{"dish_names": [], "ingredients": [], "techniques": [], "cuisines": [], "flavors": []}}}}

规则：
1. 口语转检索语言："下饭"->"口味浓郁下饭"；"整点硬的"->"肉类硬菜"
2. 菜名规范化："西红柿炒蛋"->"西红柿炒鸡蛋"
3. 补全隐式语境："晚上"->补"晚餐"；"减肥"->补"清淡低油"
4. **指代解析**：用户说"这三个菜/它们/上面的菜"时，把对话历史中的具体菜名补进 rewritten_query 和 dish_names
5. 不知道的实体留空数组，不要编造

对话历史（最近 1 轮，用于指代解析）：
{history}

用户输入：{query}
"""


def _resolve_refs(query: str, history: list[dict]) -> list[str]:
    """规则指代解析（兜底）：query 含指代词时，从最近助手消息提取菜名（dish_meta 全量匹配）。"""
    if not any(k in query for k in _REFER_KEYWORDS):
        return []
    for h in reversed(history[-2:]):
        if h.get("role") == "assistant":
            return named_dishes(h.get("content", ""))
    return []


def query_rewriter(llm: LLMClient) -> object:
    async def _node(state: AgentState) -> dict:
        query = state["input"].query
        current: QueryState = state["query"]
        history = state["context"].session_history[-2:]  # 最近 1 轮（指代解析用）
        rewritten, entities = query, {}
        # 规则指代解析（兜底，不依赖 LLM）："这三个菜" -> 上一轮推荐/回答中的菜名
        resolved = _resolve_refs(query, history)

        try:
            hist_text = "\n".join(f"{h.get('role')}: {str(h.get('content'))[:200]}" for h in history)
            result = await llm.complete(_REWRITE_PROMPT.format(query=query[:200], history=hist_text or "（无）"))
            # _extract_json 内部已 json.loads，直接返回 dict（§llm.py）
            data = llm._extract_json(result.content)
            if isinstance(data.get("rewritten_query"), str) and data["rewritten_query"].strip():
                rewritten = data["rewritten_query"].strip()
            entities = data.get("entities") or {}
        except (LLMError, ValueError, TypeError):
            pass  # 兜底：原文直查

        # 合并指代解析的菜名（LLM 可能漏）：进 entities.dish_names + 拼入检索查询 + 回写 named_dishes
        dish_names = list(entities.get("dish_names") or [])
        for n in resolved:
            if n not in dish_names:
                dish_names.append(n)
        if dish_names:
            entities = {**entities, "dish_names": dish_names}
        if resolved and not any(n in rewritten for n in resolved):
            rewritten = f"{rewritten} {' '.join(resolved)}"

        # named_dishes：原文点名优先；否则用指代解析结果（供 generate 聚焦，§6.5 召回④）
        named = named_dishes(query) or resolved

        return {"query": current.model_copy(update={
            "rewritten": rewritten,
            "entities": entities,
            "named_dishes": named,
        })}

    return _node
