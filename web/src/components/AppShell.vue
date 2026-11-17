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

const { mode, cycle } = useTheme()

const headerHidden = ref(false)
let ticking = false

function onScroll() {
  if (ticking) return
  ticking = true
  requestAnimationFrame(() => {
    const y = window.scrollY
    // 顶部 40px 内始终显示；下滚隐藏、上滚显示
    if (y < 40) {
      headerHidden.value = false
    } else if (y > 200) {
      headerHidden.value = true
    }
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
  if (mode.value === 'light') return '浅色主题（点击切换）'
  if (mode.value === 'dark') return '深色主题（点击切换）'
  return '跟随系统主题（点击切换）'
}
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>

  <header :class="['site-header', { 'site-header--hidden': headerHidden }]">
    <div class="site-header__inner">
      <RouterLink to="/" class="brand" aria-label="MediaLib 首页">
        <span class="brand__mark" aria-hidden="true">◐</span>
        <span class="brand__name">MediaLib</span>
      </RouterLink>

      <nav class="site-nav" aria-label="主导航">
        <RouterLink to="/browse" class="site-nav__link">浏览</RouterLink>
      </nav>

      <div class="site-header__actions">
        <button
          type="button"
          class="icon-btn"
          :aria-label="themeLabel()"
          :title="themeLabel()"
          @click="cycle"
        >
          <span aria-hidden="true">{{ mode === 'light' ? '☀' : mode === 'dark' ? '☾' : '◐' }}</span>
        </button>
      </div>
    </div>
  </header>

  <main id="main">
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

/* 减弱动效：顶栏不滑动，仅淡出（A-03） */
@media (prefers-reduced-motion: reduce) {
  .site-header {
    transition: none;
  }
}
</style>
