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
    'lightbox.compare': '对比',
    'lightbox.comparePick': '加入对比',
    'lightbox.compareClear': '退出对比',
    'lightbox.info': '详细信息',
    'lightbox.spec': '规格',
    'lightbox.author': '作者',
    'lightbox.added': '入库时间',
    'lightbox.source': '来源',
    'lightbox.license': '授权',
    'lightbox.palette': '主色板',
    'lightbox.copyColor': '复制色值',
    'lightbox.copied': '已复制',
    'lightbox.copiedToast': '已复制到剪贴板',
    'lightbox.filterColor': '按此色筛选',
    'lightbox.copyLink': '复制直链',
    'lightbox.slideshowToggle': '连播开关',
    'lightbox.slideshowInterval': '连播间隔',
    'lightbox.help': '快捷键',
    'exif.make': '品牌',
    'exif.model': '机型',
    'exif.taken': '拍摄时间',
    'exif.aperture': '光圈',
    'exif.shutter': '快门',
    'exif.iso': 'ISO',
    'exif.focal': '焦距',
    'shortcut.switch': '切换上一张 / 下一张',
    'shortcut.zoom': '放大 / 缩小',
    'shortcut.reset': '复位缩放',
    'shortcut.info': '显示 / 隐藏信息面板',
    'shortcut.download': '下载原图',
    'shortcut.copy': '复制直链',
    'shortcut.slideshow': '连播开关（图片）',
    'shortcut.close': '关闭灯箱',
    'shortcut.help': '打开本帮助',
    'license.personalOnly': '仅限个人使用',
    'license.commercial': '可商用',

    // Toast
    'toast.close': '关闭提示',

    // 通用
    'common.close': '关闭',
    'common.cancel': '取消',
    'review.title': '选片与批注',
    'review.hint': '←/→ 切换 · 1 选中 · 2 待定 · 3 否决',
    'review.reviewer': '你的名字',
    'review.reviewerPlaceholder': '选填，便于库主识别',
    'review.selected': '选中',
    'review.pending': '待定',
    'review.rejected': '否决',
    'review.unmarked': '未标记',
    'review.note': '批注',
    'review.notePlaceholder': '写下你的意见，例如「这张用作封面」',
    'review.saveNote': '保存批注',
    'review.saving': '保存中…',
    'review.saved': '已保存',
    'review.filmstrip': '全部候选',
    'review.empty': '这个选片集还没有素材',
    'review.invalid': '选片链接无效或已失效',
    'review.loadFailed': '加载失败，请稍后重试',
    'review.saveFailed': '保存失败，已回滚',
    'ai.disabled': 'AI 检索未启用',
    'ai.byImage': '以图搜图',
    'ai.byImageHint': '把图片拖进来，或直接粘贴（Ctrl/⌘+V）',
    'ai.dropHint': '松手搜索相似图片',
    'ai.searchFailed': '搜图失败，请稍后重试',
    // 上传与批量（REQ-05）
    'upload.open': '上传',
    'upload.title': '添加素材',
    'upload.tabFile': '上传文件',
    'upload.tabUrl': '链接采集',
    'upload.dropHint': '拖入文件，或点击选择',
    'upload.dropSub': '支持图片与视频；也可直接粘贴（Ctrl/⌘+V）',
    'upload.onlyMedia': '只能上传图片或视频文件',
    'upload.remove': '移除',
    'upload.fieldTitle': '标题（可选）',
    'upload.titlePlaceholder': '留空则用文件名',
    'upload.fieldTags': '标签（可选）',
    'upload.tagsPlaceholder': '用逗号或空格分隔，如：城市 夜景',
    'upload.submit': '上传 {count} 个文件',
    'upload.uploading': '上传中…',
    'upload.done': '已入库 {count} 项',
    'upload.urlLabel': '素材链接',
    'upload.urlHint': '支持直链图片/视频与常见平台页面，由后台队列抓取',
    'upload.badUrl': '请输入以 http:// 或 https:// 开头的链接',
    'upload.submitUrl': '提交采集',
    'upload.queueing': '提交中…',
    'upload.queued': '已加入采集队列，完成后可在列表查看',
    'batch.select': '选择',
    'batch.exitSelect': '退出选择',
    'batch.bar': '批量操作',
    'batch.selected': '已选 {count} 项',
    'batch.tags': '打标签',
    'batch.collection': '加入画板',
    'batch.export': '导出',
    'batch.trash': '移入回收站',
    'batch.clear': '清空选择',
    'batch.done': '已完成 {count} 项',
    'batch.tagsTitle': '批量打标签',
    'batch.tagsHint': '将追加到已选的 {count} 项，不会覆盖原有标签',
    'batch.collectionTitle': '加入画板',
    'batch.collectionPick': '选择画板',
    'batch.featuredSet': '设为精选',
    'batch.featured': '已把 {count} 项设为首页精选',
    'batch.featuredFailed': '设置精选失败',
    'batch.exported': '导出包已开始下载',
    'batch.exportQueued': '{count} 项较大，已转后台打包，可在任务中心下载',
    'like.onlyLiked': '只看喜欢',
    'like.showAll': '显示全部',
    'like.empty': '还没有喜欢的素材',
    'like.failed': '操作失败，已回滚',
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
    'lightbox.compare': 'Compare',
    'lightbox.comparePick': 'Add to compare',
    'lightbox.compareClear': 'Exit compare',
    'lightbox.info': 'Details',
    'lightbox.spec': 'Spec',
    'lightbox.author': 'Author',
    'lightbox.added': 'Added',
    'lightbox.source': 'Source',
    'lightbox.license': 'License',
    'lightbox.palette': 'Palette',
    'lightbox.copyColor': 'Copy color',
    'lightbox.copied': 'Copied',
    'lightbox.copiedToast': 'Copied to clipboard',
    'lightbox.filterColor': 'Filter by this color',
    'lightbox.copyLink': 'Copy direct link',
    'lightbox.slideshowToggle': 'Toggle slideshow',
    'lightbox.slideshowInterval': 'Slideshow interval',
    'lightbox.help': 'Keyboard shortcuts',
    'exif.make': 'Make',
    'exif.model': 'Model',
    'exif.taken': 'Taken',
    'exif.aperture': 'Aperture',
    'exif.shutter': 'Shutter',
    'exif.iso': 'ISO',
    'exif.focal': 'Focal length',
    'shortcut.switch': 'Previous / next item',
    'shortcut.zoom': 'Zoom in / out',
    'shortcut.reset': 'Reset zoom',
    'shortcut.info': 'Toggle details panel',
    'shortcut.download': 'Download original',
    'shortcut.copy': 'Copy direct link',
    'shortcut.slideshow': 'Toggle slideshow (images)',
    'shortcut.close': 'Close lightbox',
    'shortcut.help': 'Open this help',
    'license.personalOnly': 'Personal use only',
    'license.commercial': 'Commercial use',

    'toast.close': 'Dismiss notification',

    'common.close': 'Close',
    'common.cancel': 'Cancel',
    'review.title': 'Review & Comment',
    'review.hint': '←/→ switch · 1 select · 2 maybe · 3 reject',
    'review.reviewer': 'Your name',
    'review.reviewerPlaceholder': 'Optional, helps the owner identify you',
    'review.selected': 'Selected',
    'review.pending': 'Maybe',
    'review.rejected': 'Rejected',
    'review.unmarked': 'Unmarked',
    'review.note': 'Comment',
    'review.notePlaceholder': 'Share your thoughts, e.g. "use this as the cover"',
    'review.saveNote': 'Save comment',
    'review.saving': 'Saving…',
    'review.saved': 'Saved',
    'review.filmstrip': 'All candidates',
    'review.empty': 'This review set has no assets yet',
    'review.invalid': 'This review link is invalid or expired',
    'review.loadFailed': 'Failed to load, please retry',
    'review.saveFailed': 'Save failed, changes reverted',
    'ai.disabled': 'AI search off',
    'ai.byImage': 'Search by image',
    'ai.byImageHint': 'Drag an image here, or paste it (Ctrl/⌘+V)',
    'ai.dropHint': 'Drop to search similar images',
    'ai.searchFailed': 'Image search failed, please retry',
    // Upload & batch (REQ-05)
    'upload.open': 'Upload',
    'upload.title': 'Add assets',
    'upload.tabFile': 'Upload files',
    'upload.tabUrl': 'Fetch from URL',
    'upload.dropHint': 'Drop files here, or click to choose',
    'upload.dropSub': 'Images and videos; you can also paste (Ctrl/⌘+V)',
    'upload.onlyMedia': 'Only image or video files are supported',
    'upload.remove': 'Remove',
    'upload.fieldTitle': 'Title (optional)',
    'upload.titlePlaceholder': 'Falls back to the file name',
    'upload.fieldTags': 'Tags (optional)',
    'upload.tagsPlaceholder': 'Comma or space separated, e.g. city night',
    'upload.submit': 'Upload {count} file | Upload {count} files',
    'upload.uploading': 'Uploading…',
    'upload.done': '{count} item added | {count} items added',
    'upload.urlLabel': 'Asset URL',
    'upload.urlHint': 'Direct image/video links and common platform pages; fetched in background',
    'upload.badUrl': 'Enter a link starting with http:// or https://',
    'upload.submitUrl': 'Fetch',
    'upload.queueing': 'Submitting…',
    'upload.queued': 'Queued for fetching; it will appear in the list when done',
    'batch.select': 'Select',
    'batch.exitSelect': 'Exit select',
    'batch.bar': 'Batch actions',
    'batch.selected': '{count} selected',
    'batch.tags': 'Tag',
    'batch.collection': 'Add to board',
    'batch.export': 'Export',
    'batch.trash': 'Move to trash',
    'batch.clear': 'Clear selection',
    'batch.done': '{count} item updated | {count} items updated',
    'batch.tagsTitle': 'Batch tag',
    'batch.tagsHint': 'Appended to the {count} selected items; existing tags are kept',
    'batch.collectionTitle': 'Add to board',
    'batch.collectionPick': 'Pick a board',
    'batch.featuredSet': 'Feature',
    'batch.featured': '{count} item featured on the home page | {count} items featured on the home page',
    'batch.featuredFailed': 'Failed to set featured',
    'batch.exported': 'Download started',
    'batch.exportQueued': '{count} items are large; packing in background, download from Jobs',
    'like.onlyLiked': 'Liked only',
    'like.showAll': 'Show all',
    'like.empty': 'No liked assets yet',
    'like.failed': 'Action failed, reverted',
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
