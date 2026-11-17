/**
 * useViewTransition 单元测试
 *
 * 重点验证降级路径（A-03 验收第 2 条）：
 * 不支持 API 或系统开启减弱动效时，更新函数仍必须被执行。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { withViewTransition } from './useViewTransition'

describe('withViewTransition', () => {
  const originalMatchMedia = window.matchMedia

  beforeEach(() => {
    // 默认不支持 View Transitions
    delete (document as unknown as Record<string, unknown>).startViewTransition
    // jsdom 未实现 matchMedia，需显式 mock 为"不减弱动效"
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia
  })

  afterEach(() => {
    vi.restoreAllMocks()
    window.matchMedia = originalMatchMedia
    delete (document as unknown as Record<string, unknown>).startViewTransition
  })

  it('不支持 View Transitions 时仍执行更新', async () => {
    const update = vi.fn()
    await withViewTransition(update)
    expect(update).toHaveBeenCalledTimes(1)
  })

  it('支持时通过 startViewTransition 包裹更新', async () => {
    const update = vi.fn()
    const start = vi.fn((cb: () => void) => {
      cb()
      return { finished: Promise.resolve() }
    })
    ;(document as unknown as Record<string, unknown>).startViewTransition = start

    await withViewTransition(update)

    expect(start).toHaveBeenCalledTimes(1)
    expect(update).toHaveBeenCalledTimes(1)
  })

  it('系统开启减弱动效时不启动转场，直接执行更新', async () => {
    const update = vi.fn()
    const start = vi.fn()
    ;(document as unknown as Record<string, unknown>).startViewTransition = start
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia

    await withViewTransition(update)

    expect(start).not.toHaveBeenCalled()
    expect(update).toHaveBeenCalledTimes(1)
  })

  it('转场抛错时不阻塞，且不重复执行更新', async () => {
    const update = vi.fn()
    const start = vi.fn((cb: () => void) => {
      cb()
      return { finished: Promise.reject(new Error('transition failed')) }
    })
    ;(document as unknown as Record<string, unknown>).startViewTransition = start

    await expect(withViewTransition(update)).resolves.toBeUndefined()
    // 更新由浏览器调用一次；异常路径不得重复调用
    expect(update).toHaveBeenCalledTimes(1)
  })
})
