<script setup lang="ts">
/**
 * 主页：单页沉浸式图片墙 + 按需展开分面检索
 *
 * 设计取舍：
 *   - 合并原「图墙」与「浏览」双页签，消除重复导航与跳页割裂感
 *   - 搜索框通过 Teleport 融入顶栏居中位置（独立挂载测试时自动回退内联）
 *   - 默认收起左侧分面栏，全屏铺开瀑布流并将人工精选置顶；点击「筛选」按需展开侧栏
 *   - URL 即状态：所有筛选、排序、视图参数实时同步 query，兼容旧 /browse?... 跳转与 /a/:slug 短链
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaStore } from '@/stores/media'
import { useFilterStore } from '@/stores/filters'
import { useToast } from '@/composables/useToast'
import { copyText } from '@/composables/useClipboard'
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
const router = useRouter()
const { t } = useI18n()

/** 顶栏居中插槽是否就绪（独立挂载单测无 AppShell 时自动禁用 Teleport） */
const headerSlotReady = ref(false)

/** 分面筛选侧栏：桌面与移动端均默认收起，保持首屏全宽沉浸看图 */
const facetsOpen = ref(false)

/** 滚动后工具条轻微降透，把视觉焦点让给图片；深滚时显示回到顶部按钮 */
const toolbarDim = ref(false)
const showBackTop = ref(false)

// ---------- 搜索与历史 ----------
const searchInput = ref(filters.q)
const searchInputEl = ref<HTMLInputElement | null>(null)
const aiImageInputEl = ref<HTMLInputElement | null>(null)
const SEARCH_HISTORY_KEY = 'medialib.searchHistory'
const searchFocused = ref(false)
const searchHistory = ref<string[]>((() => {
  try {
    const raw = localStorage.getItem(SEARCH_HISTORY_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string').slice(0, 6) : []
  } catch {
    return []
  }
})())

function pushSearchHistory(term: string) {
  const clean = term.trim()
  if (!clean) return
  const next = [clean, ...searchHistory.value.filter((x) => x !== clean)].slice(0, 6)
  searchHistory.value = next
  try {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(next))
  } catch {
    // 隐私模式忽略
  }
}

function clearSearchHistory() {
  searchHistory.value = []
  try {
    localStorage.removeItem(SEARCH_HISTORY_KEY)
  } catch {
    // 忽略
  }
}

function removeSearchHistory(term: string) {
  const next = searchHistory.value.filter((x) => x !== term)
  searchHistory.value = next
  try {
    if (next.length) localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(next))
    else localStorage.removeItem(SEARCH_HISTORY_KEY)
  } catch {
    // 忽略
  }
}

function onSearchKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    searchFocused.value = false
    searchInputEl.value?.blur()
  }
}

let debounceTimer: number | undefined

function onSearchInput(value: string) {
  searchInput.value = value
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(async () => {
    filters.setQ(value)
    await applyAndRefresh()
    if (value.trim()) {
      pushSearchHistory(value)
      track('search', { meta: { q: value.trim(), result_count: store.total } })
    }
  }, 300)
}

function applyHistoryTerm(term: string) {
  window.clearTimeout(debounceTimer)
  searchInput.value = term
  searchFocused.value = false
  filters.setQ(term)
  void applyAndRefresh()
}

function clearSearch() {
  window.clearTimeout(debounceTimer)
  searchInput.value = ''
  filters.setQ('')
  void applyAndRefresh()
}

function onSearchFocus() {
  searchFocused.value = true
}

function onSearchBlur() {
  window.setTimeout(() => {
    searchFocused.value = false
  }, 150)
}

// ---------- AI 以图搜图（B-08） ----------
const { status: aiStatus, load: loadAiStatus } = useAiStatus()
const dragActive = ref(false)
const aiBusy = ref(false)
const aiSearchActive = ref(false)

function onPickAiFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file && file.type.startsWith('image/')) void searchByImage(file)
}

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
    aiSearchActive.value = true
    clearScrollAnchor()
    clearSelection()
    window.scrollTo({ top: 0, behavior: 'auto' })
  } finally {
    aiBusy.value = false
  }
}

function exitAiSearch() {
  aiSearchActive.value = false
  void applyAndRefresh()
}

function onDropSearchImage(e: DragEvent) {
  dragActive.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file && file.type.startsWith('image/')) void searchByImage(file)
}

function onSearchDragLeave(e: DragEvent) {
  const next = e.relatedTarget as Node | null
  if (next && (e.currentTarget as HTMLElement).contains(next)) return
  dragActive.value = false
}

function onPaste(e: ClipboardEvent) {
  if (uploadOpen.value) return
  if (!aiStatus.value?.available) return
  const file = Array.from(e.clipboardData?.files ?? [])[0]
  if (file && file.type.startsWith('image/')) void searchByImage(file)
}

// ---------- 上传与全页拖拽、批量操作 ----------
const uploadOpen = ref(false)
const uploadPanelRef = ref<InstanceType<typeof UploadPanel> | null>(null)
const pageDragActive = ref(false)
const selectMode = ref(false)
const selectedIds = ref<string[]>([])
const lastSelectedId = ref<string | null>(null)

function onPageDragOver(e: DragEvent) {
  if (uploadOpen.value || store.currentItem) return
  if (e.dataTransfer?.types?.includes('Files')) {
    pageDragActive.value = true
  }
}

function onPageDragLeave(e: DragEvent) {
  const next = e.relatedTarget as Node | null
  if (next && (e.currentTarget as HTMLElement).contains(next)) return
  pageDragActive.value = false
}

function onPageDrop(e: DragEvent) {
  pageDragActive.value = false
  if (uploadOpen.value || store.currentItem) return
  const files = e.dataTransfer?.files
  if (!files?.length) return
  uploadOpen.value = true
  void nextTick(() => {
    uploadPanelRef.value?.addFiles(files)
  })
}

function toggleSelect(id: string, shiftKey = false) {
  if (shiftKey && lastSelectedId.value && lastSelectedId.value !== id) {
    const ids = visibleItems.value.map((x) => x.id)
    const a = ids.indexOf(lastSelectedId.value)
    const b = ids.indexOf(id)
    if (a >= 0 && b >= 0) {
      const [lo, hi] = a < b ? [a, b] : [b, a]
      const targetState = !selectedIds.value.includes(id)
      const set = new Set(selectedIds.value)
      for (let k = lo; k <= hi; k++) {
        if (targetState) set.add(ids[k])
        else set.delete(ids[k])
      }
      selectedIds.value = Array.from(set)
      lastSelectedId.value = id
      return
    }
  }
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
  lastSelectedId.value = id
}

function clearSelection() {
  selectedIds.value = []
  lastSelectedId.value = null
}

const allSelected = computed(
  () =>
    visibleItems.value.length > 0 &&
    selectedIds.value.length >= visibleItems.value.length,
)

/** 提取当前已选条目实际包含的标签集合（按频次排序），供批量移除标签直接点选 */
const selectedItemTags = computed(() => {
  if (!selectedIds.value.length) return []
  const picked = new Set(selectedIds.value)
  const freq = new Map<string, number>()
  for (const it of store.items) {
    if (!picked.has(it.id)) continue
    for (const tag of it.tags ?? []) {
      if (tag) freq.set(tag, (freq.get(tag) ?? 0) + 1)
    }
  }
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([tag]) => tag)
    .slice(0, 16)
})

function toggleSelectAll() {
  if (allSelected.value) clearSelection()
  else selectedIds.value = visibleItems.value.map((i) => i.id)
}

function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) clearSelection()
}

async function onUploaded() {
  await refreshWithFeatured()
}

function onBatchDone() {
  void refreshWithFeatured()
  clearSelection()
}

// ---------- 视图、密度、排序与快筛 ----------
const SORT_KEYS: SortKey[] = ['newest', 'oldest', 'pixels', 'size', 'views', 'random']

const VIEW_MODES: { key: ViewMode; icon: string }[] = [
  { key: 'masonry', icon: '⊞' },
  { key: 'grid', icon: '⊟' },
  { key: 'list', icon: '☰' },
]

type Density = 'compact' | 'comfortable' | 'spacious'
const DENSITY_MAP: Record<Density, { masonry: number; grid: number; short: string }> = {
  compact: { masonry: 210, grid: 170, short: 'S' },
  comfortable: { masonry: 272, grid: 220, short: 'M' },
  spacious: { masonry: 360, grid: 290, short: 'L' },
}
const DENSITY_KEYS: Density[] = ['compact', 'comfortable', 'spacious']
const density = ref<Density>((() => {
  try {
    const v = localStorage.getItem('medialib.density')
    return v === 'compact' || v === 'comfortable' || v === 'spacious' ? v : 'comfortable'
  } catch {
    return 'comfortable'
  }
})())

function changeDensity(d: Density) {
  const anchor = sampleAnchor()
  density.value = d
  try {
    localStorage.setItem('medialib.density', d)
  } catch {
    // 隐私模式静默忽略
  }
  if (anchor) void nextTick(() => restoreScrollAnchor(anchor, store.items))
}

function changeView(mode: ViewMode) {
  const anchor = sampleAnchor()
  filters.setView(mode)
  try {
    localStorage.setItem('medialib.view', mode)
  } catch {
    // 忽略
  }
  if (anchor) void nextTick(() => restoreScrollAnchor(anchor, store.items))
}

function changeSort(value: SortKey) {
  filters.setSort(value)
  void applyAndRefresh()
}

function onSortSelect(e: Event) {
  changeSort((e.target as HTMLSelectElement).value as SortKey)
}

/** 随机漫步：未开启时切到随机，已开启时再次点击立即换一批 */
function triggerShuffle() {
  if (filters.sort !== 'random') {
    filters.setSort('random')
  }
  void applyAndRefresh()
}

function setQuickKind(kind: '' | 'image' | 'video') {
  if (filters.kind === kind) return
  filters.setKind(kind)
}

// ---------- 列表刷新与精选置顶协调 ----------
let refreshSeq = 0
let suppressFilterWatch = false

/** 无筛选且默认按最新排序时，保持人工精选置顶，延续原图墙策展体验 */
function shouldPromoteFeatured(): boolean {
  return !filters.hasFilters && filters.sort === 'newest' && !onlyLiked.value && !aiSearchActive.value
}

async function refreshWithFeatured() {
  const seq = ++refreshSeq
  await store.refresh()
  if (seq === refreshSeq && shouldPromoteFeatured()) {
    await store.promoteFeatured()
  }
}

async function applyAndRefresh() {
  aiSearchActive.value = false
  clearScrollAnchor()
  clearSelection()
  window.scrollTo({ top: 0, behavior: 'auto' })
  await refreshWithFeatured()
}

function clearAllFilters() {
  window.clearTimeout(debounceTimer)
  suppressFilterWatch = true
  searchInput.value = ''
  filters.reset()
  suppressFilterWatch = false
  void applyAndRefresh()
}

async function copyFilterLink() {
  const ok = await copyText(window.location.href)
  if (ok) toast.success(t('browse.filterLinkCopied'))
  else toast.error(t('lightbox.copyFailed'))
}

// ---------- 喜欢与画板 ----------
const collections = ref<Collection[]>([])
const likedIds = ref<string[]>([])
const onlyLiked = ref(false)

const activeCollectionName = computed(() => {
  if (filters.collectionId === null) return ''
  return collections.value.find((c) => c.id === filters.collectionId)?.name || `#${filters.collectionId}`
})

async function loadCollections() {
  try {
    collections.value = await api.collections()
  } catch {
    collections.value = []
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

function toggleOnlyLiked() {
  onlyLiked.value = !onlyLiked.value
  if (onlyLiked.value) {
    selectedIds.value = selectedIds.value.filter((id) => likedIds.value.includes(id))
  }
  window.scrollTo({ top: 0, behavior: 'auto' })
}

const visibleItems = computed(() =>
  onlyLiked.value
    ? store.items.filter((i) => likedIds.value.includes(i.id))
    : store.items,
)

// ---------- 灯箱与可见列表定位 ----------
const visibleIndex = computed(() => {
  const cur = store.currentItem
  return cur ? visibleItems.value.findIndex((i) => i.id === cur.id) : -1
})
const visibleHasPrev = computed(() => visibleIndex.value > 0)
const visibleHasNext = computed(
  () => visibleIndex.value >= 0 && visibleIndex.value < visibleItems.value.length - 1,
)

function openLightbox(filteredIndex: number) {
  const anchor = sampleAnchor()
  if (anchor) saveScrollAnchor(anchor)
  const target = visibleItems.value[filteredIndex]
  const realIndex = target ? store.items.findIndex((i) => i.id === target.id) : -1
  if (realIndex < 0 || !target) return
  store.openLightbox(realIndex)
  pushRecent({ id: target.id, title: target.title || target.name, kind: target.kind })
  track('view', { itemId: target.id })
}

function stepVisible(delta: number) {
  const next = visibleIndex.value + delta
  const target = visibleItems.value[next]
  if (!target) return
  const real = store.items.findIndex((i) => i.id === target.id)
  if (real >= 0) {
    store.openLightbox(real)
    pushRecent({ id: target.id, title: target.title || target.name, kind: target.kind })
  }
  if (delta > 0 && next >= visibleItems.value.length - 4 && store.hasMore && !store.loading) {
    void store.load()
  }
}

function stepVisibleToFirst() {
  const first = visibleItems.value[0]
  if (!first) return
  const real = store.items.findIndex((i) => i.id === first.id)
  if (real >= 0) store.openLightbox(real)
}

function onCloseLightbox() {
  store.closeLightbox()
  if (route.name === 'asset') {
    void router.replace({ name: 'home', query: filters.toUrlQuery() })
  }
  restoreScrollAnchor(readScrollAnchor(), store.items)
}

const compareCandidates = computed(() => {
  const list = visibleItems.value
  const idx = visibleIndex.value >= 0 ? visibleIndex.value : store.lightboxIndex
  const start = Math.max(0, idx - 8)
  return list.slice(start, start + 20)
})

function onSelectSimilar(sim: { id: string; slug?: string }) {
  const idx = store.items.findIndex((x) => x.id === sim.id)
  if (idx >= 0) {
    store.openLightbox(idx)
    const target = store.items[idx]
    if (target) pushRecent({ id: target.id, title: target.title || target.name, kind: target.kind })
    return
  }
  store.closeLightbox()
  void router.push(`/a/${sim.slug ? `${sim.slug}-` : 'asset-'}${sim.id.slice(0, 8)}`)
}

function onFilterColor(color: string) {
  filters.setColor(color)
}

function onFilterTag(tag: string) {
  if (!filters.tags.includes(tag)) filters.toggleTag(tag)
}

// ---------- 文案与常量映射 ----------
const ORIENTATION_KEY: Record<string, string> = {
  landscape: 'facet.landscape',
  portrait: 'facet.portrait',
  square: 'facet.square',
}

const SIZE_KEY: Record<string, string> = {
  '4k': 'facet.size4k',
  hd: 'facet.sizeHd',
  sd: 'facet.sizeSd',
  small: 'facet.sizeSmall',
}

const emptyHint = computed(() => {
  if (filters.q.trim()) return t('browse.emptyHintSearch', { q: filters.q.trim() })
  if (filters.hasFilters) return t('browse.emptyHintFilter')
  return t('browse.emptyHintNoFilter')
})

const SKELETON_RATIOS = [1.2, 0.8, 1.0, 1.35, 0.88, 1.15, 0.75, 1.28, 0.95, 1.18]

// ---------- 滚动、快捷键与顶栏联动 ----------
const pageAutoLoad = typeof IntersectionObserver !== 'undefined'
const sentinel = ref<HTMLElement | null>(null)
let pageObserver: IntersectionObserver | null = null

function onScroll() {
  const y = window.scrollY
  toolbarDim.value = y > 120
  showBackTop.value = y > 600
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function focusSearchBar() {
  window.dispatchEvent(new CustomEvent('mlib:reveal-header'))
  void nextTick(() => searchInputEl.value?.focus())
}

function onKeydown(e: KeyboardEvent) {
  if (store.currentItem || uploadOpen.value) return
  const el = e.target as HTMLElement | null
  const tag = el?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || Boolean(el?.isContentEditable)
  if (e.key === '/' && !typing && !e.isComposing) {
    e.preventDefault()
    focusSearchBar()
    return
  }
  if (e.key === 'Escape' && !typing) {
    if (selectMode.value) {
      toggleSelectMode()
    } else if (facetsOpen.value) {
      facetsOpen.value = false
    }
  }
}

/** 点击左上角品牌标识时重置筛选并回到初始精选图墙 */
function onBrandResetHome() {
  window.clearTimeout(debounceTimer)
  const hadExtraState =
    filters.hasFilters ||
    filters.sort !== 'newest' ||
    onlyLiked.value ||
    aiSearchActive.value ||
    selectMode.value
  suppressFilterWatch = true
  searchInput.value = ''
  onlyLiked.value = false
  aiSearchActive.value = false
  selectMode.value = false
  clearSelection()
  filters.reset()
  if (filters.sort !== 'newest') filters.setSort('newest')
  suppressFilterWatch = false
  if (hadExtraState) {
    void applyAndRefresh()
  } else if (window.scrollY > 0) {
    scrollToTop()
  }
}

/** 解析语义短链 /a/{slug}-{shortId} 并打开对应资产灯箱 */
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
    suppressFilterWatch = true
    filters.reset()
    suppressFilterWatch = false
    await refreshWithFeatured()
    const j = store.items.findIndex((x) => x.id === it.id)
    if (j >= 0) store.openLightbox(j)
  } catch {
    // 解析失败静默回退普通图墙
  }
}

// ---------- 任务事件流（SSE） ----------
let es: EventSource | null = null
let sseRefreshTimer: number | undefined

function onMediaReady(e: MessageEvent) {
  try {
    const data = JSON.parse(e.data) as { item_id?: string }
    if (data.item_id) void store.updateItem(data.item_id)
  } catch {
    // 忽略异常事件负载
  }
}

function scheduleLibraryRefresh() {
  if (sseRefreshTimer !== undefined) return
  sseRefreshTimer = window.setTimeout(() => {
    sseRefreshTimer = undefined
    if (store.currentItem) return
    void refreshWithFeatured()
  }, 1500)
}

// 埋点上报必须在 setup 同步阶段注册生命周期
useEventFlush()
useImpressionTracker(computed(() => store.items.map((i) => i.id)))

onMounted(async () => {
  headerSlotReady.value = Boolean(document.getElementById('site-header-center'))

  suppressFilterWatch = true
  filters.fromUrlQuery(route.query as Record<string, string>)
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
  searchInput.value = filters.q
  suppressFilterWatch = false

  if (route.query.upload === '1') uploadOpen.value = true
  if (route.query.focus === 'search') {
    window.setTimeout(() => focusSearchBar(), 0)
  }

  await refreshWithFeatured()
  restoreScrollAnchor(readScrollAnchor(), store.items)

  void loadAiStatus()
  void loadCollections()
  void loadLikes()

  window.addEventListener('paste', onPaste)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('mlib:reset-home', onBrandResetHome)

  if (typeof IntersectionObserver !== 'undefined') {
    pageObserver = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && store.hasMore && !store.loading) {
          void store.load()
        }
      },
      { rootMargin: '200% 0px' },
    )
    if (sentinel.value) pageObserver.observe(sentinel.value)
  }

  if (typeof EventSource !== 'undefined') {
    es = new EventSource('/api/jobs/stream')
    es.addEventListener('media_ready', onMediaReady as EventListener)
    es.addEventListener('library_updated', scheduleLibraryRefresh)
  }

  if (route.name === 'asset' && route.params.slug) {
    void resolveAssetFromSlug(String(route.params.slug))
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('paste', onPaste)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('mlib:reset-home', onBrandResetHome)
  pageObserver?.disconnect()
  es?.close()
  if (sseRefreshTimer !== undefined) window.clearTimeout(sseRefreshTimer)
  window.clearTimeout(debounceTimer)
})

// 分面条件变化时自动回顶并刷新列表
watch(
  () => [
    filters.tags.join(','),
    filters.excludeTags.join(','),
    filters.kind,
    filters.orientation,
    filters.platform,
    filters.ext,
    filters.sizeClass,
    filters.color,
    filters.collectionId,
  ],
  () => {
    if (suppressFilterWatch) return
    void applyAndRefresh()
  },
)

// 外部清空筛选（例如 FacetPanel 内的「清空」）时同步搜索框输入值
watch(
  () => filters.q,
  (v) => {
    if (v !== searchInput.value) searchInput.value = v
  },
)

// 同一实例内从「最近浏览」抽屉跳转到 /a/:slug 时定位并打开灯箱
watch(
  () => [route.name, route.params.slug] as const,
  ([name, slug]) => {
    if (name === 'asset' && slug) {
      void resolveAssetFromSlug(String(slug))
    }
  },
)

function sortQueryKeys(q: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const k of Object.keys(q).sort()) out[k] = q[k]
  return out
}

// 浏览器前进/后退时按 URL 还原筛选状态
watch(
  () => route.query,
  (q) => {
    if (route.name === 'asset') return
    const incoming = JSON.stringify(sortQueryKeys(q as Record<string, unknown>))
    const current = JSON.stringify(sortQueryKeys(filters.toUrlQuery()))
    if (incoming === current) return
    suppressFilterWatch = true
    filters.fromUrlQuery(q as Record<string, string>)
    searchInput.value = filters.q
    suppressFilterWatch = false
    clearScrollAnchor()
    void refreshWithFeatured()
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
  <div
    class="wall"
    @dragover.prevent="onPageDragOver"
    @dragleave.prevent="onPageDragLeave"
    @drop.prevent="onPageDrop"
  >
    <!-- 全页拖入文件上传遮罩 -->
    <div v-if="pageDragActive" class="wall__drop-overlay" aria-hidden="true">
      <div class="wall__drop-card">
        <span class="wall__drop-plus">＋</span>
        <span>{{ t('browse.dropUploadHint') }}</span>
      </div>
    </div>

    <h1 class="sr-only">{{ t('site.name') }}</h1>

    <!-- 顶栏搜索框：有 AppShell 时挂载到顶栏中央，独立测试时保留在页内 -->
    <Teleport to="#site-header-center" :disabled="!headerSlotReady">
      <div
        :class="[
          'wall-search',
          {
            'wall-search--inline': !headerSlotReady,
            'wall-search--drag': dragActive,
            'wall-search--busy': aiBusy,
          },
        ]"
        @dragover.prevent.stop="aiStatus?.available && ((dragActive = true), (pageDragActive = false))"
        @dragleave.prevent.stop="onSearchDragLeave"
        @drop.prevent.stop="onDropSearchImage"
      >
        <span class="wall-search__icon" aria-hidden="true">⌕</span>
        <input
          ref="searchInputEl"
          :value="searchInput"
          type="search"
          class="wall-search__input"
          :placeholder="dragActive ? t('ai.dropHint') : t('browse.searchPlaceholder')"
          :title="t('browse.searchShortcut')"
          :aria-label="t('browse.searchLabel')"
          @focus="onSearchFocus"
          @blur="onSearchBlur"
          @keydown="onSearchKeydown"
          @input="onSearchInput(($event.target as HTMLInputElement).value)"
        />
        <button
          v-if="searchInput"
          type="button"
          class="wall-search__clear"
          :aria-label="t('browse.clearSearch')"
          @click="clearSearch"
        >
          ×
        </button>
        <span v-if="aiBusy" class="wall-search__ai wall-search__ai--busy">
          {{ t('ai.searching') }}
        </span>
        <button
          v-else-if="!searchInput && aiStatus?.available"
          type="button"
          class="wall-search__ai wall-search__ai--btn"
          :title="`${t('ai.byImageHint')} · ${t('browse.pickImageSearch')}`"
          @click="aiImageInputEl?.click()"
        >
          {{ t('ai.byImage') }}
        </button>
        <kbd v-else-if="!searchInput" class="wall-search__kbd mono" aria-hidden="true">/</kbd>
        <input
          ref="aiImageInputEl"
          type="file"
          accept="image/*"
          tabindex="-1"
          class="sr-only"
          @change="onPickAiFile"
        />

        <!-- 搜索历史下拉 -->
        <div
          v-if="searchFocused && searchHistory.length && !searchInput"
          class="wall-search__history"
          role="listbox"
          :aria-label="t('browse.searchHistory')"
        >
          <div class="wall-search__history-head">
            <span>{{ t('browse.searchHistory') }}</span>
            <button type="button" class="wall-search__history-clear" @mousedown.prevent="clearSearchHistory">
              {{ t('browse.clearHistory') }}
            </button>
          </div>
          <div class="wall-search__history-list">
            <span
              v-for="term in searchHistory"
              :key="term"
              class="wall-search__history-chip"
            >
              <button
                type="button"
                class="wall-search__history-item"
                @mousedown.prevent="applyHistoryTerm(term)"
              >
                {{ term }}
              </button>
              <button
                type="button"
                class="wall-search__history-del"
                :aria-label="`${t('browse.removeHistoryItem')} ${term}`"
                @mousedown.prevent="removeSearchHistory(term)"
              >
                ×
              </button>
            </span>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 轻量悬浮控制条：一排容纳快筛、漫步、视图密度与低频工具 -->
    <div :class="['wall__bar', { 'wall__bar--dim': toolbarDim && !facetsOpen && !selectMode }]">
      <div class="wall__bar-left">
        <button
          type="button"
          :class="['wall__pill-btn wall__filter-toggle', { 'wall__pill-btn--on': facetsOpen || filters.activeCount > 0 }]"
          :aria-expanded="facetsOpen"
          aria-controls="facet-panel"
          @click="facetsOpen = !facetsOpen"
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">
            <path d="M2 4h12M4.5 8h7M7 12h2" />
          </svg>
          <span>{{ t('browse.filter') }}</span>
          <span v-if="filters.activeCount" class="wall__badge mono">{{ filters.activeCount }}</span>
        </button>

        <div class="wall__kinds" role="group" :aria-label="t('home.typeFilter')">
          <button
            type="button"
            :class="['wall__kind-btn', { 'wall__kind-btn--on': filters.kind === '' }]"
            :aria-pressed="filters.kind === ''"
            @click="setQuickKind('')"
          >
            {{ t('home.all') }}
          </button>
          <button
            type="button"
            :class="['wall__kind-btn', { 'wall__kind-btn--on': filters.kind === 'image' }]"
            :aria-pressed="filters.kind === 'image'"
            @click="setQuickKind('image')"
          >
            {{ t('home.images') }}
          </button>
          <button
            type="button"
            :class="['wall__kind-btn', { 'wall__kind-btn--on': filters.kind === 'video' }]"
            :aria-pressed="filters.kind === 'video'"
            @click="setQuickKind('video')"
          >
            {{ t('home.videos') }}
          </button>
        </div>

        <span class="wall__count mono" aria-live="polite">
          {{
            store.loading && !store.items.length
              ? t('site.loading')
              : onlyLiked
                ? `${visibleItems.length} / ${store.total}`
                : t('site.total', { count: store.total })
          }}
        </span>
      </div>

      <div class="wall__bar-right">
        <select
          class="wall__sort-select"
          :value="filters.sort"
          :aria-label="t('sort.label')"
          @change="onSortSelect"
        >
          <option v-for="key in SORT_KEYS" :key="key" :value="key">
            {{ t(`sort.${key}`) }}
          </option>
        </select>

        <button
          type="button"
          :class="['wall__pill-btn', { 'wall__pill-btn--on': filters.sort === 'random' }]"
          :aria-pressed="filters.sort === 'random'"
          @click="triggerShuffle"
        >
          ↻ {{ t('home.shuffle') }}
        </button>

        <div class="wall__seg" role="group" :aria-label="t('view.label')">
          <button
            v-for="v in VIEW_MODES"
            :key="v.key"
            type="button"
            :class="['wall__seg-btn', { 'wall__seg-btn--on': filters.view === v.key }]"
            :aria-pressed="filters.view === v.key"
            :aria-label="t(`view.${v.key}`)"
            :title="t(`view.${v.key}`)"
            @click="changeView(v.key)"
          >
            <span aria-hidden="true">{{ v.icon }}</span>
          </button>
        </div>

        <div v-if="filters.view !== 'list'" class="wall__seg" role="group" :aria-label="t('density.label')">
          <button
            v-for="d in DENSITY_KEYS"
            :key="d"
            type="button"
            :class="['wall__seg-btn wall__seg-btn--mono mono', { 'wall__seg-btn--on': density === d }]"
            :aria-pressed="density === d"
            :aria-label="t(`density.${d}`)"
            :title="t(`density.${d}`)"
            @click="changeDensity(d)"
          >
            {{ DENSITY_MAP[d].short }}
          </button>
        </div>

        <button
          type="button"
          :class="['wall__pill-btn', { 'wall__pill-btn--liked': onlyLiked }]"
          :aria-pressed="onlyLiked"
          @click="toggleOnlyLiked"
        >
          <span aria-hidden="true">{{ onlyLiked ? '♥' : '♡' }}</span>
          <span>{{ onlyLiked ? t('like.showAll') : t('like.onlyLiked') }}</span>
          <span v-if="likedIds.length" class="mono">{{ likedIds.length }}</span>
        </button>

        <button
          type="button"
          :class="['wall__pill-btn', { 'wall__pill-btn--on': selectMode }]"
          :aria-pressed="selectMode"
          @click="toggleSelectMode"
        >
          {{ selectMode ? t('batch.exitSelect') : t('batch.select') }}
        </button>

        <button type="button" class="wall__pill-btn" @click="uploadOpen = true">
          + {{ t('home.upload') }}
        </button>
      </div>
    </div>

    <!-- 已选筛选条件 chips 条 -->
    <div v-if="filters.hasFilters" class="wall__active" :aria-label="t('browse.activeFilters')">
      <MLChip
        v-if="filters.q"
        :label="t('browse.keyword', { value: filters.q })"
        removable
        @remove="clearSearch()"
      />
      <MLChip
        v-for="tag in filters.tags"
        :key="`t-${tag}`"
        :label="tag"
        removable
        active
        @remove="filters.removeTag(tag)"
      />
      <MLChip
        v-for="tag in filters.excludeTags"
        :key="`x-${tag}`"
        :label="tag"
        tone="exclude"
        removable
        @remove="filters.removeExclude(tag)"
      />
      <MLChip
        v-if="filters.kind"
        :label="filters.kind === 'image' ? t('facet.kindImage') : t('facet.kindVideo')"
        removable
        active
        @remove="filters.setKind('')"
      />
      <MLChip
        v-if="filters.orientation"
        :label="t(ORIENTATION_KEY[filters.orientation])"
        removable
        active
        @remove="filters.setOrientation('')"
      />
      <MLChip
        v-if="filters.sizeClass"
        :label="t(SIZE_KEY[filters.sizeClass] ?? 'facet.sizeClass')"
        removable
        active
        @remove="filters.setSizeClass('')"
      />
      <MLChip
        v-if="filters.ext"
        :label="filters.ext.replace(/^\./, '').toUpperCase()"
        removable
        active
        @remove="filters.setExt('')"
      />
      <MLChip
        v-if="filters.platform"
        :label="filters.platform"
        removable
        active
        @remove="filters.setPlatform('')"
      />
      <span v-if="filters.color" class="wall__color-chip">
        <span
          class="wall__color-dot"
          :style="{ backgroundColor: filters.color }"
          aria-hidden="true"
        />
        <MLChip
          :label="t('browse.colorFilter', { value: filters.color })"
          removable
          active
          @remove="filters.setColor('')"
        />
      </span>
      <MLChip
        v-if="filters.collectionId !== null"
        :label="t('browse.collectionFilter', { value: activeCollectionName })"
        removable
        active
        @remove="filters.setCollectionId(null)"
      />
      <button type="button" class="wall__clear" @click="clearAllFilters">
        {{ t('browse.clearAll') }}
      </button>
      <button type="button" class="wall__copy-link" @click="copyFilterLink">
        {{ t('browse.copyFilterLink') }}
      </button>
    </div>

    <!-- 以图搜图相似结果横幅 -->
    <div v-if="aiSearchActive" class="wall__ai-banner" role="status">
      <span>{{ t('browse.aiResultBanner', { count: store.total }) }}</span>
      <MLButton variant="quiet" size="sm" @click="exitAiSearch">
        {{ t('browse.exitAiSearch') }}
      </MLButton>
    </div>

    <div v-if="selectMode && visibleItems.length" class="wall__select-bar">
      <button
        type="button"
        class="wall__pill-btn"
        @click="toggleSelectAll"
      >
        {{ allSelected ? t('batch.unselectAll') : `${t('batch.selectAll')} (${visibleItems.length})` }}
      </button>
      <span v-if="selectedIds.length" class="wall__select-count mono">
        {{ t('batch.selected', { count: selectedIds.length }) }}
      </span>
      <span v-if="visibleItems.length > 1" class="wall__select-hint muted">
        {{ t('browse.shiftRangeHint') }}
      </span>
    </div>

    <!-- 主体区：默认单栏全宽瀑布流；展开筛选时切换为左栏分面 + 右栏图墙 -->
    <div :class="['wall__layout', { 'wall__layout--facets': facetsOpen }]">
      <div v-show="facetsOpen" id="facet-panel" class="wall__facets">
        <FacetPanel :facets="store.facets" :collections="collections" :loading="store.facetsLoading" />
      </div>

      <div class="wall__main">
        <!-- 首次/切换视图骨架屏 -->
        <div
          v-if="store.loading && !store.items.length"
          :class="['wall__skeleton', `wall__skeleton--${filters.view}`]"
          role="status"
          aria-live="polite"
          aria-busy="true"
          :aria-label="t('site.loading')"
        >
          <template v-if="filters.view === 'list'">
            <div v-for="idx in 6" :key="idx" class="wall__skel-row">
              <div class="wall__skel-thumb ml-skel-shimmer" />
              <div class="wall__skel-row-body">
                <div class="wall__skel-line ml-skel-shimmer" />
                <div class="wall__skel-line wall__skel-line--short ml-skel-shimmer" />
              </div>
            </div>
          </template>
          <template v-else>
            <div v-for="(r, idx) in SKELETON_RATIOS" :key="idx" class="wall__skel-card">
              <div
                class="wall__skel-media ml-skel-shimmer"
                :style="{ aspectRatio: filters.view === 'grid' ? '4 / 3' : `1 / ${r}` }"
              />
              <div class="wall__skel-line ml-skel-shimmer" />
              <div class="wall__skel-line wall__skel-line--short ml-skel-shimmer" />
            </div>
          </template>
        </div>

        <!-- 请求异常 -->
        <div v-else-if="store.error && !store.items.length" class="wall__empty">
          <h2 class="wall__empty-title">{{ t('browse.errorTitle') }}</h2>
          <p class="muted">{{ store.error }}</p>
          <MLButton variant="ghost" @click="refreshWithFeatured()">
            {{ t('common.retry') }}
          </MLButton>
        </div>

        <!-- 空库或筛选无结果 -->
        <div v-else-if="store.isEmpty" class="wall__empty">
          <svg class="wall__empty-icon" width="46" height="46" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="6" y="10" width="36" height="28" rx="3" />
            <circle cx="17" cy="20" r="3" />
            <path d="m40 33-9-9-7 7-4-4-12 11" />
          </svg>
          <h2 class="wall__empty-title">{{ t('browse.emptyTitle') }}</h2>
          <p class="muted">{{ emptyHint }}</p>
          <div v-if="filters.hasFilters" class="wall__empty-actions">
            <MLButton
              v-if="filters.q.trim() && filters.activeCount > 1"
              variant="ghost"
              @click="clearSearch"
            >
              {{ t('browse.clearKeyword') }}
            </MLButton>
            <MLButton variant="ghost" @click="clearAllFilters">
              {{ t('browse.clearAll') }}
            </MLButton>
          </div>
          <MLButton v-else variant="ghost" @click="uploadOpen = true">
            {{ t('home.addFirst') }}
          </MLButton>
        </div>

        <!-- 只看喜欢但当前无喜欢项 -->
        <div v-else-if="!visibleItems.length" class="wall__empty">
          <h2 class="wall__empty-title">{{ t('like.empty') }}</h2>
          <MLButton variant="ghost" @click="onlyLiked = false">
            {{ t('like.showAll') }}
          </MLButton>
        </div>

        <!-- 图片墙本体 -->
        <MasonryGrid
          v-else
          :items="visibleItems"
          :mode="filters.view"
          :base-column-width="DENSITY_MAP[density].masonry"
          :grid-min-width="DENSITY_MAP[density].grid"
          :selectable="selectMode"
          :selected-ids="selectedIds"
          :liked-ids="likedIds"
          @open="openLightbox"
          @toggle="toggleSelect"
          @toggle-like="toggleLike"
          @filter-color="onFilterColor"
        />

        <!-- 无限滚动哨兵 -->
        <div ref="sentinel" class="wall__sentinel" aria-hidden="true" />
        <div v-if="store.hasMore && !pageAutoLoad" class="wall__more">
          <MLButton variant="ghost" :disabled="store.loading" @click="store.load()">
            {{ store.loading ? t('site.loading') : t('browse.loadMore') }}
          </MLButton>
        </div>
        <p v-else-if="store.loading && visibleItems.length" class="wall__end muted">
          {{ t('site.loading') }}
        </p>
        <p v-else-if="!store.hasMore && visibleItems.length && !store.loading" class="wall__end mono muted">
          {{ t('browse.endOfList', { count: visibleItems.length }) }}
        </p>
        <div v-if="onlyLiked && store.hasMore && !store.loading" class="wall__liked-more">
          <span class="muted">
            {{
              t('browse.likedLoadMoreHint', {
                loaded: store.items.length,
                remaining: Math.max(0, store.total - store.items.length),
                total: store.total,
              })
            }}
          </span>
          <MLButton variant="ghost" size="sm" @click="store.load()">
            {{ t('browse.loadMoreToFindLikes') }}
          </MLButton>
        </div>
      </div>
    </div>

    <LightboxViewer
      v-if="store.currentItem"
      :item="store.currentItem"
      :index="visibleIndex >= 0 ? visibleIndex + 1 : store.lightboxIndex + 1"
      :total="onlyLiked ? visibleItems.length : Math.max(store.total, store.items.length)"
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
      @updated="store.patchItemInPlace($event)"
      @select-item="onSelectSimilar"
    />

    <!-- 回到顶部悬浮钮 -->
    <Transition name="ml-fade-up">
      <button
        v-if="showBackTop"
        type="button"
        class="wall__top"
        :aria-label="t('wall.backToTop')"
        :title="t('wall.backToTop')"
        @click="scrollToTop"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" />
        </svg>
      </button>
    </Transition>

    <UploadPanel
      ref="uploadPanelRef"
      v-model:open="uploadOpen"
      :suggested-tags="(store.facets?.tag ?? []).filter((x) => x.count > 0).slice(0, 8).map((x) => x.value)"
      @uploaded="onUploaded"
    />

    <BatchBar
      :selected="selectedIds"
      :collections="collections"
      :available-tags="(store.facets?.tag ?? []).filter((x) => x.count > 0).slice(0, 12).map((x) => x.value)"
      :selected-tags="selectedItemTags"
      @clear="clearSelection"
      @done="onBatchDone"
    />
  </div>
</template>

<style scoped>
.wall {
  position: relative;
  max-width: 1720px;
  margin: 0 auto;
  padding: var(--p-space-2) var(--p-space-5) var(--p-space-8);
  min-height: 100vh;
}

.wall__drop-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--p-z-sheet);
  background: color-mix(in srgb, var(--paper) 82%, transparent);
  backdrop-filter: blur(6px);
  display: grid;
  place-items: center;
  padding: var(--p-space-5);
  pointer-events: none;
}

.wall__drop-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-2);
  padding: var(--p-space-7) var(--p-space-8);
  border-radius: var(--p-radius-lg);
  border: 2px dashed var(--accent);
  background: var(--surface);
  color: var(--ink);
  font-size: var(--p-step-1);
  font-weight: 500;
  box-shadow: var(--sheet-shadow);
}

.wall__drop-plus {
  font-size: 2rem;
  color: var(--accent);
  line-height: 1;
}

/* ---------- 顶栏搜索框（Teleport 至 AppShell 中央插槽） ---------- */
.wall-search {
  position: relative;
  width: 100%;
  max-width: 520px;
}

.wall-search--inline {
  margin-bottom: var(--p-space-3);
}

.wall-search--drag {
  outline: 2px dashed var(--accent);
  outline-offset: 2px;
  border-radius: var(--p-radius-full);
}

.wall-search--busy {
  opacity: 0.72;
}

.wall-search__icon {
  position: absolute;
  left: var(--p-space-3);
  top: 50%;
  transform: translateY(-50%);
  color: var(--ink-faint);
  pointer-events: none;
}

.wall-search__input {
  width: 100%;
  font: inherit;
  font-size: var(--p-step--1);
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--rule-strong);
  border-radius: var(--p-radius-full);
  padding: var(--p-space-1) var(--p-space-9) var(--p-space-1) var(--p-space-7);
  min-height: 34px;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.wall-search__input:hover,
.wall-search__input:focus {
  border-color: var(--ink-faint);
}

.wall-search__input::placeholder {
  color: var(--ink-faint);
}

.wall-search__clear {
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

.wall-search__clear:hover {
  background: var(--surface-sunken);
  color: var(--ink);
}

.wall-search__ai {
  position: absolute;
  right: var(--p-space-2);
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.75rem;
  color: var(--accent);
  font-weight: 500;
  white-space: nowrap;
}

.wall-search__ai--btn {
  padding: 2px 8px;
  border-radius: var(--p-radius-full);
  background: var(--accent-soft);
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.wall-search__ai--btn:hover {
  background: color-mix(in srgb, var(--accent) 22%, transparent);
}

.wall-search__ai--busy {
  right: var(--p-space-3);
  pointer-events: none;
  animation: wall-pulse var(--p-dur-slow) var(--p-ease-in-out) infinite alternate;
}

@keyframes wall-pulse {
  from {
    opacity: 0.5;
  }
  to {
    opacity: 1;
  }
}

.wall-search__kbd {
  position: absolute;
  right: var(--p-space-3);
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.6875rem;
  line-height: 1;
  padding: 2px 6px;
  border-radius: var(--p-radius-sm);
  border: 1px solid var(--rule);
  background: var(--paper);
  color: var(--ink-muted);
  pointer-events: none;
}

.wall-search__history {
  position: absolute;
  left: 0;
  right: 0;
  top: calc(100% + 8px);
  z-index: calc(var(--p-z-header) + 5);
  padding: var(--p-space-3);
  border-radius: var(--p-radius-lg);
  background: var(--surface);
  border: 1px solid var(--rule-strong);
  box-shadow: var(--sheet-shadow);
}

.wall-search__history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--ink-faint);
  margin-bottom: var(--p-space-2);
}

.wall-search__history-clear {
  font-size: 0.75rem;
  color: var(--ink-muted);
}

.wall-search__history-clear:hover {
  color: var(--danger);
}

.wall-search__history-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.wall-search__history-chip {
  display: inline-flex;
  align-items: center;
  border-radius: var(--p-radius-full);
  background: var(--surface-sunken);
  border: 1px solid transparent;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out);
}

.wall-search__history-chip:hover {
  background: var(--accent-soft);
  border-color: var(--rule-strong);
}

.wall-search__history-item {
  padding: 2px 6px 2px 10px;
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wall-search__history-chip:hover .wall-search__history-item {
  color: var(--accent-hover);
}

.wall-search__history-del {
  padding: 0 7px 0 2px;
  font-size: 0.8125rem;
  line-height: 1;
  color: var(--ink-faint);
  border-radius: 0 var(--p-radius-full) var(--p-radius-full) 0;
}

.wall-search__history-del:hover {
  color: var(--danger);
}

/* ---------- 悬浮控制条 ---------- */
.wall__bar {
  position: sticky;
  top: var(--header-offset, 0px);
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--p-space-2) var(--p-space-3);
  padding: var(--p-space-2) 0 var(--p-space-3);
  background: color-mix(in srgb, var(--paper) 84%, transparent);
  backdrop-filter: blur(10px);
  transition:
    opacity var(--p-dur-base) var(--p-ease-out),
    top var(--p-dur-base) var(--p-ease-out);
}

.wall__bar--dim {
  opacity: 0.68;
}

.wall__bar:hover,
.wall__bar:focus-within {
  opacity: 1;
}

.wall__bar-left,
.wall__bar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--p-space-2);
}

.wall__bar-right {
  margin-left: auto;
}

.wall__kinds {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: var(--p-radius-full);
  background: var(--surface);
  border: 1px solid var(--rule);
}

.wall__kind-btn {
  padding: 2px var(--p-space-3);
  min-height: 24px;
  border-radius: var(--p-radius-full);
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  white-space: nowrap;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.wall__kind-btn:hover {
  color: var(--ink);
}

.wall__kind-btn--on {
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 500;
}

.wall__count {
  font-size: var(--p-step--1);
  color: var(--ink-faint);
  padding: 0 var(--p-space-1);
  white-space: nowrap;
}

.wall__pill-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-1);
  padding: 2px var(--p-space-3);
  min-height: 28px;
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  white-space: nowrap;
  transition:
    color var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.wall__pill-btn:hover {
  color: var(--ink);
  border-color: var(--rule-strong);
}

.wall__pill-btn--on {
  background: var(--accent-soft);
  color: var(--accent-hover);
  border-color: var(--accent);
  font-weight: 500;
}

.wall__pill-btn--liked {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--rule));
  font-weight: 500;
}

.wall__badge {
  background: var(--accent);
  color: var(--on-accent);
  border-radius: var(--p-radius-full);
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0 5px;
  min-width: 16px;
  text-align: center;
}

.wall__sort-select {
  font: inherit;
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  padding: 2px var(--p-space-3);
  min-height: 28px;
  cursor: pointer;
  transition:
    color var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out);
}

.wall__sort-select:hover,
.wall__sort-select:focus {
  color: var(--ink);
  border-color: var(--rule-strong);
}

.wall__seg {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  padding: 2px;
  gap: 2px;
  background: var(--surface);
}

.wall__seg-btn {
  min-width: 26px;
  min-height: 24px;
  padding: 0 6px;
  border-radius: var(--p-radius-full);
  color: var(--ink-muted);
  font-size: 0.8125rem;
  display: grid;
  place-items: center;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.wall__seg-btn--mono {
  font-size: 0.6875rem;
  font-weight: 500;
}

.wall__seg-btn:hover {
  color: var(--ink);
  background: var(--surface-hover);
}

.wall__seg-btn--on {
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 600;
}

/* ---------- 已选条件与提示条 ---------- */
.wall__active {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--p-space-1);
  padding-bottom: var(--p-space-3);
  border-bottom: 1px solid var(--rule);
  margin-bottom: var(--p-space-4);
}

.wall__color-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-1);
}

.wall__color-dot {
  width: 12px;
  height: 12px;
  border-radius: var(--p-radius-full);
  border: 1px solid var(--rule-strong);
  flex-shrink: 0;
}

.wall__clear {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-2);
}

.wall__clear:hover {
  color: var(--danger);
}

.wall__copy-link {
  margin-left: auto;
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-2);
  border-radius: var(--p-radius-sm);
  transition:
    color var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.wall__copy-link:hover {
  color: var(--ink);
  background: var(--surface-hover);
}

.wall__ai-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-3);
  margin-bottom: var(--p-space-4);
  border-radius: var(--p-radius-md);
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-size: var(--p-step--1);
}

.wall__select-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--p-space-2) var(--p-space-3);
  margin-bottom: var(--p-space-3);
  padding: 4px var(--p-space-2) 4px 4px;
  border-radius: var(--p-radius-full);
  background: var(--surface-sunken);
  width: fit-content;
  max-width: 100%;
}

.wall__select-count {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--accent-hover);
}

.wall__select-hint {
  font-size: 0.75rem;
  padding-right: var(--p-space-2);
}

/* ---------- 布局：默认全宽图墙，展开筛选时两栏并排 ---------- */
.wall__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
}

.wall__layout--facets {
  grid-template-columns: 210px minmax(0, 1fr);
  gap: var(--p-space-6);
}

.wall__facets {
  position: sticky;
  top: calc(var(--header-offset, 0px) + 52px);
  max-height: calc(100vh - var(--header-offset, 0px) - var(--p-space-8));
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  padding-right: var(--p-space-2);
  scrollbar-width: thin;
  scrollbar-color: var(--rule-strong) transparent;
}

.wall__main {
  min-width: 0;
}

/* ---------- 骨架屏、空态与分页尾注 ---------- */
.wall__skeleton--masonry {
  columns: 5 240px;
  column-gap: var(--p-space-4);
}

.wall__skeleton--masonry .wall__skel-card {
  break-inside: avoid;
  margin-bottom: var(--p-space-4);
}

.wall__skeleton--grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--p-space-4);
  align-items: start;
}

.wall__skeleton--list {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
}

.wall__skel-row {
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-md);
  background: var(--surface);
  border: 1px solid var(--rule);
}

.wall__skel-thumb {
  width: 64px;
  height: 48px;
  border-radius: var(--p-radius-sm);
  flex-shrink: 0;
}

.wall__skel-row-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wall__skel-card {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
}

.wall__skel-media {
  width: 100%;
  border-radius: var(--p-radius-lg);
}

.wall__skel-line {
  height: 12px;
  width: 78%;
  border-radius: var(--p-radius-sm);
}

.wall__skel-line--short {
  width: 48%;
}

.wall__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-9) var(--p-space-5);
  text-align: center;
}

.wall__empty-title {
  font-size: var(--p-step-2);
}

.wall__empty-icon {
  color: var(--ink-faint);
  opacity: 0.72;
}

.wall__empty-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--p-space-2);
}

.wall__sentinel {
  height: 1px;
}

.wall__more {
  display: flex;
  justify-content: center;
  padding: var(--p-space-6) 0;
}

.wall__end {
  text-align: center;
  padding: var(--p-space-5) 0 var(--p-space-2);
  font-size: var(--p-step--1);
}

.wall__liked-more {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  padding: var(--p-space-4) 0;
  font-size: var(--p-step--1);
}

.wall__top {
  position: fixed;
  right: var(--p-space-5);
  bottom: calc(var(--p-space-5) + var(--batch-bar-offset, 0px));
  z-index: 30;
  width: 40px;
  height: 40px;
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--rule-strong);
  box-shadow: var(--card-shadow-hover);
  display: grid;
  place-items: center;
  font-size: 1.125rem;
  transition:
    transform var(--p-dur-fast) var(--p-ease-out),
    bottom var(--p-dur-base) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.wall__top:hover {
  transform: translateY(-2px);
  background: var(--surface-hover);
}

@media (max-width: 900px) {
  .wall {
    padding: var(--p-space-2) var(--p-space-3) var(--p-space-8);
  }

  .wall__layout--facets {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--p-space-4);
  }

  .wall__facets {
    position: static;
    max-height: none;
    padding: 0 0 var(--p-space-4);
    border-bottom: 1px solid var(--rule);
  }
}

@media (max-width: 680px) {
  .wall-search {
    max-width: none;
  }

  .wall__bar-right {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wall__bar,
  .wall__top,
  .wall-search__ai--busy {
    transition: none;
    animation: none;
  }
}
</style>
