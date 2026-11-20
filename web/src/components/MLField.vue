<script setup lang="ts">
/**
 * MLField —— 输入框
 *
 * 标签与输入框显式关联（for/id），错误信息用 aria-describedby 关联，
 * 状态变化通过 aria-live 播报（E-20）。
 */
import { computed, useId } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    label?: string
    placeholder?: string
    type?: 'text' | 'search' | 'number' | 'url'
    error?: string
    hint?: string
    disabled?: boolean
  }>(),
  {
    type: 'text',
    disabled: false,
  },
)

defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

// useId 保证多个实例的 id 唯一，避免标签错配
const uid = useId()
const inputId = computed(() => `field-${uid}`)
const hintId = computed(() => `${inputId.value}-hint`)
const errorId = computed(() => `${inputId.value}-error`)

const describedBy = computed(() => {
  const ids: string[] = []
  if (props.hint) ids.push(hintId.value)
  if (props.error) ids.push(errorId.value)
  return ids.length ? ids.join(' ') : undefined
})
</script>

<template>
  <div class="ml-field" :class="{ 'ml-field--error': !!error }">
    <label v-if="label" :for="inputId" class="ml-field__label">{{ label }}</label>
    <input
      :id="inputId"
      :value="modelValue"
      :type="type"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-invalid="!!error"
      :aria-describedby="describedBy"
      class="ml-field__input"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p v-if="hint && !error" :id="hintId" class="ml-field__hint">{{ hint }}</p>
    <!-- 错误用 role=alert 即时播报 -->
    <p v-if="error" :id="errorId" class="ml-field__error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.ml-field {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-1);
}

.ml-field__label {
  font-size: var(--p-step--1);
  font-weight: 500;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
}

.ml-field__input {
  font: inherit;
  font-size: var(--p-step-0);
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--rule-strong);
  border-radius: var(--p-radius-md);
  padding: var(--p-space-2) var(--p-space-3);
  min-height: 36px;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.ml-field__input::placeholder {
  color: var(--ink-faint);
}

.ml-field__input:hover:not(:disabled) {
  border-color: var(--ink-faint);
}

.ml-field__input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

.ml-field__input:disabled {
  background: var(--surface-sunken);
  cursor: not-allowed;
}

.ml-field--error .ml-field__input {
  border-color: var(--danger);
}

.ml-field__hint {
  font-size: var(--p-step--1);
  color: var(--ink-faint);
}

.ml-field__error {
  font-size: var(--p-step--1);
  color: var(--danger);
}
@media (max-width: 680px) {
  /* 防止 iOS Safari 聚焦 <16px 输入框时触发页面放大 */
  .ml-field__input {
    font-size: 16px;
  }
}
</style>
