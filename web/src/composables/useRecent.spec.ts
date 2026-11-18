/**
 * 最近浏览测试（REQ-V2-20 C-15）
 *
 * 约束：上限 50、重复项提前不重复、存储不可用时静默降级。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearRecent, pushRecent, removeRecent, useRecent } from './useRecent'

beforeEach(() => {
  clearRecent()
  vi.restoreAllMocks()
})

describe('useRecent', () => {
  it('最新浏览排在最前', () => {
    pushRecent({ id: 'a', title: 'A', kind: 'image' })
    pushRecent({ id: 'b', title: 'B', kind: 'image' })
    expect(useRecent().recent.value.map((e) => e.id)).toEqual(['b', 'a'])
  })

  it('重复浏览不产生重复条目，只提前', () => {
    pushRecent({ id: 'a', title: 'A', kind: 'image' })
    pushRecent({ id: 'b', title: 'B', kind: 'image' })
    pushRecent({ id: 'a', title: 'A', kind: 'image' })
    const ids = useRecent().recent.value.map((e) => e.id)
    expect(ids).toEqual(['a', 'b'])
    expect(ids.filter((i) => i === 'a')).toHaveLength(1)
  })

  it('上限为 50 条', () => {
    const { LIMIT } = useRecent()
    for (let i = 0; i < LIMIT + 10; i++) {
      pushRecent({ id: `id${i}`, title: `T${i}`, kind: 'image' })
    }
    expect(useRecent().recent.value.length).toBe(LIMIT)
    // 最早的被挤出
    expect(useRecent().recent.value.map((e) => e.id)).not.toContain('id0')
  })

  it('清空后为空', () => {
    pushRecent({ id: 'a', title: 'A', kind: 'image' })
    clearRecent()
    expect(useRecent().recent.value).toEqual([])
  })

  it('removeRecent 仅移除指定条目', () => {
    pushRecent({ id: 'a', title: 'A', kind: 'image' })
    pushRecent({ id: 'b', title: 'B', kind: 'image' })
    removeRecent('a')
    expect(useRecent().recent.value.map((e) => e.id)).toEqual(['b'])
  })

  it('localStorage 不可用时不影响写入内存', () => {
    const orig = Storage.prototype.setItem
    Storage.prototype.setItem = vi.fn(() => {
      throw new Error('quota')
    })
    expect(() => pushRecent({ id: 'x', title: 'X', kind: 'image' })).not.toThrow()
    expect(useRecent().recent.value[0].id).toBe('x')
    Storage.prototype.setItem = orig
  })
})
