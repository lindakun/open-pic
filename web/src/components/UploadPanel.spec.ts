/**
 * UploadPanel 单元测试（REQ-05）
 *
 * 覆盖：文件类型过滤与去重、上传进度与结果、部分失败保留队列、
 * 链接校验、粘贴监听的生命周期。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import UploadPanel from './UploadPanel.vue'

function makeFile(name: string, type = 'image/jpeg', size = 1024): File {
  const blob = new Blob([new Uint8Array(size)], { type })
  return new File([blob], name, { type })
}

function mountPanel() {
  return mount(UploadPanel, {
    props: { open: true },
    attachTo: document.body,
  })
}

const origFetch = globalThis.fetch

beforeEach(() => {
  vi.restoreAllMocks()
  globalThis.fetch = origFetch
  // jsdom 未实现 HTMLDialogElement，补齐最小实现以便 MLSheet 挂载
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

describe('UploadPanel 文件选择', () => {
  it('非图片/视频文件被拒绝并给出提示', async () => {
    const wrapper = mountPanel()
    const input = wrapper.find('input[type="file"]')
    const file = makeFile('doc.pdf', 'application/pdf')

    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.find('.up__errors').exists()).toBe(true)
    expect(wrapper.text()).toContain('只能上传图片或视频文件')
    wrapper.unmount()
  })

  it('同名同大小文件不重复入队', async () => {
    const wrapper = mountPanel()
    const input = wrapper.find('input[type="file"]')
    const a = makeFile('a.jpg')
    const b = makeFile('a.jpg')

    Object.defineProperty(input.element, 'files', { value: [a], configurable: true })
    await input.trigger('change')
    Object.defineProperty(input.element, 'files', { value: [b], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.findAll('.up__item').length).toBe(1)
    wrapper.unmount()
  })

  it('队列项可单独移除', async () => {
    const wrapper = mountPanel()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [makeFile('a.jpg')], configurable: true })
    await input.trigger('change')
    await flushPromises()

    await wrapper.find('.up__remove').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.up__item').length).toBe(0)
    wrapper.unmount()
  })
})

describe('UploadPanel 上传', () => {
  it('成功后发出 uploaded 事件并关闭面板', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, count: 1, items: [{ id: 'x' }] }),
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const wrapper = mountPanel()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [makeFile('a.jpg')], configurable: true })
    await input.trigger('change')
    await flushPromises()

    const submit = wrapper.findAll('.up__actions button').at(-1)!
    await submit.trigger('click')
    await flushPromises()

    expect(wrapper.emitted('uploaded')?.[0]).toEqual([1])
    expect(wrapper.emitted('update:open')?.at(-1)).toEqual([false])
    wrapper.unmount()
  })

  it('部分失败时保留队列并展示错误', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: '服务错误' }) })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const wrapper = mountPanel()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [makeFile('a.jpg'), makeFile('b.jpg')], configurable: true,
    })
    await input.trigger('change')
    await flushPromises()

    await wrapper.findAll('.up__actions button').at(-1)!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.up__errors').exists()).toBe(true)
    expect(wrapper.text()).toContain('服务错误')
    // 有失败时不自动关闭，便于重试
    expect(wrapper.emitted('update:open')).toBeUndefined()
    // 成功项移除、失败项保留，用户可直接重试
    const remaining = wrapper.findAll('.up__item')
    expect(remaining.length).toBe(1)
    expect(remaining[0].text()).toContain('b.jpg')
    wrapper.unmount()
  })

  it('浏览器给不出 MIME 的容器格式按扩展名放行（如 .mkv）', async () => {
    const wrapper = mountPanel()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [makeFile('clip.mkv', '')], configurable: true,
    })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.find('.up__errors').exists()).toBe(false)
    expect(wrapper.findAll('.up__item').length).toBe(1)
    wrapper.unmount()
  })
})

describe('UploadPanel 链接采集', () => {
  it('非法链接被拦截', async () => {
    const wrapper = mountPanel()
    await wrapper.findAll('.up__tab')[1].trigger('click')
    await flushPromises()

    const input = wrapper.find('input[type="url"]')
    await input.setValue('not-a-url')
    await wrapper.findAll('.up__actions button').at(-1)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('请输入以 http:// 或 https:// 开头的链接')
    wrapper.unmount()
  })

  it('合法链接提交到采集队列', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, job_id: 7 }),
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const wrapper = mountPanel()
    await wrapper.findAll('.up__tab')[1].trigger('click')
    await flushPromises()
    await wrapper.find('input[type="url"]').setValue('https://example.com/p/1')
    await wrapper.findAll('.up__actions button').at(-1)!.trigger('click')
    await flushPromises()

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/ingest-url')
    expect(JSON.parse(init.body).url).toBe('https://example.com/p/1')
    wrapper.unmount()
  })
})

describe('UploadPanel 粘贴', () => {
  it('打开时监听粘贴，关闭后解绑', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')

    const wrapper = mount(UploadPanel, { props: { open: false }, attachTo: document.body })
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(addSpy.mock.calls.some((c) => c[0] === 'paste')).toBe(true)

    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(removeSpy.mock.calls.some((c) => c[0] === 'paste')).toBe(true)

    wrapper.unmount()
  })
})
