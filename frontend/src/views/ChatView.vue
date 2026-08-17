<script setup lang="ts">
/**
 * 聊天页（Claude/ChatGPT WebUI 风格布局）：
 * - 左侧可折叠会话栏：折叠按钮 + 新建会话 + 会话列表
 * - 会话分组（§16 决策 17）：默认分组 + 自定义分组（组头可折叠）
 *   - 拖拽移动：会话项拖到分组头即移入该组（拖到默认分组 = 移回默认；归档会话拖入 = 取消归档并归组）
 *   - 分组内新建：分组头"+"按钮 -> 新会话归属该分组（首条消息随请求下发 group）
 * - 每个会话（含当前选中）均可点"更多"：重命名 / 分叉 / 导出 / 归档
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  MoreFilled, EditPen, CopyDocument, Box, FolderOpened, Download,
  ArrowDown, ArrowRight, Plus, Fold, Expand, FolderAdd,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  apiArchiveSession, apiChatSessions, apiExportSession, apiForkSession,
  apiRenameSession, apiSetSessionGroup, type ChatSessionInfo,
} from '@/api/chat'
import StreamChat from '@/components/StreamChat.vue'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const route = useRoute()

const sessions = ref<ChatSessionInfo[]>([])
const activeSession = ref<number | null>(null)
/** 分组内新建会话的归属分组（§16 决策 17）：非空时首条消息的新会话归入该组 */
const pendingGroup = ref<string | null>(null)
const loadingSessions = ref(false)
const collapsed = ref(false)
const archivedOpen = ref(false)

/** 折叠的分组（key 为组名；'__default__' 表示默认分组） */
const closedGroups = ref<Set<string>>(new Set())
const DEFAULT_GROUP_KEY = '__default__'

const currentSessions = computed(() => sessions.value.filter((s) => !s.archived))
const archivedSessions = computed(() => sessions.value.filter((s) => s.archived))

/** 全部自定义分组名（去重，按字典序；含归档会话——组内会话归档后分组不消失，§16 决策 17） */
const groupNames = computed(() => {
  const names = new Set<string>()
  for (const s of sessions.value) {
    if (s.group) names.add(s.group)
  }
  return [...names].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
})

function sessionsInGroup(group: string | null): ChatSessionInfo[] {
  return currentSessions.value.filter((s) => (s.group ?? null) === group)
}

async function loadSessions() {
  if (!userStore.isLoggedIn) return
  loadingSessions.value = true
  try {
    sessions.value = await apiChatSessions()
  } catch {
    /* 接口异常：空列表 */
  } finally {
    loadingSessions.value = false
  }
}

function newSession() {
  activeSession.value = null
  pendingGroup.value = null
}

/** 分组内新建会话（§16 决策 17）：新会话归属该分组 */
function onNewInGroup(group: string | null) {
  activeSession.value = null
  pendingGroup.value = group
}

function selectSession(id: number) {
  activeSession.value = id
  pendingGroup.value = null
  closeMenu()
}

function toggleGroup(key: string) {
  const next = new Set(closedGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  closedGroups.value = next
}

// ── 拖拽移动会话到分组（§16 决策 17，原生 HTML5 DnD）────────────
const dragId = ref<number | null>(null)
const dragTarget = ref<string | null>(null)

function onDragStart(s: ChatSessionInfo, e: DragEvent) {
  dragId.value = s.id
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(s.id))
  }
}

function onDragOver(key: string, e: DragEvent) {
  if (dragId.value == null) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  dragTarget.value = key
}

function onDragLeave(key: string) {
  if (dragTarget.value === key) dragTarget.value = null
}

async function onDrop(key: string) {
  const id = dragId.value
  dragTarget.value = null
  dragId.value = null
  if (id == null) return
  const target = sessions.value.find((s) => s.id === id)
  if (!target) return
  // 归档会话拖入分组：取消归档 + 移入目标组（默认组 = group null）
  if (target.archived) await apiArchiveSession(id, false).catch(() => undefined)
  await apiSetSessionGroup(id, key === DEFAULT_GROUP_KEY ? null : key).catch(() => undefined)
  void loadSessions()
}

function onDragEnd() {
  dragId.value = null
  dragTarget.value = null
}

/** 侧边栏"新建分组"：把当前激活会话归入新组（空组无会话会自动消失，故必须绑定一个会话） */
async function onNewGroupFromSidebar() {
  if (activeSession.value == null) {
    ElMessage.warning('请先选择或新建一个会话，再为其创建分组')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt('输入分组名称（当前会话将移入该组）', '新建分组', {
      inputPattern: /^.{1,20}$/,
      inputErrorMessage: '分组名长度需在 1~20 字之间',
      confirmButtonText: '创建',
    })
    if (value) {
      await apiSetSessionGroup(activeSession.value, value)
      void loadSessions()
      ElMessage.success(`已创建分组「${value}」`)
    }
  } catch {
    /* 取消 */
  }
}

async function onArchive(session: ChatSessionInfo, e?: MouseEvent) {
  if (e) e.stopPropagation()
  await apiArchiveSession(session.id, !session.archived).catch(() => undefined)
  if (activeSession.value === session.id && !session.archived) {
    activeSession.value = null // 归档当前会话后回到新会话
  }
  void loadSessions()
}

async function onFork(session: ChatSessionInfo, e?: MouseEvent) {
  if (e) e.stopPropagation()
  try {
    const newId = await apiForkSession(session.id)
    activeSession.value = newId
    void loadSessions()
  } catch {
    /* 拦截器已提示 */
  }
}

async function onRename(session: ChatSessionInfo, e?: MouseEvent) {
  if (e) e.stopPropagation()
  try {
    const { value } = await ElMessageBox.prompt('输入新的会话标题', '重命名', {
      inputValue: session.title,
      inputPattern: /^.{1,40}$/,
      inputErrorMessage: '标题长度需在 1~40 字之间',
    })
    if (value && value !== session.title) {
      await apiRenameSession(session.id, value)
      void loadSessions()
    }
  } catch {
    /* 取消或失败 */
  }
}

/** "更多"自绘菜单（§9）：重命名 / 分叉 / 导出 / 归档（移动分组改为拖拽，§16 决策 17） */
const menuFor = ref<number | null>(null)

function toggleMenu(id: number, e: MouseEvent) {
  e.stopPropagation()
  menuFor.value = menuFor.value === id ? null : id
}

function closeMenu() {
  menuFor.value = null
}

function onMore(cmd: string, s: ChatSessionInfo) {
  if (cmd === 'rename') void onRename(s)
  else if (cmd === 'fork') void onFork(s)
  else if (cmd === 'export') void onExport(s)
  else if (cmd === 'archive') void onArchive(s)
}

onMounted(() => document.addEventListener('click', closeMenu))
onBeforeUnmount(() => document.removeEventListener('click', closeMenu))

/** 会话导出 Markdown（§10 可选扩展 4） */
async function onExport(s: ChatSessionInfo) {
  try {
    const blob = await apiExportSession(s.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `chat-${s.id}.md`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('会话已导出为 Markdown')
  } catch {
    /* 拦截器已提示 */
  }
}

function onSessionUpdated(sessionId: number) {
  activeSession.value = sessionId
  pendingGroup.value = null
  void loadSessions()
  // 标题由 AI 后台异步总结（§9）：延迟再刷一次，让新标题/新分组立即可见，无需手动刷新
  window.setTimeout(() => void loadSessions(), 3000)
}

// 会话列表定时静默刷新（§9）：AI 总结标题、分组变化等异步更新，轮询兜底避免"手动刷新才显示"
let refreshTimer: number | undefined
function startAutoRefresh() {
  if (refreshTimer !== undefined) return
  refreshTimer = window.setInterval(() => void loadSessions(), 15000)
}
function stopAutoRefresh() {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
}

watch(
  () => userStore.isLoggedIn,
  (v) => {
    if (v) {
      void loadSessions()
      startAutoRefresh()
    } else {
      stopAutoRefresh()
    }
  },
)

onMounted(() => {
  void loadSessions()
  startAutoRefresh()
  // 从个人中心"历史会话"跳转：?session=ID 直接打开对应会话（§10）
  const sid = route.query.session
  if (sid && !Array.isArray(sid) && /^\d+$/.test(sid)) {
    activeSession.value = Number(sid)
  }
})

onBeforeUnmount(() => stopAutoRefresh())
</script>

<template>
  <div class="chat-layout">
    <!-- 左侧会话栏（可折叠，仿 Claude/ChatGPT） -->
    <aside class="session-side" :class="{ collapsed }">
      <div class="side-head">
        <el-button v-if="!collapsed" class="new-btn" :disabled="!userStore.isLoggedIn" @click="newSession">
          <el-icon><Plus /></el-icon><span>新建会话</span>
        </el-button>
        <el-button v-else circle size="small" :disabled="!userStore.isLoggedIn" @click="newSession">
          <el-icon><Plus /></el-icon>
        </el-button>
        <el-button circle size="small" class="fold-btn" @click="collapsed = !collapsed">
          <el-icon><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
        </el-button>
      </div>

      <div v-if="!collapsed" v-loading="loadingSessions" class="session-list">
        <template v-if="userStore.isLoggedIn">
          <!-- 默认分组（未手动分组，可拖入、可新建） -->
          <div
            class="group-title arch-head"
            :class="{ 'drag-over': dragTarget === DEFAULT_GROUP_KEY }"
            @click="toggleGroup(DEFAULT_GROUP_KEY)"
            @dragover="onDragOver(DEFAULT_GROUP_KEY, $event)"
            @dragleave="onDragLeave(DEFAULT_GROUP_KEY)"
            @drop="onDrop(DEFAULT_GROUP_KEY)"
          >
            <el-icon class="arch-arrow">
              <ArrowDown v-if="!closedGroups.has(DEFAULT_GROUP_KEY)" /><ArrowRight v-else />
            </el-icon>
            <span class="group-name">默认分组{{ sessionsInGroup(null).length ? '（' + sessionsInGroup(null).length + '）' : '' }}</span>
            <el-button circle size="small" text class="group-new-btn" title="在该分组新建会话" @click.stop="onNewInGroup(null)">
              <el-icon><Plus /></el-icon>
            </el-button>
          </div>
          <div v-if="!closedGroups.has(DEFAULT_GROUP_KEY)" class="arch-list">
            <div
              v-for="s in sessionsInGroup(null)"
              :key="s.id"
              class="session-item"
              :class="{ active: s.id === activeSession, dragging: dragId === s.id }"
              draggable="true"
              @click="selectSession(s.id)"
              @dragstart="onDragStart(s, $event)"
              @dragend="onDragEnd"
            >
              <span class="session-title">{{ s.title }}</span>
              <div class="more-wrap" @click.stop>
                <el-button circle size="small" text class="arch-btn" title="更多" @click="toggleMenu(s.id, $event)">
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
                <div v-if="menuFor === s.id" class="more-menu" @click.stop>
                  <div class="menu-item" @click="onMore('rename', s)"><el-icon><EditPen /></el-icon>重命名</div>
                  <div class="menu-item" @click="onMore('fork', s)"><el-icon><CopyDocument /></el-icon>分叉会话</div>
                  <div class="menu-item" @click="onMore('export', s)"><el-icon><Download /></el-icon>导出 Markdown</div>
                  <div class="menu-item" @click="onMore('archive', s)"><el-icon><Box /></el-icon>归档</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 自定义分组（拖入目标 + 组内新建） -->
          <template v-for="g in groupNames" :key="g">
            <div
              class="group-title arch-head"
              :class="{ 'drag-over': dragTarget === g }"
              @click="toggleGroup(g)"
              @dragover="onDragOver(g, $event)"
              @dragleave="onDragLeave(g)"
              @drop="onDrop(g)"
            >
              <el-icon class="arch-arrow">
                <ArrowDown v-if="!closedGroups.has(g)" /><ArrowRight v-else />
              </el-icon>
              <span class="group-name">{{ g }}{{ sessionsInGroup(g).length ? '（' + sessionsInGroup(g).length + '）' : '' }}</span>
              <el-button circle size="small" text class="group-new-btn" title="在该分组新建会话" @click.stop="onNewInGroup(g)">
                <el-icon><Plus /></el-icon>
              </el-button>
            </div>
            <div v-if="!closedGroups.has(g)" class="arch-list">
              <div
                v-for="s in sessionsInGroup(g)"
                :key="s.id"
                class="session-item"
                :class="{ active: s.id === activeSession, dragging: dragId === s.id }"
                draggable="true"
                @click="selectSession(s.id)"
                @dragstart="onDragStart(s, $event)"
                @dragend="onDragEnd"
              >
                <span class="session-title">{{ s.title }}</span>
                <div class="more-wrap" @click.stop>
                  <el-button circle size="small" text class="arch-btn" title="更多" @click="toggleMenu(s.id, $event)">
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <div v-if="menuFor === s.id" class="more-menu" @click.stop>
                    <div class="menu-item" @click="onMore('rename', s)"><el-icon><EditPen /></el-icon>重命名</div>
                    <div class="menu-item" @click="onMore('fork', s)"><el-icon><CopyDocument /></el-icon>分叉会话</div>
                    <div class="menu-item" @click="onMore('export', s)"><el-icon><Download /></el-icon>导出 Markdown</div>
                    <div class="menu-item" @click="onMore('archive', s)"><el-icon><Box /></el-icon>归档</div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 新建分组（侧边栏入口） -->
          <div class="new-group-btn" @click="onNewGroupFromSidebar">
            <el-icon><FolderAdd /></el-icon><span>新建分组</span>
          </div>

          <!-- 归档对话（独立折叠区；拖入分组 = 取消归档并归组） -->
          <template v-if="archivedSessions.length">
            <div class="group-title arch-head" @click="archivedOpen = !archivedOpen">
              <el-icon class="arch-arrow">
                <ArrowDown v-if="archivedOpen" /><ArrowRight v-else />
              </el-icon>
              <span>归档（{{ archivedSessions.length }}）</span>
            </div>
            <div v-if="archivedOpen" class="arch-list">
              <div
                v-for="s in archivedSessions"
                :key="s.id"
                class="session-item archived"
                :class="{ active: s.id === activeSession, dragging: dragId === s.id }"
                draggable="true"
                @click="selectSession(s.id)"
                @dragstart="onDragStart(s, $event)"
                @dragend="onDragEnd"
              >
                <span class="session-title">{{ s.title }}</span>
                <el-tag v-if="s.group" size="small" effect="plain" class="arch-group-tag">{{ s.group }}</el-tag>
                <div class="more-wrap" @click.stop>
                  <el-button circle size="small" text class="arch-btn" title="更多" @click="toggleMenu(s.id, $event)">
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <div v-if="menuFor === s.id" class="more-menu" @click.stop>
                    <div class="menu-item" @click="onMore('rename', s)"><el-icon><EditPen /></el-icon>重命名</div>
                    <div class="menu-item" @click="onMore('fork', s)"><el-icon><CopyDocument /></el-icon>分叉会话</div>
                    <div class="menu-item" @click="onMore('export', s)"><el-icon><Download /></el-icon>导出 Markdown</div>
                    <div class="menu-item" @click="onMore('archive', s)"><el-icon><FolderOpened /></el-icon>取消归档</div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <el-empty
            v-if="currentSessions.length === 0 && !loadingSessions"
            :image-size="40"
            description="暂无会话，发条消息开始吧"
          />
        </template>
        <div v-else class="login-tip">登录后可保存历史会话</div>
      </div>
    </aside>

    <!-- 主区：消息流 + 输入区 -->
    <main class="chat-main">
      <StreamChat
        :session-id="activeSession"
        :default-group="pendingGroup"
        @session-updated="onSessionUpdated"
      />
    </main>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  gap: 0;
  height: calc(100vh - 60px);
  min-height: 480px;
}

/* ── 左侧会话栏 ── */
.session-side {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  transition: width 0.18s ease;
}

.session-side.collapsed {
  width: 52px;
}

.side-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 10px;
  border-bottom: 1px solid var(--border);
}

.new-btn {
  flex: 1;
}

.fold-btn {
  flex-shrink: 0;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.arch-head {
  cursor: pointer;
  user-select: none;
}

.arch-head:hover {
  color: var(--text-primary);
}

/* 拖拽目标高亮（§16 决策 17） */
.group-title.drag-over {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-radius: var(--radius-sm);
  outline: 1px dashed var(--accent);
  outline-offset: -1px;
}

.arch-arrow {
  font-size: 12px;
}

.group-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-new-btn {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.group-title:hover .group-new-btn {
  opacity: 1;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 14px;
  color: var(--text-primary);
  transition: background 0.12s ease;
}

.session-item:hover {
  background: var(--bg-hover);
}

.session-item.active {
  background: var(--bg-hover);
  color: var(--text-strong);
  font-weight: 600;
}

.session-item.archived .session-title {
  color: var(--text-secondary);
}

.session-item.dragging {
  opacity: 0.45;
}

.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 归档会话的分组标签（§16 决策 17：归档后分组不消失，标签便于识别归属） */
.arch-group-tag {
  flex-shrink: 0;
  max-width: 70px;
  font-size: 11px;
  padding: 0 6px;
  height: 20px;
  line-height: 20px;
}

.arch-group-tag :deep(span) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arch-btn {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.session-item:hover .arch-btn {
  opacity: 1;
}

/* 自绘"更多"菜单（§9）：相对会话项定位，点击外部关闭 */
.more-wrap {
  position: relative;
  flex-shrink: 0;
  display: flex;
}

.more-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  z-index: 30;
  min-width: 136px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  padding: 4px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
}

.menu-item:hover {
  background: var(--bg-hover);
  color: var(--text-strong);
}

.menu-divider {
  height: 1px;
  margin: 4px 6px;
  background: var(--border);
}

.arch-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  /* 分组下的会话缩进 + 树形左线（§16 决策 17 文件夹层级视觉） */
  margin-left: 14px;
  padding-left: 10px;
  border-left: 1px solid var(--border);
}

/* 新建分组（侧边栏底部入口，§16 决策 17） */
.new-group-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 1px dashed var(--border);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.new-group-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.login-tip {
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 24px 8px;
}

/* ── 主区 ── */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
</style>
