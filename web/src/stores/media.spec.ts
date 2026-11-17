/**
 * 首页精选置顶测试（REQ-V2-20 A-02 遗留项）
 *
 * 语义：精选只改变顺序，不改变列表内容；
 * 精选项按人工排布在前，其余保持原有时间倒序。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMediaStore } from './media'
import type { MediaItem } from '@/api/types'

function makeItem(id: string): MediaItem {
  return {
    id, file: `${id}.jpg`, thumb: `${id}.jpg`, play_file: null, preview_file: null,
    kind: 'image', ext: '.jpg', name: `${id}.jpg`, title: id, source: '',
    source_platform: 'local', author: '', notes: '', size: 100, width: 100,
    height: 100, aspect_ratio: 1, duration: 0, fps: 0, codec: '',
    dominant_color: '#000000', palette_json: '[]', exif_json: '{}', phash: '',
    ocr_text: '', views: 0, downloads: 0, ts: 0, updated_at: 0, deleted_at: null,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.restoreAllMocks()
})

describe('promoteFeatured', () => {
  it('精选项按人工顺序前置，其余保持原序', async () => {
    const store = useMediaStore()
    store.items = ['a', 'b', 'c', 'd'].map(makeItem)

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [makeItem('d'), makeItem('b')] }),
    }))

    await store.promoteFeatured()
    expect(store.items.map((i) => i.id)).toEqual(['d', 'b', 'a', 'c'])
    vi.unstubAllGlobals()
  })

  it('精选接口失败时列表保持原样', async () => {
    const store = useMediaStore()
    store.items = ['a', 'b'].map(makeItem)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')))

    await store.promoteFeatured()
    expect(store.items.map((i) => i.id)).toEqual(['a', 'b'])
    vi.unstubAllGlobals()
  })

  it('无精选时不做改动', async () => {
    const store = useMediaStore()
    store.items = ['a', 'b'].map(makeItem)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ items: [] }),
    }))

    await store.promoteFeatured()
    expect(store.items.map((i) => i.id)).toEqual(['a', 'b'])
    vi.unstubAllGlobals()
  })

  it('精选项不在当前已加载列表时，仅插入存在的条目', async () => {
    const store = useMediaStore()
    store.items = ['a'].map(makeItem)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ items: [makeItem('z'), makeItem('a')] }),
    }))

    await store.promoteFeatured()
    // 精选返回的 z 与 a 都会出现，z 在前
    expect(store.items.map((i) => i.id)).toEqual(['z', 'a'])
    vi.unstubAllGlobals()
  })
})
