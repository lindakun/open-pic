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
  duration: number
}

const toasts = ref<ToastItem[]>([])
let nextId = 1
const timers = new Map<number, { handle: number; remaining: number; startedAt: number }>()

/** 按 tone 决定停留时长（ms） */
const DURATION: Record<ToastItem['tone'], number> = {
  info: 2600,
  success: 2600,
  error: 5000,
}

function dismiss(id: number) {
  const entry = timers.get(id)
  if (entry) {
    window.clearTimeout(entry.handle)
    timers.delete(id)
  }
  const index = toasts.value.findIndex((t) => t.id === id)
  if (index !== -1) toasts.value.splice(index, 1)
}

function scheduleTimer(id: number, ms: number) {
  const handle = window.setTimeout(() => dismiss(id), ms)
  timers.set(id, { handle, remaining: ms, startedAt: Date.now() })
}

function pause(id: number) {
  const entry = timers.get(id)
  if (!entry) return
  window.clearTimeout(entry.handle)
  const elapsed = Date.now() - entry.startedAt
  timers.set(id, {
    handle: -1,
    remaining: Math.max(400, entry.remaining - elapsed),
    startedAt: entry.startedAt,
  })
}

function resume(id: number) {
  const entry = timers.get(id)
  if (!entry || entry.handle !== -1) return
  scheduleTimer(id, entry.remaining)
}

function push(message: string, tone: ToastItem['tone'] = 'info') {
  const id = nextId++
  const duration = DURATION[tone]
  toasts.value.push({ id, message, tone, duration })
  scheduleTimer(id, duration)
  return id
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    dismiss,
    pause,
    resume,
    info: (msg: string) => push(msg, 'info'),
    success: (msg: string) => push(msg, 'success'),
    error: (msg: string) => push(msg, 'error'),
  }
}
