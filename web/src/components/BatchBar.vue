<script setup lang="ts">
/**
 * 批量操作条（REQ-05）
 *
 * 出现在页面底部：已选 N 项时常驻，可批量打标、加入画板、导出、移入回收站。
 * 刻意不遮挡卡片：默认贴底并留出安全区，移动端收窄为图标+计数。
 */
import { computed, ref } from 'vue'
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
}>()

const emit = defineEmits<{
  (e: 'clear'): void
  (e: 'done', action: string, count: number): void
}>()

const { t } = useI18n()
const toast = useToast()

const busy = ref(false)
const tagOpen = ref(false)
const tagDraft = ref('')
const collectionOpen = ref(false)
const targetCollection = ref<number | null>(null)

const count = computed(() => props.selected.length)

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

async function applyTags() {
  const tags = tagDraft.value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!tags.length) return
  const ok = await run('add_tags', { tags })
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

async function trash() {
  const ok = await run('delete')
  if (ok) emit('clear')
}

async function exportZip() {
  if (!count.value || busy.value) return
  busy.value = true
  try {
    const res = await api.exportZip(props.selected, { preset: 'original' })
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
    <span class="batch__count mono">{{ t('batch.selected', { count }) }}</span>

    <div class="batch__actions">
      <MLButton variant="quiet" :disabled="busy" @click="tagOpen = true">
        {{ t('batch.tags') }}
      </MLButton>
      <MLButton
        v-if="collections?.length"
        variant="quiet"
        :disabled="busy"
        @click="collectionOpen = true"
      >
        {{ t('batch.collection') }}
      </MLButton>
      <MLButton variant="quiet" :disabled="busy" @click="exportZip">
        {{ t('batch.export') }}
      </MLButton>
      <MLButton variant="quiet" :disabled="busy" @click="trash">
        {{ t('batch.trash') }}
      </MLButton>
      <button type="button" class="batch__clear" :aria-label="t('batch.clear')" @click="emit('clear')">
        ✕
      </button>
    </div>

    <!-- 批量打标 -->
    <MLSheet v-model:open="tagOpen" :title="t('batch.tagsTitle')" width="380px">
      <div class="batch__form">
        <MLField
          v-model="tagDraft"
          :label="t('upload.fieldTags')"
          :placeholder="t('upload.tagsPlaceholder')"
          :hint="t('batch.tagsHint', { count })"
        />
        <div class="batch__form-actions">
          <MLButton variant="quiet" @click="tagOpen = false">{{ t('common.cancel') }}</MLButton>
          <MLButton :disabled="busy || !tagDraft.trim()" @click="applyTags">
            {{ t('common.confirm') }}
          </MLButton>
        </div>
      </div>
    </MLSheet>

    <!-- 加入画板 -->
    <MLSheet v-model:open="collectionOpen" :title="t('batch.collectionTitle')" width="380px">
      <div class="batch__form">
        <label class="batch__label" for="batch-collection">{{ t('batch.collectionPick') }}</label>
        <select id="batch-collection" v-model="targetCollection" class="batch__select">
          <option :value="null" disabled>{{ t('batch.collectionPick') }}</option>
          <option v-for="c in collections" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <div class="batch__form-actions">
          <MLButton variant="quiet" @click="collectionOpen = false">{{ t('common.cancel') }}</MLButton>
          <MLButton :disabled="busy || targetCollection === null" @click="applyCollection">
            {{ t('common.confirm') }}
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
  bottom: var(--p-space-4);
  transform: translateX(-50%);
  z-index: var(--p-z-lightbox);
  display: flex;
  align-items: center;
  gap: var(--p-space-4);
  max-width: calc(100vw - var(--p-space-5) * 2);
  padding: var(--p-space-2) var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: var(--surface);
  border: 1px solid var(--rule);
  box-shadow: 0 8px 28px rgba(26, 24, 21, 0.16);
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
}

.batch__actions {
  display: flex;
  align-items: center;
  gap: var(--p-space-1);
  flex-wrap: wrap;
}

.batch__clear {
  min-width: 28px;
  min-height: 28px;
  color: var(--ink-muted);
  border-radius: var(--p-radius-full);
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
