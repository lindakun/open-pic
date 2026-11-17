/**
 * 媒体库状态仓库
 *
 * 替代旧前端 app.js 里 400 行的 state 对象。
 * 分页加载、灯箱、竞态控制统一在此管理；
 * 筛选条件由 useFilterStore 独立维护（B-10），两者通过 queryParams 协作。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { MediaItem } from '@/api/types'
import { useFilterStore } from './filters'
import { pageSizeFor } from '@/composables/useScrollRestore'
import type { Facets } from './filters'

export const useMediaStore = defineStore('media', () => {
  const filters = useFilterStore()

  // ---------- 数据 ----------
  const items = ref<MediaItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const facets = ref<Facets | null>(null)
  const facetsLoading = ref(false)

  // ---------- 灯箱 ----------
  const lightboxIndex = ref(-1)
  const currentItem = computed(() =>
    lightboxIndex.value >= 0 ? items.value[lightboxIndex.value] ?? null : null,
  )

  const hasMore = computed(() => items.value.length < total.value)
  /** 首屏是否已至少完成过一次请求：避免刚进页面就闪"空库" */
  const settled = ref(false)

  const isEmpty = computed(
    () => settled.value && !loading.value && items.value.length === 0,
  )

  /** 默认分页 48；弱网/省流量降为 24（D-17） */
  const PAGE_SIZE = pageSizeFor(48, 24)

  /**
   * 请求序号：用于丢弃过期响应，防止快速切换筛选时
   * 先发的慢请求覆盖后发的快请求（B-10 验收要求）。
   */
  let requestSeq = 0
  /** 分面请求的独立序号：与列表请求节奏不同，需单独防竞态 */
  let facetsSeq = 0

  async function load(reset = false, keepCount?: number) {
    if (!reset && loading.value) return
    if (!reset && !hasMore.value && items.value.length > 0) return

    const seq = ++requestSeq
    loading.value = true
    error.value = null

    try {
      const offset = reset ? 0 : items.value.length
      // 刷新时保留已加载条数（上限 500 防爆）：翻了几页后上传/SSE
      // 触发刷新，不应把列表重置回第一页丢失滚动位置
      const limit = reset
        ? Math.min(Math.max(keepCount ?? PAGE_SIZE, PAGE_SIZE), 500)
        : PAGE_SIZE
      const res = await api.items({
        ...filters.queryParams,
        limit,
        offset,
      })
      // 过期响应直接丢弃
      if (seq !== requestSeq) return
      items.value = reset ? res.items : [...items.value, ...res.items]
      total.value = res.total
      settled.value = true
    } catch (e) {
      if (seq !== requestSeq) return
      error.value = (e as Error).message
      settled.value = true
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  /** 重新加载列表与分面计数（保留已加载条数，见 load 的 keepCount） */
  async function refresh() {
    await Promise.all([load(true, items.value.length || undefined), loadFacets()])
  }

  /** 拉取分面统计 */
  async function loadFacets() {
    // 序号防竞态：快速切换筛选时丢弃过期响应（与 load 的 requestSeq 同款口径）
    const seq = ++facetsSeq
    facetsLoading.value = true
    try {
      const res = await api.facets({
        kind: filters.kind,
        ext: filters.ext,
        orientation: filters.orientation,
        platform: filters.platform,
        // 标签也参与分面上下文：否则选标签后其余维度仍显示全集计数
        tag: filters.tags,
        exclude_tag: filters.excludeTags,
      })
      if (seq !== facetsSeq) return
      facets.value = res
    } catch {
      if (seq !== facetsSeq) return
      // 分面统计失败不影响主列表展示
      facets.value = null
    } finally {
      if (seq === facetsSeq) facetsLoading.value = false
    }
  }

  /**
   * 单卡更新（SSE media_ready 用）：异步处理完成后仅刷新该资产，
   * 不重置列表，避免打断浏览位置与已加载的分页。
   */
  async function updateItem(id: string) {
    try {
      const next = await api.item(id)
      const i = items.value.findIndex((it) => it.id === id)
      if (i >= 0) items.value[i] = next
    } catch {
      // 单卡更新失败静默：下一次全量刷新自然修正
    }
  }

  /**
   * 把人工精选提到列表最前（A-02 遗留项）。
   *
   * 首页保持"纯图片墙"结构不变，只改变顺序：
   * 精选位由人工排布，其余仍按时间倒序。
   */
  async function promoteFeatured(limit = 12) {
    try {
      const res = await fetch('/api/home/featured?' + new URLSearchParams({ limit: String(limit) }))
      if (!res.ok) return
      const data = (await res.json()) as { items: MediaItem[] }
      const featured = data.items ?? []
      if (!featured.length) return
      const order = new Map(featured.map((it, i) => [it.id, i]))
      // 已加载条目里属于精选的按精选顺序前置，其余保持原序
      const rest = items.value.filter((it) => !order.has(it.id))
      const head = [...featured].sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0))
      items.value = [...head, ...rest]
    } catch {
      // 精选失败不影响图片墙
    }
  }

  /** 用一次性检索结果替换列表（以图搜图等非分页场景） */
  function replaceItems(next: MediaItem[], nextTotal: number) {
    items.value = next
    total.value = nextTotal
    lightboxIndex.value = -1
  }

  function openLightbox(index: number) {
    lightboxIndex.value = index
  }

  function closeLightbox() {
    lightboxIndex.value = -1
  }

  /** 连播放映到末尾后回到首张继续（A-04 连播回环） */
  function stepToFirst() {
    if (items.value.length) lightboxIndex.value = 0
  }

  function stepLightbox(delta: number) {
    const next = lightboxIndex.value + delta
    if (next >= 0 && next < items.value.length) {
      lightboxIndex.value = next
    }
  }

  return {
    items,
    total,
    loading,
    error,
    facets,
    facetsLoading,
    lightboxIndex,
    currentItem,
    hasMore,
    isEmpty,
    settled,
    load,
    loadFacets,
    updateItem,
    replaceItems,
    promoteFeatured,
    refresh,
    openLightbox,
    closeLightbox,
    stepLightbox,
    stepToFirst,
  }
})
