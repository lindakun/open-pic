<script setup lang="ts">
/**
 * MLSheet —— 浮层容器
 *
 * 使用原生 <dialog>（A-03 要求）：免费获得焦点陷阱、Esc 关闭、
 * 顶层渲染与惰性焦点的正确语义，无需手写 div 遮罩。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    /** 'drawer' 从右侧滑出，'modal' 居中 */
    variant?: 'modal' | 'drawer'
    width?: string
  }>(),
  {
    variant: 'modal',
    width: '420px',
  },
)

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const { t } = useI18n()

function close() {
  emit('update:open', false)
}

/** 点击遮罩区域关闭：dialog 自身是遮罩，判断点是否落在内容外 */
function onBackdropClick(event: MouseEvent) {
  if (event.target === dialogRef.value) close()
}

watch(
  () => props.open,
  (isOpen) => {
    const el = dialogRef.value
    if (!el) return
    if (isOpen && !el.open) {
      el.showModal()
    } else if (!isOpen && el.open) {
      el.close()
    }
  },
  { immediate: true },
)

// <dialog> 在 Esc 关闭时会触发 cancel/close，需同步回父组件的状态
function onClose() {
  if (props.open) close()
}

onBeforeUnmount(() => {
  const el = dialogRef.value
  if (el?.open) el.close()
})
</script>

<template>
  <dialog
    ref="dialogRef"
    :class="['ml-sheet', `ml-sheet--${variant}`]"
    :style="{ '--sheet-width': width }"
    @click="onBackdropClick"
    @close="onClose"
  >
    <div class="ml-sheet__panel">
      <header v-if="title || $slots.header" class="ml-sheet__head">
        <slot name="header">
          <h2 class="ml-sheet__title">{{ title }}</h2>
        </slot>
        <button type="button" class="ml-sheet__close" :aria-label="t('common.close')" @click="close">
          ×
        </button>
      </header>
      <div class="ml-sheet__body">
        <slot />
      </div>
      <footer v-if="$slots.footer" class="ml-sheet__foot">
        <slot name="footer" />
      </footer>
    </div>
  </dialog>
</template>

<style scoped>
.ml-sheet {
  padding: 0;
  border: none;
  background: transparent;
  max-width: 100vw;
  max-height: 100vh;
  width: 100vw;
  height: 100vh;
  color: var(--ink);
}

.ml-sheet::backdrop {
  background: rgba(26, 24, 21, 0.38);
  backdrop-filter: blur(2px);
}

.ml-sheet__panel {
  background: var(--surface);
  box-shadow: var(--sheet-shadow);
  display: flex;
  flex-direction: column;
  max-height: 100%;
  overflow: hidden;
}

/* 抽屉：右侧滑出，宽度可配 */
.ml-sheet--drawer .ml-sheet__panel {
  margin-left: auto;
  width: var(--sheet-width);
  max-width: 92vw;
  height: 100%;
  border-radius: 0;
}

/* 居中弹层 */
.ml-sheet--modal .ml-sheet__panel {
  width: var(--sheet-width);
  max-width: 92vw;
  margin: 8vh auto;
  border-radius: var(--p-radius-lg);
  max-height: 84vh;
}

.ml-sheet__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-4);
  padding: var(--p-space-5) var(--p-space-5) var(--p-space-3);
  border-bottom: 1px solid var(--rule);
}

.ml-sheet__title {
  font-size: var(--p-step-1);
  font-weight: 600;
}

.ml-sheet__close {
  font-size: 1.5rem;
  line-height: 1;
  color: var(--ink-muted);
  padding: var(--p-space-1) var(--p-space-2);
  border-radius: var(--p-radius-md);
  min-width: 32px;
  min-height: 32px;
}

.ml-sheet__close:hover {
  color: var(--ink);
  background: var(--surface-hover);
}

.ml-sheet__body {
  padding: var(--p-space-5);
  overflow-y: auto;
  flex: 1;
}

.ml-sheet__foot {
  padding: var(--p-space-4) var(--p-space-5);
  border-top: 1px solid var(--rule);
  display: flex;
  justify-content: flex-end;
  gap: var(--p-space-2);
}
</style>
