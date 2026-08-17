/**
 * axios 实例（§7.2 前端 HTTP）：统一 baseURL、JWT 注入、401 静默续期。
 * 响应格式遵循 §9.5：{code, message, data}。
 *
 * 401 续期防递归（修复"重启后 refresh 401 无限循环"）：
 *  - refresh 请求带 X-Refresh 标记：其 401 直接 reject，不再触发拦截器递归
 *  - 刷新互斥单例：并发多个 401 只发起一次 refresh，其余等待同一 Promise
 *  - 刷新失败：清空登录态并整页跳转登录页（避免停留在"伪登录态"反复请求）
 */
import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
})

/** 请求级扩展：标记 refresh 请求（拦截器跳过续期逻辑） */
declare module 'axios' {
  interface InternalAxiosRequestConfig {
    _isRefresh?: boolean
  }
}

// 请求拦截：注入 Bearer token；标记 refresh 请求（防续期递归）
http.interceptors.request.use((config) => {
  const store = useUserStore()
  if (store.accessToken) {
    config.headers.Authorization = `Bearer ${store.accessToken}`
  }
  if (config.headers['X-Refresh'] === '1') {
    config._isRefresh = true
  }
  return config
})

/** 正在进行的刷新（互斥单例：并发 401 共享一次刷新，§9.2） */
let refreshPromise: Promise<boolean> | null = null

/** 登录态失效：清空并整页跳转（避免循环依赖 router；redirect 回跳） */
function forceLogout() {
  const store = useUserStore()
  store.logout()
  const redirect = encodeURIComponent(window.location.pathname + window.location.search)
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = `/login?redirect=${redirect}`
  }
}

// 响应拦截：401 尝试静默续期一次；错误统一提示
http.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError<{ code?: string; message?: string }>) => {
    const store = useUserStore()
    const status = error.response?.status
    const msg = error.response?.data?.message || error.message

    // refresh 请求本身失败（401/500 等）：直接失败，绝不递归续期（§9.2 防死循环）
    const isRefreshReq = (error.config as InternalAxiosRequestConfig | undefined)?._isRefresh
    if (isRefreshReq) {
      return Promise.reject(error)
    }

    if (status === 401 && store.isLoggedIn) {
      // 互斥：并发 401 共享一次刷新
      if (!refreshPromise) {
        refreshPromise = store.tryRefresh().finally(() => {
          refreshPromise = null
        })
      }
      const ok = await refreshPromise
      if (ok && error.config) {
        // 续期成功后重放原请求
        error.config.headers.Authorization = `Bearer ${store.accessToken}`
        return http.request(error.config)
      }
      // 刷新失败：登录态已失效，清理并跳登录（避免反复 401）
      forceLogout()
      return Promise.reject(error)
    }

    // 静默：用户主动取消不提示
    if (!axios.isCancel(error) && status !== 401) {
      ElMessage.error(msg || '请求失败')
    }
    return Promise.reject(error)
  },
)

/**
 * 解包响应：兼容两种形态
 * - §9.5 规范：{code, message, data}（code===0 成功）
 * - 当前后端裸对象：直接返回（如 {id, username, items, total}）
 */
export function unwrap<T>(resp: { data: unknown }): T {
  const d = resp.data as { code?: number; message?: string; data?: T } | null
  if (d && typeof d === 'object' && d.code !== undefined) {
    if (d.code !== 0) {
      throw new Error(d.message || '接口错误')
    }
    return d.data as T
  }
  return d as unknown as T
}
