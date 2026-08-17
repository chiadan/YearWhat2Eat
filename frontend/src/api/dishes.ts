/**
 * 菜谱与用户 API（§9）：列表/详情/相关/反馈/收藏/历史/画像/购物清单导出。
 */
import { http, unwrap } from './http'
import type { Profile } from './users'

export interface DishSummary {
  dish_id: string
  name: string
  category: string
  difficulty: number | null
  time_est: number | null
  meat_attr?: string
  cuisines?: string[]
  flavors?: string[]
  techniques?: string[]
  match_score?: number
  /** 成品图相对路径（/static/dishes/{image} 访问，§12.5） */
  image?: string | null
}

/** 图片 URL 构造（§12.5 静态托管） */
export function dishImageUrl(image?: string | null): string {
  if (!image) return ''
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const origin = base.startsWith('http') ? new URL(base).origin : window.location.origin
  return `${origin}/static/dishes/${image}`
}

export interface DishListQuery {
  category?: string
  difficulty?: number
  flavor?: string
  keyword?: string
  page?: number
  page_size?: number
}

export interface DishDetail extends DishSummary {
  path: string
  intro: string | null
  main_ingredients: string[]
  ingredients?: string[]
  optional_ingredients?: string[]
  calculation?: string | null
  steps: { version: string; order: number; text: string }[]
  notes?: string | null
  images?: string[]
}

export async function apiDishList(params: DishListQuery) {
  return unwrap(await http.get('/dishes', { params }))
}

/** 热门菜谱（§8.3 热度公式，首页"大家喜欢"流） */
export async function apiDishHot(limit = 12): Promise<DishSummary[]> {
  return unwrap(await http.get('/dishes/hot', { params: { limit } }))
}

export async function apiDishDetail(dishId: string): Promise<DishDetail> {
  return unwrap(await http.get(`/dishes/${dishId}`))
}

// ── 全量菜名映射（§10 正文菜名链接化）────────────────────────
// 模块级缓存：一次拉取（357 条轻量数据），跨组件共享
let _dishNamesCache: Record<string, string> | null = null
let _dishNamesLoading: Promise<Record<string, string>> | null = null

/** 全量 菜名 -> dish_id（用于回答正文任意菜名可点击，§10 需求 3） */
export async function apiDishNameMap(): Promise<Record<string, string>> {
  if (_dishNamesCache) return _dishNamesCache
  if (!_dishNamesLoading) {
    _dishNamesLoading = (async () => {
      const resp = await http.get('/dishes/names')
      const data = unwrap<{ items?: { name: string; dish_id: string }[] }>(resp)
      const map: Record<string, string> = {}
      for (const it of data.items ?? []) {
        if (it.name && !map[it.name]) map[it.name] = it.dish_id
      }
      _dishNamesCache = map
      return map
    })()
  }
  return _dishNamesLoading
}

export async function apiDishRelated(dishId: string): Promise<DishSummary[]> {
  return unwrap(await http.get(`/dishes/${dishId}/related`))
}

export interface FeedbackBody {
  dish_id: string
  action: 'view' | 'like' | 'dislike' | 'rating' | 'made'
  rating?: number
}

export async function apiFeedback(body: FeedbackBody) {
  return unwrap(await http.post('/users/me/feedback', body))
}

export async function apiFavorites() {
  return unwrap(await http.get('/users/me/favorites'))
}

export async function apiAddFavorite(dishId: string) {
  return unwrap(await http.post(`/users/me/favorites/${dishId}`))
}

export async function apiRemoveFavorite(dishId: string) {
  return unwrap(await http.delete(`/users/me/favorites/${dishId}`))
}

export async function apiHistory() {
  return unwrap(await http.get('/users/me/history'))
}

/** 购物清单导出（§9.4，文件流）：返回 Blob，前端触发下载 */
export async function apiExportShoppingList(dishIds: string[], people: number): Promise<Blob> {
  const resp = await http.post(
    '/shopping-list/export',
    { dish_ids: dishIds, people },
    { responseType: 'blob' },
  )
  return resp.data as Blob
}

export type { Profile }
export { apiGetProfile, apiUpdateProfile } from './users'
