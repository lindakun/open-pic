<script setup lang="ts">
/**
 * 站点外壳：零页签顶栏（品牌 + 居中搜索插槽 + 工具图标）+ 主内容区
 *
 * 遵循纯图规范（§2.3）：
 *   - 去除重复的「图墙 / 浏览」页签，把视觉重心完全让给图片
 *   - 顶栏一级动作精简，中间留给主页搜索框插槽
 *   - 滚动 200px 后自动隐藏，向上回滚或按 / 搜索时复现
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from '@/composables/useI18n'
import { useRecent } from '@/composables/useRecent'
import { globalLoading } from '@/stores/media'
import MLSheet from './MLSheet.vue'
import MLButton from './MLButton.vue'

const { mode, resolved, cycle } = useTheme()
const { t, locale, toggleLocale, formatDate } = useI18n()
const { recent, removeRecent, clearRecent } = useRecent()
const route = useRoute()
const router = useRouter()
const recentOpen = ref(false)
const brokenThumbs = ref<Set<string>>(new Set())

function markThumbBroken(id: string) {
  if (brokenThumbs.value.has(id)) return
  const next = new Set(brokenThumbs.value)
  next.add(id)
  brokenThumbs.value = next
}

function openRecentItem(id: string) {
  recentOpen.value = false
  void router.push(`/a/asset-${id.slice(0, 8)}`)
}

/** 点击左上角品牌标识：通知主页清空筛选并回到初始图墙 */
function onBrandClick() {
  window.dispatchEvent(new CustomEvent('mlib:reset-home'))
}

const headerRef = ref<HTMLElement | null>(null)
const headerHidden = ref(false)
const headerScrolled = ref(false)
const scrollProgress = ref(0)
let ticking = false
/** 上一次滚动位置：用于判断方向，向上滚动时必须立刻复现顶栏 */
let lastY = 0
let headerRo: ResizeObserver | null = null

/** 同步顶栏当前占位高度到 CSS 变量，供主页粘性工具条避让（消除叠层遮挡） */
function syncHeaderOffset() {
  const h = headerHidden.value || route.name === 'review' ? 0 : (headerRef.value?.offsetHeight ?? 57)
  document.documentElement.style.setProperty('--header-offset', `${h}px`)
}

function onRevealHeader() {
  headerHidden.value = false
  syncHeaderOffset()
}

watch(headerHidden, syncHeaderOffset)
watch(() => route.name, syncHeaderOffset)

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
  window.addEventListener('mlib:reveal-header', onRevealHeader)
  if (typeof ResizeObserver !== 'undefined' && headerRef.value) {
    headerRo = new ResizeObserver(() => syncHeaderOffset())
    headerRo.observe(headerRef.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', syncHeaderOffset)
  window.removeEventListener('mlib:reveal-header', onRevealHeader)
  headerRo?.disconnect()
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

/** 最近浏览相对时间格式化：今天内精准到分钟/小时，更早回退日期 */
function formatRelative(tsMs: number): string {
  const diffSec = Math.max(0, Math.floor((Date.now() - tsMs) / 1000))
  if (diffSec < 60) return t('recent.justNow')
  if (diffSec < 3600) return t('recent.minutesAgo', { count: Math.floor(diffSec / 60) })
  if (diffSec < 86400) return t('recent.hoursAgo', { count: Math.floor(diffSec / 3600) })
  return formatDate(Math.floor(tsMs / 1000))
}
</script>

<template>
  <a class="skip-link" href="#main">{{ t('site.skipToMain') }}</a>

  <header
    v-if="route.name !== 'review'"
    ref="headerRef"
    :class="['site-header', { 'site-header--hidden': headerHidden, 'site-header--scrolled': headerScrolled }]"
  >
    <div class="site-header__inner">
      <RouterLink
        to="/"
        class="brand"
        :aria-label="`${t('site.name')} ${t('site.home')}`"
        @click="onBrandClick"
      >
        <span class="brand__mark" aria-hidden="true">◐</span>
        <span class="brand__name">{{ t('site.name') }}</span>
      </RouterLink>

      <!-- 主页搜索框通过 Teleport 挂载于此；选片/404 等页面自动留空 -->
      <div id="site-header-center" class="site-header__center" />

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
          @click="recentOpen = true; ($event.currentTarget as HTMLElement)?.blur()"
        >
          <span aria-hidden="true">◷</span>
          <span v-if="recent.length" class="icon-btn__badge mono">{{ recent.length > 99 ? '99+' : recent.length }}</span>
        </button>
        <!-- 管理后台是独立的旧版单页，用普通链接跳转（带尾斜杠避免 302 往返） -->
        <a href="/admin/" class="admin-link" :title="t('site.admin')">{{ t('site.admin') }}</a>
      </div>
    </div>
    <div
      :class="['site-header__progress', { 'site-header__progress--loading': globalLoading }]"
      :style="{ transform: globalLoading ? undefined : `scaleX(${scrollProgress})` }"
      aria-hidden="true"
    />
  </header>

  <MLSheet v-model:open="recentOpen" :title="t('recent.title')" variant="drawer" width="340px">
    <div v-if="!recent.length" class="recent-empty muted">{{ t('recent.empty') }}</div>
    <template v-else>
      <p class="recent-summary mono muted">{{ t('recent.count', { count: recent.length }) }}</p>
      <ul class="recent-list">
        <li v-for="entry in recent" :key="entry.id" class="recent-row">
          <button type="button" class="recent-item" @click="openRecentItem(entry.id)">
            <span v-if="brokenThumbs.has(entry.id)" class="recent-item__thumb recent-item__thumb--fallback mono" aria-hidden="true">
              {{ entry.kind === 'video' ? '▶' : '◻' }}
            </span>
            <img
              v-else
              :src="entry.kind === 'video' ? `/t/${entry.id}.jpg` : `/t/${entry.id}_sm.webp`"
              alt=""
              class="recent-item__thumb"
              loading="lazy"
              @error="markThumbBroken(entry.id)"
            />
            <span class="recent-item__body">
              <span class="recent-item__title">{{ entry.title }}</span>
              <span class="recent-item__meta mono">
                <span>{{ entry.kind === 'video' ? t('facet.kindVideo') : t('facet.kindImage') }}</span>
                <span aria-hidden="true">·</span>
                <span>{{ formatRelative(entry.ts) }}</span>
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
    </template>
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

.site-header__progress--loading {
  width: 36%;
  right: auto;
  animation: header-indeterminate 1.2s var(--p-ease-in-out) infinite;
}

@keyframes header-indeterminate {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(320%);
  }
}

/* 下滚时顶栏滑出，把画面让给图片 */
.site-header--hidden {
  transform: translateY(-100%);
}

.site-header__inner {
  display: flex;
  align-items: center;
  gap: var(--p-space-5);
  max-width: 1720px;
  margin: 0 auto;
  padding: var(--p-space-2) var(--p-space-5);
  padding-top: max(var(--p-space-2), env(safe-area-inset-top, 0px));
  padding-left: max(var(--p-space-5), env(safe-area-inset-left, 0px));
  padding-right: max(var(--p-space-5), env(safe-area-inset-right, 0px));
  min-height: 54px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-2);
  font-family: var(--p-font-display);
  font-size: var(--p-step-1);
  font-weight: 600;
  letter-spacing: -0.02em;
  flex-shrink: 0;
}

.brand:hover {
  text-decoration: none;
}

.brand__mark {
  color: var(--accent);
  font-size: 1.125rem;
}

.site-header__center {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: center;
}

.site-header__actions {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
  flex-shrink: 0;
  margin-left: auto;
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
  top: 0;
  right: -2px;
  min-width: 15px;
  height: 15px;
  padding: 0 3.5px;
  border-radius: var(--p-radius-full);
  background: var(--accent);
  color: var(--on-accent);
  border: 1.5px solid var(--paper);
  font-size: 0.625rem;
  line-height: 12px;
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

.recent-summary {
  font-size: 0.75rem;
  margin: 0 0 var(--p-space-3);
}

.recent-item__thumb--fallback {
  display: grid;
  place-items: center;
  color: var(--ink-faint);
  border: 1px solid var(--rule);
  font-size: 0.875rem;
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
  width: 36px;
  height: 36px;
  border-radius: var(--p-radius-full);
  color: var(--ink-faint);
  display: grid;
  place-items: center;
  flex-shrink: 0;
  opacity: 0.72;
  font-size: 1rem;
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

@media (max-width: 680px) {
  .site-header__inner {
    flex-wrap: wrap;
    gap: var(--p-space-2);
    padding: var(--p-space-2) var(--p-space-3);
  }
  .site-header__center:not(:empty) {
    order: 3;
    flex: 1 1 100%;
  }
}

@media (max-width: 520px) {
  .brand__name {
    font-size: var(--p-step-0);
  }

  .brand {
    min-height: 40px;
    padding: 2px 0;
  }

  .icon-btn {
    width: 40px;
    height: 40px;
  }

  .admin-link {
    display: inline-flex;
    align-items: center;
    min-height: 40px;
  }
}

@media (max-width: 360px) {
  /* 超窄屏把管理入口移出首屏，优先保证品牌与核心工具不换行 */
  .admin-link {
    display: none;
  }
}
</style>
