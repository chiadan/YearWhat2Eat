<script setup lang="ts">
/**
 * 登录页（§9.2）：用户名密码 + 游客模式（决策 4 ✅）；登录后按 redirect 跳转。
 */
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const appName = import.meta.env.VITE_APP_NAME || '是啊吃什么'

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await userStore.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push(String(route.query.redirect || '/'))
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function onGuest() {
  loading.value = true
  try {
    await userStore.guest()
    ElMessage.success('已进入游客模式')
    router.push(String(route.query.redirect || '/'))
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-wrap">
    <el-card class="auth-card">
      <h2 class="title">登录 {{ appName }}</h2>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="username" placeholder="用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" show-password placeholder="密码" autocomplete="current-password" @keyup.enter="onLogin" />
        </el-form-item>
        <el-button type="primary" class="full" :loading="loading" @click="onLogin">登录</el-button>
        <el-button class="full" :loading="loading" @click="onGuest">游客逛逛（数据可随时转正）</el-button>
      </el-form>
      <div class="foot">
        还没有账号？
        <router-link :to="{ name: 'register', query: route.query }">去注册</router-link>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.auth-wrap {
  display: flex;
  justify-content: center;
  padding-top: 48px;
}

.auth-card {
  width: 360px;
}

.title {
  margin: 0 0 16px;
  color: var(--text-primary);
}

.full {
  width: 100%;
  margin-bottom: 10px;
}

.foot {
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
