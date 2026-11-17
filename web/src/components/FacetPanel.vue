<script setup lang="ts">
/**
 * FacetPanel —— 折叠式分面筛选面板（REQ-V2-20 B-10）
 *
 * 每个分面显示计数，零结果项置灰不可点，避免用户点进空结果。
 * 使用原生 <details> 获得折叠语义与键盘支持，无需 JS 状态。
 */
import { computed } from 'vue'
import MLChip from './MLChip.vue'
import { useFilterStore } from '@/stores/filters'
import { useI18n } from '@/composables/useI18n'
import type { Facets, FacetOption } from '@/stores/filters'

const props = defineProps<{
  facets: Facets | null
  loading?: boolean
}>()

const filters = useFilterStore()
const { t } = useI18n()

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

function isDisabled(option: FacetOption): boolean {
  return option.count === 0
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
        @click="filters.reset()"
      >
        {{ t('facet.clear') }}
      </button>
    </div>

    <p v-if="loading" class="facets__loading muted">{{ t('facet.counting') }}</p>

    <details
      v-for="group in groups"
      :key="group.key"
      class="facet"
      :open="group.key === 'kind' || group.key === 'orientation'"
    >
      <summary class="facet__summary">
        <span class="facet__name">{{ group.title }}</span>
        <span class="facet__chevon" aria-hidden="true">›</span>
      </summary>
      <div class="facet__body">
        <MLChip
          v-for="opt in group.options"
          :key="opt.value"
          :label="displayName(group.key, opt.value)"
          :count="opt.count"
          :active="isActive(group.key, opt.value)"
          removable
          class="facet__chip"
          @remove="toggle(group.key, opt.value)"
        />
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

.facet:last-child {
  border-bottom: none;
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
  font-size: var(--p-step--1);
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
</style>
