<script setup lang="ts">
/** 画像问卷表单（§8.1）：口味维度 1~5、忌口、饮食类型、技能、工具、人数、目标。 */
import { reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { Profile } from '@/api/users'

const props = defineProps<{ profile: Profile }>()
const emit = defineEmits<{ saved: [] }>()

const form = reactive<Profile>({ ...props.profile })

watch(
  () => props.profile,
  (p) => Object.assign(form, p),
)

const flavorFields = [
  { key: 'flavor_spicy' as const, label: '辣度' },
  { key: 'flavor_sweet' as const, label: '甜度' },
  { key: 'flavor_sour' as const, label: '酸度' },
  { key: 'flavor_light' as const, label: '清淡' },
]

const toolOptions = ['微波炉', '空气炸锅', '电饭煲', '烤箱', '高压锅']
const skillOptions = ['新手', '进阶', '熟练']
const dietOptions = ['无限制', '素食', '减脂', '清真']
const goalOptions = ['均衡', '快手', '省事', '大餐', '健康']

function onSave() {
  emit('saved')
  ElMessage.success('画像已保存')
}
</script>

<template>
  <el-form :model="form" label-width="90px" class="profile-form">
    <el-form-item v-for="f in flavorFields" :key="f.key" :label="f.label">
      <el-slider v-model="form[f.key]" :min="1" :max="5" :marks="{ 1: '1', 3: '3', 5: '5' }" />
    </el-form-item>

    <el-form-item label="忌口">
      <el-select v-model="form.avoid_list" multiple filterable allow-create default-first-option placeholder="输入或选择忌口食材">
        <el-option v-for="o in ['香菜', '内脏', '海鲜', '羊肉', '芹菜', '肥肉']" :key="o" :label="o" :value="o" />
      </el-select>
    </el-form-item>

    <el-form-item label="饮食类型">
      <el-radio-group v-model="form.diet_type">
        <el-radio v-for="o in dietOptions" :key="o" :value="o">{{ o }}</el-radio>
      </el-radio-group>
    </el-form-item>

    <el-form-item label="烹饪水平">
      <el-radio-group v-model="form.skill_level">
        <el-radio v-for="o in skillOptions" :key="o" :value="o">{{ o }}</el-radio>
      </el-radio-group>
    </el-form-item>

    <el-form-item label="常用工具">
      <el-select v-model="form.tools" multiple placeholder="选择家中常备工具">
        <el-option v-for="o in toolOptions" :key="o" :label="o" :value="o" />
      </el-select>
    </el-form-item>

    <el-form-item label="常驻人数">
      <el-input-number v-model="form.family_size" :min="1" :max="12" />
    </el-form-item>

    <el-form-item label="饮食目标">
      <el-radio-group v-model="form.goal">
        <el-radio v-for="o in goalOptions" :key="o" :value="o">{{ o }}</el-radio>
      </el-radio-group>
    </el-form-item>

    <el-form-item>
      <el-button type="primary" @click="onSave">保存画像</el-button>
    </el-form-item>
  </el-form>
</template>
