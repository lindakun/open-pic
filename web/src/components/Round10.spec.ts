/**
 * 循环第 5 轮回归：最近浏览存储中的脏数据必须被清洗，
 * 否则旧版本写入的缺字段/错类型条目会进入渲染层（NaN 时间、undefined 标题）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => {
  localStorage.clear()
  vi.resetModules()
})

describe('useRecent 存储清洗', () => {
  it('丢弃无 id 的条目并补齐类型', async () => {
    localStorage.setItem('medialib.recent', JSON.stringify([
      { id: 'abcdef12', title: 42, kind: 'weird', ts: 'oops' },
      { id: 'bad id!', title: 'x', kind: 'image', ts: 1 },
      { nope: true },
    ]))

    const mod = await import('@/composables/useRecent')
    const recent = mod.useRecent().recent
    expect(recent.value).toHaveLength(1)
    expect(recent.value[0]).toMatchObject({ id: 'abcdef12', title: '', kind: 'image' })
    expect(Number.isFinite(recent.value[0].ts)).toBe(true)
  })

  it('非法 JSON 时降级为空历史', async () => {
    localStorage.setItem('medialib.recent', '{not json')
    const mod = await import('@/composables/useRecent')
    expect(mod.useRecent().recent.value).toEqual([])
  })
})
