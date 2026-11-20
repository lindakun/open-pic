/**
 * 最近浏览（REQ-V2-20 C-15）
 *
 * 存 localStorage，上限 50 条，只记录可展示的最小信息（id/标题/缩略图），
 * 不回查接口——本地历史的目的就是"零开销回看"。
 * 隐私模式等存储不可用环境下静默降级，不影响浏览。
 */
import { ref } from 'vue'

const STORAGE_KEY = 'medialib.recent'
const LIMIT = 50

export interface RecentEntry {
  id: string
  title: string
  kind: 'image' | 'video'
  ts: number
}

const recent = ref<RecentEntry[]>(read())

function safeGet(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function safeSet(value: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // 存储不可用：历史仅当前会话内存中保留
  }
}

function read(): RecentEntry[] {
  const raw = safeGet()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // 存储可能被旧版本或手工修改污染：逐项校验并裁剪，防止 NaN/undefined 进入渲染层
    return parsed
      .filter((e) => e && typeof e.id === 'string' && /^[0-9a-zA-Z_-]{4,64}$/.test(e.id))
      .map((e) => ({
        id: e.id,
        title: typeof e.title === 'string' ? e.title.slice(0, 200) : '',
        kind: e.kind === 'video' ? 'video' as const : 'image' as const,
        ts: Number.isFinite(e.ts) ? e.ts : Date.now(),
      }))
      .slice(0, LIMIT)
  } catch {
    return []
  }
}

/** 记录一次浏览（重复项提到最前，不产生重复条目） */
export function pushRecent(entry: Omit<RecentEntry, 'ts'>): void {
  const next: RecentEntry[] = [
    { ...entry, ts: Date.now() },
    ...recent.value.filter((e) => e.id !== entry.id),
  ].slice(0, LIMIT)
  recent.value = next
  safeSet(JSON.stringify(next))
}

export function removeRecent(id: string): void {
  const next = recent.value.filter((e) => e.id !== id)
  recent.value = next
  safeSet(JSON.stringify(next))
}

export function clearRecent(): void {
  recent.value = []
  safeSet('[]')
}

export function useRecent() {
  return { recent, pushRecent, removeRecent, clearRecent, LIMIT }
}
