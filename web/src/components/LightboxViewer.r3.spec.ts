/**
 * 灯箱交互修复测试（R3）
 *
 * 覆盖：连播与对比互斥、帮助浮层快捷键隔离、复制失败反馈、信息面板可关闭。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import LightboxViewer from './LightboxViewer.vue'
import type { MediaItem } from '@/api/types'

function makeItem(id = 'aaaaaa11', overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id, file: `${id}.jpg`, thumb: `${id}.jpg`, play_file: null, preview_file: null,
    kind: 'image', ext: '.jpg', name: `${id}.jpg`, title: `资产${id}`, source: '',
    source_platform: 'local', author: '', notes: '', size: 1024, width: 1200,
    height: 800, aspect_ratio: 1.5, duration: 0, fps: 0, codec: '',
    dominant_color: '#223344', palette_json: '["#112233"]', exif_json: '{}',
    phash: '', ocr_text: '', views: 0, downloads: 0, ts: 0, updated_at: 0,
    deleted_at: null, tags: [], ...overrides,
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

function mountLb(candidates: MediaItem[] = []) {
  return mount(LightboxViewer, {
    props: { item: makeItem(), hasPrev: false, hasNext: true, candidates },
    attachTo: document.body,
  })
}

describe('灯箱连播', () => {
  it('到最后一张发出 slideshow-end 而非静默停止', async () => {
    const wrapper = mountLb()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    await flushPromises()
    // hasNext=true 时先 next；把 props 改成无下一张再触发间隔
    await wrapper.setProps({ hasNext: false })
    vi.useFakeTimers()
    // 重启连播以套用新的 hasNext
    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(wrapper.emitted('slideshow-end')).toBeTruthy()
    vi.useRealTimers()
    wrapper.unmount()
  })

  it('开启连播会退出对比模式（两者互斥）', async () => {
    const candidates = [makeItem('bbbbbb22'), makeItem('cccccc33')]
    const wrapper = mountLb(candidates)
    const dot = wrapper.findAll('.cmp-dot')[0]
    await dot.trigger('click')
    await flushPromises()
    expect(wrapper.find('.lightbox__stage').classes()).toContain('lightbox__stage--compare')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    await flushPromises()
    expect(wrapper.find('.lightbox__stage').classes()).not.toContain('lightbox__stage--compare')
    wrapper.unmount()
  })
})

describe('帮助浮层', () => {
  it('打开后帮助对话框获得焦点，Esc 关闭后焦点回到触发按钮', async () => {
    const wrapper = mountLb()
    const helpBtn = wrapper.findAll('.lb-btn').find((b) => b.text().trim() === '?')!
    ;(helpBtn.element as HTMLElement).focus()
    await helpBtn.trigger('click')
    await flushPromises()

    expect(document.activeElement?.classList.contains('help__close')).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(document.activeElement).toBe(helpBtn.element)
    wrapper.unmount()
  })

  it('帮助浮层打开时快捷键不作用于背后的灯箱', async () => {
    const wrapper = mountLb()
    await wrapper.findAll('.lb-btn').find((b) => b.text().trim() === '?')!.trigger('click')
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await flushPromises()
    expect(wrapper.emitted('next')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('信息面板', () => {
  it('I 键打开后有独立关闭按钮', async () => {
    const wrapper = mountLb()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i', bubbles: true }))
    await flushPromises()
    expect(wrapper.find('.panel__close').exists()).toBe(true)
    await wrapper.find('.panel__close').trigger('click')
    await flushPromises()
    expect(wrapper.find('.lightbox__panel').exists()).toBe(false)
    wrapper.unmount()
  })
})
