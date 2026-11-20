/** 后处理流水线写入的内部状态标签：只用于防重复处理，不面向用户展示或点选 */
export const INTERNAL_TAGS = new Set(['AI已标注'])

export function userTags(tags?: readonly string[] | null): string[] {
  return (tags ?? []).filter((tag) => tag && !INTERNAL_TAGS.has(tag))
}
