/**
 * 主题管理
 *
 * 浅色编辑纸感为主视觉（拍板决策 5），深色为等价映射的可选主题。
 * 默认 auto：跟随系统，但浅色是设计基准。
 */
import { computed, ref, watch } from 'vue'
import type { ThemeMode } from '@/api/types'

const STORAGE_KEY = 'medialib.theme'

function readStored(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'light' || v === 'dark' || v === 'auto' ? v : 'auto'
  } catch {
    return 'auto'
  }
}

const mode = ref<ThemeMode>(readStored())

/** 系统当前是否偏好深色 */
const systemDark = ref(
  window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
)

window
  .matchMedia?.('(prefers-color-scheme: dark)')
  .addEventListener('change', (e) => {
    systemDark.value = e.matches
  })

/** 实际生效的主题 */
const resolved = computed<'light' | 'dark'>(() =>
  mode.value === 'auto' ? (systemDark.value ? 'dark' : 'light') : mode.value,
)

/** 与 tokens.css 的 --paper 保持一致（浅/深） */
const THEME_COLORS: Record<'light' | 'dark', string> = {
  light: '#faf8f5',
  dark: '#14120f',
}

function apply() {
  document.documentElement.dataset.theme = resolved.value
  // 移动浏览器地址栏跟随主题，避免深色页面配浅色状态栏
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', THEME_COLORS[resolved.value])
}

watch(resolved, apply, { immediate: true })

watch(mode, (v) => {
  try {
    localStorage.setItem(STORAGE_KEY, v)
  } catch {
    // 存储不可用时忽略
  }
})

export function useTheme() {
  function cycle() {
    mode.value = mode.value === 'light' ? 'dark' : mode.value === 'dark' ? 'auto' : 'light'
  }

  return {
    mode,
    resolved,
    cycle,
    set: (m: ThemeMode) => (mode.value = m),
  }
}
