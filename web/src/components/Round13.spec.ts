/**
 * 循环第 9 轮（R22）移动端回归：
 *   - 多选模式在触屏显示“点按多选”提示，桌面保留 Shift 提示
 *   - 分面抽屉打开后聚焦首个控件，关闭后焦点还给“筛选”按钮
 *   - 抽屉内输入框聚焦时按 Esc 也能关闭
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
            tag: Array.from({ length: 12 }, (_, i) => ({ value: `tag${i}`, count: 1 })),
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
    media: '(max-width: 900px)',
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

describe('Round 13: 多选触屏提示', () => {
  it('同时渲染 Shift 与点按两套提示文案', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem(), makeItem({ id: 'bbbbbb22' })])
    const wrapper = await mountHome()

    await wrapper.vm.$nextTick()

    const selectBtn = wrapper.find('.wall__select-toggle')
    expect(selectBtn.exists()).toBe(true)
    await selectBtn.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.wall__select-hint--mouse').text()).toContain('Shift')
    expect(wrapper.find('.wall__select-hint--touch').text()).toContain('点按')
    wrapper.unmount()
  })
})

describe('Round 13: 分面抽屉焦点管理', () => {
  it('打开后焦点进入抽屉，关闭后回到筛选按钮', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem()])
    const wrapper = await mountHome()

    const toggle = wrapper.find('.wall__filter-toggle')
    await toggle.trigger('click')
    await flushPromises()
    await wrapper.vm.$nextTick()

    const panel = wrapper.find('.wall__facets').element as HTMLElement
    expect(panel.contains(document.activeElement)).toBe(true)

    await wrapper.find('.wall__facets-done').trigger('click')
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(toggle.element)
    wrapper.unmount()
  })

  it('聚焦抽屉内输入框时 Esc 仍关闭抽屉', async () => {
    stubMobileMatchMedia()
    stubLibraryFetch([makeItem()])
    const wrapper = await mountHome()

    await wrapper.find('.wall__filter-toggle').trigger('click')
    await flushPromises()
    await wrapper.vm.$nextTick()

    const input = wrapper.find('.facet__tag-search')
    if (input.exists()) {
      ;(input.element as HTMLInputElement).focus()
      await input.trigger('keydown', { key: 'Escape' })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.wall__filter-toggle').attributes('aria-expanded')).toBe('false')
    }
    wrapper.unmount()
  })
})
