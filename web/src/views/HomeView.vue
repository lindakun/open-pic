<script setup lang="ts">
/**
 * 首页：整屏图片墙（REQ-V2-20 A-02 改版）
 *
 * 不再是"Hero + 精选带 + 上新"的分段结构，而是：
 *   - 一进来就是瀑布流，图片是唯一主角
 *   - 艺术墙模式：列宽浮动、垂直错位、部分大图，错落而不凌乱
 *   - 仅保留一条极轻的悬浮工具条（搜索入口 / 计数 / 主题），
 *     滚动时淡出，把画面完全让给图片
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaStore } from '@/stores/media'
import { useFilterStore } from '@/stores/filters'
import { useI18n } from '@/composables/useI18n'
import { useToast } from '@/composables/useToast'
import { track, useEventFlush } from '@/composables/useAnalytics'
import MasonryGrid from '@/components/MasonryGrid.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import MLButton from '@/components/MLButton.vue'

const store = useMediaStore()
const filters = useFilterStore()
const router = useRouter()
const { t } = useI18n()
const toast = useToast()

/** 喜欢 id 集合（与浏览页同步后端 /api/likes） */
const likedIds = ref<string[]>([])

async function loadLikes() {
  try {
    const res = await fetch('/api/likes')
    if (!res.ok) return
    const data = (await res.json()) as { ids: string[] }
    likedIds.value = data.ids ?? []
  } catch {
    likedIds.value = []
  }
}

async function toggleLike(id: string) {
  const liked = !likedIds.value.includes(id)
  const before = [...likedIds.value]
  likedIds.value = liked ? [...before, id] : before.filter((x) => x !== id)
  try {
    const res = await fetch('/api/like', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: id, liked }),
    })
    if (!res.ok) throw new Error()
  } catch {
    likedIds.value = before
    toast.error(t('like.failed'))
  }
}

/** 对比候选（A-04）：取当前项附近 8 项 */
const compareCandidates = computed(() => {
  const start = Math.max(0, store.lightboxIndex - 4)
  return store.items.slice(start, start + 8)
})

/** 灯箱内点色板 → 带主色跳转浏览页（打通 A-04 与 B-10）。
 *  必须显式带上 query：浏览页挂载时按 URL 还原筛选，
 *  空路由会把刚设置的主色清掉（实测踩到）。
 */
function onFilterColor(color: string) {
  filters.setColor(color)
  void router.push({ name: 'browse', query: filters.toUrlQuery() })
}

/** 灯箱内点标签 → 带标签跳转浏览页（与色板筛选对称） */
function onFilterTag(tag: string) {
  if (!filters.tags.includes(tag)) filters.toggleTag(tag)
  void router.push({ name: 'browse', query: filters.toUrlQuery() })
}

/** 是否具备自动加载能力：无 IntersectionObserver 时退回手动按钮 */
const autoLoadAvailable = typeof IntersectionObserver !== 'undefined'

/** 滚动后工具条淡出，让图片墙占满注意力；深滚时显示返回顶部按钮 */
const toolbarDim = ref(false)
const showBackTop = ref(false)

function onScroll() {
  const y = window.scrollY
  toolbarDim.value = y > 120
  showBackTop.value = y > 600
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 触底自动加载，首页做成无限滚动的图墙 */
let observer: IntersectionObserver | null = null
const sentinel = ref<HTMLElement | null>(null)

onMounted(async () => {
  // 首页是"全部资产"的图墙：清掉浏览页遗留的筛选，
  // 否则从浏览页返回首页时图片墙会静默变成筛选子集
  filters.reset()
  // 必须先等列表刷新完成再置顶精选：
  // 两者并发时 refresh 会用接口结果覆盖 promoteFeatured 刚调整好的顺序，
  // 首页精选位会随机丢失（实测踩到）。
  await store.refresh()
  await store.promoteFeatured()
  void loadLikes()
  window.addEventListener('scroll', onScroll, { passive: true })

  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting && store.hasMore && !store.loading) {
        store.load()
      }
    },
    // 提前两屏开始加载，滚动时几乎无等待
    { rootMargin: '200% 0px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)

  // 与浏览页一致订阅任务事件：视频转码/缩略图补齐后单卡更新，
  // 新入库则节流刷新，避免停留在首页时看不到新内容
  if (typeof EventSource !== 'undefined') {
    es = new EventSource('/api/jobs/stream')
    es.addEventListener('media_ready', onMediaReady as EventListener)
    es.addEventListener('library_updated', scheduleLibraryRefresh)
  }
})

// ---------- 任务事件流（SSE） ----------
let es: EventSource | null = null
let sseRefreshTimer: number | undefined

function onMediaReady(e: MessageEvent) {
  try {
    const data = JSON.parse(e.data) as { item_id?: string }
    if (data.item_id) void store.updateItem(data.item_id)
  } catch {
    // 事件数据异常时忽略
  }
}

function scheduleLibraryRefresh() {
  if (sseRefreshTimer !== undefined) return
  sseRefreshTimer = window.setTimeout(() => {
    sseRefreshTimer = undefined
    // 灯箱打开时不重排列表，避免当前资产错位
    if (store.currentItem) return
    void store.refresh().then(() => store.promoteFeatured())
  }, 1500)
}

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  observer?.disconnect()
  es?.close()
  if (sseRefreshTimer !== undefined) window.clearTimeout(sseRefreshTimer)
})

function openLightbox(index: number) {
  store.openLightbox(index)
  const it = store.items[index]
  // 首页此前没有任何浏览埋点：补上与浏览页一致的 view 事件
  if (it) track('view', { itemId: it.id })
}

// 组合式函数必须在 setup 同步作用域调用，页面隐藏时才会自动上报
useEventFlush()

function goSearch() {
  void router.push('/browse')
}

/** 空库时引导到浏览页并直接打开上传面板 */
function goBrowseAndUpload() {
  void router.push({ name: 'browse', query: { upload: '1' } })
}
</script>

<template>
  <div class="wall">
    <!-- 悬浮工具条：极轻、半透明，不构成"头部区块" -->
    <div :class="['wall__bar', { 'wall__bar--dim': toolbarDim }]">
      <span class="wall__count mono" aria-live="polite">
        {{ store.loading && !store.items.length ? t('site.loading') : t('site.total', { count: store.total }) }}
      </span>

      <button type="button" class="wall__search" :aria-label="t('browse.searchLabel')" @click="goSearch">
        <span aria-hidden="true">⌕</span>
        <span class="wall__search-text">{{ t('browse.searchPlaceholder') }}</span>
      </button>
    </div>

    <!-- 请求失败：与空库区分，给重试入口 -->
    <div v-if="store.error && !store.items.length" class="wall__empty">
      <h1 class="wall__empty-title">{{ t('browse.errorTitle') }}</h1>
      <p class="muted">{{ store.error }}</p>
      <MLButton variant="ghost" @click="store.refresh()">{{ t('common.retry') }}</MLButton>
    </div>

    <!-- 空状态 -->
    <div v-else-if="store.isEmpty" class="wall__empty">
      <h1 class="wall__empty-title">{{ t('browse.emptyTitle') }}</h1>
      <p class="muted">{{ t('home.empty') }}</p>
      <MLButton variant="ghost" @click="goBrowseAndUpload">{{ t('home.addFirst') }}</MLButton>
    </div>

    <!-- 图片墙本体 -->
    <!-- 小红书式卡片流：等宽列 + 规整圆角卡 + 两行标题，
         不做尺寸抖动，靠图片本身的色彩与密度形成节奏 -->
    <MasonryGrid
      v-else
      :items="store.items"
      :base-column-width="268"
      :liked-ids="likedIds"
      @open="openLightbox"
      @toggle-like="toggleLike"
    />

    <!-- 无限滚动哨兵 -->
    <div ref="sentinel" class="wall__sentinel" aria-hidden="true" />

    <!-- 已有无限滚动哨兵自动加载，这里只在哨兵失效（如 reduced-motion 或
         IntersectionObserver 不可用）时作为兜底入口，避免重复的手动入口 -->
    <div v-if="store.hasMore && !autoLoadAvailable" class="wall__more">
      <MLButton variant="quiet" :disabled="store.loading" @click="store.load()">
        {{ store.loading ? t('site.loading') : t('browse.loadMore') }}
      </MLButton>
    </div>
    <p v-else-if="store.loading" class="wall__more-hint muted">{{ t('site.loading') }}</p>

    <!-- 回到顶部悬浮钮 -->
    <button
      v-if="showBackTop"
      type="button"
      class="wall__top"
      :aria-label="t('wall.backToTop')"
      :title="t('wall.backToTop')"
      @click="scrollToTop"
    >
      ↑
    </button>

    <LightboxViewer
      v-if="store.currentItem"
      :item="store.currentItem"
      :has-prev="store.lightboxIndex > 0"
      :has-next="store.lightboxIndex < store.items.length - 1"
      :candidates="compareCandidates"
      :liked="likedIds.includes(store.currentItem.id)"
      @close="store.closeLightbox"
      @prev="store.stepLightbox(-1)"
      @next="store.stepLightbox(1)"
      @slideshow-end="store.stepToFirst()"
      @filter-color="onFilterColor"
      @filter-tag="onFilterTag"
      @toggle-like="toggleLike"
    />
  </div>
</template>

<style scoped>
.wall {
  /* 卡片流：左右留出与列间距一致的内边距，视觉上等距 */
  padding: var(--p-space-3) var(--p-space-4) var(--p-space-8);
  min-height: 100vh;
}

/* ---------- 悬浮工具条 ---------- */
.wall__bar {
  position: sticky;
  /* 跟随顶栏占位偏移：顶栏可见时贴合其下沿，隐藏时回到顶部，杜绝叠层遮挡 */
  top: var(--header-offset, 0px);
  z-index: 20;
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-2) var(--p-space-3);
  /* 半透明纸色，滚动时图片从下面透出 */
  background: color-mix(in srgb, var(--paper) 82%, transparent);
  backdrop-filter: blur(10px);
  transition:
    opacity var(--p-dur-base) var(--p-ease-out),
    top var(--p-dur-base) var(--p-ease-out);
}

.wall__bar--dim {
  opacity: 0.32;
}

.wall__bar:hover {
  opacity: 1;
}

.wall__count {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  flex-shrink: 0;
  padding-left: var(--p-space-2);
}

.wall__search {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  flex: 1;
  max-width: 320px;
  margin-left: auto;
  padding: var(--p-space-1) var(--p-space-3);
  min-height: 30px;
  font-size: var(--p-step--1);
  color: var(--ink-faint);
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.wall__search:hover {
  border-color: var(--rule-strong);
  color: var(--ink-muted);
}

.wall__search-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wall__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-9) var(--p-space-5);
  text-align: center;
}

.wall__empty-title {
  font-size: var(--p-step-2);
}

.wall__sentinel {
  height: 1px;
}

.wall__more {
  display: flex;
  justify-content: center;
  padding: var(--p-space-6) 0;
}

.wall__top {
  position: fixed;
  right: var(--p-space-5);
  bottom: var(--p-space-5);
  z-index: 30;
  width: 40px;
  height: 40px;
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--rule-strong);
  box-shadow: var(--card-shadow-hover);
  display: grid;
  place-items: center;
  font-size: 1.125rem;
  transition:
    transform var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.wall__top:hover {
  transform: translateY(-2px);
  background: var(--surface-hover);
}

@media (prefers-reduced-motion: reduce) {
  .wall__bar,
  .wall__top {
    transition: none;
  }
}
</style>
