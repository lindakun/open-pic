/**
 * AI 检索能力探测（REQ-V2-20 B-08 验收 4）
 *
 * 约定：未配置 provider 时后端返回 available=false（而非报错），
 * 前端据此隐藏「以图搜图」入口并给出说明，全程不出现错误提示。
 *
 * 探测结果缓存到模块级，同一会话内不重复请求。
 */
import { ref } from 'vue'

export interface AiStatus {
  provider: string
  available: boolean
  model_version: string
  embedded: number
  pending: number
  hint: string
}

const status = ref<AiStatus | null>(null)
let inflight: Promise<AiStatus | null> | null = null

export function useAiStatus() {
  /** 拉取一次状态（失败时视为不可用，不抛错） */
  async function load(force = false): Promise<AiStatus | null> {
    if (!force && status.value) return status.value
    if (inflight) return inflight
    inflight = (async () => {
      try {
        const res = await fetch('/api/ai/status')
        if (!res.ok) {
          status.value = null
          return null
        }
        status.value = (await res.json()) as AiStatus
        return status.value
      } catch {
        // 网络异常同样视为不可用：入口隐藏优于报错
        status.value = null
        return null
      } finally {
        inflight = null
      }
    })()
    return inflight
  }

  return { status, load }
}
