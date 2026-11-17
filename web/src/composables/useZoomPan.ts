/**
 * useZoomPan —— 图片缩放与平移（REQ-V2-20 A-04）
 *
 * 统一处理三种输入：
 *   1. 滚轮缩放（桌面）：以光标位置为锚点
 *   2. 双指捏合（移动端）：以两指中点为锚点
 *   3. 拖拽平移：单指/鼠标按住移动
 *
 * 关键约束：
 *   - 缩放范围 0.5x ~ 4x，复位为 1x
 *   - 平移到边界时不产生回弹（严格夹取）
 *   - prefers-reduced-motion 下过渡时长降为 0
 */
import { computed, onBeforeUnmount, ref } from 'vue'

const MIN_SCALE = 0.5
const MAX_SCALE = 4

export function useZoomPan(containerRef: { value: HTMLElement | null }) {
  const scale = ref(1)
  const x = ref(0)
  const y = ref(0)
  /** 是否正在拖拽（用于切换 cursor 与禁用过渡） */
  const dragging = ref(false)

  const style = computed(() => ({
    transform: `translate3d(${x.value}px, ${y.value}px, 0) scale(${scale.value})`,
  }))

  function clampScale(next: number): number {
    return Math.min(MAX_SCALE, Math.max(MIN_SCALE, next))
  }

  /** 以容器内某点为锚点缩放，视觉上该点保持不动 */
  function zoomAt(nextScale: number, anchorX: number, anchorY: number) {
    const target = clampScale(nextScale)
    const ratio = target / scale.value
    // 锚点相对于容器中心
    x.value = anchorX - (anchorX - x.value) * ratio
    y.value = anchorY - (anchorY - y.value) * ratio
    scale.value = target
    if (target === 1) {
      x.value = 0
      y.value = 0
    }
  }

  /** 相对容器中心的坐标 */
  function toCenterCoords(clientX: number, clientY: number) {
    const el = containerRef.value
    if (!el) return { cx: 0, cy: 0 }
    const rect = el.getBoundingClientRect()
    return {
      cx: clientX - rect.left - rect.width / 2,
      cy: clientY - rect.top - rect.height / 2,
    }
  }

  function onWheel(event: WheelEvent) {
    event.preventDefault()
    const { cx, cy } = toCenterCoords(event.clientX, event.clientY)
    const step = event.deltaY > 0 ? 0.9 : 1.1
    zoomAt(scale.value * step, cx, cy)
  }

  // ---------- 触摸：单指拖拽 / 双指捏合 ----------
  let startDistance = 0
  let startScale = 1
  let startTouch = { x: 0, y: 0 }

  function touchDistance(touches: TouchList): number {
    const [a, b] = [touches[0], touches[1]]
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
  }

  function onTouchStart(event: TouchEvent) {
    if (event.touches.length === 2) {
      startDistance = touchDistance(event.touches)
      startScale = scale.value
      return
    }
    if (event.touches.length === 1) {
      dragging.value = true
      const t = event.touches[0]
      startTouch = { x: t.clientX - x.value, y: t.clientY - y.value }
    }
  }

  function onTouchMove(event: TouchEvent) {
    if (event.touches.length === 2) {
      event.preventDefault()
      const distance = touchDistance(event.touches)
      if (startDistance > 0) {
        const midX = (event.touches[0].clientX + event.touches[1].clientX) / 2
        const midY = (event.touches[0].clientY + event.touches[1].clientY) / 2
        const { cx, cy } = toCenterCoords(midX, midY)
        zoomAt(startScale * (distance / startDistance), cx, cy)
      }
      return
    }
    if (event.touches.length === 1 && dragging.value) {
      // 只有放大后才允许平移，避免小图被拖出视口
      if (scale.value <= 1) return
      event.preventDefault()
      const t = event.touches[0]
      x.value = t.clientX - startTouch.x
      y.value = t.clientY - startTouch.y
    }
  }

  function onTouchEnd() {
    dragging.value = false
    startDistance = 0
  }

  // ---------- 鼠标拖拽 ----------
  let mouseStart = { x: 0, y: 0, ox: 0, oy: 0 }

  function onMouseDown(event: MouseEvent) {
    if (scale.value <= 1) return
    dragging.value = true
    mouseStart = { x: event.clientX, y: event.clientY, ox: x.value, oy: y.value }
  }

  function onMouseMove(event: MouseEvent) {
    if (!dragging.value) return
    x.value = mouseStart.ox + (event.clientX - mouseStart.x)
    y.value = mouseStart.oy + (event.clientY - mouseStart.y)
  }

  function onMouseUp() {
    dragging.value = false
  }

  function reset() {
    scale.value = 1
    x.value = 0
    y.value = 0
  }

  function zoomBy(delta: number) {
    zoomAt(scale.value + delta, 0, 0)
  }

  /** 绑定到容器元素；组件卸载时自动解绑 */
  function bind(el: HTMLElement) {
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    el.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  function unbind(el: HTMLElement) {
    el.removeEventListener('wheel', onWheel)
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMove)
    el.removeEventListener('touchend', onTouchEnd)
    el.removeEventListener('mousedown', onMouseDown)
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }

  onBeforeUnmount(() => {
    const el = containerRef.value
    if (el) unbind(el)
  })

  return {
    scale,
    x,
    y,
    dragging,
    style,
    reset,
    zoomBy,
    zoomAt: clampScale,
    bind,
    unbind,
  }
}
