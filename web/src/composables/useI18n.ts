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
    'notfound.title': '页面不存在',
    'notfound.heading': '这个页面不在库里',
    'notfound.hint': '链接可能已失效，或资源已被移除。',
    'notfound.back': '回到首页',
    'site.browse': '浏览',
    'site.wall': '图墙',
    'site.admin': '管理',
    'site.skipToMain': '跳到主要内容',
    'site.toggleTheme': '切换主题',
    'site.switchToEn': '切换到英文',
    'site.switchToZh': '切换到中文',
    'site.themeLight': '浅色主题（点击切换）',
    'site.themeDark': '深色主题（点击切换）',
    'site.themeAuto': '跟随系统主题（点击切换）',
    'site.themeAutoShort': '跟随系统',
    'site.themeLightShort': '浅色',
    'site.themeDarkShort': '深色',
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
    'home.addFirst': '添加第一张素材',
    'home.notEnough': '内容还不够铺满这一栏，继续添加吧。',
    'home.browseAll': '浏览全部',
    'home.all': '全部',
    'home.images': '图片',
    'home.videos': '视频',
    'home.typeFilter': '按媒体类型筛选',
    'home.shuffle': '漫步',

    // 浏览页
    'browse.searchPlaceholder': '搜索标题、标签、来源…',
    'browse.searchLabel': '搜索媒体库',
    'browse.clearSearch': '清除搜索词',
    'browse.filter': '筛选',
    'browse.showResults': '查看 {count} 项',
    'browse.tapRangeHint': '点按卡片即可多选',
    'browse.clearAll': '清空全部',
    'browse.clearKeyword': '仅清除关键词',
    'browse.aiResultBanner': '当前为以图搜图相似结果（共 {count} 项）',
    'browse.exitAiSearch': '返回全部列表',
    'browse.copyFilterLink': '复制筛选链接',
    'browse.filterLinkCopied': '已复制当前筛选视图链接',
    'browse.likedLoadMoreHint': '仅显示已加载的 {loaded} 项中的喜欢素材，点击继续加载剩余 {remaining} 项',
    'browse.loadMoreToFindLikes': '继续加载更多',
    'browse.shiftRangeHint': '按住 Shift 点击可区间连选',
    'browse.selectionCleared': '筛选已更新，{count} 项已取消选择',
    'browse.clearFilter': '清空筛选',
    'browse.emptyTitle': '没有匹配的内容',
    'browse.errorTitle': '内容加载失败',
    'browse.emptyHint': '试试放宽筛选条件，或清空全部筛选。',
    'browse.emptyHintFilter': '没有符合当前筛选条件的内容，试试放宽或清空筛选。',
    'browse.emptyHintSearch': '没有匹配「{q}」的素材，换个关键词试试。',
    'browse.emptyHintNoFilter': '上传图片或通过链接抓取，开始构建你的视觉资产库。',
    'browse.emptyTryTags': '试试热门标签：',
    'browse.loadMore': '加载更多',
    'browse.endOfList': '已显示全部 {count} 项',
    'browse.activeFilters': '已选筛选条件',
    'browse.removeFilter': '移除筛选',
    // 卡片无标题时的读屏描述（有标题时 alt 为空，避免重复朗读）
    'card.mediaAlt': '媒体资源：{name}',
    'lightbox.filterTag': '按标签筛选',
    'browse.keyword': '关键词：{value}',
    'browse.colorFilter': '主色 {value}',
    'browse.collectionFilter': '画板：{value}',
    'browse.searchShortcut': '按 / 聚焦搜索框',
    'browse.searchHistory': '最近搜索',
    'browse.clearHistory': '清空',
    'browse.removeHistoryItem': '移除搜索记录',
    'facet.clearColor': '清除色彩筛选',
    'browse.pickImageSearch': '点击选择图片搜相似',
    'browse.dropUploadHint': '松手添加到上传队列',

    // 排序
    'sort.newest': '最新',
    'sort.oldest': '最早',
    'sort.pixels': '分辨率',
    'sort.size': '体积',
    'sort.views': '热度',
    'sort.random': '随机漫步',
    'sort.label': '排序方式',

    // 视图
    'view.label': '视图模式',
    'view.masonry': '瀑布流',
    'view.grid': '网格',
    'view.list': '列表',
    'density.label': '列密度',
    'density.compact': '紧凑',
    'density.comfortable': '舒适',
    'density.spacious': '大图',
    'wall.backToTop': '回到顶部',
    'card.like': '喜欢',
    'card.unlike': '取消喜欢',

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
    'facet.color': '色彩',
    'facet.collections': '画板',
    'facet.showMore': '展开全部（{count}）',
    'facet.showLess': '收起',
    'facet.excludeTag': '排除标签',
    'facet.filterTagsPlaceholder': '筛选标签…',
    'facet.noMatchingTags': '无匹配标签',
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
    'lightbox.videoFailed': '视频暂时无法播放（可能仍在转码），可稍后刷新或直接下载原文件。',
    'lightbox.close': '关闭',
    'lightbox.preview': '媒体预览',
    'lightbox.video': '视频',
    'lightbox.compare': '对比',
    'lightbox.comparePick': '加入对比',
    'lightbox.compareClear': '退出对比',
    'lightbox.compareSplit': '卷帘',
    'lightbox.compareSide': '并排',
    'lightbox.info': '详细信息',
    'lightbox.spec': '规格',
    'lightbox.author': '作者',
    'lightbox.added': '入库时间',
    'lightbox.heat': '热度',
    'lightbox.views': '浏览 {count}',
    'lightbox.downloads': '下载 {count}',
    'lightbox.source': '来源',
    'lightbox.license': '授权',
    'lightbox.palette': '主色板',
    'lightbox.copyColor': '复制色值',
    'lightbox.copied': '已复制',
    'lightbox.copiedToast': '已复制到剪贴板',
    'lightbox.copyFailed': '复制失败，请检查浏览器剪贴板权限',
    'lightbox.filterColor': '按此色筛选',
    'lightbox.copyLink': '复制直链',
    'lightbox.copyShare': '复制分享链接',
    'lightbox.slideshowToggle': '连播开关',
    'lightbox.slideshowInterval': '连播间隔',
    'lightbox.help': '快捷键',
    'lightbox.fit': '适应屏幕',
    'lightbox.resetZoomHint': '双击或按 0 复位',
    'lightbox.actualSize': '1:1 原图',
    'lightbox.like': '喜欢',
    'lightbox.unlike': '取消喜欢',
    'lightbox.edit': '编辑',
    'lightbox.save': '保存',
    'lightbox.saved': '已保存',
    'lightbox.saveFailed': '保存失败，请重试',
    'lightbox.notes': '备注',
    'lightbox.notesPlaceholder': '补充来源说明或使用备注',
    'lightbox.similar': '视觉相似',
    'lightbox.speed': '播放倍速',
    'lightbox.loop': '循环播放',
    'lightbox.pip': '画中画',
    'lightbox.mute': '静音 / 取消静音',
    'shortcut.mute': '视频静音开关',
    'lightbox.compareCount': '已选 {count}/4',
    'lightbox.filmstrip': '胶片快速跳转',
    'lightbox.filmstripToggle': '显隐胶片条',
    'lightbox.copyTags': '复制全部标签',
    'lightbox.editHint': 'Esc 取消编辑 · ⌘/Ctrl+Enter 保存',
    'lightbox.hideChrome': '纯净看图',
    'lightbox.showChrome': '显示控件',
    'lightbox.loadingOriginal': '正在加载原图…',
    'lightbox.stageBg': '切换看图底色',
    'lightbox.stageBgDark': '暗夜',
    'lightbox.stageBgPaper': '纸白',
    'lightbox.stageBgGrid': '透明格',
    'shortcut.stageBg': '切换看图背景（暗/白/棋盘格）',
    'shortcut.hideChrome': '纯净看图（隐藏控件）',
    'shortcut.filmstrip': '显隐胶片条',
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
    'shortcut.actualSize': '切换 1:1 原图 / 适应屏幕',
    'shortcut.like': '喜欢 / 取消喜欢',
    'shortcut.info': '显示 / 隐藏信息面板',
    'shortcut.download': '下载原图',
    'shortcut.copy': '复制直链',
    'shortcut.slideshow': '连播开关（图片）',
    'shortcut.close': '关闭灯箱',
    'shortcut.help': '打开本帮助',
    'shortcut.seekVideo': '视频快退 / 快进 5 秒',
    'license.personalOnly': '仅限个人使用',
    'license.commercial': '可商用',
    'card.personal': '个人',

    // Toast
    'toast.close': '关闭提示',

    // 通用
    'common.close': '关闭',
    'common.cancel': '取消',
    'common.retry': '重试',
    'review.title': '选片与批注',
    'review.hint': '←/→ 切换 · 1 选中 · 2 待定 · 3 否决',
    'review.expires': '此链接有效期至 {date}',
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
    'review.zoomIn': '点击放大查看',
    'review.zoomOut': '还原适配尺寸',
    'review.empty': '这个选片集还没有素材',
    'review.invalid': '选片链接无效或已失效',
    'review.loadFailed': '加载失败，请稍后重试',
    'review.saveFailed': '保存失败，已回滚',
    'review.autoNext': '标记后自动下一张',
    'review.filterAll': '全部',
    'review.progressText': '已审阅 {done} / {total}',
    'review.noteShortcutHint': '⌘/Ctrl+Enter 保存',
    'review.copySummary': '复制选中清单',
    'review.summaryCopied': '已复制选中清单',
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
    'upload.dropHintTouch': '点按选择文件',
    'upload.dropSubTouch': '支持图片与视频，可从相册或文件中选择',
    'upload.onlyMedia': '只能上传图片或视频文件',
    'upload.tooLarge': '以下文件超过 1GB，已跳过：{names}',
    'upload.remove': '移除',
    'upload.clearQueue': '清空队列',
    'upload.queueSummary': '已选 {count} 项 · {size}',
    'ai.searching': '正在以图搜图…',
    'upload.fieldTitle': '标题（可选）',
    'upload.titlePlaceholder': '留空则用文件名',
    'upload.fieldTags': '标签（可选）',
    'upload.tagsPlaceholder': '用逗号或空格分隔，如：城市 夜景',
    'upload.suggestedTags': '常用标签',
    'upload.submit': '上传 {count} 个文件',
    'upload.uploading': '上传中…',
    'upload.done': '已入库 {count} 项',
    'upload.doneWithDuplicates': '新入库 {fresh} 项，{dup} 项已存在（未重复入库）',
    'upload.urlLabel': '素材链接（支持多行批量）',
    'upload.urlPlaceholder': 'https://...（每行一条链接，可一次提交多条）',
    'upload.urlHint': '支持直链图片/视频与常见平台页面，可每行粘贴一条批量加入后台队列',
    'upload.badUrl': '请输入以 http:// 或 https:// 开头的链接',
    'upload.submitUrl': '提交采集',
    'upload.queueing': '提交中…',
    'upload.queued': '已加入采集队列，完成后可在列表查看',
    'upload.queuedMulti': '已批量加入 {count} 条采集任务，完成后自动刷新',
    'batch.select': '选择',
    'batch.exitSelect': '退出选择',
    'batch.selectAll': '全选已加载',
    'batch.unselectAll': '取消全选',
    'batch.invert': '反选已加载',
    'batch.bar': '批量操作',
    'batch.selected': '已选 {count} 项',
    'batch.tags': '打标签',
    'batch.collection': '加入画板',
    'batch.export': '导出',
    'batch.exportOptions': '导出规格设置',
    'batch.exportTitle': '导出规格与格式',
    'batch.exportPreset': '尺寸规格',
    'batch.presetOriginal': '原文件直出（无损原图/原视频）',
    'batch.preset2048': '高清交付 · 长边 2048px',
    'batch.preset1280': '网页轻量 · 长边 1280px',
    'batch.preset640': '小图预览 · 长边 640px',
    'batch.exportFormat': '图片格式',
    'batch.formatKeep': '保持原格式',
    'batch.exportStart': '开始打包导出',
    'batch.trash': '移入回收站',
    'batch.trashConfirm': '确认移入回收站 ({count})？',
    'batch.trashed': '已将 {count} 项移入回收站',
    'batch.undoTrash': '撤销',
    'batch.undone': '已恢复 {count} 项',
    'batch.undoFailed': '撤销失败，请到管理台回收站恢复',
    'batch.clear': '清空选择',
    'batch.done': '已完成 {count} 项',
    'batch.tagsTitle': '批量打标签',
    'batch.tagsRemove': '移除标签',
    'batch.tagsRemoveTitle': '批量移除标签',
    'batch.tagsRemoveField': '要移除的标签',
    'batch.tagsRemovePlaceholder': '输入或点选下方标签以移除',
    'batch.tagsRemoveHint': '将从已选的 {count} 项中移除匹配的标签，其余标签保留',
    'batch.tagsRemoveConfirm': '确认移除',
    'batch.selectedItemsTags': '已选素材包含的标签',
    'batch.tagsHint': '将追加到已选的 {count} 项，不会覆盖原有标签',
    'batch.availableTags': '已有标签',
    'batch.collectionTitle': '加入画板',
    'batch.collectionPick': '选择画板',
    'batch.featuredSet': '设为精选',
    'batch.featured': '已把 {count} 项设为首页精选',
    'batch.featuredFailed': '设置精选失败',
    'batch.exported': '导出包已开始下载',
    'batch.exportQueued': '{count} 项较大，已转后台打包，可在任务中心下载',
    'batch.exportCapped': '单次导出上限 200 项，本次仅打包前 200 项（共 {count} 项）',
    'like.onlyLiked': '只看喜欢',
    'like.showAll': '显示全部',
    'like.empty': '还没有喜欢的素材',
    'like.failed': '操作失败，已回滚',
    'recent.title': '最近浏览',
    'recent.count': '最近 {count} 条记录',
    'recent.empty': '还没有浏览记录',
    'recent.clear': '清空记录',
    'recent.remove': '移除此条记录',
    'recent.justNow': '刚刚',
    'recent.minutesAgo': '{count} 分钟前',
    'recent.hoursAgo': '{count} 小时前',
    'home.upload': '上传',
    'card.filterColor': '按主色 {color} 筛选',
    'image.retry': '点击重试加载图片',
    'image.retryLabel': '点击重试',
    'common.confirm': '确定',
  },

  'en-US': {
    'site.name': 'MediaLib',
    'notfound.title': 'Page not found',
    'notfound.heading': 'This page is not in the library',
    'notfound.hint': 'The link may have expired, or the asset was removed.',
    'notfound.back': 'Back to home',
    'site.browse': 'Browse',
    'site.wall': 'Wall',
    'site.admin': 'Admin',
    'site.skipToMain': 'Skip to main content',
    'site.toggleTheme': 'Toggle theme',
    'site.switchToEn': 'Switch to English',
    'site.switchToZh': 'Switch to Chinese',
    'site.themeLight': 'Light theme (click to change)',
    'site.themeDark': 'Dark theme (click to change)',
    'site.themeAuto': 'Follow system theme (click to change)',
    'site.themeAutoShort': 'Follow system',
    'site.themeLightShort': 'Light',
    'site.themeDarkShort': 'Dark',
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
    'home.addFirst': 'Add your first asset',
    'home.notEnough': 'Not enough content to fill this row yet — keep adding.',
    'home.browseAll': 'Browse all',
    'home.all': 'All',
    'home.images': 'Images',
    'home.videos': 'Videos',
    'home.typeFilter': 'Filter by media type',
    'home.shuffle': 'Shuffle',

    'browse.searchPlaceholder': 'Search titles, tags, sources…',
    'browse.searchLabel': 'Search media library',
    'browse.clearSearch': 'Clear search',
    'browse.filter': 'Filters',
    'browse.showResults': 'Show {count}',
    'browse.tapRangeHint': 'Tap cards to multi-select',
    'browse.clearAll': 'Clear all',
    'browse.clearKeyword': 'Clear keyword only',
    'browse.aiResultBanner': 'Showing {count} visually similar results',
    'browse.exitAiSearch': 'Back to library',
    'browse.copyFilterLink': 'Copy filter link',
    'browse.filterLinkCopied': 'Filter view link copied',
    'browse.likedLoadMoreHint': 'Showing liked items from {loaded} loaded assets; load remaining {remaining} items',
    'browse.loadMoreToFindLikes': 'Load more',
    'browse.shiftRangeHint': 'Shift+Click to select a range',
    'browse.selectionCleared': 'Filters updated; {count} item deselected | Filters updated; {count} items deselected',
    'browse.clearFilter': 'Clear filters',
    'browse.emptyTitle': 'No matching content',
    'browse.errorTitle': 'Failed to load content',
    'browse.emptyHintFilter': 'Nothing matches these filters — try loosening or clearing them.',
    'browse.emptyHintSearch': 'No assets match “{q}”. Try another keyword.',
    'browse.emptyHintNoFilter':
      'Upload images or fetch from a link to start building your library.',
    'browse.emptyTryTags': 'Try popular tags:',
    'browse.loadMore': 'Load more',
    'browse.endOfList': 'All {count} items shown',
    'browse.activeFilters': 'Active filters',
    'browse.removeFilter': 'Remove filter',
    'card.mediaAlt': 'Media asset: {name}',
    'lightbox.filterTag': 'Filter by tag',
    'browse.keyword': 'Keyword: {value}',
    'browse.colorFilter': 'Color {value}',
    'browse.collectionFilter': 'Board: {value}',
    'browse.searchShortcut': 'Press / to focus search',
    'browse.searchHistory': 'Recent searches',
    'browse.clearHistory': 'Clear all',
    'browse.removeHistoryItem': 'Remove search term',
    'facet.clearColor': 'Clear color filter',
    'browse.pickImageSearch': 'Click to choose an image to search',
    'browse.dropUploadHint': 'Drop files to add to upload queue',

    'sort.newest': 'Newest',
    'sort.oldest': 'Oldest',
    'sort.pixels': 'Resolution',
    'sort.size': 'Size',
    'sort.views': 'Popular',
    'sort.random': 'Shuffle',
    'sort.label': 'Sort by',

    'view.label': 'View mode',
    'view.masonry': 'Masonry',
    'view.grid': 'Grid',
    'view.list': 'List',
    'density.label': 'Column density',
    'density.compact': 'Compact',
    'density.comfortable': 'Standard',
    'density.spacious': 'Large',
    'wall.backToTop': 'Back to top',
    'card.like': 'Like',
    'card.unlike': 'Unlike',

    'facet.title': 'Filters',
    'facet.clear': 'Clear',
    'facet.counting': 'Counting…',
    'facet.kind': 'Type',
    'facet.orientation': 'Orientation',
    'facet.sizeClass': 'Resolution',
    'facet.ext': 'Format',
    'facet.platform': 'Source',
    'facet.tag': 'Tags',
    'facet.color': 'Color',
    'facet.collections': 'Boards',
    'facet.showMore': 'Show all ({count})',
    'facet.showLess': 'Show less',
    'facet.excludeTag': 'Exclude tag',
    'facet.filterTagsPlaceholder': 'Filter tags…',
    'facet.noMatchingTags': 'No matching tags',
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
    'lightbox.videoFailed': 'This video cannot play yet (it may still be transcoding). Refresh later or download the original file.',
    'lightbox.close': 'Close',
    'lightbox.preview': 'Media preview',
    'lightbox.video': 'Video',
    'lightbox.compare': 'Compare',
    'lightbox.comparePick': 'Add to compare',
    'lightbox.compareClear': 'Exit compare',
    'lightbox.compareSplit': 'Split',
    'lightbox.compareSide': 'Side',
    'lightbox.info': 'Details',
    'lightbox.spec': 'Spec',
    'lightbox.author': 'Author',
    'lightbox.added': 'Added',
    'lightbox.heat': 'Engagement',
    'lightbox.views': '{count} views',
    'lightbox.downloads': '{count} downloads',
    'lightbox.source': 'Source',
    'lightbox.license': 'License',
    'lightbox.palette': 'Palette',
    'lightbox.copyColor': 'Copy color',
    'lightbox.copied': 'Copied',
    'lightbox.copiedToast': 'Copied to clipboard',
    'lightbox.copyFailed': 'Copy failed — check clipboard permissions',
    'lightbox.filterColor': 'Filter by this color',
    'lightbox.copyLink': 'Copy direct link',
    'lightbox.copyShare': 'Copy share link',
    'lightbox.slideshowToggle': 'Toggle slideshow',
    'lightbox.slideshowInterval': 'Slideshow interval',
    'lightbox.help': 'Keyboard shortcuts',
    'lightbox.fit': 'Fit to screen',
    'lightbox.resetZoomHint': 'Double-click or press 0 to reset',
    'lightbox.actualSize': '1:1 Actual size',
    'lightbox.like': 'Like',
    'lightbox.unlike': 'Unlike',
    'lightbox.edit': 'Edit',
    'lightbox.save': 'Save',
    'lightbox.saved': 'Saved',
    'lightbox.saveFailed': 'Save failed, please retry',
    'lightbox.notes': 'Notes',
    'lightbox.notesPlaceholder': 'Add source notes or usage context',
    'lightbox.similar': 'Visually similar',
    'lightbox.speed': 'Playback speed',
    'lightbox.loop': 'Loop video',
    'lightbox.pip': 'Picture-in-Picture',
    'lightbox.mute': 'Mute / Unmute',
    'shortcut.mute': 'Toggle video mute',
    'lightbox.compareCount': '{count}/4 picked',
    'lightbox.filmstrip': 'Filmstrip navigation',
    'lightbox.filmstripToggle': 'Toggle filmstrip',
    'lightbox.copyTags': 'Copy all tags',
    'lightbox.editHint': 'Esc to cancel · ⌘/Ctrl+Enter to save',
    'lightbox.hideChrome': 'Clean view',
    'lightbox.showChrome': 'Show controls',
    'lightbox.loadingOriginal': 'Loading original…',
    'lightbox.stageBg': 'Cycle stage background',
    'lightbox.stageBgDark': 'Dark',
    'lightbox.stageBgPaper': 'Paper',
    'lightbox.stageBgGrid': 'Checker',
    'shortcut.stageBg': 'Cycle stage background',
    'shortcut.hideChrome': 'Toggle clean view',
    'shortcut.filmstrip': 'Toggle filmstrip',
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
    'shortcut.actualSize': 'Toggle 1:1 actual size / fit',
    'shortcut.like': 'Like / unlike',
    'shortcut.info': 'Toggle details panel',
    'shortcut.download': 'Download original',
    'shortcut.copy': 'Copy direct link',
    'shortcut.slideshow': 'Toggle slideshow (images)',
    'shortcut.close': 'Close lightbox',
    'shortcut.help': 'Open this help',
    'shortcut.seekVideo': 'Seek video ±5s',
    'license.personalOnly': 'Personal use only',
    'license.commercial': 'Commercial use',
    'card.personal': 'Personal',

    'toast.close': 'Dismiss notification',

    'common.close': 'Close',
    'common.cancel': 'Cancel',
    'common.retry': 'Retry',
    'review.title': 'Review & Comment',
    'review.hint': '←/→ switch · 1 select · 2 maybe · 3 reject',
    'review.expires': 'This link expires on {date}',
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
    'review.zoomIn': 'Click to zoom in',
    'review.zoomOut': 'Fit to viewport',
    'review.empty': 'This review set has no assets yet',
    'review.invalid': 'This review link is invalid or expired',
    'review.loadFailed': 'Failed to load, please retry',
    'review.saveFailed': 'Save failed, changes reverted',
    'review.autoNext': 'Auto-advance after mark',
    'review.filterAll': 'All',
    'review.progressText': 'Reviewed {done} / {total}',
    'review.noteShortcutHint': '⌘/Ctrl+Enter to save',
    'review.copySummary': 'Copy selected list',
    'review.summaryCopied': 'Selected list copied',
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
    'upload.dropHintTouch': 'Tap to choose files',
    'upload.dropSubTouch': 'Images and videos from your photo library or files',
    'upload.onlyMedia': 'Only image or video files are supported',
    'upload.tooLarge': 'Files over 1GB were skipped: {names}',
    'upload.remove': 'Remove',
    'upload.clearQueue': 'Clear queue',
    'upload.queueSummary': '{count} queued · {size}',
    'ai.searching': 'Searching similar…',
    'upload.fieldTitle': 'Title (optional)',
    'upload.titlePlaceholder': 'Falls back to the file name',
    'upload.fieldTags': 'Tags (optional)',
    'upload.tagsPlaceholder': 'Comma or space separated, e.g. city night',
    'upload.suggestedTags': 'Quick tags',
    'upload.submit': 'Upload {count} file | Upload {count} files',
    'upload.uploading': 'Uploading…',
    'upload.done': '{count} item added | {count} items added',
    'upload.doneWithDuplicates': '{fresh} added, {dup} already in library | {fresh} added, {dup} already in library',
    'upload.urlLabel': 'Asset URLs (one per line supported)',
    'upload.urlPlaceholder': 'https://... (paste one or multiple URLs, one per line)',
    'upload.urlHint': 'Direct image/video links and platform pages; paste multiple lines to batch-enqueue',
    'upload.badUrl': 'Enter a link starting with http:// or https://',
    'upload.submitUrl': 'Fetch',
    'upload.queueing': 'Submitting…',
    'upload.queued': 'Queued for fetching; it will appear in the list when done',
    'upload.queuedMulti': 'Queued {count} URLs for background fetching',
    'batch.select': 'Select',
    'batch.exitSelect': 'Exit select',
    'batch.selectAll': 'Select loaded',
    'batch.unselectAll': 'Unselect all',
    'batch.invert': 'Invert loaded',
    'batch.bar': 'Batch actions',
    'batch.selected': '{count} selected',
    'batch.tags': 'Tag',
    'batch.collection': 'Add to board',
    'batch.export': 'Export',
    'batch.exportOptions': 'Export options',
    'batch.exportTitle': 'Export size & format',
    'batch.exportPreset': 'Max dimension',
    'batch.presetOriginal': 'Original files (lossless)',
    'batch.preset2048': 'High-res · 2048px long edge',
    'batch.preset1280': 'Web · 1280px long edge',
    'batch.preset640': 'Compact · 640px long edge',
    'batch.exportFormat': 'Image format',
    'batch.formatKeep': 'Keep original',
    'batch.exportStart': 'Export ZIP',
    'batch.trash': 'Move to trash',
    'batch.trashConfirm': 'Confirm trash ({count})?',
    'batch.trashed': '{count} item moved to trash | {count} items moved to trash',
    'batch.undoTrash': 'Undo',
    'batch.undone': '{count} item restored | {count} items restored',
    'batch.undoFailed': 'Undo failed; restore from Trash in admin',
    'batch.clear': 'Clear selection',
    'batch.done': '{count} item updated | {count} items updated',
    'batch.tagsTitle': 'Batch tag',
    'batch.tagsRemove': 'Remove tags',
    'batch.tagsRemoveTitle': 'Batch remove tags',
    'batch.tagsRemoveField': 'Tags to remove',
    'batch.tagsRemovePlaceholder': 'Type or pick tags below to remove',
    'batch.tagsRemoveHint': 'Matching tags will be removed from the {count} selected items',
    'batch.tagsRemoveConfirm': 'Remove',
    'batch.selectedItemsTags': 'Tags on selected items',
    'batch.tagsHint': 'Appended to the {count} selected items; existing tags are kept',
    'batch.availableTags': 'Existing tags',
    'batch.collectionTitle': 'Add to board',
    'batch.collectionPick': 'Pick a board',
    'batch.featuredSet': 'Feature',
    'batch.featured': '{count} item featured on the home page | {count} items featured on the home page',
    'batch.featuredFailed': 'Failed to set featured',
    'batch.exported': 'Download started',
    'batch.exportQueued': '{count} items are large; packing in background, download from Jobs',
    'batch.exportCapped': 'Export caps at 200 items; only the first 200 will be packed (of {count})',
    'like.onlyLiked': 'Liked only',
    'like.showAll': 'Show all',
    'like.empty': 'No liked assets yet',
    'like.failed': 'Action failed, reverted',
    'recent.title': 'Recent',
    'recent.count': '{count} recent item | {count} recent items',
    'recent.empty': 'No recently viewed items yet',
    'recent.clear': 'Clear',
    'recent.remove': 'Remove entry',
    'recent.justNow': 'Just now',
    'recent.minutesAgo': '{count}m ago',
    'recent.hoursAgo': '{count}h ago',
    'home.upload': 'Upload',
    'card.filterColor': 'Filter by color {color}',
    'image.retry': 'Retry loading image',
    'image.retryLabel': 'Retry',
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
  // 切换语言后标题不会自动重算（标题在路由守卫里生成），
  // 这里派发事件让守卫逻辑有机会重跑，避免标题停留在旧语言。
  try {
    window.dispatchEvent(new CustomEvent('mlib:locale-change', {
      detail: { locale: locale.value },
    }))
  } catch {
    // 非浏览器环境忽略
  }
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

  // 复数：{count} 存在时先选形（必须是数字，调用方不应预先格式化）
  if (params && typeof params.count === 'number') {
    text = pickPlural(text, params.count)
  }

  if (params) {
    for (const [k, v] of Object.entries(params)) {
      // 数值型 count 统一按 locale 加千分位，避免万级数字连写难读；
      // 复数选形已在上面用原始数字完成，这里只负责展示。
      const shown = k === 'count' && typeof v === 'number'
        ? formatNumber(v)
        : String(v)
      text = text.replaceAll(`{${k}}`, shown)
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

/** 视频时长：秒数易读性差，统一成 m:ss（超 1 小时补 h:mm:ss） */
function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return ''
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
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
    formatDuration,
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
