<script setup lang="ts">
/**
 * 应用外壳（§10）：Header（展示名 VITE_APP_NAME / 主题切换 / 用户菜单）+ 路由出口。
 */
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import ThemeToggle from '@/components/ThemeToggle.vue'

const appName = import.meta.env.VITE_APP_NAME || '是啊吃什么'
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 刷新页面后 access token 在内存中丢失：有登录态但无 token 时静默续期（§9.2）
onMounted(() => {
  if (userStore.user && !userStore.accessToken) {
    void userStore.tryRefresh()
  }
})

const navItems = [
  { name: 'home', label: '推荐' },
  { name: 'chat', label: '聊天' },
  { name: 'dishes', label: '菜谱' },
]

const displayName = computed(() => {
  if (!userStore.user) return '未登录'
  return userStore.user.is_guest ? `游客#${userStore.user.id}` : userStore.user.username
})

async function handleLogout() {
  await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' }).catch(() => null)
  userStore.logout()
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="header-inner">
        <router-link :to="{ name: 'home' }" class="brand">
          <span class="brand-logo">吃</span>
          <span class="brand-name">{{ appName }}</span>
        </router-link>

        <nav class="nav">
          <router-link
            v-for="item in navItems"
            :key="item.name"
            :to="{ name: item.name }"
            class="nav-link"
            :class="{ active: route.name === item.name }"
          >
            {{ item.label }}
          </router-link>
        </nav>

        <div class="header-actions">
          <ThemeToggle />
          <template v-if="userStore.isLoggedIn">
            <router-link :to="{ name: 'profile' }" class="user-chip">{{ displayName }}</router-link>
            <el-button link type="primary" @click="handleLogout">退出</el-button>
          </template>
          <template v-else>
            <router-link :to="{ name: 'login' }">
              <el-button type="primary" size="small">登录 / 注册</el-button>
            </router-link>
          </template>
        </div>
      </div>
    </header>

    <main class="page-container" :class="{ 'page-wide': route.name === 'chat' }">
      <router-view />
    </main>

    <footer v-if="route.name !== 'chat'" class="app-footer">
      {{ appName }} · 千人千面菜谱推荐 · 数据源 HowToCook
    </footer>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background-color: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}

.header-inner {
  width: 100%;
  max-width: min(76%, 1700px);
  margin: 0 auto;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 24px;
}

@media (max-width: 1280px) {
  .header-inner {
    max-width: 100%;
  }
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
}

.brand-logo {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: var(--accent);
  color: var(--bg-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.nav {
  display: flex;
  gap: 4px;
  flex: 1;
}

.nav-link {
  padding: 6px 12px;
  border-radius: 6px;
  color: var(--text-primary);
  text-decoration: none;
  font-size: 15px;
}

.nav-link:hover {
  background: var(--bg-hover);
  text-decoration: none;
}

.nav-link.active {
  color: var(--accent);
  font-weight: 600;
  background: var(--bg-hover);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-chip {
  color: var(--text-primary);
  text-decoration: none;
  font-size: 14px;
}

.user-chip:hover {
  text-decoration: none;
  color: var(--accent);
}

.app-footer {
  margin-top: auto;
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
}
</style>
