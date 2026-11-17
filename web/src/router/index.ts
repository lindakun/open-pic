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

router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? 'MediaLib'
  document.title = `${title} · MediaLib`
})

export default router
