<script setup lang="ts">
/**
 * 今日菜单卡片（§10 组件）：荤素分组展示，菜名可点击跳转详情（需求 3）+ 导出购物清单（§9.4）。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import type { MenuPlan } from '@/api/chat'
import { apiExportShoppingList } from '@/api/dishes'

const props = defineProps<{ plan: MenuPlan }>()

const exporting = ref(false)

// computed：plan prop 流式更新/换一批时实时刷新（此前顶层 const 只取一次，导致菜单空白或旧数据）
const groups = computed(() => [
  { key: '荤菜', items: props.plan.meat ?? [] },
  { key: '素菜', items: props.plan.veg ?? [] },
  { key: '汤/主食', items: props.plan.soup ?? [] },
])

async function onExport() {
  const all = [...(props.plan.meat ?? []), ...(props.plan.veg ?? []), ...(props.plan.soup ?? [])]
  if (all.length === 0) return
  exporting.value = true
  try {
    const people = props.plan.ratio?.people ?? 2
    const blob = await apiExportShoppingList(
      all.map((d) => d.dish_id),
      people,
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const today = new Date().toISOString().slice(0, 10)
    a.href = url
    a.download = `shopping-list-${today}.md`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('购物清单已导出')
  } catch {
    ElMessage.error('导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="menu-card app-card">
    <div class="menu-head">
      <span class="menu-title">今日菜单</span>
      <span v-if="plan.ratio" class="menu-ratio">
        {{ plan.ratio.people }} 人 · 荤 {{ plan.ratio.meat }} · 素 {{ plan.ratio.veg }}
      </span>
      <el-button size="small" :loading="exporting" @click="onExport">
        <el-icon><Download /></el-icon>导出购物清单
      </el-button>
    </div>

    <div v-for="g in groups" :key="g.key" v-show="g.items.length" class="menu-group">
      <span class="group-key">{{ g.key }}</span>
      <span class="group-val">
        <router-link
          v-for="d in g.items"
          :key="d.dish_id"
          :to="{ name: 'dish-detail', params: { id: d.dish_id } }"
          class="dish-link"
        >
          {{ d.name }}
        </router-link>
      </span>
    </div>

    <p v-if="plan.reason" class="menu-reason">{{ plan.reason }}</p>
  </div>
</template>

<style scoped>
.menu-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.menu-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
}

.menu-ratio {
  font-size: 13px;
  color: var(--text-secondary);
  flex: 1;
}

.menu-group {
  display: flex;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
}

.group-key {
  min-width: 56px;
  font-weight: 600;
  color: var(--accent);
  flex-shrink: 0;
}

.group-val {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--text-primary);
}

.dish-link {
  color: var(--text-primary);
  text-decoration: none;
  border-bottom: 1px dashed var(--border);
  transition: color 0.15s ease;
}

.dish-link:hover {
  color: var(--accent);
  border-bottom-color: var(--accent);
  text-decoration: none;
}

.menu-reason {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}
</style>
