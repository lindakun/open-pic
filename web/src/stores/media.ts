/**
 * 媒体库状态仓库
 *
 * 替代旧前端 app.js 里 400 行的 state 对象。
 * 分页加载、筛选条件、当前浏览项统一在此管理，
 * 组件只读取派生状态并派发动作。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { MediaItem, SortKey, ViewMode } from '@/api/types'

export const useMediaStore = defineStore('media', () => {
  // ---------- 数据 ----------
  const items = ref<MediaItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ---------- 筛选 ----------
  const query = ref('')
  const sort = ref<SortKey>('newest')
  const view = ref<ViewMode>('masonry')
  const kind = ref<'' | 'image' | 'video'>('')

  // ---------- 灯箱 ----------
  const lightboxIndex = ref(-1)
  const currentItem = computed(() =>
    lightboxIndex.value >= 0 ? items.value[lightboxIndex.value] ?? null : null,
  )

  const hasMore = computed(() => items.value.length < total.value)
  const isEmpty = computed(() => !loading.value && items.value.length === 0)

  /** 每页条数：与后端默认一致 */
  const PAGE_SIZE = 48

  /** 拉取一页数据；reset 为 true 时从第一页重来 */
  async function load(reset = false) {
    if (loading.value) return
    if (!reset && !hasMore.value && items.value.length > 0) return

    loading.value = true
    error.value = null
    try {
      const offset = reset ? 0 : items.value.length
      const res = await api.items({
        limit: PAGE_SIZE,
        offset,
        q: query.value,
        kind: kind.value,
        sort: sort.value,
      })
      items.value = reset ? res.items : [...items.value, ...res.items]
      total.value = res.total
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  function refresh() {
    return load(true)
  }

  function openLightbox(index: number) {
    lightboxIndex.value = index
  }

  function closeLightbox() {
    lightboxIndex.value = -1
  }

  function stepLightbox(delta: number) {
    const next = lightboxIndex.value + delta
    if (next >= 0 && next < items.value.length) {
      lightboxIndex.value = next
    }
  }

  function setQuery(value: string) {
    query.value = value
  }

  function setSort(value: SortKey) {
    sort.value = value
  }

  function setKind(value: '' | 'image' | 'video') {
    kind.value = value
  }

  return {
    // 状态
    items,
    total,
    loading,
    error,
    query,
    sort,
    view,
    kind,
    lightboxIndex,
    // 派生
    currentItem,
    hasMore,
    isEmpty,
    // 动作
    load,
    refresh,
    openLightbox,
    closeLightbox,
    stepLightbox,
    setQuery,
    setSort,
    setKind,
  }
})
