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
import { pushRecent } from '@/composables/useRecent'
import { track, useEventFlush, useImpressionTracker } from '@/composables/useAnalytics'
import { api } from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import MasonryGrid from '@/components/MasonryGrid.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import FacetPanel from '@/components/FacetPanel.vue'
import MLButton from '@/components/MLButton.vue'
import MLChip from '@/components/MLChip.vue'
import UploadPanel from '@/components/UploadPanel.vue'
import BatchBar from '@/components/BatchBar.vue'
import type { Collection, SortKey, ViewMode } from '@/api/types'
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
const { t } = useI18n()

const searchInput = ref(filters.q)
/** AI 检索能力（B-08）：未启用时隐藏以图搜图入口 */
const { status: aiStatus, load: loadAiStatus } = useAiStatus()
const dragActive = ref(false)
const aiBusy = ref(false)
/** 上传面板与批量选择（REQ-05） */
const uploadOpen = ref(false)
const selectMode = ref(false)
const selectedIds = ref<string[]>([])
/**
 * 空态文案：区分「搜索无结果」「筛选无结果」「库本来就空」三种情况，
 * 统一文案会让用户不知道下一步该做什么。
 */
const emptyHint = computed(() => {
  if (filters.q.trim()) return t('browse.emptyHintSearch', { q: filters.q.trim() })
  if (filters.hasFilters) return t('browse.emptyHintFilter')
  return t('browse.emptyHintNoFilter')
})

/** 是否具备自动分页能力（无 IntersectionObserver 时退回手动按钮） */
const pageAutoLoad = typeof IntersectionObserver !== 'undefined'

/** 分页哨兵：与首页一致的自动加载，避免每次手动点按钮 */
const sentinel = ref<HTMLElement | null>(null)
let pageObserver: IntersectionObserver | null = null
const collections = ref<Collection[]>([])
/** 收藏 id 集合（C-15）：来自后端，跨设备一致 */
const likedIds = ref<string[]>([])
const onlyLiked = ref(false)
/** 移动端分面面板折叠 */
const facetsOpen = ref(false)

let debounceTimer: number | undefined

function onSearchInput(value: string) {
  searchInput.value = value
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(async () => {
    filters.setQ(value)
    await applyAndRefresh()
    // 记录搜索结果数：后续「零结果搜索词榜」直接来自这里（D-18）
    if (value.trim()) {
      track('search', { meta: { q: value.trim(), result_count: store.total } })
    }
  }, 300)
}

/** 一键清除搜索词：取消未决防抖、同步状态、只刷一次 */
function clearSearch() {
  window.clearTimeout(debounceTimer)
  searchInput.value = ''
  filters.setQ('')
  applyAndRefresh()
}

/** 排序项：label 由 i18n 提供，故用 key 而非直接存文案 */
const SORT_KEYS: SortKey[] = ['newest', 'oldest', 'pixels', 'size', 'views', 'random']

/** 视图模式（REQ-06）：瀑布流 / 等高网格 / 紧凑列表 */
const VIEW_MODES: { key: ViewMode; icon: string }[] = [
  { key: 'masonry', icon: '⊞' },
  { key: 'grid', icon: '⊟' },
  { key: 'list', icon: '☰' },
]

function changeView(mode: ViewMode) {
  filters.setView(mode)
  try {
    localStorage.setItem('medialib.view', mode)
  } catch {
    // 隐私模式静默忽略
  }
}

/** 方向 chip 的 i18n key */
const ORIENTATION_KEY: Record<string, string> = {
  landscape: 'facet.landscape',
  portrait: 'facet.portrait',
  square: 'facet.square',
}

/** 分辨率分桶的 i18n key（与分面面板同源） */
const SIZE_KEY: Record<string, string> = {
  '4k': 'facet.size4k',
  hd: 'facet.sizeHd',
  sd: 'facet.sizeSd',
  small: 'facet.sizeSmall',
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
    // 一次性检索结果替换整份列表：与筛选切换同样需要回顶并清理旧选择
    clearScrollAnchor()
    clearSelection()
    window.scrollTo({ top: 0, behavior: 'auto' })
  } finally {
    aiBusy.value = false
  }
}

function onDrop(e: DragEvent) {
  dragActive.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file && file.type.startsWith('image/')) void searchByImage(file)
}

/**
 * 拖拽高亮不应在「从父元素移到子元素」时熄灭：
 * dragleave 在经过每个子节点时都会触发，直接置 false 会造成闪烁
 * （与上传面板同款修复，R3 只修了面板这处漏了搜索框）。
 */
function onSearchDragLeave(e: DragEvent) {
  const next = e.relatedTarget as Node | null
  if (next && (e.currentTarget as HTMLElement).contains(next)) return
  dragActive.value = false
}

function onPaste(e: ClipboardEvent) {
  // 上传面板打开时让粘贴专供上传队列，避免同一张截图
  // 同时触发 AI 以图搜图把列表替换掉（两个全局监听都会收到事件）
  if (uploadOpen.value) return
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

/** 是否已全选当前可见项 */
const allSelected = computed(
  () =>
    visibleItems.value.length > 0 &&
    selectedIds.value.length >= visibleItems.value.length,
)

/** 全选/取消全选已加载项：批量下载、加标签时不必逐个点 */
function toggleSelectAll() {
  if (allSelected.value) {
    clearSelection()
  } else {
    selectedIds.value = visibleItems.value.map((i) => i.id)
  }
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

/**
 * 应用筛选后统一刷新（标签切换等由面板触发）。
 *
 * 筛选结果是一份全新的列表，必须回到顶部：
 * 否则用户停在旧列表底部时，新列表更短会落在空白区，
 * 而虚拟化只渲染可视区，看起来像「筛选后什么都没了」。
 * 同时清空批量选择，避免对已被筛掉的条目执行操作。
 */
function applyAndRefresh() {
  clearScrollAnchor()
  clearSelection()
  window.scrollTo({ top: 0, behavior: 'auto' })
  store.refresh()
}

/** 只看喜欢：过滤的是已加载列表，切换后同样回到顶部 */
function toggleOnlyLiked() {
  onlyLiked.value = !onlyLiked.value
  // 进入「只看喜欢」后，此前选中的未喜欢项已不可见，
  // 继续留在选择里会让批量操作作用于看不见的资产
  if (onlyLiked.value) {
    selectedIds.value = selectedIds.value.filter((id) => likedIds.value.includes(id))
  }
  window.scrollTo({ top: 0, behavior: 'auto' })
}

/**
 * 打开灯箱。
 *
 * 不使用 View Transitions：灯箱是 `<dialog>`，处于浏览器 top layer，
 * 与共享元素快照机制不兼容（实测报 "Transition was aborted because of
 * invalid state"）。改由灯箱自身的进入动画承担过渡，功能一致且无报错。
 */
function openLightbox(filteredIndex: number) {
  // 进灯箱前记录锚点（D-17）：返回列表时按资产定位，而非纯像素
  const anchor = sampleAnchor()
  if (anchor) saveScrollAnchor(anchor)
  // index 来自渲染列表（可能被「只看喜欢」过滤），
  // 需换算回 store 索引，否则灯箱会打开错误的资产。
  const target = visibleItems.value[filteredIndex]
  const realIndex = target ? store.items.findIndex((i) => i.id === target.id) : -1
  if (realIndex < 0) return
  store.openLightbox(realIndex)
  recordView(filteredIndex)
  track('view', { itemId: target!.id })
}

/** 记录最近浏览（C-15）；只看不发请求，成本可忽略 */
function recordView(index: number) {
  const it = visibleItems.value[index]
  if (!it) return
  pushRecent({ id: it.id, title: it.title || it.name, kind: it.kind })
}

/** 喜欢/取消喜欢（C-15）：乐观更新，失败回滚 */
async function toggleLike(id: string) {
  const liked = !likedIds.value.includes(id)
  const before = [...likedIds.value]
  likedIds.value = liked ? [...before, id] : before.filter((x) => x !== id)
  try {
    const res = await fetch('/api/like', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: id, liked }),
    })
    if (!res.ok) throw new Error()
  } catch {
    likedIds.value = before
    toast.error(t('like.failed'))
  }
}

async function loadLikes() {
  try {
    const res = await fetch('/api/likes')
    if (!res.ok) return
    const data = (await res.json()) as { ids: string[] }
    likedIds.value = data.ids ?? []
  } catch {
    likedIds.value = []
  }
}

/** 只看已喜欢：在已加载列表上过滤，避免为一枚开关新建查询参数 */
const visibleItems = computed(() =>
  onlyLiked.value
    ? store.items.filter((i) => likedIds.value.includes(i.id))
    : store.items,
)

/** 当前灯箱项在「可见列表」中的位置（只看喜欢时与 store 索引不同） */
const visibleIndex = computed(() => {
  const cur = store.currentItem
  return cur ? visibleItems.value.findIndex((i) => i.id === cur.id) : -1
})
const visibleHasPrev = computed(() => visibleIndex.value > 0)
const visibleHasNext = computed(
  () => visibleIndex.value >= 0 && visibleIndex.value < visibleItems.value.length - 1,
)

/**
 * 灯箱在「可见列表」内前后切换。
 *
 * 只看喜欢时若直接用 store.stepLightbox，会把灯箱带到一条
 * 未喜欢的资产上，与当前列表不符；这里先换算成可见位置。
 */
function stepVisible(delta: number) {
  const next = visibleIndex.value + delta
  const target = visibleItems.value[next]
  if (!target) return
  const real = store.items.findIndex((i) => i.id === target.id)
  if (real >= 0) store.openLightbox(real)
}

/** 连播回到「可见列表」首项（与 stepVisible 同口径） */
function stepVisibleToFirst() {
  const first = visibleItems.value[0]
  if (!first) return
  const real = store.items.findIndex((i) => i.id === first.id)
  if (real >= 0) store.openLightbox(real)
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

/** 灯箱内点标签 → 按标签筛选（与色板筛选对称） */
function onFilterTag(tag: string) {
  if (!filters.tags.includes(tag)) filters.toggleTag(tag)
  store.refresh()
}

// 从 URL 还原筛选，然后加载
onMounted(async () => {
  filters.fromUrlQuery(route.query as Record<string, string>)
  // URL 未显式指定 view 时，读取用户上次偏好的视图模式
  if (!route.query.view) {
    try {
      const savedView = localStorage.getItem('medialib.view') as ViewMode | null
      if (savedView === 'masonry' || savedView === 'grid' || savedView === 'list') {
        filters.setView(savedView)
      }
    } catch {
      // 忽略
    }
  }
  // 首页空库引导：带 upload=1 时直接打开上传面板
  if (route.query.upload === '1') uploadOpen.value = true
  searchInput.value = filters.q
  await store.refresh()
  // 首次渲染后还原上次锚点（D-17 验收 3）
  restoreScrollAnchor(readScrollAnchor(), store.items)
  // 探测 AI 能力（B-08）：失败静默，入口隐藏即可
  void loadAiStatus()
  void loadCollections()
  void loadLikes()
  window.addEventListener('paste', onPaste)
  // 订阅任务事件：异步处理完成后自动补全卡片（缩略图/元数据）
  if (typeof EventSource !== 'undefined') {
    es = new EventSource('/api/jobs/stream')
    es.addEventListener('media_ready', onMediaReady as EventListener)
    es.addEventListener('library_updated', scheduleLibraryRefresh)
  }
  // 旧分享链接 /app/a/{slug}-{shortId} 兼容路由：解析短 ID 后打开对应灯箱
  if (route.name === 'asset') {
    void resolveAssetFromSlug(String(route.params.slug ?? ''))
  }
})

/** 解析语义链接中的短 ID 并打开灯箱（E-19 的 SPA 兼容路径） */
async function resolveAssetFromSlug(slug: string) {
  const last = slug.split('-').pop() ?? ''
  if (!/^[0-9a-f]{6,32}$/.test(last)) return
  try {
    const res = await fetch(`/api/resolve/${encodeURIComponent(last)}`)
    if (!res.ok) return
    const it = (await res.json()) as { id: string }
    const idx = store.items.findIndex((x) => x.id === it.id)
    if (idx >= 0) {
      store.openLightbox(idx)
      return
    }
    // 不在当前筛选结果里：清空筛选重载后再开
    filters.reset()
    await store.refresh()
    const j = store.items.findIndex((x) => x.id === it.id)
    if (j >= 0) store.openLightbox(j)
  } catch {
    // 解析失败静默：落到普通浏览页即可
  }
}

// 组合式函数必须在 setup 同步作用域调用：
// 它们内部注册的 onMounted 只有在 setup 期间才会被执行（实测踩到，
// 放在 onMounted 回调里注册的生命周期钩子永远不会触发）。
useEventFlush()
useImpressionTracker(computed(() => store.items.map((i) => i.id)))

onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') return
  pageObserver = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting && store.hasMore && !store.loading) void store.load()
    },
    // 提前两屏开始加载，滚动时几乎无等待
    { rootMargin: '200% 0px' },
  )
  if (sentinel.value) pageObserver.observe(sentinel.value)
})

onUnmounted(() => {
  window.removeEventListener('paste', onPaste)
  pageObserver?.disconnect()
  es?.close()
  if (sseRefreshTimer !== undefined) window.clearTimeout(sseRefreshTimer)
  // 搜索防抖定时器一并清掉：卸载后触发只会发出无意义的请求
  window.clearTimeout(debounceTimer)
})

// ---------- 任务事件流（SSE） ----------
// 上传走快速路径（D-16）：先落盘返回，缩略图/元数据由后台任务补齐。
// 不订阅事件的话，卡片会一直停留在「加载失败」占位直到手动刷新。
let es: EventSource | null = null
let sseRefreshTimer: number | undefined

/** 单卡更新：media_ready 只带 item_id，替换对应卡片即可，不打断浏览位置 */
function onMediaReady(e: MessageEvent) {
  try {
    const data = JSON.parse(e.data) as { item_id?: string }
    if (data.item_id) void store.updateItem(data.item_id)
  } catch {
    // 事件数据异常时忽略
  }
}

/** 全量刷新（入库/采集等批量变化）：节流合并，且灯箱打开时跳过避免资产错位 */
function scheduleLibraryRefresh() {
  if (sseRefreshTimer !== undefined) return
  sseRefreshTimer = window.setTimeout(() => {
    sseRefreshTimer = undefined
    if (store.currentItem) return
    void store.refresh()
  }, 1500)
}

// 筛选变化时刷新（面板内直接改 store 的路径）
watch(
  () => [
    filters.tags.join(','),
    filters.excludeTags.join(','),
    filters.kind,
    filters.orientation,
    filters.platform,
    filters.ext,
    filters.sizeClass,
    // color 必须监听：仅用色彩筛选时点「清空」，其余值不变，
    // 缺了它 watch 不触发，列表会停留在旧的色彩筛选结果
    filters.color,
  ],
  () => {
    applyAndRefresh()
  },
)

// 筛选状态被外部路径清空（分面面板/空态的「清空」按钮）时，
// 同步搜索框显示，避免输入框残留旧词而实际已无筛选
watch(
  () => filters.q,
  (v) => {
    if (v !== searchInput.value) searchInput.value = v
  },
)

// 浏览器后退/前进：URL query 变化时还原筛选并重载。
// 组件内的 syncUrl 用 replace 更新 query，同样会触发本 watch，
// 通过「还原后状态与当前一致则跳过」防自更新循环。
watch(
  () => route.query,
  (q) => {
    const incoming = JSON.stringify(sortQueryKeys(q as Record<string, unknown>))
    const current = JSON.stringify(sortQueryKeys(filters.toUrlQuery()))
    if (incoming === current) return
    filters.fromUrlQuery(q as Record<string, string>)
    searchInput.value = filters.q
    clearScrollAnchor()
    void store.refresh()
  },
)

/** query 对象按 key 排序后拷贝，保证 stringify 比较稳定 */
function sortQueryKeys(q: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const k of Object.keys(q).sort()) out[k] = q[k]
  return out
}

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
        @dragleave.prevent="onSearchDragLeave"
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
        <!-- 有内容时提供一键清除：直接清队列/状态/刷新一次，
             走 onSearchInput 会再排一个 300ms 防抖造成双重请求 -->
        <button
          v-if="searchInput"
          type="button"
          class="browse__search-clear"
          :aria-label="t('browse.clearSearch')"
          @click="clearSearch"
        >
          ×
        </button>
        <!-- AI 检索未启用时只给说明，不显示入口（B-08 验收 4）。
             有搜索词时隐藏右侧标识，避免与「清除」按钮在同一位置重叠。 -->
        <span
          v-if="!searchInput && aiStatus && !aiStatus.available"
          class="browse__ai-off"
          :title="aiStatus.hint"
        >
          {{ t('ai.disabled') }}
        </span>
        <span
          v-else-if="!searchInput && aiStatus?.available"
          class="browse__ai-on"
          :title="t('ai.byImageHint')"
        >
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

      <div class="browse__views" role="group" :aria-label="t('view.label')">
        <button
          v-for="v in VIEW_MODES"
          :key="v.key"
          type="button"
          :class="['view-btn', { 'view-btn--on': filters.view === v.key }]"
          :aria-pressed="filters.view === v.key"
          :aria-label="t(`view.${v.key}`)"
          :title="t(`view.${v.key}`)"
          @click="changeView(v.key)"
        >
          <span aria-hidden="true">{{ v.icon }}</span>
        </button>
      </div>

      <MLButton
        variant="quiet"
        :aria-pressed="onlyLiked"
        @click="toggleOnlyLiked"
      >
        {{ onlyLiked ? t('like.showAll') : t('like.onlyLiked') }}<template v-if="likedIds.length"> {{ likedIds.length }}</template>
      </MLButton>
      <MLButton variant="quiet" @click="uploadOpen = true">{{ t('upload.open') }}</MLButton>
      <MLButton
        variant="quiet"
        :aria-pressed="selectMode"
        @click="toggleSelectMode"
      >
        {{ selectMode ? t('batch.exitSelect') : t('batch.select') }}
      </MLButton>
      <MLButton
        v-if="selectMode && visibleItems.length"
        variant="quiet"
        @click="toggleSelectAll"
      >
        {{ allSelected ? t('batch.unselectAll') : t('batch.selectAll') }}
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
      <MLChip
        v-if="filters.sizeClass"
        :label="t(SIZE_KEY[filters.sizeClass] ?? 'facet.sizeClass')"
        removable
        active
        @remove="filters.setSizeClass(''); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.ext"
        :label="filters.ext.replace(/^\./, '').toUpperCase()"
        removable
        active
        @remove="filters.setExt(''); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.platform"
        :label="filters.platform"
        removable
        active
        @remove="filters.setPlatform(''); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.color"
        :label="t('browse.colorFilter', { value: filters.color })"
        removable
        active
        @remove="filters.setColor(''); applyAndRefresh()"
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
        <!-- 筛选切换中：给明确的加载态，避免误以为无响应 -->
        <div v-if="store.loading && !store.items.length" class="browse__loading" role="status" aria-live="polite">
          <span class="browse__spinner" aria-hidden="true" />
          <span>{{ t('site.loading') }}</span>
        </div>

        <!-- 请求失败与「真的没有内容」是两件事：前者要给重试入口，
             否则用户会以为库里没东西 -->
        <div v-if="store.error && !store.items.length" class="browse__empty">
          <h2>{{ t('browse.errorTitle') }}</h2>
          <p class="muted">{{ store.error }}</p>
          <MLButton variant="ghost" @click="store.refresh()">
            {{ t('common.retry') }}
          </MLButton>
        </div>

        <div v-else-if="store.isEmpty" class="browse__empty">
          <h2>{{ t('browse.emptyTitle') }}</h2>
          <p class="muted">
            {{ emptyHint }}
          </p>
          <MLButton
            v-if="filters.hasFilters"
            variant="ghost"
            @click="filters.reset(); applyAndRefresh()"
          >
            {{ t('browse.clearAll') }}
          </MLButton>
        </div>

        <!-- 只看喜欢时若一条都没有，给出可撤销的空态，而非直接空白 -->
        <div v-else-if="!visibleItems.length" class="browse__empty">
          <h2>{{ t('like.empty') }}</h2>
          <MLButton variant="ghost" @click="onlyLiked = false">
            {{ t('like.showAll') }}
          </MLButton>
        </div>

        <MasonryGrid
          v-else
          :items="visibleItems"
          :mode="filters.view"
          :selectable="selectMode"
          :selected-ids="selectedIds"
          :liked-ids="likedIds"
          @open="openLightbox"
          @toggle="toggleSelect"
          @toggle-like="toggleLike"
        />

        <!-- 分页哨兵：进入视口即自动加载；同时保留手动按钮作为兜底 -->
        <div ref="sentinel" class="browse__sentinel" aria-hidden="true" />
        <div v-if="store.hasMore && !pageAutoLoad" class="browse__more">
          <MLButton variant="ghost" :disabled="store.loading" @click="store.load()">
            {{ store.loading ? t('site.loading') : t('browse.loadMore') }}
          </MLButton>
        </div>
      </div>
    </div>

    <LightboxViewer
      v-if="store.currentItem"
      :item="store.currentItem"
      :has-prev="visibleHasPrev"
      :has-next="visibleHasNext"
      :candidates="compareCandidates"
      :liked="likedIds.includes(store.currentItem.id)"
      @close="onCloseLightbox"
      @prev="stepVisible(-1)"
      @next="stepVisible(1)"
      @slideshow-end="stepVisibleToFirst()"
      @filter-color="onFilterColor"
      @filter-tag="onFilterTag"
      @toggle-like="toggleLike"
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
  gap: var(--p-space-3);
  flex-wrap: wrap;
  padding-bottom: var(--p-space-4);
}

/* 窄屏：工具项按行排布，搜索框独占一行，避免挤压成极窄的输入条 */
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
.browse__search-clear {
  position: absolute;
  right: var(--p-space-2);
  top: 50%;
  transform: translateY(-50%);
  min-width: 24px;
  min-height: 24px;
  border-radius: var(--p-radius-full);
  color: var(--ink-muted);
  font-size: 1rem;
  line-height: 1;
}

.browse__search-clear:hover {
  background: var(--surface-sunken);
}

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
  /* 右侧预留清除按钮/AI 标识的位置，长搜索词不会压在按钮下面 */
  padding: var(--p-space-2) var(--p-space-7) var(--p-space-2) var(--p-space-7);
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

.browse__views {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-md);
  padding: 2px;
  gap: 2px;
  background: var(--surface);
}

.view-btn {
  min-width: 28px;
  min-height: 26px;
  border-radius: var(--p-radius-sm);
  color: var(--ink-muted);
  font-size: 0.875rem;
  display: grid;
  place-items: center;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.view-btn:hover {
  color: var(--ink);
  background: var(--surface-hover);
}

.view-btn--on {
  background: var(--accent-soft);
  color: var(--accent-hover);
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

.browse__loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--p-space-2);
  padding: var(--p-space-8) var(--p-space-4);
  color: var(--ink-muted);
  font-size: var(--p-step--1);
}

.browse__spinner {
  width: 14px;
  height: 14px;
  border-radius: var(--p-radius-full);
  border: 2px solid var(--rule-strong);
  border-top-color: var(--accent);
  animation: browse-spin 700ms linear infinite;
}

@keyframes browse-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .browse__spinner {
    animation: none;
    border-top-color: var(--accent);
  }
}

.browse__sentinel {
  height: 1px;
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

@media (max-width: 720px) {
  .browse__toolbar {
    gap: var(--p-space-2);
  }
  .browse__search {
    order: -1;
    /* flex:1 + min-width 会阻止换行铺满，窄屏必须显式给 basis */
    flex: 1 1 100%;
    min-width: 0;
  }
  .browse__sorts {
    overflow-x: auto;
    flex-wrap: nowrap;
    max-width: 100%;
    padding-bottom: 2px;
  }
}

</style>
