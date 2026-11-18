/**
 * 第 2 轮 UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import MLMediaCard from './MLMediaCard.vue'
import UploadPanel from './UploadPanel.vue'
import LightboxViewer from './LightboxViewer.vue'
import AppShell from './AppShell.vue'
import ReviewView from '@/views/ReviewView.vue'
import { pushRecent, clearRecent } from '@/composables/useRecent'
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
    title: '海岸线',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '',
    size: 1024,
    width: 1200,
    height: 800,
    aspect_ratio: 1.5,
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
    tags: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  clearRecent()
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

describe('Round 2: MLMediaCard 底栏均衡展示与 Shift 透传', () => {
  it('多标签时展示首标签与 +N，无标签时回退作者或平台', () => {
    const c1 = mount(MLMediaCard, { props: { item: makeItem({ tags: ['海', '日落', '胶片'] }) } })
    expect(c1.find('.ml-card__tag').text()).toBe('海')
    expect(c1.find('.ml-card__tag-more').text()).toBe('+2')
    c1.unmount()

    const c2 = mount(MLMediaCard, { props: { item: makeItem({ tags: [], author: '摄影师A' }) } })
    expect(c2.find('.ml-card__tag').text()).toBe('摄影师A')
    c2.unmount()

    const c3 = mount(MLMediaCard, { props: { item: makeItem({ tags: [], source_platform: 'unsplash' }) } })
    expect(c3.find('.ml-card__tag').text()).toBe('unsplash')
    c3.unmount()
  })

  it('选择模式下 Shift+点击透传 true 参数', async () => {
    const card = mount(MLMediaCard, {
      props: { item: makeItem(), selectable: true },
    })
    await card.find('.ml-card__trigger').trigger('click', { shiftKey: true })
    expect(card.emitted('toggle')?.[0]).toEqual(['aaaaaa11', true])
    card.unmount()
  })
})

describe('Round 2: UploadPanel 常用标签点选', () => {
  it('点击推荐标签可切换追加或移除', async () => {
    const wrapper = mount(UploadPanel, {
      props: { open: true, suggestedTags: ['城市', '夜景'] },
      attachTo: document.body,
    })
    const pills = wrapper.findAll('.up__tag-pill')
    expect(pills).toHaveLength(2)

    await pills[0].trigger('click')
    expect(pills[0].classes()).toContain('up__tag-pill--on')
    await pills[1].trigger('click')
    await pills[0].trigger('click')
    expect(pills[0].classes()).not.toContain('up__tag-pill--on')
    expect(pills[1].classes()).toContain('up__tag-pill--on')
    wrapper.unmount()
  })
})

describe('Round 2: LightboxViewer 纯净看图模式 (H)', () => {
  it('按 H 键隐藏控制条并出现恢复角标，再按 Esc 仅恢复控件而不关闭灯箱', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem(), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })

    expect(wrapper.find('.lightbox__restore').exists()).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'h' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__restore').exists()).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__restore').exists()).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('Round 2: AppShell 最近浏览计数与缩略图兜底', () => {
  it('打开最近浏览抽屉展示条数，图片加载失败切占位图标', async () => {
    pushRecent({ id: 'rec12345', title: '测试图', kind: 'image' })
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

    expect(wrapper.find('.recent-summary').text()).toContain('1')
    await wrapper.find('.recent-item__thumb').trigger('error')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.recent-item__thumb--fallback').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('Round 2: ReviewView 进度计数与主题按钮', () => {
  it('展示已审阅进度数字与主题切换按钮', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        link: { title: '审片集' },
        items: [
          makeItem({ id: 'aaaaaa11' }),
          { ...makeItem({ id: 'bbbbbb22' }), review_state: 'selected' },
        ],
      }),
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/:token', component: { template: '<div/>' } }],
    })
    await router.push('/review/tok')
    await router.isReady()

    const wrapper = mount(ReviewView, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.find('.review__progress-text').text()).toContain('1 / 2')
    expect(wrapper.find('.review__theme').exists()).toBe(true)
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})
