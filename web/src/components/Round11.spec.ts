/**
 * 循环第 6 轮（Round 11）回归：
 *   - 视频时长统一为 m:ss / h:mm:ss
 *   - 选片页点击缩略图切图前提交未保存备注
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ReviewView from '@/views/ReviewView.vue'
import { useI18n } from '@/composables/useI18n'
import type { MediaItem } from '@/api/types'

function makeItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'aaaaaa11', file: 'aaaaaa11.jpg', thumb: 'aaaaaa11.jpg', play_file: null,
    preview_file: null, kind: 'image', ext: '.jpg', name: 'photo.jpg', title: '岸线',
    source: '', source_platform: 'local', author: '', notes: '', size: 1024,
    width: 1600, height: 1200, aspect_ratio: 1.33, duration: 0, fps: 0, codec: '',
    dominant_color: '#334455', palette_json: '[]', exif_json: '{}', phash: '',
    ocr_text: '', views: 0, downloads: 0, ts: 1700000000, updated_at: 1700000000,
    deleted_at: null, tags: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) { this.open = true })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) { this.open = false })
})

describe('Round 11: 时长格式化', () => {
  it('秒数按 m:ss / h:mm:ss 展示', () => {
    const { formatDuration } = useI18n()
    expect(formatDuration(0)).toBe('')
    expect(formatDuration(5)).toBe('0:05')
    expect(formatDuration(65)).toBe('1:05')
    expect(formatDuration(3661)).toBe('1:01:01')
  })
})

describe('Round 11: 选片备注不丢失', () => {
  it('点击缩略图切图前提交未保存备注', async () => {
    const items = [makeItem({ id: 'rev00001' }), makeItem({ id: 'rev00002' })]
    const bodies: { item_id: string; note: string }[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/mark')) {
        bodies.push(JSON.parse(String(init?.body)))
      }
      return { ok: true, status: 200, json: async () => ({ link: {}, items }) }
    }))

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/:token', component: ReviewView }],
    })
    await router.push('/review/tok')
    await router.isReady()
    const wrapper = mount(ReviewView, {
      global: { plugins: [createPinia(), router] },
      attachTo: document.body,
    })
    await flushPromises()

    await wrapper.find('#note').setValue('需要补标签')
    await wrapper.findAll('.film img')[1].trigger('click')
    await flushPromises()

    expect(bodies).toHaveLength(1)
    expect(bodies[0].item_id).toBe('rev00001')
    expect(bodies[0].note).toBe('需要补标签')
    wrapper.unmount()
  })
})
