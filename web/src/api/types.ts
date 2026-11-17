/**
 * 后端 API 类型定义
 *
 * 字段以后端 db.py 的 items 表为准（30 列），
 * 只声明前端实际消费的字段，避免与后端实现耦合过深。
 */

/** 媒体条目 */
export interface MediaItem {
  id: string
  file: string
  thumb: string | null
  play_file: string | null
  preview_file: string | null
  kind: 'image' | 'video'
  ext: string
  name: string
  title: string
  source: string
  source_platform: string
  author: string
  notes: string
  size: number
  width: number
  height: number
  aspect_ratio: number
  duration: number
  fps: number
  codec: string
  dominant_color: string
  palette_json: string
  exif_json: string
  phash: string
  ocr_text: string
  /** 授权与署名（C-11）。存量数据可能缺失，故为可选。 */
  license?: string
  license_url?: string
  credit?: string
  copyright_holder?: string
  /** 1 = 可商用，0 = 仅限个人使用（SQLite 无布尔类型） */
  commercial_ok?: number
  license_expires_at?: number | null
  views: number
  downloads: number
  ts: number
  updated_at: number
  deleted_at: number | null
  /** 后端 hydrate 时附带的标签数组 */
  tags?: string[]
}

/** 分页列表响应 */
export interface ItemListResponse {
  total: number
  items: MediaItem[]
}

/** 统计概览 */
export interface StatsResponse {
  total: number
  images: number
  videos: number
  trashed: number
  tags: Record<string, number>
  total_size: number
  [key: string]: unknown
}

/** 合集 */
export interface Collection {
  id: number
  name: string
  description: string
  cover_item_id: string | null
  created_at: number
  updated_at: number
  count?: number
}

/** 列表查询参数；tag 类参数可传数组，由 client 序列化为逗号分隔 */
export interface ItemQuery {
  limit?: number
  offset?: number
  q?: string
  tag?: string | string[]
  exclude_tag?: string | string[]
  kind?: string
  ext?: string
  orientation?: string
  platform?: string
  collection_id?: number | null
  color?: string
  /** 分辨率分桶：4k / hd / sd / small */
  size_class?: string
  sort?: string
  deleted?: boolean
}

/** 排序方式 */
export type SortKey = 'newest' | 'oldest' | 'size' | 'pixels' | 'views' | 'random'

/** 视图模式 */
export type ViewMode = 'masonry' | 'grid' | 'list'

/** 主题 */
export type ThemeMode = 'light' | 'dark' | 'auto'
