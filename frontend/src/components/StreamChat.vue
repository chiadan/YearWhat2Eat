<script setup lang="ts">
/**
 * 流式聊天组件（§9.1 / §10）：Claude/ChatGPT WebUI 风格布局。
 * - 消息流居中限宽（768px）；助手消息纯文本流（无边框无背景）、用户消息浅色圆角块
 * - 输入区居中同宽：模型/强度选择一行（Claude 风格）+ 大圆角输入框 + 圆形发送/停止按钮（ChatGPT 风格）
 * - 会话绑定：sessionId 切换加载历史；模型/强度随请求下发（§9）
 * - 菜名链接化：sources/plan 构造 linkMap，正文菜名可点击跳详情
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Promotion, VideoPause } from '@element-plus/icons-vue'
import { apiHideTurn, streamChat, apiChatMessages, type MenuPlan, type SourceRef, type ToolEvent } from '@/api/chat'
import { useAiConfigStore, parseModel } from '@/stores/aiConfig'
import SourceCard from './SourceCard.vue'
import MenuCard from './MenuCard.vue'
import MdRender from './MdRender.vue'

interface ChatMessage {
  /** 数据库 id（§9 软删除入口；历史加载有值，流式消息 done 帧补齐） */
  id?: number
  role: 'user' | 'assistant'
  content: string
  sources: SourceRef[]
  plan: MenuPlan | null
  tools: ToolEvent[]
  done: boolean
  error: string | null
}

const props = defineProps<{
  sessionId?: number | null
  model?: string
  strength?: string
  /** 新建会话的分组（§16 决策 17：分组内新建会话）；发送首条消息时随请求下发，null=默认分组 */
  defaultGroup?: string | null
}>()

const emit = defineEmits<{ 'session-updated': [sessionId: number] }>()

const messages = ref<ChatMessage[]>([])
/** 当前流式轮次的 user 消息引用（§9 软删除：done 帧补齐数据库 id） */
const userMsgRef = ref<ChatMessage | null>(null)
const input = ref('')
const streaming = ref(false)
const loadingHistory = ref(false)
const abortController = ref<AbortController | null>(null)
const listRef = ref<HTMLElement | null>(null)

// 模型/强度本地状态（选择器在输入区上方，Claude 风格；初始值取 Profile AI 配置默认，§10）
const aiConfigStore = useAiConfigStore()
const localModel = ref(props.model || aiConfigStore.config.model)
const localStrength = ref(props.strength || aiConfigStore.config.strength)

watch(
  () => props.model,
  (v) => {
    if (v) localModel.value = v
  },
)
watch(
  () => props.strength,
  (v) => {
    if (v) localStrength.value = v
  },
)

/** 构造菜名链接映射（菜名 -> dish_id），供 MdRender 正文链接化（需求 3） */
function linkMapOf(m: ChatMessage): Record<string, string> {
  const map: Record<string, string> = {}
  for (const s of m.sources) {
    const name = s.name || s.dish_name
    if (name && !map[name]) map[name] = s.dish_id
  }
  for (const group of [m.plan?.meat ?? [], m.plan?.veg ?? [], m.plan?.soup ?? []]) {
    for (const d of group) {
      if (d.name && !map[d.name]) map[d.name] = d.dish_id
    }
  }
  return map
}

/** 引用编号 -> {菜名, dish_id}，正文 [n] 替换为菜名链接（§9.1 参考带菜名） */
function sourceMapOf(m: ChatMessage): Record<string, { name: string; dish_id: string }> {
  const map: Record<string, { name: string; dish_id: string }> = {}
  for (const s of m.sources) {
    const name = s.name || s.dish_name
    if (s.ref != null && name) map[String(s.ref)] = { name, dish_id: s.dish_id }
  }
  return map
}

async function loadHistory(sessionId: number) {
  loadingHistory.value = true
  try {
    const rows = await apiChatMessages(sessionId)
    messages.value = rows.map((r) => ({
      id: (r as { id?: number }).id,
      role: r.role === 'user' ? ('user' as const) : ('assistant' as const),
      content: r.content,
      sources: r.sources ?? [],
      plan: null,
      tools: [],
      done: true,
      error: null,
    }))
  } catch {
    messages.value = []
  } finally {
    loadingHistory.value = false
    void scrollToBottom()
  }
}

// 切换会话：清空并加载历史
watch(
  () => props.sessionId,
  (sid) => {
    if (streaming.value) stop()
    messages.value = []
    if (sid != null) void loadHistory(sid)
  },
)

// 进入聊天页：刷新今日用量（§10 预算提醒）+ 拉取自定义 Provider（§10 多 Provider 下拉）
onMounted(() => {
  void aiConfigStore.fetchToday()
  void aiConfigStore.fetchProviders()
})

// Provider 列表变化后，校验当前模型仍有效（自定义接入被删除则回退默认，§10）
watch(
  () => aiConfigStore.providers,
  (list) => {
    const { provider } = parseModel(localModel.value)
    if (provider !== 'deepseek' && !list.some((p) => p.name === provider)) {
      localModel.value = aiConfigStore.config.model
    }
  },
)

async function scrollToBottom() {
  await nextTick()
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: 'smooth' })
}

function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  // 每日用量预算提醒（§10 可选扩展 5）：超限阻止发送
  if (aiConfigStore.budgetExceeded) {
    ElMessage.warning(`已达今日用量上限（${aiConfigStore.config.dailyTokenLimit.toLocaleString()} tokens），请明日再试或在「个人中心-AI 设置」调整`)
    return
  }
  input.value = ''
  const userMsg: ChatMessage = { role: 'user', content: text, sources: [], plan: null, tools: [], done: true, error: null }
  const assistantMsg: ChatMessage = { role: 'assistant', content: '', sources: [], plan: null, tools: [], done: false, error: null }
  userMsgRef.value = userMsg // §9 软删除：done 帧补齐 user 消息的数据库 id
  messages.value.push(userMsg, assistantMsg)
  void runStream(text)
}

/** 软删除本组问答（§9）：聊天界面移除该 user+assistant 对，历史数据保留 */
async function onDeleteTurn(m: ChatMessage) {
  const id = m.id
  if (id == null) return
  try {
    await ElMessageBox.confirm('删除这组问答？仅从聊天界面隐藏，历史记录仍保留。', '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
    })
  } catch {
    return
  }
  try {
    await apiHideTurn(id, true)
    const idx = messages.value.indexOf(m)
    if (idx >= 0) {
      const start = idx > 0 && messages.value[idx - 1].role === 'user' ? idx - 1 : idx
      messages.value.splice(start, 2)
    }
    void scrollToBottom()
  } catch {
    /* 拦截器已提示 */
  }
}

/** 过程状态（§9.1 status 帧 → Claude 式阶段指示）：思考中 -> 检索中 -> ... -> 生成中 */
const stageLabel: Record<string, string> = {
  intent: '理解你的需求',
  analyze: '分析约束条件',
  retrieve: '检索知识库',
  rerank: '精排候选菜谱',
  plan: '规划今日菜单',
  generate: '组织回答',
}
const currentStage = ref<string | null>(null)
const stageVisible = computed(() => streaming.value && currentStage.value !== null)

async function runStream(text: string) {
  const current = messages.value[messages.value.length - 1]
  abortController.value = new AbortController()
  streaming.value = true
  const seenSources = new Set<string>()

  await streamChat(
    text,
    {
      onStatus: (stage) => {
        currentStage.value = stage
      },
      onSources: (items) => {
        const fresh = items.filter((s) => !seenSources.has(s.dish_id))
        fresh.forEach((s) => seenSources.add(s.dish_id))
        current.sources = [...current.sources, ...fresh]
      },
      onTool: (tool) => {
        current.tools.push(tool)
        void scrollToBottom()
      },
      onText: (delta) => {
        current.content += delta
        void scrollToBottom()
      },
      onPlan: (plan) => {
        current.plan = plan
        void scrollToBottom()
      },
      onDone: (info) => {
        current.done = true
        // 数据库 id 补齐（§9 软删除入口）
        if (info.message_ids?.user != null && userMsgRef.value) {
          userMsgRef.value.id = info.message_ids.user
        }
        if (info.message_ids?.assistant != null) current.id = info.message_ids.assistant
        if (info.session_id) emit('session-updated', info.session_id)
      },
      onError: (err) => {
        current.done = true
        current.error = err.message
      },
    },
    {
      sessionId: props.sessionId ?? undefined,
      model: parseModel(localModel.value).model,
      strength: localStrength.value,
      provider: parseModel(localModel.value).provider,
      group: props.defaultGroup ?? null,
      signal: abortController.value.signal,
    },
  )

  streaming.value = false
  abortController.value = null
  currentStage.value = null
  current.done = true
}

function stop() {
  abortController.value?.abort()
  streaming.value = false
  const current = messages.value[messages.value.length - 1]
  if (current && !current.done) {
    current.done = true
    current.error = '已中断（回答不完整）'
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="stream-chat">
    <!-- 消息流（居中限宽，ChatGPT 风） -->
    <div ref="listRef" v-loading="loadingHistory" class="msg-scroll">
      <!-- 过程状态指示（§9.1 status 帧，Claude 式）：提问后展示 agent 阶段，完成后消失 -->
      <div v-if="stageVisible" class="stage-bar">
        <span class="stage-dot" />
        <span class="stage-text">{{ stageLabel[currentStage!] ?? '处理中' }}</span>
      </div>
      <div class="msg-column">
        <div v-if="messages.length === 0 && !loadingHistory" class="empty-hint">
          <h2>今天吃什么？</h2>
          <p>试试这样问：</p>
          <div class="hint-list">
            <button class="hint-tag" @click="input = '两个人晚餐想吃辣的，30分钟能搞定'">两个人晚餐想吃辣的</button>
            <button class="hint-tag" @click="input = '宫保鸡丁怎么做'">宫保鸡丁怎么做</button>
            <button class="hint-tag" @click="input = '家里只有微波炉和电饭煲能做什么'">只有微波炉和电饭煲能做什么</button>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <!-- 用户消息：浅色圆角块（右对齐） -->
          <template v-if="m.role === 'user'">
            <div class="user-bubble">{{ m.content }}</div>
          </template>

          <!-- 助手消息：纯文本流（无边框无背景） -->
          <template v-else>
            <div class="assistant-block">
              <!-- 软删除本组问答（§9）：hover 显示，仅聊天界面隐藏、历史保留 -->
              <el-button
                v-if="m.id != null && !streaming"
                circle
                size="small"
                text
                class="del-turn-btn"
                title="删除这组问答"
                @click="onDeleteTurn(m)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
              <div v-if="m.tools.length" class="tool-list">
                <el-tag
                  v-for="(t, ti) in m.tools"
                  :key="ti"
                  size="small"
                  type="info"
                  effect="plain"
                  class="tool-tag"
                >
                  工具: {{ t.name }}{{ t.summary ? ` - ${t.summary}` : '' }}
                </el-tag>
              </div>
              <MdRender
                v-if="m.content"
                :content="m.content"
                :link-map="linkMapOf(m)"
                :source-map="sourceMapOf(m)"
              />
              <div v-else-if="streaming && i === messages.length - 1" class="thinking">
                <span class="dot" /><span class="dot" /><span class="dot" />
              </div>
              <MenuCard v-if="m.plan" :plan="m.plan" class="plan-card" />
              <SourceCard v-if="m.sources.length" :items="m.sources" />
              <el-alert v-if="m.error" :title="m.error" type="error" :closable="false" class="err-alert" />
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 输入区（居中限宽，Claude 风选择行 + ChatGPT 风输入框） -->
    <div class="input-wrap">
      <div class="input-column">
        <div class="gen-row">
          <el-select v-model="localModel" size="small" class="gen-select model-select">
            <el-option v-for="opt in aiConfigStore.modelOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-select v-model="localStrength" size="small" class="gen-select">
            <el-option v-for="s in ['fast', 'balanced', 'deep']" :key="s" :label="s === 'fast' ? '快速' : s === 'deep' ? '深度' : '均衡'" :value="s" />
          </el-select>
        </div>

        <div class="composer">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            :disabled="streaming"
            class="composer-input"
            placeholder="输入你的需求，Enter 发送，Shift+Enter 换行"
            @keydown="onKeydown"
          />
          <el-button
            v-if="streaming"
            circle
            type="danger"
            class="send-btn"
            @click="stop"
          >
            <el-icon :size="18"><VideoPause /></el-icon>
          </el-button>
          <el-button
            v-else
            circle
            type="primary"
            class="send-btn"
            :disabled="!input.trim()"
            @click="send"
          >
            <el-icon :size="18"><Promotion /></el-icon>
          </el-button>
        </div>
        <div class="composer-hint">内容由 AI 生成，仅供参考 · Enter 发送</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stream-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 420px;
}

/* ── 消息滚动区 ── */
.msg-scroll {
  flex: 1;
  overflow-y: auto;
}

/* 过程状态指示条（§9.1 status 帧 → Claude 式阶段展示） */
.stage-bar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 0;
  background: color-mix(in srgb, var(--bg-primary) 88%, transparent);
  backdrop-filter: blur(4px);
  border-bottom: 1px solid transparent;
}

.stage-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: stage-pulse 1.2s infinite ease-in-out;
}

@keyframes stage-pulse {
  0%,
  100% {
    opacity: 0.3;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1.15);
  }
}

.stage-text {
  font-size: 12px;
  color: var(--text-secondary);
  letter-spacing: 0.03em;
}

.msg-column {
  max-width: 768px;
  margin: 0 auto;
  padding: 24px 20px 8px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.empty-hint {
  margin: 70px auto;
  text-align: center;
  color: var(--text-primary);
}

.empty-hint h2 {
  font-size: 26px;
  margin: 0 0 10px;
  color: var(--text-strong);
}

.empty-hint p {
  color: var(--text-secondary);
  margin: 0 0 14px;
}

.hint-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.hint-tag {
  padding: 7px 14px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.hint-tag:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* 消息 */
.msg {
  display: flex;
  flex-direction: column; /* 助手消息多个子块纵向排列：正文 -> 菜单 -> 参考菜谱（文末下一行） */
  gap: 4px;
}

.msg.user {
  align-items: flex-end; /* 用户气泡右对齐（column 下由 align-items 控制） */
}

.user-bubble {
  max-width: 78%;
  padding: 10px 16px;
  border-radius: 18px;
  border-bottom-right-radius: 6px;
  background: var(--bg-hover);
  color: var(--text-primary);
  line-height: 1.7;
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 助手消息块：相对定位承载 hover 删除按钮（§9 软删除） */
.assistant-block {
  position: relative;
  min-width: 0;
}

.del-turn-btn {
  position: absolute;
  right: -8px;
  top: -4px;
  opacity: 0;
  transition: opacity 0.12s ease;
  color: var(--text-secondary);
}

.assistant-block:hover .del-turn-btn {
  opacity: 1;
}

.del-turn-btn:hover {
  color: var(--danger, #f56c6c);
}

/* 助手：纯文本流（ChatGPT 风） */
.tool-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.thinking {
  display: inline-flex;
  gap: 5px;
  padding: 6px 0;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: blink 1.2s infinite ease-in-out;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.25;
  }
  40% {
    opacity: 1;
  }
}

.plan-card {
  margin-top: 12px;
  max-width: 640px;
}

.err-alert {
  margin-top: 8px;
  max-width: 640px;
}

/* ── 输入区（ChatGPT 风） ── */
.input-wrap {
  padding: 8px 16px 12px;
  background: var(--bg-primary);
}

.input-column {
  max-width: 768px;
  margin: 0 auto;
}

.gen-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.gen-select {
  width: 170px;
}

.model-select {
  width: 230px;
}

.composer {
  position: relative;
}

.composer-input :deep(.el-textarea__inner) {
  border-radius: 24px;
  padding: 12px 52px 12px 18px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  box-shadow: none;
  font-size: 15px;
  line-height: 1.6;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer-input :deep(.el-textarea__inner:focus) {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.send-btn {
  position: absolute;
  right: 10px;
  bottom: 12px;
  width: 34px;
  height: 34px;
}

.composer-hint {
  margin-top: 6px;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
