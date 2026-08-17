<script setup lang="ts">
/**
 * 注册页（§9.2）：游客转正优先（upgrade 合并游客数据，决策 4 ✅），否则普通注册。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const confirm = ref('')
const loading = ref(false)

const isGuestUpgrade = computed(() => userStore.isGuest)

async function onRegister() {
  if (!username.value || !password.value) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  if (password.value !== confirm.value) {
    ElMessage.warning('两次密码不一致')
    return
  }
  loading.value = true
  try {
    if (isGuestUpgrade.value) {
      await userStore.upgrade(username.value, password.value)
      ElMessage.success('注册成功，游客数据已合并进新账号（§9.2 upgrade）')
    } else {
      await userStore.register(username.value, password.value)
      ElMessage.success('注册成功')
    }
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
      <h2 class="title">{{ isGuestUpgrade ? '游客转正' : '注册' }}</h2>
      <el-alert
        v-if="isGuestUpgrade"
        type="info"
        :closable="false"
        class="tip"
        title="当前为游客模式，注册后浏览/收藏/评分等数据将自动合并到新账号"
      />
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="username" placeholder="用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" show-password placeholder="密码" autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="confirm" type="password" show-password placeholder="再次输入密码" autocomplete="new-password" @keyup.enter="onRegister" />
        </el-form-item>
        <el-button type="primary" class="full" :loading="loading" @click="onRegister">
          {{ isGuestUpgrade ? '注册并合并游客数据' : '注册' }}
        </el-button>
      </el-form>
      <div class="foot">
        已有账号？
        <router-link :to="{ name: 'login', query: route.query }">去登录</router-link>
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

.tip {
  margin-bottom: 12px;
}

.full {
  width: 100%;
}

.foot {
  margin-top: 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
