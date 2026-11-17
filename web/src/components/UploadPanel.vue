<script setup lang="ts">
/**
 * 上传与采集面板（REQ-05）
 *
 * 目标：让 /app 用户页也能完成「传素材」，不必退回 /admin 后台。
 *   - 拖拽 / 点选 / 粘贴（Ctrl+V）上传，支持多文件与进度
 *   - 输入外链走后台采集队列（ingest_url），不阻塞界面
 *   - 上传后可立即补标题与标签
 *
 * 无障碍：原生 <dialog>（Esc 关闭、焦点陷阱）、错误用 aria-live 播报。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import { useToast } from '@/composables/useToast'
import MLSheet from './MLSheet.vue'
import MLField from './MLField.vue'
import MLButton from './MLButton.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  /** 有文件入库成功后触发，父组件据此刷新列表 */
  (e: 'uploaded', count: number): void
}>()

const { t, formatBytes } = useI18n()
const toast = useToast()

type Tab = 'file' | 'url'
const tab = ref<Tab>('file')
const dragActive = ref(false)
const uploading = ref(false)
const progress = ref({ done: 0, total: 0 })
const errors = ref<string[]>([])
const fileInput = ref<HTMLInputElement | null>(null)

const title = ref('')
const tags = ref('')
const url = ref('')
const urlBusy = ref(false)

/** 待上传队列（拖入或选择后先入列，便于确认） */
const queue = ref<File[]>([])
const canSubmit = computed(() => queue.value.length > 0 && !uploading.value)

function addFiles(files: FileList | File[] | null | undefined) {
  if (!files) return
  const list = Array.from(files).filter(
    (f) => f.type.startsWith('image/') || f.type.startsWith('video/'),
  )
  if (!list.length) {
    errors.value = [t('upload.onlyMedia')]
    return
  }
  errors.value = []
  // 去重：同名同大小视为同一文件，避免重复上传
  const seen = new Set(queue.value.map((f) => `${f.name}:${f.size}`))
  for (const f of list) {
    const key = `${f.name}:${f.size}`
    if (!seen.has(key)) {
      seen.add(key)
      queue.value.push(f)
    }
  }
}

function removeAt(index: number) {
  queue.value.splice(index, 1)
}

function onDrop(e: DragEvent) {
  dragActive.value = false
  addFiles(e.dataTransfer?.files)
}

/**
 * 拖放高亮不应在「从父元素移到子元素」时熄灭：
 * dragleave 会在经过每个子节点时触发，直接置 false 会造成闪烁。
 */
function onDragLeave(e: DragEvent) {
  const next = e.relatedTarget as Node | null
  if (next && (e.currentTarget as HTMLElement).contains(next)) return
  dragActive.value = false
}

function onPaste(e: ClipboardEvent) {
  const files = Array.from(e.clipboardData?.files ?? [])
  if (!files.length) return
  e.preventDefault()
  addFiles(files)
}

async function submit() {
  if (!canSubmit.value) return
  uploading.value = true
  errors.value = []
  progress.value = { done: 0, total: queue.value.length }
  let ok = 0
  const failed: string[] = []
  /** 失败文件保留在队列里，便于用户直接重试（此前成功即清空整个队列） */
  const failedFiles: File[] = []

  // 三个一批并发上传：串行传 10 个文件要等 10 倍时间，
  // 并发过高又容易在弱网下集体超时
  const CONCURRENCY = 3
  const pending = [...queue.value]
  async function worker() {
    while (pending.length) {
      const file = pending.shift()
      if (!file) return
      try {
        await api.upload(file, { title: title.value, tags: tags.value })
        ok++
      } catch (e) {
        failed.push(`${file.name}: ${(e as Error).message}`)
        failedFiles.push(file)
      }
      progress.value.done++
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.value.length) }, worker))

  uploading.value = false
  if (failed.length) errors.value = failed
  if (ok > 0) {
    // 只清掉成功的；失败项留在队列里可直接重试
    queue.value = failedFiles
    if (!failedFiles.length) title.value = ''
    toast.success(t('upload.done', { count: ok }))
    emit('uploaded', ok)
    // 全部成功才自动关闭，有失败时留在面板里便于重试
    if (!failed.length) emit('update:open', false)
  }
}

async function submitUrl() {
  const value = url.value.trim()
  if (!/^https?:\/\//i.test(value)) {
    errors.value = [t('upload.badUrl')]
    return
  }
  urlBusy.value = true
  errors.value = []
  try {
    await api.ingestUrl(value, { title: title.value, tags: tags.value })
    url.value = ''
    toast.info(t('upload.queued'))
    emit('update:open', false)
  } catch (e) {
    errors.value = [(e as Error).message]
  } finally {
    urlBusy.value = false
  }
}

/** 面板关闭时清理状态，避免下次打开残留上次的队列 */
watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) {
      errors.value = []
      dragActive.value = false
      progress.value = { done: 0, total: 0 }
    }
  },
)

// 面板打开期间监听粘贴：很多素材是截图后直接 Ctrl+V
watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) window.addEventListener('paste', onPaste)
    else window.removeEventListener('paste', onPaste)
  },
  { immediate: true },
)

onBeforeUnmount(() => window.removeEventListener('paste', onPaste))
</script>

<template>
  <MLSheet
    :open="open"
    :title="t('upload.title')"
    variant="modal"
    width="520px"
    @update:open="emit('update:open', $event)"
  >
    <div class="up">
      <div class="up__tabs" role="tablist" :aria-label="t('upload.title')">
        <button
          type="button"
          role="tab"
          :aria-selected="tab === 'file'"
          :class="['up__tab', { 'up__tab--on': tab === 'file' }]"
          @click="tab = 'file'"
        >
          {{ t('upload.tabFile') }}
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="tab === 'url'"
          :class="['up__tab', { 'up__tab--on': tab === 'url' }]"
          @click="tab = 'url'"
        >
          {{ t('upload.tabUrl') }}
        </button>
      </div>

      <!-- 文件上传 -->
      <div v-if="tab === 'file'" class="up__pane">
        <div
          :class="['up__drop', { 'up__drop--active': dragActive }]"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="onDragLeave"
          @drop.prevent="onDrop"
          @click="fileInput?.click()"
          @keydown.enter.prevent="fileInput?.click()"
          @keydown.space.prevent="fileInput?.click()"
          role="button"
          tabindex="0"
          :aria-label="t('upload.dropHint')"
        >
          <span class="up__drop-icon" aria-hidden="true">＋</span>
          <span class="up__drop-text">{{ t('upload.dropHint') }}</span>
          <span class="up__drop-sub">{{ t('upload.dropSub') }}</span>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/*,video/*"
          multiple
          tabindex="-1"
          class="sr-only"
          @change="addFiles(($event.target as HTMLInputElement).files); ($event.target as HTMLInputElement).value = ''"
        />

        <ul v-if="queue.length" class="up__queue">
          <li v-for="(f, i) in queue" :key="`${f.name}-${i}`" class="up__item">
            <span class="up__item-name">{{ f.name }}</span>
            <span class="up__item-size mono">{{ formatBytes(f.size) }}</span>
            <button
              type="button"
              class="up__remove"
              :aria-label="`${t('upload.remove')} ${f.name}`"
              @click="removeAt(i)"
            >
              ×
            </button>
          </li>
        </ul>

        <div class="up__meta">
          <MLField v-model="title" :label="t('upload.fieldTitle')" :placeholder="t('upload.titlePlaceholder')" />
          <MLField v-model="tags" :label="t('upload.fieldTags')" :placeholder="t('upload.tagsPlaceholder')" />
        </div>

        <div v-if="uploading" class="up__progress" aria-hidden="true">
          <span class="up__progress-text mono">
            {{ progress.done }} / {{ progress.total }}
          </span>
          <span class="up__bar">
            <span
              class="up__bar-fill"
              :style="{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }"
            />
          </span>
        </div>

        <div class="up__actions">
          <MLButton variant="quiet" @click="emit('update:open', false)">
            {{ t('common.cancel') }}
          </MLButton>
          <MLButton :disabled="!canSubmit" @click="submit">
            {{ uploading ? t('upload.uploading') : t('upload.submit', { count: queue.length }) }}
          </MLButton>
        </div>
      </div>

      <!-- 链接采集 -->
      <div v-else class="up__pane">
        <MLField
          v-model="url"
          type="url"
          :label="t('upload.urlLabel')"
          placeholder="https://..."
          :hint="t('upload.urlHint')"
        />
        <div class="up__meta">
          <MLField v-model="title" :label="t('upload.fieldTitle')" :placeholder="t('upload.titlePlaceholder')" />
          <MLField v-model="tags" :label="t('upload.fieldTags')" :placeholder="t('upload.tagsPlaceholder')" />
        </div>
        <div class="up__actions">
          <MLButton variant="quiet" @click="emit('update:open', false)">
            {{ t('common.cancel') }}
          </MLButton>
          <MLButton :disabled="urlBusy || !url.trim()" @click="submitUrl">
            {{ urlBusy ? t('upload.queueing') : t('upload.submitUrl') }}
          </MLButton>
        </div>
      </div>

      <!-- 错误统一在此播报，屏幕阅读器可感知 -->
      <ul v-if="errors.length" class="up__errors" role="alert">
        <li v-for="(e, i) in errors" :key="i">{{ e }}</li>
      </ul>
    </div>
  </MLSheet>
</template>

<style scoped>
.up {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-4);
}

.up__tabs {
  display: flex;
  gap: var(--p-space-1);
  border-bottom: 1px solid var(--rule);
}

.up__tab {
  min-height: 36px;
  padding: 0 var(--p-space-3);
  font-size: var(--p-step--1);
  font-weight: 500;
  color: var(--ink-muted);
  border-bottom: 2px solid transparent;
}

.up__tab--on {
  color: var(--ink);
  border-bottom-color: var(--accent);
}

.up__pane {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-3);
}

.up__drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--p-space-1);
  padding: var(--p-space-6) var(--p-space-4);
  border: 1px dashed var(--rule-strong);
  border-radius: var(--p-radius-md);
  background: var(--surface-sunken);
  cursor: pointer;
  text-align: center;
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.up__drop--active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.up__drop-icon {
  font-size: 1.5rem;
  color: var(--ink-muted);
}

.up__drop-text {
  font-size: var(--p-step-0);
  font-weight: 500;
}

.up__drop-sub {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}

.up__queue {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 160px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.up__item {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  font-size: var(--p-step--1);
  padding: 2px var(--p-space-2);
  border-radius: var(--p-radius-sm);
  background: var(--surface-sunken);
}

.up__item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.up__item-size {
  color: var(--ink-muted);
  flex-shrink: 0;
}

.up__remove {
  min-width: 24px;
  min-height: 24px;
  color: var(--ink-muted);
  font-size: 1rem;
}

.up__meta {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-2);
}

.up__progress {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  font-size: var(--p-step--1);
}

.up__bar {
  flex: 1;
  height: 4px;
  border-radius: var(--p-radius-full);
  background: var(--rule);
  overflow: hidden;
}

.up__bar-fill {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width var(--p-dur-base) var(--p-ease-out);
}

.up__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--p-space-2);
}

.up__errors {
  margin: 0;
  padding: var(--p-space-2) var(--p-space-3);
  list-style: none;
  font-size: var(--p-step--1);
  color: #b04a3f;
  background: rgba(176, 74, 63, 0.08);
  border-radius: var(--p-radius-sm);
}
</style>
