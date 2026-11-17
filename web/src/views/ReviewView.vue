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
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import type { MediaItem } from '@/api/types'

const route = useRoute()
const { t, formatBytes } = useI18n()

const token = computed(() => String(route.params.token ?? ''))
const items = ref<MediaItem[]>([])
const linkTitle = ref('')
const linkMessage = ref('')
const loading = ref(true)
const error = ref('')
const index = ref(0)
const saving = ref(false)
const savedAt = ref(0)

/** 本地标记缓存：以 item_id 为键，避免每次切换都回查 */
type MarkState = 'selected' | 'pending' | 'rejected'
interface Mark {
  state: MarkState
  note: string
  reviewer: string
}
const marks = ref<Record<string, Mark>>({})
const noteDraft = ref('')
const reviewer = ref('')

const current = computed(() => items.value[index.value] ?? null)

const counts = computed(() => {
  const c = { selected: 0, pending: 0, rejected: 0, unmarked: 0 }
  for (const it of items.value) {
    const m = marks.value[it.id]
    if (!m) c.unmarked++
    else c[m.state]++
  }
  return c
})

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
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

/** 写入标记；乐观更新 + 失败回滚（C-15 同款约定） */
async function setMark(state: MarkState, note?: string) {
  const it = current.value
  if (!it || saving.value) return
  const prev = marks.value[it.id]
  const next: Mark = {
    state,
    note: note ?? prev?.note ?? '',
    reviewer: reviewer.value || prev?.reviewer || '',
  }
  marks.value = { ...marks.value, [it.id]: next }
  saving.value = true
  try {
    const res = await fetch(`/api/review/${encodeURIComponent(token.value)}/mark`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: it.id,
        state: next.state,
        note: next.note,
        reviewer: next.reviewer,
      }),
    })
    if (!res.ok) throw new Error(t('review.saveFailed'))
    savedAt.value = Date.now()
  } catch {
    // 回滚
    if (prev) marks.value = { ...marks.value, [it.id]: prev }
    else {
      const copy = { ...marks.value }
      delete copy[it.id]
      marks.value = copy
    }
  } finally {
    saving.value = false
  }
}

function saveNote() {
  const it = current.value
  if (!it) return
  void setMark(marks.value[it.id]?.state ?? 'pending', noteDraft.value)
}

function step(delta: number) {
  const next = index.value + delta
  if (next >= 0 && next < items.value.length) {
    index.value = next
    noteDraft.value = marks.value[items.value[next].id]?.note ?? ''
  }
}

function jump(i: number) {
  index.value = i
  noteDraft.value = marks.value[items.value[i].id]?.note ?? ''
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  const tag = el?.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || Boolean(el?.isContentEditable)
}

function onKeydown(e: KeyboardEvent) {
  if (isTypingTarget(e.target) || e.isComposing) return
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
  if (it.ext) parts.push(it.ext.toUpperCase())
  if (it.size) parts.push(formatBytes(it.size))
  return parts.join(' · ')
})

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="review">
    <header class="review__head">
      <h1 class="review__title">{{ linkTitle || t('review.title') }}</h1>
      <p v-if="linkMessage" class="review__msg">{{ linkMessage }}</p>
      <p class="review__hint">{{ t('review.hint') }}</p>
      <label class="review__who">
        <span>{{ t('review.reviewer') }}</span>
        <input
          v-model="reviewer"
          type="text"
          :placeholder="t('review.reviewerPlaceholder')"
          maxlength="40"
        />
      </label>
    </header>

    <p v-if="loading" class="review__state">{{ t('site.loading') }}</p>
    <p v-else-if="error" class="review__state review__state--error">{{ error }}</p>
    <p v-else-if="!items.length" class="review__state">{{ t('review.empty') }}</p>

    <template v-else>
      <main class="review__stage">
        <figure v-if="current" class="review__figure">
          <img
            v-if="current.kind === 'image'"
            :src="`/t/${current.id}_lg.webp`"
            :alt="current.title || current.name"
            class="review__img"
          />
          <video
            v-else
            :src="`/f/${current.file}`"
            :poster="`/t/${current.id}.jpg`"
            controls
            playsinline
            class="review__img"
          />
          <figcaption class="review__cap">
            <strong>{{ current.title || current.name }}</strong>
            <span v-if="spec" class="mono">{{ spec }}</span>
          </figcaption>
        </figure>

        <div class="review__actions">
          <button
            type="button"
            :class="['rv-btn', { 'rv-btn--on': markOf(current?.id ?? '')?.state === 'selected' }]"
            @click="setMark('selected')"
          >
            ✓ {{ t('review.selected') }}
          </button>
          <button
            type="button"
            :class="['rv-btn', { 'rv-btn--on': markOf(current?.id ?? '')?.state === 'pending' }]"
            @click="setMark('pending')"
          >
            ? {{ t('review.pending') }}
          </button>
          <button
            type="button"
            :class="['rv-btn', { 'rv-btn--on': markOf(current?.id ?? '')?.state === 'rejected' }]"
            @click="setMark('rejected')"
          >
            ✕ {{ t('review.rejected') }}
          </button>
        </div>

        <div class="review__note">
          <label :for="'note'" class="sr-only">{{ t('review.note') }}</label>
          <textarea
            id="note"
            v-model="noteDraft"
            :placeholder="t('review.notePlaceholder')"
            rows="2"
          />
          <button type="button" class="rv-btn" @click="saveNote">{{ t('review.saveNote') }}</button>
        </div>
        <p v-if="saving" class="review__saving">{{ t('review.saving') }}</p>
        <p v-else-if="savedAt" class="review__saving">{{ t('review.saved') }}</p>
      </main>

      <!-- 底部胶片条 -->
      <nav class="review__film" :aria-label="t('review.filmstrip')">
        <button
          v-for="(it, i) in items"
          :key="it.id"
          type="button"
          :class="['film', { 'film--cur': i === index }]"
          :aria-current="i === index"
          :aria-label="it.title || it.name"
          @click="jump(i)"
        >
          <img :src="`/t/${it.id}_sm.webp`" alt="" />
          <span v-if="markOf(it.id)" :class="['film__dot', `film__dot--${markOf(it.id)!.state}`]" />
        </button>
      </nav>

      <footer class="review__counts mono">
        <span>{{ t('review.selected') }} {{ counts.selected }}</span>
        <span>{{ t('review.pending') }} {{ counts.pending }}</span>
        <span>{{ t('review.rejected') }} {{ counts.rejected }}</span>
        <span>{{ t('review.unmarked') }} {{ counts.unmarked }}</span>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.review {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--paper);
  /* 375px 下也不出横向滚动 */
  max-width: 100vw;
  overflow-x: hidden;
}

.review__head {
  padding: var(--p-space-5) var(--p-space-5) var(--p-space-3);
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  text-align: center;
}

.review__title {
  margin: 0;
  font-size: var(--p-step-2);
  font-weight: 600;
}

.review__msg {
  margin: var(--p-space-2) 0 0;
  color: var(--ink-muted);
}

.review__hint {
  margin: var(--p-space-2) 0 0;
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}

.review__who {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-2);
  margin-top: var(--p-space-3);
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}

.review__who input {
  min-height: 32px;
  padding: 0 var(--p-space-2);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-md);
  background: var(--surface);
  color: var(--ink);
  max-width: 160px;
}

.review__state {
  text-align: center;
  padding: var(--p-space-8);
  color: var(--ink-muted);
}

.review__state--error {
  color: #b04a3f;
}

.review__stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-3);
  padding: 0 var(--p-space-4) var(--p-space-4);
  min-height: 0;
}

.review__figure {
  margin: 0;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--p-space-2);
}

.review__img {
  max-width: min(1100px, 100%);
  max-height: 58vh;
  object-fit: contain;
  background: var(--surface);
  border-radius: var(--p-radius-sm);
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

.review__actions,
.review__note {
  display: flex;
  gap: var(--p-space-2);
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
  width: 100%;
}

.review__note textarea {
  flex: 1 1 240px;
  max-width: 520px;
  padding: var(--p-space-2);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-md);
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-size: var(--p-step--1);
  resize: vertical;
}

.rv-btn {
  min-height: 36px;
  padding: 0 var(--p-space-4);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-full);
  background: var(--surface);
  color: var(--ink);
  font-size: var(--p-step--1);
  font-weight: 500;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.rv-btn--on {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.review__saving {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  margin: 0;
}

.review__film {
  display: flex;
  gap: var(--p-space-1);
  overflow-x: auto;
  padding: var(--p-space-2) var(--p-space-4);
  border-top: 1px solid var(--rule);
  background: var(--surface);
}

.film {
  position: relative;
  flex: 0 0 auto;
  width: 64px;
  height: 64px;
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
  background: #4a8c5f;
}

.film__dot--pending {
  background: #b08a3f;
}

.film__dot--rejected {
  background: #b04a3f;
}

.review__counts {
  display: flex;
  gap: var(--p-space-4);
  justify-content: center;
  flex-wrap: wrap;
  padding: var(--p-space-2) var(--p-space-4) var(--p-space-4);
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}
</style>
