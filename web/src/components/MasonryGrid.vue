<script setup lang="ts">
/**
 * 瀑布流容器
 *
 * 列式绝对定位：按容器宽度算列数，逐项放入当前最矮的列。
 * 依赖后端返回的 aspect_ratio，缺省按 1:1（§4 A-05）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MediaItem, ViewMode } from '@/api/types'
import { useI18n } from '@/composables/useI18n'
import MLMediaCard from './MLMediaCard.vue'
import SmartImage from './SmartImage.vue'

const props = withDefaults(
  defineProps<{
    items: MediaItem[]
    /** 视图模式：瀑布流 / 等高网格 / 紧凑列表 */
    mode?: ViewMode
    /**
     * 艺术墙模式：列宽不再完全均等、部分图片放大、
     * 每列带轻微垂直错位，形成错落而非规整网格的观感。
     */
    artistic?: boolean
    /** 列宽基准（px），艺术墙模式下在此基础上浮动 */
    baseColumnWidth?: number
    /** 等高网格最小列宽（px），随密度档位调整 */
    gridMinWidth?: number
    /** 批量选择模式（REQ-05） */
    selectable?: boolean
    /** 已选中的 id 集合 */
    selectedIds?: string[]
    /** 已喜欢的 id 集合 */
    likedIds?: string[]
  }>(),
  {
    mode: 'masonry',
    artistic: false,
    baseColumnWidth: 280,
    gridMinWidth: 220,
    selectable: false,
    selectedIds: () => [],
    likedIds: () => [],
  },
)

const emit = defineEmits<{
  (e: 'open', index: number): void
  (e: 'toggle', id: string, shiftKey?: boolean): void
  (e: 'toggle-like', id: string): void
  (e: 'filter-color', color: string): void
  (e: 'filter-tag', tag: string): void
}>()

const previewingRowId = ref<string | null>(null)

const selectedSet = computed(() => new Set(props.selectedIds))
const likedSet = computed(() => new Set(props.likedIds))
const { t, formatBytes, formatDate, formatNumber } = useI18n()

/**
 * 虚拟化的目的（D-17）：DOM 随滚动无限增长会拖慢合成与内存。
 * 做法是保留可视区 ± 2 屏的真实卡片，其余以等高占位替代——
 * 占位仍参与布局（用同一份 layout 数据），因此滚动条总高与卡片位置不变。
 */
/** 可视区上下各保留几屏，过低会在快速滚动时闪白 */
const OVERSCAN_SCREENS = 2
/** scrollY 的采样节流（ms）：滚动中不必每帧重算可见区间 */
const SCROLL_THROTTLE_MS = 60

const containerRef = ref<HTMLElement | null>(null)
const containerWidth = ref(0)

/**
 * 列数：统一按基准列宽推导（小红书式密排）。
 * 桌面 1440px 下约 5 列、每列 ~270px，与主流图片流一致；
 * 窄屏自动降到 2 列，避免卡片过窄。
 */
const columns = computed(() => {
  const w = containerWidth.value
  const n = Math.floor(w / props.baseColumnWidth)
  return Math.min(7, Math.max(2, n))
})

/* 卡片流间距：横向 16、纵向靠布局计算，整体更紧凑 */
const gap = computed(() => (containerWidth.value < 600 ? 8 : 16))

/**
 * 卡片信息层高度（8px 顶部间距 + 34px 两行标题 + 4px 间距 + 18px 底部信息行 = 64px）。
 * 与 MLMediaCard 的实际盒高像素级对齐，杜绝长标题列纵向重叠。
 */
const META_HEIGHT = 64

const columnWidth = computed(() => {
  const c = columns.value
  return (containerWidth.value - gap.value * (c - 1)) / c
})

/**
 * 稳定伪随机：同一张图每次渲染得到同样的偏移量，
 * 避免窗口缩放后版面跳动（艺术墙必须有确定性）。
 */
function hashUnit(seed: string, salt = 0): number {
  let h = 2166136261 ^ salt
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 10000) / 10000
}

/** 计算每项的绝对位置 */
const layout = computed(() => {
  const cols = columns.value
  const cw = columnWidth.value
  const g = gap.value
  const heights = new Array(cols).fill(0)
  const artistic = props.artistic

  return props.items.map((item) => {
    const ratio = item.width && item.height
      ? Math.min(Math.max(item.height / item.width, 0.4), 2.4)
      : 1

    if (!artistic) {
      const h = Math.round(cw * ratio)
      let target = 0
      for (let i = 1; i < cols; i++) {
        if (heights[i] < heights[target]) target = i
      }
      const pos = { left: target * (cw + g), top: heights[target], width: cw, height: h }
      heights[target] += h + META_HEIGHT + g
      return pos
    }

    // ---------- 艺术墙 ----------
    // a. 列内宽度浮动：±7%，让整行不再齐平
    const jitter = 0.93 + hashUnit(item.id) * 0.14
    const w = Math.round(cw * jitter)
    // 图片按自身比例，但限制高度区间，避免超长图把某一列拉垮
    const h = Math.round(Math.min(Math.max(w * ratio, w * 0.6), w * 2.0))

    // b. 选择最矮列
    let target = 0
    for (let i = 1; i < cols; i++) {
      if (heights[i] < heights[target]) target = i
    }

    // c. 水平方向在列内轻微居中偏移，形成"手贴"感
    const slack = cw - w
    const offsetX = slack > 0 ? slack * (0.5 + (hashUnit(item.id, 7) - 0.5) * 0.6) : 0
    // d. 垂直方向留 0–14px 的呼吸差
    const offsetY = hashUnit(item.id, 13) * 14

    const pos = {
      left: target * (cw + g) + offsetX,
      top: heights[target] + offsetY,
      width: w,
      height: h,
    }
    heights[target] += h + META_HEIGHT + g + offsetY
    return pos
  })
})

/** 容器总高度 = 最高列的底部 */
const containerHeight = computed(() => {
  if (!layout.value.length) return 0
  // 不再按 left 反推列号（艺术墙有水平偏移，反推会错），
  // 直接取所有卡片底部的最大值。
  let bottom = 0
  for (const pos of layout.value) {
    const b = pos.top + pos.height + META_HEIGHT
    if (b > bottom) bottom = b
  }
  return bottom
})

let observer: ResizeObserver | null = null
let roRaf = 0

/** 当前滚动位置与视口高度：驱动可见区间计算 */
const scrollY = ref(0)
const viewportH = ref(0)

function measure() {
  const el = containerRef.value
  if (el) {
    containerWidth.value = el.clientWidth
    // 重排会改变容器高度与列数，旧的 scrollY 立即失效；
    // 只更新宽度而不重算可见区间，缩放窗口后会出现大片未渲染的空白
    scrollY.value = -el.getBoundingClientRect().top
  }
  viewportH.value = window.innerHeight
}

let scrollTimer: number | undefined

function onScroll() {
  if (scrollTimer !== undefined) return
  scrollTimer = window.setTimeout(() => {
    scrollTimer = undefined
    // 用容器相对视口的位置换算，避免把整页 header 也算进去
    const el = containerRef.value
    if (!el) return
    const rect = el.getBoundingClientRect()
    scrollY.value = -rect.top
  }, SCROLL_THROTTLE_MS)
}

/**
 * 可见区间：以容器自身坐标为准（scrollY 是容器顶边滚出视口的距离）。
 * 上下各留 OVERSCAN_SCREENS 屏，快速滚动时不至于露出空白。
 */
const visibleRange = computed(() => {
  const h = viewportH.value || 800
  const pad = h * OVERSCAN_SCREENS
  const top = scrollY.value - pad
  const bottom = scrollY.value + h + pad
  return { top, bottom }
})

/**
 * 回收判定：卡片底部在区间上方，或顶部在区间下方 ⇒ 用占位替代。
 * 保留首屏前 4 张强制渲染（LCP 元素不能被回收）。
 */
function isVisible(index: number): boolean {
  if (index < 4) return true
  const pos = layout.value[index]
  if (!pos) return false
  const top = pos.top
  const bottom = pos.top + pos.height + META_HEIGHT
  return bottom >= visibleRange.value.top && top <= visibleRange.value.bottom
}

/** 实际渲染的条目数（用于测试与观测） */
const renderedCount = computed(() => {
  let n = 0
  for (let i = 0; i < layout.value.length; i++) if (isVisible(i)) n++
  return n
})

onMounted(() => {
  measure()
  // 容器宽度变化（窗口缩放、侧栏开合）时用 rAF 重排，避免同帧高度变化引起 ResizeObserver loop 告警
  observer = new ResizeObserver(() => {
    if (roRaf) cancelAnimationFrame(roRaf)
    roRaf = requestAnimationFrame(() => {
      roRaf = 0
      measure()
    })
  })
  if (containerRef.value) observer.observe(containerRef.value)

  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', measure, { passive: true })
  onScroll()
})

onUnmounted(() => {
  observer?.disconnect()
  if (roRaf) cancelAnimationFrame(roRaf)
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', measure)
  if (scrollTimer !== undefined) window.clearTimeout(scrollTimer)
})

// 条目追加后立即重算一次，避免新卡片在可视区外被误判为回收
watch(() => props.items.length, () => {
  measure()
  onScroll()
})

defineExpose({ renderedCount, isVisible, visibleRange })
</script>

<template>
  <!-- 瀑布流模式（默认，虚拟化） -->
  <div
    v-if="mode === 'masonry'"
    ref="containerRef"
    class="masonry"
    :style="{ height: `${containerHeight}px` }"
  >
    <div
      v-for="(item, index) in items"
      :key="item.id"
      class="masonry__cell"
      :data-item-id="item.id"
      :style="{
        transform: `translate3d(${layout[index]?.left ?? 0}px, ${layout[index]?.top ?? 0}px, 0)`,
        width: `${layout[index]?.width ?? 0}px`,
      }"
    >
      <MLMediaCard
        v-if="isVisible(index)"
        :item="item"
        :priority="index < 4"
        :selectable="selectable"
        :selected="selectedSet.has(item.id)"
        :liked="likedSet.has(item.id)"
        @open="emit('open', index)"
        @toggle="(id, shift) => emit('toggle', id, shift)"
        @toggle-like="emit('toggle-like', $event)"
        @filter-color="emit('filter-color', $event)"
      />
      <!-- 回收态占位：与卡片同尺寸同位置，保证滚动条总高与已渲染卡片零位移 -->
      <div
        v-else
        class="masonry__ghost"
        :style="{ height: `${(layout[index]?.height ?? 0) + META_HEIGHT}px` }"
        aria-hidden="true"
      />
    </div>
  </div>

  <!-- 等高网格模式：适合横向比对与规整浏览 -->
  <div v-else-if="mode === 'grid'" class="grid-view" :style="{ '--grid-min': `${gridMinWidth}px` }">
    <div
      v-for="(item, index) in items"
      :key="item.id"
      :data-item-id="item.id"
      class="grid-view__cell"
    >
      <MLMediaCard
        :item="item"
        :priority="index < 8"
        :ratio-override="0.75"
        :selectable="selectable"
        :selected="selectedSet.has(item.id)"
        :liked="likedSet.has(item.id)"
        @open="emit('open', index)"
        @toggle="(id, shift) => emit('toggle', id, shift)"
        @toggle-like="emit('toggle-like', $event)"
        @filter-color="emit('filter-color', $event)"
      />
    </div>
  </div>

  <!-- 紧凑列表模式：适合快速扫元信息与批量管理 -->
  <div v-else class="list-view">
    <div
      v-for="(item, index) in items"
      :key="item.id"
      :data-item-id="item.id"
      :class="['list-row', { 'list-row--picked': selectable && selectedSet.has(item.id) }]"
      @mouseenter="item.kind === 'video' && item.preview_file && (previewingRowId = item.id)"
      @mouseleave="previewingRowId === item.id && (previewingRowId = null)"
    >
      <button
        type="button"
        class="list-row__main"
        :aria-pressed="selectable ? selectedSet.has(item.id) : undefined"
        @click="selectable ? emit('toggle', item.id, $event.shiftKey) : emit('open', index)"
      >
        <span
          v-if="selectable"
          :class="['list-row__check', { 'list-row__check--on': selectedSet.has(item.id) }]"
          aria-hidden="true"
        >
          {{ selectedSet.has(item.id) ? '✓' : '' }}
        </span>
        <div class="list-row__thumb">
          <SmartImage
            :id="item.id"
            :file="item.file"
            :kind="item.kind"
            :color="item.dominant_color"
            :ratio="0.75"
            :display-width="120"
            :version="item.updated_at"
          />
          <img
            v-if="previewingRowId === item.id && item.preview_file"
            :src="`/p/${item.preview_file}`"
            alt=""
            aria-hidden="true"
            class="list-row__preview"
          />
          <span v-if="item.kind === 'video'" class="list-row__vbadge mono" aria-hidden="true">
            ▶{{ item.duration ? `${Math.round(item.duration)}s` : '' }}
          </span>
        </div>
        <div class="list-row__info">
          <span class="list-row__title">
            <span class="list-row__title-text" :title="item.title || item.name">{{ item.title || item.name }}</span>
          </span>
          <span class="list-row__tags">
            <span
              v-for="tag in (item.tags ?? []).slice(0, 4)"
              :key="tag"
              class="list-row__tag"
              @click.stop="!selectable && emit('filter-tag', tag)"
            >
              {{ tag }}
            </span>
          </span>
        </div>
        <span class="list-row__spec mono">
          <template v-if="item.width && item.height">{{ formatNumber(item.width) }}×{{ formatNumber(item.height) }}</template>
          <template v-if="item.ext"> · {{ item.ext.replace(/^\./, '').toUpperCase() }}</template>
          <template v-if="item.size"> · {{ formatBytes(item.size) }}</template>
          <template v-if="item.ts"> · {{ formatDate(item.ts) }}</template>
        </span>
      </button>
      <button
        v-if="!selectable && item.dominant_color"
        type="button"
        class="list-row__swatch"
        :style="{ backgroundColor: item.dominant_color }"
        :aria-label="t('card.filterColor', { color: item.dominant_color })"
        :title="t('card.filterColor', { color: item.dominant_color })"
        @click.stop="emit('filter-color', item.dominant_color)"
      />
      <button
        v-if="!selectable"
        type="button"
        :class="['list-row__like', { 'list-row__like--on': likedSet.has(item.id) }]"
        :aria-pressed="likedSet.has(item.id)"
        :aria-label="likedSet.has(item.id) ? t('card.unlike') : t('card.like')"
        @click="emit('toggle-like', item.id)"
      >
        <span aria-hidden="true">{{ likedSet.has(item.id) ? '♥' : '♡' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.masonry {
  position: relative;
  width: 100%;
}

.masonry__ghost {
  /* 占位不绘制任何内容，避免触发额外绘制与图片请求 */
  background: transparent;
}

.masonry__cell {
  position: absolute;
  top: 0;
  left: 0;
  /* 用 transform 定位，交给合成层，滚动更顺滑（D-17 前置） */
  will-change: transform;
  /* 只对宽度做过渡：位置由 transform 驱动，无需过渡，
     否则列数变化时会看到卡片"飞过去"的拖影（实测观感差） */
}

/* ---------- 等高网格视图 ---------- */
.grid-view {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--grid-min, 220px), 1fr));
  gap: var(--p-space-4);
}

.grid-view__cell {
  min-width: 0;
}

@media (max-width: 600px) {
  .grid-view {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--p-space-2);
  }
}

/* ---------- 紧凑列表视图 ---------- */
.list-view {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
}

.list-row {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-md);
  background: var(--surface);
  border: 1px solid var(--rule);
  transition:
    border-color var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.list-row:hover,
.list-row:focus-within {
  border-color: var(--rule-strong);
  background: var(--surface-hover);
}

.list-row--picked {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.list-row__main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  text-align: left;
}

.list-row__check {
  width: 20px;
  height: 20px;
  border-radius: var(--p-radius-full);
  border: 1.5px solid var(--rule-strong);
  background: var(--surface-sunken);
  color: var(--on-accent);
  font-size: 0.75rem;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.list-row__check--on {
  background: var(--accent);
  border-color: var(--accent);
}

.list-row__thumb {
  position: relative;
  width: 72px;
  flex-shrink: 0;
  border-radius: var(--p-radius-sm);
  overflow: hidden;
}

.list-row__preview {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
}

.list-row__vbadge {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 4px;
  border-radius: var(--p-radius-sm);
  background: rgba(26, 24, 21, 0.76);
  color: #faf8f5;
  font-size: 0.625rem;
  line-height: 1.4;
}

.list-row__info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.list-row__title {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  font-size: var(--p-step-0);
  font-weight: 500;
  color: var(--ink);
  min-width: 0;
}

.list-row__color {
  width: 10px;
  height: 10px;
  border-radius: var(--p-radius-full);
  border: 1px solid var(--rule-strong);
  flex-shrink: 0;
}

.list-row__title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list-row__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.list-row__tag {
  font-size: 0.6875rem;
  color: var(--ink-muted);
  background: var(--surface-sunken);
  border-radius: var(--p-radius-full);
  padding: 0 7px;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.list-row__tag:hover {
  background: var(--accent-soft);
  color: var(--accent-hover);
}

.list-row__spec {
  font-size: var(--p-step--1);
  color: var(--ink-faint);
  white-space: nowrap;
  flex-shrink: 0;
}

.list-row__like {
  min-width: 32px;
  min-height: 32px;
  border-radius: var(--p-radius-full);
  color: var(--ink-muted);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.list-row__like:hover {
  background: var(--surface-sunken);
  color: var(--ink);
}

.list-row__like--on {
  color: var(--danger);
}

.list-row__swatch {
  width: 16px;
  height: 16px;
  border-radius: var(--p-radius-full);
  border: 1.5px solid var(--surface);
  box-shadow: 0 0 0 1px var(--rule-strong);
  flex-shrink: 0;
  transition: transform var(--p-dur-fast) var(--p-ease-out);
}

.list-row__swatch:hover {
  transform: scale(1.2);
}

@media (max-width: 640px) {
  .list-row__spec {
    display: none;
  }
}
</style>
