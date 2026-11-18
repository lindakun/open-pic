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
import { computed, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'

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
    /**
     * 版本号（通常传 item.updated_at）。
     * 后台处理完成后版本变化会重置加载状态并给 URL 加缓存参数，
     * 让之前 404 的缩略图重新拉取，而不是一直停在失败占位。
     */
    version?: number | string
  }>(),
  {
    kind: 'image',
    displayWidth: 640,
    priority: false,
    alt: '',
    ratio: 1,
  },
)

const { t } = useI18n()
const loaded = ref(false)
/** 加载失败：展示占位图标而非永远的空白块 */
const failed = ref(false)
const retrySeed = ref(0)

const versionQuery = computed(() => {
  const v = props.version
  const base = v === undefined || v === null || v === '' ? '' : `v=${v}`
  if (!retrySeed.value) return base
  return base ? `${base}&r=${retrySeed.value}` : `r=${retrySeed.value}`
})

function onError() {
  failed.value = true
  // 失败时也显示容器，避免一直透明看起来像卡死
  loaded.value = true
}

function retryLoad() {
  failed.value = false
  loaded.value = false
  retrySeed.value += 1
}

/** 白名单档位，与后端 ALLOWED_WIDTHS 保持一致 */
const WIDTHS = [360, 720, 960, 1440, 1920]

/** 只生成不大于"容器宽度 × 1.5"的档位，避免为小图请求超大档 */
const availableWidths = computed(() => {
  const max = Math.max(props.displayWidth * 1.6, 360)
  return WIDTHS.filter((w) => w <= max || w === 360)
})

const srcset = computed(() =>
  availableWidths.value
    .map((w) => `/img/${props.id}?w=${w}&fm=webp${versionQuery.value ? `&${versionQuery.value}` : ''} ${w}w`)
    .join(', '),
)

const avifSrcset = computed(() =>
  availableWidths.value
    .map((w) => `/img/${props.id}?w=${w}&fm=avif${versionQuery.value ? `&${versionQuery.value}` : ''} ${w}w`)
    .join(', '),
)

/** sizes 描述图片在页面上的实际渲染宽度，浏览器据此选档 */
const sizes = computed(() => {
  const cw = props.displayWidth
  if (cw < 480) return `${cw}px`
  if (cw < 900) return `(max-width: 780px) 50vw, ${cw}px`
  return `(max-width: 780px) 50vw, (max-width: 1120px) 33vw, ${cw}px`
})

/**
 * 兜底 src。
 *
 * 视频不能用 /f/ 原文件——浏览器会把视频当作图片解码失败，
 * 表现为纯黑块（线上实测）。后端已为视频生成海报帧 /t/{id}.jpg，
 * 这里直接用它作为卡片缩略图。
 */
const fallbackSrc = computed(() => {
  const v = versionQuery.value
  return props.kind === 'video'
    ? `/t/${props.id}.jpg${v ? `?${v}` : ''}`
    : `/img/${props.id}?w=720&fm=webp${v ? `&${v}` : ''}`
})

// 版本变化说明后台已补齐缩略图/元数据：重置失败态并重新发起加载
watch(
  () => props.version,
  () => {
    failed.value = false
    loaded.value = false
  },
)
</script>

<template>
  <div
    :class="['smart-image', { 'is-loading': !loaded && !failed }]"
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
        @error="onError"
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
      @error="onError"
    />
    <!-- 失败态：给明确视觉反馈，支持点击单卡重试 -->
    <button
      v-if="failed"
      type="button"
      class="smart-image__failed"
      :aria-label="t('image.retry')"
      :title="t('image.retry')"
      @click.stop="retryLoad"
    >
      <span class="smart-image__failed-inner">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <circle cx="8.5" cy="10" r="1.5" />
          <path d="m21 16-5-5-4 4-2-2-7 6" />
        </svg>
        <span class="smart-image__failed-label">{{ t('image.retryLabel') }}</span>
      </span>
    </button>
  </div>
</template>

<style scoped>
.smart-image {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: var(--p-radius-sm);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink) 6%, transparent);
}

/* 加载中微光骨架：克制的纸感对角光泽，图片淡入后自动撤除 */
.smart-image.is-loading::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    110deg,
    transparent 20%,
    color-mix(in srgb, var(--surface) 38%, transparent) 45%,
    transparent 70%
  );
  background-size: 220% 100%;
  animation: smart-shimmer 1.6s var(--p-ease-in-out) infinite;
  pointer-events: none;
}

@keyframes smart-shimmer {
  from {
    background-position: 120% 0;
  }
  to {
    background-position: -120% 0;
  }
}

/* <picture> 默认是 inline 元素、无高度，
   必须显式撑满容器，否则内部 img 的 height:100% 退化为 auto，
   会在等高容器底部露出主色占位条（实测发现的缺陷）。 */
.smart-image picture {
  display: block;
  width: 100%;
  height: 100%;
}

.smart-image__failed {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--ink-muted);
  background: color-mix(in srgb, var(--surface-sunken) 88%, transparent);
  opacity: 0.85;
  cursor: pointer;
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.smart-image__failed:hover {
  opacity: 1;
  color: var(--ink);
}

.smart-image__failed-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.smart-image__failed-label {
  font-size: 0.6875rem;
  opacity: 0;
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.smart-image__failed:hover .smart-image__failed-label,
.smart-image__failed:focus-visible .smart-image__failed-label {
  opacity: 0.9;
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

/* 减弱动效：直接显示，不做淡入与微光 */
@media (prefers-reduced-motion: reduce) {
  .smart-image.is-loading::after {
    animation: none;
    display: none;
  }
  .smart-image__img {
    transition: none;
  }
}
</style>
