"""分层 State（§6.1，M3 全量）。

- 公共层：InputState / OutputState —— SSE 只暴露 OutputState（§9.1）
- 内部层：ContextState / QueryState / RetrievalState / PlanningState
- 节点签名只声明自己需要的子状态（§6.1 命名空间化）
"""
from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Intent = Literal["dish_qa", "tips_qa", "recommend", "chitchat", "plan_menu", "shopping_list"]


# ── 公共层：客户端可见 ─────────────────────────────────────────
class InputState(BaseModel):
    query: str
    user_id: str | None = None
    session_id: str | None = None
    message_id: str | None = None       # 幂等（§9.1 要点 7）
    stream: bool = True


class OutputState(BaseModel):
    status: Literal["running", "done", "error"] = "running"
    answer: str = ""                    # 最终回答（流式增量写入）
    sources: list[dict] = Field(default_factory=list)   # [{dish_id, name, chunk_type, score, ref}]
    plan: dict | None = None            # 推荐模式：今日菜单（§6.5 planner 输出）
    events: list[dict] = Field(default_factory=list)    # 过程事件（status/sources/tool/plan）
    error: str | None = None


# ── 上下文层：会话与画像 ───────────────────────────────────────
class ContextState(BaseModel):
    session_history: list[dict] = Field(default_factory=list)  # [{role, content}] 最近 N 轮全文
    summary: str = ""          # 更早轮次滚动摘要（§6.2 第 7 条：超长会话压缩，存 chat_sessions.summary）
    profile: dict | None = None         # 画像快照（M4 填充，M3 为 None）


# ── 理解层：意图 / 扩写 / 结构化约束（§6.4 / §6.1） ─────────────
class DishConstraints(BaseModel):
    """约束解析产物（query_analyzer 输出）。"""

    people: int | None = None
    meal_time: str | None = None            # 早餐/午餐/晚餐/夜宵
    max_time_min: int | None = None
    flavors: list[str] = Field(default_factory=list)
    avoids: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    skill_level: str | None = None          # 新手/进阶/熟练
    diet_type: str | None = None            # 素食/减脂/清真
    want_meat: bool | None = None
    use_ingredients: list[str] = Field(default_factory=list)


class QueryState(BaseModel):
    intent: Intent = "dish_qa"
    confidence: float = 0.0             # <0.7 走兜底（§6.4）
    rewritten: str = ""                 # 扩写后的检索查询
    entities: dict = Field(default_factory=dict)
    constraints: DishConstraints = Field(default_factory=DishConstraints)
    # query 点名的具体菜名（intent_router 规则检测，dish_meta 全量菜名子串匹配）：
    # 供 dish_qa 聚焦引用（§6.5 召回④ / 决策 16）——generate 只引用点名菜，不混入其他菜
    named_dishes: list[str] = Field(default_factory=list)
    # 是否应用千人千面硬过滤（§6.5 召回④ / 决策 16，intent_router 意图 agent 产出）：
    #   True = 推荐场景（忌口/素食/难度/工具/近7天做过生效）
    #   False = 具体内容查询（点名具体菜/做法/技巧问答），只保留会话显式约束，保证指定菜必召回
    personalize: bool = True
    # 多样化（换一批，§10）：rank_fuse/planner 探索率提升，同约束下产出不同结果
    diversity: bool = False


# ── 检索层：三路召回 + 精排 + 融合（§6.5） ─────────────────────
class RetrievalState(BaseModel):
    vector_hits: list[dict] = Field(default_factory=list)   # [{id, score, payload, source}]
    graph_hits: list[dict] = Field(default_factory=list)    # [{dish_id, weight}]
    rule_hits: list[dict] = Field(default_factory=list)     # 规则过滤后的候选 [{dish_id, name, ...}]
    hard_filtered: list[dict] = Field(default_factory=list) # [{dish_id, name, reason}]（可解释）
    reranked: list[dict] = Field(default_factory=list)      # RRF top-30 -> reranker top-15
    fused: list[dict] = Field(default_factory=list)         # rank_fuse 融合打分（含 final_score）


# ── 规划层：菜单组合（仅 recommend / plan_menu，§6.5 三） ───────
class PlanningState(BaseModel):
    ratio: dict | None = None               # {meat: b, veg: a}（荤素公式）
    meat_candidates: list[dict] = Field(default_factory=list)
    veg_candidates: list[dict] = Field(default_factory=list)
    plan: dict | None = None                # {meat: [...], veg: [...], soup: [...], reason}


# ── 内部总状态：仅图内部可见，不向客户端流式暴露 ──────────────
class AgentState(TypedDict):
    input: InputState
    context: ContextState
    query: QueryState
    retrieval: RetrievalState
    planning: PlanningState
    output: OutputState
