/**
 * 第 4 轮 UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import LightboxViewer from './LightboxViewer.vue'
import MLMediaCard from './MLMediaCard.vue'
import SmartImage from './SmartImage.vue'
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
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

describe('Round 4: LightboxViewer 2图卷帘叠加对比', () => {
  it('选中 1 项形成 2 图对比时可切换卷帘对比并调节滑块', async () => {
    const a = makeItem({ id: 'aaaaaa11', title: '原片' })
    const b = makeItem({ id: 'bbbbbb22', title: '精修' })
    const wrapper = mount(LightboxViewer, {
      props: { item: a, hasPrev: false, hasNext: true, candidates: [a, b] },
      attachTo: document.body,
    })

    await wrapper.find('.cmp-dot').trigger('click')
    await wrapper.vm.$nextTick()
    const splitBtn = wrapper.findAll('.cmp-clear').find((el) => el.text().includes('卷帘'))!
    expect(splitBtn.exists()).toBe(true)

    await splitBtn.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__split-box').exists()).toBe(true)
    expect(wrapper.find('.lightbox__split-range').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('Round 4: MLMediaCard 仅限个人使用卡片角标', () => {
  it('commercial_ok === 0 时渲染个人使用提示角标', () => {
    const card = mount(MLMediaCard, {
      props: { item: makeItem({ commercial_ok: 0 }) },
    })
    expect(card.find('.ml-card__personal').text()).toBe('个人')
    card.unmount()
  })
})

describe('Round 4: SmartImage 失败态重试提示', () => {
  it('加载失败时包含可读的重试标签', async () => {
    const wrapper = mount(SmartImage, { props: { id: 'x1' } })
    await wrapper.find('img').trigger('error')
    expect(wrapper.find('.smart-image__failed-label').text()).toBe('点击重试')
    wrapper.unmount()
  })
})

describe('Round 4: ReviewView 复制选中清单', () => {
  it('有选中项时渲染复制选中清单按钮并可触发复制', async () => {
    const execSpy = vi.fn().mockReturnValue(true)
    document.execCommand = execSpy
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        link: { title: '选片集' },
        items: [{ ...makeItem({ id: 'aaaaaa11', title: '封面图' }), review_state: 'selected', review_note: '加急' }],
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

    const copyBtn = wrapper.find('.review__copy-summary')
    expect(copyBtn.exists()).toBe(true)
    await copyBtn.trigger('click')
    await flushPromises()
    expect(copyBtn.text()).toContain('已复制选中清单')
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})

describe('Round 4: NotFoundView 排版与入口', () => {
  it('展示插画与返回首页、浏览入口', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div/>' } },
        { path: '/browse', component: { template: '<div/>' } },
      ],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(NotFoundView, { global: { plugins: [router] } })
    expect(wrapper.find('.not-found__art').exists()).toBe(true)
    expect(wrapper.findAll('.nf-btn')).toHaveLength(2)
    wrapper.unmount()
  })
})
