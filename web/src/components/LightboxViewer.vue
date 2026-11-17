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
import { useI18n } from '@/composables/useI18n'
import { copyText } from '@/composables/useClipboard'
import { useZoomPan } from '@/composables/useZoomPan'

const props = defineProps<{
  item: MediaItem
  hasPrev: boolean
  hasNext: boolean
  /** 同屏可对比的候选（通常为当前列表），用于挑选 2–4 项 */
  candidates?: MediaItem[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'prev'): void
  (e: 'next'): void
  /** 按主色筛选（对接 B-10 的 color 参数） */
  (e: 'filter-color', color: string): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const stageRef = ref<HTMLElement | null>(null)
const helpRef = ref<HTMLDialogElement | null>(null)
const { t, formatBytes, formatDate } = useI18n()

const {
  scale,
  style: zoomStyle,
  reset: resetZoom,
  zoomBy,
  bind: bindZoom,
  unbind: unbindZoom,
} = useZoomPan(stageRef)

/** 信息面板展开状态：默认收起，纯图优先 */
const infoOpen = ref(false)
const helpOpen = ref(false)
/** 复制反馈：'link' | 'hex:<color>' | null，1.6s 后自动清除 */
const copied = ref<string | null>(null)
/** 对比模式：从候选里选出的 2–4 项 id（含当前项） */
const compareIds = ref<string[]>([])
/** 连播状态与间隔 */
const slideshow = ref<{ on: boolean; ms: number }>({ on: false, ms: 5000 })
let slideshowTimer: number | null = null
let copyTimer: number | null = null

const mediaUrl = computed(() => `/f/${props.item.file}`)
const previewUrl = computed(() =>
  props.item.thumb ? `/t/${props.item.id}_lg.webp` : `/f/${props.item.file}`,
)

/** 固定浮点误差，保证对比模式下两图 transform 数值完全一致 */
const priceScale = computed(() => Number(scale.value.toFixed(3)))

const spec = computed(() => {
  const parts: string[] = []
  if (props.item.width && props.item.height) {
    parts.push(`${props.item.width}×${props.item.height}`)
  }
  if (props.item.ext) parts.push(props.item.ext.toUpperCase())
  if (props.item.size) parts.push(formatBytes(props.item.size))
  if (props.item.duration) parts.push(`${props.item.duration.toFixed(1)}s`)
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

/** 对比候选：限额 8 个，覆盖当前列表附近即可，避免长列表渲染开销 */
const compareChoices = computed(() =>
  (props.candidates ?? []).slice(0, 8),
)

function toggleCompare(id: string) {
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
  slideshow.value = { ...slideshow.value, on: true }
  slideshowTimer = window.setInterval(() => {
    if (props.hasNext) emit('next')
    else stopSlideshow()
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

async function copyLink() {
  const url = new URL(mediaUrl.value, window.location.origin).toString()
  if (await copyText(url)) await flash('link')
}

async function copyColor(color: string) {
  if (await copyText(color.toUpperCase())) await flash(`hex:${color}`)
}

function filterByColor(color: string) {
  emit('filter-color', color)
  close()
}

function download() {
  const a = document.createElement('a')
  a.href = mediaUrl.value
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

function onKeydown(e: KeyboardEvent) {
  // 输入态与输入法组字期间不拦截（A-04 验收）
  if (isTypingTarget(e.target)) return
  if (e.isComposing) return

  switch (e.key) {
    case 'Escape':
      if (helpOpen.value) {
        closeHelp()
        return
      }
      close()
      break
    case 'ArrowLeft':
      if (props.hasPrev) emit('prev')
      break
    case 'ArrowRight':
      if (props.hasNext) emit('next')
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
    case 'i':
    case 'I':
      infoOpen.value = !infoOpen.value
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

function openHelp() {
  helpOpen.value = true
  nextTick(() => helpRef.value?.showModal())
}

function closeHelp() {
  helpRef.value?.close()
  helpOpen.value = false
}

const shortcuts = computed(() => [
  { key: '← / →', desc: t('shortcut.switch') },
  { key: '+ / -', desc: t('shortcut.zoom') },
  { key: '0', desc: t('shortcut.reset') },
  { key: 'I', desc: t('shortcut.info') },
  { key: 'D', desc: t('shortcut.download') },
  { key: 'C', desc: t('shortcut.copy') },
  { key: 'Space', desc: t('shortcut.slideshow') },
  { key: 'Esc', desc: t('shortcut.close') },
  { key: '?', desc: t('shortcut.help') },
])

// 切换条目时复位视图状态
watch(
  () => props.item.id,
  () => {
    resetZoom()
    compareIds.value = []
  },
)

onMounted(() => {
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
  window.removeEventListener('keydown', onKeydown)
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
    @close="close"
    @click="($event.target as HTMLElement).tagName === 'DIALOG' && close()"
  >
    <!-- 舞台：对比模式为网格，单图为单格 -->
    <div
      ref="stageRef"
      :class="['lightbox__stage', { 'lightbox__stage--compare': compareOn }]"
    >
      <template v-if="item.kind === 'image'">
        <figure v-for="it in compareOn ? compareItems : [item]" :key="it.id" class="lightbox__frame">
          <img
            :src="it.thumb ? `/t/${it.id}_lg.webp` : `/f/${it.file}`"
            :alt="it.title || it.name"
            class="lightbox__img"
            :style="compareOn ? { transform: `scale(${priceScale})` } : { ...zoomStyle, viewTransitionName: `media-${item.id}` }"
            @dblclick="resetZoom()"
          />
          <figcaption v-if="compareOn" class="lightbox__cap mono">
            {{ it.width }}×{{ it.height }} · {{ it.ext.toUpperCase() }}
          </figcaption>
        </figure>
      </template>
      <video
        v-else
        :src="mediaUrl"
        :poster="`/t/${item.id}.jpg`"
        controls
        autoplay
        playsinline
        class="lightbox__video"
      />

      <!-- 对比选择条：只在候选足够时出现 -->
      <div v-if="item.kind === 'image' && compareChoices.length >= 1" class="lightbox__compare">
        <span class="lightbox__compare-label">{{ t('lightbox.compare') }}</span>
        <button
          v-for="c in compareChoices"
          :key="c.id"
          type="button"
          :class="['cmp-dot', { 'cmp-dot--on': inCompare(c.id) }]"
          :aria-pressed="inCompare(c.id)"
          :aria-label="`${t('lightbox.comparePick')} ${c.title || c.name}`"
          :style="{ backgroundImage: `url(/t/${c.id}_sm.webp)` }"
          @click="toggleCompare(c.id)"
        />
        <button
          v-if="compareOn"
          type="button"
          class="cmp-clear"
          @click="compareIds = []"
        >
          {{ t('lightbox.compareClear') }}
        </button>
      </div>
    </div>

    <!-- 信息面板：默认收起，纯图优先 -->
    <aside v-if="infoOpen" class="lightbox__panel" :aria-label="t('lightbox.info')">
      <h2 class="panel__title">{{ item.title || item.name }}</h2>
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
        <div v-if="item.source" class="panel__row">
          <dt>{{ t('lightbox.source') }}</dt>
          <dd class="panel__source">
            <a :href="item.source" target="_blank" rel="noopener noreferrer nofollow">
              {{ item.source }}
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

      <div v-if="item.tags?.length" class="panel__tags">
        <span v-for="tag in item.tags" :key="tag" class="panel__tag">{{ tag }}</span>
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
    </aside>

    <!-- 悬浮控制条 -->
    <div class="lightbox__bar">
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
        <span v-if="item.credit" class="lightbox__credit">{{ item.credit }}</span>
      </div>

      <div class="lightbox__controls">
        <button
          v-if="item.kind === 'image'"
          type="button"
          class="lb-btn"
          :class="{ 'lb-btn--on': slideshow.on }"
          :aria-pressed="slideshow.on"
          :aria-label="t('lightbox.slideshowToggle')"
          @click="toggleSlideshow"
        >
          ▶
        </button>
        <select
          v-if="item.kind === 'image'"
          class="lb-select mono"
          :value="slideshow.ms"
          :aria-label="t('lightbox.slideshowInterval')"
          @change="setInterval_(Number(($event.target as HTMLSelectElement).value))"
        >
          <option :value="3000">3s</option>
          <option :value="5000">5s</option>
          <option :value="8000">8s</option>
        </select>

        <button
          type="button"
          class="lb-btn"
          :class="{ 'lb-btn--on': infoOpen }"
          :aria-pressed="infoOpen"
          :aria-label="t('lightbox.info')"
          @click="infoOpen = !infoOpen"
        >
          i
        </button>
        <button type="button" class="lb-btn" :aria-label="t('lightbox.copyLink')" @click="copyLink">
          {{ copied === 'link' ? '✓' : '⧉' }}
        </button>
        <button type="button" class="lb-btn" :aria-label="t('lightbox.help')" @click="openHelp">?</button>

        <span class="lightbox__divider" aria-hidden="true" />

        <button
          type="button"
          class="lb-btn"
          :disabled="!hasPrev"
          :aria-label="t('lightbox.prev')"
          @click="$emit('prev')"
        >
          ←
        </button>
        <span class="lightbox__zoom mono">{{ Math.round(scale * 100) }}%</span>
        <button
          type="button"
          class="lb-btn"
          :disabled="!hasNext"
          :aria-label="t('lightbox.next')"
          @click="$emit('next')"
        >
          →
        </button>
        <a :href="mediaUrl" download class="lb-btn" :aria-label="t('lightbox.download')">↓</a>
        <button type="button" class="lb-btn" :aria-label="t('lightbox.close')" @click="close">✕</button>
      </div>
    </div>

    <!-- 复制反馈：aria-live 让屏幕阅读器也能听到 -->
    <p class="sr-only" aria-live="polite">
      {{ copied ? t('lightbox.copiedToast') : '' }}
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
  max-width: 100vw;
  max-height: 100vh;
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
  place-items: center;
  padding: var(--p-space-8) var(--p-space-6) 96px;
  overflow: hidden;
  /* 灯箱自身的进入动画：替代无法用于 dialog 的共享元素转场 */
  animation: lightbox-in var(--p-dur-base) var(--p-ease-out);
}

/* 对比模式：2 项两列，3–4 项两列两行，铺满舞台 */
.lightbox__stage--compare {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: center;
  gap: var(--p-space-4);
  padding-top: var(--p-space-7);
}

.lightbox__frame {
  display: grid;
  place-items: center;
  min-width: 0;
  min-height: 0;
  height: 100%;
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
  object-fit: contain;
  transition: transform var(--p-dur-base) var(--p-ease-out);
  /* 缩放锚点固定为左上，配合 useZoomPan 的中心坐标换算 */
  transform-origin: center center;
}

.lightbox__img {
  cursor: grab;
}

.lightbox__cap {
  margin-top: var(--p-space-2);
  font-size: var(--p-step--1);
  opacity: 0.7;
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
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: rgba(18, 16, 13, 0.72);
  backdrop-filter: blur(6px);
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

.panel__title {
  margin: 0 0 var(--p-space-4);
  font-size: var(--p-step-1);
  font-weight: 600;
  line-height: 1.3;
  word-break: break-word;
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

.panel__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-1);
  margin-top: var(--p-space-4);
}

.panel__tag {
  padding: 2px var(--p-space-2);
  font-size: var(--p-step--1);
  border-radius: var(--p-radius-sm);
  background: rgba(250, 248, 245, 0.14);
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
  opacity: 0.7;
  min-width: 42px;
  text-align: center;
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
</style>
