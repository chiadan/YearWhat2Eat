<script setup lang="ts">
/**
 * 引用来源卡片（§9.1 sources 帧）：竖排列表式，点击整行跳菜谱详情。
 * - 头行：参考菜谱 + 篇数（white-space: nowrap 杜绝中文折行）
 * - 列表项：编号角标（与正文 [n] 对应）+ 菜名单行省略 + 右侧箭头（hover 右移，明确可点击暗示）
 * - hover：accent 边框 + 背景提亮 + 箭头位移，整行可点（router-link）
 */
import { Right } from '@element-plus/icons-vue'
import type { SourceRef } from '@/api/chat'

defineProps<{ items: SourceRef[] }>()
</script>

<template>
  <div v-if="items.length" class="source-card">
    <div class="source-head">
      <span class="source-label">参考菜谱</span>
      <span class="source-count">{{ items.length }} 篇</span>
    </div>
    <div class="source-list">
      <router-link
        v-for="(s, i) in items"
        :key="s.dish_id"
        :to="{ name: 'dish-detail', params: { id: s.dish_id } }"
        class="source-item"
        :title="s.score != null ? `查看菜谱详情（相关度 ${s.score}）` : '查看菜谱详情'"
      >
        <span class="source-idx">{{ s.ref ?? i + 1 }}</span>
        <span class="source-name">{{ s.name || s.dish_name }}</span>
        <el-icon class="source-arrow"><Right /></el-icon>
      </router-link>
    </div>
  </div>
</template>

<style scoped>
.source-card {
  margin-top: 12px;
  max-width: 420px;
}

/* ── 头行：标题 + 篇数（nowrap 防中文折行） ── */
.source-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
  white-space: nowrap;
}

.source-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.source-count {
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.75;
}

/* ── 列表项：整行可点，左对齐 ── */
.source-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  text-decoration: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.source-item:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, var(--bg-secondary));
  text-decoration: none;
}

/* 编号角标：与正文 [n] 引用对应 */
.source-idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 16%, transparent);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

/* 菜名：单行省略，不换行 */
.source-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 右侧箭头：hover 位移，强化可点击暗示 */
.source-arrow {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--text-secondary);
  opacity: 0.6;
  transition: transform 0.15s ease, color 0.15s ease;
}

.source-item:hover .source-arrow {
  color: var(--accent);
  opacity: 1;
  transform: translateX(2px);
}
</style>
