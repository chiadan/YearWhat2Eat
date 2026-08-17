<script setup lang="ts">
/**
 * 菜谱详情（§10 / 需求 2）：成品图（/static/dishes 托管，§12.5）+ 与数据源一致的完整内容
 * （必备原料 / 可选原料 / 计算定量 / 分版本步骤 / 附加内容）+ 收藏/做过/评分 + 相关菜。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Star, StarFilled, Check } from '@element-plus/icons-vue'
import { apiAddFavorite, apiDishDetail, apiDishRelated, apiFeedback, apiRemoveFavorite, dishImageUrl, type DishDetail } from '@/api/dishes'
import { useUserStore } from '@/stores/user'
import FlavorTags from '@/components/FlavorTags.vue'
import DishCard from '@/components/DishCard.vue'
import RatingStars from '@/components/RatingStars.vue'
import MdRender from '@/components/MdRender.vue'

const route = useRoute()
const userStore = useUserStore()

const dish = ref<DishDetail | null>(null)
const related = ref<{ dish_id: string; name: string; category: string; difficulty: number | null; time_est: number | null }[]>([])
const loading = ref(true)
const favorite = ref(false)
const rating = ref(0)
const made = ref(false)
const activeVersion = ref('default')
const activeImage = ref('')

const versions = computed(() => {
  if (!dish.value) return ['default']
  const set = new Set(dish.value.steps.map((s) => s.version))
  return [...set]
})

const stepsOfVersion = computed(() =>
  (dish.value?.steps ?? []).filter((s) => s.version === activeVersion.value),
)

const allImages = computed(() => dish.value?.images ?? [])

async function load() {
  loading.value = true
  // 每次加载动态读取路由参数（相关菜跳转时 dishId 会变化，§10）
  const currentId = String(route.params.id)
  try {
    dish.value = await apiDishDetail(currentId)
    if (dish.value.image) activeImage.value = dish.value.image
    related.value = await apiDishRelated(currentId)
  } finally {
    loading.value = false
  }
}

// 相关菜跳转：同一路由组件复用，params 变化需重新加载 + 复位滚动（§10 详情页刷新）
watch(
  () => route.params.id,
  () => {
    activeVersion.value = 'default'
    activeImage.value = ''
    window.scrollTo({ top: 0, behavior: 'instant' })
    void load()
  },
)

async function toggleFavorite() {
  if (!userStore.isLoggedIn) {
    ElMessage.warning('请先登录')
    return
  }
  const currentId = String(route.params.id)
  try {
    if (favorite.value) {
      await apiRemoveFavorite(currentId)
      favorite.value = false
    } else {
      await apiAddFavorite(currentId)
      favorite.value = true
    }
    void apiFeedback({ dish_id: currentId, action: favorite.value ? 'like' : 'dislike' }).catch(() => undefined)
  } catch {
    /* 拦截器已提示 */
  }
}

async function onRating(v: number) {
  rating.value = v
  const currentId = String(route.params.id)
  if (userStore.isLoggedIn) {
    await apiFeedback({ dish_id: currentId, action: 'rating', rating: v }).catch(() => undefined)
    ElMessage.success('评分已记录')
  } else {
    ElMessage.warning('请先登录后再评分')
  }
}

async function onMade() {
  made.value = true
  const currentId = String(route.params.id)
  if (userStore.isLoggedIn) {
    await apiFeedback({ dish_id: currentId, action: 'made' }).catch(() => undefined)
    ElMessage.success('打卡成功，已记录"做过"')
  }
}

onMounted(() => void load())
</script>

<template>
  <div v-loading="loading" class="detail-view">
    <template v-if="dish">
      <!-- 头部：封面图 + 基本信息 -->
      <div class="app-card head-card">
        <div v-if="activeImage" class="cover-wrap">
          <img :src="dishImageUrl(activeImage)" :alt="dish.name" class="cover" />
          <div v-if="allImages.length > 1" class="thumbs">
            <img
              v-for="img in allImages"
              :key="img"
              :src="dishImageUrl(img)"
              :class="{ on: img === activeImage }"
              class="thumb"
              @click="activeImage = img"
            />
          </div>
        </div>

        <h1 class="name">{{ dish.name }}</h1>
        <div class="meta">
          <span class="cat">{{ dish.category }}</span>
          <span class="diff">难度 {{ dish.difficulty ? `${dish.difficulty}/5` : '未知' }}</span>
          <span v-if="dish.time_est" class="time">约 {{ dish.time_est }} 分钟</span>
          <FlavorTags :flavors="dish.flavors ?? []" />
        </div>
        <p v-if="dish.intro" class="intro">
          <MdRender :content="dish.intro" />
        </p>

        <div class="actions">
          <el-button :type="favorite ? 'warning' : 'default'" @click="toggleFavorite">
            <el-icon><StarFilled v-if="favorite" /><Star v-else /></el-icon>
            {{ favorite ? '已收藏' : '收藏' }}
          </el-button>
          <el-button :type="made ? 'success' : 'default'" @click="onMade">
            <el-icon><Check /></el-icon>{{ made ? '已做过' : '我做过' }}
          </el-button>
          <span class="rating-label">评分</span>
          <RatingStars :model-value="rating" @update:model-value="onRating" />
        </div>
      </div>

      <!-- 主体：原料 + 做法（与数据源 md 一致，§2.2） -->
      <div class="columns">
        <div class="app-card col-ingredients">
          <h3>必备原料</h3>
          <ul class="ing-list">
            <li v-for="ing in dish.ingredients ?? []" :key="ing" class="ing-item">
              <MdRender :content="ing" />
            </li>
          </ul>
          <template v-if="(dish.optional_ingredients ?? []).length">
            <h3 class="sub-title">可选原料</h3>
            <ul class="ing-list optional">
              <li v-for="ing in dish.optional_ingredients ?? []" :key="ing" class="ing-item">
                <MdRender :content="ing" />
              </li>
            </ul>
          </template>
          <div v-if="dish.calculation" class="calc-block">
            <h3 class="sub-title">定量参考</h3>
            <div class="calc">
              <MdRender :content="dish.calculation" />
            </div>
          </div>
        </div>

        <div class="app-card col-steps">
          <h3>做法</h3>
          <el-radio-group v-model="activeVersion" class="ver-tabs">
            <el-radio-button v-for="v in versions" :key="v" :value="v">{{ v === 'default' ? '标准做法' : v }}</el-radio-button>
          </el-radio-group>
          <ol class="step-list">
            <li v-for="s in stepsOfVersion" :key="s.order" class="step-item">
              <span class="step-no">{{ s.order }}</span>
              <span class="step-text"><MdRender :content="s.text" /></span>
            </li>
          </ol>
          <div v-if="dish.notes" class="notes">
            <h3 class="sub-title">附加内容</h3>
            <MdRender :content="dish.notes" />
          </div>
        </div>
      </div>

      <div v-if="related.length" class="app-card related-card">
        <h3>相关菜</h3>
        <div class="grid">
          <DishCard v-for="r in related.slice(0, 6)" :key="r.dish_id" :dish="r" />
        </div>
      </div>
    </template>
    <el-empty v-else-if="!loading" description="菜谱不存在" />
  </div>
</template>

<style scoped>
.detail-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cover-wrap {
  margin-bottom: 14px;
}

.cover {
  width: 100%;
  max-height: 360px;
  object-fit: cover;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}

.thumbs {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  overflow-x: auto;
}

.thumb {
  width: 72px;
  height: 54px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 2px solid transparent;
  opacity: 0.75;
  transition: all 0.15s ease;
}

.thumb:hover {
  opacity: 1;
}

.thumb.on {
  border-color: var(--accent);
  opacity: 1;
}

.head-card .name {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 24px;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  font-size: 13px;
  color: var(--text-secondary);
}

.intro {
  margin: 10px 0 0;
  color: var(--text-primary);
  line-height: 1.7;
}

.actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.rating-label {
  margin-left: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.columns {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 16px;
}

@media (max-width: 720px) {
  .columns {
    grid-template-columns: 1fr;
  }
}

.sub-title {
  margin-top: 16px;
}

.ing-list {
  margin: 0;
  padding-left: 18px;
  line-height: 2;
  color: var(--text-primary);
}

/* 原料项内 MdRender：内联展示（短文本可能含加粗等 md 标记） */
.ing-item :deep(.md-body),
.ing-item :deep(.md-body p) {
  display: inline;
  margin: 0;
}

.ing-list.optional li {
  color: var(--text-secondary);
}

.calc-block {
  margin-top: 12px;
}

.calc {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  font-size: 13px;
  margin: 0;
}

/* 定量参考/步骤/附加内容内的 MdRender：段落边距收敛 */
.calc :deep(.md-body p),
.step-text :deep(.md-body p),
.notes :deep(.md-body p) {
  margin: 4px 0;
}

.calc :deep(.md-body ul),
.calc :deep(.md-body ol) {
  margin: 4px 0;
  padding-left: 20px;
}

.step-text :deep(.md-body),
.notes :deep(.md-body) {
  line-height: 1.7;
}

.ver-tabs {
  margin-bottom: 12px;
}

.step-list {
  margin: 0;
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-item {
  display: flex;
  gap: 10px;
  line-height: 1.7;
  color: var(--text-primary);
}

.step-no {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-primary);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.notes {
  margin-top: 16px;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
  color: var(--text-secondary);
  line-height: 1.7;
  font-size: 13px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
</style>
