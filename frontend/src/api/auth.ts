/**
 * 认证 API（§9 认证段）：注册/登录/游客/刷新/转正。
 * 后端返回平铺 tokens：{access_token, refresh_token, token_type}（§9.2）；
 * user 信息由 GET /users/me 获取（stores/user.ts fetchMe）。
 */
import { http, unwrap } from './http'

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

export async function apiRegister(username: string, password: string): Promise<AuthTokens> {
  return unwrap(await http.post('/auth/register', { username, password }))
}

export async function apiLogin(username: string, password: string): Promise<AuthTokens> {
  return unwrap(await http.post('/auth/login', { username, password }))
}

export async function apiGuest(): Promise<AuthTokens> {
  return unwrap(await http.post('/auth/guest'))
}

/** 刷新 token（§9.2）：带 X-Refresh 标记——其 401 由拦截器直接放行，不触发续期递归 */
export async function apiRefresh(refreshToken: string): Promise<AuthTokens> {
  return unwrap(
    await http.post('/auth/refresh', { refresh_token: refreshToken }, { headers: { 'X-Refresh': '1' } }),
  )
}

/** 游客转正（§9.2 upgrade）：guest_token = 当前游客 access token */
export async function apiUpgrade(
  guestToken: string,
  username: string,
  password: string,
): Promise<AuthTokens> {
  return unwrap(await http.post('/auth/upgrade', { guest_token: guestToken, username, password }))
}
