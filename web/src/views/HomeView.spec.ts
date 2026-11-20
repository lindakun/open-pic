/**
 * 单主页融合测试：零页签顶栏 + 默认全屏看图 + 按需筛选 + /browse 兼容跳转
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppShell from '@/components/AppShell.vue'
import HomeView from './HomeView.vue'
import type { MediaItem } from '@/api/types'

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

function makeTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      {
        path: '/browse',
        name: 'browse',
        redirect: (to) => ({ name: 'home', query: to.query, replace: true }),
      },
      { path: '/a/:slug', name: 'asset', component: HomeView },
    ],
  })
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

function stubLibraryFetch(items: MediaItem[], featured: MediaItem[] = []) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/items')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ items, total: items.length }),
      }
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
      return {
        ok: true,
        status: 200,
        json: async () => ({ items: featured }),
      }
    }
    if (url.startsWith('/api/likes')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ ids: [] }),
      }
    }
    if (url.startsWith('/api/collections')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ collections: [] }),
      }
    }
    if (url.startsWith('/api/ai/status')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ available: false }),
      }
    }
    return { ok: true, status: 200, json: async () => ({}) }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('单主页融合（无顶栏重复页签 + 默认全屏看图 + 按需筛选）', () => {
  it('顶栏移除图墙/浏览重复页签，并将搜索框挂载到顶栏居中槽位', async () => {
    stubLibraryFetch([makeItem()])
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = makeTestRouter()
    await router.push('/')
    await router.isReady()

    const wrapper = mount(AppShell, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.site-nav').exists()).toBe(false)
    expect(wrapper.find('#site-header-center .wall-search__input').exists()).toBe(true)

    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('默认收起左侧筛选面板并将精选置顶，点击「筛选」按钮按需展开侧栏', async () => {
    const a = makeItem({ id: 'normal01', title: '普通图' })
    const b = makeItem({ id: 'feat0002', title: '精选图' })
    stubLibraryFetch([a, b], [b])

    const pinia = createPinia()
    setActivePinia(pinia)
    const router = makeTestRouter()
    await router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()

    // 默认单栏全宽，不展开分面侧栏
    expect(wrapper.find('.wall__layout--facets').exists()).toBe(false)
    const filterToggle = wrapper.find('.wall__filter-toggle')
    expect(filterToggle.attributes('aria-expanded')).toBe('false')

    // 精选已前置到首位
    const cards = wrapper.findAll('.ml-card')
    expect(cards.length).toBe(2)
    expect(cards[0].text()).toContain('精选图')

    // 点击「筛选」展开分面侧栏
    await filterToggle.trigger('click')
    expect(filterToggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.wall__layout--facets').exists()).toBe(true)

    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('多选支持反选，打开批量弹层时 Esc 不退出选择模式', async () => {
    stubLibraryFetch([
      makeItem({ id: 'pick0001' }),
      makeItem({ id: 'pick0002' }),
      makeItem({ id: 'pick0003' }),
    ])
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = makeTestRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()

    await wrapper.find('.wall__select-toggle').trigger('click')
    await wrapper.findAll('.ml-card__trigger')[0].trigger('click')
    expect(wrapper.find('.wall__select-summary').text()).toContain('1')
    await wrapper.find('.wall__select-bar').findAll('button')[1].trigger('click')
    expect(wrapper.find('.wall__select-summary').text()).toContain('2')

    const dialog = document.createElement('dialog')
    dialog.open = true
    document.body.appendChild(dialog)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.wall__select-toggle').attributes('aria-pressed')).toBe('true')
    dialog.remove()

    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('旧 /browse?tag=自然 链接自动携带查询参数归并到主页 /', async () => {
    stubLibraryFetch([makeItem()])
    const router = makeTestRouter()
    await router.push('/browse?tag=自然&sort=views')
    await router.isReady()

    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.query).toEqual({
      tag: '自然',
      sort: 'views',
    })
    vi.unstubAllGlobals()
  })
})
