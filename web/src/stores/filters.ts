/**
 * 筛选状态（REQ-V2-20 B-10）
 *
 * 核心约定：URL 即状态。所有筛选写入 query string，
 * 复制链接即可还原完整视图；滚动位置不进 URL（放 history.state）。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useRouter } from 'vue-router'
import type { SortKey, ViewMode } from '@/api/types'

export interface FacetOption {
  value: string
  count: number
}

export interface Facets {
  kind: FacetOption[]
  ext: FacetOption[]
  orientation: FacetOption[]
  platform: FacetOption[]
  tag: FacetOption[]
  size_class: FacetOption[]
  total: number
}

export const useFilterStore = defineStore('filters', () => {
  const router = useRouter()

  const q = ref('')
  const tags = ref<string[]>([])
  const excludeTags = ref<string[]>([])
  const kind = ref<'' | 'image' | 'video'>('')
  const orientation = ref<'' | 'landscape' | 'portrait' | 'square'>('')
  const platform = ref('')
  const ext = ref('')
  /** 分辨率分桶（分面面板的「分辨率」组，后端按长边分桶） */
  const sizeClass = ref('')
  /** 主色筛选（A-04 色板 → B-10 色彩分面打通） */
  const color = ref('')
  /** 画板筛选（REQ-10） */
  const collectionId = ref<number | null>(null)
  const sort = ref<SortKey>('newest')
  const view = ref<ViewMode>('masonry')

  /** 是否有任何激活的筛选 */
  const activeCount = computed(
    () =>
      (q.value ? 1 : 0) +
      tags.value.length +
      excludeTags.value.length +
      (kind.value ? 1 : 0) +
      (orientation.value ? 1 : 0) +
      (platform.value ? 1 : 0) +
      (ext.value ? 1 : 0) +
      (sizeClass.value ? 1 : 0) +
      (color.value ? 1 : 0) +
      (collectionId.value !== null ? 1 : 0),
  )

  const hasFilters = computed(() => activeCount.value > 0)

  /** 序列化为后端查询参数 */
  const queryParams = computed(() => ({
    q: q.value,
    tag: tags.value,
    exclude_tag: excludeTags.value,
    kind: kind.value,
    orientation: orientation.value,
    platform: platform.value,
    ext: ext.value,
    size_class: sizeClass.value,
    color: color.value,
    collection_id: collectionId.value,
    sort: sort.value,
  }))

  /** 序列化为 URL query string */
  function toUrlQuery(): Record<string, string> {
    const out: Record<string, string> = {}
    if (q.value) out.q = q.value
    if (tags.value.length) out.tag = tags.value.join(',')
    if (excludeTags.value.length) out.exclude = excludeTags.value.join(',')
    if (kind.value) out.kind = kind.value
    if (orientation.value) out.orientation = orientation.value
    if (platform.value) out.platform = platform.value
    if (ext.value) out.ext = ext.value
    if (sizeClass.value) out.size = sizeClass.value
    if (color.value) out.color = color.value
    if (collectionId.value !== null) out.collection = String(collectionId.value)
    if (sort.value !== 'newest') out.sort = sort.value
    if (view.value !== 'masonry') out.view = view.value
    return out
  }

  /** 从 URL 读取并还原筛选状态 */
  function fromUrlQuery(query: Record<string, string | string[]>): void {
    const get = (k: string): string => {
      const v = query[k]
      return Array.isArray(v) ? (v[0] ?? '') : (v ?? '')
    }
    const split = (v: string): string[] => (v ? v.split(',').filter(Boolean) : [])

    q.value = get('q')
    tags.value = split(get('tag'))
    excludeTags.value = split(get('exclude'))
    kind.value = (get('kind') as '' | 'image' | 'video') || ''
    orientation.value = (get('orientation') as '' | 'landscape' | 'portrait' | 'square') || ''
    platform.value = get('platform')
    ext.value = get('ext')
    sizeClass.value = get('size')
    color.value = get('color')
    const rawCol = get('collection')
    const parsedCol = rawCol ? Number(rawCol) : NaN
    collectionId.value = Number.isFinite(parsedCol) && parsedCol > 0 ? parsedCol : null
    sort.value = (get('sort') as SortKey) || 'newest'
    view.value = (get('view') as ViewMode) || 'masonry'
  }

  let syncTimer: number | undefined

  /** 把当前筛选同步到 URL（防抖，避免每个按键都写历史） */
  function syncUrl(): void {
    window.clearTimeout(syncTimer)
    syncTimer = window.setTimeout(() => {
      router.replace({ query: toUrlQuery() })
    }, 200)
  }

  function toggleTag(tag: string): void {
    const i = tags.value.indexOf(tag)
    if (i >= 0) tags.value.splice(i, 1)
    else {
      tags.value.push(tag)
      // 同时存在于排除列表时不合法，移出排除
      const j = excludeTags.value.indexOf(tag)
      if (j >= 0) excludeTags.value.splice(j, 1)
    }
    syncUrl()
  }

  function excludeTag(tag: string): void {
    const i = tags.value.indexOf(tag)
    if (i >= 0) tags.value.splice(i, 1)
    const j = excludeTags.value.indexOf(tag)
    if (j >= 0) excludeTags.value.splice(j, 1)
    else excludeTags.value.push(tag)
    syncUrl()
  }

  function removeTag(tag: string): void {
    tags.value = tags.value.filter((t) => t !== tag)
    syncUrl()
  }

  function removeExclude(tag: string): void {
    excludeTags.value = excludeTags.value.filter((t) => t !== tag)
    syncUrl()
  }

  function setQ(value: string): void {
    q.value = value
    syncUrl()
  }

  function setKind(value: '' | 'image' | 'video'): void {
    kind.value = value
    syncUrl()
  }

  function setOrientation(value: '' | 'landscape' | 'portrait' | 'square'): void {
    orientation.value = value
    syncUrl()
  }

  function setPlatform(value: string): void {
    platform.value = value
    syncUrl()
  }

  function setExt(value: string): void {
    ext.value = value
    syncUrl()
  }

  function setSizeClass(value: string): void {
    sizeClass.value = value
    syncUrl()
  }

  function setColor(value: string): void {
    color.value = value
    syncUrl()
  }

  function setCollectionId(value: number | null): void {
    collectionId.value = value
    syncUrl()
  }

  function setSort(value: SortKey): void {
    sort.value = value
    syncUrl()
  }

  function setView(value: ViewMode): void {
    view.value = value
    syncUrl()
  }

  /** 清空全部筛选（保留视图与排序偏好） */
  function reset(): void {
    q.value = ''
    tags.value = []
    excludeTags.value = []
    kind.value = ''
    orientation.value = ''
    platform.value = ''
    ext.value = ''
    sizeClass.value = ''
    color.value = ''
    collectionId.value = null
    syncUrl()
  }

  return {
    q,
    tags,
    excludeTags,
    kind,
    orientation,
    platform,
    ext,
    sizeClass,
    color,
    collectionId,
    sort,
    view,
    activeCount,
    hasFilters,
    queryParams,
    fromUrlQuery,
    toUrlQuery,
    syncUrl,
    toggleTag,
    excludeTag,
    removeTag,
    removeExclude,
    setQ,
    setKind,
    setOrientation,
    setPlatform,
    setExt,
    setSizeClass,
    setColor,
    setCollectionId,
    setSort,
    setView,
    reset,
  }
})
