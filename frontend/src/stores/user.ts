/**
 * 用户 store（§9.2）：登录/注册/游客/转正/画像。
 * - 后端 token 平铺返回，user 信息经 GET /users/me 获取（is_guest 由 guest_ 前缀判断）
 * - access token 放内存（防 XSS 窃取），refresh 放 localStorage 用于静默续期
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  apiGuest,
  apiLogin,
  apiRefresh,
  apiRegister,
  apiUpgrade,
  type AuthTokens,
} from '@/api/auth'
import { apiMe } from '@/api/users'
import { apiGetProfile, apiUpdateProfile, type Profile } from '@/api/users'

const REFRESH_KEY = 'yeahwhat2eat-refresh'
const USER_KEY = 'yeahwhat2eat-user'

export interface UserInfo {
  id: number
  username: string
  role: string
  is_guest: boolean
}

export const useUserStore = defineStore('user', () => {
  const accessToken = ref<string>('')
  const user = ref<UserInfo | null>(null)

  const isLoggedIn = computed(() => !!user.value)
  const isGuest = computed(() => !!user.value?.is_guest)

  async function fetchMe(): Promise<UserInfo> {
    const info = await apiMe()
    return { ...info, is_guest: info.username.startsWith('guest_') }
  }

  /** 先存 token（fetchMe 需要它携带 Bearer），再拉用户信息——顺序不可颠倒（§9.2） */
  function setTokens(tokens: AuthTokens) {
    accessToken.value = tokens.access_token
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
  }

  function persist(tokens: AuthTokens, info: UserInfo) {
    setTokens(tokens)
    localStorage.setItem(USER_KEY, JSON.stringify(info))
    user.value = info
  }

  async function register(username: string, password: string) {
    const tokens = await apiRegister(username, password)
    setTokens(tokens)
    persist(tokens, await fetchMe())
  }

  async function login(username: string, password: string) {
    const tokens = await apiLogin(username, password)
    setTokens(tokens)
    persist(tokens, await fetchMe())
  }

  /** 游客会话（§16 决策 4 ✅） */
  async function guest() {
    const tokens = await apiGuest()
    setTokens(tokens)
    persist(tokens, await fetchMe())
  }

  /** 游客转正（§9.2 upgrade：guest_token = 当前游客 access token） */
  async function upgrade(username: string, password: string) {
    const tokens = await apiUpgrade(accessToken.value, username, password)
    setTokens(tokens)
    persist(tokens, await fetchMe())
  }

  /** 静默续期：access 过期时用 refresh 换新 */
  async function tryRefresh(): Promise<boolean> {
    const refresh = localStorage.getItem(REFRESH_KEY)
    if (!refresh || !user.value) return false
    try {
      const tokens = await apiRefresh(refresh)
      accessToken.value = tokens.access_token
      localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
      return true
    } catch {
      logout()
      return false
    }
  }

  function logout() {
    accessToken.value = ''
    user.value = null
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
  }

  // 刷新页面后从 localStorage 恢复登录态（access token 需静默续期）
  function restore() {
    const saved = localStorage.getItem(USER_KEY)
    if (saved) {
      try {
        user.value = JSON.parse(saved) as UserInfo
      } catch {
        localStorage.removeItem(USER_KEY)
      }
    }
  }

  restore()

  // 画像
  const profile = ref<Profile | null>(null)

  async function loadProfile() {
    profile.value = await apiGetProfile()
  }

  async function saveProfile(data: Partial<Profile>) {
    profile.value = await apiUpdateProfile(data)
  }

  return {
    accessToken,
    user,
    profile,
    isLoggedIn,
    isGuest,
    register,
    login,
    guest,
    upgrade,
    tryRefresh,
    logout,
    loadProfile,
    saveProfile,
  }
})
