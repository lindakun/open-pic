<script setup lang="ts">
/**
 * 浏览页 —— S0 最小闭环
 *
 * 搜索 + 排序 + 瀑布流 + 灯箱。分面筛选（B-10）在 S1 补齐。
 */
import { onMounted, ref, watch } from 'vue'
import { useMediaStore } from '@/stores/media'
import { useToast } from '@/composables/useToast'
import MasonryGrid from '@/components/MasonryGrid.vue'
import LightboxViewer from '@/components/LightboxViewer.vue'
import MLButton from '@/components/MLButton.vue'
import type { SortKey } from '@/api/types'

const store = useMediaStore()
const toast = useToast()

const searchInput = ref(store.query)

let debounceTimer: number | undefined

/** 搜索防抖 300ms，避免每次按键都请求 */
function onSearchInput(value: string) {
  searchInput.value = value
  window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => {
    store.setQuery(value)
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
  store.setSort(value)
  store.refresh()
}

onMounted(() => {
  if (store.items.length === 0) store.refresh()
})

// 请求失败时提示一次，不在渲染中反复弹
watch(
  () => store.error,
  (err) => {
    if (err) toast.error(err)
  },
)
</script>

<template>
  <div class="browse">
    <!-- 筛选栏：S0 先放搜索与排序，分面面板在 S1 加入 -->
    <div class="browse__toolbar">
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
          :class="['sort-btn', { 'sort-btn--on': store.sort === s.key }]"
          :aria-pressed="store.sort === s.key"
          @click="changeSort(s.key)"
        >
          {{ s.label }}
        </button>
      </div>

      <span class="browse__count mono" aria-live="polite">
        {{ store.loading && !store.items.length ? '载入中…' : `${store.total} 项` }}
      </span>
    </div>

    <!-- 空状态：不插画，用排版承担（纸感原则） -->
    <div v-if="store.isEmpty" class="browse__empty">
      <h2>还没有内容</h2>
      <p class="muted">上传图片或通过链接抓取，开始构建你的视觉资产库。</p>
    </div>

    <MasonryGrid
      v-else
      :items="store.items"
      @open="store.openLightbox"
    />

    <div v-if="store.hasMore" class="browse__more">
      <MLButton variant="ghost" :disabled="store.loading" @click="store.load()">
        {{ store.loading ? '载入中…' : '加载更多' }}
      </MLButton>
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
  max-width: 1600px;
  margin: 0 auto;
  padding: var(--p-space-6) var(--p-space-5) var(--p-space-9);
}

.browse__toolbar {
  display: flex;
  align-items: center;
  gap: var(--p-space-4);
  flex-wrap: wrap;
  margin-bottom: var(--p-space-7);
}

.browse__search {
  position: relative;
  flex: 1;
  min-width: 220px;
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
  min-height: 38px;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.browse__search-input:hover {
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

.browse__empty {
  padding: var(--p-space-9) 0;
  text-align: center;
}

.browse__empty h2 {
  margin-bottom: var(--p-space-2);
}

.browse__more {
  display: flex;
  justify-content: center;
  padding: var(--p-space-7) 0;
}
</style>
