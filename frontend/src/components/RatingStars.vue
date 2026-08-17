<script setup lang="ts">
/** 评分星星（§10 组件）：1~5 星，支持只读与交互（§8.2 rating 行为）。 */
import { computed, ref, watch } from 'vue'
import { Star, StarFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: number
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: number] }>()

const hover = ref(0)
const shown = computed(() => hover.value || props.modelValue)

watch(
  () => props.modelValue,
  (v) => {
    hover.value = 0
    void v
  },
)

function onPick(n: number) {
  if (props.readonly) return
  emit('update:modelValue', n)
}
</script>

<template>
  <div class="rating" @mouseleave="hover = 0">
    <span
      v-for="n in 5"
      :key="n"
      class="star"
      :class="{ on: n <= shown }"
      @mouseenter="hover = n"
      @click="onPick(n)"
    >
      <el-icon><StarFilled v-if="n <= shown" /><Star v-else /></el-icon>
    </span>
  </div>
</template>

<style scoped>
.rating {
  display: inline-flex;
  gap: 2px;
}

.star {
  cursor: pointer;
  color: var(--text-secondary);
}

.star.on {
  color: var(--warning);
}
</style>
