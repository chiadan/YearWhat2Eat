<script setup lang="ts">
/**
 * Markdown 渲染组件（§7.2 / §10）：markdown-it + DOMPurify 白名单清洗。
 * - linkMap：菜名 -> dish_id，渲染前把正文中的菜名替换为可点击链接（需求 3：跳转菜谱详情）
 * - sourceMap：引用编号 [n] -> {name, dish_id}，把正文中 LLM 生成的 [n] 引用标记替换为
 *   [菜名](详情链接)（§9.1 sources 帧对应，参考不能只有数字）
 * - 全量菜名增强：自动拉取 /dishes/names 全量字典（模块级缓存），
 *   正文中出现的任何菜谱菜名都可点击（不限于 sources/plan 命中，§16 决策 16）
 * - 替换策略：按菜名长度降序，避免短名误替换长名内部；跳过已带链接的 [菜名]
 */
import { computed, onMounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { apiDishNameMap } from '@/api/dishes'

const props = defineProps<{
  content: string
  linkMap?: Record<string, string>
  /** 引用编号 -> {菜名, dish_id}（§9.1 sources 帧的 ref），正文 [n] 替换为菜名链接 */
  sourceMap?: Record<string, { name: string; dish_id: string }>
}>()

const md = new MarkdownIt({ html: false, linkify: true })

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function linkify(text: string, map: Record<string, string>): string {
  const names = Object.keys(map).sort((a, b) => b.length - a.length)
  let out = text
  for (const n of names) {
    if (!n) continue
    const re = new RegExp(`(?<!\\[)(${escapeRegExp(n)})(?!\\])`, 'g')
    out = out.replace(re, `[$1](/dishes/${map[n]})`)
  }
  return out
}

/** 正文 [n] 引用标记 -> 菜名链接；引用前已出现该菜名（含 markdown 修饰、更早位置）则保留 [n] 角标 */
function replaceRefs(text: string, map: Record<string, { name: string; dish_id: string }>): string {
  return text.replace(/\[(\d+)\]/g, (m, n: string, offset: number) => {
    const s = map[n]
    if (!s || !s.name) return m
    // 加粗标题（"1. **农家一碗香**[1]"）或"农家一碗香的做法[1]"：菜名已在引用前出现（LLM 已写），
    // 保留 [n] 角标，防止菜名重复（链接化会把正文菜名也变成链接）
    if (text.slice(0, offset).includes(s.name)) {
      return m
    }
    // 独立引用（"做法如下[1]"）-> 替换为菜名链接
    return `[${s.name}](/dishes/${s.dish_id})`
  })
}

// 全量菜名字典（异步拉取，完成后触发重渲染）
const allNames = ref<Record<string, string>>({})

onMounted(async () => {
  try {
    allNames.value = await apiDishNameMap()
  } catch {
    /* 静默：退化为仅 linkMap 链接 */
  }
})

const html = computed(() => {
  let src = props.content
  if (props.sourceMap && Object.keys(props.sourceMap).length) {
    src = replaceRefs(src, props.sourceMap)
  }
  const map: Record<string, string> = { ...allNames.value }
  if (props.linkMap) {
    for (const [k, v] of Object.entries(props.linkMap)) {
      if (k && !map[k]) map[k] = v
    }
  }
  src = Object.keys(map).length ? linkify(src, map) : src
  return DOMPurify.sanitize(md.render(src))
})
</script>

<template>
  <!-- DOMPurify 已白名单清洗（§10 技术要点），v-html 安全 -->
  <div class="md-body" v-html="html" />
</template>

<style scoped>
.md-body {
  line-height: 1.8;
  font-size: 14px;
  color: var(--text-primary);
  word-break: break-word;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 14px 0 8px;
  color: var(--text-strong);
  line-height: 1.4;
}

.md-body :deep(h1) {
  font-size: 20px;
}

.md-body :deep(h2) {
  font-size: 17px;
}

.md-body :deep(h3) {
  font-size: 15px;
}

.md-body :deep(p) {
  margin: 8px 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 8px 0;
  padding-left: 22px;
}

.md-body :deep(li) {
  margin: 4px 0;
}

.md-body :deep(pre) {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 13px;
  margin: 10px 0;
}

.md-body :deep(code) {
  background: var(--code-bg);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 13px;
}

.md-body :deep(pre code) {
  background: none;
  padding: 0;
}

.md-body :deep(blockquote) {
  margin: 10px 0;
  padding: 4px 12px;
  border-left: 3px solid var(--highlight);
  color: var(--text-secondary);
  background: var(--bg-hover);
  border-radius: 0 6px 6px 0;
}

.md-body :deep(a) {
  color: var(--accent);
}

.md-body :deep(strong) {
  color: var(--text-strong);
}

.md-body :deep(table) {
  border-collapse: collapse;
  margin: 10px 0;
  width: 100%;
}

.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
}

.md-body :deep(th) {
  background: var(--bg-hover);
}
</style>
