<script setup lang="ts">
/** 口味标签（§10 组件）：辣/甜/酸/咸鲜/清淡 等，Solarized 语义色。 */
import { computed } from 'vue'

const props = defineProps<{ flavors: string[]; limit?: number }>()

const shown = computed(() => props.flavors.slice(0, props.limit ?? 6))
</script>

<template>
  <div class="flavor-tags">
    <span v-for="f in shown" :key="f" class="flavor-tag">{{ f }}</span>
  </div>
</template>

<style scoped>
.flavor-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.flavor-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-hover);
  color: var(--text-primary);
  border: 1px solid var(--border);
}
</style>
