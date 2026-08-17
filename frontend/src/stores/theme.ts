/**
 * 主题 store（§10.1 多主题）：5 套主流主题可选（Solarized Light/Dark、GitHub Light/Dark、Nord），
 * 持久化 localStorage；暗色主题挂 html.dark（Element Plus 联动）。
 */
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

const STORAGE_KEY = 'yeahwhat2eat-theme'

export type ThemeName =
  | 'solarized-light'
  | 'solarized-dark'
  | 'github-light'
  | 'github-dark'
  | 'nord'

export interface ThemeOption {
  name: ThemeName
  label: string
  dark: boolean
  color: string
}

export const THEME_OPTIONS: ThemeOption[] = [
  { name: 'solarized-light', label: 'Solarized 浅色', dark: false, color: '#fdf6e3' },
  { name: 'solarized-dark', label: 'Solarized 深色', dark: true, color: '#002b36' },
  { name: 'github-light', label: 'GitHub 浅色', dark: false, color: '#ffffff' },
  { name: 'github-dark', label: 'GitHub 深色', dark: true, color: '#0d1117' },
  { name: 'nord', label: 'Nord 冷色', dark: false, color: '#eceff4' },
]

const DARK_THEMES = new Set<ThemeName>(['solarized-dark', 'github-dark'])

function systemDefault(): ThemeName {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'solarized-dark'
    : 'solarized-light'
}

function applyTheme(name: ThemeName) {
  const el = document.documentElement
  el.setAttribute('data-theme', name)
  el.classList.toggle('dark', DARK_THEMES.has(name))
}

export const useThemeStore = defineStore('theme', () => {
  const stored = localStorage.getItem(STORAGE_KEY) as ThemeName | null
  const valid = THEME_OPTIONS.some((t) => t.name === stored)
  const theme = ref<ThemeName>(valid ? (stored as ThemeName) : systemDefault())

  const current = computed(() => THEME_OPTIONS.find((t) => t.name === theme.value) ?? THEME_OPTIONS[0])
  const isDark = computed(() => current.value.dark)

  function setTheme(name: ThemeName) {
    theme.value = name
    localStorage.setItem(STORAGE_KEY, name)
    applyTheme(name)
  }

  // 初始化
  applyTheme(theme.value)

  // 主题切换事件（供 ECharts 等第三方实例监听，§10.1 图表跟随）
  watch(theme, (name) => {
    window.dispatchEvent(new CustomEvent('theme-changed', { detail: name }))
  })

  return { theme, current, isDark, setTheme, options: THEME_OPTIONS }
})
