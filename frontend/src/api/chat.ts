/**
 * SSE 流式客户端（§9.1）：fetch + ReadableStream 逐帧解析。
 * - 携带 JWT（Bearer）；不用 EventSource（带不了请求头）
 * - message_id：客户端生成（crypto.randomUUID），断线重试复用，服务端幂等（§9.1 要点 7）
 * - 断线自动重试 1 次（3s 退避，复用 message_id），仍失败回调 error（§9.1 要点 3）
 * - AbortController 支持用户中断（§9.1 要点 2）
 */
import { useUserStore } from '@/stores/user'
import { http, unwrap } from './http'

export interface SourceRef {
  dish_id: string
  /** 菜名：后端 sources 帧字段为 name（§9.1）；历史兼容 dish_name */
  name?: string
  dish_name?: string
  category?: string
  score?: number
  /** 引用编号（§9.1 sources 帧 / generate 输出） */
  ref?: number
}

export interface ToolEvent {
  name: string
  args?: Record<string, unknown>
  summary?: string
}

export interface MenuPlan {
  meat?: { dish_id: string; name: string }[]
  veg?: { dish_id: string; name: string }[]
  soup?: { dish_id: string; name: string }[]
  ratio?: { veg: number; meat: number; people: number }
  reason?: string
}

export interface DoneInfo {
  trace_id: string
  session_id: number
  message_id: string
  sources: SourceRef[]
  duration_ms: number
  /** 本轮问答的数据库 id（§9 软删除入口） */
  message_ids?: { user?: number; assistant?: number }
}

export interface StreamError {
  code: string
  message: string
  retryable: boolean
}

export interface StreamCallbacks {
  onStatus?: (stage: string, traceId: string) => void
  onSources?: (items: SourceRef[]) => void
  onTool?: (tool: ToolEvent) => void
  onText?: (delta: string) => void
  onPlan?: (plan: MenuPlan) => void
  onDone?: (info: DoneInfo) => void
  onError?: (err: StreamError) => void
}

interface StreamOptions {
  sessionId?: number
  userId?: string
  signal?: AbortSignal
  /** 模型选择（§9 聊天界面）：格式 "provider::model"（deepseek::deepseek-v4-flash 或 自定义名::xxx） */
  model?: string
  /** 强度选择（§9）：fast | balanced | deep */
  strength?: string
  /** 多 Provider（§10）：deepseek=默认；其他=用户自定义接入配置名 */
  provider?: string
  /** 新建会话的分组（§16 决策 17）：仅 sessionId 为空时生效；null=默认分组 */
  group?: string | null
  /** 一次性查询（§10 首页推荐）：false 不创建会话不落库；默认 true */
  persist?: boolean
  /** 多样化（§10 换一批）：true 时后端探索率提升，同约束换新结果 */
  diversity?: boolean
}

/** 历史会话列表（§9 聊天界面左侧栏 / §10 Profile 对话历史） */
export interface ChatSessionInfo {
  id: number
  title: string
  archived?: boolean
  /** 会话分组（§16 决策 17）：null/undefined = 默认分组 */
  group?: string | null
  created_at: string | null
  last_message?: string | null
  message_count?: number
}

export async function apiChatSessions(): Promise<ChatSessionInfo[]> {
  const resp = await http.get('/chat/sessions')
  const data = unwrap<{ items?: ChatSessionInfo[] } | ChatSessionInfo[]>(resp)
  return Array.isArray(data) ? data : (data.items ?? [])
}

/** 归档/取消归档会话（§9 归档对话分组） */
export async function apiArchiveSession(sessionId: number, archived: boolean): Promise<void> {
  await http.patch(`/chat/sessions/${sessionId}`, { archived })
}

/** 手动重命名会话（§9：改名后 AI 不再自动覆盖标题） */
export async function apiRenameSession(sessionId: number, title: string): Promise<void> {
  await http.patch(`/chat/sessions/${sessionId}`, { title })
}

/** 移动会话到分组（§16 决策 17）：group=null 移回默认分组 */
export async function apiSetSessionGroup(sessionId: number, group: string | null): Promise<void> {
  await http.patch(`/chat/sessions/${sessionId}`, { group })
}

/** 软删除/恢复一组问答（§9）：聊天界面隐藏（user+assistant 成对），历史数据保留；messageId=该轮任意一条消息的数据库 id */
export async function apiHideTurn(messageId: number, hidden: boolean): Promise<void> {
  await http.patch(`/chat/messages/${messageId}`, { hidden })
}

/** 分叉会话（§9）：复制会话与历史消息为新会话，返回新 id */
export async function apiForkSession(sessionId: number): Promise<number> {
  const resp = await http.post(`/chat/sessions/${sessionId}/fork`)
  return unwrap<{ id: number }>(resp).id
}

/** 会话导出 Markdown（§10 可选扩展 4）：返回 Blob，前端触发下载 */
export async function apiExportSession(sessionId: number): Promise<Blob> {
  const resp = await http.get(`/chat/sessions/${sessionId}/export`, { responseType: 'blob' })
  return resp.data as Blob
}

/** 会话消息历史（§9） */
export interface HistoryMessage {
  id: number
  role: string
  content: string
  sources: SourceRef[]
}

export async function apiChatMessages(sessionId: number): Promise<HistoryMessage[]> {
  const resp = await http.get(`/chat/sessions/${sessionId}/messages`)
  const data = unwrap<{ items?: HistoryMessage[] } | HistoryMessage[]>(resp)
  return Array.isArray(data) ? data : (data.items ?? [])
}

/** 规则推荐（§10 首页，无 LLM）：POST /api/v1/recommend，毫秒级响应 */
export interface RuleRecommendParams {
  people: number
  meal_time: string
  flavors: string[]
  max_time_min: number
  want_soup?: boolean
  /** 换一批（§10）：同约束下探索采样 */
  diversity?: boolean
}

export interface RuleRecommendResult {
  plan: MenuPlan
  sources: SourceRef[]
  reason: string
}

export async function apiRuleRecommend(params: RuleRecommendParams): Promise<RuleRecommendResult> {
  return unwrap(await http.post('/recommend', {
    people: params.people,
    meal_time: params.meal_time,
    flavors: params.flavors,
    max_time_min: params.max_time_min,
    want_soup: params.want_soup ?? false,
    diversity: params.diversity ?? false,
  }))
}

export async function streamChat(
  message: string,
  callbacks: StreamCallbacks,
  options: StreamOptions = {},
): Promise<void> {
  const messageId = crypto.randomUUID()
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const store = useUserStore()

  // 闭包内调用：避免 TS 控制流收缩导致 optional call 推断为 never
  const notifyError = (code: string, message: string, retryable: boolean) => {
    callbacks.onError?.({ code, message, retryable })
  }

  const doRequest = async (signal: AbortSignal): Promise<void> => {
    const resp = await fetch(`${base}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(store.accessToken ? { Authorization: `Bearer ${store.accessToken}` } : {}),
      },
      body: JSON.stringify({
        message,
        message_id: messageId,
        session_id: options.sessionId,
        user_id: options.userId,
        model: options.model,
        strength: options.strength,
        provider: options.provider,
        group: options.group ?? null,
        persist: options.persist ?? true,
        diversity: options.diversity ?? false,
      }),
      signal,
    })

    if (!resp.ok || !resp.body) {
      let detail = `HTTP ${resp.status}`
      try {
        const j = await resp.json()
        detail = j.message || detail
      } catch {
        /* 非 JSON 错误体 */
      }
      throw Object.assign(new Error(detail), { retryable: resp.status >= 500 })
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let event: string | null = null
    let dataLines: string[] = []

    const flush = () => {
      if (!event || dataLines.length === 0) return
      const data = dataLines.join('\n')
      const payload = data.startsWith('{') ? (JSON.parse(data) as Record<string, unknown>) : data
      handleEvent(event, payload, callbacks)
      event = null
      dataLines = []
    }

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n')
      buf = parts.pop() ?? ''
      for (const line of parts) {
        if (line.startsWith(':')) continue // 心跳注释行
        if (line === '') {
          flush()
          continue
        }
        if (line.startsWith('event:')) {
          event = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim())
        }
      }
    }
    flush()
  }

  try {
    await doRequest(options.signal ?? new AbortController().signal)
  } catch (err) {
    const e = err as Error & { retryable?: boolean }
    if (options.signal?.aborted) return // 用户主动取消，静默
    // 自动重试 1 次（3s 退避，复用 message_id，§9.1 要点 3）
    if ((e.retryable ?? true) && !callbacks.onError) {
      await new Promise((r) => setTimeout(r, 3000))
      try {
        await doRequest(options.signal ?? new AbortController().signal)
        return
      } catch (err2) {
        notifyError('STREAM_FAILED', (err2 as Error).message, true)
        return
      }
    }
    notifyError('STREAM_FAILED', e.message, e.retryable ?? true)
  }
}

function handleEvent(event: string, payload: unknown, cb: StreamCallbacks) {
  const p = payload as Record<string, unknown>
  switch (event) {
    case 'status':
      cb.onStatus?.(String(p.stage ?? ''), String(p.trace_id ?? ''))
      break
    case 'sources':
      cb.onSources?.((p.items as SourceRef[]) ?? [])
      break
    case 'tool':
      cb.onTool?.({
        name: String(p.name ?? ''),
        args: (p.args as Record<string, unknown>) ?? {},
        summary: p.summary ? String(p.summary) : undefined,
      })
      break
    case 'text':
      cb.onText?.(String(p.delta ?? ''))
      break
    case 'plan':
      cb.onPlan?.(p as MenuPlan)
      break
    case 'done':
      cb.onDone?.(p as unknown as DoneInfo)
      break
    case 'error':
      cb.onError?.({
        code: String(p.code ?? 'UNKNOWN'),
        message: String(p.message ?? '未知错误'),
        retryable: Boolean(p.retryable),
      })
      break
  }
}
