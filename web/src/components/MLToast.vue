<script setup lang="ts">
/**
 * MLToast —— 轻提示
 *
 * 使用 aria-live="polite" 播报，不抢焦点（E-20）。
 * 由 useToast 组合式函数统一驱动，挂载点唯一。
 */
import type { ToastItem } from '@/composables/useToast'
import { useToast } from '@/composables/useToast'
import { useI18n } from '@/composables/useI18n'

defineProps<{
  toasts: readonly ToastItem[]
}>()

defineEmits<{
  (e: 'dismiss', id: number): void
}>()

const { t } = useI18n()
const { pause, resume } = useToast()
</script>

<template>
  <!-- 容器常驻，内容变化时 aria-live 才会播报 -->
  <TransitionGroup tag="div" name="ml-toast" class="ml-toast-stack" role="status" aria-live="polite" aria-atomic="false">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      :class="['ml-toast', `ml-toast--${toast.tone}`]"
      @mouseenter="pause(toast.id)"
      @mouseleave="resume(toast.id)"
    >
      <span class="ml-toast__icon mono" aria-hidden="true">
        {{ toast.tone === 'success' ? '✓' : toast.tone === 'error' ? '!' : 'i' }}
      </span>
      <span class="ml-toast__msg">{{ toast.message }}</span>
      <button
        type="button"
        class="ml-toast__close"
        :aria-label="t('toast.close')"
        @click="$emit('dismiss', toast.id)"
      >
        ×
      </button>
      <span
        class="ml-toast__timer"
        :style="{ animationDuration: `${toast.duration ?? 2600}ms` }"
        aria-hidden="true"
      />
    </div>
  </TransitionGroup>
</template>

<style scoped>
.ml-toast-stack {
  position: fixed;
  left: 50%;
  /* 批量操作条占据底部中央，toast 需要让位，否则两者重叠看不清 */
  bottom: calc(var(--p-space-6) + env(safe-area-inset-bottom, 0px) + var(--batch-bar-offset, 0px));
  transition: bottom var(--p-dur-base) var(--p-ease-out);
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
  z-index: var(--p-z-toast);
  pointer-events: none;
}

.ml-toast {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-2) var(--p-space-2) var(--p-space-4);
  background: var(--ink);
  color: var(--ink-inverse);
  border-radius: var(--p-radius-md);
  box-shadow: var(--sheet-shadow);
  font-size: var(--p-step--1);
  pointer-events: auto;
  max-width: min(420px, 90vw);
}

.ml-toast__timer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.32);
  transform-origin: left center;
  animation: toast-countdown linear forwards;
  pointer-events: none;
}

.ml-toast:hover .ml-toast__timer {
  animation-play-state: paused;
}

@keyframes toast-countdown {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

.ml-toast-enter-active,
.ml-toast-leave-active {
  transition:
    opacity var(--p-dur-base) var(--p-ease-out),
    transform var(--p-dur-base) var(--p-ease-spring);
}

.ml-toast-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.96);
}

.ml-toast-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.96);
}

.ml-toast--error {
  background: var(--danger);
  color: #fff;
}

.ml-toast--success {
  background: var(--success);
  color: #fff;
}

.ml-toast__icon {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: var(--p-radius-full);
  background: rgba(255, 255, 255, 0.18);
  font-size: 0.75rem;
  font-weight: 700;
  flex-shrink: 0;
}

.ml-toast__msg {
  flex: 1;
  overflow-wrap: anywhere;
}

.ml-toast__close {
  color: inherit;
  opacity: 0.65;
  font-size: 1.125rem;
  line-height: 1;
  padding: var(--p-space-1);
  min-width: 24px;
  min-height: 24px;
  border-radius: var(--p-radius-sm);
}

.ml-toast__close:hover {
  opacity: 1;
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 减弱动效：仅淡入（A-03） */
@media (prefers-reduced-motion: reduce) {
  .ml-toast-enter-active,
  .ml-toast-leave-active,
  .ml-toast__timer {
    transition: none;
    animation: none;
  }
}
</style>
