<script setup lang="ts">
/**
 * 浏览页（REQ-V2-20 A-05 / B-10）
 *
 * 结构：左侧分面面板 + 右侧瀑布流。
 * URL 即状态：刷新或分享链接都能还原完整筛选视图。
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMediaStore } from '@/stores/media'
import { useFilterStore } from '@/stores/filters'
import { useToast } from '@/composables/useToast'
import { withViewTransition } from '@/composables/useViewTransition'
import MasonryGrid from '@/components/MasonryGrid.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import FacetPanel from '@/components/FacetPanel.vue'
import MLButton from '@/components/MLButton.vue'
import MLChip from '@/components/MLChip.vue'
import type { SortKey } from '@/api/types'

const store = useMediaStore()
const filters = useFilterStore()
const toast = useToast()
const route = useRoute()

const searchInput = ref(filters.q)
/** 移动端分面面板折叠 */
const facetsOpen = ref(false)

let debounceTimer: number | undefined

function onSearchInput(value: string) {
  searchInput.value = value
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => {
    filters.setQ(value)
    store.refresh()
  }, 300)
}

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'newest', label: '最新' },
  { key: 'oldest', label: '最早' },
  { key: 'pixels', label: '分辨率' },
  { key: 'size', label: '体积' },
  { key: 'views', label: '热度' },
]

function changeSort(value: SortKey) {
  filters.setSort(value)
  store.refresh()
}

/** 应用筛选后统一刷新（标签切换等由面板触发） */
function applyAndRefresh() {
  store.refresh()
}

/** 打开灯箱：用共享元素转场让卡片"长成"大图（A-03） */
function openLightbox(index: number) {
  void withViewTransition(() => store.openLightbox(index))
}

// 从 URL 还原筛选，然后加载
onMounted(() => {
  filters.fromUrlQuery(route.query as Record<string, string>)
  searchInput.value = filters.q
  store.refresh()
})

// 筛选变化时刷新（面板内直接改 store 的路径）
watch(
  () => [
    filters.tags.join(','),
    filters.excludeTags.join(','),
    filters.kind,
    filters.orientation,
    filters.platform,
    filters.ext,
  ],
  () => {
    applyAndRefresh()
  },
)

watch(
  () => store.error,
  (err) => {
    if (err) toast.error(err)
  },
)
</script>

<template>
  <div class="browse">
    <!-- 工具条 -->
    <div class="browse__toolbar">
      <button
        type="button"
        class="browse__facets-toggle"
        :aria-expanded="facetsOpen"
        aria-controls="facet-panel"
        @click="facetsOpen = !facetsOpen"
      >
        筛选
        <span v-if="filters.activeCount" class="browse__badge mono">
          {{ filters.activeCount }}
        </span>
      </button>

      <div class="browse__search">
        <span class="browse__search-icon" aria-hidden="true">⌕</span>
        <input
          :value="searchInput"
          type="search"
          class="browse__search-input"
          placeholder="搜索标题、标签、来源…"
          aria-label="搜索媒体库"
          @input="onSearchInput(($event.target as HTMLInputElement).value)"
        />
      </div>

      <div class="browse__sorts" role="group" aria-label="排序方式">
        <button
          v-for="s in SORTS"
          :key="s.key"
          type="button"
          :class="['sort-btn', { 'sort-btn--on': filters.sort === s.key }]"
          :aria-pressed="filters.sort === s.key"
          @click="changeSort(s.key)"
        >
          {{ s.label }}
        </button>
      </div>

      <span class="browse__count mono" aria-live="polite">
        {{ store.loading && !store.items.length ? '载入中…' : `${store.total} 项` }}
      </span>
    </div>

    <!-- 已选条件 chips 条 -->
    <div v-if="filters.hasFilters" class="browse__active" aria-label="已选筛选条件">
      <MLChip
        v-if="filters.q"
        :label="`关键词：${filters.q}`"
        removable
        @remove="filters.setQ(''); searchInput = ''; applyAndRefresh()"
      />
      <MLChip
        v-for="tag in filters.tags"
        :key="`t-${tag}`"
        :label="tag"
        removable
        active
        @remove="filters.removeTag(tag); applyAndRefresh()"
      />
      <MLChip
        v-for="tag in filters.excludeTags"
        :key="`x-${tag}`"
        :label="tag"
        tone="exclude"
        removable
        @remove="filters.removeExclude(tag); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.kind"
        :label="filters.kind === 'image' ? '图片' : '视频'"
        removable
        active
        @remove="filters.setKind(''); applyAndRefresh()"
      />
      <MLChip
        v-if="filters.orientation"
        :label="{ landscape: '横图', portrait: '竖图', square: '方图' }[filters.orientation]"
        removable
        active
        @remove="filters.setOrientation(''); applyAndRefresh()"
      />
      <button type="button" class="browse__clear" @click="filters.reset(); applyAndRefresh()">
        清空全部
      </button>
    </div>

    <div class="browse__layout">
      <!-- 分面面板：桌面常驻，移动端按需展开 -->
      <div
        id="facet-panel"
        :class="['browse__facets', { 'browse__facets--open': facetsOpen }]"
      >
        <FacetPanel :facets="store.facets" :loading="store.facetsLoading" />
      </div>

      <div class="browse__main">
        <div v-if="store.isEmpty" class="browse__empty">
          <h2>没有匹配的内容</h2>
          <p class="muted">
            {{ filters.hasFilters ? '试试放宽筛选条件，或清空全部筛选。' : '上传图片或通过链接抓取，开始构建你的视觉资产库。' }}
          </p>
          <MLButton
            v-if="filters.hasFilters"
            variant="ghost"
            @click="filters.reset(); applyAndRefresh()"
          >
            清空筛选
          </MLButton>
        </div>

        <MasonryGrid v-else :items="store.items" @open="openLightbox" />

        <div v-if="store.hasMore" class="browse__more">
          <MLButton variant="ghost" :disabled="store.loading" @click="store.load()">
            {{ store.loading ? '载入中…' : '加载更多' }}
          </MLButton>
        </div>
      </div>
    </div>

    <LightboxViewer
      v-if="store.currentItem"
      :item="store.currentItem"
      :has-prev="store.lightboxIndex > 0"
      :has-next="store.lightboxIndex < store.items.length - 1"
      @close="store.closeLightbox"
      @prev="store.stepLightbox(-1)"
      @next="store.stepLightbox(1)"
    />
  </div>
</template>

<style scoped>
.browse {
  max-width: 1700px;
  margin: 0 auto;
  padding: var(--p-space-5) var(--p-space-5) var(--p-space-9);
}

.browse__toolbar {
  display: flex;
  align-items: center;
  gap: var(--p-space-4);
  flex-wrap: wrap;
  padding-bottom: var(--p-space-4);
}

.browse__facets-toggle {
  display: none;
  align-items: center;
  gap: var(--p-space-1);
  font-size: var(--p-step--1);
  color: var(--ink);
  border: 1px solid var(--rule-strong);
  border-radius: var(--p-radius-md);
  padding: var(--p-space-1) var(--p-space-3);
  min-height: 32px;
}

.browse__badge {
  background: var(--accent);
  color: var(--on-accent);
  border-radius: var(--p-radius-full);
  font-size: 0.6875rem;
  padding: 0 5px;
  min-width: 16px;
  text-align: center;
}

.browse__search {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.browse__search-icon {
  position: absolute;
  left: var(--p-space-3);
  top: 50%;
  transform: translateY(-50%);
  color: var(--ink-faint);
  pointer-events: none;
}

.browse__search-input {
  width: 100%;
  font: inherit;
  font-size: var(--p-step-0);
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--rule-strong);
  border-radius: var(--p-radius-md);
  padding: var(--p-space-2) var(--p-space-3) var(--p-space-2) var(--p-space-7);
  min-height: 36px;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.browse__search-input:hover,
.browse__search-input:focus {
  border-color: var(--ink-faint);
}

.browse__search-input::placeholder {
  color: var(--ink-faint);
}

.browse__sorts {
  display: flex;
  gap: var(--p-space-1);
}

.sort-btn {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-3);
  border-radius: var(--p-radius-full);
  min-height: 28px;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.sort-btn:hover {
  color: var(--ink);
  background: var(--surface-hover);
}

.sort-btn--on {
  color: var(--accent-hover);
  background: var(--accent-soft);
  font-weight: 500;
}

.browse__count {
  font-size: var(--p-step--1);
  color: var(--ink-faint);
  margin-left: auto;
}

/* 已选 chips 条 */
.browse__active {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--p-space-1);
  padding-bottom: var(--p-space-4);
  border-bottom: 1px solid var(--rule);
  margin-bottom: var(--p-space-5);
}

.browse__clear {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-2);
}

.browse__clear:hover {
  color: var(--danger);
}

/* 两栏布局 */
.browse__layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--p-space-7);
  align-items: start;
}

.browse__facets {
  position: sticky;
  top: var(--p-space-6);
}

.browse__main {
  min-width: 0;
}

.browse__empty {
  padding: var(--p-space-9) 0;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-3);
}

.browse__more {
  display: flex;
  justify-content: center;
  padding: var(--p-space-7) 0;
}

/* 窄屏：分面面板收起为抽屉式，工具条折叠按钮出现 */
@media (max-width: 900px) {
  .browse__layout {
    grid-template-columns: 1fr;
  }

  .browse__facets-toggle {
    display: inline-flex;
  }

  .browse__facets {
    display: none;
    position: static;
  }

  .browse__facets--open {
    display: block;
    padding-bottom: var(--p-space-4);
    border-bottom: 1px solid var(--rule);
    margin-bottom: var(--p-space-4);
  }
}
</style>
