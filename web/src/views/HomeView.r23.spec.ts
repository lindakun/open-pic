/**
 * R23 移动端回归：分面标签、清空态、吸顶全选/反选与 iOS 键盘偏移
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import HomeView from './HomeView.vue'
import FacetPanel from '@/components/FacetPanel.vue'
import BatchBar from '@/components/BatchBar.vue'
import { useFilterStore } from '@/stores/filters'
import type { MediaItem } from '@/api/types'
import type { Facets } from '@/stores/filters'

function makeItem(id: string, overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id,
    file: `${id}.jpg`,
    thumb: `${id}.jpg`,
    play_file: null,
    preview_file: null,
    kind: 'image',
    ext: '.jpg',
    name: `${id}.jpg`,
    title: id,
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

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'home', component: HomeView }],
  })
}

function stubFetch(items: MediaItem[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/items')) {
        return { ok: true, status: 200, json: async () => ({ items, total: items.length }) }
      }
      if (url.startsWith('/api/facets')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            kind: [{ value: 'image', count: items.length }],
            ext: [],
            orientation: [],
            platform: [],
            size_class: [],
            tag: [{ value: '自然', count: items.length }],
            total: items.length,
          }),
        }
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
    }),
  )
}

/** 只让 max-width 查询命中，模拟手机断点 */
function stubMobileMatchMedia() {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('max-width'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  }))
}

beforeEach(() => {
  vi.restoreAllMocks()
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
  window.scrollTo = vi.fn()
})

describe('R23 移动端分面与多选', () => {
  it('非标签分组的胶囊不预留排除按钮宽度，标签文字不会被压成 0', async () => {
    const facets: Facets = {
      kind: [{ value: 'image', count: 306 }],
      ext: [{ value: '.jpg', count: 300 }],
      orientation: [{ value: 'portrait', count: 200 }],
      platform: [],
      size_class: [],
      tag: [{ value: '自然', count: 120 }],
      total: 306,
    }
    const wrapper = mount(FacetPanel, {
      props: { facets },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    const items = wrapper.findAll('.facet__item')
    const tagItem = items.find((i) => i.text().includes('自然'))
    const kindItem = items.find((i) => i.text().includes('图片'))
    expect(kindItem).toBeTruthy()
    expect(kindItem!.classes()).not.toContain('facet__item--tag')
    expect(tagItem!.classes()).toContain('facet__item--tag')
    // 标签文字与计数同时存在，回归「只剩数字」的塌陷
    expect(kindItem!.find('.ml-chip__label').text()).toBe('图片')
    expect(kindItem!.find('.ml-chip__count').text()).toBe('306')
    wrapper.unmount()
  })

  it('没有可清空条件时禁用抽屉「清空全部」，有筛选时恢复可用', async () => {
    stubFetch([makeItem('a1')])
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()

    const reset = wrapper.find('.wall__facets-reset')
    expect(reset.attributes('disabled')).toBeDefined()

    const filters = useFilterStore()
    filters.toggleTag('自然')
    await flushPromises()
    expect(wrapper.find('.wall__facets-reset').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('多选时吸顶工具条提供全选/反选，不再依赖会滚出视口的页内选择条', async () => {
    stubFetch([makeItem('a1'), makeItem('a2'), makeItem('a3')])
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()

    await wrapper.find('.wall__select-toggle').trigger('click')
    const selectAll = wrapper.find('.wall__select-all-mobile')
    const invert = wrapper.find('.wall__select-invert-mobile')
    expect(selectAll.exists()).toBe(true)
    expect(invert.exists()).toBe(true)

    await selectAll.trigger('click')
    expect(wrapper.find('.wall__select-summary').text()).toContain('3')
    await invert.trigger('click')
    expect(wrapper.find('.wall__select-summary').text()).toContain('0')
    wrapper.unmount()
  })

  it('iOS 键盘压缩 visualViewport 时抽屉抬升到底部可见区上方', async () => {
    stubMobileMatchMedia()
    const listeners = new Map<string, () => void>()
    const vv = {
      width: 390,
      height: 420,
      offsetTop: 0,
      addEventListener: (name: string, fn: () => void) => listeners.set(name, fn),
      removeEventListener: (name: string) => listeners.delete(name),
    }
    vi.stubGlobal('visualViewport', vv)
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 844 })

    stubFetch([makeItem('a1')])
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()

    await wrapper.find('.wall__filter-toggle').trigger('click')
    await flushPromises()
    await wrapper.vm.$nextTick()

    const panel = wrapper.find('#facet-panel')
    expect(panel.attributes('style')).toContain('bottom: 424px')
    expect(panel.attributes('style')).toContain('max-height: 408px')
    wrapper.unmount()
  })

  it('手机批量条出现时把底部避让基线抬高，避免 Toast / 回顶被遮住', async () => {
    stubMobileMatchMedia()
    const wrapper = mount(BatchBar, {
      props: { selected: ['a1', 'a2'] },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    expect(document.documentElement.style.getPropertyValue('--batch-bar-offset')).toBe('136px')
    wrapper.unmount()
    expect(document.documentElement.style.getPropertyValue('--batch-bar-offset')).toBe('')
  })
})
