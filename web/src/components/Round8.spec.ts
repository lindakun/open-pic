/**
 * 循环第 3 轮（Round 8）回归测试
 *
 * 覆盖本轮修复：
 *   - 画板筛选 chip 使用后端 item_count 展示数量
 *   - 分面「清空」通过 reset 事件交给主页统一刷新
 *   - 分享深链指向首批之外的资产时仍能打开灯箱
 *   - 灯箱从视频切回图片后重新绑定滚轮缩放
 *   - 视频聚焦时方向键不再触发切换
 *   - 非首页资产的深链兜底（store.openFetchedItem）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import FacetPanel from './FacetPanel.vue'
import LightboxViewer from './LightboxViewer.vue'
import HomeView from '@/views/HomeView.vue'
import { useMediaStore } from '@/stores/media'
import { useFilterStore } from '@/stores/filters'
import type { MediaItem } from '@/api/types'
import type { Facets } from '@/stores/filters'

function makeItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'aaaaaa11',
    file: 'aaaaaa11.jpg',
    thumb: 'aaaaaa11.jpg',
    play_file: null,
    preview_file: null,
    kind: 'image',
    ext: '.jpg',
    name: 'photo.jpg',
    title: '晨雾山林',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '',
    size: 1024,
    width: 1600,
    height: 1200,
    aspect_ratio: 1.33,
    duration: 0,
    fps: 0,
    codec: '',
    dominant_color: '#334455',
    palette_json: '[]',
    exif_json: '{}',
    phash: '',
    ocr_text: '',
    views: 0,
    downloads: 0,
    ts: 1700000000,
    updated_at: 1700000000,
    deleted_at: null,
    tags: ['自然'],
    ...overrides,
  }
}

function emptyFacets(total = 1): Facets {
  return { kind: [], ext: [], orientation: [], platform: [], size_class: [], tag: [], total }
}

function stubFetch(extra: (url: string) => any = () => null) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const custom = extra(url)
    if (custom) return custom
    if (url.startsWith('/api/items')) {
      return { ok: true, status: 200, json: async () => ({ items: [makeItem()], total: 1 }) }
    }
    if (url.startsWith('/api/facets')) {
      return { ok: true, status: 200, json: async () => emptyFacets() }
    }
    if (url.startsWith('/api/home/featured')) {
      return { ok: true, status: 200, json: async () => ({ items: [] }) }
    }
    if (url.startsWith('/api/likes')) {
      return { ok: true, status: 200, json: async () => ({ ids: [] }) }
    }
    if (url.startsWith('/api/collections')) {
      return { ok: true, status: 200, json: async () => ({ collections: [] }) }
    }
    if (url.startsWith('/api/ai/status')) {
      return { ok: true, status: 200, json: async () => ({ available: false }) }
    }
    return { ok: true, status: 200, json: async () => ({}) }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'EventSource',
    class {
      addEventListener() {}
      close() {}
    },
  )
})

describe('Round 8: 画板计数与分面清空', () => {
  it('画板 chip 使用后端 item_count 展示数量', async () => {
    const wrapper = mount(FacetPanel, {
      props: {
        facets: emptyFacets(),
        collections: [
          {
            id: 1,
            name: '旅行',
            description: '',
            cover_item_id: null,
            created_at: 1,
            updated_at: 1,
            item_count: 7,
          },
        ],
      },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('旅行')
    expect(wrapper.find('.ml-chip__count').text()).toBe('7')
    wrapper.unmount()
  })

  it('点击清空通过 reset 事件交给主页统一处理', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const filters = useFilterStore()
    filters.setQ('海岸')
    const wrapper = mount(FacetPanel, {
      props: { facets: emptyFacets() },
      global: { plugins: [pinia] },
    })
    await wrapper.find('.facets__reset').trigger('click')
    expect(wrapper.emitted('reset')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('Round 8: 深链与灯箱交互', () => {
  it('openFetchedItem 将不在列表中的资产插入并打开灯箱', () => {
    const store = useMediaStore()
    store.items = [makeItem({ id: 'first001' })]
    store.total = 1
    store.openFetchedItem(makeItem({ id: 'deep0002', title: '深链资产' }))
    expect(store.currentItem?.id).toBe('deep0002')
    expect(store.items[0].id).toBe('deep0002')
  })

  it('/a/ 深链指向首批之外的资产时按 id 拉取并打开', async () => {
    const deep = makeItem({ id: 'deadbeef', title: '深链老图' })
    stubFetch((url) => {
      if (url.startsWith('/api/items')) {
        return { ok: true, status: 200, json: async () => ({ items: [makeItem()], total: 1 }) }
      }
      if (url.startsWith('/api/resolve/deadbeef')) {
        return { ok: true, status: 200, json: async () => ({ id: 'deadbeef' }) }
      }
      if (url.startsWith('/api/item/deadbeef')) {
        return { ok: true, status: 200, json: async () => deep }
      }
      return null
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: HomeView },
        { path: '/a/:slug', name: 'asset', component: HomeView },
      ],
    })
    await router.push('/a/asset-deadbeef')
    await router.isReady()
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()
    await new Promise((r) => setTimeout(r, 0))
    await flushPromises()
    const store = useMediaStore()
    expect(store.currentItem?.id).toBe('deadbeef')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('视频切回图片后滚轮缩放仍然生效（重新绑定手势）', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem({ kind: 'video', ext: '.mp4' }), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    await wrapper.setProps({ item: makeItem({ id: 'img00001', kind: 'image' }) })
    await wrapper.vm.$nextTick()
    const stage = wrapper.find('.lightbox__stage')
    stage.element.dispatchEvent(
      new WheelEvent('wheel', { deltaY: -100, clientX: 100, clientY: 100, bubbles: true, cancelable: true }),
    )
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__zoom-pill').exists()).toBe(true)
    wrapper.unmount()
  })

  it('视频聚焦时方向键交给原生播放器，不切换素材', async () => {
    const wrapper = mount(LightboxViewer, {
      props: {
        item: makeItem({ id: 'vid00001', kind: 'video', ext: '.mp4' }),
        hasPrev: true,
        hasNext: true,
      },
      attachTo: document.body,
    })
    const video = wrapper.find('video')
    ;(video.element as HTMLVideoElement).focus()
    video.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }),
    )
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('next')).toBeUndefined()
    wrapper.unmount()
  })
})
