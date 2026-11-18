<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
</script>

<template>
  <div class="not-found">
    <svg class="not-found__art" width="56" height="56" viewBox="0 0 56 56" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="8" y="12" width="40" height="32" rx="4" />
      <path d="M21 23l14 14M35 23L21 37" />
    </svg>
    <p class="eyebrow mono">404</p>
    <h1>{{ t('notfound.heading') }}</h1>
    <p class="muted">{{ t('notfound.hint') }}</p>
    <div class="not-found__actions">
      <RouterLink to="/" class="nf-btn nf-btn--primary">← {{ t('notfound.back') }}</RouterLink>
      <RouterLink :to="{ path: '/', query: { sort: 'random' } }" class="nf-btn nf-btn--ghost">↻ {{ t('sort.random') }}</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.not-found {
  max-width: 560px;
  margin: var(--p-space-8) auto 0;
  padding: var(--p-space-8) var(--p-space-6);
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--p-radius-lg);
  text-align: center;
}

.not-found__art {
  color: var(--ink-faint);
  opacity: 0.72;
  margin: 0 auto var(--p-space-4);
}

.not-found h1 {
  margin: var(--p-space-2) 0 var(--p-space-3);
}

.not-found__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--p-space-3);
  margin-top: var(--p-space-6);
}

.nf-btn {
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 0 var(--p-space-4);
  border-radius: var(--p-radius-md);
  font-size: var(--p-step-0);
  font-weight: 500;
  transition:
    background-color var(--p-dur-fast) var(--p-ease-out),
    border-color var(--p-dur-fast) var(--p-ease-out);
}

.nf-btn:hover {
  text-decoration: none;
}

.nf-btn--primary {
  background: var(--accent);
  color: var(--on-accent);
}

.nf-btn--primary:hover {
  background: var(--accent-hover);
}

.nf-btn--ghost {
  border: 1px solid var(--rule-strong);
  color: var(--ink);
}

.nf-btn--ghost:hover {
  background: var(--surface-hover);
}
</style>
