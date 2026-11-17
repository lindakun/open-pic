/**
 * 国际化（REQ-V2-20 E-20）
 *
 * 设计取舍：
 *   - 不引入 vue-i18n（包体积 ~20KB），自建轻量实现即可满足本项目的文案规模
 *   - 支持 {name} 占位符与简单复数（zh 无量词变化，en 需区分单复数）
 *   - 语言持久化到 localStorage，并同步 <html lang>
 *   - 日期/数字/体积统一走 Intl，不手工拼字符串
 */
import { computed, ref } from 'vue'

export type Locale = 'zh-CN' | 'en-US'

const STORAGE_KEY = 'medialib.locale'

/** 文案字典：扁平 key，便于查漏 */
type Dict = Record<string, string>

const messages: Record<Locale, Dict> = {
  'zh-CN': {
    // 站点
    'site.name': 'MediaLib',
    'site.browse': '浏览',
    'site.admin': '管理',
    'site.skipToMain': '跳到主要内容',
    'site.toggleTheme': '切换主题',
    'site.themeLight': '浅色主题（点击切换）',
    'site.themeDark': '深色主题（点击切换）',
    'site.themeAuto': '跟随系统主题（点击切换）',
    'site.home': '首页',
    'site.search': '搜索',
    'site.total': '{count} 项',
    'site.loading': '载入中…',

    // 首页
    'home.eyebrow': 'Visual Asset Library',
    'home.title': '把每一次看见，都收进库里。',
    'home.lede': '一个为商业使用而建的视觉资产库——可检索、可策展、可交付。',
    'home.enterAll': '进入全部资产',
    'home.viewAll': '查看全部',
    'home.featured': '编辑精选',
    'home.recent': '最近上新',
    'home.empty': '库还是空的。上传第一张图片，或通过链接抓取。',
    'home.notEnough': '内容还不够铺满这一栏，继续添加吧。',
    'home.browseAll': '浏览全部',

    // 浏览页
    'browse.searchPlaceholder': '搜索标题、标签、来源…',
    'browse.searchLabel': '搜索媒体库',
    'browse.filter': '筛选',
    'browse.clearAll': '清空全部',
    'browse.clearFilter': '清空筛选',
    'browse.emptyTitle': '没有匹配的内容',
    'browse.emptyHint': '试试放宽筛选条件，或清空全部筛选。',
    'browse.emptyHintNoFilter': '上传图片或通过链接抓取，开始构建你的视觉资产库。',
    'browse.loadMore': '加载更多',
    'browse.activeFilters': '已选筛选条件',
    'browse.removeFilter': '移除筛选',
    'browse.keyword': '关键词：{value}',

    // 排序
    'sort.newest': '最新',
    'sort.oldest': '最早',
    'sort.pixels': '分辨率',
    'sort.size': '体积',
    'sort.views': '热度',
    'sort.label': '排序方式',

    // 分面
    'facet.title': '筛选',
    'facet.clear': '清空',
    'facet.counting': '统计中…',
    'facet.kind': '类型',
    'facet.orientation': '方向',
    'facet.sizeClass': '分辨率',
    'facet.ext': '格式',
    'facet.platform': '来源',
    'facet.tag': '标签',
    'facet.kindImage': '图片',
    'facet.kindVideo': '视频',
    'facet.landscape': '横图',
    'facet.portrait': '竖图',
    'facet.square': '方图',
    'facet.size4k': '4K+',
    'facet.sizeHd': '高清 1080',
    'facet.sizeSd': '标清 720',
    'facet.sizeSmall': '小图',
    'facet.platformLocal': '本地上传',

    // 灯箱
    'lightbox.prev': '上一张',
    'lightbox.next': '下一张',
    'lightbox.download': '下载原图',
    'lightbox.close': '关闭',
    'lightbox.preview': '媒体预览',
    'lightbox.video': '视频',
    'license.personalOnly': '仅限个人使用',
    'license.commercial': '可商用',

    // Toast
    'toast.close': '关闭提示',

    // 通用
    'common.close': '关闭',
    'common.cancel': '取消',
    'common.confirm': '确定',
  },

  'en-US': {
    'site.name': 'MediaLib',
    'site.browse': 'Browse',
    'site.admin': 'Admin',
    'site.skipToMain': 'Skip to main content',
    'site.toggleTheme': 'Toggle theme',
    'site.themeLight': 'Light theme (click to change)',
    'site.themeDark': 'Dark theme (click to change)',
    'site.themeAuto': 'Follow system theme (click to change)',
    'site.home': 'Home',
    'site.search': 'Search',
    // 英文需区分单复数；{count} 项统一用 one/other
    'site.total': '{count} item | {count} items',
    'site.loading': 'Loading…',

    'home.eyebrow': 'Visual Asset Library',
    'home.title': 'Every sight you see, kept in your library.',
    'home.lede':
      'A visual asset library built for commercial work — searchable, curatable, deliverable.',
    'home.enterAll': 'Enter all assets',
    'home.viewAll': 'View all',
    'home.featured': "Editor's Picks",
    'home.recent': 'Recently Added',
    'home.empty': 'The library is empty. Upload your first image or fetch from a link.',
    'home.notEnough': 'Not enough content to fill this row yet — keep adding.',
    'home.browseAll': 'Browse all',

    'browse.searchPlaceholder': 'Search titles, tags, sources…',
    'browse.searchLabel': 'Search media library',
    'browse.filter': 'Filters',
    'browse.clearAll': 'Clear all',
    'browse.clearFilter': 'Clear filters',
    'browse.emptyTitle': 'No matching content',
    'browse.emptyHint': 'Try loosening the filters, or clear them all.',
    'browse.emptyHintNoFilter':
      'Upload images or fetch from a link to start building your library.',
    'browse.loadMore': 'Load more',
    'browse.activeFilters': 'Active filters',
    'browse.removeFilter': 'Remove filter',
    'browse.keyword': 'Keyword: {value}',

    'sort.newest': 'Newest',
    'sort.oldest': 'Oldest',
    'sort.pixels': 'Resolution',
    'sort.size': 'Size',
    'sort.views': 'Popular',
    'sort.label': 'Sort by',

    'facet.title': 'Filters',
    'facet.clear': 'Clear',
    'facet.counting': 'Counting…',
    'facet.kind': 'Type',
    'facet.orientation': 'Orientation',
    'facet.sizeClass': 'Resolution',
    'facet.ext': 'Format',
    'facet.platform': 'Source',
    'facet.tag': 'Tags',
    'facet.kindImage': 'Image',
    'facet.kindVideo': 'Video',
    'facet.landscape': 'Landscape',
    'facet.portrait': 'Portrait',
    'facet.square': 'Square',
    'facet.size4k': '4K+',
    'facet.sizeHd': 'HD 1080',
    'facet.sizeSd': '720',
    'facet.sizeSmall': 'Small',
    'facet.platformLocal': 'Local upload',

    'lightbox.prev': 'Previous',
    'lightbox.next': 'Next',
    'lightbox.download': 'Download original',
    'lightbox.close': 'Close',
    'lightbox.preview': 'Media preview',
    'lightbox.video': 'Video',
    'license.personalOnly': 'Personal use only',
    'license.commercial': 'Commercial use',

    'toast.close': 'Dismiss notification',

    'common.close': 'Close',
    'common.cancel': 'Cancel',
    'common.confirm': 'Confirm',
  },
}

/** 英文复数所需的最小规则：只区分 one / other */
function pickPlural(template: string, count: number): string {
  const forms = template.split('|')
  if (forms.length === 1) return template
  // 模板写作 "one | other" 时两侧留空格便于阅读，选形后需去掉
  return (count === 1 ? forms[0] : forms[1]).trim()
}

/**
 * 安全读取 localStorage。
 * 某些环境（隐私模式、非浏览器上下文、测试环境）不可用，
 * 此时静默回退到默认语言，不影响功能。
 */
function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 存储不可用时忽略：语言仅当前会话生效
  }
}

function readStoredLocale(): Locale {
  const v = safeGet(STORAGE_KEY)
  return v === 'en-US' || v === 'zh-CN' ? v : 'zh-CN'
}

const locale = ref<Locale>(readStoredLocale())

/** 同步 <html lang>，屏幕阅读器据此选择发音 */
function applyLang() {
  document.documentElement.lang = locale.value
}

applyLang()

const dict = computed(() => messages[locale.value])

/**
 * 翻译函数。
 * @param key 文案 key
 * @param params 占位符参数；含 count 时按单复数选形
 */
function t(key: string, params?: Record<string, string | number>): string {
  let text = dict.value[key] ?? messages['zh-CN'][key] ?? key

  // 复数：{count} 存在时先选形
  if (params && typeof params.count === 'number') {
    text = pickPlural(text, params.count)
  }

  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v))
    }
  }
  return text
}

/** 按 locale 格式化日期 */
function formatDate(ts: number): string {
  return new Intl.DateTimeFormat(locale.value, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(ts * 1000))
}

/** 按 locale 格式化文件体积 */
function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  const formatted = new Intl.NumberFormat(locale.value, {
    maximumFractionDigits: i === 0 ? 0 : 2,
  }).format(value)
  return `${formatted} ${units[i]}`
}

/** 按 locale 格式化数字 */
function formatNumber(n: number): string {
  return new Intl.NumberFormat(locale.value).format(n)
}

export function useI18n() {
  return {
    locale,
    t,
    formatDate,
    formatBytes,
    formatNumber,
    setLocale(next: Locale) {
      locale.value = next
      safeSet(STORAGE_KEY, next)
      applyLang()
    },
    toggleLocale() {
      const next: Locale = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
      locale.value = next
      safeSet(STORAGE_KEY, next)
      applyLang()
    },
  }
}
