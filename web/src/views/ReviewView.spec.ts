/**
 * ReviewView 单元测试（REQ-V2-20 C-14）
 *
 * 覆盖：链接无效态的友好提示、标记写入、快捷键、胶片条切换、计数。
 * fetch 全部走 stub，不依赖真实后端。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const items = [
  {
    id: 'aaaaaa11', file: 'a.jpg', thumb: 'a.jpg', play_file: null, preview_file: null,
    kind: 'image', ext: '.jpg', name: 'a.jpg', title: '海岸线', source: '', source_platform: 'local',
    author: '', notes: '', size: 1024, width: 1200, height: 800, aspect_ratio: 1.5,
    duration: 0, fps: 0, codec: '', dominant_color: '#223344', palette_json: '[]',
    exif_json: '{}', phash: '', ocr_text: '', views: 0, downloads: 0,
    ts: 1700000000, updated_at: 1700000000, deleted_at: null,
  },
  {
    id: 'bbbbbb22', file: 'b.jpg', thumb: 'b.jpg', play_file: null, preview_file: null,
    kind: 'image', ext: '.jpg', name: 'b.jpg', title: '街角', source: '', source_platform: 'local',
    author: '', notes: '', size: 2048, width: 900, height: 1200, aspect_ratio: 0.75,
    duration: 0, fps: 0, codec: '', dominant_color: '#445566', palette_json: '[]',
    exif_json: '{}', phash: '', ocr_text: '', views: 0, downloads: 0,
    ts: 1700000000, updated_at: 1700000000, deleted_at: null,
    review_state: 'selected', review_note: '做封面', review_reviewer: '客户A',
  },
]

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/review/:token', name: 'review', component: { template: '<div/>' } },
    ],
  })
}

async function mountReview(token = 'tok123') {
  const ReviewView = (await import('./ReviewView.vue')).default
  const router = makeRouter()
  router.push(`/review/${token}`)
  await router.isReady()
  return mount(ReviewView, { global: { plugins: [router] }, attachTo: document.body })
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('ReviewView 数据加载', () => {
  it('链接失效时显示友好提示而非报错栈', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    const wrapper = await mountReview('bad')
    await flushPromises()
    expect(wrapper.text()).toContain('选片链接无效或已失效')
    wrapper.unmount()
  })

  it('加载成功后渲染标题与首张图', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '客户A选片', message: '看下这几张' }, items }),
    }))
    const wrapper = await mountReview()
    await flushPromises()
    expect(wrapper.text()).toContain('客户A选片')
    expect(wrapper.find('.review__img').attributes('src')).toBe('/t/aaaaaa11_lg.webp')
    wrapper.unmount()
  })

  it('已存在的标记被还原并计入统计', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '' }, items }),
    }))
    const wrapper = await mountReview()
    await flushPromises()
    // 第二项预置 selected，计数器显示 1
    expect(wrapper.find('.review__counts').text()).toContain('选中 1')
    wrapper.unmount()
  })
})

describe('ReviewView 交互', () => {
  it('点击「选中」发出写入请求', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ link: { title: '' }, items }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountReview()
    await flushPromises()

    const buttons = wrapper.findAll('.review__actions .rv-btn')
    await buttons[0].trigger('click')
    await flushPromises()

    const [, init] = fetchMock.mock.calls[1]
    const body = JSON.parse(init.body)
    expect(body.item_id).toBe('aaaaaa11')
    expect(body.state).toBe('selected')
    wrapper.unmount()
  })

  it('写入失败时回滚本地标记', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ link: { title: '' }, items }) })
      .mockResolvedValueOnce({ ok: false, status: 500 })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountReview()
    await flushPromises()
    const before = wrapper.find('.review__counts').text()

    await wrapper.findAll('.review__actions .rv-btn')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.review__counts').text()).toBe(before)
    wrapper.unmount()
  })

  it('快捷键 1/2/3 分别写入三种状态', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '' }, items }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountReview()
    await flushPromises()

    for (const key of ['1', '2', '3']) {
      window.dispatchEvent(new KeyboardEvent('keydown', { key }))
      await flushPromises()
    }
    const states = fetchMock.mock.calls
      .filter((c) => String(c[0]).endsWith('/mark'))
      .map((c) => JSON.parse(c[1].body).state)
    expect(states).toEqual(['selected', 'pending', 'rejected'])
    wrapper.unmount()
  })

  it('输入框聚焦时快捷键不触发标记', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '' }, items }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountReview()
    await flushPromises()

    const input = wrapper.find('.review__who input')
    await input.trigger('keydown', { key: '1' })
    await flushPromises()
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/mark'))).toHaveLength(0)
    wrapper.unmount()
  })

  it('胶片条切换当前项', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ link: { title: '' }, items }),
    }))
    const wrapper = await mountReview()
    await flushPromises()
    expect(wrapper.findAll('.film').length).toBe(2)

    await wrapper.findAll('.film')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.review__img').attributes('src')).toBe('/t/bbbbbb22_lg.webp')
    wrapper.unmount()
  })
})
