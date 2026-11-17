# web/ —— MediaLib 前端（Vite + Vue 3 + TypeScript）

对应需求：[docs/REQ-V2-20.md](../docs/REQ-V2-20.md) 拍板决策 2「一次性重构到位」。

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
    ├── components/         # S0 基础组件库（6 个）
    │   ├── MLButton.vue
    │   ├── MLChip.vue
    │   ├── MLField.vue
    │   ├── MLMediaCard.vue
    │   ├── MLSheet.vue
    │   ├── MLToast.vue
    │   ├── AppShell.vue    # 顶栏外壳
    │   ├── MasonryGrid.vue # 瀑布流
    │   └── LightboxViewer.vue
    ├── composables/
    │   ├── useTheme.ts     # 浅色为主、深色等价映射
    │   └── useToast.ts
    ├── router/index.ts
    ├── stores/media.ts
    ├── styles/
    │   ├── tokens.css      # 三层 Token：primitive → semantic
    │   └── base.css
    └── views/
        ├── HomeView.vue
        ├── BrowseView.vue
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

## S0 完成范围

已完成：脚手架、路由、Pinia、API 客户端、设计 Token、6 个基础组件、双前端切换、`列表 + 灯箱` 最小闭环、8 个单元测试。

未开始（按 §5.1 排期）：A-01 完整 Token 体系与组件库扩充、A-02 编辑化首页、A-03 动效、A-05 响应式图片管线、B-10 分面筛选。
