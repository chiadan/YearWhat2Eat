<script setup lang="ts">
/** 菜谱浏览（§10）：分类 Tab + 难度/口味筛选 + 搜索 + 分页卡片。 */
import { onMounted, ref, watch } from 'vue'
import { apiDishList, type DishSummary } from '@/api/dishes'
import DishCard from '@/components/DishCard.vue'

const categories = [
  { label: '全部', value: '' },
  { label: '素菜', value: 'vegetable_dish' },
  { label: '荤菜', value: 'meat_dish' },
  { label: '水产', value: 'aquatic' },
  { label: '早餐', value: 'breakfast' },
  { label: '主食', value: 'staple' },
  { label: '半成品', value: 'semi-finished' },
  { label: '汤粥', value: 'soup' },
  { label: '饮料', value: 'drink' },
  { label: '酱料', value: 'condiment' },
  { label: '甜品', value: 'dessert' },
]

const category = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = 24
const total = ref(0)
const dishes = ref<DishSummary[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const resp = await apiDishList({
      category: category.value || undefined,
      keyword: keyword.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    const data = resp as { items?: DishSummary[]; total?: number } | DishSummary[]
    if (Array.isArray(data)) {
      dishes.value = data
      total.value = data.length
    } else {
      dishes.value = data.items ?? []
      total.value = data.total ?? 0
    }
  } finally {
    loading.value = false
  }
}

watch([category, keyword], () => {
  page.value = 1
  void load()
})
watch(page, () => void load())

onMounted(() => void load())
</script>

<template>
  <div class="dish-list-view">
    <div class="toolbar">
      <el-radio-group v-model="category" class="cats">
        <el-radio-button v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</el-radio-button>
      </el-radio-group>
      <el-input v-model="keyword" placeholder="搜索菜名 / 食材" clearable style="width: 220px" />
    </div>

    <div v-loading="loading" class="grid">
      <DishCard v-for="d in dishes" :key="d.dish_id" :dish="d" />
    </div>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      class="pager"
    />
    <el-empty v-if="!loading && dishes.length === 0" description="没有符合条件的菜谱" />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}

.cats {
  flex-wrap: wrap;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 14px;
  min-height: 120px;
}

.pager {
  margin-top: 16px;
  justify-content: center;
}
</style>
