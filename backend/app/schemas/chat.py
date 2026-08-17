"""chat 请求/响应 DTO（§9.5 与 ORM/State 分离）。"""
from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    message_id: str | None = Field(default=None, max_length=64)  # 幂等（§9.1 要点 7）
    session_id: int | None = None
    user_id: str | None = None
    # 模型 / 强度选择（§9 聊天界面）：model=deepseek-v4-flash|deepseek-chat；strength=fast|balanced|deep
    model: str | None = Field(default=None, max_length=64)
    strength: str | None = Field(default=None, max_length=16)
    # 多 Provider（§10）：deepseek=默认；其他=用户自定义接入配置名（OpenAI 兼容 / Anthropic）
    provider: str | None = Field(default=None, max_length=64)
    # 新建会话的分组（§16 决策 17）：仅当 session_id 为空（新建会话）时生效；null=默认分组
    group: str | None = Field(default=None, max_length=40)
    # 一次性查询（首页推荐等，§10）：persist=false 不创建会话、不落库（无历史）
    persist: bool = True
    # 多样化（换一批，§10）：true 时 rank_fuse/planner 探索率提升，同约束下换新结果
    diversity: bool = False


class SessionUpdateRequest(BaseModel):
    """会话更新请求（§9）：归档 / 手动重命名（改名后 title_auto=0，AI 不再覆盖）/ 移动分组（§16 决策 17）。"""

    archived: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=40)
    # 会话分组（决策 17）：null=默认分组；空串/超长由 service 归一化
    group: str | None = Field(default=None, max_length=40)


class MessageUpdateRequest(BaseModel):
    """消息更新请求（§9 删除单轮问答）：hidden=true 软删除（聊天界面隐藏、历史保留）/ false 恢复。"""

    hidden: bool = False
