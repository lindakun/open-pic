/**
 * useToast —— 全局轻提示
 *
 * 单例状态，任意组件可调用 push 触发提示。
 * 自动消失时间可按 tone 调整，错误提示停留更久。
 */
import { readonly, ref } from 'vue'

export interface ToastAction {
  label: string
  run: () => void
}

export interface ToastItem {
  id: number
  message: string
  tone: 'info' | 'success' | 'error'
  duration: number
  action?: ToastAction
}

export interface ToastOptions {
  /** 覆盖默认停留时长；带撤销类操作时通常需要更久 */
  duration?: number
  action?: ToastAction
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

function push(message: string, tone: ToastItem['tone'] = 'info', opts: ToastOptions = {}) {
  const id = nextId++
  const duration = opts.duration ?? DURATION[tone]
  toasts.value.push({ id, message, tone, duration, action: opts.action })
  scheduleTimer(id, duration)
  return id
}

/** 关闭提示并执行其快捷操作（如撤销批量删除） */
function runAction(id: number) {
  const item = toasts.value.find((t) => t.id === id)
  if (!item?.action) return
  dismiss(id)
  item.action.run()
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    dismiss,
    pause,
    resume,
    runAction,
    info: (msg: string, opts?: ToastOptions) => push(msg, 'info', opts),
    success: (msg: string, opts?: ToastOptions) => push(msg, 'success', opts),
    error: (msg: string, opts?: ToastOptions) => push(msg, 'error', opts),
  }
}
