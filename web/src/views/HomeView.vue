<script setup lang="ts">
/**
 * 编辑化首页（REQ-V2-20 A-02）
 *
 * 版式遵循浅色编辑纸感：
 *   - Hero 用大留白 + 高字重标题承担叙事，不用插画与色块
 *   - 精选带与合辑带横排，制造杂志式翻阅感
 *   - 最近上新用 Editorial Grid 混排，打破单一流水线观感
 */
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useMediaStore } from '@/stores/media'
import SmartImage from '@/components/SmartImage.vue'

const store = useMediaStore()

onMounted(() => {
  if (store.items.length === 0) store.refresh()
})

/** Hero 主图：取库里分辨率最高的一张，作为门面 */
const heroItem = computed(() => {
  const withDims = store.items.filter((i) => i.width * i.height > 0)
  if (!withDims.length) return store.items[0] ?? null
  return withDims.reduce((best, cur) =>
    cur.width * cur.height > best.width * best.height ? cur : best,
  )
})

/** 编辑精选带：跳过 Hero 后的 6 项 */
const featured = computed(() =>
  store.items.filter((i) => i.id !== heroItem.value?.id).slice(0, 6),
)

/** 最近上新：紧跟精选之后的 8 项，用混排网格 */
const recent = computed(() =>
  store.items.filter((i) => i.id !== heroItem.value?.id).slice(6, 14),
)
</script>

<template>
  <div class="home">
    <!-- Hero：杂志式开场 -->
    <section class="hero">
      <div class="hero__text">
        <p class="eyebrow">Visual Asset Library</p>
        <h1 class="hero__title">
          把每一次<br />看见，都收进库里。
        </h1>
        <p class="hero__lede">
          一个为商业使用而建的视觉资产库——可检索、可策展、可交付。
        </p>
        <div class="hero__actions">
          <RouterLink to="/browse" class="link-arrow">进入全部资产 →</RouterLink>
        </div>
      </div>

      <RouterLink
        v-if="heroItem"
        :to="`/browse?q=`"
        class="hero__figure"
        :aria-label="`精选：${heroItem.title || heroItem.name}`"
      >
        <SmartImage
          :id="heroItem.id"
          :file="heroItem.file"
          :kind="heroItem.kind"
          :color="heroItem.dominant_color"
          :ratio="1.25"
          :display-width="760"
          priority
          alt=""
        />
        <span class="hero__caption">
          <span class="hero__caption-title">{{ heroItem.title || heroItem.name }}</span>
          <span v-if="heroItem.width" class="hero__caption-spec mono">
            {{ heroItem.width }}×{{ heroItem.height }}
          </span>
        </span>
      </RouterLink>
    </section>

    <!-- 编辑精选带 -->
    <section v-if="featured.length" class="strip">
      <header class="strip__head">
        <h2 class="strip__title">编辑精选</h2>
        <RouterLink to="/browse" class="strip__more">查看全部</RouterLink>
      </header>
      <div class="strip__rail">
        <RouterLink
          v-for="item in featured"
          :key="item.id"
          to="/browse"
          class="strip__cell"
        >
          <SmartImage
            :id="item.id"
            :file="item.file"
            :kind="item.kind"
            :color="item.dominant_color"
            :ratio="0.75"
            :display-width="280"
            alt=""
          />
          <span class="strip__label">{{ item.title || item.name }}</span>
        </RouterLink>
      </div>
    </section>

    <!-- 最近上新：Editorial Grid 混排 -->
    <section class="recent">
      <header class="strip__head">
        <h2 class="strip__title">最近上新</h2>
        <RouterLink to="/browse" class="strip__more">查看全部</RouterLink>
      </header>

      <div v-if="recent.length" class="recent__grid">
        <RouterLink
          v-for="item in recent"
          :key="item.id"
          to="/browse"
          class="recent__cell"
        >
          <SmartImage
            :id="item.id"
            :file="item.file"
            :kind="item.kind"
            :color="item.dominant_color"
            :ratio="1"
            :display-width="520"
            alt=""
          />
        </RouterLink>
      </div>

      <p v-else-if="store.isEmpty" class="empty-note">
        库还是空的。上传第一张图片，或通过链接抓取。
      </p>
      <p v-else-if="!store.items.length" class="empty-note">载入中…</p>
      <p v-else class="empty-note">内容还不够铺满这一栏，继续添加吧。</p>
    </section>

    <footer class="home__foot">
      <RouterLink to="/browse" class="link-arrow">浏览全部 →</RouterLink>
    </footer>
  </div>
</template>

<style scoped>
.home {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 var(--p-space-5);
}

/* ---------- Hero ---------- */
.hero {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--p-space-8);
  align-items: center;
  padding: var(--p-space-9) 0 var(--p-space-8);
}

.hero__title {
  margin: var(--p-space-4) 0 var(--p-space-5);
  font-size: clamp(2.5rem, 6vw, 5rem);
  line-height: 1.02;
  letter-spacing: -0.035em;
}

.hero__lede {
  font-size: var(--p-step-1);
  color: var(--ink-muted);
  max-width: 34ch;
  line-height: 1.6;
}

.hero__actions {
  margin-top: var(--p-space-6);
}

.hero__figure {
  position: relative;
  display: block;
}

.hero__figure:hover {
  text-decoration: none;
}

.hero__caption {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--p-space-3);
  padding-top: var(--p-space-3);
}

.hero__caption-title {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hero__caption-spec {
  font-size: 0.6875rem;
  color: var(--ink-faint);
  flex-shrink: 0;
}

/* ---------- 区块标题 ---------- */
.strip {
  padding-bottom: var(--p-space-8);
}

.strip__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--p-space-4);
  padding-bottom: var(--p-space-4);
  margin-bottom: var(--p-space-5);
  border-bottom: 1px solid var(--rule);
}

.strip__title {
  font-size: var(--p-step-2);
  font-family: var(--p-font-display);
  font-weight: 500;
}

.strip__more {
  font-size: var(--p-step--1);
  color: var(--ink-muted);
}

.strip__more:hover {
  color: var(--ink);
}

/* ---------- 横向滚动带 ---------- */
.strip__rail {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(180px, 1fr);
  gap: var(--p-space-4);
  overflow-x: auto;
  padding-bottom: var(--p-space-2);
  scroll-snap-type: x proximity;
  scrollbar-width: thin;
}

.strip__cell {
  scroll-snap-align: start;
}

.strip__cell:hover {
  text-decoration: none;
}

.strip__label {
  display: block;
  padding-top: var(--p-space-2);
  font-size: var(--p-step--1);
  color: var(--ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- Editorial Grid 混排 ---------- */
.recent {
  padding-bottom: var(--p-space-8);
}

.recent__grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: var(--p-space-4);
}

.recent__cell {
  grid-column: span 3;
}

/* 第 1、6 项跨双倍宽，制造版式节奏 */
.recent__cell:nth-child(1),
.recent__cell:nth-child(6) {
  grid-column: span 6;
}

.recent__cell:hover {
  text-decoration: none;
}

.empty-note {
  color: var(--ink-muted);
  padding: var(--p-space-7) 0;
  font-size: var(--p-step-0);
}

/* ---------- 页脚 ---------- */
.home__foot {
  padding: var(--p-space-8) 0 var(--p-space-9);
  border-top: 1px solid var(--rule);
}

/* 通用箭头链接：纸感强调——只有下划线，不加色块 */
.link-arrow {
  font-size: var(--p-step-0);
  font-weight: 500;
  color: var(--accent-hover);
  padding-bottom: 2px;
  border-bottom: 1px solid var(--accent);
  transition: opacity var(--p-dur-fast) var(--p-ease-out);
}

.link-arrow:hover {
  text-decoration: none;
  opacity: 0.72;
}

@media (max-width: 900px) {
  .hero {
    grid-template-columns: 1fr;
    gap: var(--p-space-6);
    padding-top: var(--p-space-7);
  }

  .recent__cell,
  .recent__cell:nth-child(1),
  .recent__cell:nth-child(6) {
    grid-column: span 6;
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
