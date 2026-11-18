<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
</script>

<template>
  <div class="not-found">
    <p class="eyebrow mono">404</p>
    <h1>{{ t('notfound.heading') }}</h1>
    <p class="muted">{{ t('notfound.hint') }}</p>
    <div class="not-found__actions">
      <RouterLink to="/" class="back">← {{ t('notfound.back') }}</RouterLink>
      <RouterLink to="/browse" class="browse-link">{{ t('site.browse') }} →</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.not-found {
  max-width: 640px;
  margin: 0 auto;
  padding: var(--p-space-9) var(--p-space-5);
  border-left: 2px solid var(--rule);
}

.not-found h1 {
  margin: var(--p-space-4) 0 var(--p-space-3);
}

.not-found__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-5);
  margin-top: var(--p-space-6);
}

.back {
  display: inline-block;
  color: var(--accent-hover);
  border-bottom: 1px solid var(--accent);
}

.browse-link {
  display: inline-block;
  color: var(--ink-muted);
  border-bottom: 1px solid var(--rule-strong);
}

.browse-link:hover {
  color: var(--ink);
}
</style>
