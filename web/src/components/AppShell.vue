<script setup lang="ts">
/**
 * 站点外壳：顶栏 + 主内容区
 *
 * 遵循纯图规范（§2.3）：
 *   - 顶栏一级动作 ≤5 个
 *   - 滚动 200px 后自动隐藏，回到顶部 40px 内复现
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from '@/composables/useI18n'
import { useRecent } from '@/composables/useRecent'
import MLSheet from './MLSheet.vue'
import MLButton from './MLButton.vue'

const { mode, resolved, cycle } = useTheme()
const { t, locale, toggleLocale, formatDate } = useI18n()
const { recent, removeRecent, clearRecent } = useRecent()
const router = useRouter()
const recentOpen = ref(false)

function openRecentItem(id: string) {
  recentOpen.value = false
  void router.push(`/a/asset-${id.slice(0, 8)}`)
}

const headerRef = ref<HTMLElement | null>(null)
const headerHidden = ref(false)
const headerScrolled = ref(false)
const scrollProgress = ref(0)
let ticking = false
/** 上一次滚动位置：用于判断方向，向上滚动时必须立刻复现顶栏 */
let lastY = 0

/** 同步顶栏当前占位高度到 CSS 变量，供首页粘性工具条避让（消除叠层遮挡） */
function syncHeaderOffset() {
  const h = headerHidden.value ? 0 : (headerRef.value?.offsetHeight ?? 57)
  document.documentElement.style.setProperty('--header-offset', `${h}px`)
}

watch(headerHidden, syncHeaderOffset)

function onScroll() {
  if (ticking) return
  ticking = true
  requestAnimationFrame(() => {
    const y = window.scrollY
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight)
    scrollProgress.value = maxScroll > 0 ? Math.min(1, Math.max(0, y / maxScroll)) : 0
    headerScrolled.value = y > 20
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
  syncHeaderOffset()
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', syncHeaderOffset, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', syncHeaderOffset)
  document.documentElement.style.removeProperty('--header-offset')
})

const themeLabel = () => {
  if (mode.value === 'light') return t('site.themeLight')
  if (mode.value === 'dark') return t('site.themeDark')
  // auto 模式下说明当前实际生效的主题。用 *Short 文案而不是对完整
  // 文案做中文字符串替换——英文环境下替换不生效，会出现双重「点击切换」
  const active = resolved.value === 'dark'
    ? t('site.themeDarkShort')
    : t('site.themeLightShort')
  return `${t('site.themeAutoShort')} · ${active}`
}

/** 按钮上的语言显示：切换目标而非当前语言，减少歧义 */
const localeShort = () => (locale.value === 'zh-CN' ? 'EN' : '中')
</script>

<template>
  <a class="skip-link" href="#main">{{ t('site.skipToMain') }}</a>

  <header
    ref="headerRef"
    :class="['site-header', { 'site-header--hidden': headerHidden, 'site-header--scrolled': headerScrolled }]"
  >
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
        <button
          type="button"
          class="icon-btn icon-btn--recent"
          :aria-label="t('recent.title')"
          :title="t('recent.title')"
          @click="recentOpen = true"
        >
          <span aria-hidden="true">◷</span>
          <span v-if="recent.length" class="icon-btn__badge mono">{{ recent.length > 99 ? '99+' : recent.length }}</span>
        </button>
        <!-- 管理后台是独立的旧版单页，用普通链接跳转，不经 SPA 路由 -->
        <a href="/admin" class="admin-link" :title="t('site.admin')">{{ t('site.admin') }}</a>
      </div>
    </div>
    <div
      class="site-header__progress"
      :style="{ transform: `scaleX(${scrollProgress})` }"
      aria-hidden="true"
    />
  </header>

  <MLSheet v-model:open="recentOpen" :title="t('recent.title')" variant="drawer" width="340px">
    <div v-if="!recent.length" class="recent-empty muted">{{ t('recent.empty') }}</div>
    <ul v-else class="recent-list">
      <li v-for="entry in recent" :key="entry.id" class="recent-row">
        <button type="button" class="recent-item" @click="openRecentItem(entry.id)">
          <img
            :src="entry.kind === 'video' ? `/t/${entry.id}.jpg` : `/t/${entry.id}_sm.webp`"
            alt=""
            class="recent-item__thumb"
            loading="lazy"
          />
          <span class="recent-item__body">
            <span class="recent-item__title">{{ entry.title }}</span>
            <span class="recent-item__meta mono">
              <span>{{ entry.kind === 'video' ? t('facet.kindVideo') : t('facet.kindImage') }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ formatDate(Math.floor(entry.ts / 1000)) }}</span>
            </span>
          </span>
        </button>
        <button
          type="button"
          class="recent-row__remove"
          :aria-label="t('recent.remove')"
          :title="t('recent.remove')"
          @click.stop="removeRecent(entry.id)"
        >
          ×
        </button>
      </li>
    </ul>
    <template v-if="recent.length" #footer>
      <MLButton variant="quiet" size="sm" @click="clearRecent">{{ t('recent.clear') }}</MLButton>
    </template>
  </MLSheet>

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
  transition:
    transform var(--p-dur-base) var(--p-ease-out),
    box-shadow var(--p-dur-base) var(--p-ease-out);
}

.site-header--scrolled {
  box-shadow: 0 4px 16px color-mix(in srgb, var(--ink) 6%, transparent);
}

.site-header__progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--accent);
  transform-origin: left center;
  pointer-events: none;
  opacity: 0.78;
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

.icon-btn--recent {
  position: relative;
}

.icon-btn__badge {
  position: absolute;
  top: 2px;
  right: 1px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: var(--p-radius-full);
  background: var(--accent);
  color: var(--on-accent);
  font-size: 0.625rem;
  line-height: 14px;
  text-align: center;
  pointer-events: none;
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

.recent-empty {
  padding: var(--p-space-6) 0;
  text-align: center;
  font-size: var(--p-step--1);
}

.recent-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
}

.recent-row {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
}

.recent-item {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-1);
  border-radius: var(--p-radius-md);
  text-align: left;
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.recent-item:hover {
  background: var(--surface-hover);
}

.recent-item__thumb {
  width: 48px;
  height: 48px;
  border-radius: var(--p-radius-sm);
  object-fit: cover;
  background: var(--surface-sunken);
  flex-shrink: 0;
}

.recent-item__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.recent-item__title {
  font-size: var(--p-step--1);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-item__meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.6875rem;
  color: var(--ink-faint);
}

.recent-row__remove {
  width: 24px;
  height: 24px;
  border-radius: var(--p-radius-full);
  color: var(--ink-faint);
  display: grid;
  place-items: center;
  flex-shrink: 0;
  opacity: 0.65;
  transition:
    opacity var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.recent-row__remove:hover {
  opacity: 1;
  background: var(--surface-hover);
  color: var(--ink);
}
</style>
