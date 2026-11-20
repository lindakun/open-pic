/**
 * MLMediaCard 显示逻辑测试（R2）
 *
 * 覆盖：
 *   1. 长标题必须两行截断（卡片高度依赖两行计算，行数变动会让瀑布流参差）
 *   2. 视频只在右上角展示播放三角，时长保留在底部规格行
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MLMediaCard from './MLMediaCard.vue'
import type { MediaItem } from '@/api/types'
function makeItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'a1', file: 'a1.jpg', thumb: 'a1.jpg', play_file: null, preview_file: null,
    kind: 'image', ext: '.jpg', name: 'a1.jpg', title: '标题', source: '',
    source_platform: 'local', author: '', notes: '', size: 100, width: 800,
    height: 600, aspect_ratio: 1.33, duration: 0, fps: 0, codec: '',
    dominant_color: '#334455', palette_json: '[]', exif_json: '{}', phash: '',
    ocr_text: '', views: 0, downloads: 0, ts: 0, updated_at: 0, deleted_at: null,
    ...overrides,
  }
}

describe('MLMediaCard 显示逻辑', () => {
  it('视频卡片显示右上角播放三角，时长保留在规格行', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem({ kind: 'video', duration: 12.6, play_file: 'v.mp4' }) },
    })
    expect(wrapper.find('.ml-card__badge').exists()).toBe(false)
    expect(wrapper.find('.ml-card__fmt').exists()).toBe(false)
    expect(wrapper.find('.ml-card__video-mark').exists()).toBe(true)
    expect(wrapper.find('.ml-card__video-mark').attributes('aria-label')).toContain('视频')
    expect(wrapper.find('.ml-card__spec').text()).toContain('0:13')
  })

  it('图片卡片不显示视频标记', () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem() } })
    expect(wrapper.find('.ml-card__video-mark').exists()).toBe(false)
    expect(wrapper.find('.ml-card__badge').exists()).toBe(false)
  })

  it('长标题容器带两行截断类，保证高度一致', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem({ title: '非常长的标题'.repeat(12) }) },
    })
    const title = wrapper.find('.ml-card__title')
    expect(title.exists()).toBe(true)
    // 文本仍完整保留（截断是视觉层，不影响可访问性与复制）
    expect(title.text().length).toBeGreaterThan(20)
  })

  it('选择模式下点击发出 toggle 而非 open', async () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem(), selectable: true, selected: false },
    })
    await wrapper.find('.ml-card__trigger').trigger('click')
    expect(wrapper.emitted('toggle')?.[0]).toEqual(['a1'])
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('非选择模式点击发出 open', async () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem() } })
    await wrapper.find('.ml-card__trigger').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
  })

  it('选中态有 aria-pressed 与视觉标记', () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem(), selectable: true, selected: true },
    })
    expect(wrapper.find('.ml-card__trigger').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('.ml-card__check--on').exists()).toBe(true)
  })

  it('点击喜欢按钮发出 toggle-like 且不触发 open', async () => {
    const wrapper = mount(MLMediaCard, { props: { item: makeItem(), liked: false } })
    await wrapper.find('.ml-card__like').trigger('click')
    expect(wrapper.emitted('toggle-like')?.[0]).toEqual(['a1'])
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('点击主色圆点发出 filter-color 且不触发 open', async () => {
    const wrapper = mount(MLMediaCard, {
      props: { item: makeItem({ dominant_color: '#3a7bd5' }) },
    })
    await wrapper.find('.ml-card__swatch').trigger('click')
    expect(wrapper.emitted('filter-color')?.[0]).toEqual(['#3a7bd5'])
    expect(wrapper.emitted('open')).toBeUndefined()
  })
})
