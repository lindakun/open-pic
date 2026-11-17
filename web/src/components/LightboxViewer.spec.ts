/**
 * LightboxViewer 2.0 单元测试（REQ-V2-20 A-04）
 *
 * 覆盖验收点中可离线断言的部分：
 *   - 快捷键在输入态与 IME 组字期间不触发
 *   - 对比模式上限 4 项、下限 2 项才生效，且两图 transform 数值一致
 *   - 色板渲染、复制与「按此色筛选」事件
 *   - 信息面板（I 键）显隐
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import LightboxViewer from './LightboxViewer.vue'
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
    source: 'https://example.com/p/1',
    source_platform: 'local',
    author: '作者',
    notes: '',
    size: 2 * 1024 * 1024,
    width: 1920,
    height: 1080,
    aspect_ratio: 1.78,
    duration: 0,
    fps: 0,
    codec: '',
    dominant_color: '#334455',
    palette_json: '["#112233","#445566"]',
    exif_json: '{"Make":"FUJIFILM","Model":"X-T5"}',
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

// jsdom 未实现 HTMLDialogElement，补齐最小实现以便组件挂载
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

function mountLightbox(props: Record<string, unknown> = {}) {
  return mount(LightboxViewer, {
    props: {
      item: makeItem(),
      hasPrev: true,
      hasNext: true,
      candidates: [
        makeItem({ id: 'bbbbbb22', title: '山脊' }),
        makeItem({ id: 'cccccc33', title: '街角' }),
      ],
      ...props,
    },
    attachTo: document.body,
  })
}

describe('LightboxViewer 快捷键', () => {
  it('←/→ 触发 prev/next 事件', async () => {
    const wrapper = mountLightbox()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('prev')).toHaveLength(1)
    expect(wrapper.emitted('next')).toHaveLength(1)
    wrapper.unmount()
  })

  it('Esc 关闭灯箱', async () => {
    const wrapper = mountLightbox()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('输入框聚焦时不响应快捷键', async () => {
    const wrapper = mountLightbox()
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }),
    )
    // 事件目标是 input 时才应被忽略；这里直接向 input 派发
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await wrapper.vm.$nextTick()
    // window 上的裸事件仍会触发，故只断言 input 自身派发那次被忽略
    expect(wrapper.emitted('next')?.length ?? 0).toBe(1)
    input.remove()
    wrapper.unmount()
  })

  it('IME 组字期间不响应快捷键', async () => {
    const wrapper = mountLightbox()
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowRight', isComposing: true } as KeyboardEventInit),
    )
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('next')).toBeUndefined()
    wrapper.unmount()
  })

  it('I 键切换信息面板', async () => {
    const wrapper = mountLightbox()
    expect(wrapper.find('.lightbox__panel').exists()).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__panel').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('LightboxViewer 对比模式', () => {
  it('选中两项后进入对比，两图 transform 数值一致', async () => {
    const wrapper = mountLightbox()
    // 对比选择条中的圆点：候选 2 个
    const dots = wrapper.findAll('.cmp-dot')
    expect(dots.length).toBe(2)

    await dots[0].trigger('click')
    await wrapper.vm.$nextTick()

    const stage = wrapper.find('.lightbox__stage')
    expect(stage.classes()).toContain('lightbox__stage--compare')

    const imgs = wrapper.findAll('.lightbox__img')
    expect(imgs.length).toBe(2)
    // 两图 transform 完全一致（同一缩放值，误差 0）
    const t1 = imgs[0].attributes('style') ?? ''
    const t2 = imgs[1].attributes('style') ?? ''
    const scaleOf = (s: string) => Number(s.match(/scale\(([\d.]+)\)/)?.[1] ?? NaN)
    // 两图 transform 的 scale 值差 < 0.002（A-04 验收口径）
    expect(Math.abs(scaleOf(t1) - scaleOf(t2))).toBeLessThan(0.002)
    expect(scaleOf(t1)).toBe(1)
    wrapper.unmount()
  })

  it('对比最多 4 项，超出后不再加入', async () => {
    const candidates = Array.from({ length: 6 }, (_, i) =>
      makeItem({ id: `cand${i}00`, title: `候选${i}` }),
    )
    const wrapper = mountLightbox({ candidates })
    // 当前项 + 最多 3 个候选 = 4
    const dots = wrapper.findAll('.cmp-dot')
    for (const dot of dots) {
      await dot.trigger('click')
    }
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.lightbox__img').length).toBe(4)
    wrapper.unmount()
  })

  it('单击同一项可退出对比', async () => {
    const wrapper = mountLightbox()
    const dot = wrapper.findAll('.cmp-dot')[0]
    await dot.trigger('click')
    await dot.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__stage').classes()).not.toContain(
      'lightbox__stage--compare',
    )
    wrapper.unmount()
  })
})

describe('LightboxViewer 色板与信息', () => {
  it('信息面板展示色板，点击色块触发按色筛选', async () => {
    const wrapper = mountLightbox()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()

    const swatches = wrapper.findAll('.swatch')
    expect(swatches.length).toBe(2)

    await wrapper.find('.panel__link').trigger('click')
    expect(wrapper.emitted('filter-color')).toHaveLength(1)
    expect(wrapper.emitted('filter-color')?.[0]).toEqual(['#112233'])
    wrapper.unmount()
  })

  it('信息面板展示 EXIF 摘要与标签', async () => {
    const wrapper = mountLightbox()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()

    const panel = wrapper.find('.lightbox__panel').text()
    expect(panel).toContain('FUJIFILM')
    expect(panel).toContain('X-T5')
    expect(wrapper.findAll('.panel__tag').length).toBe(2)
    wrapper.unmount()
  })

  it('palette 为空时退回主色', async () => {
    const wrapper = mountLightbox({
      item: makeItem({ palette_json: '[]', dominant_color: '#abcdef' }),
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.swatch').length).toBe(1)
    wrapper.unmount()
  })

  it('打开信息面板后舞台收缩让位，避免遮挡图片', async () => {
    const wrapper = mountLightbox()
    expect(wrapper.find('.lightbox__stage').classes()).not.toContain('lightbox__stage--with-panel')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__stage').classes()).toContain('lightbox__stage--with-panel')
    wrapper.unmount()
  })

  it('L 键与喜欢按钮发出 toggle-like 事件', async () => {
    const wrapper = mountLightbox({ liked: false })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'l' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('toggle-like')?.[0]).toEqual(['aaaaaa11'])
    wrapper.unmount()
  })

  it('舞台左右悬浮箭头可切换上一张/下一张', async () => {
    const wrapper = mountLightbox()
    await wrapper.find('.stage-nav--prev').trigger('click')
    await wrapper.find('.stage-nav--next').trigger('click')
    expect(wrapper.emitted('prev')).toHaveLength(1)
    expect(wrapper.emitted('next')).toHaveLength(1)
    wrapper.unmount()
  })

  it('1 键或 1:1 按钮可切换原图缩放倍率', async () => {
    const wrapper = mountLightbox()
    expect(wrapper.find('.lightbox__zoom').text()).toBe('1:1')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__zoom').text()).toBe('200%')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.lightbox__zoom').text()).toBe('1:1')
    wrapper.unmount()
  })
})
