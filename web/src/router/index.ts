import { createRouter, createWebHistory } from 'vue-router'

// 路由定义（§4 A-02）：首页编辑化、浏览页独立、资产页语义化 URL
// 组件按需懒加载，首屏只加载首页所需代码
const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { title: 'MediaLib' },
    },
    {
      path: '/browse',
      name: 'browse',
      component: () => import('@/views/BrowseView.vue'),
      meta: { title: '浏览全部资产' },
    },
    {
      // 兼容旧分享链接：/app/ 下不做 301，直接渲染到浏览页并定位
      path: '/a/:slug',
      name: 'asset',
      component: () => import('@/views/BrowseView.vue'),
    },
    {
      // 客户选片页（C-14）：独立布局，不套顶栏
      path: '/review/:token',
      name: 'review',
      component: () => import('@/views/ReviewView.vue'),
      meta: { title: '选片' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
  scrollBehavior(to, from, savedPosition) {
    // 返回时还原位置，新导航回到顶部
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})

/** 页面标题走 i18n，切换语言后也能同步更新（原先写死中文） */
const TITLE_KEYS: Record<string, string> = {
  home: 'site.name',
  browse: 'site.browse',
  review: 'review.title',
  asset: 'site.browse',
  'not-found': 'notfound.title',
}

function applyTitle(to: { name?: unknown; meta: Record<string, unknown> }): void {
  const key = TITLE_KEYS[String(to.name ?? '')]
  const name = (to.meta.title as string | undefined) ?? 'MediaLib'
  // 动态导入避免循环依赖：i18n 在组件外也能用
  import('@/composables/useI18n').then(({ useI18n }) => {
    const { t } = useI18n()
    const label = key ? t(key) : name
    document.title = label === 'MediaLib' ? 'MediaLib' : `${label} · MediaLib`
  })
}

router.afterEach((to) => applyTitle(to as never))

// 语言切换后重算标题
if (typeof window !== 'undefined') {
  window.addEventListener('mlib:locale-change', () => {
    const current = router.currentRoute.value
    if (current) applyTitle(current as never)
  })
}

export default router
