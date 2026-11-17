/**
 * useScrollRestore 单元测试（REQ-V2-20 D-17）
 *
 * 重点验证「按锚点而非像素」：
 *   列数变化后仍定位到同一 itemId，而不是回到相同的 scrollTop。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearScrollAnchor,
  isSaveData,
  pageSizeFor,
  readScrollAnchor,
  restoreScrollAnchor,
  sampleAnchor,
  saveScrollAnchor,
} from './useScrollRestore'
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
  history.replaceState({}, '')
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('锚点存取', () => {
  it('写入后可从 history.state 读回', () => {
    saveScrollAnchor({ itemId: 'abc', ratio: 0.5 })
    expect(readScrollAnchor()).toEqual({ itemId: 'abc', ratio: 0.5 })
  })

  it('不污染 URL（只写 history.state）', () => {
    const before = location.search
    saveScrollAnchor({ itemId: 'abc', ratio: 0.2 })
    expect(location.search).toBe(before)
  })

  it('清除后读回 null', () => {
    saveScrollAnchor({ itemId: 'abc', ratio: 0.5 })
    clearScrollAnchor()
    expect(readScrollAnchor()).toBeNull()
  })
})

describe('锚点采样', () => {
  it('取第一个顶部进入视口的卡片（而非已滚出的上一张）', () => {
    const a = document.createElement('div')
    a.dataset.itemId = 'above'
    // jsdom 的 getBoundingClientRect 默认全 0，这里显式覆盖
    a.getBoundingClientRect = () => ({ top: -200, bottom: -100, height: 100 }) as DOMRect
    const b = document.createElement('div')
    b.dataset.itemId = 'straddling'
    b.getBoundingClientRect = () => ({ top: -50, bottom: 50, height: 100 }) as DOMRect
    const c = document.createElement('div')
    c.dataset.itemId = 'startsInView'
    c.getBoundingClientRect = () => ({ top: 10, bottom: 210, height: 200 }) as DOMRect
    document.body.append(a, b, c)

    // b 跨过顶部但 top<0，c 才是用户阅读的起点
    expect(sampleAnchor()?.itemId).toBe('startsInView')
  })

  it('容器内没有卡片时返回 null', () => {
    expect(sampleAnchor()).toBeNull()
  })
})

describe('锚点恢复', () => {
  it('锚点资产不在当前列表时不滚动', () => {
    const spy = vi.fn()
    vi.stubGlobal('scrollTo', spy)
    const ok = restoreScrollAnchor({ itemId: 'missing', ratio: 0 }, [makeItem('a')])
    expect(ok).toBe(false)
    expect(spy).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('锚点在列表内时安排滚动（列数变化仍定位同一资产）', async () => {
    const el = document.createElement('div')
    el.dataset.itemId = 'target'
    el.getBoundingClientRect = () => ({ top: 120, bottom: 420, height: 300 }) as DOMRect
    document.body.appendChild(el)

    const spy = vi.fn()
    vi.stubGlobal('scrollTo', spy)
    // 让 rAF 同步执行，断言不依赖时序
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })

    const ok = restoreScrollAnchor({ itemId: 'target', ratio: 0.5 }, [makeItem('target')])
    expect(ok).toBe(true)
    expect(spy).toHaveBeenCalled()
    // 目标 = rect.top + scrollY - height*ratio = 120 + scrollY - 150
    const arg = spy.mock.calls[0][0] as { top: number }
    expect(arg.top).toBe(Math.max(0, 120 + window.scrollY - 150))

    vi.unstubAllGlobals()
  })
})

describe('弱网降级', () => {
  it('saveData 为真时降为 24', () => {
    vi.stubGlobal('navigator', {
      ...navigator,
      connection: { saveData: true },
    })
    expect(isSaveData()).toBe(true)
    expect(pageSizeFor(48, 24)).toBe(24)
    vi.unstubAllGlobals()
  })

  it('无 connection 信息时保持默认', () => {
    vi.stubGlobal('navigator', { ...navigator, connection: undefined })
    expect(isSaveData()).toBe(false)
    expect(pageSizeFor(48, 24)).toBe(48)
    vi.unstubAllGlobals()
  })

  it('2g 网络视为弱网', () => {
    vi.stubGlobal('navigator', {
      ...navigator,
      connection: { effectiveType: '2g' },
    })
    expect(isSaveData()).toBe(true)
    vi.unstubAllGlobals()
  })
})
