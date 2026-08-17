/**
 * 路由（§10 页面）：推荐首页 / 聊天 / 菜谱浏览 / 详情 / 个人中心 / 登录注册。
 * 强制登录（§10 千人千面前置）：除 login/register 外全部页面需登录（游客也是登录态），
 * 未登录访问任意页面跳转登录页（带 redirect 回跳）。
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
    { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue') },
    { path: '/dishes', name: 'dishes', component: () => import('@/views/DishListView.vue') },
    { path: '/dishes/:id', name: 'dish-detail', component: () => import('@/views/DishDetailView.vue') },
    { path: '/profile', name: 'profile', component: () => import('@/views/ProfileView.vue') },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

const PUBLIC_PAGES = new Set(['login', 'register'])

// 全局守卫：强制登录（§10 千人千面前置）——除登录/注册外全部需登录
router.beforeEach((to) => {
  const store = useUserStore()
  if (!PUBLIC_PAGES.has(String(to.name))) {
    if (!store.isLoggedIn) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  } else if (store.isLoggedIn) {
    // 已登录访问登录/注册页 → 回首页
    return { name: 'home' }
  }
  return true
})

export default router
