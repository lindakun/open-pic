<script setup lang="ts">
/**
 * MLButton —— 基础按钮
 *
 * 使用原生 <button>，天然获得键盘可达与屏幕阅读器支持（E-20）。
 * variant 控制视觉权重，不做成"色块堆叠"，靠字重与极轻底色区分。
 */
withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'quiet' | 'danger'
    size?: 'sm' | 'md'
    disabled?: boolean
    loading?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  {
    variant: 'ghost',
    size: 'md',
    disabled: false,
    loading: false,
    type: 'button',
  },
)
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    :class="['ml-btn', `ml-btn--${variant}`, `ml-btn--${size}`, { 'ml-btn--loading': loading }]"
  >
    <span v-if="loading" class="ml-btn__spin" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.ml-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--p-space-2);
  font-family: var(--p-font-text);
  font-weight: 500;
  letter-spacing: 0.01em;
  border-radius: var(--p-radius-md);
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out),
    transform var(--p-dur-fast) var(--p-ease-out);
  /* WCAG 2.2 AA：2.5.8 目标尺寸 ≥24px */
  min-height: 32px;
  white-space: nowrap;
  border: 1px solid transparent;
}

.ml-btn:active:not(:disabled) {
  transform: scale(0.975);
}

@media (prefers-reduced-motion: reduce) {
  .ml-btn:active:not(:disabled) {
    transform: none;
  }
}

@media (max-width: 680px) {
  .ml-btn {
    min-height: 36px;
  }

  .ml-btn--md {
    min-height: 40px;
  }

  .ml-btn--sm {
    min-height: 32px;
  }
}

.ml-btn--md {
  padding: 0 var(--p-space-4);
  font-size: var(--p-step-0);
  min-height: 36px;
}

.ml-btn--sm {
  padding: 0 var(--p-space-3);
  font-size: var(--p-step--1);
  min-height: 28px;
}

.ml-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 主操作：低饱和赭石实底，全站唯一的高权重色块 */
.ml-btn--primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--on-accent);
}

.ml-btn--primary:disabled {
  background: var(--surface-sunken);
  border-color: var(--rule-strong);
  color: var(--ink-muted);
  opacity: 0.72;
}

.ml-btn--primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

/* 次操作：极浅描边，纸感克制 */
.ml-btn--ghost {
  background: transparent;
  color: var(--ink);
  border-color: var(--rule-strong);
}

.ml-btn--ghost:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--ink-faint);
}

/* 弱操作：无边框纯文字 */
.ml-btn--quiet {
  background: transparent;
  color: var(--ink-muted);
}

.ml-btn--quiet:hover:not(:disabled) {
  color: var(--ink);
  background: var(--surface-hover);
}

.ml-btn--danger {
  background: transparent;
  color: var(--danger);
  border-color: transparent;
}

.ml-btn--danger:hover:not(:disabled) {
  background: var(--danger-soft);
}

.ml-btn__spin {
  width: 13px;
  height: 13px;
  border-radius: var(--p-radius-full);
  border: 1.8px solid currentColor;
  border-top-color: transparent;
  animation: ml-btn-spin 650ms linear infinite;
  flex-shrink: 0;
}

@keyframes ml-btn-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ml-btn__spin {
    animation: none;
  }
}
</style>
