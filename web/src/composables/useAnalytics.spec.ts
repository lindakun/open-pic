/**
 * 埋点测试（REQ-V2-20 D-18）
 *
 * 重点：合并上报（一次请求多条事件）、失败静默、设备/来源分类、
 * 曝光需停留 ≥1s。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deviceClass, referrerClass, track } from './useAnalytics'

const origFetch = globalThis.fetch

beforeEach(() => {
  vi.useFakeTimers()
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
  globalThis.fetch = origFetch
})

describe('设备与来源分类', () => {
  it('按视口宽度分三档', () => {
    expect(deviceClass()).toBe('desktop')
    window.innerWidth = 800
    expect(deviceClass()).toBe('tablet')
    window.innerWidth = 400
    expect(deviceClass()).toBe('mobile')
    window.innerWidth = 1280
  })

  it('无 referrer 记为 direct', () => {
    expect(referrerClass()).toBe('direct')
  })
})

describe('事件合并', () => {
  it('累计 20 条才立即上报，且只发一次请求', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    for (let i = 0; i < 19; i++) track('view', { itemId: `id${i}` })
    expect(fetchMock).not.toHaveBeenCalled()

    track('view', { itemId: 'id19' })
    await vi.runOnlyPendingTimersAsync()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.events).toHaveLength(20)
    expect(body.events[0].type).toBe('view')
  })

  it('10 秒后自动上报', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    track('like', { itemId: 'x' })
    expect(fetchMock).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('上报失败静默，不抛出', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch
    track('view', { itemId: 'y' })
    await expect(vi.advanceTimersByTimeAsync(10_000)).resolves.not.toThrow()
  })

  it('事件带页面类型与设备', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    globalThis.fetch = fetchMock as unknown as typeof fetch
    track('search', { meta: { q: '城市', result_count: 0 } })
    await vi.advanceTimersByTimeAsync(10_000)

    const ev = JSON.parse(fetchMock.mock.calls[0][1].body).events[0]
    expect(ev.page).toBeTruthy()
    expect(ev.device).toBeTruthy()
    expect(ev.meta.q).toBe('城市')
    expect(ev.meta.result_count).toBe(0)
  })
})
