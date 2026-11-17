/**
 * 埋点（REQ-V2-20 D-18）
 *
 * 三条硬约束：
 *   1. **合并上报**：单次交互产生的埋点请求 ≤ 1——事件进队列，
 *      10 秒或累计 20 条flush一次，页面隐藏/卸载时立即 flush。
 *   2. **失败静默**：埋点永远不能影响业务，任何异常都不抛出、不提示。
 *   3. **曝光口径**：元素停留 ≥1 秒才计曝光（IntersectionObserver + 计时），
 *      避免快速滚过就刷出一堆无效曝光。
 */
import { onBeforeUnmount, onMounted, type Ref } from 'vue'

export type EventType =
  | 'impression' | 'view' | 'download' | 'like' | 'collect' | 'search' | 'share'

interface QueuedEvent {
  type: EventType
  item_id?: string
  ts: number
  page: string
  referrer: string
  device: string
  meta?: Record<string, unknown>
}

const FLUSH_INTERVAL_MS = 10_000
const FLUSH_THRESHOLD = 20
/** 曝光最短停留，低于此值不计（D-18 要求） */
const IMPRESSION_MIN_MS = 1000

const queue: QueuedEvent[] = []
let timer: number | null = null

/** 设备类别：只分三档，够用且不采集指纹信息 */
export function deviceClass(): string {
  if (typeof window === 'undefined') return 'unknown'
  const w = window.innerWidth
  if (w < 640) return 'mobile'
  if (w < 1024) return 'tablet'
  return 'desktop'
}

/** 来源分类：同源 referrer 折叠为 internal，避免把内链当外部来源统计 */
export function referrerClass(): string {
  if (typeof document === 'undefined') return 'direct'
  const ref = document.referrer
  if (!ref) return 'direct'
  try {
    const url = new URL(ref)
    return url.origin === window.location.origin ? 'internal' : url.host
  } catch {
    return 'unknown'
  }
}

function pageType(): string {
  if (typeof window === 'undefined') return ''
  const p = window.location.pathname
  if (p.includes('/review/')) return 'review'
  if (p.startsWith('/browse')) return 'browse'
  if (p.startsWith('/app')) return 'home'
  return p.replace(/^\/+/, '').split('/')[0] || 'root'
}

/** 立即上报队列（失败静默，不重试，避免堆积） */
export async function flushEvents(): Promise<void> {
  if (!queue.length) return
  const batch = queue.splice(0, queue.length)
  try {
    await fetch('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: batch }),
      // 页面卸载时用 keepalive 提高送达率
      keepalive: true,
    })
  } catch {
    // 静默：埋点丢失可接受，不能影响用户操作
  }
}

function schedule(): void {
  if (timer !== null) return
  timer = window.setTimeout(() => {
    timer = null
    void flushEvents()
  }, FLUSH_INTERVAL_MS)
}

/** 记录一个事件（进队列，不直接发请求） */
export function track(type: EventType, opts: {
  itemId?: string
  meta?: Record<string, unknown>
} = {}): void {
  if (typeof window === 'undefined') return
  queue.push({
    type,
    item_id: opts.itemId,
    ts: Date.now(),
    page: pageType(),
    referrer: referrerClass(),
    device: deviceClass(),
    meta: opts.meta,
  })
  if (queue.length >= FLUSH_THRESHOLD) {
    void flushEvents()
    return
  }
  schedule()
}

/**
 * 曝光追踪（D-18）：给每个元素挂 IntersectionObserver，
 * 进入视口后开始计时，累计可见 ≥1s 才计一次曝光，同一元素只计一次。
 */
export function useImpressionTracker(ids: Ref<string[]>) {
  let observer: IntersectionObserver | null = null
  const seen = new Set<string>()
  const timers = new Map<string, number>()

  function watchElement(el: Element): void {
    const id = (el as HTMLElement).dataset.itemId
    if (!id || seen.has(id)) return
    timers.set(id, window.setTimeout(() => {
      if (seen.has(id)) return
      seen.add(id)
      track('impression', { itemId: id })
    }, IMPRESSION_MIN_MS))
  }

  function unwatchElement(el: Element): void {
    const id = (el as HTMLElement).dataset.itemId
    if (!id || seen.has(id)) return
    const t = timers.get(id)
    if (t !== undefined) {
      window.clearTimeout(t)
      timers.delete(id)
    }
  }

  let mutation: MutationObserver | null = null

  function observeCards(): number {
    if (!observer) return 0
    const nodes = document.querySelectorAll('[data-item-id]')
    nodes.forEach((el) => observer!.observe(el))
    return nodes.length
  }

  onMounted(() => {
    if (typeof IntersectionObserver === 'undefined') return
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) watchElement(entry.target)
        else unwatchElement(entry.target)
      }
    }, { threshold: 0.5 })

    // 卡片是异步渲染的（首次挂载时 DOM 还是空的），
    // 只扫一次会漏掉全部曝光（实测踩到）。用 MutationObserver 增量补观测。
    observeCards()
    if (typeof MutationObserver !== 'undefined') {
      // 虚拟化列表滚动时每次卡片回收/挂载都会触发 mutation，
      // 不节流的话每次都全量 querySelectorAll（滚动性能实测劣化）。
      // 用 rAF 合并同一帧内的多次变更，每帧最多扫一遍。
      let scanPending = false
      mutation = new MutationObserver(() => {
        if (scanPending) return
        scanPending = true
        requestAnimationFrame(() => {
          scanPending = false
          observeCards()
        })
      })
      mutation.observe(document.body, { childList: true, subtree: true })
    }
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    mutation?.disconnect()
    for (const t of timers.values()) window.clearTimeout(t)
    timers.clear()
  })

  return { seen, ids }
}

/** 仅供调试/测试：立刻把队列发出去 */
export function __debugFlush(): Promise<void> {
  return flushEvents()
}

/** 页面隐藏或卸载时立即上报，减少事件丢失 */
export function useEventFlush(): void {
  function onHide(): void {
    // visibilitychange 在「变为隐藏」和「重新可见」都会触发，
    // 只在真正隐藏时上报，避免无谓请求
    if (document.visibilityState === 'hidden') void flushEvents()
  }
  onMounted(() => {
    window.addEventListener('visibilitychange', onHide)
    window.addEventListener('pagehide', onHide)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('visibilitychange', onHide)
    window.removeEventListener('pagehide', onHide)
    void flushEvents()
  })
}
