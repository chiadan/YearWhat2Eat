"""生成节点（§9.1 text 帧来源）：DeepSeek 流式生成 + 引用结构化。

- 流式：节点内 yield token -> LangGraph stream_mode="custom" -> chat_service 转 SSE text 帧
- 引用：上下文编号 [1][2]，sources 结构化写入 OutputState（SSE sources 帧）
- token 预算：检索上下文 ≤ ~6000 字符（§7.3）
"""
from __future__ import annotations

from langgraph.config import get_stream_writer

from app.core.clients.llm import LLMClient
from app.rag.prompts import get_prompt
from app.rag.state import AgentState, OutputState

_CONTEXT_CHARS = 6000
_MAX_ITEMS = 10


def _build_context_and_sources(state: AgentState) -> tuple[str, list[dict]]:
    hits = state["retrieval"].reranked
    intent = state["query"].intent
    named = state["query"].named_dishes or []

    # 具体问答聚焦（§6.5 召回④ / 决策 16）：点名菜时只引用该菜，不混入其他菜谱；
    # 聚焦集为空（名字未匹配）则回退全部，保证 context 不空
    focus_limit = 400
    if intent == "dish_qa" and named:
        focused = [h for h in hits if (h.get("name") or "") in named]
        if focused:
            hits = focused
            focus_limit = 800  # 聚焦菜放宽截断，给完整做法更多空间

    parts: list[str] = []
    sources: list[dict] = []
    total = 0
    for i, hit in enumerate(hits[: _MAX_ITEMS], start=1):
        # rerank 节点输出扁平结构（text 在顶层，§6.5 融合②）；兼容历史 payload 结构
        payload = hit.get("payload") or {}
        text = (payload.get("text") or hit.get("text") or "")[:focus_limit]
        if not text:
            continue
        parts.append(f"[{i}] {text}")
        total += len(text)
        sources.append(
            {
                "ref": i,
                "dish_id": payload.get("dish_id") or hit.get("dish_id"),
                "name": payload.get("dish_name")
                or payload.get("name")
                or hit.get("name")
                or hit.get("title"),
                "source": hit.get("source"),
                "score": round(float(hit.get("rerank_score") or hit.get("score") or 0), 4),
            }
        )
        if total >= _CONTEXT_CHARS:
            break
    return "\n\n".join(parts), sources


def generate(llm: LLMClient) -> object:
    async def _node(state: AgentState):
        query = state["input"].query
        intent = state["query"].intent
        output: OutputState = state["output"]
        output.status = "running"

        if intent == "chitchat":
            prompt = get_prompt("chitchat").format(query=query[:200])
        elif intent in ("recommend", "plan_menu"):
            plan = state["planning"].plan
            if plan and (plan.get("meat") or plan.get("veg") or plan.get("soup")):
                output.plan = plan
                output.events.append({"type": "plan", "plan": plan})
                # 通用引用（§9.1）：推荐场景的参考菜谱 = 今日菜单中的菜（可点击跳详情）
                ref_sources = [
                    {"ref": i, "dish_id": d["dish_id"], "name": d["name"], "source": "plan", "score": 0}
                    for i, d in enumerate(
                        list(plan.get("meat", [])) + list(plan.get("veg", [])) + list(plan.get("soup", [])),
                        start=1,
                    )
                    if d.get("dish_id") and d.get("name")
                ]
                if ref_sources:
                    output.sources = ref_sources
                    output.events.append({"type": "sources", "items": ref_sources})
                dishes_text = "、".join(
                    [f"{d['name']}（荤）" for d in plan.get("meat", [])]
                    + [f"{d['name']}（素）" for d in plan.get("veg", [])]
                    + [f"{d['name']}（汤）" for d in plan.get("soup", [])]
                )
                ratio = plan.get("ratio") or {}
                prompt = get_prompt("recommend_generate").format(
                    context=f"今日菜单（{ratio.get('people', '?')} 人，荤素 {ratio.get('veg', '?')} 素 + {ratio.get('meat', '?')} 荤）：{dishes_text}",
                    query=query[:200],
                )
            else:
                # plan 为空（约束过严）：引用检索候选作为参考，诚实说明未找到完全匹配
                context, sources = _build_context_and_sources(state)
                if context:
                    output.sources = sources
                    output.events.append({"type": "sources", "items": sources})
                prompt = (
                    "用户想让你推荐吃的，但候选为空（可能约束过严）。"
                    "请诚实说明没有找到完全匹配的菜，并给出放宽约束的建议。\n用户需求：" + query[:200]
                )
        else:  # dish_qa / tips_qa
            context, sources = _build_context_and_sources(state)
            output.sources = sources
            output.events.append({"type": "sources", "items": sources})
            if not context:
                prompt = "知识库检索结果为空。请说明未检索到相关内容，并建议换一种问法。\n用户问题：" + query[:200]
            else:
                prompt = get_prompt("qa_generate").format(context=context, query=query[:200])

        parts: list[str] = []
        # 多轮历史拼接（§6.2 上下文管理，M2：最近 6 轮，每轮截断）
        history = state["context"].session_history[-6:]
        # 滚动摘要（§6.2 第 7 条）：超长会话的早期信息经压缩后前置注入，最近全文在后
        summary = (state["context"].summary or "").strip()
        if summary and intent != "chitchat":
            prompt = "早前对话摘要：\n" + summary[:800] + "\n\n" + prompt
        if history and intent != "chitchat":
            hist_text = "\n".join(f"{h.get('role')}: {str(h.get('content'))[:200]}" for h in history)
            prompt = "对话历史：\n" + hist_text + "\n\n" + prompt

        # 流式：get_stream_writer 推送 token 到 stream_mode="custom"（§9.1 text 帧）
        writer = get_stream_writer()
        async for token in llm.stream(prompt):
            parts.append(token)
            writer(token)

        output.answer = "".join(parts)
        output.status = "done"
        return {"output": output}

    return _node
