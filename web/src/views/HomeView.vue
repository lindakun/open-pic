<script setup lang="ts">
/**
 * 首页 —— S0 最小版
 *
 * 编辑化首页（A-02）在 S1 完整实现：Hero 精选、合辑带、Editorial Grid。
 * S0 先给出正确的版式骨架与排版基调，验证纸感视觉方向。
 */
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useMediaStore } from '@/stores/media'

const store = useMediaStore()

onMounted(() => {
  if (store.items.length === 0) store.refresh()
})
</script>

<template>
  <div class="home">
    <!-- Hero：大留白 + 高字重标题承担叙事 -->
    <section class="hero">
      <p class="eyebrow">Visual Asset Library</p>
      <h1 class="hero__title">
        把每一次<br />看见，都<br />收进库里。
      </h1>
      <p class="hero__lede muted">
        一个为商业使用而建的视觉资产库：可检索、可策展、可交付。
      </p>
      <div class="hero__actions">
        <RouterLink to="/browse" class="hero__cta">进入全部资产 →</RouterLink>
      </div>
    </section>

    <!-- 最近上新：Editorial Grid 的骨架，S1 完善混排版式 -->
    <section class="recent">
      <header class="recent__head">
        <h2>最近上新</h2>
        <RouterLink to="/browse" class="recent__more">查看全部</RouterLink>
      </header>

      <div v-if="store.items.length" class="recent__grid">
        <RouterLink
          v-for="item in store.items.slice(0, 8)"
          :key="item.id"
          :to="`/browse?item=${item.id}`"
          class="recent__cell"
        >
          <img
            :src="item.thumb ? `/t/${item.id}_md.webp` : `/f/${item.file}`"
            :alt="item.title || item.name"
            loading="lazy"
            decoding="async"
          />
        </RouterLink>
      </div>

      <p v-else-if="store.isEmpty" class="muted recent__empty">
        库还是空的。上传第一张图片，或通过链接抓取。
      </p>
      <p v-else class="muted recent__empty">载入中…</p>
    </section>
  </div>
</template>

<style scoped>
.home {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 var(--p-space-5);
}

/* Hero：纸感的核心体现——大留白、大字、少元素 */
.hero {
  padding: var(--p-space-9) 0 var(--p-space-8);
  max-width: 900px;
}

.hero__title {
  margin: var(--p-space-4) 0 var(--p-space-5);
  font-size: clamp(2.5rem, 7vw, 5.5rem);
  line-height: 1.02;
  letter-spacing: -0.035em;
}

.hero__lede {
  font-size: var(--p-step-1);
  max-width: 42ch;
  line-height: 1.65;
}

.hero__actions {
  margin-top: var(--p-space-6);
}

.hero__cta {
  display: inline-block;
  font-size: var(--p-step-0);
  font-weight: 500;
  color: var(--accent-hover);
  padding-bottom: 2px;
  border-bottom: 1px solid var(--accent);
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.hero__cta:hover {
  text-decoration: none;
  opacity: 0.72;
}

.recent {
  padding-bottom: var(--p-space-9);
}

.recent__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--p-space-4);
  padding-bottom: var(--p-space-5);
  margin-bottom: var(--p-space-7);
  border-bottom: 1px solid var(--rule);
}

.recent__more {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}

.recent__more:hover {
  color: var(--ink);
}

/* 混排网格骨架：交替列宽制造杂志感 */
.recent__grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: var(--p-space-4);
}

.recent__cell {
  grid-column: span 3;
  overflow: hidden;
  border-radius: var(--p-radius-sm);
  background: var(--surface-sunken);
  aspect-ratio: 4 / 3;
}

/* 前两项跨两倍宽度，形成版式节奏 */
.recent__cell:nth-child(1),
.recent__cell:nth-child(6) {
  grid-column: span 6;
  aspect-ratio: 16 / 9;
}

.recent__cell img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform var(--p-dur-slow) var(--p-ease-out);
}

.recent__cell:hover img {
  transform: scale(1.02);
}

.recent__empty {
  padding: var(--p-space-8) 0;
}

@media (max-width: 900px) {
  .recent__cell,
  .recent__cell:nth-child(1),
  .recent__cell:nth-child(6) {
    grid-column: span 6;
    aspect-ratio: 4 / 3;
  }
}

@media (max-width: 560px) {
  .recent__cell,
  .recent__cell:nth-child(1),
  .recent__cell:nth-child(6) {
    grid-column: span 12;
  }
}
</style>
