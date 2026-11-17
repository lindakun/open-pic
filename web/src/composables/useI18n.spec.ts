/**
 * i18n 单元测试（REQ-V2-20 E-20）
 *
 * 重点验证：
 *   - 占位符替换
 *   - 英文单复数选形（中文无此概念，应原样输出）
 *   - 缺失 key 的兜底行为
 *   - Intl 格式化的 locale 差异
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { useI18n } from './useI18n'

describe('useI18n', () => {
  const { t, setLocale, formatBytes, formatNumber, locale } = useI18n()

  beforeEach(() => {
    setLocale('zh-CN')
  })

  it('中文占位符替换', () => {
    expect(t('site.total', { count: 42 })).toBe('42 项')
  })

  it('英文按单复数选形', () => {
    setLocale('en-US')
    expect(t('site.total', { count: 1 })).toBe('1 item')
    expect(t('site.total', { count: 5 })).toBe('5 items')
  })

  it('中文复数模板原样输出', () => {
    setLocale('zh-CN')
    expect(t('site.total', { count: 1 })).toBe('1 项')
    expect(t('site.total', { count: 99 })).toBe('99 项')
  })

  it('缺失 key 时回退到中文而非报错', () => {
    expect(t('完全不存在.key')).toBe('完全不存在.key')
  })

  it('切换语言后 <html lang> 同步更新', () => {
    setLocale('en-US')
    expect(document.documentElement.lang).toBe('en-US')
    setLocale('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('locale 响应式引用同步变化', () => {
    setLocale('en-US')
    expect(locale.value).toBe('en-US')
    setLocale('zh-CN')
    expect(locale.value).toBe('zh-CN')
  })

  it('中英文体积格式化不同但语义一致', () => {
    setLocale('zh-CN')
    const zh = formatBytes(1024 * 1024)
    setLocale('en-US')
    const en = formatBytes(1024 * 1024)
    expect(zh).toContain('MB')
    expect(en).toContain('MB')
    // 两者都不应出现 NaN 或 undefined
    expect(zh).not.toContain('NaN')
    expect(en).not.toContain('NaN')
  })

  it('数字按 locale 分组', () => {
    setLocale('en-US')
    expect(formatNumber(12345)).toBe('12,345')
  })

  it('零字节显示占位符而非 0 B', () => {
    expect(formatBytes(0)).toBe('—')
  })

  it('中英关键页面文案均已提供', () => {
    const keys = [
      'home.title',
      'home.featured',
      'browse.loadMore',
      'facet.title',
      'lightbox.close',
      'sort.newest',
    ]
    for (const l of ['zh-CN', 'en-US'] as const) {
      setLocale(l)
      for (const k of keys) {
        // 不应回退成 key 本身
        expect(t(k)).not.toBe(k)
      }
    }
  })
})
