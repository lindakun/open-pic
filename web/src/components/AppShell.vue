<script setup lang="ts">
/**
 * 站点外壳：顶栏 + 主内容区
 *
 * 遵循纯图规范（§2.3）：
 *   - 顶栏一级动作 ≤5 个
 *   - 滚动 200px 后自动隐藏，回到顶部 40px 内复现
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from '@/composables/useI18n'

const { mode, resolved, cycle } = useTheme()
const { t, locale, toggleLocale } = useI18n()

const headerHidden = ref(false)
let ticking = false
/** 上一次滚动位置：用于判断方向，向上滚动时必须立刻复现顶栏 */
let lastY = 0

function onScroll() {
  if (ticking) return
  ticking = true
  requestAnimationFrame(() => {
    const y = window.scrollY
    // 顶部 40px 内始终显示；下滚隐藏、上滚显示。
    // 仅按位置判断会在向上滚动时也保持隐藏，与「回看时顶栏复现」的预期相反。
    if (y < 40) {
      headerHidden.value = false
    } else if (y > lastY + 4 && y > 200) {
      headerHidden.value = true
    } else if (y < lastY - 4) {
      headerHidden.value = false
    }
    lastY = y
    ticking = false
  })
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})

const themeLabel = () => {
  if (mode.value === 'light') return t('site.themeLight')
  if (mode.value === 'dark') return t('site.themeDark')
  // auto 模式下说明当前实际生效的主题，避免重复带「点击切换」后缀
  const active = resolved.value === 'dark' ? t('site.themeDark') : t('site.themeLight')
  return `${t('site.themeAuto')}：${active.replace('（点击切换）', '')}`
}

/** 按钮上的语言显示：切换目标而非当前语言，减少歧义 */
const localeShort = () => (locale.value === 'zh-CN' ? 'EN' : '中')
</script>

<template>
  <a class="skip-link" href="#main">{{ t('site.skipToMain') }}</a>

  <header :class="['site-header', { 'site-header--hidden': headerHidden }]">
    <div class="site-header__inner">
      <RouterLink to="/" class="brand" :aria-label="`${t('site.name')} ${t('site.home')}`">
        <span class="brand__mark" aria-hidden="true">◐</span>
        <span class="brand__name">{{ t('site.name') }}</span>
      </RouterLink>

      <nav class="site-nav" aria-label="Main">
        <RouterLink to="/browse" class="site-nav__link">{{ t('site.browse') }}</RouterLink>
      </nav>

      <div class="site-header__actions">
        <button
          type="button"
          class="icon-btn icon-btn--text mono"
          :aria-label="`${t('site.toggleTheme')} (${themeLabel()})`"
          :title="themeLabel()"
          @click="cycle"
        >
          <span aria-hidden="true">{{ mode === 'light' ? '☀' : mode === 'dark' ? '☾' : '◐' }}</span>
        </button>
        <button
          type="button"
          class="icon-btn icon-btn--text mono"
          :aria-label="locale === 'zh-CN' ? t('site.switchToEn') : t('site.switchToZh')"
          :title="locale === 'zh-CN' ? t('site.switchToEn') : t('site.switchToZh')"
          @click="toggleLocale"
        >
          <span aria-hidden="true">{{ localeShort() }}</span>
        </button>
        <!-- 管理后台是独立的旧版单页，用普通链接跳转，不经 SPA 路由 -->
        <a href="/admin" class="admin-link" :title="t('site.admin')">{{ t('site.admin') }}</a>
      </div>
    </div>
  </header>

  <!-- tabindex=-1：让 skip link 的锚点跳转真正把焦点交给主内容区 -->
  <main id="main" tabindex="-1">
    <RouterView />
  </main>
</template>

<style scoped>
.site-header {
  position: sticky;
  top: 0;
  z-index: var(--p-z-header);
  background: color-mix(in srgb, var(--paper) 86%, transparent);
  backdrop-filter: blur(12px) saturate(1.1);
  border-bottom: 1px solid var(--rule);
  transition: transform var(--p-dur-base) var(--p-ease-out);
}

/* 下滚时顶栏滑出，把画面让给图片 */
.site-header--hidden {
  transform: translateY(-100%);
}

.site-header__inner {
  display: flex;
  align-items: center;
  gap: var(--p-space-6);
  max-width: 1600px;
  margin: 0 auto;
  padding: var(--p-space-3) var(--p-space-5);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-2);
  font-family: var(--p-font-display);
  font-size: var(--p-step-1);
  font-weight: 600;
  letter-spacing: -0.02em;
}

.brand:hover {
  text-decoration: none;
}

.brand__mark {
  color: var(--accent);
  font-size: 1.125rem;
}

.site-nav {
  display: flex;
  gap: var(--p-space-4);
  flex: 1;
}

.site-nav__link {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  letter-spacing: 0.04em;
  padding: var(--p-space-1) 0;
  border-bottom: 1px solid transparent;
  transition: color var(--p-dur-fast) var(--p-ease-out);
}

.site-nav__link:hover {
  color: var(--ink);
  text-decoration: none;
}

.site-nav__link.router-link-active {
  color: var(--ink);
  border-bottom-color: var(--accent);
}

.site-header__actions {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--p-radius-md);
  color: var(--ink-muted);
  font-size: 1rem;
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.icon-btn:hover {
  background: var(--surface-hover);
  color: var(--ink);
}

/* 文字型图标按钮（语言切换）：字号略小以保持视觉重量一致 */
.icon-btn--text {
  font-size: 0.75rem;
  font-weight: 500;
  letter-spacing: 0.02em;
}

/* 管理后台入口：文字链，弱化为工具属性，不与浏览动作争夺注意力 */
.admin-link {
  font-size: var(--p-step--1);
  color: var(--ink-faint);
  padding: var(--p-space-1) var(--p-space-2);
  border-left: 1px solid var(--rule);
  margin-left: var(--p-space-1);
  white-space: nowrap;
  transition: color var(--p-dur-fast) var(--p-ease-out);
}

.admin-link:hover {
  color: var(--ink);
  text-decoration: none;
}

/* 减弱动效：顶栏不滑动，仅淡出（A-03） */
@media (prefers-reduced-motion: reduce) {
  .site-header {
    transition: none;
  }
}
</style>
