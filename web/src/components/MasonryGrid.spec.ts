/**
 * MasonryGrid 虚拟滚动测试（REQ-V2-20 D-17）
 *
 * 验收点 1 的离线断言：加载大量条目后，真实渲染的卡片数远少于总数。
 * 占位元素保证滚动条总高不变（验收 4 的零位移前提）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MasonryGrid from './MasonryGrid.vue'
import type { MediaItem } from '@/api/types'

function makeItem(i: number): MediaItem {
  return {
    id: `item${String(i).padStart(4, '0')}`,
    file: `f${i}.jpg`, thumb: `f${i}.jpg`, play_file: null, preview_file: null,
    kind: 'image', ext: '.jpg', name: `f${i}.jpg`, title: `资产${i}`, source: '',
    source_platform: 'local', author: '', notes: '', size: 100,
    width: 1200, height: 800, aspect_ratio: 1.5, duration: 0, fps: 0, codec: '',
    dominant_color: '#000000', palette_json: '[]', exif_json: '{}', phash: '',
    ocr_text: '', views: 0, downloads: 0, ts: 0, updated_at: 0, deleted_at: null,
  }
}

function mountGrid(count: number) {
  const items = Array.from({ length: count }, (_, i) => makeItem(i))
  return mount(MasonryGrid, {
    props: { items },
    global: {
      stubs: {
        // 卡片替换为轻量桩，避免图片与交互干扰计数
        MLMediaCard: { template: '<div class="card-stub" />' },
      },
    },
    attachTo: document.body,
  })
}

beforeEach(() => {
  // jsdom 不实现 ResizeObserver
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
})

describe('MasonryGrid 虚拟化', () => {
  it('大量条目下只渲染可视区附近的卡片', async () => {
    const wrapper = mountGrid(1000)
    await wrapper.vm.$nextTick()

    const cards = wrapper.findAll('.card-stub')
    const ghosts = wrapper.findAll('.masonry__ghost')

    expect(cards.length + ghosts.length).toBe(1000)
    // 可视区 ± 2 屏之外全部回收；首屏场景下渲染数应远小于总量
    expect(cards.length).toBeLessThan(200)
    expect(ghosts.length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('首屏前 4 张永不被回收（LCP 元素）', async () => {
    const wrapper = mountGrid(500)
    await wrapper.vm.$nextTick()
    const cells = wrapper.findAll('.masonry__cell')
    for (let i = 0; i < 4; i++) {
      expect(cells[i].find('.card-stub').exists()).toBe(true)
    }
    wrapper.unmount()
  })

  it('占位与卡片共用同一布局，总高度不受回收影响', async () => {
    const wrapper = mountGrid(300)
    await wrapper.vm.$nextTick()
    const container = wrapper.find('.masonry')
    const heightBefore = container.attributes('style')

    // 触发一次全量回收判定（滚到很远）
    Object.defineProperty(window, 'scrollY', { value: 100000, configurable: true })
    window.dispatchEvent(new Event('scroll'))
    await new Promise((r) => setTimeout(r, 120))
    await wrapper.vm.$nextTick()

    expect(container.attributes('style')).toBe(heightBefore)
    wrapper.unmount()
  })

  it('每个单元格带 data-item-id，供锚点恢复使用', async () => {
    const wrapper = mountGrid(10)
    await wrapper.vm.$nextTick()
    const cells = wrapper.findAll('.masonry__cell')
    expect(cells[0].attributes('data-item-id')).toBe('item0000')
    wrapper.unmount()
  })

  it('条目总数变化时布局与高度同步更新', async () => {
    const wrapper = mountGrid(20)
    await wrapper.vm.$nextTick()
    const before = wrapper.find('.masonry').attributes('style')

    await wrapper.setProps({ items: Array.from({ length: 40 }, (_, i) => makeItem(i)) })
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.masonry__cell').length).toBe(40)
    expect(wrapper.find('.masonry').attributes('style')).not.toBe(before)
    wrapper.unmount()
  })
})
