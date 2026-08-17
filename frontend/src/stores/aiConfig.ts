/**
 * AI 配置 store（§10 Profile AI 配置）：默认模型/强度 + 每日用量预算 + 多 Provider。
 * - localStorage 持久化（模型/强度/预算上限）；model 格式 "provider::model"（deepseek::xxx 或 自定义名::xxx）
 * - providers：用户自定义接入配置（OpenAI 兼容 / Anthropic），后端加密存储
 * - todayTokens：今日已用 token（用量页 / 聊天页发送前检查）
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { apiGetAiProviders, apiUsage, type AiProvider } from '@/api/users'

const STORAGE_KEY = 'yeahwhat2eat-ai-config'

export interface AiConfig {
  model: string
  strength: 'fast' | 'balanced' | 'deep'
  /** 每日 token 上限（0 = 不限制，§10 可选扩展 5） */
  dailyTokenLimit: number
}

const DEFAULT_CONFIG: AiConfig = { model: 'deepseek::deepseek-v4-flash', strength: 'balanced', dailyTokenLimit: 0 }

function load(): AiConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<AiConfig>
      const limit = typeof parsed.dailyTokenLimit === 'number' && parsed.dailyTokenLimit > 0
        ? Math.floor(parsed.dailyTokenLimit)
        : 0
      return {
        model: typeof parsed.model === 'string' && parsed.model ? parsed.model : DEFAULT_CONFIG.model,
        strength: parsed.strength === 'fast' || parsed.strength === 'deep' ? parsed.strength : 'balanced',
        dailyTokenLimit: limit,
      }
    }
  } catch {
    /* 损坏配置回默认 */
  }
  return { ...DEFAULT_CONFIG }
}

export function parseModel(value: string): { provider: string; model: string } {
  const idx = value.indexOf('::')
  if (idx > 0) return { provider: value.slice(0, idx), model: value.slice(idx + 2) }
  return { provider: 'deepseek', model: value }
}

export const useAiConfigStore = defineStore('aiConfig', () => {
  const config = ref<AiConfig>(load())
  const providers = ref<AiProvider[]>([])
  const todayTokens = ref(0)

  const budgetEnabled = computed(() => config.value.dailyTokenLimit > 0)
  const remainingTokens = computed(() =>
    budgetEnabled.value ? Math.max(config.value.dailyTokenLimit - todayTokens.value, 0) : Infinity,
  )
  const budgetExceeded = computed(() => budgetEnabled.value && todayTokens.value >= config.value.dailyTokenLimit)

  /** 模型下拉选项：DeepSeek 预置 + 自定义 Provider 的全部模型（§10 多 Provider） */
  const modelOptions = computed(() => {
    const options: { label: string; value: string }[] = [
      { label: 'DeepSeek · deepseek-v4-flash', value: 'deepseek::deepseek-v4-flash' },
      { label: 'DeepSeek · deepseek-chat', value: 'deepseek::deepseek-chat' },
    ]
    for (const p of providers.value) {
      for (const m of p.models) {
        options.push({ label: `${p.name} · ${m}`, value: `${p.name}::${m}` })
      }
    }
    return options
  })

  function setConfig(next: Partial<AiConfig>) {
    config.value = { ...config.value, ...next }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config.value))
  }

  /** 拉取自定义 Provider 列表（§10） */
  async function fetchProviders() {
    try {
      providers.value = await apiGetAiProviders()
    } catch {
      /* 静默 */
    }
  }

  /** 拉取今日用量（Profile 用量页 / 聊天页进入时调用） */
  async function fetchToday() {
    try {
      const usage = await apiUsage()
      todayTokens.value = usage.today.prompt_tokens + usage.today.completion_tokens
    } catch {
      /* 静默 */
    }
  }

  return {
    config,
    providers,
    todayTokens,
    budgetEnabled,
    remainingTokens,
    budgetExceeded,
    modelOptions,
    setConfig,
    fetchProviders,
    fetchToday,
  }
})
