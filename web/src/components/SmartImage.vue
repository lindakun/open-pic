<script setup lang="ts">
/**
 * SmartImage —— 统一响应式图片组件（REQ-V2-20 A-05）
 *
 * 职责：
 *   1. 生成 srcset/sizes，交给浏览器按 DPR 与容器宽度自选档位
 *   2. AVIF → WebP → 原图 三级回退（AVIF 为渐进增强）
 *   3. 主色占位 + 淡入，消除加载过程中的空白跳变（零抖动原则）
 *   4. 首屏项 eager + fetchpriority=high，其余 lazy
 *
 * 注意：悬停预览等"换图"场景请用独立的叠加层元素，
 * 不要改写本组件的 src（会破坏 srcset 选择）。
 */
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 资产 id */
    id: string
    /** 视频没有变换管线，传 file 走原图 */
    file?: string
    kind?: 'image' | 'video'
    /** 容器宽度提示，用于生成 sizes；默认按全宽 */
    displayWidth?: number
    /** 首屏优先项 */
    priority?: boolean
    /** 主色占位 */
    color?: string
    alt?: string
    /** 宽高比，用于预留高度防抖动 */
    ratio?: number
  }>(),
  {
    kind: 'image',
    displayWidth: 640,
    priority: false,
    alt: '',
    ratio: 1,
  },
)

const loaded = ref(false)

/** 白名单档位，与后端 ALLOWED_WIDTHS 保持一致 */
const WIDTHS = [360, 720, 960, 1440, 1920]

/** 只生成不大于"容器宽度 × 1.5"的档位，避免为小图请求超大档 */
const availableWidths = computed(() => {
  const max = Math.max(props.displayWidth * 1.6, 360)
  return WIDTHS.filter((w) => w <= max || w === 360)
})

const srcset = computed(() =>
  availableWidths.value
    .map((w) => `/img/${props.id}?w=${w}&fm=webp ${w}w`)
    .join(', '),
)

const avifSrcset = computed(() =>
  availableWidths.value
    .map((w) => `/img/${props.id}?w=${w}&fm=avif ${w}w`)
    .join(', '),
)

/** sizes 描述图片在页面上的实际渲染宽度，浏览器据此选档 */
const sizes = computed(() => {
  const cw = props.displayWidth
  if (cw < 480) return `${cw}px`
  if (cw < 900) return `(max-width: 780px) 50vw, ${cw}px`
  return `(max-width: 780px) 50vw, (max-width: 1120px) 33vw, ${cw}px`
})

/** 兜底 src：最小档 WebP；视频或无变换管线时回退原文件 */
const fallbackSrc = computed(() =>
  props.kind === 'video' && props.file
    ? `/f/${props.file}`
    : `/img/${props.id}?w=720&fm=webp`,
)
</script>

<template>
  <div
    class="smart-image"
    :style="{
      aspectRatio: `1 / ${ratio}`,
      backgroundColor: color || 'var(--surface-sunken)',
    }"
  >
    <picture v-if="kind === 'image'">
      <source type="image/avif" :srcset="avifSrcset" :sizes="sizes" />
      <source type="image/webp" :srcset="srcset" :sizes="sizes" />
      <img
        :src="fallbackSrc"
        :sizes="sizes"
        :alt="alt"
        :loading="priority ? 'eager' : 'lazy'"
        :fetchpriority="priority ? 'high' : 'auto'"
        decoding="async"
        :class="['smart-image__img', { 'is-loaded': loaded }]"
        @load="loaded = true"
      />
    </picture>

    <img
      v-else
      :src="fallbackSrc"
      :alt="alt"
      :loading="priority ? 'eager' : 'lazy'"
      decoding="async"
      :class="['smart-image__img', { 'is-loaded': loaded }]"
      @load="loaded = true"
    />
  </div>
</template>

<style scoped>
.smart-image {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: var(--p-radius-sm);
}

/* <picture> 默认是 inline 元素、无高度，
   必须显式撑满容器，否则内部 img 的 height:100% 退化为 auto，
   会在等高容器底部露出主色占位条（实测发现的缺陷）。 */
.smart-image picture {
  display: block;
  width: 100%;
  height: 100%;
}

.smart-image__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 先透明后淡入：主色占位期间不闪白（P2 零抖动） */
  opacity: 0;
  transition: opacity var(--p-dur-base) var(--p-ease-out);
}

.smart-image__img.is-loaded {
  opacity: 1;
}

/* 减弱动效：直接显示，不做淡入 */
@media (prefers-reduced-motion: reduce) {
  .smart-image__img {
    transition: none;
  }
}
</style>
