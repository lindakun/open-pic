/**
 * MLMediaCard 单元测试
 *
 * 重点验证无障碍规则（E-20）：有标题时 alt 为空，
 * 无标题时才生成描述性 alt；卡片必须是原生 button。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MLMediaCard from './MLMediaCard.vue'
import type { MediaItem } from '@/api/types'

function makeItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'abc123',
    file: 'abc123.jpg',
    thumb: 'abc123.jpg',
    play_file: null,
    preview_file: null,
    kind: 'image',
    ext: '.jpg',
    name: 'photo.jpg',
    title: '日落时分的海岸线',
    source: '',
    source_platform: 'local',
    author: '',
    notes: '',
    size: 1024 * 1024,
    width: 1920,
    height: 1080,
    aspect_ratio: 1.78,
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
    ...overrides,
  }
}

describe('MLMediaCard', () => {
  it('渲染为原生 button，保证键盘可达', () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem() } })
    expect(wrapper.element.tagName).toBe('BUTTON')
  })

  it('有标题时 img 的 alt 为空，避免重复朗读', () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem() } })
    const img = wrapper.find('img')
    expect(img.attributes('alt')).toBe('')
  })

  it('无标题时生成描述性 alt', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem({ title: '', name: 'unnamed.jpg' }) },
    })
    expect(wrapper.find('img').attributes('alt')).toContain('unnamed.jpg')
  })

  it('首屏优先项使用 eager 与 high 优先级', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem(), priority: true },
    })
    const img = wrapper.find('img')
    expect(img.attributes('loading')).toBe('eager')
    expect(img.attributes('fetchpriority')).toBe('high')
  })

  it('非优先项延迟加载', () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem() } })
    const img = wrapper.find('img')
    expect(img.attributes('loading')).toBe('lazy')
  })

  it('点击时向父级抛出 open 事件', async () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem() } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
  })

  it('视频卡片显示时长徽标', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem({ kind: 'video', duration: 42 }) },
    })
    expect(wrapper.find('.ml-card__badge').text()).toContain('42s')
  })

  it('缺失宽高时按 1:1 布局，不产生 NaN', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem({ width: 0, height: 0 }) },
    })
    const style = wrapper.find('.ml-card__media').attributes('style') ?? ''
    expect(style).toContain('aspect-ratio')
    expect(style).not.toContain('NaN')
  })
})
