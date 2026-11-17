/**
 * useClipboard —— 复制到剪贴板（REQ-V2-20 A-04）
 *
 * 设计取舍：
 *   - 内网 HTTP 环境下 navigator.clipboard 可能不可用（非安全上下文），
 *     因此保留 document.execCommand('copy') 降级路径，保证功能不降级。
 *   - 复制结果由调用方展示反馈，本模块只返回成功与否。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 继续走降级路径
  }

  try {
    const ta = document.createElement('textarea')
    ta.value = text
    // 移到视口外，避免复制瞬间页面跳动
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-1000px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
