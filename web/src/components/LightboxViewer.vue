<script setup lang="ts">
/**
 * 灯箱（S0 最小版）
 *
 * S0 只实现必要闭环：打开、切换、缩放、Esc 关闭、焦点还原。
 * 对比模式 / 连播 / 色板 / 快捷键表在 S2（A-04）补齐。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MediaItem } from '@/api/types'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  item: MediaItem
  hasPrev: boolean
  hasNext: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'prev'): void
  (e: 'next'): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const zoom = ref(1)
const { t, formatBytes } = useI18n()

const mediaUrl = computed(() => `/f/${props.item.file}`)
const previewUrl = computed(() =>
  props.item.thumb ? `/t/${props.item.id}_lg.webp` : `/f/${props.item.file}`,
)

const spec = computed(() => {
  const parts: string[] = []
  if (props.item.width && props.item.height) {
    parts.push(`${props.item.width}×${props.item.height}`)
  }
  if (props.item.ext) parts.push(props.item.ext.toUpperCase())
  if (props.item.size) {
    // 体积按 locale 格式化，避免英文界面出现中文单位或反之
    parts.push(formatBytes(props.item.size))
  }
  return parts.join(' · ')
})

function close() {
  emit('close')
}

/** 键盘操作：输入态下不拦截（A-04 要求） */
function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null
  const tag = target?.tagName
  // 输入框 / 文本域 / 可编辑区内不响应快捷键
  if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
  // 输入法组字期间不响应
  if (e.isComposing) return

  switch (e.key) {
    case 'Escape':
      close()
      break
    case 'ArrowLeft':
      if (props.hasPrev) emit('prev')
      break
    case 'ArrowRight':
      if (props.hasNext) emit('next')
      break
    case '+':
    case '=':
      zoom.value = Math.min(zoom.value + 0.25, 4)
      break
    case '-':
    case '0':
      zoom.value = e.key === '0' ? 1 : Math.max(zoom.value - 0.25, 0.5)
      break
  }
}

// 打开时聚焦对话框，让键盘事件与焦点陷阱生效
watch(
  () => props.item.id,
  () => {
    zoom.value = 1
  },
)

onMounted(() => {
  dialogRef.value?.showModal()
  window.addEventListener('keydown', onKeydown)
  // 标记"灯箱开启"：隐藏 sticky 顶栏并锁定背景滚动。
  // dialog::backdrop 处于 top layer，但 sticky 元素仍会绘制在其上，
  // 必须显式隐藏顶栏，否则顶栏会浮在灯箱之上（实测发现）。
  document.documentElement.classList.add('lightbox-open')
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.documentElement.classList.remove('lightbox-open')
})
</script>

<template>
  <dialog
    ref="dialogRef"
    class="lightbox"
    :aria-label="t('lightbox.preview')"
    @close="close"
    @click="($event.target as HTMLElement).tagName === 'DIALOG' && close()"
  >
    <div class="lightbox__stage">
      <img
        v-if="item.kind === 'image'"
        :src="previewUrl"
        alt=""
        class="lightbox__img"
        :style="{ transform: `scale(${zoom})`, viewTransitionName: `media-${item.id}` }"
      />
      <video
        v-else
        :src="mediaUrl"
        :poster="`/t/${item.id}.jpg`"
        controls
        autoplay
        playsinline
        class="lightbox__video"
      />
    </div>

    <!-- 悬浮控制条：不抢画面 -->
    <div class="lightbox__bar">
      <div class="lightbox__info">
        <span class="lightbox__title">
          {{ item.title || item.name }}
          <!-- 授权状态（C-11）：不可商用必须有明确提示 -->
          <span v-if="item.commercial_ok === 0" class="badge-personal">
            {{ t('license.personalOnly') }}
          </span>
          <span v-else-if="item.license" class="badge-license mono">{{ item.license }}</span>
        </span>
        <span v-if="spec" class="lightbox__spec mono">{{ spec }}</span>
        <span v-if="item.credit" class="lightbox__credit">{{ item.credit }}</span>
      </div>

      <div class="lightbox__controls">
        <button
          type="button"
          class="lb-btn"
          :disabled="!hasPrev"
          :aria-label="t('lightbox.prev')"
          @click="$emit('prev')"
        >
          ←
        </button>
        <span class="lightbox__zoom mono">{{ Math.round(zoom * 100) }}%</span>
        <button
          type="button"
          class="lb-btn"
          :disabled="!hasNext"
          :aria-label="t('lightbox.next')"
          @click="$emit('next')"
        >
          →
        </button>
        <a :href="mediaUrl" download class="lb-btn" :aria-label="t('lightbox.download')">↓</a>
        <button type="button" class="lb-btn" :aria-label="t('lightbox.close')" @click="close">✕</button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.lightbox {
  width: 100vw;
  height: 100vh;
  max-width: 100vw;
  max-height: 100vh;
  padding: 0;
  border: none;
  background: transparent;
  color: #faf8f5;
  /* dialog 的 top layer 只盖得住同级 stacking context，
     sticky 顶栏（z-index 40）仍在视口内可见，需显式提高层级 */
  z-index: var(--p-z-lightbox);
}

.lightbox::backdrop {
  /* 灯箱用深底，让图片成为唯一焦点——这是纸感主题下唯一允许的深色面 */
  background: rgba(18, 16, 13, 0.94);
  /* 遮住包含 sticky 顶栏的整个视口 */
  z-index: var(--p-z-lightbox);
}

.lightbox__stage {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: var(--p-space-8) var(--p-space-6) 96px;
  overflow: hidden;
  /* 灯箱自身的进入动画：替代无法用于 dialog 的共享元素转场 */
  animation: lightbox-in var(--p-dur-base) var(--p-ease-out);
}

@keyframes lightbox-in {
  from {
    opacity: 0;
    transform: scale(0.985);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .lightbox__stage {
    animation: none;
  }
}

.lightbox__img,
.lightbox__video {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  transition: transform var(--p-dur-base) var(--p-ease-out);
}

.lightbox__bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-4);
  padding: var(--p-space-4) var(--p-space-5);
  background: linear-gradient(to top, rgba(18, 16, 13, 0.9), transparent);
}

.lightbox__info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.lightbox__title {
  font-size: var(--p-step-0);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lightbox__spec {
  font-size: var(--p-step--1);
  opacity: 0.75;
}

.lightbox__credit {
  font-size: var(--p-step--1);
  opacity: 0.6;
}

/* 授权徽标：角标形式，不抢画面但不可忽略 */
.badge-license,
.badge-personal {
  display: inline-block;
  margin-left: var(--p-space-2);
  padding: 0 6px;
  font-size: 0.6875rem;
  border-radius: var(--p-radius-sm);
  vertical-align: middle;
}

.badge-license {
  background: rgba(250, 248, 245, 0.16);
  color: #faf8f5;
}

.badge-personal {
  background: rgba(176, 74, 63, 0.9);
  color: #fff;
}

.lightbox__controls {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
  flex-shrink: 0;
}

.lb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  min-height: 34px;
  border-radius: var(--p-radius-md);
  color: inherit;
  font-size: 1rem;
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.lb-btn:hover:not(:disabled) {
  background: rgba(250, 248, 245, 0.14);
}

.lb-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.lightbox__zoom {
  font-size: var(--p-step--1);
  opacity: 0.7;
  min-width: 42px;
  text-align: center;
}
</style>
