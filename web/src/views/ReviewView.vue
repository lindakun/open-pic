<script setup lang="ts">
/**
 * 客户选片与批注页（REQ-V2-20 C-14）
 *
 * 设计约束：
 *   - 纯图预览布局：无侧栏，图片居中大图，底部胶片条
 *   - 标记（选中/待定/否决）与批注写回后端，刷新后保留
 *   - 快捷键与灯箱一致：←/→ 切换、1/2/3 标记、Esc 退出输入态
 *   - 375px 宽下不产生横向溢出
 *
 * 数据流：库主生成 /review/{token} 链接 → 客户打开即标记 → 库主在后台看汇总。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useTheme } from '@/composables/useTheme'
import { copyText } from '@/composables/useClipboard'
import type { MediaItem } from '@/api/types'

const route = useRoute()
const { t, locale, toggleLocale, formatBytes, formatDate } = useI18n()
const { mode: themeMode, resolved: resolvedTheme, cycle: cycleTheme } = useTheme()

const themeHint = computed(() => {
  if (themeMode.value === 'light') return t('site.themeLight')
  if (themeMode.value === 'dark') return t('site.themeDark')
  const active = resolvedTheme.value === 'dark' ? t('site.themeDarkShort') : t('site.themeLightShort')
  return `${t('site.themeAutoShort')} · ${active}`
})

const token = computed(() => String(route.params.token ?? ''))
const items = ref<MediaItem[]>([])
const linkTitle = ref('')
const linkMessage = ref('')
/** 选片链接到期时间（0 = 永久有效） */
const linkExpiresAt = ref(0)
const loading = ref(true)
const error = ref('')
const index = ref(0)
const saving = ref(false)
const savedAt = ref(0)
const summaryCopied = ref(false)
let summaryTimer: number | undefined

async function copySelectedSummary() {
  const picked = items.value.filter((it) => marks.value[it.id]?.state === 'selected')
  if (!picked.length) return
  const lines = picked.map((it, idx) => {
    const title = it.title || it.name
    const note = marks.value[it.id]?.note?.trim()
    return note ? `${idx + 1}. ${title} — ${note}` : `${idx + 1}. ${title}`
  })
  const ok = await copyText(lines.join('\n'))
  if (ok) {
    summaryCopied.value = true
    if (summaryTimer !== undefined) window.clearTimeout(summaryTimer)
    summaryTimer = window.setTimeout(() => {
      summaryCopied.value = false
    }, 2000)
  }
}
/** 点击图片放大检视细节 */
const zoomed = ref(false)
/** 标记后自动跳下一张（本地记忆，默认关闭以免打扰慢看） */
const autoNext = ref((() => {
  try {
    return localStorage.getItem('medialib.reviewAutoNext') === '1'
  } catch {
    return false
  }
})())
watch(autoNext, (v) => {
  try {
    localStorage.setItem('medialib.reviewAutoNext', v ? '1' : '0')
  } catch {
    // 忽略
  }
})

/** 胶片条过滤态 */
type FilmFilter = 'all' | 'unmarked' | 'selected' | 'pending' | 'rejected'
const filmFilter = ref<FilmFilter>('all')

/** 本地标记缓存：以 item_id 为键，避免每次切换都回查 */
type MarkState = 'selected' | 'pending' | 'rejected'
interface Mark {
  state: MarkState
  note: string
  reviewer: string
}
const marks = ref<Record<string, Mark>>({})
const noteDraft = ref('')
const saveError = ref('')
/** 保存中收到的新标记：按 item_id 排队，保存完成后逐个补发（不依赖当前项） */
interface PendingMark {
  state: MarkState
  note: string
  advance: boolean
  prev?: Mark
}
const pendingMarks = new Map<string, PendingMark>()
/** 审阅人名字持久化：客户刷新后不用重输（C-14）。
 *  localStorage 用安全访问器：测试环境/隐私模式下不可用时静默降级。
 */
const savedReviewer = (() => {
  try {
    return localStorage.getItem('medialib.reviewer') ?? ''
  } catch {
    return ''
  }
})()
const reviewer = ref(savedReviewer)

const current = computed(() => items.value[index.value] ?? null)

// 审阅人名字落 localStorage，跨会话保留
watch(reviewer, (v) => {
  try {
    if (v.trim()) localStorage.setItem('medialib.reviewer', v.trim())
    else localStorage.removeItem('medialib.reviewer')
  } catch {
    // 隐私模式等存储不可用场景静默降级
  }
})

const counts = computed(() => {
  const c = { selected: 0, pending: 0, rejected: 0, unmarked: 0 }
  for (const it of items.value) {
    const m = marks.value[it.id]
    if (!m) c.unmarked++
    else c[m.state]++
  }
  return c
})

const markedRatio = computed(() => {
  const total = items.value.length
  if (!total) return 0
  return (total - counts.value.unmarked) / total
})

function jumpToState(target: MarkState | 'unmarked') {
  const total = items.value.length
  if (!total) return
  for (let offset = 1; offset <= total; offset++) {
    const idx = (index.value + offset) % total
    const m = marks.value[items.value[idx].id]
    if (target === 'unmarked' ? !m : m?.state === target) {
      jump(idx)
      return
    }
  }
}

let swipeStartX = 0
let swipeStartY = 0
function onTouchStart(e: TouchEvent) {
  if (zoomed.value || e.touches.length !== 1) return
  swipeStartX = e.touches[0].clientX
  swipeStartY = e.touches[0].clientY
}
function onTouchEnd(e: TouchEvent) {
  if (zoomed.value || e.changedTouches.length !== 1) return
  const dx = e.changedTouches[0].clientX - swipeStartX
  const dy = e.changedTouches[0].clientY - swipeStartY
  if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.4) {
    step(dx > 0 ? -1 : 1)
  }
}

const filmEntries = computed(() =>
  items.value
    .map((item, idx) => ({ item, idx }))
    .filter(({ item }) => {
      if (filmFilter.value === 'all') return true
      const m = marks.value[item.id]
      if (filmFilter.value === 'unmarked') return !m
      return m?.state === filmFilter.value
    }),
)

function markOf(id: string): Mark | undefined {
  return marks.value[id]
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(`/api/review/${encodeURIComponent(token.value)}`)
    if (!res.ok) {
      error.value = res.status === 404 ? t('review.invalid') : t('review.loadFailed')
      return
    }
    const data = await res.json()
    linkTitle.value = data.link?.title || ''
    linkMessage.value = data.link?.message || ''
    linkExpiresAt.value = Number(data.link?.expires_at || 0)
    items.value = data.items ?? []
    const next: Record<string, Mark> = {}
    for (const it of items.value) {
      const raw = it as MediaItem & {
        review_state?: string
        review_note?: string
        review_reviewer?: string
      }
      if (raw.review_state) {
        next[it.id] = {
          state: raw.review_state as MarkState,
          note: raw.review_note ?? '',
          reviewer: raw.review_reviewer ?? '',
        }
      }
    }
    marks.value = next
    savedAt.value = 0
    // 首次进入时也要把批注框填成当前项的已存批注
    noteDraft.value = items.value[0] ? (marks.value[items.value[0].id]?.note ?? '') : ''
    void scrollFilmToCurrent()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

/** 写入标记；乐观更新 + 失败回滚（C-15 同款约定） */
async function setMark(state: MarkState, note?: string) {
  const it = current.value
  if (!it) return
  const prev = marks.value[it.id]
  const effectiveNote = note ?? prev?.note ?? ''
  const next: Mark = {
    state,
    note: effectiveNote,
    reviewer: reviewer.value || prev?.reviewer || '',
  }
  // 先乐观更新当前项，快速连点时界面始终反映最后一次选择
  marks.value = { ...marks.value, [it.id]: next }
  saveError.value = ''

  if (saving.value) {
    const existing = pendingMarks.get(it.id)
    pendingMarks.set(it.id, {
      state,
      note: effectiveNote,
      advance: note === undefined,
      // 同一项多次排队时保留最初的旧值，回滚才有意义
      prev: existing ? existing.prev : prev,
    })
    return
  }

  saving.value = true
  let job: { itemId: string; state: MarkState; note: string; advance: boolean; prev?: Mark } = {
    itemId: it.id,
    state,
    note: effectiveNote,
    advance: note === undefined,
    prev,
  }
  while (job) {
    const ok = await sendMark(job.itemId, job.state, job.note, job.prev)
    if (ok && autoNext.value && job.advance && current.value?.id === job.itemId && index.value < items.value.length - 1) {
      step(1)
    }
    const nextJob = pendingMarks.entries().next()
    if (nextJob.done) break
    const [itemId, p] = nextJob.value
    pendingMarks.delete(itemId)
    job = { itemId, state: p.state, note: p.note, advance: p.advance, prev: p.prev }
  }
  saving.value = false
}

async function sendMark(itemId: string, state: MarkState, note: string, prev?: Mark): Promise<boolean> {
  try {
    const res = await fetch(`/api/review/${encodeURIComponent(token.value)}/mark`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: itemId,
        state,
        note,
        reviewer: reviewer.value || prev?.reviewer || '',
      }),
    })
    if (!res.ok) throw new Error(t('review.saveFailed'))
    savedAt.value = Date.now()
    saveError.value = ''
    return true
  } catch {
    // 若同一项还有排队中的新标记，回滚会覆盖用户最新选择，交给后续补发处理
    if (!pendingMarks.has(itemId)) {
      if (prev) marks.value = { ...marks.value, [itemId]: prev }
      else {
        const copy = { ...marks.value }
        delete copy[itemId]
        marks.value = copy
      }
    }
    saveError.value = t('review.saveFailed')
    return false
  }
}

function saveNote() {
  const it = current.value
  if (!it) return
  void setMark(marks.value[it.id]?.state ?? 'pending', noteDraft.value)
}

/** 切图前提交未保存的备注，避免用户输入随缩略图点击静默丢失 */
function flushNoteDraft() {
  const it = current.value
  if (!it) return
  const typed = noteDraft.value
  const saved = marks.value[it.id]?.note ?? ''
  if (typed.trim() === saved.trim()) return
  void setMark(marks.value[it.id]?.state ?? 'pending', typed)
}

/** 胶片条跟随当前项滚动：键盘切图后选中项可能在可视区外 */
async function scrollFilmToCurrent() {
  await nextTick()
  // jsdom 等环境没有 scrollIntoView，可选调用避免测试/降级环境报错
  document
    .querySelector<HTMLElement>('.film--cur')
    ?.scrollIntoView?.({ block: 'nearest', inline: 'center', behavior: 'smooth' })
}

function step(delta: number) {
  const next = index.value + delta
  if (next >= 0 && next < items.value.length) {
    flushNoteDraft()
    index.value = next
    noteDraft.value = marks.value[items.value[next].id]?.note ?? ''
    // 「已保存」是上一张的状态，切图后必须清掉
    savedAt.value = 0
    saveError.value = ''
    zoomed.value = false
    void scrollFilmToCurrent()
  }
}

function jump(i: number) {
  flushNoteDraft()
  index.value = i
  noteDraft.value = marks.value[items.value[i].id]?.note ?? ''
  savedAt.value = 0
  saveError.value = ''
  zoomed.value = false
  void scrollFilmToCurrent()
}

/** 胶片条缩略图失败：先回退主缩略图，再失败回退原图 */
function onFilmError(event: Event, item: MediaItem) {
  const img = event.target as HTMLImageElement
  const main = `/t/${item.id}.jpg`
  if (img.getAttribute('src') !== main) {
    img.src = main
    return
  }
  img.src = `/f/${item.file}`
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  const tag = el?.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || Boolean(el?.isContentEditable)
}

function onKeydown(e: KeyboardEvent) {
  // 放大看图时 Esc 优先还原尺寸
  if (e.key === 'Escape' && zoomed.value) {
    e.preventDefault()
    zoomed.value = false
    return
  }
  // Esc 退出输入态（文档约定）：让快捷键重新作用于选片而非文本框
  if (e.key === 'Escape' && isTypingTarget(e.target)) {
    ;(e.target as HTMLElement).blur()
    return
  }
  if (isTypingTarget(e.target) || e.isComposing) return
  // 视频获得焦点时方向键交给原生播放器，避免一边 seek 一边切换素材
  const focusedTag = (e.target as HTMLElement | null)?.tagName
  if (focusedTag === 'VIDEO' && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) return
  switch (e.key) {
    case 'ArrowLeft':
      step(-1)
      break
    case 'ArrowRight':
      step(1)
      break
    case '1':
      void setMark('selected')
      break
    case '2':
      void setMark('pending')
      break
    case '3':
      void setMark('rejected')
      break
  }
}

const spec = computed(() => {
  const it = current.value
  if (!it) return ''
  const parts: string[] = []
  if (it.width && it.height) parts.push(`${it.width}×${it.height}`)
  if (it.ext) parts.push(it.ext.replace(/^\./, '').toUpperCase())
  if (it.size) parts.push(formatBytes(it.size))
  return parts.join(' · ')
})

// 同一组件实例内切换 token（例如粘贴不同选片链接）时重新加载
watch(token, () => {
  index.value = 0
  marks.value = {}
  savedAt.value = 0
  void load()
})

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (summaryTimer !== undefined) window.clearTimeout(summaryTimer)
})
</script>

<template>
  <div class="review">
    <header class="review__head">
      <div class="review__head-bar">
        <a href="/app/" class="review__brand">
          <span class="review__brand-mark" aria-hidden="true">◐</span>
          <span>{{ t('site.name') }}</span>
        </a>
        <div class="review__head-center">
          <h1 class="review__title">{{ linkTitle || t('review.title') }}</h1>
          <span class="review__hint">{{ t('review.hint') }}</span>
        </div>
        <div class="review__head-tools">
          <label class="review__who">
            <span>{{ t('review.reviewer') }}</span>
            <input
              v-model="reviewer"
              type="text"
              :placeholder="t('review.reviewerPlaceholder')"
              maxlength="40"
            />
          </label>
          <button
            type="button"
            class="review__lang mono"
            :aria-label="locale === 'zh-CN' ? t('site.switchToEn') : t('site.switchToZh')"
            :title="locale === 'zh-CN' ? t('site.switchToEn') : t('site.switchToZh')"
            @click="toggleLocale"
          >
            {{ locale === 'zh-CN' ? 'EN' : '中' }}
          </button>
          <button
            type="button"
            class="review__theme mono"
            :aria-label="`${t('site.toggleTheme')} (${themeHint})`"
            :title="themeHint"
            @click="cycleTheme"
          >
            {{ themeMode === 'light' ? '☀' : themeMode === 'dark' ? '☾' : '◐' }}
          </button>
        </div>
      </div>
      <p v-if="linkMessage || linkExpiresAt" class="review__sub">
        <span v-if="linkMessage" class="review__msg">{{ linkMessage }}</span>
        <span v-if="linkExpiresAt" class="review__msg mono">
          {{ t('review.expires', { date: formatDate(linkExpiresAt) }) }}
        </span>
      </p>
    </header>

    <div v-if="loading" class="review__state" role="status">
      <span class="review__spinner" aria-hidden="true" />
      <span>{{ t('site.loading') }}</span>
    </div>
    <div v-else-if="error" class="review__state review__state--error">
      <p>{{ error }}</p>
      <button type="button" class="rv-btn" @click="load">{{ t('common.retry') }}</button>
    </div>
    <p v-else-if="!items.length" class="review__state">{{ t('review.empty') }}</p>

    <template v-else>
      <div class="review__progress-wrap">
        <div class="review__progress" aria-hidden="true">
          <div class="review__progress-fill" :style="{ transform: `scaleX(${markedRatio})` }" />
        </div>
        <span class="review__progress-text mono">
          {{ t('review.progressText', { done: items.length - counts.unmarked, total: items.length }) }}
        </span>
        <!-- 手机端底部统计与筛选条重复，把「复制清单」挪到进度行，选中后即时可用 -->
        <button
          v-if="counts.selected > 0"
          type="button"
          class="review__copy-progress"
          @click="copySelectedSummary"
        >
          {{ summaryCopied ? `✓ ${t('review.summaryCopied')}` : t('review.copySummary') }}
        </button>
      </div>

      <main class="review__stage">
        <div class="review__viewer">
          <button
            type="button"
            class="review__nav review__nav--prev"
            :disabled="index === 0"
            :aria-label="t('lightbox.prev')"
            @click="step(-1)"
          >
            ‹
          </button>
          <figure
            v-if="current"
            :class="['review__figure', { 'review__figure--zoomed': zoomed }]"
            @touchstart.passive="onTouchStart"
            @touchend.passive="onTouchEnd"
          >
            <!-- 快速上传路径下缩略图可能尚未生成：失败时回退原图，不留破图 -->
            <img
              v-if="current.kind === 'image'"
              :src="zoomed ? `/f/${current.file}` : `/t/${current.id}_lg.webp`"
              :alt="current.title || current.name"
              :title="zoomed ? t('review.zoomOut') : t('review.zoomIn')"
              class="review__img review__img--clickable"
              @click="zoomed = !zoomed"
              @error="($event.target as HTMLImageElement).src = `/f/${current.file}`"
            />
            <video
              v-else
              :src="current.play_file ? `/f/${current.file}?play=1` : `/f/${current.file}`"
              :poster="`/t/${current.id}.jpg`"
              :style="current.width && current.height ? { aspectRatio: `${current.width} / ${current.height}` } : undefined"
              controls
              playsinline
              preload="metadata"
              class="review__img review__video"
            />
            <figcaption class="review__cap">
              <strong>{{ current.title || current.name }}</strong>
              <span class="mono">{{ index + 1 }} / {{ items.length }}</span>
              <span v-if="spec" class="mono">{{ spec }}</span>
            </figcaption>
          </figure>
          <button
            type="button"
            class="review__nav review__nav--next"
            :disabled="index >= items.length - 1"
            :aria-label="t('lightbox.next')"
            @click="step(1)"
          >
            ›
          </button>
        </div>

        <div class="review__workbench">
          <div class="review__actions">
            <button
              type="button"
              :class="['rv-btn', { 'rv-btn--selected': markOf(current?.id ?? '')?.state === 'selected' }]"
              @click="setMark('selected')"
            >
              ✓ {{ t('review.selected') }}
            </button>
            <button
              type="button"
              :class="['rv-btn', { 'rv-btn--pending': markOf(current?.id ?? '')?.state === 'pending' }]"
              @click="setMark('pending')"
            >
              ? {{ t('review.pending') }}
            </button>
            <button
              type="button"
              :class="['rv-btn', { 'rv-btn--rejected': markOf(current?.id ?? '')?.state === 'rejected' }]"
              @click="setMark('rejected')"
            >
              ✕ {{ t('review.rejected') }}
            </button>
            <label class="review__auto-next">
              <input v-model="autoNext" type="checkbox" />
              <span>{{ t('review.autoNext') }}</span>
            </label>
          </div>

          <div class="review__note">
            <label :for="'note'" class="sr-only">{{ t('review.note') }}</label>
            <textarea
              id="note"
              v-model="noteDraft"
              :placeholder="`${t('review.notePlaceholder')} (${t('review.noteShortcutHint')})`"
              rows="1"
              @keydown.ctrl.enter.prevent="saveNote"
              @keydown.meta.enter.prevent="saveNote"
            />
            <button type="button" class="rv-btn" @click="saveNote">{{ t('review.saveNote') }}</button>
            <span v-if="saveError" class="review__saving review__saving--err" role="alert">{{ saveError }}</span>
            <span v-else-if="saving" class="review__saving">{{ t('review.saving') }}</span>
            <span v-else-if="savedAt" class="review__saving review__saving--ok">✓ {{ t('review.saved') }}</span>
          </div>
        </div>
      </main>

      <!-- 底部胶片条过滤与缩略图 -->
      <div class="review__film-bar" role="group" :aria-label="t('review.filmstrip')">
        <button
          v-for="f in (['all', 'unmarked', 'selected', 'pending', 'rejected'] as const)"
          :key="f"
          type="button"
          :class="['film-filter', { 'film-filter--on': filmFilter === f }]"
          :aria-pressed="filmFilter === f"
          @click="filmFilter = f"
        >
          {{ f === 'all' ? t('review.filterAll') : t(`review.${f}`) }}
          <span class="mono">
            {{ f === 'all' ? items.length : counts[f] }}
          </span>
        </button>
      </div>
      <nav class="review__film" :aria-label="t('review.filmstrip')">
        <button
          v-for="{ item: it, idx: i } in filmEntries"
          :key="it.id"
          type="button"
          :class="['film', { 'film--cur': i === index }]"
          :aria-current="i === index"
          :aria-label="it.title || it.name"
          @click="jump(i)"
        >
          <img
            :src="it.kind === 'video' ? `/t/${it.id}.jpg` : `/t/${it.id}_sm.webp`"
            alt=""
            loading="lazy"
            decoding="async"
            @error="onFilmError($event, it)"
          />
          <span v-if="it.kind === 'video'" class="film__vid" aria-hidden="true">▶</span>
          <span v-if="markOf(it.id)" :class="['film__dot', `film__dot--${markOf(it.id)!.state}`]" />
        </button>
      </nav>

      <footer class="review__counts mono" aria-live="polite">
        <button type="button" class="review__count-btn" :disabled="!counts.selected" @click="jumpToState('selected')">
          {{ t('review.selected') }} {{ counts.selected }}
        </button>
        <button type="button" class="review__count-btn" :disabled="!counts.pending" @click="jumpToState('pending')">
          {{ t('review.pending') }} {{ counts.pending }}
        </button>
        <button type="button" class="review__count-btn" :disabled="!counts.rejected" @click="jumpToState('rejected')">
          {{ t('review.rejected') }} {{ counts.rejected }}
        </button>
        <button type="button" class="review__count-btn" :disabled="!counts.unmarked" @click="jumpToState('unmarked')">
          {{ t('review.unmarked') }} {{ counts.unmarked }}
        </button>
        <button
          v-if="counts.selected > 0"
          type="button"
          class="review__copy-summary"
          @click="copySelectedSummary"
        >
          {{ summaryCopied ? `✓ ${t('review.summaryCopied')}` : t('review.copySummary') }}
        </button>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.review {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--paper);
  color: var(--ink);
  /* 375px 下也不出横向滚动 */
  max-width: 100vw;
  overflow-x: hidden;
}

.review__head {
  padding: var(--p-space-2) var(--p-space-4);
  border-bottom: 1px solid var(--rule);
  background: color-mix(in srgb, var(--paper) 90%, transparent);
  backdrop-filter: blur(10px);
}

.review__head-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-3);
  max-width: 1440px;
  margin: 0 auto;
  width: 100%;
  flex-wrap: wrap;
}

.review__brand {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--p-font-display);
  font-weight: 600;
  font-size: var(--p-step-0);
  color: var(--ink);
  flex-shrink: 0;
}

.review__brand:hover {
  text-decoration: none;
}

.review__brand-mark {
  color: var(--accent);
}

.review__head-center {
  display: flex;
  align-items: baseline;
  gap: var(--p-space-3);
  flex-wrap: wrap;
  justify-content: center;
}

.review__head-tools {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  flex-wrap: wrap;
}

.review__sub {
  display: flex;
  justify-content: center;
  gap: var(--p-space-3);
  flex-wrap: wrap;
  margin: var(--p-space-1) 0 0;
  font-size: var(--p-step--1);
}

.review__theme,
.review__lang {
  width: 30px;
  height: 30px;
  border-radius: var(--p-radius-full);
  border: 1px solid var(--rule);
  background: var(--surface);
  color: var(--ink-muted);
  display: grid;
  place-items: center;
  font-size: 0.8125rem;
  flex-shrink: 0;
}

.review__theme:hover,
.review__lang:hover {
  color: var(--ink);
  border-color: var(--rule-strong);
}

.review__progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  padding: 6px var(--p-space-4);
  max-width: 1440px;
  margin: 0 auto;
  width: 100%;
}

.review__progress-text {
  font-size: 0.75rem;
  color: var(--ink-muted);
  white-space: nowrap;
}

/* 仅手机/横屏显示：桌面端仍使用底部统计行里的复制按钮 */
.review__copy-progress {
  display: none;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  padding: 0 var(--p-space-2);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink-muted);
  font-size: 0.75rem;
  white-space: nowrap;
}

.review__title {
  margin: 0;
  font-size: var(--p-step-1);
  font-weight: 600;
}

.review__msg {
  margin: 0;
  color: var(--ink-muted);
}

.review__hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--ink-faint);
}

.review__who {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--ink-muted);
}

.review__who input {
  min-height: 28px;
  padding: 0 var(--p-space-2);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink);
  font-size: 0.75rem;
  width: 136px;
}

.review__state {
  text-align: center;
  padding: var(--p-space-8);
  color: var(--ink-muted);
}

.review__state--error {
  color: var(--danger);
}

.review__stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--p-space-2);
  padding: var(--p-space-1) var(--p-space-4) var(--p-space-2);
  min-height: 0;
}

.review__figure {
  margin: 0;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.review__img {
  max-width: min(1280px, 100%);
  /* 动态预留顶栏 + 操作台 + 胶片条高度，保证桌面端无需滚动即可一屏完整展示 */
  max-height: clamp(200px, calc(100dvh - 320px), 680px);
  width: auto;
  height: auto;
  object-fit: contain;
  background: var(--surface);
  border-radius: var(--p-radius-sm);
}

.review__video {
  /* 防止大体积竖屏视频元数据未就绪时宽度坍缩挤掉原生音量与进度条 */
  min-width: min(300px, 92vw);
  background: #12100d;
  color-scheme: dark;
}

.review__img--clickable {
  cursor: zoom-in;
}

.review__figure--zoomed {
  position: fixed;
  inset: 0;
  z-index: var(--p-z-lightbox);
  background: rgba(18, 16, 13, 0.94);
  padding: var(--p-space-5);
  justify-content: center;
  overflow: auto;
}

.review__figure--zoomed .review__img {
  max-width: 96vw;
  max-height: 88dvh;
  cursor: zoom-out;
  background: transparent;
}

.review__figure--zoomed .review__cap {
  color: #faf8f5;
}

.review__cap {
  display: flex;
  gap: var(--p-space-3);
  align-items: baseline;
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  flex-wrap: wrap;
  justify-content: center;
}

.review__workbench {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: var(--p-space-2) var(--p-space-4);
  width: 100%;
  max-width: 1120px;
}

.review__actions,
.review__note {
  display: flex;
  gap: var(--p-space-2);
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
}

.review__note {
  flex: 1 1 320px;
  max-width: 500px;
}

.review__note textarea {
  flex: 1 1 200px;
  min-height: 34px;
  max-height: 96px;
  padding: 6px var(--p-space-3);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-size: var(--p-step--1);
  line-height: 1.4;
  resize: none;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.review__note textarea:focus {
  border-color: var(--accent);
}

.rv-btn {
  min-height: 34px;
  padding: 0 var(--p-space-3);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink);
  font-size: var(--p-step--1);
  font-weight: 500;
  white-space: nowrap;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.rv-btn--selected {
  border-color: var(--success);
  background: var(--success-soft);
  color: var(--success);
}

.rv-btn--pending {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-hover);
}

.rv-btn--rejected {
  border-color: var(--danger);
  background: var(--danger-soft);
  color: var(--danger);
}

.review__progress {
  width: 100%;
  height: 3px;
  background: var(--rule);
  overflow: hidden;
}

.review__progress-fill {
  height: 100%;
  background: var(--accent);
  transform-origin: left center;
  transition: transform var(--p-dur-base) var(--p-ease-out);
}

.review__viewer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--p-space-3);
  width: 100%;
}

.review__nav {
  width: 36px;
  height: 36px;
  border-radius: var(--p-radius-full);
  border: 1px solid var(--rule);
  background: var(--surface);
  color: var(--ink);
  font-size: 1.25rem;
  line-height: 1;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.review__nav:hover:not(:disabled) {
  background: var(--surface-hover);
}

.review__nav:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.review__spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  margin-right: var(--p-space-2);
  border-radius: var(--p-radius-full);
  border: 2px solid var(--rule-strong);
  border-top-color: var(--accent);
  animation: rv-spin 700ms linear infinite;
  vertical-align: middle;
}

@keyframes rv-spin {
  to {
    transform: rotate(360deg);
  }
}

.film__vid {
  position: absolute;
  left: 3px;
  bottom: 3px;
  padding: 0 3px;
  border-radius: var(--p-radius-sm);
  background: rgba(26, 24, 21, 0.72);
  color: #faf8f5;
  font-size: 0.5625rem;
  line-height: 1.4;
}

.review__count-btn {
  padding: 2px var(--p-space-2);
  border-radius: var(--p-radius-full);
  color: inherit;
  transition: background-color var(--p-dur-fast) var(--p-ease-out);
}

.review__count-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--ink);
}

.review__count-btn:disabled {
  cursor: default;
}

.review__copy-summary {
  padding: 2px var(--p-space-3);
  border-radius: var(--p-radius-full);
  border: 1px solid var(--rule-strong);
  background: var(--surface);
  color: var(--ink);
  font-size: 0.75rem;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out);
}

.review__copy-summary:hover {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent-hover);
}

@media (max-width: 600px) {
  .review__nav {
    display: none;
  }
}

.review__auto-next {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: var(--p-space-2);
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  cursor: pointer;
  user-select: none;
}

.review__auto-next input {
  accent-color: var(--accent);
}

.review__film-bar {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: var(--p-space-1);
  padding: var(--p-space-2) var(--p-space-4);
  border-top: 1px solid var(--rule);
  background: var(--paper);
}

.film-filter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--p-space-2);
  border-radius: var(--p-radius-full);
  font-size: 0.75rem;
  color: var(--ink-muted);
  /* 320px 下按钮变窄时「全部」会折成两行，把整条筛选撑高 20px */
  white-space: nowrap;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.film-filter:hover {
  background: var(--surface-hover);
  color: var(--ink);
}

.film-filter--on {
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 500;
}

.review__saving {
  font-size: 0.75rem;
  color: var(--ink-muted);
  white-space: nowrap;
}

.review__saving--ok {
  color: var(--success);
}

.review__saving--err {
  color: var(--danger);
}

.review__film {
  display: flex;
  gap: var(--p-space-1);
  overflow-x: auto;
  padding: 6px var(--p-space-4);
  border-top: 1px solid var(--rule);
  background: var(--surface);
}

.film {
  position: relative;
  flex: 0 0 auto;
  width: 54px;
  height: 54px;
  border-radius: var(--p-radius-sm);
  overflow: hidden;
  border: 2px solid transparent;
}

.film--cur {
  border-color: var(--accent);
}

.film img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.film__dot {
  position: absolute;
  right: 3px;
  bottom: 3px;
  width: 10px;
  height: 10px;
  border-radius: var(--p-radius-full);
  border: 1px solid var(--surface);
}

.film__dot--selected {
  background: var(--success);
}

.film__dot--pending {
  background: var(--accent);
}

.film__dot--rejected {
  background: var(--danger);
}

.review__counts {
  display: flex;
  gap: var(--p-space-3);
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  padding: 6px var(--p-space-4) var(--p-space-2);
  font-size: 0.75rem;
  color: var(--ink-muted);
}

@media (max-width: 680px) {
  .review__head {
    padding: 6px var(--p-space-3);
    padding-top: calc(6px + env(safe-area-inset-top, 0px));
  }
  .review__hint {
    display: none;
  }
  .review__stage {
    padding: 4px var(--p-space-3) 6px;
    gap: 6px;
  }
  .review__img {
    /* 为更高的操作按钮与胶片筛选让出空间，并扣除刘海/Home 指示条安全区；
       否则真机 393×852 会正好多出 80px 左右，底部胶片与统计被挤出屏幕 */
    max-height: clamp(
      150px,
      calc(
        100dvh - 470px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px)
      ),
      380px
    );
  }
  .film {
    width: 44px;
    height: 44px;
  }
  .review__film,
  .review__film-bar {
    /* 320px 下五个筛选项会换行成两行并顶掉胶片与统计；改为单行横滑 */
    flex-wrap: nowrap;
    justify-content: flex-start;
    overflow-x: auto;
    scrollbar-width: none;
    padding: 4px var(--p-space-3);
  }

  .review__film-bar::-webkit-scrollbar {
    display: none;
  }

  /* 名字输入固定 136px 会把「选填，便于库主识别」截断；让它吃掉剩余宽度 */
  .review__who {
    flex: 1 1 160px;
    min-width: 0;
    white-space: nowrap;
  }

  .review__who input {
    width: 100%;
    min-width: 0;
  }

  /* 底部统计与筛选条重复，手机上隐藏；复制清单移到进度行 */
  .review__counts {
    display: none;
  }

  .review__copy-progress {
    display: inline-flex;
  }

  /* 触屏操作台：按钮与输入框加高到 36–40px，避免选片时误触 */
  .review__theme,
  .review__lang {
    width: 36px;
    height: 36px;
  }
  .review__brand {
    min-height: 36px;
    padding: 2px 0;
  }
  .review__who input {
    min-height: 36px;
    font-size: 16px;
  }
  .rv-btn {
    min-height: 40px;
  }
  .review__note textarea {
    min-height: 40px;
    font-size: 16px;
  }
  .review__auto-next input {
    width: 24px;
    height: 24px;
  }
  .film-filter {
    min-height: 32px;
    padding: 4px 10px;
    font-size: 0.8125rem;
  }
  .review__count-btn {
    min-height: 32px;
    padding: 4px var(--p-space-2);
  }
  .review__copy-summary {
    min-height: 32px;
  }
}

/* 短屏手机（320×568 / 375×667）：压缩非关键留白，保证操作台与统计仍在一屏内 */
@media (max-height: 680px) and (orientation: portrait) {
  .review__sub {
    display: none;
  }

  .review__head {
    padding-top: calc(4px + env(safe-area-inset-top, 0px));
    padding-bottom: 4px;
  }

  .review__head-bar {
    gap: 6px;
  }

  .review__progress-wrap {
    padding-top: 2px;
    padding-bottom: 2px;
  }

  .review__stage {
    gap: 4px;
    padding-top: 0;
    padding-bottom: 2px;
  }

  .review__counts {
    padding-top: 2px;
    padding-bottom: calc(2px + env(safe-area-inset-bottom, 0px));
  }

  .review__img {
    max-height: clamp(
      128px,
      calc(
        100dvh - 470px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px)
      ),
      380px
    );
  }
}

/* 320px 小屏：收紧筛选胶囊，让五个状态在一行内完整露出 */
@media (max-width: 360px) {
  .review__film-bar {
    gap: 4px;
    padding-left: var(--p-space-2);
    padding-right: var(--p-space-2);
  }

  .film-filter {
    padding: 4px 8px;
  }
}

/* 横屏选片：图片与操作台并排，隐藏胶片与统计，避免纵向堆叠溢出 */
@media (max-height: 520px) and (orientation: landscape) {
  .review__head {
    padding-top: calc(2px + env(safe-area-inset-top, 0px));
    padding-bottom: 2px;
  }

  .review__sub,
  .review__hint,
  .review__film-bar,
  .review__film,
  .review__counts {
    display: none;
  }

  .review__stage {
    flex-direction: row;
    align-items: center;
    gap: var(--p-space-3);
    padding: 4px var(--p-space-3);
  }

  .review__viewer {
    flex: 1;
    min-width: 0;
    display: flex;
    justify-content: center;
  }

  .review__workbench {
    flex: 0 0 300px;
    max-width: 300px;
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }

  /* 纵向排列后 flex-basis 会作用到高度，批注区不能沿用 320px 的横向 basis */
  .review__note {
    flex: 0 0 auto;
    width: 100%;
    max-width: none;
  }

  .review__note textarea {
    flex: 1 1 auto;
    max-height: 72px;
  }

  .review__actions {
    width: 100%;
  }

  .review__img {
    max-height: calc(
      100dvh - 140px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px)
    );
  }

  .review__copy-progress {
    display: inline-flex;
  }
}
</style>
