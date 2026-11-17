<script setup lang="ts">
/**
 * MLChip —— 筛选条件片
 *
 * 用于已选筛选条件的展示与移除（B-10）。
 * 可移除时渲染为按钮，纯展示时渲染为 span，避免误导性的可点击语义。
 */
withDefaults(
  defineProps<{
    label: string
    count?: number
    removable?: boolean
    active?: boolean
    tone?: 'default' | 'exclude'
  }>(),
  {
    removable: false,
    active: false,
    tone: 'default',
  },
)

defineEmits<{
  (e: 'remove'): void
  (e: 'click'): void
}>()
</script>

<template>
  <component
    :is="removable ? 'button' : 'span'"
    :type="removable ? 'button' : undefined"
    :class="['ml-chip', { 'ml-chip--active': active, 'ml-chip--exclude': tone === 'exclude' }]"
    @click="removable ? $emit('remove') : $emit('click')"
  >
    <span class="ml-chip__label">{{ label }}</span>
    <span v-if="count !== undefined" class="ml-chip__count mono">{{ count }}</span>
    <span v-if="removable" class="ml-chip__x" aria-hidden="true">×</span>
    <span v-if="removable" class="sr-only">移除筛选</span>
  </component>
</template>

<style scoped>
.ml-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-1);
  padding: 2px var(--p-space-3);
  min-height: 26px;
  font-size: var(--p-step--1);
  font-weight: 500;
  border-radius: var(--p-radius-full);
  background: var(--surface-sunken);
  color: var(--ink-muted);
  border: 1px solid transparent;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
  /* 英文文案比中文长 30–50%，允许换行不溢出（E-20） */
  max-width: 100%;
}

.ml-chip__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

button.ml-chip:hover {
  background: var(--accent-soft);
  color: var(--accent-hover);
}

.ml-chip--active {
  background: var(--accent-soft);
  color: var(--accent-hover);
  border-color: var(--accent);
}

/* 排除标签用删除线语义，不用红色（避免与危险操作混淆） */
.ml-chip--exclude .ml-chip__label {
  text-decoration: line-through;
  text-decoration-thickness: 1px;
}

.ml-chip__count {
  font-size: 0.6875rem;
  color: var(--ink-faint);
}

.ml-chip__x {
  font-size: 0.875rem;
  line-height: 1;
  opacity: 0.6;
}
</style>
