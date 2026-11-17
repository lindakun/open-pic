<script setup lang="ts">
/**
 * MLToast —— 轻提示
 *
 * 使用 aria-live="polite" 播报，不抢焦点（E-20）。
 * 由 useToast 组合式函数统一驱动，挂载点唯一。
 */
import type { ToastItem } from '@/composables/useToast'

defineProps<{
  toasts: readonly ToastItem[]
}>()

defineEmits<{
  (e: 'dismiss', id: number): void
}>()
</script>

<template>
  <!-- 容器常驻，内容变化时 aria-live 才会播报 -->
  <div class="ml-toast-stack" role="status" aria-live="polite" aria-atomic="false">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      :class="['ml-toast', `ml-toast--${toast.tone}`]"
    >
      <span class="ml-toast__msg">{{ toast.message }}</span>
      <button
        type="button"
        class="ml-toast__close"
        aria-label="关闭提示"
        @click="$emit('dismiss', toast.id)"
      >
        ×
      </button>
    </div>
  </div>
</template>

<style scoped>
.ml-toast-stack {
  position: fixed;
  left: 50%;
  bottom: var(--p-space-6);
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
  z-index: var(--p-z-toast);
  pointer-events: none;
}

.ml-toast {
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
  animation: toast-in var(--p-dur-base) var(--p-ease-spring);
}

.ml-toast--error {
  background: var(--danger);
  color: #fff;
}

.ml-toast--success {
  background: var(--success);
  color: #fff;
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
  .ml-toast {
    animation: none;
  }
}
</style>
