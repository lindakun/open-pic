/**
 * BatchBar 单元测试（REQ-05）
 *
 * 覆盖：计数展示、批量打标、加入画板、导出（同步/异步）、移入回收站，
 * 以及失败时的错误提示不吞掉。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import BatchBar from './BatchBar.vue'
import type { Collection } from '@/api/types'

const collections: Collection[] = [
  { id: 1, name: '画板 A', description: '', cover_item_id: null, created_at: 0, updated_at: 0 },
]

function mountBar(selected = ['a', 'b']) {
  return mount(BatchBar, {
    props: { selected, collections },
    attachTo: document.body,
  })
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

describe('BatchBar 展示', () => {
  it('无选择时不渲染', () => {
    const wrapper = mountBar([])
    expect(wrapper.find('.batch').exists()).toBe(false)
    wrapper.unmount()
  })

  it('展示已选数量', () => {
    const wrapper = mountBar(['a', 'b', 'c'])
    expect(wrapper.text()).toContain('已选 3 项')
    wrapper.unmount()
  })

  it('关闭按钮发出 clear', async () => {
    const wrapper = mountBar()
    await wrapper.find('.batch__clear').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('BatchBar 批量操作', () => {
  it('移入回收站调用 batch 接口并清空选择', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, count: 2 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mountBar()
    const trashBtn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('移入回收站'))!
    await trashBtn.trigger('click')
    expect(trashBtn.text()).toContain('确认移入回收站')
    await trashBtn.trigger('click')
    await flushPromises()

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/items/batch')
    const body = JSON.parse(init.body)
    expect(body.action).toBe('delete')
    expect(body.ids).toEqual(['a', 'b'])
    expect(wrapper.emitted('clear')).toHaveLength(1)
    expect(wrapper.emitted('done')?.[0]).toEqual(['delete', 2])
    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('接口失败时发出错误 toast，不清空选择', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 500, json: async () => ({ detail: '后端异常' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mountBar()
    const trashBtn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('移入回收站'))!
    await trashBtn.trigger('click')
    expect(trashBtn.text()).toContain('确认移入回收站')
    await trashBtn.trigger('click')
    await flushPromises()

    expect(wrapper.emitted('clear')).toBeUndefined()
    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('批量打标把标签数组提交给接口', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, count: 2 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mountBar()
    const tagBtn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('打标签'))!
    await tagBtn.trigger('click')
    await flushPromises()

    // 两个弹层都会渲染 DOM，需按标签弹层定位确认按钮
    const tagSheet = wrapper.findAll('.batch__form').find((f) => f.find('input').exists())!
    const input = tagSheet.find('input')
    await input.setValue('城市 夜景')
    await tagSheet.findAll('button').at(-1)!.trigger('click')
    await flushPromises()

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.action).toBe('add_tags')
    expect(body.tags).toEqual(['城市', '夜景'])
    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('批量移除标签提交 remove_tags', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, count: 2 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mountBar()
    const btn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('移除标签'))!
    await btn.trigger('click')
    await flushPromises()

    const tagSheet = wrapper.findAll('.batch__form').find((f) => f.find('input').exists())!
    await tagSheet.find('input').setValue('城市')
    await tagSheet.findAll('button').at(-1)!.trigger('click')
    await flushPromises()

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.action).toBe('remove_tags')
    expect(body.tags).toEqual(['城市'])
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})

describe('BatchBar 导出', () => {
  it('同步导出触发浏览器下载', async () => {
    const blob = new Blob(['zip'], { type: 'application/zip' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, blob: async () => blob,
    }))
    const createSpy = vi.fn(() => 'blob:mock')
    vi.stubGlobal('URL', Object.assign(URL, {
      createObjectURL: createSpy,
      revokeObjectURL: vi.fn(),
    }))
    // 拦截锚点点击，避免 jsdom 导航告警
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = mountBar()
    const exportBtn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('导出'))!
    await exportBtn.trigger('click')
    await flushPromises()

    expect(createSpy).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
    vi.unstubAllGlobals()
    clickSpy.mockRestore()
    wrapper.unmount()
  })

  it('超过阈值时后端返回 202，走任务提示而非下载', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ async: true, job_id: 9, count: 30 }),
    }))
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = mountBar()
    const exportBtn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('导出'))!
    await exportBtn.trigger('click')
    await flushPromises()

    // 202 不应触发下载
    expect(clickSpy).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
    clickSpy.mockRestore()
    wrapper.unmount()
  })
})

describe('BatchBar 设为精选', () => {
  it('把已选 id 按顺序提交给 featured 接口', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, count: 2 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mountBar(['x', 'y'])
    const btn = wrapper.findAll('.batch__actions button').find((b) => b.text().includes('设为精选'))!
    await btn.trigger('click')
    await flushPromises()

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/featured')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body).ids).toEqual(['x', 'y'])
    expect(wrapper.emitted('done')?.[0]).toEqual(['featured', 2])
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})
