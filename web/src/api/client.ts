/**
 * API 客户端
 *
 * 统一处理：基础路径、错误抛出、查询参数序列化。
 * 后端约定：错误返回 { detail: string }，见 server.py 的 HTTPException。
 */

import type {
  Collection,
  ItemListResponse,
  ItemQuery,
  MediaItem,
  StatsResponse,
} from './types'
import type { Facets } from '@/stores/filters'

/** 后端返回的错误结构 */
interface ApiError {
  detail?: string
}

export class ApiRequestError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
  }
}

/**
 * 把查询对象序列化为 query string，跳过空值。
 * 复数为 null/undefined/'' 的参数不发送，避免后端把空串当作筛选条件。
 */
function toQuery(params: Record<string, unknown>): string {
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      if (value.length === 0) continue
      sp.set(key, value.join(','))
      continue
    }
    sp.set(key, String(value))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      headers: init?.body instanceof FormData
        ? undefined
        : { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (e) {
    throw new ApiRequestError(
      `网络请求失败：${(e as Error).message}`,
      0,
    )
  }

  if (!res.ok) {
    let message = `请求失败（${res.status}）`
    // 后端部分校验错误是英文短码，换成本地化文案
    if (res.status === 413) message = '文件超过大小上限（1GB）'
    try {
      const body = (await res.json()) as ApiError
      if (res.status !== 413 && body?.detail) message = body.detail
    } catch {
      // 响应不是 JSON 时保留默认文案
    }
    throw new ApiRequestError(message, res.status)
  }

  // 204 无内容
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  stats(): Promise<StatsResponse> {
    return request<StatsResponse>('/api/stats')
  },

  items(query: ItemQuery = {}): Promise<ItemListResponse> {
    return request<ItemListResponse>(`/api/items${toQuery(query as Record<string, unknown>)}`)
  },

  item(id: string, markView = false): Promise<MediaItem> {
    return request<MediaItem>(`/api/item/${id}${markView ? '?view=true' : ''}`)
  },

  updateItem(id: string, patch: Partial<MediaItem>): Promise<MediaItem> {
    return request<MediaItem>(`/api/item/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  deleteItem(id: string, permanent = false): Promise<unknown> {
    return request('/api/delete', {
      method: 'POST',
      body: JSON.stringify({ ids: [id], permanent }),
    })
  },

  collections(): Promise<Collection[]> {
    // 后端返回 { collections: [...] }，在此解构为纯数组，
    // 否则调用方拿到的是对象，v-if="collections?.length" 恒为假
    return request<{ collections: Collection[] }>('/api/collections').then(
      (data) => data.collections,
    )
  },

  /** 分面统计（B-10）：返回各筛选维度的可选值与计数 */
  facets(params: Partial<ItemQuery> = {}): Promise<Facets> {
    return request<Facets>(`/api/facets${toQuery(params as Record<string, unknown>)}`)
  },

  // ---------- 上传与采集（REQ-05） ----------

  /** 上传文件；synchronous 仅用于需要立即拿到元数据的场景（CLI 兼容） */
  upload(
    file: File,
    opts: { title?: string; tags?: string; source?: string } = {},
  ): Promise<{ ok: boolean; count: number; items: MediaItem[] }> {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.title) fd.append('title', opts.title)
    if (opts.tags) fd.append('tags', opts.tags)
    if (opts.source) fd.append('source', opts.source)
    return request('/api/upload', { method: 'POST', body: fd })
  },

  /** 链接采集（走后台队列） */
  ingestUrl(url: string, opts: { title?: string; tags?: string } = {}): Promise<{
    ok: boolean
    job_id: number
  }> {
    return request('/api/ingest-url', {
      method: 'POST',
      body: JSON.stringify({ url, title: opts.title ?? '', tags: opts.tags ?? '' }),
    })
  },

  /** 批量操作：加标签 / 加入合集 / 移入回收站 */
  batch(
    ids: string[],
    action: string,
    extra: { tags?: string[]; collection_id?: number } = {},
  ): Promise<{ ok: boolean; count: number }> {
    return request('/api/items/batch', {
      method: 'POST',
      body: JSON.stringify({ ids, action, ...extra }),
    })
  },

  /** 导出（小批量同步返回 ZIP，大批量返回 202 + job_id） */
  async exportZip(
    ids: string[],
    opts: { preset?: string; format?: string; quality?: number } = {},
  ): Promise<{ kind: 'file'; blob: Blob } | { kind: 'job'; jobId: number; count: number }> {
    const res = await fetch('/api/items/download-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, ...opts }),
    })
    if (res.status === 202) {
      const body = (await res.json()) as { job_id: number; count: number }
      return { kind: 'job', jobId: body.job_id, count: body.count }
    }
    if (!res.ok) {
      let message = `导出失败（${res.status}）`
      try {
        const body = (await res.json()) as ApiError
        if (body?.detail) message = body.detail
      } catch {
        // 保留默认文案
      }
      throw new ApiRequestError(message, res.status)
    }
    return { kind: 'file', blob: await res.blob() }
  },
}
