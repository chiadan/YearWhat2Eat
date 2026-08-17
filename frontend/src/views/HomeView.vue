<script setup lang="ts">
/**
 * 推荐首页：Hero 大标题 + 场景快捷入口 + 人性化标签选项（人数/餐次/口味/时长）
 * + 规则推荐结果（§10：无 LLM、毫秒级——千人千面规则打分 + 荤素规划，菜单卡片 + 参考菜谱）
 * + 页面加载默认自动推荐一次（无"大家喜欢"热门流）。
 */
import { onMounted, ref } from 'vue'
import { Refresh, MagicStick } from '@element-plus/icons-vue'
import { apiRuleRecommend, type MenuPlan, type SourceRef } from '@/api/chat'
import MenuCard from '@/components/MenuCard.vue'
import SourceCard from '@/components/SourceCard.vue'

const appName = import.meta.env.VITE_APP_NAME || '是啊吃什么'

// ── 场景快捷入口（4 个，需求 4） ──
const scenes = [
  { label: '深夜食堂', emoji: '🌙', build: () => ({ people: 1, mealTime: '夜宵', maxTime: 20, flavors: [] }) },
  { label: '减脂餐', emoji: '🥗', build: () => ({ people: 1, mealTime: '晚餐', maxTime: 30, flavors: ['清淡'] }) },
  { label: '招待朋友', emoji: '🥂', build: () => ({ people: 4, mealTime: '晚餐', maxTime: 120, flavors: [] }) },
  { label: '周末大餐', emoji: '🍲', build: () => ({ people: 3, mealTime: '晚餐', maxTime: 90, flavors: ['辣'] }) },
]

// ── 标签式选项（人性化） ──
const people = ref(2)
const mealTime = ref('晚餐')
const flavors = ref<string[]>([])
const maxTime = ref(30)
const mealOptions = ['早餐', '午餐', '晚餐', '夜宵']
const flavorOptions = ['辣', '清淡', '甜', '酸', '咸鲜']
const timeOptions = [
  { label: '15 分钟内', value: 15 },
  { label: '30 分钟内', value: 30 },
  { label: '1 小时内', value: 60 },
  { label: '不赶时间', value: 0 },
]

const loading = ref(false)
const plan = ref<MenuPlan | null>(null)
const reason = ref('')
const sources = ref<SourceRef[]>([])

function applyScene(build: () => { people: number; mealTime: string; maxTime: number; flavors: string[] }) {
  const s = build()
  people.value = s.people
  mealTime.value = s.mealTime
  maxTime.value = s.maxTime
  flavors.value = [...s.flavors]
  void recommend()
}

function toggleFlavor(f: string, checked: boolean) {
  if (checked) {
    if (!flavors.value.includes(f)) flavors.value.push(f)
  } else {
    flavors.value = flavors.value.filter((x) => x !== f)
  }
}

/** 规则推荐（§10，无 LLM）：千人千面规则打分 + 荤素规划，毫秒级；diversity=true 换一批 */
async function recommend() {
  loading.value = true
  plan.value = null
  reason.value = ''
  sources.value = []
  try {
    const result = await apiRuleRecommend({
      people: people.value,
      meal_time: mealTime.value,
      flavors: flavors.value,
      max_time_min: maxTime.value,
      diversity: isRefresh.value, // 换一批：探索采样（§10）
    })
    plan.value = result.plan
    reason.value = result.reason
    sources.value = result.sources
  } finally {
    loading.value = false
  }
}

/** 换一批（§10）：同约束下 diversity 探索采样，产出不同菜单 */
const isRefresh = ref(false)

async function refresh() {
  isRefresh.value = true
  try {
    await recommend()
  } finally {
    isRefresh.value = false
  }
}

// 页面加载默认自动推荐一次（§10：规则推荐毫秒级，打开即有结果）
onMounted(() => void recommend())
</script>

<template>
  <div class="home-view">
    <!-- Hero 区（需求 4：更美观、更人性化） -->
    <section class="hero">
      <h1 class="hero-title">今天吃什么？</h1>
      <p class="hero-sub">让 {{ appName }} 根据你的口味与食材，配一桌好菜</p>
      <div class="scene-row">
        <button
          v-for="s in scenes"
          :key="s.label"
          class="scene-chip"
          :disabled="loading"
          @click="applyScene(s.build)"
        >
          <span class="scene-emoji">{{ s.emoji }}</span>{{ s.label }}
        </button>
      </div>
    </section>

    <!-- 人性化选项 -->
    <section class="ask-card app-card">
      <div class="opt-row">
        <span class="opt-label">人数</span>
        <el-radio-group v-model="people">
          <el-radio-button v-for="n in [1, 2, 3, 4]" :key="n" :value="n">{{ n }} 人</el-radio-button>
          <el-radio-button :value="5">5+</el-radio-button>
        </el-radio-group>
      </div>
      <div class="opt-row">
        <span class="opt-label">餐次</span>
        <el-radio-group v-model="mealTime">
          <el-radio-button v-for="t in mealOptions" :key="t" :value="t">{{ t }}</el-radio-button>
        </el-radio-group>
      </div>
      <div class="opt-row">
        <span class="opt-label">口味</span>
        <el-check-tag
          v-for="f in flavorOptions"
          :key="f"
          :checked="flavors.includes(f)"
          class="flavor-chip"
          @change="(checked: boolean) => toggleFlavor(f, checked)"
        >
          {{ f }}
        </el-check-tag>
      </div>
      <div class="opt-row">
        <span class="opt-label">时长</span>
        <el-radio-group v-model="maxTime">
          <el-radio-button v-for="t in timeOptions" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
        </el-radio-group>
      </div>
      <div class="opt-actions">
        <el-button type="primary" size="large" :loading="loading" @click="recommend">
          <el-icon><MagicStick /></el-icon>推荐菜单
        </el-button>
        <el-button size="large" :disabled="!plan" @click="refresh">
          <el-icon><Refresh /></el-icon>换一批
        </el-button>
      </div>
    </section>

    <!-- 推荐结果（规则推荐 §10：菜单卡片 + 推荐理由 + 参考菜谱，毫秒级） -->
    <section v-if="plan" class="result">
      <MenuCard :plan="plan" />
      <p v-if="reason" class="reason">{{ reason }}</p>
      <SourceCard v-if="sources.length" :items="sources" />
    </section>
  </div>
</template>

<style scoped>
.home-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* Hero：大标题 + 场景入口 */
.hero {
  text-align: center;
  padding: 28px 16px 8px;
}

.hero-title {
  margin: 0;
  font-size: 34px;
  font-weight: 800;
  color: var(--text-strong);
  letter-spacing: 1px;
}

.hero-sub {
  margin: 8px 0 20px;
  color: var(--text-secondary);
  font-size: 15px;
}

.scene-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}

.scene-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.scene-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  transform: translateY(-1px);
  box-shadow: var(--shadow);
}

.scene-chip:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.scene-emoji {
  font-size: 16px;
}

/* 选项区 */
.opt-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  flex-wrap: wrap;
}

.opt-label {
  min-width: 44px;
  font-size: 14px;
  color: var(--text-secondary);
}

.flavor-chip {
  margin-right: 8px;
}

.opt-actions {
  display: flex;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}

/* 结果区 */
.result {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.reason {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
}
</style>
