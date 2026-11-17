/**
 * 滚动位置恢复（REQ-V2-20 D-17）
 *
 * 关键取舍：**按锚点恢复而非像素**。
 * 纯像素恢复在列数变化（1440→768 时 5 列变 3 列）后会落到别的位置；
 * 记录「首个可视卡片 id + 其内偏移比例」则始终回到同一资产。
 *
 * 存储位置：`history.state`，不进 URL——滚动位置属于会话状态，
 * 写进 query string 会污染分享链接（B-10 审核意见）。
 */
import type { MediaItem } from '@/api/types'

export interface ScrollAnchor {
  /** 首个可见卡片的 id */
  itemId: string
  /** 该卡片顶部到视口顶部的距离占比（0–1），用于同列宽下的精细还原 */
  ratio: number
}

const STATE_KEY = 'mlibScrollAnchor'

interface HistoryStateWithAnchor {
  [STATE_KEY]?: ScrollAnchor
}

/** 写入锚点到 history.state（replaceState，不产生历史记录） */
export function saveScrollAnchor(anchor: ScrollAnchor): void {
  try {
    const current = (history.state ?? {}) as HistoryStateWithAnchor
    history.replaceState({ ...current, [STATE_KEY]: anchor }, '')
  } catch {
    // 隐私模式或沙箱内不可用：静默降级，不影响浏览
  }
}

/** 读取锚点 */
export function readScrollAnchor(): ScrollAnchor | null {
  try {
    const state = (history.state ?? {}) as HistoryStateWithAnchor
    return state[STATE_KEY] ?? null
  } catch {
    return null
  }
}

/**
 * 从当前 DOM 采样锚点。
 *
 * 用 `[data-item-id]` 而非索引：列表顺序可能因筛选变化，
 * id 是唯一稳定的标识。
 */
export function sampleAnchor(root: ParentNode = document): ScrollAnchor | null {
  const nodes = root.querySelectorAll<HTMLElement>('[data-item-id]')
  // 取「第一个顶部已进入视口」的卡片：它就是用户当前阅读的起点。
  // 用 top >= 0 而非 bottom > 0，否则会取到大部分已经滚出视口的上一张，
  // 恢复时会停在上一张而非用户看到的这一张（实测偏差约 440px）。
  let fallback: ScrollAnchor | null = null
  for (const el of nodes) {
    const rect = el.getBoundingClientRect()
    if (rect.bottom <= 0) continue // 完全在视口上方
    if (rect.height <= 0) continue
    const ratio = Math.min(1, Math.max(0, -rect.top / rect.height))
    const id = el.dataset.itemId
    if (!id) continue
    if (rect.top >= 0) return { itemId: id, ratio }
    // 视口内没有卡片从顶部开始时（大图占满），退回最接近顶部的一张
    if (!fallback) fallback = { itemId: id, ratio }
  }
  return fallback
}

/**
 * 把列表还原到锚点位置。
 *
 * 实现要点：
 *   - 先确认锚点资产在已加载列表内；不在则放弃（避免滚到错误位置）
 *   - 用 `scrollIntoView` 的 `start` 对齐后再按 ratio 微调，
 *     列数变化时也能停在同一资产上
 *   - 全流程在 `requestAnimationFrame` 内完成，等布局稳定再滚
 */
export function restoreScrollAnchor(
  anchor: ScrollAnchor | null,
  items: MediaItem[],
): boolean {
  if (!anchor) return false
  if (!items.some((i) => i.id === anchor.itemId)) return false

  // 双帧：等 dialog 关闭解除 body 滚动锁、且瀑布流完成一次布局后再测坐标，
  // 单帧时 rect 仍带着滚动锁的影响（实测偏 20px 左右）。
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      // CSS.escape 在部分环境（jsdom、旧浏览器）缺失，降级为属性选择器转义
      const escaped = escapeAttrValue(anchor.itemId)
      const el = document.querySelector<HTMLElement>(`[data-item-id="${escaped}"]`)
      if (!el) return
      const rect = el.getBoundingClientRect()
      const targetTop = rect.top + window.scrollY - rect.height * anchor.ratio
      window.scrollTo({ top: Math.max(0, targetTop), behavior: 'auto' })
    })
  })
  return true
}

/**
 * 转义属性选择器中的值。
 * 资产 id 是 `[0-9a-f]{16}`，本身安全；但锚点也用于任意数据，
 * 这里统一转义双引号与反斜杠，避免选择器语法错误。
 */
function escapeAttrValue(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
    return CSS.escape(value)
  }
  return value.replace(/["\\]/g, '\\$&')
}

/** 清除锚点（例如用户主动切换筛选时） */
export function clearScrollAnchor(): void {
  try {
    const current = (history.state ?? {}) as HistoryStateWithAnchor
    if (STATE_KEY in current) {
      const next = { ...current }
      delete next[STATE_KEY]
      history.replaceState(next, '')
    }
  } catch {
    // 忽略
  }
}

/** 是否处于省流量/弱网环境（D-17：批量降为 24） */
export function isSaveData(): boolean {
  try {
    const conn = (navigator as Navigator & {
      connection?: { saveData?: boolean; effectiveType?: string }
    }).connection
    if (!conn) return false
    if (conn.saveData) return true
    return conn.effectiveType === 'slow-2g' || conn.effectiveType === '2g'
  } catch {
    return false
  }
}

/** 按网络状况决定分页大小：默认 48，弱网 24 */
export function pageSizeFor(normal = 48, reduced = 24): number {
  return isSaveData() ? reduced : normal
}
