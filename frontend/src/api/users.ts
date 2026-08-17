/**
 * 用户画像 API（§8.1 问卷字段）。
 */
import { http, unwrap } from './http'

export interface Profile {
  flavor_spicy: number
  flavor_sweet: number
  flavor_sour: number
  flavor_light: number
  avoid_list: string[]
  diet_type: string
  skill_level: string
  tools: string[]
  family_size: number
  budget_level: string
  goal: string
}

export async function apiGetProfile(): Promise<Profile> {
  return unwrap(await http.get('/users/me/profile'))
}

export async function apiUpdateProfile(data: Partial<Profile>): Promise<Profile> {
  return unwrap(await http.put('/users/me/profile', data))
}

/** AI 用量统计（§10 Profile AI 配置）：今日/近 7 天/累计，按模型与节点拆分 */
export interface UsageStats {
  today: { prompt_tokens: number; completion_tokens: number }
  week_total: { prompt_tokens: number; completion_tokens: number }
  total: { prompt_tokens: number; completion_tokens: number }
  by_day: { date: string; tokens: number }[]
  by_model: { model: string; prompt_tokens: number; completion_tokens: number }[]
  by_node: { node: string; prompt_tokens: number; completion_tokens: number }[]
}

export async function apiUsage(): Promise<UsageStats> {
  return unwrap(await http.get('/users/me/usage'))
}

/** BYOK（§10）：用户自定义 DeepSeek API Key（明文只提交一次，读取仅返回 has_custom_key） */
export async function apiGetAiKey(): Promise<{ has_custom_key: boolean }> {
  return unwrap(await http.get('/users/me/ai-key'))
}

export async function apiSetAiKey(apiKey: string): Promise<{ has_custom_key: boolean }> {
  return unwrap(await http.put('/users/me/ai-key', { api_key: apiKey }))
}

export async function apiDeleteAiKey(): Promise<{ has_custom_key: boolean }> {
  return unwrap(await http.delete('/users/me/ai-key'))
}

/** 多 Provider（§10）：OpenAI 兼容 / Anthropic 自定义接入（key 加密存后端，回显脱敏） */
export interface AiProvider {
  name: string
  provider_type: 'openai' | 'anthropic'
  base_url: string
  has_key?: boolean
  models: string[]
  /** 仅提交时使用：新 Key（明文只传一次）；编辑时留空 = 保留原 Key */
  api_key?: string
}

export async function apiGetAiProviders(): Promise<AiProvider[]> {
  const resp = await http.get('/users/me/ai-providers')
  return (unwrap<{ providers: AiProvider[] }>(resp)).providers ?? []
}

export async function apiSetAiProviders(providers: AiProvider[]): Promise<AiProvider[]> {
  const resp = await http.put('/users/me/ai-providers', { providers })
  return (unwrap<{ providers: AiProvider[] }>(resp)).providers ?? []
}

export interface MeInfo {
  id: number
  username: string
  role: string
}

/** 当前用户信息（§9.2：token 平铺返回，user 信息单独获取） */
export async function apiMe(): Promise<MeInfo> {
  return unwrap(await http.get('/users/me'))
}
