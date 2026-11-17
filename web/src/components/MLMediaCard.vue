<script setup lang="ts">
/**
 * MLMediaCard —— 媒体卡片
 *
 * 遵循 §2.3 纯图规范：
 *   - 默认无边框、无阴影
 *   - hover 时轻微浮起并显信息层
 *   - 有标题时 alt=""（避免与可见标题重复朗读，E-20）
 *
 * 使用 <button> 而非 <div onclick>，键盘可达（E-20 整改的 45 处之一）。
 */
import { computed } from 'vue'
import type { MediaItem } from '@/api/types'
import SmartImage from './SmartImage.vue'

const props = withDefaults(
  defineProps<{
    item: MediaItem
    width?: number
    /** 首屏前若干张用 eager 加载并提升优先级（A-05） */
    priority?: boolean
  }>(),
  {
    width: 320,
    priority: false,
  },
)

defineEmits<{
  (e: 'open', item: MediaItem): void
}>()

/** 后端返回的宽高比，缺失时按 1:1 兜底 */
const ratio = computed(() => {
  const { width: w, height: h } = props.item
  if (!w || !h) return 1
  // 限制极端比例，避免长图撑满视口
  return Math.min(Math.max(h / w, 0.4), 2.4)
})

const displayTitle = computed(() => props.item.title || props.item.name)

const meta = computed(() => {
  const parts: string[] = []
  if (props.item.width && props.item.height) {
    parts.push(`${props.item.width}×${props.item.height}`)
  }
  if (props.item.kind === 'video' && props.item.duration) {
    parts.push(`${Math.round(props.item.duration)}s`)
  }
  return parts.join(' · ')
})

/**
 * alt 规则：有可见标题时为 alt=""（装饰性），
 * 仅当无标题时才生成描述性文本。
 */
const altText = computed(() =>
  props.item.title ? '' : `媒体资源：${props.item.name}`,
)

</script>

<template>
  <button
    type="button"
    class="ml-card"
    @click="$emit('open', item)"
  >
    <div class="ml-card__media">
      <SmartImage
        :id="item.id"
        :file="item.file"
        :kind="item.kind"
        :priority="priority"
        :color="item.dominant_color"
        :alt="altText"
        :ratio="ratio"
        :display-width="width"
      />
      <span v-if="item.kind === 'video'" class="ml-card__badge mono" aria-label="视频">
        {{ item.duration ? `${Math.round(item.duration)}s` : 'VIDEO' }}
      </span>
    </div>

    <!-- 信息层：hover / 键盘聚焦时出现 -->
    <div class="ml-card__meta">
      <span class="ml-card__title">{{ displayTitle }}</span>
      <span v-if="meta" class="ml-card__spec mono">{{ meta }}</span>
    </div>
  </button>
</template>

<style scoped>
.ml-card {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  /* 无边框、无阴影（纯图规范）；只在 hover 时浮起 */
  border: none;
  border-radius: var(--p-radius-sm);
  padding: 0;
  transition:
    transform var(--p-dur-base) var(--p-ease-out),
    box-shadow var(--p-dur-base) var(--p-ease-out);
}

.ml-card:hover,
.ml-card:focus-visible {
  transform: translateY(-2px);
  box-shadow: var(--card-shadow-hover);
}

.ml-card__media {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: var(--p-radius-sm);
  background: var(--surface-sunken);
}

.ml-card__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 图片是唯一高饱和元素，其余 UI 全部退让 */
  transition: opacity var(--p-dur-base) var(--p-ease-out);
}

.ml-card__badge {
  position: absolute;
  right: var(--p-space-2);
  bottom: var(--p-space-2);
  padding: 1px var(--p-space-2);
  font-size: 0.6875rem;
  background: rgba(26, 24, 21, 0.72);
  color: #faf8f5;
  border-radius: var(--p-radius-sm);
  letter-spacing: 0.02em;
}

.ml-card__meta {
  padding: var(--p-space-2) 0 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  /* 默认半隐，hover 时提亮：让版面默认干净 */
  opacity: 0.62;
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.ml-card:hover .ml-card__meta,
.ml-card:focus-visible .ml-card__meta {
  opacity: 1;
}

.ml-card__title {
  font-size: var(--p-step--1);
  font-weight: 500;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ml-card__spec {
  font-size: 0.6875rem;
  color: var(--ink-faint);
}

/* 减弱动效时取消位移（A-03） */
@media (prefers-reduced-motion: reduce) {
  .ml-card:hover,
  .ml-card:focus-visible {
    transform: none;
  }
}
</style>
