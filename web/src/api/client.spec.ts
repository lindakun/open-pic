/**
 * API 客户端契约测试（R6）
 *
 * 重点覆盖后端响应结构与前端期望的解构关系：
 * /api/collections 返回 { collections: [...] }，client 层负责解构为数组，
 * 否则调用方 v-if="collections?.length" 恒为假（R6 修复的缺陷）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

function mockFetchOnce(body: unknown, status = 200) {
  const mock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api.collections 解构', () => {
  it('把 { collections: [...] } 解构为数组', async () => {
    const mock = mockFetchOnce({
      collections: [{ id: 1, name: '画板一', description: '', item_count: 0 }],
    })
    const list = await api.collections()
    expect(Array.isArray(list)).toBe(true)
    expect(list[0].name).toBe('画板一')
    // 请求打到了正确端点
    expect(mock.mock.calls[0][0]).toBe('/api/collections')
  })

  it('空合集列表返回空数组', async () => {
    mockFetchOnce({ collections: [] })
    const list = await api.collections()
    expect(list).toEqual([])
  })
})

describe('api.facets 参数序列化', () => {
  it('携带非空筛选参数，跳过空值', async () => {
    const mock = mockFetchOnce({
      kind: [], ext: [], orientation: [], platform: [], tag: [], size_class: [], total: 0,
    })
    await api.facets({ kind: 'video', ext: '', orientation: undefined })
    const url = mock.mock.calls[0][0] as string
    expect(url).toContain('kind=video')
    expect(url).not.toContain('ext=')
  })
})
