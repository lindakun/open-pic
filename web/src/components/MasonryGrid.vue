<script setup lang="ts">
/**
 * 瀑布流容器
 *
 * 列式绝对定位：按容器宽度算列数，逐项放入当前最矮的列。
 * 依赖后端返回的 aspect_ratio，缺省按 1:1（§4 A-05）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MediaItem } from '@/api/types'
import MLMediaCard from './MLMediaCard.vue'

const props = withDefaults(
  defineProps<{
    items: MediaItem[]
    /**
     * 艺术墙模式：列宽不再完全均等、部分图片放大、
     * 每列带轻微垂直错位，形成错落而非规整网格的观感。
     */
    artistic?: boolean
    /** 列宽基准（px），艺术墙模式下在此基础上浮动 */
    baseColumnWidth?: number
    /** 批量选择模式（REQ-05） */
    selectable?: boolean
    /** 已选中的 id 集合 */
    selectedIds?: string[]
  }>(),
  {
    artistic: false,
    baseColumnWidth: 280,
    selectable: false,
    selectedIds: () => [],
  },
)

const emit = defineEmits<{
  (e: 'open', index: number): void
  (e: 'toggle', id: string): void
}>()

const selectedSet = computed(() => new Set(props.selectedIds))

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
 * 卡片信息层高度（标题两行 + 信息行 + 间距）。
 * 与 MLMediaCard 的实际高度对齐，否则列高会逐张累积偏差导致底部不齐。
 * 实测：标题两行 47px；单行标题时略矮，取两者中间值以平衡。
 */
const META_HEIGHT = 46

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

/** 当前滚动位置与视口高度：驱动可见区间计算 */
const scrollY = ref(0)
const viewportH = ref(0)
/** 弱网/省流量模式：批量降为 24（D-17） */
const saveData = ref(false)

function measure() {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.clientWidth
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
  // 容器宽度变化（窗口缩放、侧栏开合）时重排
  observer = new ResizeObserver(measure)
  if (containerRef.value) observer.observe(containerRef.value)

  const conn = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string }
  }).connection
  saveData.value = Boolean(conn?.saveData)

  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', measure, { passive: true })
  onScroll()
})

onUnmounted(() => {
  observer?.disconnect()
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', measure)
  if (scrollTimer !== undefined) window.clearTimeout(scrollTimer)
})

// 条目追加后立即重算一次，避免新卡片在可视区外被误判为回收
watch(() => props.items.length, () => {
  measure()
  onScroll()
})

defineExpose({ renderedCount, isVisible, visibleRange, saveData })
</script>

<template>
  <div
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
        @open="emit('open', index)"
        @toggle="emit('toggle', $event)"
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
  transition: width var(--p-dur-base) var(--p-ease-out);
}
</style>
