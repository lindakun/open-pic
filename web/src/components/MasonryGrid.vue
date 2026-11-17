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
  }>(),
  {},
)

defineEmits<{
  (e: 'open', index: number): void
}>()

const containerRef = ref<HTMLElement | null>(null)
const containerWidth = ref(0)

/** 列数按断点确定，与旧前端一致（2/3/4/5） */
const columns = computed(() => {
  const w = containerWidth.value
  if (w >= 1480) return 5
  if (w >= 1120) return 4
  if (w >= 780) return 3
  return 2
})

const gap = computed(() => (containerWidth.value < 600 ? 8 : 12))

const columnWidth = computed(() => {
  const c = columns.value
  return (containerWidth.value - gap.value * (c - 1)) / c
})

/** 计算每项的绝对位置 */
const layout = computed(() => {
  const cols = columns.value
  const cw = columnWidth.value
  const g = gap.value
  const heights = new Array(cols).fill(0)

  return props.items.map((item) => {
    const ratio = item.width && item.height
      ? Math.min(Math.max(item.height / item.width, 0.4), 2.4)
      : 1
    const h = Math.round(cw * ratio)

    // 找到最矮的列
    let target = 0
    for (let i = 1; i < cols; i++) {
      if (heights[i] < heights[target]) target = i
    }

    const pos = {
      left: target * (cw + g),
      top: heights[target],
      width: cw,
      height: h,
    }
    // 卡片还有信息层高度，参与下一行排版计算
    heights[target] += h + 44 + g
    return pos
  })
})

/** 容器总高度 = 最高列的底部 */
const containerHeight = computed(() => {
  const g = gap.value
  const cols = columns.value
  if (!layout.value.length) return 0
  const heights = new Array(cols).fill(0)
  layout.value.forEach((pos, i) => {
    const col = Math.round(pos.left / (columnWidth.value + g))
    const bottom = pos.top + pos.height + 44
    if (bottom > heights[col]) heights[col] = bottom
  })
  return Math.max(...heights, 0)
})

let observer: ResizeObserver | null = null

function measure() {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.clientWidth
  }
}

onMounted(() => {
  measure()
  // 容器宽度变化（窗口缩放、侧栏开合）时重排
  observer = new ResizeObserver(measure)
  if (containerRef.value) observer.observe(containerRef.value)
})

onUnmounted(() => {
  observer?.disconnect()
})

watch(() => props.items.length, measure)
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
      :style="{
        transform: `translate3d(${layout[index]?.left ?? 0}px, ${layout[index]?.top ?? 0}px, 0)`,
        width: `${layout[index]?.width ?? 0}px`,
      }"
    >
      <MLMediaCard
        :item="item"
        :priority="index < 4"
        @open="$emit('open', index)"
      />
    </div>
  </div>
</template>

<style scoped>
.masonry {
  position: relative;
  width: 100%;
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
