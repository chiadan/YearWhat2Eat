<script setup lang="ts">
/**
 * 个人中心（§10 / Profile AI 配置）：
 * 画像问卷（口味雷达图）、AI 设置（默认模型/强度）、API 用量统计（今日/7 天/累计 + 按模型/节点）、
 * 我的收藏、行为历史、历史会话（点击跳聊天页打开）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { use, init, type ECharts } from 'echarts/core'
import { RadarChart, LineChart } from 'echarts/charts'
import { RadarComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useAiConfigStore } from '@/stores/aiConfig'
import {
  apiGetAiKey,
  apiSetAiKey,
  apiDeleteAiKey,
  apiGetAiProviders,
  apiSetAiProviders,
  apiUsage,
  type AiProvider,
  type UsageStats,
} from '@/api/users'
import { apiChatSessions, apiSetSessionGroup, type ChatSessionInfo } from '@/api/chat'
import { apiFavorites, apiHistory, apiRemoveFavorite, type DishSummary } from '@/api/dishes'
import ProfileForm from '@/components/ProfileForm.vue'
import DishCard from '@/components/DishCard.vue'

// ECharts 按需注册（§7.2：雷达 + 折线）
use([RadarChart, LineChart, RadarComponent, GridComponent, TooltipComponent, CanvasRenderer])

const userStore = useUserStore()
const aiConfigStore = useAiConfigStore()
const router = useRouter()

const tab = ref<'profile' | 'ai-config' | 'usage' | 'favorites' | 'history' | 'sessions'>('profile')
const favorites = ref<DishSummary[]>([])
const history = ref<{ dish_id: string; name: string; action: string; created_at: string }[]>([])
const sessions = ref<ChatSessionInfo[]>([])
const chartRef = ref<HTMLElement | null>(null)
const usageChartRef = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
let usageChart: ECharts | null = null

// ── AI 设置 ──
const aiModel = ref(aiConfigStore.config.model)
const aiStrength = ref(aiConfigStore.config.strength)
const aiLimit = ref(aiConfigStore.config.dailyTokenLimit)
// BYOK（§10）：用户自定义 DeepSeek Key
const hasCustomKey = ref(false)
const customKeyInput = ref('')
const keySaving = ref(false)

// ── 多 Provider（§10）：自定义接入（OpenAI 兼容 / Anthropic）──
const providerList = ref<AiProvider[]>([])
const providerSaving = ref(false)
const providerDialog = ref(false)
const providerForm = ref<{
  name: string
  provider_type: 'openai' | 'anthropic'
  base_url: string
  api_key: string
  modelsText: string
}>({ name: '', provider_type: 'openai', base_url: '', api_key: '', modelsText: '' })
const editingProviderName = ref<string | null>(null)

async function loadProviders() {
  try {
    providerList.value = await apiGetAiProviders()
    void aiConfigStore.fetchProviders()
  } catch {
    /* 拦截器已提示 */
  }
}

function openAddProvider() {
  editingProviderName.value = null
  providerForm.value = { name: '', provider_type: 'openai', base_url: '', api_key: '', modelsText: '' }
  providerDialog.value = true
}

function openEditProvider(p: AiProvider) {
  editingProviderName.value = p.name
  providerForm.value = {
    name: p.name,
    provider_type: p.provider_type,
    base_url: p.base_url,
    api_key: '',
    modelsText: (p.models ?? []).join(', '),
  }
  providerDialog.value = true
}

async function saveProvider() {
  const f = providerForm.value
  const name = f.name.trim()
  if (!name) {
    ElMessage.warning('请填写接入名称')
    return
  }
  const dup = providerList.value.find((p) => p.name === name && p.name !== editingProviderName.value)
  if (dup) {
    ElMessage.warning(`接入名称「${name}」已存在`)
    return
  }
  if (!f.base_url.trim()) {
    ElMessage.warning('请填写 Base URL')
    return
  }
  const models = f.modelsText.split(/[,，]/).map((m) => m.trim()).filter(Boolean)
  if (models.length === 0) {
    ElMessage.warning('请至少填写一个模型名（逗号分隔）')
    return
  }
  if (!editingProviderName.value && !f.api_key.trim()) {
    ElMessage.warning('新增接入必须填写 API Key')
    return
  }
  const entry: AiProvider = {
    name,
    provider_type: f.provider_type,
    base_url: f.base_url.trim(),
    models,
    api_key: f.api_key.trim() || undefined,
  }
  providerSaving.value = true
  try {
    const rest = providerList.value.filter((p) => p.name !== editingProviderName.value)
    const saved = await apiSetAiProviders([...rest, entry])
    providerList.value = saved
    providerDialog.value = false
    void aiConfigStore.fetchProviders()
    ElMessage.success('接入配置已保存（Key 加密存于后端）')
  } finally {
    providerSaving.value = false
  }
}

async function removeProvider(p: AiProvider) {
  try {
    await ElMessageBox.confirm(`删除接入「${p.name}」？其 API Key 将一并清除。`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  providerSaving.value = true
  try {
    const saved = await apiSetAiProviders(providerList.value.filter((x) => x.name !== p.name))
    providerList.value = saved
    void aiConfigStore.fetchProviders()
    ElMessage.success('已删除接入')
  } finally {
    providerSaving.value = false
  }
}

async function loadAiKey() {
  try {
    hasCustomKey.value = (await apiGetAiKey()).has_custom_key
  } catch {
    /* 静默 */
  }
}

async function saveCustomKey() {
  const key = customKeyInput.value.trim()
  if (!key) {
    ElMessage.warning('请输入 API Key')
    return
  }
  keySaving.value = true
  try {
    await apiSetAiKey(key)
    hasCustomKey.value = true
    customKeyInput.value = ''
    ElMessage.success('自定义 Key 已保存（仅存于后端加密存储）')
  } finally {
    keySaving.value = false
  }
}

async function clearCustomKey() {
  try {
    await apiDeleteAiKey()
    hasCustomKey.value = false
    ElMessage.success('已清除自定义 Key，回退系统默认 Key')
  } catch {
    /* 拦截器已提示 */
  }
}

function saveAiConfig() {
  aiConfigStore.setConfig({
    model: aiModel.value,
    strength: aiStrength.value,
    dailyTokenLimit: aiLimit.value,
  })
  void aiConfigStore.fetchToday()
  ElMessage.success('AI 配置已保存（聊天页默认生效）')
}

// ── 用量统计 ──
const usage = ref<UsageStats | null>(null)
const usageLoading = ref(false)

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

async function loadUsage() {
  usageLoading.value = true
  try {
    usage.value = await apiUsage()
    renderUsageChart()
  } finally {
    usageLoading.value = false
  }
}

function renderUsageChart() {
  if (!usageChartRef.value || !usage.value) return
  if (!usageChart) usageChart = init(usageChartRef.value)
  const dark = document.documentElement.classList.contains('dark')
  const text = dark ? '#8b949e' : '#59636e'
  usageChart.setOption(
    {
      tooltip: { trigger: 'axis' },
      grid: { left: 48, right: 16, top: 20, bottom: 28 },
      xAxis: { type: 'category', data: usage.value.by_day.map((d) => d.date), axisLabel: { color: text } },
      yAxis: { type: 'value', axisLabel: { color: text } },
      series: [
        {
          name: 'token 用量',
          type: 'line',
          smooth: true,
          data: usage.value.by_day.map((d) => d.tokens),
          lineStyle: { color: '#268bd2', width: 2 },
          itemStyle: { color: '#268bd2' },
          areaStyle: { color: 'rgba(38,139,210,0.15)' },
        },
      ],
    },
    true,
  )
}

// ── 口味雷达 ──
const radarValues = computed(() => {
  const p = userStore.profile
  if (!p) return [3, 3, 3, 3]
  return [p.flavor_spicy, p.flavor_sweet, p.flavor_sour, p.flavor_light]
})

function renderChart() {
  if (!chartRef.value) return
  if (!chart) chart = init(chartRef.value)
  const dark = document.documentElement.classList.contains('dark')
  const text = dark ? '#93a1a1' : '#657b83'
  chart.setOption(
    {
      radar: {
        indicator: [
          { name: '辣', max: 5 },
          { name: '甜', max: 5 },
          { name: '酸', max: 5 },
          { name: '清淡', max: 5 },
        ],
        axisName: { color: text },
        splitLine: { lineStyle: { color: dark ? '#586e75' : '#93a1a1' } },
      },
      series: [
        {
          type: 'radar',
          data: [{ value: radarValues.value, name: '我的口味', areaStyle: { color: 'rgba(38,139,210,0.25)' } }],
          lineStyle: { color: '#268bd2' },
          itemStyle: { color: '#268bd2' },
        },
      ],
    },
    true,
  )
}

function onThemeChanged() {
  renderChart()
  renderUsageChart()
}

// ── 收藏 / 历史 / 会话 ──
async function loadTabs() {
  if (tab.value === 'favorites') {
    const resp = await apiFavorites()
    const raw = Array.isArray(resp)
      ? (resp as { dish_id: string; name: string }[])
      : ((resp as { items?: { dish_id: string; name: string }[] }).items ?? [])
    favorites.value = raw.map((f) => ({ ...f, category: '', difficulty: null, time_est: null }))
  }
  if (tab.value === 'history') {
    const resp = await apiHistory()
    history.value = Array.isArray(resp)
      ? (resp as { dish_id: string; name: string; action: string; created_at: string }[])
      : ((resp as { items?: { dish_id: string; name: string; action: string; created_at: string }[] })?.items ?? [])
  }
  if (tab.value === 'sessions') {
    sessions.value = await apiChatSessions().catch(() => [])
  }
  if (tab.value === 'usage') {
    await loadUsage()
  }
}

async function removeFav(id: string) {
  await apiRemoveFavorite(id)
  favorites.value = favorites.value.filter((f) => f.dish_id !== id)
  ElMessage.success('已取消收藏')
}

async function onSaved() {
  await userStore.loadProfile()
  renderChart()
}

function openSession(id: number) {
  void router.push({ name: 'chat', query: { session: String(id) } })
}

// ── 历史会话按分组展示（§16 决策 17：默认分组 + 自定义分组）──
const profileGroupNames = computed(() => {
  const names = new Set<string>()
  for (const s of sessions.value) {
    if (s.group) names.add(s.group)
  }
  return [...names].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
})

const sessionGroups = computed(() => {
  const groups: { key: string; name: string; items: ChatSessionInfo[] }[] = []
  const def = sessions.value.filter((s) => !s.group)
  if (def.length) groups.push({ key: '__default__', name: '默认分组', items: def })
  for (const gn of profileGroupNames.value) {
    const items = sessions.value.filter((s) => s.group === gn)
    if (items.length) groups.push({ key: gn, name: gn, items })
  }
  return groups
})

async function onMoveSession(row: ChatSessionInfo, value: string) {
  if (value === '__new__') {
    try {
      const { value: name } = await ElMessageBox.prompt('输入新分组名称（该会话将移入）', '新建分组', {
        inputPattern: /^.{1,20}$/,
        inputErrorMessage: '分组名长度需在 1~20 字之间',
        confirmButtonText: '创建',
      })
      if (name) {
        await apiSetSessionGroup(row.id, name)
        void loadTabs()
      }
    } catch {
      /* 取消 */
    }
    return
  }
  await apiSetSessionGroup(row.id, value || null)
  void loadTabs()
}

watch(tab, () => void loadTabs())
watch(radarValues, () => renderChart())

onMounted(() => {
  void userStore.loadProfile()
  void loadTabs()
  void loadAiKey()
  void loadProviders()
  renderChart()
  window.addEventListener('theme-changed', onThemeChanged)
})

onBeforeUnmount(() => {
  window.removeEventListener('theme-changed', onThemeChanged)
  chart?.dispose()
  usageChart?.dispose()
  chart = null
  usageChart = null
})
</script>

<template>
  <div class="profile-view">
    <div class="head-row">
      <h2>{{ userStore.user?.is_guest ? '游客中心' : userStore.user?.username }}</h2>
      <el-tag v-if="userStore.isGuest" type="warning">游客模式 · 注册后数据自动合并</el-tag>
    </div>

    <el-tabs v-model="tab">
      <!-- 画像问卷 -->
      <el-tab-pane label="画像问卷" name="profile">
        <div class="profile-grid">
          <div class="app-card">
            <ProfileForm v-if="userStore.profile" :profile="userStore.profile" @saved="onSaved" />
          </div>
          <div class="app-card">
            <h3>我的口味雷达</h3>
            <div ref="chartRef" class="radar-chart" />
          </div>
        </div>
      </el-tab-pane>

      <!-- AI 设置 -->
      <el-tab-pane label="AI 设置" name="ai-config">
        <div class="app-card ai-config-card">
          <h3>默认模型与强度</h3>
          <el-form label-width="90px">
            <el-form-item label="默认模型">
              <el-select v-model="aiModel" style="width: 300px">
                <el-option v-for="opt in aiConfigStore.modelOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <span class="ai-tip">格式：接入名::模型（自定义接入在下方配置）</span>
            </el-form-item>
            <el-form-item label="默认强度">
              <el-select v-model="aiStrength" style="width: 160px">
                <el-option label="快速" value="fast" />
                <el-option label="均衡" value="balanced" />
                <el-option label="深度" value="deep" />
              </el-select>
            </el-form-item>
            <el-form-item label="每日用量上限">
              <el-input-number v-model="aiLimit" :min="0" :max="100000000" :step="10000" style="width: 180px" />
              <span class="ai-tip">0 = 不限制；超出后聊天页将阻止发送并提醒（§10 可选扩展 5）</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveAiConfig">保存配置</el-button>
              <span class="ai-tip">聊天页输入区上方仍可临时切换；此处为全局默认</span>
            </el-form-item>
          </el-form>

          <el-divider />
          <h3>自定义 DeepSeek API Key（BYOK）</h3>
          <p class="byok-tip">
            配置后对话使用<b>你自己的 Key</b>（密钥仅加密存于后端，前端不保存明文）；未配置则使用系统默认 Key。
          </p>
          <div class="byok-row">
            <el-input
              v-model="customKeyInput"
              type="password"
              show-password
              placeholder="sk-...（仅提交一次，不会回显）"
              style="width: 360px"
              @keyup.enter="saveCustomKey"
            />
            <el-button type="primary" :loading="keySaving" @click="saveCustomKey">保存 Key</el-button>
          </div>
          <div class="byok-status">
            <el-tag :type="hasCustomKey ? 'success' : 'info'" size="small">
              {{ hasCustomKey ? '已使用自定义 Key' : '使用系统默认 Key' }}
            </el-tag>
            <el-button v-if="hasCustomKey" size="small" text type="danger" @click="clearCustomKey">清除并回退系统 Key</el-button>
          </div>

          <el-divider />
          <div class="provider-head">
            <h3>自定义接入（多 Provider）</h3>
            <el-button type="primary" size="small" @click="openAddProvider">新增接入</el-button>
          </div>
          <p class="byok-tip">
            支持 OpenAI 兼容接口与 Anthropic；配置后可在聊天页模型下拉选择「接入名::模型」。Key 加密存于后端，不在此回显。
          </p>
          <div v-if="providerList.length" v-loading="providerSaving" class="provider-list">
            <div v-for="p in providerList" :key="p.name" class="provider-item">
              <div class="provider-info">
                <div class="provider-name">
                  <b>{{ p.name }}</b>
                  <el-tag :type="p.provider_type === 'anthropic' ? 'warning' : 'success'" size="small">
                    {{ p.provider_type === 'anthropic' ? 'Anthropic' : 'OpenAI 兼容' }}
                  </el-tag>
                  <el-tag :type="p.has_key ? 'info' : 'danger'" size="small" effect="plain">
                    {{ p.has_key ? '已配置 Key' : '无 Key' }}
                  </el-tag>
                </div>
                <div class="provider-url">{{ p.base_url }}</div>
                <div class="provider-models">
                  <el-tag v-for="m in p.models" :key="m" size="small" effect="plain" class="model-tag">{{ m }}</el-tag>
                </div>
              </div>
              <div class="provider-ops">
                <el-button size="small" text type="primary" @click="openEditProvider(p)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeProvider(p)">删除</el-button>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无自定义接入，点击「新增接入」添加" :image-size="60" />

          <el-dialog
            v-model="providerDialog"
            :title="editingProviderName ? `编辑接入：${editingProviderName}` : '新增接入'"
            width="480px"
            append-to-body
          >
            <el-form label-width="90px">
              <el-form-item label="接入名称" required>
                <el-input v-model="providerForm.name" placeholder="如：硅基流动 / Kimi / 我的 Claude" maxlength="30" />
              </el-form-item>
              <el-form-item label="接口类型" required>
                <el-radio-group v-model="providerForm.provider_type">
                  <el-radio value="openai">OpenAI 兼容（/v1/chat/completions）</el-radio>
                  <el-radio value="anthropic">Anthropic（/v1/messages）</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="Base URL" required>
                <el-input v-model="providerForm.base_url" placeholder="如：https://api.siliconflow.cn/v1" />
              </el-form-item>
              <el-form-item label="API Key" :required="!editingProviderName">
                <el-input
                  v-model="providerForm.api_key"
                  type="password"
                  show-password
                  :placeholder="editingProviderName ? '留空则保留原 Key' : 'sk-...（仅提交一次，不会回显）'"
                />
              </el-form-item>
              <el-form-item label="模型列表" required>
                <el-input
                  v-model="providerForm.modelsText"
                  placeholder="逗号分隔，如：Qwen/Qwen2.5-7B-Instruct, deepseek-chat"
                />
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="providerDialog = false">取消</el-button>
              <el-button type="primary" :loading="providerSaving" @click="saveProvider">保存</el-button>
            </template>
          </el-dialog>
        </div>
      </el-tab-pane>

      <!-- API 用量 -->
      <el-tab-pane label="API 用量" name="usage">
        <div v-loading="usageLoading" class="usage-wrap">
          <div v-if="aiConfigStore.budgetEnabled" class="app-card budget-bar">
            <div class="budget-head">
              <span class="budget-label">今日用量 / 上限</span>
              <span class="budget-val">
                {{ fmtTokens(aiConfigStore.todayTokens) }} / {{ fmtTokens(aiConfigStore.config.dailyTokenLimit) }} tokens
              </span>
            </div>
            <el-progress
              :percentage="Math.min(Math.round((aiConfigStore.todayTokens / aiConfigStore.config.dailyTokenLimit) * 100), 100)"
              :status="aiConfigStore.budgetExceeded ? 'exception' : 'success'"
            />
          </div>

          <div class="stat-cards">
            <div class="stat-card app-card">
              <span class="stat-label">今日</span>
              <span class="stat-value">{{ fmtTokens((usage?.today.prompt_tokens ?? 0) + (usage?.today.completion_tokens ?? 0)) }}</span>
              <span class="stat-unit">tokens</span>
            </div>
            <div class="stat-card app-card">
              <span class="stat-label">近 7 天</span>
              <span class="stat-value">{{ fmtTokens((usage?.week_total.prompt_tokens ?? 0) + (usage?.week_total.completion_tokens ?? 0)) }}</span>
              <span class="stat-unit">tokens</span>
            </div>
            <div class="stat-card app-card">
              <span class="stat-label">累计</span>
              <span class="stat-value">{{ fmtTokens((usage?.total.prompt_tokens ?? 0) + (usage?.total.completion_tokens ?? 0)) }}</span>
              <span class="stat-unit">tokens</span>
            </div>
          </div>

          <div class="app-card">
            <h3>近 7 天趋势</h3>
            <div ref="usageChartRef" class="usage-chart" />
          </div>

          <div class="usage-tables">
            <div class="app-card">
              <h3>按模型</h3>
              <el-table :data="usage?.by_model ?? []" size="small">
                <el-table-column prop="model" label="模型" />
                <el-table-column prop="prompt_tokens" label="输入 tokens" />
                <el-table-column prop="completion_tokens" label="输出 tokens" />
              </el-table>
            </div>
            <div class="app-card">
              <h3>按节点</h3>
              <el-table :data="usage?.by_node ?? []" size="small">
                <el-table-column prop="node" label="节点" />
                <el-table-column prop="prompt_tokens" label="输入 tokens" />
                <el-table-column prop="completion_tokens" label="输出 tokens" />
              </el-table>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 我的收藏 -->
      <el-tab-pane label="我的收藏" name="favorites">
        <div class="grid">
          <div v-for="f in favorites" :key="f.dish_id" class="fav-item">
            <DishCard :dish="f" />
            <el-button size="small" text type="danger" class="unfav" @click="removeFav(f.dish_id)">取消收藏</el-button>
          </div>
        </div>
        <el-empty v-if="favorites.length === 0" description="还没有收藏的菜谱" />
      </el-tab-pane>

      <!-- 行为历史 -->
      <el-tab-pane label="行为历史" name="history">
        <el-table :data="history" size="small">
          <el-table-column prop="dish_id" label="菜谱" />
          <el-table-column prop="action" label="行为" width="100" />
          <el-table-column prop="created_at" label="时间" width="200" />
        </el-table>
        <el-empty v-if="history.length === 0" description="暂无行为记录" />
      </el-tab-pane>

      <!-- 历史会话（按分组展示 + 行内移动分组，§16 决策 17） -->
      <el-tab-pane label="历史会话" name="sessions">
        <div v-for="g in sessionGroups" :key="g.key" class="session-group-block">
          <div class="session-group-title">{{ g.name }}（{{ g.items.length }}）</div>
          <el-table :data="g.items" size="small" @row-click="(row: ChatSessionInfo) => openSession(row.id)">
            <el-table-column prop="title" label="标题" min-width="180" />
            <el-table-column prop="message_count" label="消息数" width="80" />
            <el-table-column prop="last_message" label="最后消息" min-width="200" show-overflow-tooltip />
            <el-table-column prop="created_at" label="创建时间" width="170" />
            <el-table-column label="分组" width="150">
              <template #default="{ row }">
                <el-select
                  :model-value="(row as ChatSessionInfo).group ?? ''"
                  size="small"
                  class="move-group-select"
                  @click.stop
                  @change="(v: string) => onMoveSession(row as ChatSessionInfo, v)"
                >
                  <el-option label="默认分组" value="" />
                  <el-option v-for="gn in profileGroupNames" :key="gn" :label="gn" :value="gn" />
                  <el-option label="+ 新建分组…" value="__new__" />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-empty v-if="sessions.length === 0" description="暂无会话" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.profile-grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 16px;
}

@media (max-width: 860px) {
  .profile-grid {
    grid-template-columns: 1fr;
  }
}

.radar-chart {
  height: 260px;
}

.ai-config-card {
  max-width: 560px;
}

.ai-tip {
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}

.byok-tip {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0 12px;
}

.byok-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.byok-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.stat-cards {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.budget-bar {
  margin-bottom: 14px;
}

.budget-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.budget-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.budget-val {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
}

.stat-card {
  flex: 1;
  min-width: 150px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-strong);
}

.stat-unit {
  font-size: 12px;
  color: var(--text-secondary);
}

.usage-chart {
  height: 220px;
}

.usage-tables {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}

@media (max-width: 860px) {
  .usage-tables {
    grid-template-columns: 1fr;
  }
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.fav-item {
  position: relative;
}

.unfav {
  margin-top: 6px;
}

/* ── 多 Provider 管理（§10） ── */
.provider-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.provider-head h3 {
  margin: 0;
}

.provider-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.provider-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-secondary);
}

.provider-info {
  min-width: 0;
}

.provider-name {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.provider-url {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  word-break: break-all;
}

.provider-models {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-tag {
  margin-right: 0;
}

.provider-ops {
  flex-shrink: 0;
}

/* ── 历史会话分组（§16 决策 17） ── */
.session-group-block {
  margin-bottom: 16px;
}

.session-group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 4px 0 8px;
  padding-left: 8px;
  border-left: 3px solid var(--accent);
}

.move-group-select {
  width: 130px;
}
</style>
