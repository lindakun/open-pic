/**
 * useToast —— 全局轻提示
 *
 * 单例状态，任意组件可调用 push 触发提示。
 * 自动消失时间可按 tone 调整，错误提示停留更久。
 */
import { readonly, ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
  tone: 'info' | 'success' | 'error'
}

const toasts = ref<ToastItem[]>([])
let nextId = 1

/** 按 tone 决定停留时长（ms） */
const DURATION: Record<ToastItem['tone'], number> = {
  info: 2600,
  success: 2600,
  error: 5000,
}

function dismiss(id: number) {
  const index = toasts.value.findIndex((t) => t.id === id)
  if (index !== -1) toasts.value.splice(index, 1)
}

function push(message: string, tone: ToastItem['tone'] = 'info') {
  const id = nextId++
  toasts.value.push({ id, message, tone })
  window.setTimeout(() => dismiss(id), DURATION[tone])
  return id
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    dismiss,
    info: (msg: string) => push(msg, 'info'),
    success: (msg: string) => push(msg, 'success'),
    error: (msg: string) => push(msg, 'error'),
  }
}
