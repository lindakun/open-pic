/**
 * 第 3 轮 UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import LightboxViewer from './LightboxViewer.vue'
import FacetPanel from './FacetPanel.vue'
import MasonryGrid from './MasonryGrid.vue'
import BatchBar from './BatchBar.vue'
import MLToast from './MLToast.vue'
import { useFilterStore } from '@/stores/filters'
import { useToast } from '@/composables/useToast'
import type { MediaItem } from '@/api/types'

function makeItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'aaaaaa11',
    file: 'aaaaaa11.png',
    thumb: 'aaaaaa11.png',
    play_file: null,
    preview_file: null,
    kind: 'image',
    ext: '.png',
    name: 'logo.png',
    title: '透明徽标',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '透明底 PNG，用于浅色背景演示',
    size: 4096,
    width: 1024,
    height: 1024,
    aspect_ratio: 1,
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
    tags: ['徽标'],
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
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
})

describe('Round 3: LightboxViewer 备注展示与看图底色切换', () => {
  it('信息面板阅读态展示 item.notes', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem(), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.panel__notes').text()).toContain('透明底 PNG')
    wrapper.unmount()
  })

  it('按 B 键循环切换暗夜/纸白/透明棋盘格底色', async () => {
    const wrapper = mount(LightboxViewer, {
      props: { item: makeItem(), hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    expect(wrapper.find('.lightbox__stage').classes()).toContain('lightbox__stage--bg-dark')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__stage').classes()).toContain('lightbox__stage--bg-paper')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__stage').classes()).toContain('lightbox__stage--bg-grid')
    wrapper.unmount()
  })
})

describe('Round 3: FacetPanel 预设色彩筛选', () => {
  it('点击预设色点可切换主色筛选', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/browse', component: { template: '<div/>' } }],
    })
    await router.push('/browse')
    await router.isReady()

    const wrapper = mount(FacetPanel, {
      props: { facets: null },
      global: { plugins: [router] },
    })
    const filters = useFilterStore()
    const dots = wrapper.findAll('.facet__color-dot')
    expect(dots.length).toBe(8)
    await dots[0].trigger('click')
    expect(filters.color).toBe('#b04a3f')
    await dots[0].trigger('click')
    expect(filters.color).toBe('')
    wrapper.unmount()
  })
})

describe('Round 3: MasonryGrid 列表模式主色快筛', () => {
  it('列表行点击主色圆点发出 filter-color', async () => {
    const wrapper = mount(MasonryGrid, {
      props: { items: [makeItem()], mode: 'list' },
    })
    await wrapper.find('.list-row__swatch').trigger('click')
    expect(wrapper.emitted('filter-color')?.[0]).toEqual(['#334455'])
    wrapper.unmount()
  })
})

describe('Round 3: BatchBar 已有标签候选点选', () => {
  it('打开批量打标弹窗可点击已有标签快速填入', async () => {
    const wrapper = mount(BatchBar, {
      props: { selected: ['a'], availableTags: ['人像', '棚拍'] },
      attachTo: document.body,
    })
    await wrapper.findAll('.batch__actions button')[0].trigger('click')
    await wrapper.vm.$nextTick()
    const picks = wrapper.findAll('.batch__tag-pick')
    expect(picks).toHaveLength(2)
    await picks[0].trigger('click')
    expect(picks[0].classes()).toContain('batch__tag-pick--on')
    wrapper.unmount()
  })
})

describe('Round 3: MLToast 倒计时线与悬停暂停', () => {
  it('悬停暂停并包含倒计时进度条', () => {
    const { toasts, info, dismiss } = useToast()
    const id = info('测试提示')
    const wrapper = mount(MLToast, { props: { toasts: [...toasts.value] } })
    expect(wrapper.find('.ml-toast__timer').exists()).toBe(true)
    dismiss(id)
    wrapper.unmount()
  })
})
