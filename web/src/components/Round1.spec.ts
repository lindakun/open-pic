/**
 * 第 1 轮 UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import FacetPanel from './FacetPanel.vue'
import LightboxViewer from './LightboxViewer.vue'
import MLMediaCard from './MLMediaCard.vue'
import ReviewView from '@/views/ReviewView.vue'
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
    source: 'https://www.unsplash.com/photos/some-very-long-photo-slug-id-123456',
    source_platform: 'unsplash',
    author: '作者',
    notes: '',
    size: 2 * 1024 * 1024,
    width: 3840,
    height: 2160,
    aspect_ratio: 1.78,
    duration: 0,
    fps: 0,
    codec: '',
    dominant_color: '#334455',
    palette_json: '["#112233","#445566"]',
    exif_json: '{}',
    phash: '',
    ocr_text: '',
    views: 0,
    downloads: 0,
    ts: 1700000000,
    updated_at: 1700000000,
    deleted_at: null,
    tags: ['海', '风景'],
    ...overrides,
  }
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
})

describe('Round 1: FacetPanel 标签快速筛选', () => {
  it('标签超过 8 个时渲染标签过滤框并实时过滤标签', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/browse', component: { template: '<div/>' } }],
    })
    await router.push('/browse')
    await router.isReady()

    const tags = Array.from({ length: 10 }, (_, i) => ({
      value: i === 9 ? 'cyberpunk' : `tag-${i}`,
      count: 3,
    }))
    const wrapper = mount(FacetPanel, {
      props: {
        facets: {
          kind: [],
          ext: [],
          orientation: [],
          platform: [],
          size_class: [],
          tag: tags,
          total: 30,
        },
      },
      global: { plugins: [router] },
    })

    const search = wrapper.find('.facet__tag-search')
    expect(search.exists()).toBe(true)
    await search.setValue('cyber')
    await flushPromises()

    expect(wrapper.text()).toContain('cyberpunk')
    expect(wrapper.text()).not.toContain('tag-0')
    wrapper.unmount()
  })
})

describe('Round 1: MLMediaCard 画质与格式角标', () => {
  it('4K 图片渲染 4K 角标，GIF 渲染 GIF 角标', () => {
    const card4k = mount(MLMediaCard, { props: { item: makeItem({ width: 3840, height: 2160 }) } })
    expect(card4k.find('.ml-card__fmt').text()).toBe('4K')
    card4k.unmount()

    const cardGif = mount(MLMediaCard, { props: { item: makeItem({ ext: '.gif', width: 640, height: 480 }) } })
    expect(cardGif.find('.ml-card__fmt').text()).toBe('GIF')
    cardGif.unmount()
  })
})

describe('Round 1: LightboxViewer 胶片条与编辑 Esc 保护', () => {
  it('按 F 键切换胶片快速跳转条并可点击切图', async () => {
    const cands = [makeItem({ id: 'aaaaaa11' }), makeItem({ id: 'bbbbbb22', title: '山脊' })]
    const wrapper = mount(LightboxViewer, {
      props: { item: cands[0], hasPrev: false, hasNext: true, candidates: cands },
      attachTo: document.body,
    })

    expect(wrapper.find('.lightbox__filmstrip').exists()).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'f' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__filmstrip').exists()).toBe(true)
    await wrapper.findAll('.lb-film')[1].trigger('click')
    expect(wrapper.emitted('select-item')?.[0]?.[0]).toMatchObject({ id: 'bbbbbb22' })
    wrapper.unmount()
  })

  it('行内编辑态按 Esc 仅退出编辑而不关闭灯箱', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem(), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()
    await wrapper.find('.panel__edit-btn').trigger('click')
    expect(wrapper.find('.panel__form').exists()).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.panel__form').exists()).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
    wrapper.unmount()
  })

  it('来源链接显示精简域名与路径摘要', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem(), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()
    const sourceText = wrapper.find('.panel__source').text()
    expect(sourceText).toContain('unsplash.com')
    expect(sourceText).toContain('↗')
    wrapper.unmount()
  })
})

describe('Round 1: ReviewView 胶片过滤与 Esc 退出放大', () => {
  it('支持按状态过滤胶片条与 Esc 退出放大', async () => {
    const reviewItems = [
      makeItem({ id: 'aaaaaa11', title: '未标记图' }),
      { ...makeItem({ id: 'bbbbbb22', title: '已选图' }), review_state: 'selected' },
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '选片' }, items: reviewItems }),
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/:token', name: 'review', component: { template: '<div/>' } }],
    })
    await router.push('/review/tok')
    await router.isReady()

    const wrapper = mount(ReviewView, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()

    // 点击放大后按 Esc 还原
    await wrapper.find('.review__img').trigger('click')
    expect(wrapper.find('.review__figure--zoomed').exists()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.review__figure--zoomed').exists()).toBe(false)

    // 过滤只看已选中
    const filters = wrapper.findAll('.film-filter')
    await filters[2].trigger('click')
    expect(wrapper.findAll('.film')).toHaveLength(1)

    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})
