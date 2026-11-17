/**
 * 共享元素转场（REQ-V2-20 A-03）
 *
 * 用 View Transitions API 把卡片位置/尺寸连续插值到灯箱，
 * 不支持时静默降级为原来的即时切换（功能不降级，只是少了动画）。
 *
 * 关键约束：
 *   1. prefers-reduced-motion: reduce 时直接执行，不启动转场
 *   2. 转场期间不允许并发调用，避免 startViewTransition 抛错
 *   3. 不改变调用方状态，只负责"包一层" DOM 更新
 */
import { readonly, ref } from 'vue'

/** 当前是否有转场在进行 */
const inFlight = ref(false)

/**
 * 是否支持 View Transitions。
 *
 * 用函数而非模块级常量：一是便于测试注入，
 * 二是避免在不具备 API 的环境里长期持有错误的判定。
 */
function isSupported(): boolean {
  return typeof document !== 'undefined' && 'startViewTransition' in document
}

/** 是否应当禁动画（系统减弱动效） */
function shouldReduceMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  )
}

/**
 * 在转场中执行 DOM 更新。
 *
 * @param update 真正改变 DOM 状态的函数（如打开灯箱）
 */
export async function withViewTransition(update: () => void): Promise<void> {
  // 不支持或需减弱动效：直接执行
  if (!isSupported() || shouldReduceMotion()) {
    update()
    return
  }

  // 已有转场在跑：跳过动画直接执行，避免并发报错
  if (inFlight.value) {
    update()
    return
  }

  inFlight.value = true
  let done = false
  try {
    const transition = (
      document as Document & {
        startViewTransition: (cb: () => void) => {
          finished: Promise<void>
          updateCallbackDone: Promise<void>
        }
      }
    ).startViewTransition(() => {
      update()
      done = true
    })
    // 只等待"更新已应用"，不等动画播完：
    // 灯箱是 <dialog> 顶层元素，与共享元素动画的时序经常冲突，
    // 等待 finished 会在动画被中止时抛出无意义的错误。
    await transition.updateCallbackDone
  } catch {
    // 转场失败不应阻塞交互；若回调尚未执行，补一次确保状态生效
    if (!done) update()
  } finally {
    inFlight.value = false
  }
}

export function useViewTransition() {
  return {
    isSupported,
    inFlight: readonly(inFlight),
    run: withViewTransition,
  }
}
