# web/ —— MediaLib 前端（Vite + Vue 3 + TypeScript）

## 产品定位与访问入口

`open-pic` 的主流程是**定时自动抓取图片和视频 → 处理入库 → 用户 Web 浏览 → 管理员前台维护**；手工链接采集与上传是补充，不是唯一的数据来源。

| 入口 | 面向对象与用途 | 代码位置 |
| :--- | :--- | :--- |
| `/app/` | 用户前台：图片墙、搜索筛选、灯箱查看与视频播放 | 本目录 `src/`；构建产物为 `media-library/scripts/static/app/` |
| `/admin/` | 管理员前台：素材、标签、合集、回收站、采集任务与统计维护 | `media-library/scripts/static/index.html`、`app.css`、`app.js` |
| `/` | 站点入口，默认跳转 `/app/`；旧前端模式或缺少构建产物时跳转 `/admin` | `media-library/scripts/server.py` |

两套前台共用 FastAPI 接口、SQLite 索引与媒体文件，管理员前台并非仅供临时回退。X 自动采集由 NAS 上的 PicoClaw 定时任务调用本项目 `x_scrape_cron.sh`，不是由用户打开网页触发，具体约定见 [技能说明](../media-library/SKILL.md)。

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
        ├── HomeView.vue    # 单页沉浸式图片墙 + 按需展开分面检索主页
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

产物输出至 `media-library/scripts/static/app/`，**源代码与构建产物都纳入本项目版本库**；管理员前台的源文件同样在本仓库维护，不得只在 NAS 上修改页面或静态文件。

每次更新部署严格执行：

1. 在本项目修改、测试并构建，审查源代码和构建产物。
2. 将本次变更提交到 Git，再推送 GitHub `origin/main`。
3. NAS 的 `/vol1/picoclaw/repos/open-pic` 从 GitHub `pull --ff-only`，再将仓库内 `media-library/` 同步到 PicoClaw 技能部署目录。
4. 按项目部署规范显式重启服务，并检查 `/healthz`、用户前台 `/app/` 与管理员前台 `/admin/`。

**只运行 `git pull` 并不等于完成部署，直接修改 NAS 部署副本也不会回写仓库。** NAS 不需要安装 Node 工具链；代码同步、数据保护和重启注意事项见 [项目部署规范](../CLAUDE.md)。

服务端按环境变量选择站点根路径的默认入口，`/admin/` 管理员前台独立保留：

| `MEDIA_LIB_FRONTEND` | 行为 |
| :--- | :--- |
| 未设置 | 用户前台产物存在时，`/` 跳转 `/app/`；否则跳转 `/admin` |
| `next` | 优先用户前台；产物存在时 `/` 跳转 `/app/`，缺失时回落 `/admin` |
| `legacy` | `/` 跳转 `/admin`；管理员前台仍承担日常维护功能 |

## 设计约束（来自文档 §2.3 / §2.4）

1. **底色不纯白**：`--paper: #FAF8F5`，卡片 `--surface: #FFFFFF`，靠极轻明度差分层。
2. **对比靠排版**：禁止用色块或 ≥2px 边框分割内容区；分隔仅 1px `--rule`。
3. **图片是唯一高饱和元素**：UI 自身除 `--accent` 外全部中性暖灰。
4. **留白即叙事**：区块间距用 48/64/96px，不用 16/24px。
5. **组件层禁止硬编码颜色**：只能消费 `var(--semantic-*)`，Token 在 `tokens.css`。

## 迭代状态（2026-11-20）

已完成全站 V2 重构、R1–R7 基础精修与连续 9 轮（含线上截图驱动的 4 轮全栈双端精修，累计 90 项）UI/UX 深度优化：
- **导航与视觉质感**：顶栏滚动进度/加载指示线、最近浏览抽屉（防压盖描边角标 + 相对时间 + 破图兜底 + 单条移除）、纸感微光视图态骨架屏、空态热门标签快筛/漫步引导与居中 404 卡片、直觉化 `auto/浅/深` 主题即时翻转过渡。
- **卡片与多视图**：瀑布流/等高网格/紧凑列表三视图、S/M/L 列密度切换与锚点保持、长连续文件名智能断行提示、列表行唯一主色快筛/多选勾选圈/视频动态预览与标签直筛、Shift 区间连选与无跳动多选状态条。
- **检索、批量与多规格导出**：隐藏原生搜索重复叉号、搜索历史 `↑/↓` 键盘选词与单条删除、粘性分面侧栏（无横向溢出 + 当前色值 HEX 预览清除）、多行/多条链接批量采集入队、批量移除标签专属危险态语义与已选标签提取、ZIP 多规格（原图/2048/1280/640）与格式（WebP/JPG/PNG）商业交付面板。
- **灯箱、选片页与分享页**：顶部对比条严格过滤视频、胶片条右侧面板避让防裁切与视频角标、纯净看图（H）与三态底色（B）；客户选片页桌面/手机端一屏完整露出布局、中英切换与竖屏视频真实宽高比防控件坍缩；公开分享页主题同步、外置零遮挡底色切换器与色板 HEX 胶囊；管理后台 `/admin/` 1440px 单行顶栏、幽灵栏/列表行高修复、可视化存储进度条、自定义批量模态框与移动端侧栏抽屉。
- **测试**：`npm test` 覆盖 25 个测试文件全部通过，`vue-tsc --noEmit && vite build` 0 错误通过。
- **移动端第 8 轮（R21）**：分面筛选在窄屏改为底部抽屉（吸顶「查看 N 项」、遮罩与 Esc 关闭、背景滚动锁定）；工具条收为单行横滑并把触控目标提升到 32–36px，密度折叠为循环按钮、喜欢/选择/上传图标化；卡片喜欢与主色点在触屏常显可点；顶栏、批量条、灯箱、抽屉、Toast、选片页与分享页补齐 iOS 安全区与 `100dvh`；选片操作台按钮 40px 且保持一屏完整露出；隐藏文件输入补齐可读标签，触屏字号与对比度同步修正。
- **移动端第 9 轮（R22）**：≤900px 平板也改用分面抽屉，抽屉打开聚焦首个控件并圈闭 Tab、关闭后焦点归还；全站移动输入框统一 16px 防止 iOS 聚焦放大；上传/批量弹层在手机上改为贴底全宽抽屉；灯箱触屏保留 44px 左右浮箭并精简快捷键/画中画/连播等低频控件，控制条由 124px 降到 88px；搜索历史条目与删除按钮放大且限高滚动；多选提示在触屏改为点按语义；加载骨架与真实两列对齐；分享页顶栏吸顶并随主题同步 theme-color；批量条操作轨道增加右缘渐隐、Toast 关闭按钮放大。
