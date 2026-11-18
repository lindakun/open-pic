import { createRouter, createWebHistory } from 'vue-router'

// 路由定义：单主页沉浸看图 + 按需筛选，保留 /browse 与 /a/:slug 兼容跳转
// 组件按需懒加载，首屏只加载主页所需代码
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
      // 兼容旧浏览页链接与 SEO 落地页跳转：携带全部筛选 query 无缝归并到主页
      path: '/browse',
      name: 'browse',
      redirect: (to) => ({ name: 'home', query: to.query, replace: true }),
    },
    {
      // 兼容分享短链：/app/ 下不做 301，直接渲染主页并定位打开灯箱
      path: '/a/:slug',
      name: 'asset',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      // 客户选片页（C-14）：独立布局
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
  browse: 'site.name',
  review: 'review.title',
  asset: 'site.name',
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
