/**
 * SmartImage 测试（前端显示缺陷修复）
 *
 * 关注两个真实 bug：
 *   1. 加载失败时必须显示失败态，而不是永远透明的空块
 *   2. 视频必须用海报帧作为缩略图（否则浏览器按图片解码失败显示黑块）
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SmartImage from './SmartImage.vue'

describe('SmartImage', () => {
  it('图片请求 720 档 WebP 作为兜底 src', () => {
    const wrapper = mount(SmartImage, { props: { id: 'abc' } })
    const img = wrapper.find('img')
    expect(img.attributes('src')).toBe('/img/abc?w=720&fm=webp')
  })

  it('视频用海报帧而非原视频作为缩略图（否则显示黑块）', () => {
    const wrapper = mount(SmartImage, {
      props: { id: 'vid1', kind: 'video', file: 'vid1.mp4' },
    })
    expect(wrapper.find('img').attributes('src')).toBe('/t/vid1.jpg')
  })

  it('生成 avif/webp 两级 source，实现渐进增强', () => {
    const wrapper = mount(SmartImage, { props: { id: 'abc', displayWidth: 800 } })
    const types = wrapper.findAll('source').map((s) => s.attributes('type'))
    expect(types).toEqual(['image/avif', 'image/webp'])
  })

  it('加载失败时显示失败态而非保持透明', async () => {
    const wrapper = mount(SmartImage, { props: { id: 'broken' } })
    expect(wrapper.find('.smart-image__failed').exists()).toBe(false)

    await wrapper.find('img').trigger('error')
    expect(wrapper.find('.smart-image__failed').exists()).toBe(true)
    // 失败时也要标记 loaded，避免永远 opacity:0
    expect(wrapper.find('img').classes()).toContain('is-loaded')
  })

  it('加载成功后淡入（is-loaded）', async () => {
    const wrapper = mount(SmartImage, { props: { id: 'ok' } })
    await wrapper.find('img').trigger('load')
    expect(wrapper.find('img').classes()).toContain('is-loaded')
  })

  it('priority 项使用 eager 与 high 优先级', () => {
    const wrapper = mount(SmartImage, { props: { id: 'p1', priority: true } })
    const img = wrapper.find('img')
    expect(img.attributes('loading')).toBe('eager')
    expect(img.attributes('fetchpriority')).toBe('high')
  })

  it('版本变化时重置失败态并给 URL 加缓存参数（后台补图后可重试）', async () => {
    const wrapper = mount(SmartImage, { props: { id: 'retry', version: 1 } })
    expect(wrapper.find('img').attributes('src')).toContain('v=1')
    await wrapper.find('img').trigger('error')
    expect(wrapper.find('.smart-image__failed').exists()).toBe(true)

    await wrapper.setProps({ version: 2 })
    expect(wrapper.find('.smart-image__failed').exists()).toBe(false)
    expect(wrapper.find('img').attributes('src')).toContain('v=2')
  })

  it('比率写入容器 aspect-ratio，防止加载时抖动', () => {
    const wrapper = mount(SmartImage, { props: { id: 'r1', ratio: 1.5 } })
    expect(wrapper.find('.smart-image').attributes('style')).toContain('aspect-ratio: 1 / 1.5')
  })
})
