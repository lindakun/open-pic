<script setup lang="ts">
/**
 * 浏览页（REQ-V2-20 A-05 / B-10）
 *
 * 结构：左侧分面面板 + 右侧瀑布流。
 * URL 即状态：刷新或分享链接都能还原完整筛选视图。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMediaStore } from '@/stores/media'
import { useFilterStore } from '@/stores/filters'
import { useToast } from '@/composables/useToast'
import { useAiStatus } from '@/composables/useAiStatus'
import { api } from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import MasonryGrid from '@/components/MasonryGrid.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import FacetPanel from '@/components/FacetPanel.vue'
import MLButton from '@/components/MLButton.vue'
import MLChip from '@/components/MLChip.vue'
import UploadPanel from '@/components/UploadPanel.vue'
import BatchBar from '@/components/BatchBar.vue'
import type { Collection } from '@/api/types'
import type { SortKey } from '@/api/types'
import {
  clearScrollAnchor,
  readScrollAnchor,
  restoreScrollAnchor,
  sampleAnchor,
  saveScrollAnchor,
} from '@/composables/useScrollRestore'

const store = useMediaStore()
const filters = useFilterStore()
const toast = useToast()
const route = useRoute()
const { t, formatNumber } = useI18n()

const searchInput = ref(filters.q)
/** AI 检索能力（B-08）：未启用时隐藏以图搜图入口 */
const { status: aiStatus, load: loadAiStatus } = useAiStatus()
const dragActive = ref(false)
const aiBusy = ref(false)
/** 上传面板与批量选择（REQ-05） */
const uploadOpen = ref(false)
const selectMode = ref(false)
const selectedIds = ref<string[]>([])
const collections = ref<Collection[]>([])
/** 移动端分面面板折叠 */
const facetsOpen = ref(false)

let debounceTimer: number | undefined

function onSearchInput(value: string) {
  searchInput.value = value
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => {
    filters.setQ(value)
    store.refresh()
  }, 300)
}

/** 排序项：label 由 i18n 提供，故用 key 而非直接存文案 */
const SORT_KEYS: SortKey[] = ['newest', 'oldest', 'pixels', 'size', 'views']

/** 方向 chip 的 i18n key */
const ORIENTATION_KEY: Record<string, string> = {
  landscape: 'facet.landscape',
  portrait: 'facet.portrait',
  square: 'facet.square',
}

function changeSort(value: SortKey) {
  filters.setSort(value)
  store.refresh()
}

/** 以图搜图（B-08）：拖入或粘贴图片即检索相似资产 */
async function searchByImage(file: File) {
  if (!aiStatus.value?.available || aiBusy.value) return
  aiBusy.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/search/by-image', { method: 'POST', body: fd })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      toast.error(body.detail || t('ai.searchFailed'))
      return
    }
    const data = await res.json()
    store.replaceItems(data.items ?? [], data.total ?? 0)
  } finally {
    aiBusy.value = false
  }
}

function onDrop(e: DragEvent) {
  dragActive.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file && file.type.startsWith('image/')) void searchByImage(file)
}

function onPaste(e: ClipboardEvent) {
  if (!aiStatus.value?.available) return
  const file = Array.from(e.clipboardData?.files ?? [])[0]
  if (file && file.type.startsWith('image/')) void searchByImage(file)
}

/** 勾选/取消勾选单项（REQ-05 批量操作） */
function toggleSelect(id: string) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}

function clearSelection() {
  selectedIds.value = []
}

/** 开启选择模式时清空旧选择，避免跨筛选的陈旧选择 */
function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) clearSelection()
}

async function onUploaded() {
  await store.refresh()
}

async function loadCollections() {
  try {
    collections.value = await api.collections()
  } catch {
    collections.value = []
  }
}

function onBatchDone() {
  void store.refresh()
  clearSelection()
}

/** 应用筛选后统一刷新（标签切换等由面板触发） */
function applyAndRefresh() {
  clearScrollAnchor()
  store.refresh()
}

/**
 * 打开灯箱。
 *
 * 不使用 View Transitions：灯箱是 `<dialog>`，处于浏览器 top layer，
 * 与共享元素快照机制不兼容（实测报 "Transition was aborted because of
 * invalid state"）。改由灯箱自身的进入动画承担过渡，功能一致且无报错。
 */
function openLightbox(index: number) {
  // 进灯箱前记录锚点（D-17）：返回列表时按资产定位，而非纯像素
  const anchor = sampleAnchor()
  if (anchor) saveScrollAnchor(anchor)
  store.openLightbox(index)
}

/** 从灯箱返回：还原锚点（列数变化也能回到同一资产） */
function onCloseLightbox() {
  store.closeLightbox()
  restoreScrollAnchor(readScrollAnchor(), store.items)
}

/**
 * 对比候选（A-04）：取当前项前后各若干项，覆盖同屏浏览范围即可。
 * 传整屏 48 项会带来无谓的缩略图请求，故限制在附近 8 项。
 */
const compareCandidates = computed(() => {
  const start = Math.max(0, store.lightboxIndex - 4)
  return store.items.slice(start, start + 8)
})

/** 灯箱内点色板 → 按主色筛选（打通 A-04 与 B-10） */
function onFilterColor(color: string) {
  filters.setColor(color)
  store.refresh()
}

// 从 URL 还原筛选，然后加载
onMounted(async () => {
  filters.fromUrlQuery(route.query as Record<string, string>)
  searchInput.value = filters.q
  await store.refresh()
  // 首次渲染后还原上次锚点（D-17 验收 3）
  restoreScrollAnchor(readScrollAnchor(), store.items)
  // 探测 AI 能力（B-08）：失败静默，入口隐藏即可
  void loadAiStatus()
  void loadCollections()
  window.addEventListener('paste', onPaste)
})

onUnmounted(() => {
  window.removeEventListener('paste', onPaste)
})

// 筛选变化时刷新（面板内直接改 store 的路径）
watch(
  () => [
    filters.tags.join(','),
    filters.excludeTags.join(','),
    filters.kind,
    filters.orientation,
    filters.platform,
    filters.ext,
  ],
  () => {
    applyAndRefresh()
  },
)

watch(
  () => store.error,
  (err) => {
    if (err) toast.error(err)
  },
)
</script>

<template>
  <div class="browse">
    <!-- 页面主标题：屏幕阅读器用于定位，视觉上以工具条承担同样语义 -->
    <h1 class="sr-only">{{ t('site.browse') }}</h1>

    <!-- 工具条 -->
    <div class="browse__toolbar">
      <button
        type="button"
        class="browse__facets-toggle"
        :aria-expanded="facetsOpen"
        aria-controls="facet-panel"
        @click="facetsOpen = !facetsOpen"
      >
        {{ t('browse.filter') }}
        <span v-if="filters.activeCount" class="browse__badge mono">
          {{ filters.activeCount }}
        </span>
      </button>

      <div
        :class="['browse__search', { 'browse__search--drag': dragActive, 'browse__search--busy': aiBusy }]"
        @dragover.prevent="aiStatus?.available && (dragActive = true)"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="onDrop"
      >
        <span class="browse__search-icon" aria-hidden="true">⌕</span>
        <input
          :value="searchInput"
          type="search"
          class="browse__search-input"
          :placeholder="dragActive ? t('ai.dropHint') : t('browse.searchPlaceholder')"
          :aria-label="t('browse.searchLabel')"
          @input="onSearchInput(($event.target as HTMLInputElement).value)"
        />
        <!-- AI 检索未启用时只给说明，不显示入口（B-08 验收 4） -->
        <span v-if="aiStatus && !aiStatus.available" class="browse__ai-off" :title="aiStatus.hint">
          {{ t('ai.disabled') }}
        </span>
        <span v-else-if="aiStatus?.available" class="browse__ai-on" :title="t('ai.byImageHint')">
          {{ t('ai.byImage') }}
        </span>
      </div>

      <div class="browse__sorts" role="group" :aria-label="t('sort.label')">
        <button
          v-for="key in SORT_KEYS"
          :key="key"
          type="button"
          :class="['sort-btn', { 'sort-btn--on': filters.sort === key }]"
          :aria-pressed="filters.sort === key"
          @click="changeSort(key)"
        >
          {{ t(`sort.${key}`) }}
        </button>
      </div>

      <MLButton variant="quiet" @click="uploadOpen = true">{{ t('upload.open') }}</MLButton>
      <MLButton
        variant="quiet"
        :aria-pressed="selectMode"
        @click="toggleSelectMode"
      >
        {{ selectMode ? t('batch.exitSelect') : t('batch.select') }}
      </MLButton>

      <span class="browse__count mono" aria-live="polite">
        {{
          store.loading && !store.items.length
            ? t('site.loading')
            : t('site.total', { count: store.total })
        }}
      </span>
    </div>

    <!-- 已选条件 chips 条 -->
    <div v-if="filters.hasFilters" class="browse__active" :aria-label="t('browse.activeFilters')">
      <MLChip
        v-if="filters.q"
        :label="t('browse.keyword', { value: filters.q })"
        removable
        @remove="filters.setQ(''); searchInput = ''; applyAndRefresh()"
      />
      <MLChip
        v-for="tag in filters.tags"
        :key="`t-${tag}`"
        :label="tag"
        removable
        active
        @remove="filters.removeTag(tag); applyAndRefresh()"
      />
      <MLChip
        v-for="tag in filters.excludeTags"
        :key="`x-${tag}`"
        :label="tag"
        tone="exclude"
        removable
        @remove="filters.removeExclude(tag); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.kind"
        :label="filters.kind === 'image' ? t('facet.kindImage') : t('facet.kindVideo')"
        removable
        active
        @remove="filters.setKind(''); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.orientation"
        :label="t(ORIENTATION_KEY[filters.orientation])"
        removable
        active
        @remove="filters.setOrientation(''); applyAndRefresh()"
      />
      <button type="button" class="browse__clear" @click="filters.reset(); applyAndRefresh()">
        {{ t('browse.clearAll') }}
      </button>
    </div>

    <div class="browse__layout">
      <!-- 分面面板：桌面常驻，移动端按需展开 -->
      <div
        id="facet-panel"
        :class="['browse__facets', { 'browse__facets--open': facetsOpen }]"
      >
        <FacetPanel :facets="store.facets" :loading="store.facetsLoading" />
      </div>

      <div class="browse__main">
        <div v-if="store.isEmpty" class="browse__empty">
          <h2>{{ t('browse.emptyTitle') }}</h2>
          <p class="muted">
            {{ filters.hasFilters ? t('browse.emptyHint') : t('browse.emptyHintNoFilter') }}
          </p>
          <MLButton
            v-if="filters.hasFilters"
            variant="ghost"
            @click="filters.reset(); applyAndRefresh()"
          >
            {{ t('browse.clearFilter') }}
          </MLButton>
        </div>

        <MasonryGrid
          v-else
          :items="store.items"
          :selectable="selectMode"
          :selected-ids="selectedIds"
          @open="openLightbox"
          @toggle="toggleSelect"
        />

        <div v-if="store.hasMore" class="browse__more">
          <MLButton variant="ghost" :disabled="store.loading" @click="store.load()">
            {{ store.loading ? t('site.loading') : t('browse.loadMore') }}
          </MLButton>
        </div>
      </div>
    </div>

    <LightboxViewer
      v-if="store.currentItem"
      :item="store.currentItem"
      :has-prev="store.lightboxIndex > 0"
      :has-next="store.lightboxIndex < store.items.length - 1"
      :candidates="compareCandidates"
      @close="onCloseLightbox"
      @prev="store.stepLightbox(-1)"
      @next="store.stepLightbox(1)"
      @filter-color="onFilterColor"
    />

    <UploadPanel v-model:open="uploadOpen" @uploaded="onUploaded" />

    <BatchBar
      :selected="selectedIds"
      :collections="collections"
      @clear="clearSelection"
      @done="onBatchDone"
    />
  </div>
</template>

<style scoped>
.browse {
  max-width: 1700px;
  margin: 0 auto;
  padding: var(--p-space-5) var(--p-space-5) var(--p-space-9);
}

.browse__toolbar {
  display: flex;
  align-items: center;
  gap: var(--p-space-4);
  flex-wrap: wrap;
  padding-bottom: var(--p-space-4);
}

.browse__facets-toggle {
  display: none;
  align-items: center;
  gap: var(--p-space-1);
  font-size: var(--p-step--1);
  color: var(--ink);
  border: 1px solid var(--rule-strong);
  border-radius: var(--p-radius-md);
  padding: var(--p-space-1) var(--p-space-3);
  min-height: 32px;
}

.browse__badge {
  background: var(--accent);
  color: var(--on-accent);
  border-radius: var(--p-radius-full);
  font-size: 0.6875rem;
  padding: 0 5px;
  min-width: 16px;
  text-align: center;
}

.browse__search {
  position: relative;
  flex: 1;
  min-width: 200px;
}

/* 拖入图片时的全框高亮：明确告诉用户这里可以接图片（B-08） */
.browse__search--drag {
  outline: 2px dashed var(--accent);
  outline-offset: 2px;
  border-radius: var(--p-radius-md);
}

.browse__search--busy {
  opacity: 0.7;
}

/* 右侧能力标识：不可用时只作说明，不构成可点击入口 */
.browse__ai-off,
.browse__ai-on {
  position: absolute;
  right: var(--p-space-3);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--p-step--1);
  white-space: nowrap;
  pointer-events: none;
}

.browse__ai-off {
  color: var(--ink-faint);
}

.browse__ai-on {
  color: var(--accent);
  font-weight: 500;
}

.browse__search-icon {
  position: absolute;
  left: var(--p-space-3);
  top: 50%;
  transform: translateY(-50%);
  color: var(--ink-faint);
  pointer-events: none;
}

.browse__search-input {
  width: 100%;
  font: inherit;
  font-size: var(--p-step-0);
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--rule-strong);
  border-radius: var(--p-radius-md);
  padding: var(--p-space-2) var(--p-space-3) var(--p-space-2) var(--p-space-7);
  min-height: 36px;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.browse__search-input:hover,
.browse__search-input:focus {
  border-color: var(--ink-faint);
}

.browse__search-input::placeholder {
  color: var(--ink-faint);
}

.browse__sorts {
  display: flex;
  gap: var(--p-space-1);
}

.sort-btn {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-3);
  border-radius: var(--p-radius-full);
  min-height: 28px;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.sort-btn:hover {
  color: var(--ink);
  background: var(--surface-hover);
}

.sort-btn--on {
  color: var(--accent-hover);
  background: var(--accent-soft);
  font-weight: 500;
}

.browse__count {
  font-size: var(--p-step--1);
  color: var(--ink-faint);
  margin-left: auto;
}

/* 已选 chips 条 */
.browse__active {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--p-space-1);
  padding-bottom: var(--p-space-4);
  border-bottom: 1px solid var(--rule);
  margin-bottom: var(--p-space-5);
}

.browse__clear {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-2);
}

.browse__clear:hover {
  color: var(--danger);
}

/* 两栏布局 */
.browse__layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--p-space-7);
  align-items: start;
}

.browse__facets {
  position: sticky;
  top: var(--p-space-6);
}

.browse__main {
  min-width: 0;
}

.browse__empty {
  padding: var(--p-space-9) 0;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-3);
}

.browse__more {
  display: flex;
  justify-content: center;
  padding: var(--p-space-7) 0;
}

/* 窄屏：分面面板收起为抽屉式，工具条折叠按钮出现 */
@media (max-width: 900px) {
  .browse__layout {
    grid-template-columns: 1fr;
  }

  .browse__facets-toggle {
    display: inline-flex;
  }

  .browse__facets {
    display: none;
    position: static;
  }

  .browse__facets--open {
    display: block;
    padding-bottom: var(--p-space-4);
    border-bottom: 1px solid var(--rule);
    margin-bottom: var(--p-space-4);
  }
}
</style>
