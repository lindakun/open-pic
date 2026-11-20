<script setup lang="ts">
/**
 * 灯箱 2.0（REQ-V2-20 A-04）
 *
 * 能力边界：
 *   - 图片：滚轮/双击缩放、拖拽平移、1:1 查看（useZoomPan 统一桌面与双指手势）
 *   - 对比模式：选 2–4 项并排/叠加对比，缩放与拖动同步（transform 差 < 0.002 / 1px）
 *   - 连播：Space 播放暂停，间隔 3/5/8s 可选
 *   - 色板：展示 palette 三色，点色值复制 HEX，可「按此色筛选」
 *   - 快捷键：←/→ 切换、+/- 缩放、0 复位、I 信息、D 下载、C 复制直链、Esc 关闭、? 帮助
 *   - 信息面板：分辨率、体积、格式、EXIF 摘要、来源、入库时间、标签、授权
 *
 * 无障碍约束（E-20）：
 *   - 输入框 / TEXTAREA / contenteditable 聚焦时禁用快捷键，IME 组字期间不拦截
 *   - 快捷键帮助为原生 <dialog>，Esc 关闭后焦点回到触发按钮
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MediaItem } from '@/api/types'
import { api } from '@/api/client'
import { userTags } from '@/api/tags'
import { useI18n } from '@/composables/useI18n'
import { copyText } from '@/composables/useClipboard'
import { useZoomPan } from '@/composables/useZoomPan'
import { track } from '@/composables/useAnalytics'

const props = defineProps<{
  item: MediaItem
  hasPrev: boolean
  hasNext: boolean
  /** 当前序号（1-based）与总数，可选传入以展示进度 */
  index?: number
  total?: number
  /** 同屏可对比的候选（通常为当前列表），用于挑选 2–4 项 */
  candidates?: MediaItem[]
  /** 是否已喜欢（C-15） */
  liked?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'prev'): void
  (e: 'next'): void
  (e: 'slideshow-end'): void
  /** 按主色筛选（对接 B-10 的 color 参数） */
  (e: 'filter-color', color: string): void
  /** 按标签筛选（信息面板的标签 chips） */
  (e: 'filter-tag', tag: string): void
  /** 喜欢/取消喜欢 */
  (e: 'toggle-like', id: string): void
  /** 行内编辑保存后通知父组件原地更新列表 */
  (e: 'updated', item: MediaItem): void
  /** 点击相似推荐时通知父组件优先原地切换 */
  (e: 'select-item', item: MediaItem): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const stageRef = ref<HTMLElement | null>(null)
const helpRef = ref<HTMLDialogElement | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const { t, formatBytes, formatDate, formatNumber, formatDuration } = useI18n()

/** 视频播放控制：倍速、循环、静音、画中画 */
const videoSpeed = ref(1)
const videoLoop = ref(false)
const videoMuted = ref((() => {
  try {
    return localStorage.getItem('medialib.videoMuted') === '1'
  } catch {
    return false
  }
})())
const pipSupported = typeof document !== 'undefined' && 'pictureInPictureEnabled' in document && document.pictureInPictureEnabled

function setVideoSpeed(rate: number) {
  videoSpeed.value = rate
  if (videoRef.value) videoRef.value.playbackRate = rate
}

function toggleVideoLoop() {
  videoLoop.value = !videoLoop.value
  if (videoRef.value) videoRef.value.loop = videoLoop.value
}

function toggleVideoMute() {
  videoMuted.value = !videoMuted.value
  if (videoRef.value) videoRef.value.muted = videoMuted.value
  try {
    localStorage.setItem('medialib.videoMuted', videoMuted.value ? '1' : '0')
  } catch {
    // 忽略
  }
}

async function togglePip() {
  const v = videoRef.value
  if (!v || !pipSupported) return
  try {
    if (document.pictureInPictureElement === v) {
      await document.exitPictureInPicture()
    } else {
      await v.requestPictureInPicture()
    }
  } catch {
    // 浏览器限制时静默忽略
  }
}

/**
 * 兼容播放副本缺失或转码未完成时，先回退原文件再试一次；
 * 仍失败则展示下载引导，避免用户只看到一块黑屏。
 */
function onVideoError() {
  const v = videoRef.value
  if (!v) return
  const original = `/f/${props.item.file}`
  let usingPlayCopy = false
  try {
    usingPlayCopy = new URL(v.currentSrc || v.src, window.location.origin).searchParams.has('play')
  } catch {
    usingPlayCopy = false
  }
  if (usingPlayCopy) {
    v.src = original
    v.load()
    return
  }
  videoFailed.value = true
}

/** 转码可能刚完成：清空失败态并重新按兼容副本加载 */
function retryVideo() {
  const v = videoRef.value
  if (!v) return
  videoFailed.value = false
  v.src = props.item.play_file ? `/f/${props.item.file}?play=1` : `/f/${props.item.file}`
  v.load()
  void v.play().catch(() => {})
}

/** 信息面板行内编辑（REQ-05） */
const editing = ref(false)
const editTitle = ref('')
const editTags = ref('')
const editNotes = ref('')
const editSaving = ref(false)
const editError = ref('')

function startEdit() {
  editTitle.value = props.item.title || ''
  editTags.value = (props.item.tags ?? []).join(' ')
  editNotes.value = props.item.notes || ''
  editError.value = ''
  editing.value = true
}

async function saveEdit() {
  if (editSaving.value) return
  editSaving.value = true
  editError.value = ''
  try {
    const tags = editTags.value
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    const updated = await api.updateItem(props.item.id, {
      title: editTitle.value.trim(),
      tags,
      notes: editNotes.value.trim(),
    } as Partial<MediaItem>)
    editing.value = false
    emit('updated', updated)
    await flash('saved')
  } catch {
    editError.value = t('lightbox.saveFailed')
  } finally {
    editSaving.value = false
  }
}

/** 视觉相似推荐（REQ-09）：仅在信息面板展开时按需拉取 */
const similarItems = ref<MediaItem[]>([])
let similarSeq = 0

async function loadSimilar() {
  const seq = ++similarSeq
  similarItems.value = []
  try {
    const list = await api.similar(props.item.id, 6)
    if (seq === similarSeq) {
      similarItems.value = list.filter((i) => i.id !== props.item.id).slice(0, 6)
    }
  } catch {
    if (seq === similarSeq) similarItems.value = []
  }
}

const {
  scale,
  x: zoomX,
  y: zoomY,
  dragging,
  style: zoomStyle,
  reset: resetZoom,
  zoomBy,
  setScale,
  bind: bindZoom,
  unbind: unbindZoom,
} = useZoomPan(stageRef)

/** 信息面板展开状态：默认收起，纯图优先 */
const infoOpen = ref(false)
const helpOpen = ref(false)
/** 胶片快速跳转条：长列表下快速跨项跳转，快捷键 F 显隐 */
const filmstripOpen = ref(false)
/** 缩略图多级回退：_sm.webp → 标准缩略图 → 原文件，避免老资产出现破图 */
function onThumbError(e: Event, pick: MediaItem) {
  const img = e.target as HTMLImageElement
  const level = img.dataset.fb ?? '0'
  if (level === '0') {
    img.dataset.fb = '1'
    img.src = `/t/${pick.id}.jpg`
  } else if (level === '1') {
    img.dataset.fb = '2'
    img.src = `/f/${pick.file}`
  }
}
/** 纯净看图模式：隐藏悬浮控制条与顶部对比条，仅留角落恢复按钮（快捷键 H） */
const chromeHidden = ref(false)
/** 看图背景底色：暗夜 / 纸白 / 透明棋盘格（快捷键 B） */
type StageBg = 'dark' | 'paper' | 'grid'
const STAGE_BGS: StageBg[] = ['dark', 'paper', 'grid']
const stageBg = ref<StageBg>('dark')
function cycleStageBg() {
  const i = STAGE_BGS.indexOf(stageBg.value)
  stageBg.value = STAGE_BGS[(i + 1) % STAGE_BGS.length]
}
const stageBgLabel = computed(() => {
  if (stageBg.value === 'paper') return t('lightbox.stageBgPaper')
  if (stageBg.value === 'grid') return t('lightbox.stageBgGrid')
  return t('lightbox.stageBgDark')
})
/** 当前主图解码完成标记：切换大图时显示柔和加载环 */
const imgLoaded = ref(false)
/** 视频解码/播放失败（兼容副本缺失或仍在转码） */
const videoFailed = ref(false)
/** 放大 >1.2x 升级加载原图时的状态标记 */
const upgradingOriginal = ref(false)
/** 复制反馈：'link' | 'hex:<color>' | null，1.6s 后自动清除 */
const copied = ref<string | null>(null)
/** 对比模式：从候选里选出的 2–4 项 id（含当前项） */
const compareIds = ref<string[]>([])
/** 两图对比时支持「并排」或「卷帘叠加」切换 */
const compareSplit = ref(false)
const splitPos = ref(50)
/** 连播状态与间隔 */
const slideshow = ref<{ on: boolean; ms: number }>({ on: false, ms: 5000 })
let slideshowTimer: number | null = null
let copyTimer: number | null = null

const mediaUrl = computed(() => `/f/${props.item.file}`)
/**
 * 视频播放地址：优先走后端生成的 H.264 兼容副本（?play=1），
 * HEVC/AVI/MKV 等浏览器不支持的编码会黑屏，副本由入库任务自动转码。
 * 原图仅用于下载。
 */
const videoUrl = computed(() =>
  props.item.play_file ? `/f/${props.item.file}?play=1` : `/f/${props.item.file}`,
)
/** 下载地址：带 dl=1 让后端计入下载量统计 */
const downloadUrl = computed(() => `/f/${props.item.file}?dl=1`)

/** 放大到 >1.2x 时无缝升级为原图，保证细节锐利 */
function imgSrcFor(it: MediaItem): string {
  if (!it.thumb) return `/f/${it.file}`
  if (!compareOn.value && it.id === props.item.id && scale.value > 1.2) {
    return `/f/${it.file}`
  }
  return `/t/${it.id}_lg.webp`
}

/** 切换 1:1 原图像素尺寸 / 适应屏幕 */
function toggleActualSize() {
  if (props.item.kind !== 'image') return
  if (scale.value > 1.05) {
    resetZoom()
    return
  }
  const imgEl = stageRef.value?.querySelector<HTMLImageElement>('.lightbox__img')
  const naturalW = props.item.width || imgEl?.naturalWidth || 0
  const displayedW = imgEl?.clientWidth || 0
  if (naturalW > 0 && displayedW > 0 && naturalW > displayedW) {
    setScale(naturalW / displayedW)
  } else {
    setScale(2)
  }
}

/** 双击：未放大时以点击位置放大 2x，已放大时复位 */
function onImgDblClick(e: MouseEvent) {
  if (scale.value > 1.05) {
    resetZoom()
    return
  }
  const el = stageRef.value
  if (!el) {
    setScale(2)
    return
  }
  const rect = el.getBoundingClientRect()
  const cx = e.clientX - rect.left - rect.width / 2
  const cy = e.clientY - rect.top - rect.height / 2
  setScale(2, cx, cy)
}

/** 移动端左右滑动切图（仅在未放大时生效，避免与拖拽平移冲突） */
let swipeStart = { x: 0, y: 0, active: false }

function onStageTouchStart(e: TouchEvent) {
  if (e.touches.length === 1 && scale.value <= 1.05) {
    swipeStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, active: true }
  } else {
    swipeStart.active = false
  }
}

function onStageTouchEnd(e: TouchEvent) {
  if (!swipeStart.active || scale.value > 1.05) return
  swipeStart.active = false
  const t0 = e.changedTouches[0]
  if (!t0) return
  const dx = t0.clientX - swipeStart.x
  const dy = t0.clientY - swipeStart.y
  if (Math.abs(dx) >= 48 && Math.abs(dx) > Math.abs(dy) * 1.5) {
    if (dx > 0 && props.hasPrev) emit('prev')
    else if (dx < 0 && props.hasNext) emit('next')
  }
}

/** 静默预加载相邻图的大尺寸缩略图，切图更顺滑 */
function preloadNeighbors() {
  if (typeof Image === 'undefined' || !props.candidates?.length) return
  const idx = props.candidates.findIndex((c) => c.id === props.item.id)
  if (idx < 0) return
  for (const offset of [-1, 1]) {
    const nb = props.candidates[idx + offset]
    if (nb && nb.kind === 'image') {
      const loader = new Image()
      loader.src = nb.thumb ? `/t/${nb.id}_lg.webp` : `/f/${nb.file}`
    }
  }
}
function onImgError(event: Event, item: MediaItem) {
  const img = event.target as HTMLImageElement
  const fallback = `/f/${item.file}`
  if (img.getAttribute('src') !== fallback) img.src = fallback
}

/** 固定浮点误差，保证对比模式下两图 transform 数值完全一致 */
const priceScale = computed(() => Number(scale.value.toFixed(3)))

const spec = computed(() => {
  const parts: string[] = []
  if (props.item.width && props.item.height) {
    parts.push(`${props.item.width}×${props.item.height}`)
  }
  if (props.item.ext) parts.push(props.item.ext.replace(/^\./, '').toUpperCase())
  if (props.item.size) parts.push(formatBytes(props.item.size))
  if (props.item.duration) parts.push(formatDuration(props.item.duration))
  if (props.item.kind === 'video' && props.item.fps) {
    parts.push(`${Math.round(props.item.fps)}fps`)
  }
  if (props.item.kind === 'video' && props.item.codec) {
    parts.push(props.item.codec.toUpperCase())
  }
  return parts.join(' · ')
})

/** 色板：palette 为空时退回主色 */
const palette = computed<string[]>(() => {
  // 后端 hydrate 会把 palette_json 解析成 palette 数组；
  // 直接取原始 item（例如列表缓存）时则回退解析 palette_json。
  const item = props.item as MediaItem & { palette?: string[] }
  let list: string[] = Array.isArray(item.palette) ? item.palette : []
  if (!list.length) {
    try {
      const parsed = JSON.parse(props.item.palette_json || '[]')
      if (Array.isArray(parsed)) list = parsed.map(String)
    } catch {
      list = []
    }
  }
  const valid = list.filter((c) => /^#[0-9a-fA-F]{6}$/.test(c))
  if (valid.length) return valid.slice(0, 4)
  return /^#[0-9a-fA-F]{6}$/.test(props.item.dominant_color)
    ? [props.item.dominant_color]
    : []
})

/** EXIF 摘要：只挑常用的几项，避免整块 JSON 铺满面板 */
const exifRows = computed<{ label: string; value: string }[]>(() => {
  let data: Record<string, unknown> = {}
  try {
    data = JSON.parse(props.item.exif_json || '{}')
  } catch {
    return []
  }
  const map: Record<string, string> = {
    Make: 'exif.make',
    Model: 'exif.model',
    DateTimeOriginal: 'exif.taken',
    FNumber: 'exif.aperture',
    ExposureTime: 'exif.shutter',
    ISOSpeedRatings: 'exif.iso',
    FocalLength: 'exif.focal',
  }
  const rows: { label: string; value: string }[] = []
  for (const [key, tKey] of Object.entries(map)) {
    const raw = data[key]
    if (raw === undefined || raw === null || raw === '' || raw === 0) continue
    rows.push({ label: t(tKey), value: String(raw) })
  }
  return rows
})

/** 对比项：当前项始终在首位，其余按选择顺序 */
const compareItems = computed<MediaItem[]>(() => {
  const pool = props.candidates ?? []
  const all = [props.item, ...pool.filter((i) => i.id !== props.item.id)]
  // 当前项恒定在首位，其余按选择顺序
  const picked = compareIds.value
    .filter((id) => id !== props.item.id)
    .map((id) => all.find((i) => i.id === id))
    .filter((i): i is MediaItem => Boolean(i))
  return [props.item, ...picked]
})

/**
 * 对比模式判定：当前项恒定参与，额外选中 1 项即为「2 图对比」。
 * 上限 4 图 ⇒ 额外选中最多 3 项（A-04 验收：2/3/4 图布局）。
 */
const compareOn = computed(() => compareIds.value.length >= 1)
const COMPARE_EXTRA_MAX = 3

watch(
  () => !compareOn.value && props.item.kind === 'image' && Boolean(props.item.thumb) && scale.value > 1.2,
  (isOriginal) => {
    upgradingOriginal.value = isOriginal
  },
)

/** 对比候选：限额 8 个且仅收图片（视频不支持静态并排/卷帘对比），避免长列表渲染开销。
 *  当前项不进候选条——它已恒定参与对比，点自己的圆点只会产生
 *  单图"对比"的挤压布局（实测发现）。
 */
const compareChoices = computed(() =>
  (props.candidates ?? []).filter((i) => i.id !== props.item.id && i.kind === 'image').slice(0, 8),
)

function toggleCompare(id: string) {
  // 连播与对比互斥：连播会自动切图，对比却要固定住图片，二者同时开会互相打架
  if (slideshow.value.on) stopSlideshow()
  if (compareIds.value.includes(id)) {
    compareIds.value = compareIds.value.filter((x) => x !== id)
    return
  }
  // 2–4 图上限：当前项 + 额外 3 项（A-04 验收）
  if (compareIds.value.length >= COMPARE_EXTRA_MAX) return
  compareIds.value = [...compareIds.value, id]
}

function inCompare(id: string) {
  return compareIds.value.includes(id)
}

function close() {
  emit('close')
}

// ---------- 连播 ----------
function stopSlideshow() {
  if (slideshowTimer !== null) {
    window.clearInterval(slideshowTimer)
    slideshowTimer = null
  }
  slideshow.value = { ...slideshow.value, on: false }
}

function startSlideshow() {
  stopSlideshow()
  // 连播时退出对比，避免自动切图与固定对比冲突
  compareIds.value = []
  slideshow.value = { ...slideshow.value, on: true }
  slideshowTimer = window.setInterval(() => {
    if (props.hasNext) {
      emit('next')
    } else {
      // 到底后回到首张继续，符合"连播放映"的语义；
      // 父组件若不回到首张则停止，避免空转。
      emit('slideshow-end')
    }
  }, slideshow.value.ms)
}

function toggleSlideshow() {
  if (slideshow.value.on) stopSlideshow()
  else startSlideshow()
}

function setInterval_(ms: number) {
  slideshow.value = { ...slideshow.value, ms }
  if (slideshow.value.on) startSlideshow()
}

// ---------- 复制与筛选 ----------
async function flash(key: string) {
  copied.value = key
  if (copyTimer !== null) window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => {
    copied.value = null
  }, 1600)
}

/**
 * 复制分享链接而非裸文件地址。
 *
 * 语义页 /a/{slug}-{shortId} 带标题、下载与 OG 信息，
 * 比 /f/ 直链更适合对外分享；没有 slug 的存量资产回退到 /s/{id}。
 */
const shareUrl = computed(() => {
  const it = props.item
  const path = it.slug
    ? `/a/${it.slug}-${it.id.slice(0, 8)}`
    : `/s/${it.id}`
  return new URL(path, window.location.origin).toString()
})

async function copyLink() {
  if (await copyText(shareUrl.value)) await flash('link')
  else await flash('copy-failed')
}

async function copyColor(color: string) {
  if (await copyText(color.toUpperCase())) await flash(`hex:${color}`)
  else await flash('copy-failed')
}

async function copyTags() {
  const list = userTags(props.item.tags)
  if (!list.length) return
  if (await copyText(list.join(' '))) await flash('tags')
  else await flash('copy-failed')
}

function formatSource(raw: string): string {
  try {
    const u = new URL(raw)
    const path = u.pathname === '/' ? '' : u.pathname.replace(/\/$/, '')
    const shortPath = path.length > 24 ? `${path.slice(0, 22)}…` : path
    return `${u.hostname.replace(/^www\./, '')}${shortPath}`
  } catch {
    return raw
  }
}

function filterByColor(color: string) {
  emit('filter-color', color)
  close()
}

function filterByTag(tag: string) {
  emit('filter-tag', tag)
  close()
}

function download() {
  track('download', { itemId: props.item.id })
  const a = document.createElement('a')
  a.href = downloadUrl.value
  a.download = props.item.name || ''
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// ---------- 快捷键 ----------
function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  const tag = el?.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || Boolean(el?.isContentEditable)
}

function onDialogCancel(e: Event) {
  if (editing.value) {
    e.preventDefault()
    editing.value = false
    editError.value = ''
  }
}

function onKeydown(e: KeyboardEvent) {
  // 帮助浮层打开时只保留 Esc 关闭，其余快捷键不作用于背后的灯箱
  if (helpOpen.value) {
    if (e.key === 'Escape') {
      e.preventDefault()
      closeHelp()
    }
    return
  }
  // 行内编辑中按 Esc 优先退出编辑，避免直接关掉灯箱丢失草稿
  if (e.key === 'Escape' && editing.value) {
    e.preventDefault()
    editing.value = false
    editError.value = ''
    return
  }
  // 输入态与输入法组字期间不拦截（A-04 验收）
  if (isTypingTarget(e.target)) return
  if (e.isComposing) return
  // 视频获得焦点时方向键/空格交给原生播放器：否则会一边 seek 一边切换素材
  const focusedTag = (e.target as HTMLElement | null)?.tagName
  if (focusedTag === 'VIDEO' && (e.key.startsWith('Arrow') || e.key === ' ')) return

  switch (e.key) {
    case 'Escape':
      if (chromeHidden.value) {
        chromeHidden.value = false
        break
      }
      close()
      break
    case 'ArrowLeft':
      if (e.shiftKey && props.item.kind === 'video' && videoRef.value) {
        e.preventDefault()
        videoRef.value.currentTime = Math.max(0, videoRef.value.currentTime - 5)
        break
      }
      if (props.hasPrev) {
        emit('prev')
        if (slideshow.value.on) startSlideshow() // 手动切图后重置计时，避免紧接着又自动跳
      }
      break
    case 'ArrowRight':
      if (e.shiftKey && props.item.kind === 'video' && videoRef.value) {
        e.preventDefault()
        videoRef.value.currentTime = videoRef.value.currentTime + 5
        break
      }
      if (props.hasNext) {
        emit('next')
        if (slideshow.value.on) startSlideshow()
      }
      break
    case '+':
    case '=':
      e.preventDefault()
      zoomBy(0.25)
      break
    case '-':
      e.preventDefault()
      zoomBy(-0.25)
      break
    case '0':
      resetZoom()
      break
    case '1':
      toggleActualSize()
      break
    case 'l':
    case 'L':
      emit('toggle-like', props.item.id)
      break
    case 'i':
    case 'I':
      infoOpen.value = !infoOpen.value
      if (infoOpen.value) focusPanel()
      break
    case 'f':
    case 'F':
      if ((props.candidates?.length ?? 0) > 1 && !compareOn.value) {
        filmstripOpen.value = !filmstripOpen.value
      }
      break
    case 'h':
    case 'H':
      chromeHidden.value = !chromeHidden.value
      break
    case 'b':
    case 'B':
      if (props.item.kind === 'image') cycleStageBg()
      break
    case 'm':
    case 'M':
      if (props.item.kind === 'video') toggleVideoMute()
      break
    case 'Home':
      if (!compareOn.value && props.candidates?.length) {
        e.preventDefault()
        emit('select-item', props.candidates[0])
      }
      break
    case 'End':
      if (!compareOn.value && props.candidates?.length) {
        e.preventDefault()
        emit('select-item', props.candidates[props.candidates.length - 1])
      }
      break
    case 'd':
    case 'D':
      download()
      break
    case 'c':
    case 'C':
      void copyLink()
      break
    case '?':
    case '/':
      e.preventDefault()
      openHelp()
      break
    case ' ':
      // Space：视频由原生控件处理，图片走连播
      if (props.item.kind === 'image') {
        e.preventDefault()
        toggleSlideshow()
      }
      break
  }
}

let helpTrigger: HTMLElement | null = null

/** 信息面板打开后把焦点交给其关闭按钮，避免 Tab 跑到背景卡片 */
function focusPanel() {
  nextTick(() => {
    document.querySelector<HTMLButtonElement>('.panel__close')?.focus({ preventScroll: true })
  })
}

function openHelp() {
  helpTrigger = document.activeElement as HTMLElement | null
  helpOpen.value = true
  nextTick(() => {
    helpRef.value?.showModal()
    // 焦点落在首个可交互元素（关闭按钮），键盘可直接 Esc/回车退出
    helpRef.value?.querySelector<HTMLButtonElement>('.help__close')?.focus()
  })
}

function closeHelp() {
  helpRef.value?.close()
  helpOpen.value = false
  if (helpTrigger && document.contains(helpTrigger)) {
    helpTrigger.focus({ preventScroll: true })
  }
}

const shortcuts = computed(() => [
  { key: '← / →', desc: t('shortcut.switch') },
  { key: 'Shift + ← / →', desc: t('shortcut.seekVideo') },
  { key: '+ / -', desc: t('shortcut.zoom') },
  { key: '1', desc: t('shortcut.actualSize') },
  { key: '0', desc: t('shortcut.reset') },
  { key: 'L', desc: t('shortcut.like') },
  { key: 'I', desc: t('shortcut.info') },
  { key: 'F', desc: t('shortcut.filmstrip') },
  { key: 'H', desc: t('shortcut.hideChrome') },
  { key: 'B', desc: t('shortcut.stageBg') },
  { key: 'M', desc: t('shortcut.mute') },
  { key: 'D', desc: t('shortcut.download') },
  { key: 'C', desc: t('shortcut.copy') },
  { key: 'Space', desc: t('shortcut.slideshow') },
  { key: 'Esc', desc: t('shortcut.close') },
  { key: '?', desc: t('shortcut.help') },
])

function scrollLbFilmToCurrent() {
  void nextTick(() => {
    dialogRef.value
      ?.querySelector<HTMLElement>('.lb-film--cur')
      ?.scrollIntoView?.({ block: 'nearest', inline: 'center', behavior: 'smooth' })
  })
}

watch(filmstripOpen, (open) => {
  if (open) scrollLbFilmToCurrent()
})

// 切换条目时复位视图状态并预加载相邻图片
watch(
  () => props.item.id,
  () => {
    imgLoaded.value = false
    upgradingOriginal.value = false
    videoFailed.value = false
    resetZoom()
    compareIds.value = []
    compareSplit.value = false
    splitPos.value = 50
    editing.value = false
    editError.value = ''
    // 切图时若帮助浮层还开着，关掉避免说明与当前内容脱节
    if (helpOpen.value) closeHelp()
    preloadNeighbors()
    if (filmstripOpen.value) scrollLbFilmToCurrent()
    if (infoOpen.value) void loadSimilar()
  },
  { immediate: true },
)

// 灯箱实例在图片/视频间切换时复用：视频态不能保留滚轮缩放拦截，
// 从视频切回图片也必须重新绑定，否则缩放/拖拽会静默失效。
watch(
  () => props.item.kind,
  (kind) => {
    const el = stageRef.value
    if (!el) return
    if (kind === 'image') bindZoom(el)
    else unbindZoom(el)
  },
)

watch(infoOpen, (open) => {
  if (open && !similarItems.value.length) void loadSimilar()
})

// 窗口尺寸变化后，先前的缩放/平移锚点会失效（图片被裁切），复位更符合预期
function onResize() {
  resetZoom()
}

/** 记住触发元素，关闭后把焦点还回去（键盘用户不会丢失位置） */
let lastFocused: HTMLElement | null = null

onMounted(() => window.addEventListener('resize', onResize, { passive: true }))

onMounted(() => {
  lastFocused = document.activeElement as HTMLElement | null
  dialogRef.value?.showModal()
  window.addEventListener('keydown', onKeydown)
  if (stageRef.value && props.item.kind === 'image') bindZoom(stageRef.value)
  // 标记"灯箱开启"：隐藏 sticky 顶栏并锁定背景滚动。
  // dialog::backdrop 处于 top layer，但 sticky 元素仍会绘制在其上，
  // 必须显式隐藏顶栏，否则顶栏会浮在灯箱之上（实测发现）。
  // 记录滚动条占用宽度：隐藏滚动条后补 padding，避免内容横向抖动
  const scrollbar = window.innerWidth - document.documentElement.clientWidth
  document.documentElement.style.setProperty('--scrollbar-comp', `${Math.max(0, scrollbar)}px`)
  document.documentElement.classList.add('lightbox-open')
})

onUnmounted(() => {
  // 焦点还原：仅在原元素仍在文档中时执行，避免指针落到已卸载节点
  if (lastFocused && document.contains(lastFocused)) {
    lastFocused.focus({ preventScroll: true })
  }
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
  if (stageRef.value) unbindZoom(stageRef.value)
  stopSlideshow()
  if (copyTimer !== null) window.clearTimeout(copyTimer)
  document.documentElement.classList.remove('lightbox-open')
  document.documentElement.style.removeProperty('--scrollbar-comp')
})
</script>

<template>
  <dialog
    ref="dialogRef"
    class="lightbox"
    :aria-label="t('lightbox.preview')"
    @cancel="onDialogCancel"
    @close="close"
    @click="($event.target as HTMLElement).tagName === 'DIALOG' && close()"
  >
    <!-- 舞台：对比模式为网格，单图为单格；打开信息面板时右侧让出空间，避免遮挡图片 -->
    <div
      ref="stageRef"
      :class="[
        'lightbox__stage',
        `lightbox__stage--bg-${stageBg}`,
        {
          'lightbox__stage--compare': compareOn && !(compareSplit && compareItems.length === 2),
          'lightbox__stage--split': compareOn && compareSplit && compareItems.length === 2,
          'lightbox__stage--compare-grid': compareOn && compareItems.length > 2,
          'lightbox__stage--with-panel': infoOpen,
          'lightbox__stage--with-film': filmstripOpen && (candidates?.length ?? 0) > 1 && !compareOn,
          'lightbox__stage--has-compare': item.kind === 'image' && compareChoices.length >= 1,
        },
      ]"
      @click.self="close"
      @touchstart.passive="onStageTouchStart"
      @touchend.passive="onStageTouchEnd"
    >
      <!-- 连播倒计时进度条 -->
      <div
        v-if="slideshow.on && item.kind === 'image'"
        :key="`ss-${item.id}-${slideshow.ms}`"
        class="lightbox__ss-bar"
        :style="{ animationDuration: `${slideshow.ms}ms` }"
        aria-hidden="true"
      />

      <template v-if="item.kind === 'image'">
        <div v-if="!imgLoaded && !compareOn" class="lightbox__spinner" aria-hidden="true" />
        <!-- 两图卷帘叠加对比 -->
        <div v-if="compareOn && compareSplit && compareItems.length === 2" class="lightbox__split-box">
          <img
            :src="imgSrcFor(compareItems[1])"
            :alt="compareItems[1].title || compareItems[1].name"
            class="lightbox__img lightbox__img--ready lightbox__split-img"
            :style="{ transform: `translate3d(${zoomX}px, ${zoomY}px, 0) scale(${priceScale})` }"
            @error="onImgError($event, compareItems[1])"
          />
          <img
            :src="imgSrcFor(compareItems[0])"
            :alt="compareItems[0].title || compareItems[0].name"
            class="lightbox__img lightbox__img--ready lightbox__split-img lightbox__split-top"
            :style="{
              transform: `translate3d(${zoomX}px, ${zoomY}px, 0) scale(${priceScale})`,
              clipPath: `inset(0 ${100 - splitPos}% 0 0)`,
            }"
            @error="onImgError($event, compareItems[0])"
          />
          <div class="lightbox__split-line" :style="{ left: `${splitPos}%` }" aria-hidden="true">
            <span class="lightbox__split-knob">⇆</span>
          </div>
          <input
            v-model.number="splitPos"
            type="range"
            min="0"
            max="100"
            class="lightbox__split-range"
            :aria-label="t('lightbox.compareSplit')"
          />
          <span class="lightbox__split-tag lightbox__split-tag--left mono">{{ compareItems[0].title || compareItems[0].name }}</span>
          <span class="lightbox__split-tag lightbox__split-tag--right mono">{{ compareItems[1].title || compareItems[1].name }}</span>
        </div>
        <!-- 单图或并排多图对比 -->
        <template v-else>
          <figure v-for="it in compareOn ? compareItems : [item]" :key="it.id" class="lightbox__frame">
            <img
              :src="imgSrcFor(it)"
              :alt="it.title || it.name"
              :class="[
                'lightbox__img',
                {
                  'lightbox__img--zoomed': scale > 1.02,
                  'lightbox__img--dragging': dragging,
                  'lightbox__img--ready': compareOn || imgLoaded,
                },
              ]"
              :style="compareOn
                ? { transform: `translate3d(${zoomX}px, ${zoomY}px, 0) scale(${priceScale})` }
                : { ...zoomStyle, viewTransitionName: `media-${item.id}` }"
              @load="it.id === item.id && (imgLoaded = true, upgradingOriginal = false)"
              @dblclick="onImgDblClick($event)"
              @error="it.id === item.id && (imgLoaded = true, upgradingOriginal = false); onImgError($event, it)"
            />
            <figcaption v-if="compareOn" class="lightbox__cap mono">
              {{ it.title || it.name }} · {{ it.width }}×{{ it.height }} · {{ it.ext.replace(/^\./, '').toUpperCase() }}<template v-if="it.size"> · {{ formatBytes(it.size) }}</template>
            </figcaption>
          </figure>
        </template>
      </template>
      <!-- key 强制切换条目时重建播放器：仅改 src 时部分浏览器
           不会重新触发 autoplay，会停留在上一支视频的最后一帧 -->
      <video
        v-else
        ref="videoRef"
        :key="item.id"
        :src="videoUrl"
        :poster="`/t/${item.id}.jpg`"
        :loop="videoLoop"
        :muted="videoMuted"
        :style="{ backgroundColor: item.dominant_color || '#12100d' }"
        controls
        autoplay
        playsinline
        preload="metadata"
        class="lightbox__video"
        @loadedmetadata="videoRef && (videoRef.playbackRate = videoSpeed)"
        @error="onVideoError"
      />
      <!-- 视频彻底无法播放时的兜底引导，避免只有黑屏 -->
      <div v-if="videoFailed" class="lightbox__video-error" role="status">
        <p>{{ t('lightbox.videoFailed') }}</p>
        <a :href="downloadUrl" class="lb-btn" download>{{ t('lightbox.download') }}</a>
        <button type="button" class="lb-btn" @click="retryVideo">{{ t('common.retry') }}</button>
      </div>

      <!-- 舞台左右悬浮切图箭头（桌面端 hover 显示，自动避让右侧信息面板） -->
      <button
        v-if="hasPrev && !compareOn"
        type="button"
        class="stage-nav stage-nav--prev" :class="{ 'stage-nav--info-open': infoOpen }"
        :aria-label="t('lightbox.prev')"
        @click.stop="$emit('prev')"
      >
        ‹
      </button>
      <button
        v-if="hasNext && !compareOn"
        type="button"
        :class="['stage-nav', 'stage-nav--next', { 'stage-nav--shifted': infoOpen, 'stage-nav--info-open': infoOpen }]"
        :aria-label="t('lightbox.next')"
        @click.stop="$emit('next')"
      >
        ›
      </button>

      <!-- 缩放倍率浮标（单图与对比模式均可一键复位） -->
      <button
        v-if="item.kind === 'image' && scale > 1.05 && !chromeHidden"
        type="button"
        class="lightbox__zoom-pill mono"
        :title="t('lightbox.fit')"
        @click="resetZoom"
      >
        {{ upgradingOriginal && !compareOn ? t('lightbox.loadingOriginal') : `${Math.round(scale * 100)}% · ${t('lightbox.resetZoomHint')}` }}
      </button>

      <!-- 对比选择条：只在候选足够时出现 -->
      <div v-if="item.kind === 'image' && compareChoices.length >= 1 && !chromeHidden" class="lightbox__compare">
        <span class="lightbox__compare-label">
          {{ compareOn ? t('lightbox.compareCount', { count: compareItems.length }) : t('lightbox.compare') }}
        </span>
        <button
          v-for="c in compareChoices"
          :key="c.id"
          type="button"
          :class="['cmp-dot', { 'cmp-dot--on': inCompare(c.id) }]"
          :aria-pressed="inCompare(c.id)"
          :aria-label="`${t('lightbox.comparePick')} ${c.title || c.name}`"
          :title="`${c.title || c.name} (${c.width}×${c.height})`"
          :style="{
            backgroundImage: `url(/t/${c.id}_sm.webp)`,
            backgroundColor: c.dominant_color || 'var(--surface-sunken)',
          }"
          @click="toggleCompare(c.id)"
        />
        <button
          v-if="compareOn && compareItems.length === 2"
          type="button"
          :class="['cmp-clear', { 'cmp-clear--on': compareSplit }]"
          :aria-pressed="compareSplit"
          @click="compareSplit = !compareSplit"
        >
          {{ compareSplit ? t('lightbox.compareSide') : t('lightbox.compareSplit') }}
        </button>
        <button
          v-if="compareOn"
          type="button"
          class="cmp-clear"
          @click="compareIds = []; compareSplit = false"
        >
          {{ t('lightbox.compareClear') }}
        </button>
      </div>
    </div>

    <!-- 信息面板：默认收起，纯图优先 -->
    <aside v-if="infoOpen" class="lightbox__panel" :aria-label="t('lightbox.info')">
      <button
        type="button"
        class="panel__close"
        :aria-label="t('common.close')"
        @click="infoOpen = false"
      >
        ×
      </button>
      <div class="panel__head">
        <h2 class="panel__title">{{ item.title || item.name }}</h2>
        <button
          v-if="!editing"
          type="button"
          class="panel__edit-btn"
          @click="startEdit"
        >
          {{ t('lightbox.edit') }}
        </button>
      </div>

      <!-- 行内编辑表单 -->
      <form
        v-if="editing"
        class="panel__form"
        @submit.prevent="saveEdit"
        @keydown.ctrl.enter.prevent="saveEdit"
        @keydown.meta.enter.prevent="saveEdit"
      >
        <label class="panel__field">
          <span>{{ t('upload.fieldTitle') }}</span>
          <input v-model="editTitle" type="text" maxlength="200" />
        </label>
        <label class="panel__field">
          <span>{{ t('upload.fieldTags') }}</span>
          <input v-model="editTags" type="text" :placeholder="t('upload.tagsPlaceholder')" />
        </label>
        <label class="panel__field">
          <span>{{ t('lightbox.notes') }}</span>
          <textarea v-model="editNotes" rows="2" :placeholder="t('lightbox.notesPlaceholder')" />
        </label>
        <p class="panel__edit-hint">{{ t('lightbox.editHint') }}</p>
        <p v-if="editError" class="panel__err">{{ editError }}</p>
        <div class="panel__form-actions">
          <button type="button" class="panel__btn" @click="editing = false">{{ t('common.cancel') }}</button>
          <button type="submit" class="panel__btn panel__btn--primary" :disabled="editSaving">
            {{ t('lightbox.save') }}
          </button>
        </div>
      </form>

      <p v-if="!editing && item.notes" class="panel__notes">{{ item.notes }}</p>

      <dl class="panel__rows">
        <div v-if="spec" class="panel__row">
          <dt>{{ t('lightbox.spec') }}</dt>
          <dd class="mono">{{ spec }}</dd>
        </div>
        <div v-if="item.author" class="panel__row">
          <dt>{{ t('lightbox.author') }}</dt>
          <dd>{{ item.author }}</dd>
        </div>
        <div class="panel__row">
          <dt>{{ t('lightbox.added') }}</dt>
          <dd class="mono">{{ formatDate(item.ts) }}</dd>
        </div>
        <div v-if="item.views || item.downloads" class="panel__row">
          <dt>{{ t('lightbox.heat') }}</dt>
          <dd class="mono">
            {{ t('lightbox.views', { count: formatNumber(item.views || 0) }) }} ·
            {{ t('lightbox.downloads', { count: formatNumber(item.downloads || 0) }) }}
          </dd>
        </div>
        <div v-if="item.source" class="panel__row">
          <dt>{{ t('lightbox.source') }}</dt>
          <dd class="panel__source">
            <a :href="item.source" target="_blank" rel="noopener noreferrer nofollow" :title="item.source">
              {{ formatSource(item.source) }} <span aria-hidden="true">↗</span>
            </a>
          </dd>
        </div>
        <div v-if="item.credit || item.license" class="panel__row">
          <dt>{{ t('lightbox.license') }}</dt>
          <dd>{{ item.license || '—' }}<template v-if="item.credit"> · {{ item.credit }}</template></dd>
        </div>
        <div v-for="row in exifRows" :key="row.label" class="panel__row">
          <dt>{{ row.label }}</dt>
          <dd class="mono">{{ row.value }}</dd>
        </div>
      </dl>

      <div v-if="userTags(item.tags).length" class="panel__tags-wrap">
        <div class="panel__tags">
          <button
            v-for="tag in userTags(item.tags)"
            :key="tag"
            type="button"
            class="panel__tag"
            :aria-label="`${t('lightbox.filterTag')} ${tag}`"
            @click="filterByTag(tag)"
          >
            {{ tag }}
          </button>
        </div>
        <button
          type="button"
          class="panel__copy-tags"
          @click="copyTags"
        >
          {{ copied === 'tags' ? t('lightbox.copied') : t('lightbox.copyTags') }}
        </button>
      </div>

      <div v-if="palette.length" class="panel__palette">
        <span class="panel__label">{{ t('lightbox.palette') }}</span>
        <div class="panel__swatches">
          <button
            v-for="c in palette"
            :key="c"
            type="button"
            class="swatch"
            :style="{ background: c }"
            :aria-label="`${t('lightbox.copyColor')} ${c}`"
            @click="copyColor(c)"
          >
            <span class="swatch__hex mono">{{ copied === `hex:${c}` ? t('lightbox.copied') : c }}</span>
          </button>
        </div>
        <button
          type="button"
          class="panel__link"
          @click="filterByColor(palette[0])"
        >
          {{ t('lightbox.filterColor') }}
        </button>
      </div>

      <div v-if="similarItems.length" class="panel__similar">
        <span class="panel__label">{{ t('lightbox.similar') }}</span>
        <div class="panel__sim-grid">
          <a
            v-for="sim in similarItems"
            :key="sim.id"
            :href="sim.slug ? `/a/${sim.slug}-${sim.id.slice(0, 8)}` : `/s/${sim.id}`"
            class="panel__sim-item"
            :title="sim.title || sim.name"
            @click.prevent="emit('select-item', sim)"
          >
            <img
              :src="sim.kind === 'video' ? `/t/${sim.id}.jpg` : `/t/${sim.id}_sm.webp`"
              :alt="sim.title || sim.name"
              loading="lazy"
              @error="onThumbError($event, sim)"
            />
          </a>
        </div>
      </div>
    </aside>

    <!-- 胶片快速跳转条（快捷键 F 显隐） -->
    <nav
      v-if="filmstripOpen && (candidates?.length ?? 0) > 1 && !compareOn && !chromeHidden"
      :class="['lightbox__filmstrip', { 'lightbox__filmstrip--shifted': infoOpen }]"
      :aria-label="t('lightbox.filmstrip')"
    >
      <button
        v-for="c in candidates"
        :key="c.id"
        type="button"
        :class="['lb-film', { 'lb-film--cur': c.id === item.id }]"
        :aria-current="c.id === item.id"
        :title="c.title || c.name"
        @click="emit('select-item', c)"
      >
        <img
          :src="c.kind === 'video' ? `/t/${c.id}.jpg` : `/t/${c.id}_sm.webp`"
          alt=""
          loading="lazy"
          @error="onThumbError($event, c)"
        />
        <span v-if="c.kind === 'video'" class="lb-film__vid" aria-hidden="true">▶</span>
      </button>
    </nav>

    <!-- 纯净看图恢复角标 -->
    <button
      v-if="chromeHidden"
      type="button"
      class="lightbox__restore"
      :aria-label="t('lightbox.showChrome')"
      :title="`${t('lightbox.showChrome')} (H)`"
      @click="chromeHidden = false"
    >
      ◎ {{ t('lightbox.showChrome') }}
    </button>

    <!-- 悬浮控制条 -->
    <div v-show="!chromeHidden" class="lightbox__bar">
      <div class="lightbox__info">
        <span class="lightbox__title">
          {{ item.title || item.name }}
          <!-- 授权状态（C-11）：不可商用必须有明确提示 -->
          <span v-if="item.commercial_ok === 0" class="badge-personal">
            {{ t('license.personalOnly') }}
          </span>
          <span v-else-if="item.license" class="badge-license mono">{{ item.license }}</span>
        </span>
        <span v-if="spec" class="lightbox__spec mono">{{ spec }}</span>
        <span v-if="index && total" class="lightbox__index mono">{{ index }} / {{ total }}</span>
        <span v-if="item.credit" class="lightbox__credit">{{ item.credit }}</span>
      </div>

      <div class="lightbox__controls">
        <button
          v-if="item.kind === 'image'"
          type="button"
          class="lb-btn lb-rare"
          :class="{ 'lb-btn--on': slideshow.on }"
          :aria-pressed="slideshow.on"
          :aria-label="t('lightbox.slideshowToggle')"
          :title="`${t('lightbox.slideshowToggle')} (Space)`"
          @click="toggleSlideshow"
        >
          ▶
        </button>
        <select
          v-if="item.kind === 'image'"
          class="lb-select lb-rare mono"
          :value="slideshow.ms"
          :aria-label="t('lightbox.slideshowInterval')"
          @change="setInterval_(Number(($event.target as HTMLSelectElement).value))"
        >
          <option :value="3000">3s</option>
          <option :value="5000">5s</option>
          <option :value="8000">8s</option>
        </select>

        <!-- 视频倍速 / 循环 / 画中画 -->
        <template v-if="item.kind === 'video'">
          <select
            class="lb-select lb-rare mono"
            :value="videoSpeed"
            :aria-label="t('lightbox.speed')"
            :title="t('lightbox.speed')"
            @change="setVideoSpeed(Number(($event.target as HTMLSelectElement).value))"
          >
            <option :value="0.5">0.5×</option>
            <option :value="1">1×</option>
            <option :value="1.5">1.5×</option>
            <option :value="2">2×</option>
          </select>
          <button
            type="button"
            class="lb-btn"
            :class="{ 'lb-btn--on': videoLoop }"
            :aria-pressed="videoLoop"
            :aria-label="t('lightbox.loop')"
            :title="t('lightbox.loop')"
            @click="toggleVideoLoop"
          >
            ↻
          </button>
          <button
            type="button"
            class="lb-btn"
            :class="{ 'lb-btn--on': videoMuted }"
            :aria-pressed="videoMuted"
            :aria-label="t('lightbox.mute')"
            :title="`${t('lightbox.mute')} (M)`"
            @click="toggleVideoMute"
          >
            {{ videoMuted ? '🔇' : '🔊' }}
          </button>
          <button
            v-if="pipSupported"
            type="button"
            class="lb-btn lb-rare"
            :aria-label="t('lightbox.pip')"
            :title="t('lightbox.pip')"
            @click="togglePip"
          >
            ⧉
          </button>
        </template>

        <button
          type="button"
          class="lb-btn"
          :class="{ 'lb-btn--liked': liked }"
          :aria-pressed="Boolean(liked)"
          :aria-label="liked ? t('lightbox.unlike') : t('lightbox.like')"
          :title="liked ? t('lightbox.unlike') : t('lightbox.like')"
          @click="$emit('toggle-like', item.id)"
        >
          {{ liked ? '♥' : '♡' }}
        </button>
        <button
          v-if="(candidates?.length ?? 0) > 1 && !compareOn"
          type="button"
          class="lb-btn"
          :class="{ 'lb-btn--on': filmstripOpen }"
          :aria-pressed="filmstripOpen"
          :aria-label="t('lightbox.filmstripToggle')"
          :title="`${t('lightbox.filmstripToggle')} (F)`"
          @click="filmstripOpen = !filmstripOpen"
        >
          ▤
        </button>
        <button
          type="button"
          class="lb-btn"
          :class="{ 'lb-btn--on': infoOpen }"
          :aria-pressed="infoOpen"
          :aria-label="t('lightbox.info')"
          :title="`${t('lightbox.info')} (I)`"
          @click="infoOpen = !infoOpen; if (infoOpen) focusPanel()"
        >
          i
        </button>
        <button
          type="button"
          class="lb-btn"
          :class="{ 'lb-btn--ok': copied === 'link' }"
          :aria-label="t('lightbox.copyShare')"
          :title="`${t('lightbox.copyShare')} (C)`"
          @click="copyLink"
        >
          {{ copied === 'link' ? '✓' : '⧉' }}
        </button>
        <button
          v-if="item.kind === 'image'"
          type="button"
          class="lb-btn lb-btn--bg"
          :class="{ 'lb-btn--on': stageBg !== 'dark' }"
          :aria-label="`${t('lightbox.stageBg')} (${stageBgLabel})`"
          :title="`${t('lightbox.stageBg')} · ${stageBgLabel} (B)`"
          @click="cycleStageBg"
        >
          ◐
        </button>
        <button
          type="button"
          class="lb-btn"
          :aria-label="t('lightbox.hideChrome')"
          :title="`${t('lightbox.hideChrome')} (H)`"
          @click="chromeHidden = true"
        >
          ◎
        </button>
        <button
          type="button"
          class="lb-btn lb-rare"
          :aria-label="t('lightbox.help')"
          :title="`${t('lightbox.help')} (?)`"
          @click="openHelp"
        >?</button>

        <span class="lightbox__divider" aria-hidden="true" />

        <button
          type="button"
          class="lb-btn lb-nav"
          :disabled="!hasPrev"
          :aria-label="t('lightbox.prev')"
          :title="`${t('lightbox.prev')} (←)`"
          @click="$emit('prev')"
        >
          ←
        </button>
        <button
          v-if="item.kind === 'image'"
          type="button"
          class="lightbox__zoom mono"
          :class="{ 'lightbox__zoom--active': scale > 1.05 }"
          :title="scale > 1.05 ? t('lightbox.fit') : t('lightbox.actualSize')"
          :aria-label="scale > 1.05 ? t('lightbox.fit') : t('lightbox.actualSize')"
          @click="toggleActualSize"
        >
          {{ scale > 1.05 ? `${Math.round(scale * 100)}%` : '1:1' }}
        </button>
        <button
          type="button"
          class="lb-btn lb-nav"
          :disabled="!hasNext"
          :aria-label="t('lightbox.next')"
          :title="`${t('lightbox.next')} (→)`"
          @click="$emit('next')"
        >
          →
        </button>
        <a
          :href="downloadUrl"
          download
          class="lb-btn"
          :aria-label="t('lightbox.download')"
          :title="`${t('lightbox.download')} (D)`"
          @click="track('download', { itemId: item.id })"
        >↓</a>
        <button
          type="button"
          class="lb-btn"
          :aria-label="t('lightbox.close')"
          :title="`${t('lightbox.close')} (Esc)`"
          @click="close"
        >✕</button>
      </div>
    </div>

    <!-- 复制反馈：aria-live 让屏幕阅读器也能听到 -->
    <p class="sr-only" aria-live="polite">
      {{ copied === 'copy-failed' ? t('lightbox.copyFailed') : copied ? t('lightbox.copiedToast') : '' }}
    </p>

    <!-- 快捷键帮助浮层 -->
    <dialog ref="helpRef" class="help" :aria-label="t('lightbox.help')" @close="helpOpen = false">
      <h2 class="help__title">{{ t('lightbox.help') }}</h2>
      <ul class="help__list">
        <li v-for="s in shortcuts" :key="s.key">
          <kbd class="help__key mono">{{ s.key }}</kbd>
          <span>{{ s.desc }}</span>
        </li>
      </ul>
      <button type="button" class="help__close" @click="closeHelp">{{ t('common.close') }}</button>
    </dialog>
  </dialog>
</template>

<style scoped>
.lightbox {
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  max-width: 100vw;
  max-height: 100vh;
  max-height: 100dvh;
  padding: 0;
  border: none;
  background: transparent;
  color: #faf8f5;
  /* dialog 的 top layer 只盖得住同级 stacking context，
     sticky 顶栏（z-index 40）仍在视口内可见，需显式提高层级 */
  z-index: var(--p-z-lightbox);
}

.lightbox::backdrop {
  /* 灯箱用深底，让图片成为唯一焦点——这是纸感主题下唯一允许的深色面 */
  background: rgba(18, 16, 13, 0.94);
  /* 遮住包含 sticky 顶栏的整个视口 */
  z-index: var(--p-z-lightbox);
}

.lightbox__stage {
  position: absolute;
  inset: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  place-items: center;
  padding: var(--p-space-5) var(--p-space-6) 88px;
  overflow: hidden;
  transition: padding-right var(--p-dur-base) var(--p-ease-out);
  /* 灯箱自身的进入动画：替代无法用于 dialog 的共享元素转场 */
  animation: lightbox-in var(--p-dur-base) var(--p-ease-out);
}

/* 看图背景底色切换：适配透明图与浅/深线稿 */
.lightbox__stage--bg-paper {
  background: #faf8f5;
}

.lightbox__stage--bg-grid {
  background-color: #d9d5ce;
  background-image:
    linear-gradient(45deg, #c4bfb7 25%, transparent 25%),
    linear-gradient(-45deg, #c4bfb7 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #c4bfb7 75%),
    linear-gradient(-45deg, transparent 75%, #c4bfb7 75%);
  background-size: 20px 20px;
  background-position: 0 0, 0 10px, 10px -10px, -10px 0;
}

.lightbox__stage--bg-paper .lightbox__img,
.lightbox__stage--bg-grid .lightbox__img {
  border: 1px solid rgba(26, 24, 21, 0.12);
  box-shadow: 0 6px 28px rgba(26, 24, 21, 0.14);
}

.lightbox__stage--bg-paper .lightbox__spinner,
.lightbox__stage--bg-grid .lightbox__spinner {
  border-color: rgba(26, 24, 21, 0.22);
  border-top-color: var(--accent);
}

.lightbox__split-box {
  position: relative;
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  overflow: hidden;
}

.lightbox__split-img {
  position: absolute;
  max-width: 100%;
  max-height: 100%;
  pointer-events: none;
}

.lightbox__split-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--p-accent-500);
  box-shadow: 0 0 0 1px rgba(18, 16, 13, 0.45);
  transform: translateX(-50%);
  pointer-events: none;
  z-index: 3;
}

.lightbox__split-knob {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 30px;
  height: 30px;
  border-radius: var(--p-radius-full);
  background: var(--p-accent-600);
  color: #faf8f5;
  border: 2px solid #faf8f5;
  display: grid;
  place-items: center;
  font-size: 0.75rem;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.4);
}

.lightbox__split-range {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: ew-resize;
  z-index: 4;
}

.lightbox__split-tag {
  position: absolute;
  bottom: var(--p-space-3);
  z-index: 2;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 8px;
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.72);
  color: #faf8f5;
  font-size: 0.6875rem;
  pointer-events: none;
}

.lightbox__split-tag--left {
  left: var(--p-space-3);
}

.lightbox__split-tag--right {
  right: var(--p-space-3);
}

.cmp-clear--on {
  background: var(--p-accent-600);
}

/* 有顶部对比选择条时让出安全高度，防止长竖图顶部被遮住 */
.lightbox__stage--has-compare {
  padding-top: 68px;
}

.lightbox__stage--with-film {
  padding-bottom: 148px;
}

/* 桌面端打开信息面板时收缩舞台右侧，图片自动重新居中适配 */
@media (min-width: 760px) {
  .lightbox__stage--with-panel {
    padding-right: calc(min(360px, 88vw) + var(--p-space-5));
  }
}

/* 对比模式：2 项两列，3–4 项两列两行，铺满舞台且不纵向溢出 */
.lightbox__stage--compare {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: minmax(0, 1fr);
  align-items: center;
  gap: var(--p-space-4);
  padding-top: 68px;
}

.lightbox__stage--compare-grid {
  grid-template-rows: repeat(2, minmax(0, 1fr));
}

.lightbox__frame {
  margin: 0;
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  place-items: center;
  min-width: 0;
  min-height: 0;
}

.lightbox__stage--compare .lightbox__frame {
  grid-template-rows: minmax(0, 1fr) auto;
}

@keyframes lightbox-in {
  from {
    opacity: 0;
    transform: scale(0.985);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .lightbox__stage {
    animation: none;
  }
  .lightbox__img {
    transition: none;
  }
}

.lightbox__img,
.lightbox__video {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
  transition: transform var(--p-dur-base) var(--p-ease-out);
  /* 缩放锚点固定为居中，配合 useZoomPan 的中心坐标换算 */
  transform-origin: center center;
}

.lightbox__img {
  cursor: zoom-in;
  user-select: none;
  opacity: 0.45;
  transition:
    transform var(--p-dur-base) var(--p-ease-out),
    opacity var(--p-dur-fast) var(--p-ease-out);
}

.lightbox__video-error {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  z-index: 6;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: min(90%, 420px);
  padding: 18px 22px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(18, 16, 13, 0.84);
  color: #faf8f5;
  text-align: center;
}

.lightbox__video-error p {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.55;
}

.lightbox__video-error .lb-btn {
  color: #faf8f5;
  border-color: rgba(255, 255, 255, 0.28);
  text-decoration: none;
}

.lightbox__img--ready {
  opacity: 1;
}

.lightbox__ss-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--accent);
  transform-origin: left center;
  animation: ss-progress linear forwards;
  z-index: 4;
  pointer-events: none;
}

@keyframes ss-progress {
  from {
    transform: scaleX(0);
  }
  to {
    transform: scaleX(1);
  }
}

.lightbox__spinner {
  position: absolute;
  width: 28px;
  height: 28px;
  border-radius: var(--p-radius-full);
  border: 2px solid rgba(250, 248, 245, 0.22);
  border-top-color: var(--accent);
  animation: lb-spin 700ms linear infinite;
  pointer-events: none;
  z-index: 2;
}

@keyframes lb-spin {
  to {
    transform: rotate(360deg);
  }
}

.lightbox__zoom-pill {
  position: absolute;
  left: var(--p-space-4);
  bottom: 84px;
  z-index: 3;
  padding: 4px var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.72);
  border: 1px solid rgba(250, 248, 245, 0.2);
  color: rgba(250, 248, 245, 0.9);
  font-size: 0.75rem;
  backdrop-filter: blur(6px);
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.lightbox__zoom-pill:hover {
  background: rgba(18, 16, 13, 0.9);
}

.lightbox__img--zoomed {
  cursor: grab;
}

.lightbox__img--dragging {
  cursor: grabbing;
  transition: none;
}

/* 舞台左右悬浮切图箭头 */
.stage-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
  width: 44px;
  height: 44px;
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.45);
  color: #faf8f5;
  font-size: 1.5rem;
  line-height: 1;
  display: grid;
  place-items: center;
  backdrop-filter: blur(6px);
  opacity: 0.45;
  transition:
    opacity var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out),
    right var(--p-dur-base) var(--p-ease-out);
}

.stage-nav:hover,
.stage-nav:focus-visible {
  opacity: 1;
  background: rgba(18, 16, 13, 0.78);
}

.stage-nav--prev {
  left: var(--p-space-4);
}

.stage-nav--next {
  right: var(--p-space-4);
}

@media (min-width: 760px) {
  .stage-nav--shifted {
    right: calc(min(360px, 88vw) + var(--p-space-4));
  }
}

@media (max-width: 640px) {
  /* 手机上保留大尺寸左右箭头：比隐藏后只靠滑动更易发现 */
  .stage-nav {
    display: grid;
    width: 44px;
    height: 44px;
    opacity: 0.72;
  }

  .stage-nav--prev {
    left: max(var(--p-space-2), env(safe-area-inset-left, 0px));
  }

  .stage-nav--next {
    right: max(var(--p-space-2), env(safe-area-inset-right, 0px));
  }

  .stage-nav--info-open {
    display: none;
  }
}

@media (hover: none) {
  /* 触屏精简低频控件（快捷键/画中画/连播与倍速等），底部栏不换行 */
  .lb-rare,
  .lb-nav {
    display: none;
  }

  .lb-btn {
    min-width: 36px;
    min-height: 36px;
  }

  .lightbox__controls {
    gap: 2px;
  }
}

.lightbox__cap {
  margin-top: var(--p-space-2);
  padding: 2px var(--p-space-2);
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.72);
  color: #faf8f5;
  font-size: var(--p-step--1);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 对比选择条：底部居中，不遮挡图片主体 */
.lightbox__compare {
  position: absolute;
  left: 50%;
  top: var(--p-space-4);
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  max-width: calc(100vw - var(--p-space-5));
  overflow-x: auto;
  scrollbar-width: none;
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.72);
  backdrop-filter: blur(6px);
}

.lightbox__compare::-webkit-scrollbar {
  display: none;
}

.lightbox__compare-label {
  font-size: var(--p-step--1);
  opacity: 0.75;
  white-space: nowrap;
}

.cmp-dot {
  width: 34px;
  height: 34px;
  border-radius: var(--p-radius-sm);
  background-size: cover;
  background-position: center;
  border: 1px solid rgba(250, 248, 245, 0.35);
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.cmp-dot--on {
  border: 2px solid var(--p-accent-500);
}

.cmp-clear {
  font-size: var(--p-step--1);
  padding: 0 var(--p-space-2);
  min-height: 24px;
  border-radius: var(--p-radius-full);
  background: rgba(250, 248, 245, 0.14);
  color: inherit;
}

/* 信息面板：右侧抽屉 */
.lightbox__panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(360px, 88vw);
  padding: var(--p-space-6) var(--p-space-5) 112px;
  overflow-y: auto;
  background: rgba(18, 16, 13, 0.88);
  backdrop-filter: blur(10px);
  animation: panel-in var(--p-dur-base) var(--p-ease-out);
}

@keyframes panel-in {
  from {
    transform: translateX(12px);
    opacity: 0;
  }
  to {
    transform: none;
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lightbox__panel {
    animation: none;
  }
}

.panel__close {
  position: absolute;
  top: var(--p-space-2);
  right: var(--p-space-2);
  min-width: 40px;
  min-height: 40px;
  border-radius: var(--p-radius-full);
  color: inherit;
  font-size: 1.25rem;
  line-height: 1;
}

.panel__close:hover {
  background: rgba(250, 248, 245, 0.14);
}

.panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--p-space-2);
  margin: 0 0 var(--p-space-4);
  padding-right: 28px;
}

.panel__title {
  margin: 0;
  color: inherit;
  font-size: var(--p-step-1);
  font-weight: 600;
  line-height: 1.3;
  word-break: break-word;
}

.panel__edit-btn {
  flex-shrink: 0;
  font-size: var(--p-step--1);
  padding: 2px var(--p-space-2);
  border-radius: var(--p-radius-sm);
  border: 1px solid rgba(250, 248, 245, 0.28);
  color: inherit;
}

.panel__edit-btn:hover {
  background: rgba(250, 248, 245, 0.14);
}

.panel__form {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
  margin-bottom: var(--p-space-4);
  padding-bottom: var(--p-space-4);
  border-bottom: 1px solid rgba(250, 248, 245, 0.16);
}

.panel__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--p-step--1);
}

.panel__field span {
  opacity: 0.7;
}

.panel__field input,
.panel__field textarea {
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--p-radius-sm);
  border: 1px solid rgba(250, 248, 245, 0.24);
  background: rgba(250, 248, 245, 0.08);
  color: #faf8f5;
  font: inherit;
}

.panel__edit-hint {
  font-size: 0.6875rem;
  opacity: 0.55;
  margin: 0;
}

.panel__notes {
  margin: 0 0 var(--p-space-4);
  padding: var(--p-space-2) var(--p-space-3);
  border-left: 2px solid var(--p-accent-500);
  background: rgba(250, 248, 245, 0.06);
  border-radius: 0 var(--p-radius-sm) var(--p-radius-sm) 0;
  font-size: var(--p-step--1);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.panel__err {
  color: #e87a6e;
  font-size: var(--p-step--1);
}

.panel__form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--p-space-2);
}

.panel__btn {
  min-height: 28px;
  padding: 0 var(--p-space-3);
  border-radius: var(--p-radius-sm);
  border: 1px solid rgba(250, 248, 245, 0.24);
  font-size: var(--p-step--1);
}

.panel__btn--primary {
  background: var(--p-accent-600);
  border-color: var(--p-accent-600);
}

.panel__similar {
  margin-top: var(--p-space-5);
}

.panel__sim-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--p-space-2);
}

.panel__sim-item {
  display: block;
  aspect-ratio: 1;
  border-radius: var(--p-radius-sm);
  overflow: hidden;
  background: rgba(250, 248, 245, 0.08);
}

.panel__sim-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform var(--p-dur-base) var(--p-ease-out);
}

.panel__sim-item:hover img {
  transform: scale(1.06);
}

.panel__rows {
  margin: 0;
  display: grid;
  gap: var(--p-space-2);
}

.panel__row {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: var(--p-space-2);
  font-size: var(--p-step--1);
}

.panel__row dt {
  opacity: 0.6;
}

.panel__row dd {
  margin: 0;
  word-break: break-word;
}

.panel__source a {
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.panel__tags-wrap {
  margin-top: var(--p-space-4);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--p-space-2);
}

.panel__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-1);
}

.panel__copy-tags {
  font-size: 0.6875rem;
  opacity: 0.68;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.panel__copy-tags:hover {
  opacity: 1;
}

.panel__tag {
  padding: 2px var(--p-space-2);
  font-size: var(--p-step--1);
  border-radius: var(--p-radius-sm);
  background: rgba(250, 248, 245, 0.14);
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.panel__tag:hover {
  background: rgba(250, 248, 245, 0.26);
}

.panel__palette {
  margin-top: var(--p-space-5);
}

.panel__label {
  display: block;
  font-size: var(--p-step--1);
  opacity: 0.6;
  margin-bottom: var(--p-space-2);
}

.panel__swatches {
  display: flex;
  gap: var(--p-space-2);
  flex-wrap: wrap;
}

.swatch {
  position: relative;
  width: 56px;
  height: 40px;
  border-radius: var(--p-radius-sm);
  border: 1px solid rgba(250, 248, 245, 0.28);
  transition:
    transform var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out);
}

.swatch:hover {
  transform: translateY(-2px);
  border-color: rgba(250, 248, 245, 0.72);
}

.swatch__hex {
  position: absolute;
  inset: auto 0 0 0;
  font-size: 0.625rem;
  padding: 1px 2px;
  background: rgba(18, 16, 13, 0.72);
  color: #faf8f5;
}

.panel__link {
  margin-top: var(--p-space-3);
  font-size: var(--p-step--1);
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
  min-height: 24px;
}

.lightbox__filmstrip {
  position: absolute;
  left: 50%;
  bottom: 74px;
  transform: translateX(-50%);
  z-index: 3;
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
  max-width: min(680px, 92vw);
  padding: 5px 8px;
  border-radius: var(--p-radius-md);
  background: rgba(18, 16, 13, 0.76);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(250, 248, 245, 0.14);
  overflow-x: auto;
  scrollbar-width: none;
  transition: left var(--p-dur-base) var(--p-ease-out);
}

.lightbox__filmstrip::-webkit-scrollbar {
  display: none;
}

@media (min-width: 760px) {
  .lightbox__filmstrip--shifted {
    left: calc((100vw - min(360px, 88vw)) / 2);
    max-width: min(680px, calc(100vw - min(360px, 88vw) - var(--p-space-6) * 2));
  }
}

.lb-film {
  position: relative;
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border-radius: var(--p-radius-sm);
  overflow: hidden;
  border: 2px solid transparent;
  opacity: 0.62;
  transition:
    opacity var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out),
    transform var(--p-dur-fast) var(--p-ease-out);
}

.lb-film__vid {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 3px;
  border-radius: var(--p-radius-sm);
  background: rgba(18, 16, 13, 0.78);
  color: #faf8f5;
  font-size: 0.5rem;
  line-height: 1.3;
  pointer-events: none;
}

.lb-film:hover {
  opacity: 0.95;
  transform: translateY(-1px);
}

.lb-film--cur {
  border-color: var(--p-accent-500);
  opacity: 1;
}

.lb-film img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.lightbox__restore {
  position: absolute;
  right: var(--p-space-4);
  bottom: var(--p-space-4);
  z-index: 4;
  padding: 4px var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.56);
  border: 1px solid rgba(250, 248, 245, 0.22);
  color: rgba(250, 248, 245, 0.85);
  font-size: var(--p-step--1);
  backdrop-filter: blur(6px);
  opacity: 0.55;
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.lightbox__restore:hover {
  opacity: 1;
}

.lightbox__bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-4);
  padding: var(--p-space-4) var(--p-space-5);
  background: linear-gradient(to top, rgba(18, 16, 13, 0.9), transparent);
}

.lightbox__info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.lightbox__title {
  font-size: var(--p-step-0);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lightbox__spec {
  font-size: var(--p-step--1);
  opacity: 0.75;
}

.lightbox__credit {
  font-size: var(--p-step--1);
  opacity: 0.6;
}

/* 授权徽标：角标形式，不抢画面但不可忽略 */
.badge-license,
.badge-personal {
  display: inline-block;
  margin-left: var(--p-space-2);
  padding: 0 6px;
  font-size: 0.6875rem;
  border-radius: var(--p-radius-sm);
  vertical-align: middle;
}

.badge-license {
  background: rgba(250, 248, 245, 0.16);
  color: #faf8f5;
}

.badge-personal {
  background: rgba(176, 74, 63, 0.9);
  color: #fff;
}

.lightbox__controls {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.lightbox__divider {
  width: 1px;
  height: 20px;
  margin: 0 var(--p-space-1);
  background: rgba(250, 248, 245, 0.24);
}

.lb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 目标尺寸 ≥24px（WCAG 2.5.8），实际给到 34px 更易点 */
  min-width: 34px;
  min-height: 34px;
  border-radius: var(--p-radius-md);
  color: inherit;
  font-size: 1rem;
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.lb-btn:hover:not(:disabled) {
  background: rgba(250, 248, 245, 0.14);
}

.lb-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.lb-btn--on {
  background: rgba(140, 106, 74, 0.55);
}

.lb-btn--ok {
  background: color-mix(in srgb, var(--success) 38%, transparent);
  color: #e8f0ea;
}

.lightbox__index {
  font-size: var(--p-step--1);
  opacity: 0.75;
  margin-right: var(--p-space-2);
}

.lb-btn--liked {
  color: #e87a6e;
  background: rgba(176, 74, 63, 0.22);
}

.lb-select {
  min-height: 28px;
  padding: 0 var(--p-space-1);
  font-size: var(--p-step--1);
  border-radius: var(--p-radius-md);
  background: rgba(250, 248, 245, 0.12);
  color: inherit;
  border: 1px solid rgba(250, 248, 245, 0.24);
}

.lb-select option {
  color: #1a1815;
}

.lightbox__zoom {
  font-size: var(--p-step--1);
  opacity: 0.85;
  min-width: 44px;
  min-height: 28px;
  padding: 0 var(--p-space-2);
  border-radius: var(--p-radius-md);
  text-align: center;
  background: rgba(250, 248, 245, 0.1);
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.lightbox__zoom:hover {
  background: rgba(250, 248, 245, 0.2);
}

.lightbox__zoom--active {
  background: rgba(140, 106, 74, 0.55);
  opacity: 1;
}

@media (max-width: 640px) {
  .lightbox__stage {
    padding: var(--p-space-4) var(--p-space-2) calc(112px + env(safe-area-inset-bottom, 0px));
  }
  .lightbox__stage--has-compare {
    padding-top: 62px;
  }
  .lightbox__filmstrip {
    bottom: calc(94px + env(safe-area-inset-bottom, 0px));
  }
  .lightbox__bar {
    flex-direction: column;
    align-items: stretch;
    gap: var(--p-space-2);
    padding: var(--p-space-3) var(--p-space-3);
    padding-bottom: calc(var(--p-space-2) + env(safe-area-inset-bottom, 0px));
  }
  .lightbox__controls {
    justify-content: center;
  }
  /* 手机上把标题与序号压成一行，规格/署名收进信息面板，底部操作条减负 */
  .lightbox__info {
    flex-direction: row;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 2px var(--p-space-2);
  }
  .lightbox__spec,
  .lightbox__credit {
    display: none;
  }
  .lightbox__index {
    margin-right: 0;
  }
  .lb-select {
    min-height: 32px;
  }
  /* 信息面板内的小字与标签在手机上补足可读/可点尺寸 */
  .panel__copy-tags {
    min-height: 32px;
    font-size: 0.75rem;
  }
  .panel__tag {
    min-height: 32px;
    display: inline-flex;
    align-items: center;
  }
  .swatch__hex {
    font-size: 0.75rem;
  }
  .lightbox__panel {
    padding-bottom: calc(148px + env(safe-area-inset-bottom, 0px));
  }
  .lightbox__divider {
    display: none;
  }
}

/* 快捷键帮助 */
.help {
  width: min(420px, 92vw);
  padding: var(--p-space-5);
  border-radius: var(--p-radius-lg);
  border: 1px solid var(--rule);
  background: var(--surface);
  color: var(--ink);
}

.help__title {
  margin: 0 0 var(--p-space-4);
  font-size: var(--p-step-0);
  font-weight: 600;
}

.help__list {
  list-style: none;
  margin: 0 0 var(--p-space-5);
  padding: 0;
  display: grid;
  gap: var(--p-space-2);
}

.help__list li {
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  font-size: var(--p-step--1);
}

.help__key {
  min-width: 68px;
  padding: 1px var(--p-space-2);
  border-radius: var(--p-radius-sm);
  background: var(--surface-sunken);
  text-align: center;
}

.help__close {
  min-height: 32px;
  padding: 0 var(--p-space-4);
  border-radius: var(--p-radius-md);
  border: 1px solid var(--rule);
}

/* 触屏精简低频控件：追加在基础按钮样式之后，避免被后续 display 规则覆盖 */
@media (hover: none) {
  .lb-btn.lb-rare,
  .lb-btn.lb-nav,
  .lb-select.lb-rare {
    display: none;
  }

  .lightbox__controls .lb-btn {
    min-width: 36px;
    min-height: 36px;
  }

  .lightbox__controls .lb-select,
  .lightbox__controls .lightbox__zoom {
    min-height: 36px;
  }

  .lightbox__controls {
    gap: 2px;
  }
}

</style>
