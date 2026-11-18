# web/ —— MediaLib 前端（Vite + Vue 3 + TypeScript）

## 技术栈

| 项 | 选择 |
| :--- | :--- |
| 构建 | Vite 6 |
| 框架 | Vue 3.5 `<script setup>` |
| 语言 | TypeScript（strict） |
| 状态 | Pinia |
| 路由 | Vue Router（history 模式，base = `/app/`） |
| 样式 | 原生 CSS + CSS 变量 Token（不引 Tailwind） |
| 组件库 | 自建（不引第三方 UI 库） |
| 测试 | Vitest + Vue Test Utils |

## 目录结构

```text
web/
├── index.html
├── vite.config.ts          # 产物输出到 ../media-library/scripts/static/app
├── vitest.config.ts
├── tsconfig.json
└── src/
    ├── main.ts
    ├── App.vue
    ├── api/
    │   ├── types.ts        # 与后端 items 表对齐的类型
    │   └── client.ts       # 统一请求、错误处理、查询序列化
    ├── components/         # 基础与业务组件（13 个）
    │   ├── MLButton.vue
    │   ├── MLChip.vue
    │   ├── MLField.vue
    │   ├── MLMediaCard.vue
    │   ├── MLSheet.vue
    │   ├── MLToast.vue
    │   ├── AppShell.vue    # 顶栏外壳与最近浏览抽屉
    │   ├── BatchBar.vue    # 批量操作条
    │   ├── FacetPanel.vue  # 粘性分面筛选侧栏
    │   ├── LightboxViewer.vue # 灯箱（缩放/对比/连播/行内编辑/相似推荐）
    │   ├── MasonryGrid.vue # 瀑布流 / 等高网格 / 紧凑列表视图
    │   ├── SmartImage.vue  # AVIF/WebP 响应式图片与微光骨架
    │   └── UploadPanel.vue # 拖拽/粘贴上传与队列缩略图预览
    ├── composables/
    │   ├── useAiStatus.ts
    │   ├── useAnalytics.ts
    │   ├── useClipboard.ts
    │   ├── useI18n.ts      # 中英文切换与本地化格式化
    │   ├── useRecent.ts    # 最近浏览历史（localStorage）
    │   ├── useScrollRestore.ts
    │   ├── useTheme.ts     # 浅色为主、深色等价映射
    │   ├── useToast.ts
    │   ├── useViewTransition.ts
    │   └── useZoomPan.ts
    ├── router/index.ts
    ├── stores/
    │   ├── filters.ts      # URL 同步筛选与排序状态
    │   └── media.ts        # 列表分页与灯箱状态
    ├── styles/
    │   ├── tokens.css      # 三层 Token：primitive → semantic
    │   └── base.css
    └── views/
        ├── HomeView.vue    # 整屏瀑布流图片墙
        ├── BrowseView.vue  # 分面检索与多视图浏览页
        ├── ReviewView.vue  # 客户独立选片与批注页
        └── NotFoundView.vue
```

## 开发

```bash
cd web
pnpm install
pnpm dev        # http://127.0.0.1:5173，/api 代理到 :18100
```

后端需先启动：

```bash
MEDIA_LIB_DIR=/tmp/mlib-dev python3 media-library/scripts/server.py --port 18100
```

## 构建与部署

```bash
# 在仓库根目录
bash scripts/build-web.sh
```

产物输出至 `media-library/scripts/static/app/`，**并纳入版本库**——NAS 端只需 `git pull`，无需安装 Node 工具链。

服务端按环境变量切换前端：

| `MEDIA_LIB_FRONTEND` | 行为 |
| :--- | :--- |
| 未设置 | 若 `static/app/index.html` 存在则用新前端，否则用旧单页 |
| `next` | 强制新前端（`/` 302 到 `/app/`） |
| `legacy` | 强制旧单页，用于回退 |

## 设计约束（来自文档 §2.3 / §2.4）

1. **底色不纯白**：`--paper: #FAF8F5`，卡片 `--surface: #FFFFFF`，靠极轻明度差分层。
2. **对比靠排版**：禁止用色块或 ≥2px 边框分割内容区；分隔仅 1px `--rule`。
3. **图片是唯一高饱和元素**：UI 自身除 `--accent` 外全部中性暖灰。
4. **留白即叙事**：区块间距用 48/64/96px，不用 16/24px。
5. **组件层禁止硬编码颜色**：只能消费 `var(--semantic-*)`，Token 在 `tokens.css`。

## 迭代状态（2026-11-18）

已完成全站 V2 重构与 7 轮（R1-R7）UI/UX 深度精修：
- **导航与视觉质感**：顶栏滚动进度发丝线与阴影、最近浏览抽屉（角标 + 元信息 + 单条移除）、全站骨架屏、列表尽头提示与标准细滚动条。
- **卡片与多视图**：瀑布流/等高网格/紧凑列表三视图、悬停呼吸与主色圆点快筛、视频悬停动态预览、SmartImage 加载失败单卡重试。
- **检索与批量/上传**：`/` 键直达搜索、粘性分面侧栏与维度计数徽标、移动端排除按钮可见性、颜色筛选真色块、批量回收站二次确认、上传图片队列缩略图预览与一键清空。
- **灯箱与选片页**：1:1 原图查看、2-4 图同步缩放对比、连播倒计时进度条、视频倍速/循环/PiP、信息面板行内编辑与原地跳转相似推荐；选片页语义化三态配色、审阅进度条、统计快捷跳转与手势切图。
- **测试**：`pnpm test`（或 `npm test`）覆盖 17 个测试文件共 129 条单元测试全部通过，`vue-tsc --noEmit && vite build` 0 错误通过。
