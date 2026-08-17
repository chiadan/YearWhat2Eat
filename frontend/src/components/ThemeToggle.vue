<script setup lang="ts">
/** 主题选择器（§10.1 多主题）：5 套主流主题下拉，带色点预览。 */
import { useThemeStore, type ThemeName } from '@/stores/theme'

const store = useThemeStore()

function onChange(name: string) {
  store.setTheme(name as ThemeName)
}
</script>

<template>
  <el-select
    :model-value="store.theme"
    size="small"
    class="theme-select"
    @change="onChange"
  >
    <el-option v-for="opt in store.options" :key="opt.name" :label="opt.label" :value="opt.name">
      <div class="opt-item">
        <span class="color-dot" :style="{ background: opt.color }" />
        <span>{{ opt.label }}</span>
      </div>
    </el-option>
  </el-select>
</template>

<style scoped>
.theme-select {
  width: 132px;
}

.opt-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.color-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--border);
  flex-shrink: 0;
}
</style>
