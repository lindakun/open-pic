<script setup lang="ts">
/**
 * FacetPanel —— 折叠式分面筛选面板（REQ-V2-20 B-10）
 *
 * 每个分面显示计数，零结果项置灰不可点，避免用户点进空结果。
 * 使用原生 <details> 获得折叠语义与键盘支持，无需 JS 状态。
 */
import { computed, ref } from 'vue'
import MLChip from './MLChip.vue'
import { useFilterStore } from '@/stores/filters'
import { useI18n } from '@/composables/useI18n'
import type { Facets, FacetOption } from '@/stores/filters'
import type { Collection } from '@/api/types'

const props = defineProps<{
  facets: Facets | null
  collections?: Collection[]
  loading?: boolean
}>()

const emit = defineEmits<{
  /** 请求父组件执行「清空全部筛选」：关键词等状态只有主页能统一重置并刷新 */
  (e: 'reset'): void
}>()

const filters = useFilterStore()
const { t } = useI18n()

/** 标签组超过 18 个时默认折叠，避免侧栏过长 */
const TAG_FOLD_LIMIT = 18
const tagsExpanded = ref(false)
/** 标签组内即时过滤关键词 */
const tagQuery = ref('')

function visibleTagOptions(options: FacetOption[]): FacetOption[] {
  const q = tagQuery.value.trim().toLowerCase()
  const filtered = q
    ? options.filter((o) => o.value.toLowerCase().includes(q))
    : options
  if (q || tagsExpanded.value) return filtered
  return filtered.slice(0, TAG_FOLD_LIMIT)
}

/** 方向的中文标签 */
/** 分面值到 i18n key 的映射 */
const LABEL_KEY: Record<string, Record<string, string>> = {
  orientation: {
    landscape: 'facet.landscape',
    portrait: 'facet.portrait',
    square: 'facet.square',
  },
  kind: { image: 'facet.kindImage', video: 'facet.kindVideo' },
  size_class: {
    '4k': 'facet.size4k',
    hd: 'facet.sizeHd',
    sd: 'facet.sizeSd',
    small: 'facet.sizeSmall',
  },
  platform: { local: 'facet.platformLocal' },
}

function displayName(dimension: string, value: string): string {
  const key = LABEL_KEY[dimension]?.[value]
  if (key) return t(key)
  if (dimension === 'ext') return value.replace(/^\./, '').toUpperCase()
  return value
}

/** 当前是否选中某项 */
function isActive(dimension: string, value: string): boolean {
  if (dimension === 'tag') return filters.tags.includes(value)
  if (dimension === 'kind') return filters.kind === value
  if (dimension === 'orientation') return filters.orientation === value
  if (dimension === 'platform') return filters.platform === value
  if (dimension === 'ext') return filters.ext === value
  if (dimension === 'size_class') return filters.sizeClass === value
  return false
}

function toggle(dimension: string, value: string): void {
  if (dimension === 'tag') {
    filters.toggleTag(value)
    return
  }
  if (dimension === 'kind') {
    filters.setKind(filters.kind === value ? '' : (value as 'image' | 'video'))
    return
  }
  if (dimension === 'orientation') {
    const v = value as 'landscape' | 'portrait' | 'square'
    filters.setOrientation(filters.orientation === v ? '' : v)
    return
  }
  if (dimension === 'platform') {
    filters.setPlatform(filters.platform === value ? '' : value)
    return
  }
  if (dimension === 'ext') {
    filters.setExt(filters.ext === value ? '' : value)
    return
  }
  if (dimension === 'size_class') {
    filters.setSizeClass(filters.sizeClass === value ? '' : value)
  }
}

/** 折叠的分面定义 */
const groups = computed(() => {
  const f = props.facets
  if (!f) return []
  return [
    { key: 'kind', title: t('facet.kind'), options: f.kind },
    { key: 'orientation', title: t('facet.orientation'), options: f.orientation },
    { key: 'size_class', title: t('facet.sizeClass'), options: f.size_class },
    { key: 'ext', title: t('facet.ext'), options: f.ext },
    { key: 'platform', title: t('facet.platform'), options: f.platform },
    { key: 'tag', title: t('facet.tag'), options: f.tag },
  ].filter((g) => g.options && g.options.length > 0)
})

/** 零结果项不可点：保留展示但禁用交互 */
function canToggle(option: FacetOption): boolean {
  return option.count > 0
}

/** 常用色彩预设：无需先点开图片就能按主色调筛选 */
const PRESET_COLORS = [
  '#b04a3f',
  '#c97a3a',
  '#c8a441',
  '#4a7c59',
  '#3f6a8a',
  '#6a568a',
  '#26231f',
  '#ede8e1',
]

function togglePresetColor(hex: string) {
  filters.setColor(filters.color.toLowerCase() === hex.toLowerCase() ? '' : hex)
}

/** 某分面维度当前已激活的条件数（含排除标签） */
function groupActiveCount(key: string): number {
  if (key === 'kind') return filters.kind ? 1 : 0
  if (key === 'orientation') return filters.orientation ? 1 : 0
  if (key === 'size_class') return filters.sizeClass ? 1 : 0
  if (key === 'ext') return filters.ext ? 1 : 0
  if (key === 'platform') return filters.platform ? 1 : 0
  if (key === 'tag') return filters.tags.length + filters.excludeTags.length
  return 0
}
</script>

<template>
  <aside class="facets" :aria-label="t('facet.title')">
    <div class="facets__head">
      <h2 class="facets__title">{{ t('facet.title') }}</h2>
      <button
        v-if="filters.hasFilters"
        type="button"
        class="facets__reset"
        @click="emit('reset')"
      >
        {{ t('facet.clear') }}
      </button>
    </div>

    <p v-if="loading" class="facets__loading muted">{{ t('facet.counting') }}</p>

    <!-- 画板（Collections）筛选：有画板时展示 -->
    <details v-if="collections?.length" class="facet" open>
      <summary class="facet__summary">
        <span class="facet__name">{{ t('facet.collections') }}</span>
        <span class="facet__chevon" aria-hidden="true">›</span>
      </summary>
      <div class="facet__body">
        <MLChip
          v-for="col in collections"
          :key="col.id"
          :label="col.name"
          :count="col.item_count"
          :active="filters.collectionId === col.id"
          :removable="filters.collectionId === col.id"
          :interactive="true"
          @remove="filters.setCollectionId(null)"
          @click="filters.setCollectionId(filters.collectionId === col.id ? null : col.id)"
        />
      </div>
    </details>

    <!-- 色彩倾向快速筛选 -->
    <details :class="['facet', { 'facet--active': Boolean(filters.color) }]" :open="Boolean(filters.color)">
      <summary class="facet__summary">
        <span class="facet__name">
          {{ t('facet.color') }}
          <span v-if="filters.color" class="facet__active-dot mono">1</span>
        </span>
        <span class="facet__chevon" aria-hidden="true">›</span>
      </summary>
      <div class="facet__body facet__colors">
        <button
          v-for="hex in PRESET_COLORS"
          :key="hex"
          type="button"
          :class="['facet__color-dot', { 'facet__color-dot--on': filters.color.toLowerCase() === hex.toLowerCase() }]"
          :style="{ backgroundColor: hex }"
          :aria-pressed="filters.color.toLowerCase() === hex.toLowerCase()"
          :aria-label="t('card.filterColor', { color: hex })"
          :title="hex.toUpperCase()"
          @click="togglePresetColor(hex)"
        />
        <div v-if="filters.color" class="facet__color-current">
          <span class="facet__color-preview" :style="{ backgroundColor: filters.color }" aria-hidden="true" />
          <span class="mono">{{ filters.color.toUpperCase() }}</span>
          <button
            type="button"
            class="facet__color-clear"
            :aria-label="t('facet.clearColor')"
            :title="t('facet.clearColor')"
            @click="filters.setColor('')"
          >
            ×
          </button>
        </div>
      </div>
    </details>

    <details
      v-for="group in groups"
      :key="group.key"
      :class="['facet', { 'facet--active': groupActiveCount(group.key) > 0 }]"
      :open="group.key === 'kind' || group.key === 'orientation' || groupActiveCount(group.key) > 0"
    >
      <summary class="facet__summary">
        <span class="facet__name">
          {{ group.title }}
          <span v-if="groupActiveCount(group.key)" class="facet__active-dot mono">
            {{ groupActiveCount(group.key) }}
          </span>
        </span>
        <span class="facet__chevon" aria-hidden="true">›</span>
      </summary>
      <div class="facet__body">
        <input
          v-if="group.key === 'tag' && group.options.length > 8"
          v-model="tagQuery"
          type="search"
          class="facet__tag-search"
          :placeholder="t('facet.filterTagsPlaceholder')"
          :aria-label="t('facet.filterTagsPlaceholder')"
        />
        <!-- 已选项渲染为可移除 chip（×），未选项渲染为普通 chip：
             两者都点击即切换。此前未选项也带 ×，视觉上像「移除」而非「添加」。 -->
        <template
          v-for="opt in group.key === 'tag' ? visibleTagOptions(group.options) : group.options"
          :key="opt.value"
        >
          <span class="facet__item">
            <MLChip
              :label="displayName(group.key, opt.value)"
              :count="opt.count"
              :active="isActive(group.key, opt.value)"
              :removable="isActive(group.key, opt.value)"
              :interactive="canToggle(opt) || isActive(group.key, opt.value)"
              :class="['facet__chip', { 'facet__chip--empty': opt.count === 0 }]"
              :aria-disabled="!canToggle(opt) && !isActive(group.key, opt.value)"
              @remove="toggle(group.key, opt.value)"
              @click="canToggle(opt) || isActive(group.key, opt.value) ? toggle(group.key, opt.value) : undefined"
            />
            <!-- 标签组支持快捷排除（NOT 逻辑） -->
            <button
              v-if="group.key === 'tag' && opt.count > 0 && !isActive('tag', opt.value)"
              type="button"
              :class="['facet__exclude', { 'facet__exclude--on': filters.excludeTags.includes(opt.value) }]"
              :title="`${t('facet.excludeTag')} ${opt.value}`"
              :aria-label="`${t('facet.excludeTag')} ${opt.value}`"
              :aria-pressed="filters.excludeTags.includes(opt.value)"
              @click.stop="filters.excludeTag(opt.value)"
            >
              −
            </button>
          </span>
        </template>
        <p
          v-if="group.key === 'tag' && tagQuery.trim() && visibleTagOptions(group.options).length === 0"
          class="facet__empty muted"
        >
          {{ t('facet.noMatchingTags') }}
        </p>
        <button
          v-if="group.key === 'tag' && !tagQuery.trim() && group.options.length > TAG_FOLD_LIMIT"
          type="button"
          class="facet__more"
          @click="tagsExpanded = !tagsExpanded"
        >
          {{ tagsExpanded ? t('facet.showLess') : t('facet.showMore', { count: group.options.length }) }}
        </button>
      </div>
    </details>
  </aside>
</template>

<style scoped>
.facets {
  display: flex;
  flex-direction: column;
  gap: var(--p-space-1);
  font-size: var(--p-step--1);
  overflow-x: hidden;
}

.facets__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: var(--p-space-3);
  border-bottom: 1px solid var(--rule);
  margin-bottom: var(--p-space-2);
}

.facets__title {
  font-size: var(--p-step--1);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-muted);
  font-weight: 500;
  font-family: inherit;
}

.facets__reset {
  color: var(--accent-hover);
  font-size: var(--p-step--1);
}

.facets__reset:hover {
  text-decoration: underline;
}

.facets__loading {
  padding: var(--p-space-2) 0;
}

.facet {
  border-bottom: 1px solid var(--rule);
}

.facet--active > .facet__summary .facet__name {
  color: var(--accent-hover);
}

.facet__tag-search {
  width: 100%;
  margin-bottom: var(--p-space-1);
  padding: 4px var(--p-space-2);
  min-height: 28px;
  font: inherit;
  font-size: var(--p-step--1);
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-sm);
  transition: border-color var(--p-dur-fast) var(--p-ease-out);
}

.facet__tag-search:focus {
  border-color: var(--accent);
}

.facet__tag-search::placeholder {
  color: var(--ink-faint);
}

.facet__empty {
  width: 100%;
  font-size: var(--p-step--1);
  padding: var(--p-space-1) 0;
}

.facet:last-child {
  border-bottom: none;
}

.facet__chip--empty {
  /* 零结果项置灰仍可见：让用户知道"这个选项存在但现在没内容" */
  opacity: 0.42;
  cursor: not-allowed;
}

.facets__loading {
  margin: 0 0 var(--p-space-2);
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}

.facet__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--p-space-3) 0;
  cursor: pointer;
  list-style: none;
  color: var(--ink);
  font-weight: 500;
}

/* 隐藏原生三角，改用自定义箭头 */
.facet__summary::-webkit-details-marker {
  display: none;
}

.facet__name {
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-2);
  font-size: var(--p-step--1);
}

.facet__active-dot {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--p-radius-full);
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-size: 0.6875rem;
  font-weight: 600;
}

.facet__chevon {
  color: var(--ink-faint);
  transition: transform var(--p-dur-fast) var(--p-ease-out);
  font-size: 0.875rem;
}

.facet[open] .facet__chevon {
  transform: rotate(90deg);
}

.facet__body {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-1);
  padding: 0 0 var(--p-space-3);
}

.facet__item {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  max-width: 100%;
}

.facet__exclude {
  min-width: 20px;
  min-height: 22px;
  border-radius: var(--p-radius-full);
  color: var(--ink-faint);
  font-size: 0.75rem;
  line-height: 1;
  opacity: 0;
  transition:
    opacity var(--p-dur-fast) var(--p-ease-out),
    background-color var(--p-dur-fast) var(--p-ease-out),
    color var(--p-dur-fast) var(--p-ease-out);
}

.facet__item:hover .facet__exclude,
.facet__item:focus-within .facet__exclude,
.facet__exclude--on {
  opacity: 1;
}

@media (hover: none) {
  .facet__exclude {
    opacity: 0.72;
    min-width: 28px;
    min-height: 28px;
  }

  /* 触屏没有悬停提示，扩大分面行与色点的可点区域 */
  .facet__summary {
    min-height: 44px;
    padding: var(--p-space-2) 0;
  }

  .facet__tag-search {
    min-height: 38px;
    font-size: 16px;
  }

  .facet__color-dot {
    width: 26px;
    height: 26px;
  }

  .facet__colors {
    gap: var(--p-space-2);
  }

  .facet__color-clear {
    min-width: 32px;
    min-height: 32px;
  }

  .facet__active-dot {
    font-size: 0.75rem;
  }
}

.facet__exclude:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.facet__exclude--on {
  background: var(--danger-soft);
  color: var(--danger);
  font-weight: 600;
}

.facet__more {
  width: 100%;
  text-align: left;
  padding: var(--p-space-1) 0 0;
  font-size: var(--p-step--1);
  color: var(--accent-hover);
}

.facet__more:hover {
  text-decoration: underline;
}

.facet__colors {
  gap: var(--p-space-2);
  padding: 4px 4px var(--p-space-3);
}

.facet__color-dot {
  width: 22px;
  height: 22px;
  border-radius: var(--p-radius-full);
  border: 1.5px solid var(--rule-strong);
  transition:
    transform var(--p-dur-fast) var(--p-ease-out),
    box-shadow var(--p-dur-fast) var(--p-ease-out);
}

.facet__color-dot:hover {
  transform: scale(1.12);
}

.facet__color-dot--on {
  transform: scale(1.12);
  box-shadow: 0 0 0 2px var(--paper), 0 0 0 3.5px var(--accent);
}

.facet__color-current {
  width: 100%;
  display: inline-flex;
  align-items: center;
  gap: var(--p-space-1);
  margin-top: 2px;
  padding: 2px var(--p-space-2);
  border-radius: var(--p-radius-full);
  background: var(--surface-sunken);
  color: var(--ink-muted);
  font-size: 0.75rem;
}

.facet__color-preview {
  width: 12px;
  height: 12px;
  border-radius: var(--p-radius-full);
  border: 1px solid var(--rule-strong);
  flex-shrink: 0;
}

.facet__color-clear {
  margin-left: auto;
  min-width: 18px;
  min-height: 18px;
  border-radius: var(--p-radius-full);
  color: var(--ink-muted);
  display: grid;
  place-items: center;
  line-height: 1;
}

.facet__color-clear:hover {
  background: var(--surface-hover);
  color: var(--danger);
}
</style>
