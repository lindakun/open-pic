/**
 * 循环第 2 轮（Round 7）UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import BatchBar from './BatchBar.vue'
import LightboxViewer from './LightboxViewer.vue'
import MasonryGrid from './MasonryGrid.vue'
import UploadPanel from './UploadPanel.vue'
import HomeView from '@/views/HomeView.vue'
import ReviewView from '@/views/ReviewView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
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
    title: '晨光山谷',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '',
    size: 2048,
    width: 1920,
    height: 1080,
    aspect_ratio: 1.78,
    duration: 0,
    fps: 0,
    codec: '',
    dominant_color: '#4c5050',
    palette_json: '[]',
    exif_json: '{}',
    phash: '',
    ocr_text: '',
    views: 0,
    downloads: 0,
    ts: 1700000000,
    updated_at: 1700000000,
    deleted_at: null,
    tags: ['风景', '壁纸'],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  setActivePinia(createPinia())
  localStorage.clear()
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

describe('Cycle 2: MasonryGrid 列表模式主色圆点去重、勾选框与标签快筛', () => {
  it('列表行仅渲染唯一主色筛选钮，支持多选勾选圈与点击标签直接筛选', async () => {
    const wrapper = mount(MasonryGrid, {
      props: {
        items: [makeItem()],
        mode: 'list',
        selectable: false,
      },
    })
    expect(wrapper.find('.list-row__color').exists()).toBe(false)
    expect(wrapper.findAll('.list-row__swatch')).toHaveLength(1)

    await wrapper.findAll('.list-row__tag')[0].trigger('click')
    expect(wrapper.emitted('filter-tag')?.[0]).toEqual(['风景'])

    await wrapper.setProps({ selectable: true, selectedIds: ['aaaaaa11'] })
    expect(wrapper.find('.list-row__check--on').text()).toBe('✓')
    wrapper.unmount()
  })
})

describe('Cycle 2: LightboxViewer 对比候选过滤视频与胶片条视频角标', () => {
  it('顶部图片对比条过滤掉视频条目，而底部胶片条保留视频并展示播放角标', async () => {
    const imgA = makeItem({ id: 'aaaaaa11', kind: 'image' })
    const vidB = makeItem({ id: 'bbbbbb22', kind: 'video', ext: '.mp4', duration: 15 })
    const imgC = makeItem({ id: 'cccccc33', kind: 'image' })
    const wrapper = mount(LightboxViewer, {
      props: {
        item: imgA,
        hasPrev: false,
        hasNext: true,
        candidates: [imgA, vidB, imgC],
      },
      attachTo: document.body,
    })

    // 顶部对比只出现 imgC（1 个圆点），不混入 vidB
    expect(wrapper.findAll('.cmp-dot')).toHaveLength(1)

    // 打开底部胶片条：包含全部 3 项，且视频项带播放角标
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'f' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.lb-film')).toHaveLength(3)
    expect(wrapper.findAll('.lb-film__vid')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('Cycle 2: BatchBar 多规格与格式导出面板', () => {
  it('可通过导出规格设置选择 1280px + WebP 并传递给打包接口', async () => {
    const blob = new Blob(['zip'], { type: 'application/zip' })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => blob,
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal(
      'URL',
      Object.assign(URL, {
        createObjectURL: vi.fn(() => 'blob:mock'),
        revokeObjectURL: vi.fn(),
      }),
    )
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = mount(BatchBar, {
      props: { selected: ['aaaaaa11'] },
      attachTo: document.body,
    })

    await wrapper.find('.batch__export-more').trigger('click')
    await wrapper.vm.$nextTick()

    // 选择第 3 档（1280px）+ WEBP 格式
    const presets = wrapper.findAll('.batch__preset-item')
    expect(presets).toHaveLength(4)
    await presets[2].trigger('click')
    await wrapper.vm.$nextTick()

    const webpBtn = wrapper.findAll('.batch__fmt-pills button').find((b) => b.text() === 'WEBP')!
    await webpBtn.trigger('click')
    expect(wrapper.find('.batch__export-badge').text()).toBe('1280·WEBP')

    const startBtn = wrapper.findAll('button').find((b) => b.text().includes('开始打包导出'))!
    await startBtn.trigger('click')
    await flushPromises()

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.preset).toBe('1280')
    expect(body.format).toBe('webp')

    clickSpy.mockRestore()
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})

describe('Cycle 2: UploadPanel 多条链接批量采集与主按钮视觉权重', () => {
  it('支持粘贴或输入多条空格分隔链接依次入队并使用 primary 主按钮', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, job_id: 99 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(UploadPanel, { props: { open: true }, attachTo: document.body })
    await wrapper.findAll('.up__tab')[1].trigger('click')
    await flushPromises()

    const urlInput = wrapper.find('input[type="url"]')
    await urlInput.setValue('https://example.com/1.jpg https://example.com/2.jpg')
    expect(wrapper.text()).toContain('(2)')

    const submitBtn = wrapper.findAll('.up__actions button').at(-1)!
    expect(submitBtn.classes()).toContain('ml-btn--primary')
    await submitBtn.trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})

describe('Cycle 2: HomeView 搜索历史方向键选词、空结果标签推荐与选片页视频宽高比', () => {
  it('搜索框支持 ArrowDown + Enter 选中历史词，零结果空态提供热门标签快筛', async () => {
    localStorage.setItem('medialib.searchHistory', JSON.stringify(['不存在的词']))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/items')) {
        const empty = url.includes('q=')
        return {
          ok: true,
          status: 200,
          json: async () => ({ items: empty ? [] : [makeItem()], total: empty ? 0 : 1 }),
        }
      }
      if (url.startsWith('/api/facets')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            kind: [],
            ext: [],
            orientation: [],
            platform: [],
            size_class: [],
            tag: [{ value: '人物', count: 12 }],
            total: 12,
          }),
        }
      }
      return { ok: true, status: 200, json: async () => ({ items: [], ids: [], collections: [], available: false }) }
    }))

    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'home', component: HomeView }],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await flushPromises()

    const input = wrapper.find('.wall-search__input')
    await input.trigger('focus')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.find('.wall-search__history-chip--active').exists()).toBe(true)
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    // 进入零结果空态，展示热门标签胶囊「#人物」
    expect(wrapper.find('.wall__empty-tag').text()).toBe('#人物')

    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('ReviewView 竖屏视频绑定真实宽高比避免控件挤压，NotFoundView 提供漫步入口', async () => {
    const vid = makeItem({ id: 'v1', kind: 'video', ext: '.mp4', width: 2160, height: 2880 })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '选片' }, items: [vid] }),
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div/>' } },
        { path: '/review/:token', name: 'review', component: { template: '<div/>' } },
      ],
    })
    await router.push('/review/tok')
    await router.isReady()

    const rv = mount(ReviewView, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
    const videoEl = rv.find('video.review__video')
    expect(videoEl.exists()).toBe(true)
    expect(videoEl.attributes('style')).toContain('2160 / 2880')
    rv.unmount()

    const nf = mount(NotFoundView, { global: { plugins: [router] } })
    expect(nf.findAll('.nf-btn')[1].text()).toContain('随机漫步')
    nf.unmount()
    vi.unstubAllGlobals()
  })
})
