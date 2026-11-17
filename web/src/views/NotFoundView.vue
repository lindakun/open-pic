<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="not-found">
    <p class="eyebrow">404</p>
    <h1>这个页面不在库里</h1>
    <p class="muted">链接可能已失效，或资源已被移除。</p>
    <RouterLink to="/" class="back">← 回到首页</RouterLink>
  </div>
</template>

<style scoped>
.not-found {
  max-width: 640px;
  margin: 0 auto;
  padding: var(--p-space-9) var(--p-space-5);
}

.not-found h1 {
  margin: var(--p-space-4) 0 var(--p-space-3);
}

.back {
  display: inline-block;
  margin-top: var(--p-space-6);
  color: var(--accent-hover);
  border-bottom: 1px solid var(--accent);
}
</style>
