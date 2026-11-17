/**
 * i18n 显示逻辑测试（R5）
 *
 * 重点：count 必须先用于复数选形，再按 locale 加千分位；
 * 不能由调用方预先格式化成字符串（会让复数选形失效）。
 */
import { describe, expect, it } from 'vitest'
import { useI18n } from './useI18n'

describe('count 格式化', () => {
  it('中文大数字加千分位', () => {
    const { t, setLocale } = useI18n()
    setLocale('zh-CN')
    expect(t('site.total', { count: 12345 })).toContain('12,345')
  })

  it('英文大数字加千分位', () => {
    const { t, setLocale } = useI18n()
    setLocale('en-US')
    expect(t('site.total', { count: 12345 })).toContain('12,345')
  })

  it('英文单数选 one 形式', () => {
    const { t, setLocale } = useI18n()
    setLocale('en-US')
    const out = t('site.total', { count: 1 })
    expect(out).toContain('1 item')
    expect(out).not.toContain('items')
  })

  it('英文复数选 other 形式', () => {
    const { t, setLocale } = useI18n()
    setLocale('en-US')
    expect(t('site.total', { count: 2 })).toContain('2 items')
  })

  it('复数选形与千分位同时生效', () => {
    const { t, setLocale } = useI18n()
    setLocale('en-US')
    const out = t('site.total', { count: 1001 })
    expect(out).toContain('items')
    expect(out).toContain('1,001')
  })

  it('普通占位符不受影响', () => {
    const { t } = useI18n()
    expect(t('browse.keyword', { value: '城市' })).toContain('城市')
  })
})
