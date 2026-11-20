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
import { computed, ref } from 'vue'
import type { MediaItem } from '@/api/types'
import { userTags } from '@/api/tags'
import SmartImage from './SmartImage.vue'
import { useI18n } from '@/composables/useI18n'

const props = withDefaults(
  defineProps<{
    item: MediaItem
    width?: number
    /** 首屏前若干张用 eager 加载并提升优先级（A-05） */
    priority?: boolean
    /** 批量选择模式：显示勾选圈（REQ-05） */
    selectable?: boolean
    /** 当前是否被选中 */
    selected?: boolean
    /** 是否已喜欢（C-15） */
    liked?: boolean
    /** 强制覆盖宽高比（等高网格视图用） */
    ratioOverride?: number
  }>(),
  {
    width: 320,
    priority: false,
    selectable: false,
    selected: false,
    liked: false,
  },
)

const emit = defineEmits<{
  (e: 'open', item: MediaItem): void
  /** 选择模式下点击卡片是勾选而非打开，透传 shiftKey 支持区间连选 */
  (e: 'toggle', id: string, shiftKey?: boolean): void
  /** 喜欢/取消喜欢 */
  (e: 'toggle-like', id: string): void
  /** 按主色筛选 */
  (e: 'filter-color', color: string): void
}>()

/** 视频悬停动态预览（后端预生成的 3s WebP）：
 *  用独立叠加层换图，不改写 SmartImage 的 src（会破坏 srcset 选择）。
 */
const previewing = ref(false)
const previewSrc = computed(() =>
  props.item.preview_file ? `/p/${props.item.preview_file}` : '',
)

function onClick(e: MouseEvent) {
  if (!props.selectable) {
    emit('open', props.item)
    return
  }
  if (e.shiftKey) emit('toggle', props.item.id, true)
  else emit('toggle', props.item.id)
}

const { t, formatNumber, formatDuration } = useI18n()

/** 后端返回的宽高比，缺失时按 1:1 兜底；支持外部网格模式强制等高比例 */
const ratio = computed(() => {
  if (props.ratioOverride) return props.ratioOverride
  const { width: w, height: h } = props.item
  if (!w || !h) return 1
  // 限制极端比例，避免长图撑满视口
  return Math.min(Math.max(h / w, 0.4), 2.4)
})

const displayTitle = computed(() => props.item.title || props.item.name)

const meta = computed(() => {
  const parts: string[] = []
  if (props.item.width && props.item.height) {
    parts.push(`${formatNumber(props.item.width)}×${formatNumber(props.item.height)}`)
  }
  if (props.item.kind === 'video' && props.item.duration) {
    parts.push(formatDuration(props.item.duration))
  }
  return parts.join(' · ')
})

/**
 * alt 规则：有可见标题时为 alt=""（装饰性），
 * 仅当无标题时才生成描述性文本。
 */
const altText = computed(() =>
  props.item.title ? '' : t('card.mediaAlt', { name: props.item.name }),
)

/** 后处理状态标签属于内部元数据，不占用用户可见的标签位置 */
const visibleTags = computed(() => userTags(props.item.tags))

/** 底部主胶囊：有标签显示首标签，无标签时回退作者或外链平台，让卡片底栏左右均衡 */
const primaryPill = computed(() => {
  if (visibleTags.value.length) return visibleTags.value[0]
  if (props.item.author) return props.item.author
  if (props.item.source_platform && props.item.source_platform !== 'local') {
    return props.item.source_platform
  }
  return ''
})

const extraTagCount = computed(() => Math.max(0, visibleTags.value.length - 1))
</script>

<template>
  <article :class="['ml-card', { 'ml-card--picked': selectable && selected }]">
    <button
      type="button"
      class="ml-card__trigger"
      :aria-pressed="selectable ? selected : undefined"
      @click="onClick"
      @mouseenter="item.kind === 'video' && previewSrc && (previewing = true)"
      @mouseleave="previewing = false"
    >
      <div
        class="ml-card__media"
        :style="{ viewTransitionName: `media-${item.id}` }"
      >
        <SmartImage
          :id="item.id"
          :file="item.file"
          :kind="item.kind"
          :priority="priority"
          :color="item.dominant_color"
          :alt="altText"
          :ratio="ratio"
          :display-width="width"
          :version="item.updated_at"
        />
        <!-- 视频悬停动态预览：叠加在海报帧上，移出即停。
             桌面 hover 设备才显示（触屏长按会误触） -->
        <img
          v-if="previewing && previewSrc"
          :src="previewSrc"
          alt=""
          aria-hidden="true"
          class="ml-card__preview"
        />
        <!-- 悬停边缘保护渐变：确保浅色图上的喜欢心形与色点清晰可辨 -->
        <span class="ml-card__scrim" aria-hidden="true" />
        <!-- 视频只保留右上角小三角播放标记（参考小红书），不再堆叠格式与时长胶囊 -->
        <span
          v-if="item.kind === 'video' && !selectable"
          class="ml-card__video-mark"
          role="img"
          :aria-label="t('facet.kindVideo')"
          :title="item.duration ? `${t('facet.kindVideo')} · ${formatDuration(item.duration)}` : t('facet.kindVideo')"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 5.2v13.6L19.2 12 8 5.2Z" fill="currentColor" />
          </svg>
        </span>
        <!-- 不可商用授权提示：卡片态一目了然，避免选图后才发现受限 -->
        <span
          v-if="!selectable && item.commercial_ok === 0"
          class="ml-card__personal"
          :title="t('license.personalOnly')"
        >
          {{ t('card.personal') }}
        </span>
        <!-- 选择圈：选择模式下常驻，避免 hover 才可见导致移动端不可用 -->
        <span v-if="selectable" :class="['ml-card__check', { 'ml-card__check--on': selected }]" aria-hidden="true">
          {{ selected ? '✓' : '' }}
        </span>
      </div>

      <!-- 标题与数据：固定盒高（64px），保证瀑布流列高计算零偏差 -->
      <div class="ml-card__meta">
        <span class="ml-card__title" :title="displayTitle">{{ displayTitle }}</span>
        <span class="ml-card__foot">
          <span v-if="primaryPill" class="ml-card__tag">{{ primaryPill }}</span>
          <span v-if="extraTagCount > 0" class="ml-card__tag-more mono">+{{ extraTagCount }}</span>
          <span v-if="meta" class="ml-card__spec mono">{{ meta }}</span>
        </span>
      </div>
    </button>

    <!-- 独立喜欢按钮（与主按钮为兄弟节点，避免嵌套 button 破坏可访问性） -->
    <button
      v-if="!selectable"
      type="button"
      :class="['ml-card__like', { 'ml-card__like--on': liked }]"
      :aria-pressed="liked"
      :aria-label="liked ? t('card.unlike') : t('card.like')"
      :title="liked ? t('card.unlike') : t('card.like')"
      @click.stop="emit('toggle-like', item.id)"
    >
      <span aria-hidden="true">{{ liked ? '♥' : '♡' }}</span>
    </button>

    <!-- 主色点：hover 时浮现于媒体左下角，点击按此主色筛选 -->
    <button
      v-if="!selectable && item.dominant_color"
      type="button"
      class="ml-card__swatch"
      :style="{ backgroundColor: item.dominant_color }"
      :aria-label="t('card.filterColor', { color: item.dominant_color })"
      :title="t('card.filterColor', { color: item.dominant_color })"
      @click.stop="emit('filter-color', item.dominant_color)"
    />
  </article>
</template>

<style scoped>
.ml-card--picked {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--p-radius-lg);
}

/* 视频角标：只用右上角小三角，不叠加格式/时长胶囊 */
.ml-card__video-mark {
  position: absolute;
  top: var(--p-space-2);
  right: var(--p-space-2);
  z-index: 1;
  display: inline-flex;
  color: rgba(255, 255, 255, 0.96);
  line-height: 0;
  pointer-events: none;
  filter: drop-shadow(0 1px 3px rgba(18, 16, 13, 0.65));
}

/* 悬停动态预览叠加层：铺满媒体区，覆盖海报帧 */
.ml-card__preview {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
}

.ml-card__scrim {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  background: linear-gradient(
    to bottom,
    rgba(26, 24, 21, 0.24) 0%,
    transparent 26%,
    transparent 74%,
    rgba(26, 24, 21, 0.26) 100%
  );
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.ml-card:hover .ml-card__scrim,
.ml-card:focus-within .ml-card__scrim {
  opacity: 1;
}

@media (hover: none) {
  .ml-card__preview {
    display: none;
  }
}

.ml-card__check {
  position: absolute;
  top: var(--p-space-2);
  right: var(--p-space-2);
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: var(--p-radius-full);
  border: 1.5px solid rgba(255, 255, 255, 0.9);
  background: rgba(18, 16, 13, 0.35);
  color: #fff;
  font-size: 0.8125rem;
  line-height: 1;
  backdrop-filter: blur(2px);
}

.ml-card__check--on {
  background: var(--accent);
  border-color: var(--accent);
}

.ml-card {
  position: relative;
  display: block;
  width: 100%;
  border-radius: var(--p-radius-lg);
  /* 小红书式：整卡轻微上浮，图片圆角统一 */
  transition:
    transform var(--p-dur-base) var(--p-ease-out),
    box-shadow var(--p-dur-base) var(--p-ease-out);
}

.ml-card__trigger {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  border-radius: var(--p-radius-lg);
  padding: 0;
}

.ml-card__like {
  position: absolute;
  top: var(--p-space-2);
  left: var(--p-space-2);
  z-index: 2;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--p-radius-full);
  border: 1px solid rgba(255, 255, 255, 0.24);
  background: rgba(26, 24, 21, 0.56);
  color: #faf8f5;
  font-size: 0.875rem;
  line-height: 1;
  backdrop-filter: blur(4px);
  opacity: 0;
  transform: scale(0.92);
  transition:
    opacity var(--p-dur-fast) var(--p-ease-out),
    transform var(--p-dur-fast) var(--p-ease-spring),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.ml-card__swatch {
  position: absolute;
  left: var(--p-space-2);
  bottom: calc(64px + var(--p-space-2));
  z-index: 2;
  width: 16px;
  height: 16px;
  border-radius: var(--p-radius-full);
  border: 1.5px solid rgba(255, 255, 255, 0.92);
  box-shadow:
    0 0 0 1px rgba(26, 24, 21, 0.28),
    0 2px 6px rgba(26, 24, 21, 0.3);
  opacity: 0;
  transform: scale(0.85);
  transition:
    opacity var(--p-dur-fast) var(--p-ease-out),
    transform var(--p-dur-fast) var(--p-ease-out);
}

.ml-card:hover .ml-card__swatch,
.ml-card:focus-within .ml-card__swatch {
  opacity: 1;
  transform: scale(1);
}

.ml-card__swatch:hover {
  transform: scale(1.18);
}

.ml-card:hover .ml-card__like,
.ml-card:focus-within .ml-card__like,
.ml-card__like--on {
  opacity: 1;
  transform: scale(1);
}

.ml-card__like--on {
  background: color-mix(in srgb, var(--danger) 90%, transparent);
  color: #fff;
}

@media (hover: none) {
  .ml-card__like {
    opacity: 0.88;
    transform: scale(1);
  }
}

/* 触屏设备没有 hover，:hover 会"粘住"导致卡片一直浮起。
   限定只有真正支持 hover 的设备才应用位移。 */
@media (hover: hover) {
  .ml-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--card-shadow-hover);
  }

  .ml-card:hover .ml-card__media :deep(.smart-image__img) {
    transform: scale(1.018);
  }
}

.ml-card__media :deep(.smart-image__img) {
  transition:
    opacity var(--p-dur-base) var(--p-ease-out),
    transform var(--p-dur-slow) var(--p-ease-out);
}

.ml-card:has(.ml-card__trigger:focus-visible) {
  transform: translateY(-2px);
  box-shadow: var(--card-shadow-hover);
}

.ml-card__media {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: var(--p-radius-lg);
  background: var(--surface-sunken);
}

.ml-card__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 图片是唯一高饱和元素，其余 UI 全部退让 */
  transition: opacity var(--p-dur-base) var(--p-ease-out);
}

.ml-card__personal {
  position: absolute;
  left: var(--p-space-2);
  bottom: var(--p-space-2);
  padding: 1px 6px;
  font-size: 0.625rem;
  font-weight: 500;
  border-radius: var(--p-radius-sm);
  background: color-mix(in srgb, var(--danger) 88%, transparent);
  color: #fff;
  pointer-events: none;
}

.ml-card__meta {
  padding: var(--p-space-2) 2px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.ml-card:hover .ml-card__meta,
.ml-card:focus-visible .ml-card__meta {
  opacity: 1;
}

.ml-card__title {
  /* 统一两行固定盒高：与 MasonryGrid META_HEIGHT=64 像素级对齐，杜绝列内卡片纵向重叠 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  overflow-wrap: anywhere;
  word-break: break-word;
  font-size: var(--p-step--1);
  font-weight: 500;
  line-height: 17px;
  min-height: 34px;
  color: var(--ink);
}

/* 底部信息行：标签 + 规格，弱化但不低于 AA 对比度 */
.ml-card__foot {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  height: 18px;
  min-width: 0;
}

.ml-card__tag {
  font-size: 0.6875rem;
  color: var(--ink-muted);
  background: var(--surface-sunken);
  border-radius: var(--p-radius-full);
  padding: 0 7px;
  flex-shrink: 0;
  max-width: 55%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ml-card__tag-more {
  font-size: 0.625rem;
  color: var(--ink-faint);
  flex-shrink: 0;
}

.ml-card__spec {
  font-size: 0.6875rem;
  color: var(--ink-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 减弱动效时取消位移（A-03） */
@media (prefers-reduced-motion: reduce) {
  .ml-card:hover,
  .ml-card:focus-visible {
    transform: none;
  }
}
@media (hover: none) {
  /* 触屏没有 hover：喜欢按钮常显并放大到可稳定点按的尺寸 */
  .ml-card__like {
    width: 36px;
    height: 36px;
    top: 6px;
    left: 6px;
    opacity: 0.92;
    transform: scale(1);
    font-size: 1rem;
  }

  /* 主色圆点在触屏上会压住图片左下角，影响看图；按主色筛选仍可从分面面板进入 */
  .ml-card__swatch {
    display: none;
  }
}

@media (max-width: 680px) {
  /* 手机屏幕下把 10–11px 的元信息提升到 12px，并保持 64px 固定盒高 */
  .ml-card__tag,
  .ml-card__spec {
    font-size: 0.75rem;
    line-height: 18px;
  }

  .ml-card__tag-more {
    font-size: 0.6875rem;
  }

  .ml-card__personal {
    font-size: 0.6875rem;
  }
}

</style>
