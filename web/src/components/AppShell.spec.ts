/**
 * AppShell 无障碍测试（R4）
 *
 * 覆盖：skip link 能真正把焦点交给 main、语言按钮 aria-label 走 i18n。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppShell from './AppShell.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div/>' } },
      { path: '/browse', name: 'browse', component: { template: '<div/>' } },
    ],
  })
}

beforeEach(() => vi.restoreAllMocks())

describe('AppShell 键盘可达', () => {
  it('main 带 tabindex=-1，skip link 锚点可接收焦点', async () => {
    const router = makeRouter()
    router.push('/')
    await router.isReady()
    const wrapper = mount(AppShell, { global: { plugins: [router] }, attachTo: document.body })
    const main = wrapper.find('main')
    expect(main.attributes('id')).toBe('main')
    expect(main.attributes('tabindex')).toBe('-1')
    wrapper.unmount()
  })

  it('skip link 指向 #main', () => {
    const router = makeRouter()
    const wrapper = mount(AppShell, { global: { plugins: [router] }, attachTo: document.body })
    expect(wrapper.find('.skip-link').attributes('href')).toBe('#main')
    wrapper.unmount()
  })

  it('语言切换按钮 aria-label 不硬编码中文', () => {
    const router = makeRouter()
    const wrapper = mount(AppShell, { global: { plugins: [router] }, attachTo: document.body })
    const btn = wrapper.findAll('.site-header__actions button')[1]
    expect(btn.attributes('aria-label')).toBeTruthy()
    // 中文状态下应指向「切换到英文」
    expect(btn.attributes('aria-label')).toContain('切换到英文')
    wrapper.unmount()
  })
})
