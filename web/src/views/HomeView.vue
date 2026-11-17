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
import MasonryGrid from '@/components/MasonryGrid.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import MLButton from '@/components/MLButton.vue'

const store = useMediaStore()
const filters = useFilterStore()
const router = useRouter()
const { t } = useI18n()

/** 对比候选（A-04）：取当前项附近 8 项 */
const compareCandidates = computed(() => {
  const start = Math.max(0, store.lightboxIndex - 4)
  return store.items.slice(start, start + 8)
})

/** 灯箱内点色板 → 带主色跳转浏览页（打通 A-04 与 B-10） */
function onFilterColor(color: string) {
  filters.setColor(color)
  router.push({ name: 'browse' })
}

/** 是否具备自动加载能力：无 IntersectionObserver 时退回手动按钮 */
const autoLoadAvailable = typeof IntersectionObserver !== 'undefined'

/** 滚动后工具条淡出，让图片墙占满注意力 */
const toolbarDim = ref(false)

function onScroll() {
  toolbarDim.value = window.scrollY > 120
}

/** 触底自动加载，首页做成无限滚动的图墙 */
let observer: IntersectionObserver | null = null
const sentinel = ref<HTMLElement | null>(null)

onMounted(async () => {
  if (store.items.length === 0) {
    await store.refresh()
    // 人工精选置顶（A-02）：不改变图片墙结构，只调整顺序
    await store.promoteFeatured()
  }
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
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  observer?.disconnect()
})

function openLightbox(index: number) {
  store.openLightbox(index)
}

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

    <!-- 空状态 -->
    <div v-if="store.isEmpty" class="wall__empty">
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
      @open="openLightbox"
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

    <LightboxViewer
      v-if="store.currentItem"
      :item="store.currentItem"
      :has-prev="store.lightboxIndex > 0"
      :has-next="store.lightboxIndex < store.items.length - 1"
      :candidates="compareCandidates"
      @close="store.closeLightbox"
      @prev="store.stepLightbox(-1)"
      @next="store.stepLightbox(1)"
      @slideshow-end="store.stepToFirst()"
      @filter-color="onFilterColor"
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
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-2) var(--p-space-3);
  /* 半透明纸色，滚动时图片从下面透出 */
  background: color-mix(in srgb, var(--paper) 82%, transparent);
  backdrop-filter: blur(10px);
  transition: opacity var(--p-dur-base) var(--p-ease-out);
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

@media (prefers-reduced-motion: reduce) {
  .wall__bar {
    transition: none;
  }
}
</style>
