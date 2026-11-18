/**
 * 第 5 轮 UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import LightboxViewer from './LightboxViewer.vue'
import FacetPanel from './FacetPanel.vue'
import AppShell from './AppShell.vue'
import BatchBar from './BatchBar.vue'
import UploadPanel from './UploadPanel.vue'
import { useFilterStore } from '@/stores/filters'
import { pushRecent, clearRecent } from '@/composables/useRecent'
import type { MediaItem } from '@/api/types'

function makeItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'aaaaaa11',
    file: 'aaaaaa11.mp4',
    thumb: 'aaaaaa11.jpg',
    play_file: 'aaaaaa11_play.mp4',
    preview_file: null,
    kind: 'video',
    ext: '.mp4',
    name: 'clip.mp4',
    title: '城市延时',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '',
    size: 8 * 1024 * 1024,
    width: 1920,
    height: 1080,
    aspect_ratio: 1.78,
    duration: 12,
    fps: 60,
    codec: 'h264',
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
    tags: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  setActivePinia(createPinia())
  clearRecent()
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

describe('Round 5: LightboxViewer 视频帧率编码展示与静音控制', () => {
  it('视频规格展示 fps 与 codec，按 M 键切换静音', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem(), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    expect(wrapper.find('.lightbox__spec').text()).toContain('60fps')
    expect(wrapper.find('.lightbox__spec').text()).toContain('H264')

    const video = wrapper.find('video').element as HTMLVideoElement
    expect(video.muted).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'm' }))
    await wrapper.vm.$nextTick()
    expect(video.muted).toBe(true)
    wrapper.unmount()
  })
})

describe('Round 5: FacetPanel 自动展开已有筛选组', () => {
  it('URL 带 ext 筛选时，格式分组自动展开', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/browse', component: { template: '<div/>' } }],
    })
    await router.push('/browse')
    await router.isReady()
    const filters = useFilterStore()
    filters.setExt('.png')

    const wrapper = mount(FacetPanel, {
      props: {
        facets: {
          kind: [{ value: 'image', count: 5 }],
          orientation: [],
          size_class: [],
          platform: [],
          tag: [],
          ext: [{ value: '.png', count: 5 }],
          total: 5,
        },
      },
      global: { plugins: [router] },
    })

    const detailsList = wrapper.findAll('details.facet')
    const extDetails = detailsList.find((d) => d.text().includes('PNG'))!
    expect(extDetails.attributes('open')).toBeDefined()
    wrapper.unmount()
  })
})

describe('Round 5: AppShell 最近浏览相对时间', () => {
  it('刚刚浏览的记录展示相对时间「刚刚」', async () => {
    pushRecent({ id: 'rec1', title: '测试素材', kind: 'image' })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div/>' } },
        { path: '/browse', component: { template: '<div/>' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(AppShell, { global: { plugins: [router] }, attachTo: document.body })
    await wrapper.find('.icon-btn--recent').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.recent-item__meta').text()).toContain('刚刚')
    wrapper.unmount()
  })
})

describe('Round 5: UploadPanel 与 BatchBar 回车提交', () => {
  it('UploadPanel 链接采集输入合法链接按 Enter 直接提交', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, job_id: 12 }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(UploadPanel, { props: { open: true }, attachTo: document.body })
    await wrapper.findAll('.up__tab')[1].trigger('click')
    await flushPromises()
    const input = wrapper.find('input[type="url"]')
    await input.setValue('https://example.com/a.jpg')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalled()
    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('BatchBar 打标签输入框按 Enter 直接提交', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, count: 1 }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(BatchBar, { props: { selected: ['a'] }, attachTo: document.body })
    await wrapper.findAll('.batch__actions button')[0].trigger('click')
    await flushPromises()
    const input = wrapper.find('.batch__form input')
    await input.setValue('街拍')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalled()
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})
