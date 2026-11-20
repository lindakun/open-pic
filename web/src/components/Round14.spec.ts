/**
 * 循环第 10 轮回归测试
 *
 * 覆盖：
 *   - 列表视图标签胶囊在选择模式下不再吞掉勾选点击
 *   - 批量移入回收站后 toast 提供撤销，撤销调用 restore 接口
 *   - 分面面板与批量候选不向用户暴露内部状态标签「AI已标注」
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import MasonryGrid from './MasonryGrid.vue'
import BatchBar from './BatchBar.vue'
import FacetPanel from './FacetPanel.vue'
import { useToast } from '@/composables/useToast'
import type { MediaItem } from '@/api/types'
import type { Facets } from '@/stores/filters'

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
    tags: ['AI已标注', '人物'],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

describe('Round 14: 列表多选与撤销', () => {
  it('选择模式下点击列表标签胶囊发出 toggle 而非被吞掉', async () => {
    const wrapper = mount(MasonryGrid, {
      props: { items: [makeItem()], mode: 'list', selectable: true, selectedIds: [] },
    })
    await wrapper.find('.list-row__tag').trigger('click')
    expect(wrapper.emitted('toggle')?.[0]).toEqual(['aaaaaa11', false])
    wrapper.unmount()
  })

  it('非选择模式下点击列表标签仍按标签筛选', async () => {
    const wrapper = mount(MasonryGrid, {
      props: { items: [makeItem()], mode: 'list', selectable: false },
    })
    await wrapper.find('.list-row__tag').trigger('click')
    expect(wrapper.emitted('filter-tag')?.[0]).toEqual(['人物'])
    expect(wrapper.emitted('toggle')).toBeUndefined()
    wrapper.unmount()
  })

  it('移入回收站后 toast 提供撤销并调用 restore', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, count: 2 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(BatchBar, {
      props: { selected: ['a', 'b'] },
      attachTo: document.body,
    })
    const trash = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('移入回收站'))!
    await trash.trigger('click')
    await trash.trigger('click')
    await flushPromises()
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).action).toBe('delete')

    const { toasts, runAction } = useToast()
    expect(toasts.value[0].action?.label).toBe('撤销')
    runAction(toasts.value[0].id)
    await flushPromises()
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).action).toBe('restore')

    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})

describe('Round 14: 内部标签不面向用户', () => {
  it('分面标签组隐藏 AI已标注', async () => {
    setActivePinia(createPinia())
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div/>' } }],
    })
    await router.push('/')
    await router.isReady()
    const facets: Facets = {
      kind: [], ext: [], orientation: [], platform: [], size_class: [],
      tag: [
        { value: 'AI已标注', count: 10 },
        { value: '人物', count: 5 },
      ],
      total: 10,
    }
    const wrapper = mount(FacetPanel, { props: { facets } })
    expect(wrapper.text()).toContain('人物')
    expect(wrapper.text()).not.toContain('AI已标注')
    wrapper.unmount()
  })
})
