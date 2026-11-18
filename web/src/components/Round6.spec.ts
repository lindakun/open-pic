/**
 * 循环第 1 轮（Round 6）UI/UX 优化单元测试
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppShell from './AppShell.vue'
import BatchBar from './BatchBar.vue'
import FacetPanel from './FacetPanel.vue'
import MLMediaCard from './MLMediaCard.vue'
import HomeView from '@/views/HomeView.vue'
import ReviewView from '@/views/ReviewView.vue'
import { useFilterStore } from '@/stores/filters'
import { useTheme } from '@/composables/useTheme'
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
    name: '2122490101926445086_01_HXSZeVdboAAletI.jpg',
    title: '2122490101926445086_01_HXSZeVdboAAletI',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '',
    size: 1024,
    width: 1440,
    height: 1919,
    aspect_ratio: 0.75,
    duration: 0,
    fps: 0,
    codec: '',
    dominant_color: '#3f2827',
    palette_json: '[]',
    exif_json: '{}',
    phash: '',
    ocr_text: '',
    views: 0,
    downloads: 0,
    ts: 1700000000,
    updated_at: 1700000000,
    deleted_at: null,
    tags: ['人物', 'X抓取'],
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

describe('Cycle 1: BatchBar 批量移除标签专属语义与已选标签提取', () => {
  it('移除标签模式显示移除专属提示、优先列出已选素材包含的标签并使用危险强调样式', async () => {
    const wrapper = mount(BatchBar, {
      props: {
        selected: ['a', 'b'],
        availableTags: ['全库标签'],
        selectedTags: ['人物', 'X抓取'],
      },
      attachTo: document.body,
    })

    const removeBtn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('移除标签'))!
    await removeBtn.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('将从已选的 2 项中移除匹配的标签')
    expect(wrapper.text()).toContain('已选素材包含的标签')
    const picks = wrapper.findAll('.batch__tag-pick')
    expect(picks.map((p) => p.text())).toEqual(['人物', 'X抓取'])

    await picks[0].trigger('click')
    expect(picks[0].classes()).toContain('batch__tag-pick--remove')
    expect(wrapper.text()).toContain('确认移除')
    wrapper.unmount()
  })
})

describe('Cycle 1: FacetPanel 色彩筛选当前色值展示与一键清除', () => {
  it('激活主色（含非预设任意 HEX）时展示色值胶囊与清除按钮', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div/>' } }],
    })
    await router.push('/')
    await router.isReady()

    const filters = useFilterStore()
    filters.setColor('#4c5050')

    const wrapper = mount(FacetPanel, {
      props: { facets: null },
      global: { plugins: [router] },
    })

    expect(wrapper.find('.facet__color-current').text()).toContain('#4C5050')
    await wrapper.find('.facet__color-clear').trigger('click')
    expect(filters.color).toBe('')
    wrapper.unmount()
  })
})

describe('Cycle 1: HomeView 搜索历史单条删除与喜欢余量精确展示', () => {
  it('支持单条移除搜索历史记录，且只看喜欢提示剩余未加载项数而非总库数', async () => {
    localStorage.setItem('medialib.searchHistory', JSON.stringify(['壁纸', '夜景']))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/items')) {
        return { ok: true, status: 200, json: async () => ({ items: [makeItem()], total: 182 }) }
      }
      if (url.startsWith('/api/likes')) {
        return { ok: true, status: 200, json: async () => ({ ids: ['aaaaaa11'] }) }
      }
      if (url.startsWith('/api/facets')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ kind: [], ext: [], orientation: [], platform: [], size_class: [], tag: [], total: 182 }),
        }
      }
      return { ok: true, status: 200, json: async () => ({ items: [], collections: [], available: false }) }
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

    // 聚焦搜索框，展示历史并单条移除「壁纸」
    await wrapper.find('.wall-search__input').trigger('focus')
    expect(wrapper.findAll('.wall-search__history-chip')).toHaveLength(2)
    await wrapper.findAll('.wall-search__history-del')[0].trigger('mousedown')
    expect(wrapper.findAll('.wall-search__history-chip')).toHaveLength(1)
    expect(wrapper.find('.wall-search__history').text()).toContain('夜景')

    // 切换只看喜欢：total=182, loaded=1 -> 剩余 181 项（而非 182 项）
    const likeBtn = wrapper.findAll('.wall__pill-btn').find((b) => b.text().includes('只看喜欢'))!
    await likeBtn.trigger('click')
    expect(wrapper.find('.wall__liked-more').text()).toContain('181')

    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})

describe('Cycle 1: 主题切换直觉化、卡片长标题提示与选片页语言切换', () => {
  it('auto 模式下首次点击主题切换必定立即翻转实际明暗态', () => {
    const theme = useTheme()
    theme.set('auto')
    const initialResolved = theme.resolved.value
    theme.cycle()
    expect(theme.resolved.value).not.toBe(initialResolved)
  })

  it('卡片长无空格标题携带完整 title 属性且管理后台链接带尾斜杠', async () => {
    const card = mount(MLMediaCard, { props: { item: makeItem() } })
    expect(card.find('.ml-card__title').attributes('title')).toBe('2122490101926445086_01_HXSZeVdboAAletI')
    card.unmount()

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div/>' } }],
    })
    await router.push('/')
    await router.isReady()
    const shell = mount(AppShell, { global: { plugins: [router] } })
    expect(shell.find('.admin-link').attributes('href')).toBe('/admin/')
    shell.unmount()
  })

  it('ReviewView 提供单行紧凑工作台与中英切换按钮', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '线上验证' }, items: [makeItem()] }),
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/:token', name: 'review', component: { template: '<div/>' } }],
    })
    await router.push('/review/tok')
    await router.isReady()
    const wrapper = mount(ReviewView, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()

    expect(wrapper.find('.review__workbench').exists()).toBe(true)
    expect(wrapper.find('.review__lang').exists()).toBe(true)
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})
