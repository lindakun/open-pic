/**
 * 循环第 8 轮（R21）移动端回归：
 *   - 窄屏分面改为底部抽屉，可通过「查看 N 项」或 Esc 收起
 *   - 工具条密度三键折叠为循环按钮，移动端仍可切换 S/M/L
 *   - 移动端操作按钮保留 aria-label，隐藏文字不影响可访问性
 *   - 隐藏的 AI 以图搜图输入具备可读标签
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
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
      { path: '/browse', name: 'browse', redirect: (to) => ({ name: 'home', query: to.query }) },
      { path: '/a/:slug', name: 'asset', component: HomeView },
    ],
  })
}

function stubLibraryFetch(items: MediaItem[]) {
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

function stubMobileMatchMedia() {
  const mql = {
    matches: true,
    media: '(max-width: 680px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(mql))
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue(mql),
  })
  return mql
}

async function mountHome() {
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
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
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

describe('Round 12: 移动端分面抽屉', () => {
  it('窄屏打开筛选显示抽屉头部，点击「查看 N 项」收起', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem()])
    const wrapper = await mountHome()

    const facets = wrapper.find('.wall__facets')
    expect(facets.attributes('style') ?? '').toContain('display: none')
    await wrapper.find('.wall__filter-toggle').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.wall__facets').attributes('style') ?? '').not.toContain('display: none')
    const done = wrapper.find('.wall__facets-done')
    expect(done.exists()).toBe(true)
    expect(done.text()).toContain('查看')
    expect(wrapper.find('.wall__facets').attributes('role')).toBe('dialog')

    await done.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.wall__filter-toggle').attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })

  it('Esc 收起移动端分面抽屉', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem()])
    const wrapper = await mountHome()

    await wrapper.find('.wall__filter-toggle').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.wall__filter-toggle').attributes('aria-expanded')).toBe('true')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.wall__filter-toggle').attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })
})

describe('Round 12: 移动端工具条', () => {
  it('密度循环按钮按 S → M → L 轮换并写入本地偏好', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem()])
    const wrapper = await mountHome()

    const cycle = wrapper.find('.wall__density-cycle')
    expect(cycle.exists()).toBe(true)
    expect(cycle.text()).toBe('M')

    await cycle.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.wall__density-cycle').text()).toBe('L')
    expect(localStorage.getItem('medialib.density')).toBe('spacious')

    await wrapper.find('.wall__density-cycle').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.wall__density-cycle').text()).toBe('S')
    wrapper.unmount()
  })

  it('图标化操作保留可读名称且隐藏复制文案', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem()])
    const wrapper = await mountHome()

    const upload = wrapper.find('.wall__upload-btn')
    expect(upload.attributes('aria-label')).toBe('上传')
    expect(upload.find('.wall__pill-label').text()).toBe('上传')

    const like = wrapper.find('.wall__like-toggle')
    expect(like.attributes('aria-label')).toBe('只看喜欢')

    const aiInput = wrapper.find('input[accept="image/*"]')
    expect(aiInput.attributes('aria-label')).toBeTruthy()
    wrapper.unmount()
  })
})
