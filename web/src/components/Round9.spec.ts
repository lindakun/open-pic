/**
 * 循环第 4 轮（Round 9）回归测试
 *
 * 覆盖：
 *   - 随机漫步生成固定 seed，分页请求参数稳定
 *   - 选片页保存中连续标记不同资产时，排队补发不丢失
 *   - 选片页视频聚焦时方向键不切换素材
 *   - 重复上传不会计入「新入库」数量
 *   - 灯箱兼容副本失败时回退原文件，彻底失败显示下载引导
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ReviewView from '@/views/ReviewView.vue'
import UploadPanel from '@/components/UploadPanel.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import { useFilterStore } from '@/stores/filters'
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
    title: '岸线',
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
    tags: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

async function mountReview(items: MediaItem[]) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/review/:token', component: ReviewView }],
  })
  await router.push('/review/tok')
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(ReviewView, {
    global: { plugins: [pinia, router] },
    attachTo: document.body,
  })
  return { wrapper, router }
}

describe('Round 9: 随机漫步种子', () => {
  it('shuffle 生成新 seed，分页参数保持一致', () => {
    const filters = useFilterStore()
    filters.shuffle()
    const seed = filters.seed
    expect(filters.sort).toBe('random')
    expect(seed).toBeGreaterThan(0)
    expect(filters.queryParams.seed).toBe(seed)
    filters.shuffle()
    expect(filters.seed).not.toBe(seed)
  })
})

describe('Round 9: 选片标记保存队列', () => {
  it('保存中标记另一张图，前一次完成后仍会补发', async () => {
    const items = [makeItem({ id: 'rev00001' }), makeItem({ id: 'rev00002' })]
    const markBodies: { item_id: string }[] = []
    const resolvers: (() => void)[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/mark')) {
        markBodies.push(JSON.parse(String(init?.body)))
        await new Promise<void>((resolve) => resolvers.push(resolve))
        return { ok: true, status: 200, json: async () => ({}) }
      }
      return { ok: true, status: 200, json: async () => ({ link: {}, items }) }
    }))

    const { wrapper } = await mountReview(items)
    await flushPromises()

    const markSelected = wrapper.findAll('.review__actions .rv-btn')[0]
    await markSelected.trigger('click')
    expect(markBodies).toHaveLength(1)

    // 第一张还在保存时切到第二张并标记
    await wrapper.find('.review__nav--next').trigger('click')
    await wrapper.findAll('.review__actions .rv-btn')[0].trigger('click')
    expect(markBodies).toHaveLength(1)

    resolvers.shift()?.()
    await flushPromises()
    expect(markBodies.map((b) => b.item_id)).toEqual(['rev00001', 'rev00002'])

    resolvers.shift()?.()
    await flushPromises()
    wrapper.unmount()
  })

  it('视频聚焦时方向键交给原生播放器', async () => {
    const items = [makeItem({ id: 'vid00001', kind: 'video', ext: '.mp4' }), makeItem({ id: 'img00002' })]
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ link: {}, items }),
    })))
    const { wrapper } = await mountReview(items)
    await flushPromises()

    const video = wrapper.find('video')
    ;(video.element as HTMLVideoElement).focus()
    video.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await flushPromises()
    expect(wrapper.find('.review__cap').text()).toContain('1 / 2')
    wrapper.unmount()
  })
})

describe('Round 9: 上传与视频容错', () => {
  it('重复文件不计入新入库数量', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        count: 1,
        items: [{ ...makeItem(), duplicate: true }],
        errors: [],
      }),
    })))
    const wrapper = mount(UploadPanel, {
      props: { open: true },
      global: { plugins: [createPinia()] },
      attachTo: document.body,
    })
    await wrapper.vm.addFiles([new File(['x'], 'dup.jpg', { type: 'image/jpeg' })])
    await flushPromises()
    const submit = wrapper.findAll('.up__actions button').at(-1)!
    await submit.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('uploaded')?.[0]?.[0]).toBe(0)
    wrapper.unmount()
  })

  it('兼容副本失败先回退原文件，再失败显示下载引导', async () => {
    const item = makeItem({ id: 'vid00009', file: 'vid00009.mp4', kind: 'video', ext: '.mp4', play_file: 'vid00009.mp4' })
    const wrapper = mount(LightboxViewer, {
      props: { item, hasPrev: false, hasNext: false },
      attachTo: document.body,
    })
    const video = wrapper.find('video')
    await video.trigger('error')
    expect(wrapper.find('.lightbox__video-error').exists()).toBe(false)
    expect((video.element as HTMLVideoElement).getAttribute('src')).toBe('/f/vid00009.mp4')

    await video.trigger('error')
    expect(wrapper.find('.lightbox__video-error').exists()).toBe(true)
    wrapper.unmount()
  })
})
