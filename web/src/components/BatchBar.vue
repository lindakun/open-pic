<script setup lang="ts">
/**
 * 批量操作条（REQ-05）
 *
 * 出现在页面底部：已选 N 项时常驻，可批量打标、加入画板、导出、移入回收站。
 * 刻意不遮挡卡片：默认贴底并留出安全区，移动端收窄为图标+计数。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import { useToast } from '@/composables/useToast'
import MLButton from './MLButton.vue'
import MLSheet from './MLSheet.vue'
import MLField from './MLField.vue'
import type { Collection } from '@/api/types'

const props = defineProps<{
  selected: string[]
  collections?: Collection[]
  availableTags?: string[]
  /** 当前已选素材实际携带的标签，供「移除标签」模式优先点选 */
  selectedTags?: string[]
}>()

const emit = defineEmits<{
  (e: 'clear'): void
  (e: 'done', action: string, count: number): void
}>()

const { t } = useI18n()
const toast = useToast()

const busy = ref(false)
const trashConfirm = ref(false)
let trashTimer: number | undefined
const tagOpen = ref(false)
/** 标签操作模式：新增或移除（后端 batch 接口两种都支持） */
const tagMode = ref<'add' | 'remove'>('add')
const tagDraft = ref('')
const collectionOpen = ref(false)
const targetCollection = ref<number | null>(null)
const exportOpen = ref(false)
type ExportPreset = 'original' | '2048' | '1280' | '640'
type ExportFormat = '' | 'webp' | 'jpeg' | 'png'
const exportPreset = ref<ExportPreset>('original')
const exportFormat = ref<ExportFormat>('')

const exportPresetBadge = computed(() => {
  if (exportPreset.value === 'original' && !exportFormat.value) return ''
  const p = exportPreset.value === 'original' ? '' : exportPreset.value
  const f = exportFormat.value ? exportFormat.value.toUpperCase() : ''
  return [p, f].filter(Boolean).join('·')
})

const count = computed(() => props.selected.length)

/** 候选标签列表：移除模式优先展示当前已选项拥有的标签，无则回退全库标签 */
const candidateTags = computed(() => {
  const tags = tagMode.value === 'remove' && props.selectedTags?.length
    ? props.selectedTags
    : props.availableTags ?? []
  return tags.filter((tag) => tag !== 'AI已标注')
})

/**
 * 批量条出现时抬高 toast 的基线高度，避免两者在底部中央重叠。
 * 用 CSS 变量而非直接操作 toast 组件，保持组件解耦。
 */
function syncBatchOffset(visible: boolean) {
  const root = document.documentElement
  if (visible) root.style.setProperty('--batch-bar-offset', '72px')
  else root.style.removeProperty('--batch-bar-offset')
}

watch(count, (n) => {
  syncBatchOffset(n > 0)
  trashConfirm.value = false
  if (trashTimer !== undefined) window.clearTimeout(trashTimer)
})
onMounted(() => syncBatchOffset(count.value > 0))
onBeforeUnmount(() => {
  syncBatchOffset(false)
  if (trashTimer !== undefined) window.clearTimeout(trashTimer)
})

async function run(action: string, extra: Record<string, unknown> = {}) {
  if (!count.value || busy.value) return
  busy.value = true
  try {
    const res = await api.batch(props.selected, action, extra as { tags?: string[]; collection_id?: number })
    toast.success(t('batch.done', { count: res.count ?? count.value }))
    emit('done', action, res.count ?? count.value)
    return true
  } catch (e) {
    toast.error((e as Error).message)
    return false
  } finally {
    busy.value = false
  }
}

/** 打开标签面板并指定模式（新增/移除） */
function openTags(mode: 'add' | 'remove') {
  tagMode.value = mode
  tagDraft.value = ''
  tagOpen.value = true
}

function appendAvailableTag(tag: string) {
  const list = tagDraft.value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  const idx = list.indexOf(tag)
  if (idx >= 0) list.splice(idx, 1)
  else list.push(tag)
  tagDraft.value = list.join(' ')
}

function hasDraftTag(tag: string): boolean {
  return tagDraft.value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .includes(tag)
}

async function applyTags() {
  const tags = tagDraft.value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!tags.length) return
  const ok = await run(tagMode.value === 'remove' ? 'remove_tags' : 'add_tags', { tags })
  if (ok) {
    tagOpen.value = false
    tagDraft.value = ''
    emit('clear')
  }
}

async function applyCollection() {
  if (targetCollection.value === null) return
  const ok = await run('add_collection', { collection_id: targetCollection.value })
  if (ok) {
    collectionOpen.value = false
    emit('clear')
  }
}

/** 把已选项设为首页精选（A-02）：选择顺序即展示顺序 */
async function setFeatured() {
  if (!count.value || busy.value) return
  busy.value = true
  try {
    const res = await fetch('/api/featured', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: props.selected }),
    })
    if (!res.ok) throw new Error(t('batch.featuredFailed'))
    toast.success(t('batch.featured', { count: count.value }))
    emit('done', 'featured', count.value)
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

async function trash() {
  if (!trashConfirm.value) {
    trashConfirm.value = true
    if (trashTimer !== undefined) window.clearTimeout(trashTimer)
    trashTimer = window.setTimeout(() => {
      trashConfirm.value = false
    }, 3000)
    return
  }
  trashConfirm.value = false
  if (trashTimer !== undefined) window.clearTimeout(trashTimer)
  const ok = await run('delete')
  if (ok) emit('clear')
}

async function exportZip() {
  if (!count.value || busy.value) return
  busy.value = true
  exportOpen.value = false
  try {
    // 后端同步/异步导出上限 200 项，超出部分静默丢弃——必须提前告知
    if (count.value > 200) {
      toast.info(t('batch.exportCapped', { count: count.value }))
    }
    const res = await api.exportZip(props.selected, {
      preset: exportPreset.value,
      format: exportFormat.value || undefined,
    })
    if (res.kind === 'job') {
      toast.info(t('batch.exportQueued', { count: res.count }))
      return
    }
    const url = URL.createObjectURL(res.blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'medialib-pack.zip'
    document.body.appendChild(a)
    a.click()
    a.remove()
    // 释放对象 URL，避免内存泄漏
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
    toast.success(t('batch.exported'))
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="count" class="batch" role="region" :aria-label="t('batch.bar')">
    <span class="batch__count mono" aria-live="polite">{{ t('batch.selected', { count }) }}</span>

    <div class="batch__actions">
      <MLButton variant="quiet" :disabled="busy" @click="openTags('add')">
        {{ t('batch.tags') }}
      </MLButton>
      <MLButton variant="quiet" :disabled="busy" @click="openTags('remove')">
        {{ t('batch.tagsRemove') }}
      </MLButton>
      <MLButton
        v-if="collections?.length"
        variant="quiet"
        :disabled="busy"
        @click="collectionOpen = true"
      >
        {{ t('batch.collection') }}
      </MLButton>
      <span class="batch__export-group">
        <MLButton variant="quiet" :disabled="busy" @click="exportZip">
          {{ t('batch.export') }}
          <span v-if="exportPresetBadge" class="batch__export-badge mono">{{ exportPresetBadge }}</span>
        </MLButton>
        <button
          type="button"
          class="batch__export-more"
          :disabled="busy"
          :aria-label="t('batch.exportOptions')"
          :title="t('batch.exportOptions')"
          @click="exportOpen = true"
        >
          ▾
        </button>
      </span>
      <MLButton variant="quiet" :disabled="busy" @click="setFeatured">
        {{ t('batch.featuredSet') }}
      </MLButton>
      <MLButton
        :variant="trashConfirm ? 'danger' : 'quiet'"
        :disabled="busy"
        @click="trash"
      >
        {{ trashConfirm ? t('batch.trashConfirm', { count }) : t('batch.trash') }}
      </MLButton>
    </div>

    <button type="button" class="batch__clear" :aria-label="t('batch.clear')" @click="emit('clear')">
      ✕
    </button>

    <!-- 批量打标 / 移除标签 -->
    <MLSheet
      v-model:open="tagOpen"
      :title="tagMode === 'remove' ? t('batch.tagsRemoveTitle') : t('batch.tagsTitle')"
      width="380px"
    >
      <div class="batch__form" @keydown.enter.prevent="applyTags">
        <MLField
          v-model="tagDraft"
          :label="tagMode === 'remove' ? t('batch.tagsRemoveField') : t('upload.fieldTags')"
          :placeholder="tagMode === 'remove' ? t('batch.tagsRemovePlaceholder') : t('upload.tagsPlaceholder')"
          :hint="tagMode === 'remove' ? t('batch.tagsRemoveHint', { count }) : t('batch.tagsHint', { count })"
        />
        <div v-if="candidateTags.length" class="batch__tag-picks">
          <span class="batch__tag-picks-label">
            {{ tagMode === 'remove' && selectedTags?.length ? t('batch.selectedItemsTags') : t('batch.availableTags') }}
          </span>
          <button
            v-for="tag in candidateTags"
            :key="tag"
            type="button"
            :class="[
              'batch__tag-pick',
              {
                'batch__tag-pick--on': hasDraftTag(tag) && tagMode !== 'remove',
                'batch__tag-pick--remove': hasDraftTag(tag) && tagMode === 'remove',
              },
            ]"
            @click="appendAvailableTag(tag)"
          >
            {{ tag }}
          </button>
        </div>
        <div class="batch__form-actions">
          <MLButton variant="quiet" @click="tagOpen = false">{{ t('common.cancel') }}</MLButton>
          <MLButton
            :variant="tagMode === 'remove' ? 'danger' : 'primary'"
            :disabled="busy || !tagDraft.trim()"
            @click="applyTags"
          >
            {{ tagMode === 'remove' ? t('batch.tagsRemoveConfirm') : t('common.confirm') }}
          </MLButton>
        </div>
      </div>
    </MLSheet>

    <!-- 加入画板 -->
    <MLSheet v-model:open="collectionOpen" :title="t('batch.collectionTitle')" width="380px">
      <div class="batch__form" @keydown.enter.prevent="applyCollection">
        <label class="batch__label" for="batch-collection">{{ t('batch.collectionPick') }}</label>
        <select id="batch-collection" v-model="targetCollection" class="batch__select">
          <option :value="null" disabled>{{ t('batch.collectionPick') }}</option>
          <option v-for="c in collections" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <div class="batch__form-actions">
          <MLButton variant="quiet" @click="collectionOpen = false">{{ t('common.cancel') }}</MLButton>
          <MLButton variant="primary" :disabled="busy || targetCollection === null" @click="applyCollection">
            {{ t('common.confirm') }}
          </MLButton>
        </div>
      </div>
    </MLSheet>

    <!-- 多规格导出设置 -->
    <MLSheet v-model:open="exportOpen" :title="t('batch.exportTitle')" width="400px">
      <div class="batch__form" @keydown.enter.prevent="exportZip">
        <div class="batch__preset-group">
          <span class="batch__label">{{ t('batch.exportPreset') }}</span>
          <div class="batch__preset-list">
            <button
              v-for="p in (['original', '2048', '1280', '640'] as const)"
              :key="p"
              type="button"
              :class="['batch__preset-item', { 'batch__preset-item--on': exportPreset === p }]"
              @click="exportPreset = p; if (p === 'original') exportFormat = ''"
            >
              <span>{{ p === 'original' ? t('batch.presetOriginal') : t(`batch.preset${p}`) }}</span>
              <span v-if="exportPreset === p" aria-hidden="true">✓</span>
            </button>
          </div>
        </div>
        <div v-if="exportPreset !== 'original'" class="batch__preset-group">
          <span class="batch__label">{{ t('batch.exportFormat') }}</span>
          <div class="batch__fmt-pills">
            <button
              v-for="fmt in (['', 'webp', 'jpeg', 'png'] as const)"
              :key="fmt || 'keep'"
              type="button"
              :class="['batch__tag-pick', { 'batch__tag-pick--on': exportFormat === fmt }]"
              @click="exportFormat = fmt"
            >
              {{ fmt ? fmt.toUpperCase() : t('batch.formatKeep') }}
            </button>
          </div>
        </div>
        <div class="batch__form-actions">
          <MLButton variant="quiet" @click="exportOpen = false">{{ t('common.cancel') }}</MLButton>
          <MLButton variant="primary" :disabled="busy" @click="exportZip">
            {{ t('batch.exportStart') }}
          </MLButton>
        </div>
      </div>
    </MLSheet>
  </div>
</template>

<style scoped>
.batch {
  position: fixed;
  left: 50%;
  bottom: calc(var(--p-space-4) + env(safe-area-inset-bottom, 0px));
  transform: translateX(-50%);
  z-index: var(--p-z-lightbox);
  display: flex;
  align-items: center;
  gap: var(--p-space-4);
  max-width: calc(100vw - var(--p-space-5) * 2);
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  backdrop-filter: blur(14px) saturate(1.1);
  border: 1px solid var(--rule-strong);
  box-shadow: var(--bar-shadow);
  animation: batch-in var(--p-dur-base) var(--p-ease-out);
}

@keyframes batch-in {
  from {
    opacity: 0;
    transform: translate(-50%, 8px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .batch {
    animation: none;
  }
}

.batch__count {
  font-size: var(--p-step--1);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.batch__actions {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
  flex: 1;
  min-width: 0;
  flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: none;
}

.batch__actions::-webkit-scrollbar {
  display: none;
}

.batch__clear {
  min-width: 28px;
  min-height: 28px;
  color: var(--ink-muted);
  border-radius: var(--p-radius-full);
  flex-shrink: 0;
}

.batch__clear:hover {
  background: var(--surface-sunken);
}

.batch__form {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-3);
}

.batch__form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--p-space-2);
}

.batch__tag-picks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.batch__tag-picks-label {
  font-size: 0.75rem;
  color: var(--ink-faint);
}

.batch__tag-pick {
  padding: 1px 8px;
  border-radius: var(--p-radius-full);
  font-size: 0.75rem;
  color: var(--ink-muted);
  background: var(--surface-sunken);
  border: 1px solid transparent;
}

.batch__tag-pick:hover,
.batch__tag-pick--on {
  background: var(--accent-soft);
  color: var(--accent-hover);
  border-color: var(--accent);
}

.batch__tag-pick--remove,
.batch__tag-pick--remove:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
  text-decoration: line-through;
}

.batch__label {
  font-size: var(--p-step--1);
  font-weight: 500;
}

.batch__select {
  min-height: 36px;
  padding: 0 var(--p-space-2);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-md);
  background: var(--surface);
  color: var(--ink);
  font: inherit;
}

.batch__export-group {
  display: inline-flex;
  align-items: center;
}

.batch__export-badge {
  font-size: 0.6875rem;
  padding: 0 5px;
  border-radius: var(--p-radius-full);
  background: var(--accent-soft);
  color: var(--accent-hover);
}

.batch__export-more {
  min-width: 22px;
  min-height: 30px;
  margin-left: -4px;
  padding: 0 4px;
  border-radius: var(--p-radius-md);
  color: var(--ink-muted);
  font-size: 0.75rem;
}

.batch__export-more:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--ink);
}

.batch__preset-group {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
}

.batch__preset-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.batch__preset-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-md);
  border: 1px solid var(--rule);
  background: var(--surface-sunken);
  color: var(--ink);
  font-size: var(--p-step--1);
  text-align: left;
  transition:
    border-color var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out);
}

.batch__preset-item:hover {
  border-color: var(--rule-strong);
}

.batch__preset-item--on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 500;
}

.batch__fmt-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 680px) {
  /* 防止 iOS 聚焦下拉框时页面放大 */
  .batch__select {
    font-size: 16px;
    min-height: 40px;
  }

  /* 操作轨道右缘渐隐，提示还有横向可滑出的操作 */
  .batch__actions {
    -webkit-mask-image: linear-gradient(to right, #000 92%, transparent);
    mask-image: linear-gradient(to right, #000 92%, transparent);
    padding-right: 6px;
  }

  .batch__clear,
  .batch__export-more {
    min-width: 40px;
    min-height: 40px;
  }

  .batch__tag-pick {
    min-height: 40px;
    padding: 6px 12px;
    font-size: 0.8125rem;
  }

  .batch__preset-item {
    min-height: 48px;
  }

  .batch__form-actions :deep(.ml-button) {
    min-height: 44px;
  }
}

/* 移动端：操作条收窄，避免超出视口 */
@media (max-width: 520px) {
  .batch {
    gap: var(--p-space-2);
    padding: var(--p-space-1) var(--p-space-2);
  }
  .batch__actions {
    gap: 0;
  }
}
</style>
