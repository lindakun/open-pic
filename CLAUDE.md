# CLAUDE.md

本文件为在本仓库工作的开发者与编程助手提供项目定位、架构、代码管理与部署规范。

## 项目定位与主流程

`open-pic`（服务名：`MediaLib`）是一个**通过定时自动抓取获取图片和视频，并提供用户 Web 浏览与管理员前台维护**的媒体平台，不只是收到链接后执行下载的 PicoClaw 技能。

1. **定时采集**：PicoClaw 按计划调用本项目的抓取脚本，从配置的 X 账号获取图片与视频，分批轮转并保留去重断点。
2. **处理入库**：采集结果通过 FastAPI 入库，SQLite 保存索引与元数据，磁盘保存原文件、缩略图及播放副本。
3. **用户浏览**：用户通过 `/app/` 浏览、搜索、筛选、查看图片及播放视频。
4. **管理员维护**：管理员通过 `/admin/` 维护素材、标签、合集、回收站，查看任务与统计，并在「⚙ 采集与后处理」面板在线维护抓取/后处理/视觉模型参数、账号白名单与运行状态；手工链接采集和上传是补充入口。

技术架构为 **FastAPI + SQLite（WAL + FTS5）+ 独立静态前端**。两套前台共用同一后端与图库；当前用户前台为 Vue 应用，管理员前台为保留的管理单页。

- **线上访问地址**：`http://192.168.31.188:18100/`（默认跳转用户前台 `/app/`）
- **管理员入口**：`http://192.168.31.188:18100/admin/`
- **NAS 部署路径**：
  - Git 工作副本：`/vol1/picoclaw/repos/open-pic`（跟踪 GitHub `origin/main`）
  - 技能部署副本：`/vol1/picoclaw/.picoclaw/workspace/skills/media-library`
  - 虚拟环境：`/vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv`
  - 运行数据：`/vol1/picoclaw/.picoclaw/workspace/media-library`（媒体文件、`media.db`、账号名单、抓取断点与日志）

**技能部署目录不是 Git 仓库，也不会自动与本项目双向同步。** 本仓库的 `media-library/` 才是其代码来源，NAS 工作副本拉取 GitHub 后再同步到技能目录；运行数据与代码目录必须分离，部署不得覆盖账号名单、去重状态或数据库。

## 目录结构

```text
open-pic/
├── CLAUDE.md                        # 项目开发与部署规范（本文件）
├── requirements.txt                 # Python 依赖（FastAPI/Uvicorn/Pillow/Pytest）
├── web/                             # 新前端（Vite + Vue 3 + TypeScript）
│   ├── src/components/              # 基础与业务组件（MLButton/MLMediaCard/LightboxViewer 等）
│   ├── src/styles/tokens.css        # 三层设计 Token（浅色编辑纸感）
│   └── README.md                    # 前端开发、架构与迭代状态说明
├── scripts/build-web.sh             # 前端构建脚本（产物纳入版本库）
└── media-library/
    ├── SKILL.md                     # picoclaw 技能说明文档
    ├── references/LEARNINGS.md      # 踩坑经验记录
    └── scripts/
        ├── server.py                # FastAPI 主服务 + CLI（--port/--stop/--status/--repair）
        ├── pipeline_config.py       # 抓取/后处理统一配置中心：校验、脱敏、锁探测与运维动作
        ├── db.py                    # SQLite WAL + FTS5 仓储、软删除、画板、任务表
        ├── media_proc.py            # 元数据提取、主色调、dHash、多规格 WebP、视频预览/转码
        ├── tasks.py                 # 后台异步任务队列与 SSE 事件广播
        ├── x_scrape_cron.sh         # X 定时采集入口：互斥、保活、分批参数
        ├── x_scrape.py              # X 账号图片/视频抓取、断点与入库
        ├── test_x_scrape.py         # 抓取解析、断点、失败及互斥回归测试
        ├── ingest.py                # 手工链接/网页/yt-dlp 采集入库 CLI
        ├── ensure.sh                # 图片库服务保活；不负责定时抓取
        ├── learn.py                 # 经验记录工具
        ├── test_pipeline_config.py  # 配置中心、参数优先级与 pipeline API 回归测试
        ├── test_server.py           # FastAPI + SQLite 集成测试
        └── static/                  # 前端目录
            ├── index.html/app.css/app.js   # 管理员前台（/admin/，独立保留）
            └── app/                        # 新前端构建产物（勿手改）
```

## 核心开发约定

1. **保持 CLI 与入库契约向后兼容**：
   - `ingest.py`、`x_scrape.py` 与 `ensure.sh` 依赖 `GET /api/stats` 探活、`POST /api/upload` 上传，以及 `server.py --port/--stop/--status/--repair` CLI 参数；不得破坏定时抓取或手工入库契约。
2. **文件与存储规范**：
   - 内容以 `SHA1[:16]` 作为唯一 `id`，不可变媒体资源（`/f/`、`/t/`、`/p/`）必须携带 `ETag` 与 `Cache-Control: immutable`，视频流必须支持 `Range` 206。
   - 删除操作默认走软删除（`deleted_at`），仅在回收站清空或显式 `permanent=true` 时物理删盘。
3. **重活不阻塞主线程/锁**：
   - `ffmpeg` 转码、动态预览生成、全库元数据回填等耗时任务一律走 `TaskManager` 异步队列，并通过 `/api/jobs/stream`（SSE）推送状态。
4. **语言与注释**：
   - 代码注释与文档统一使用中文。

5. **运行参数配置中心**：
   - 定时抓取、存量后处理与在线视觉模型参数统一保存在运行数据目录 `pipeline_config.json`（同步兼容 `vision_config.json`），由管理台「⚙ 采集与后处理」（`/api/pipeline/*`）在线维护；账号白名单直接读写 `DATA/x_accounts.txt`。
   - 脚本参数按 **CLI 参数 > 环境变量 > 配置文件 > 代码默认值** 四级优先级取值；Shell 入口仅在环境变量显式非空时追加 CLI flag，否则由 Python 脚本读配置。
   - API Key 只脱敏返回（`sk-****xxxx`），留空保留原值；配置文件属于运行数据，`rsync --delete` 部署绝不覆盖。

6. **前端重构约定（v2.0）**：
   - 新前端源码在 `web/`，构建产物输出到 `media-library/scripts/static/app/`，**产物纳入版本库**，NAS 端从远程仓库 pull 即可获得产物（无需在 NAS 构建）；**部署仍须显式重启服务**，见第 6 条。
   - `static/app/` 为构建产物，**禁止手改**；所有改动在 `web/src/` 内完成并重新 `bash scripts/build-web.sh`。
   - 两套前台并存：`web/` 提供 `/app/` 用户前台，`static/index.html`、`app.css`、`app.js` 提供 `/admin/` 管理员前台；后者不是可随意删除的临时回退页。`MEDIA_LIB_FRONTEND=next|legacy` 只选择根路径的默认入口，未设置时依据用户前台产物是否存在判定。
   - 样式只消费 `web/src/styles/tokens.css` 的语义变量，组件内禁止硬编码颜色（浅色编辑纸感为设计基准）。

7. **代码统一维护与部署：`本仓库修改/测试 → commit → push GitHub → NAS pull → 同步部署 → 验证`**：   - **本项目所有代码必须放在本仓库维护**，包括定时抓取入口及主程序、服务端、用户前台、管理员前台、测试、构建与部署脚本；不得只存在于 NAS 技能目录、临时目录或历史会话中。
   - 唯一远程仓库为 GitHub（`origin`: `https://github.com/lindakun/open-pic.git`），**禁止推送到 NAS 裸仓库**。NAS 的 Git 工作副本和技能目录分别是拉取位置与部署位置，不是第二套独立维护的源码。
   - 每次更新部署都必须先在本项目完成修改、测试和 **Git 提交**，再 `git push origin main`，然后 NAS `git pull --ff-only origin main` 并同步到部署目录；禁止跳过 GitHub，直接把本地未提交或未推送代码拷入生产目录，也禁止只在 NAS 热改。
   - 恢复遗失脚本同样遵守此流程：先找回或重写到本仓库，补测试、提交并推送，再部署；上线前检查 `git status`，避免遗漏未跟踪的脚本。
   - `rsync --delete` 会删除部署目录中源仓库没有的文件。先预览同步差异，遇到未知脚本或预期外删除立即停止核查；不要用长期排除某个业务脚本来代替纳入版本管理。
   - 运行数据、账号名单、断点、cookies、日志、数据库与 `venv` 不属于业务源代码；与部署副本分离并备份，凭证和真实媒体不得提交 Git。
   - 代码部署后按下文显式重启服务并验证；`ensure.sh` 仅保活，不会重启旧代码。纯文档更新不需要重启服务。
   - 验收同时覆盖 `/healthz`、实际运行进程、用户与管理员前台，以及定时抓取日志/断点；不能仅以页面能打开、PID 存在或调度器显示 `ok` 判定全链路正常。

## 定时任务与代码入口

以下是当前 NAS 的 PicoClaw 调度约定，时间按 NAS 本地时区；调度器配置保存在 `/vol1/picoclaw/.picoclaw/workspace/cron/jobs.json`，其执行的业务脚本必须来自本仓库。

| 任务 | 调度 | 仓库代码 | 职责 |
|---|---|---|---|
| X 账号图片视频自动抓取 | `15 */2 * * *` | `media-library/scripts/x_scrape_cron.sh` → `x_scrape.py` | 互斥执行、轮转账号、采集并入库 |
| 存量后处理（去重与标注） | `45 */2 * * *` | `media-library/scripts/library_postprocess_cron.sh` → `library_postprocess.py` | 视频指纹回填、全库去重、分批视觉补齐 |
| 图片库服务守护 | `0 * * * *` | `media-library/scripts/ensure.sh` | 服务不可用时拉起，不负责抓取 |

X 抓取入口默认每次轮转 14 个账号，每账号最多处理 4 条推文，视频上限 30MB（以上默认值可在管理台「⚙ 采集与后处理」在线调整，保存于运行数据目录 `pipeline_config.json`）；从运行数据目录读取 `x_accounts.txt` 与 `x_scrape_state.json`，写入 `x_scrape.log`。默认通过 `setsid` 启动独立后台任务，避免受到 PicoClaw 5 分钟命令时限影响；互斥锁由后台任务持有，重复调度不会并发抓取。调度器返回只表示已投递，应以 `x_scrape_runner.log` 的退出码和 `x_scrape.log` 的完成摘要验收。

`--dry-run` 同步执行且不改断点，`--foreground` 可同步执行真实采集用于人工诊断，不应用于有 5 分钟时限的 cron。更新代码不能清空名单或断点，也不能把“未处理的推文”标成已见；主页仅提供有限的最新推文，不保证补齐全部历史。

参数、试运行及运维检查见 [media-library/SKILL.md](media-library/SKILL.md)，两套前台和构建规则见 [web/README.md](web/README.md)。

## 常用命令

```bash
# 本地运行服务端与采集回归测试；bash/flock 用例需在 Linux 环境验证
pytest -v media-library/scripts/test_server.py media-library/scripts/test_x_scrape.py

# 本地启动开发服务（默认数据目录可通过 MEDIA_LIB_DIR 指定）
MEDIA_LIB_DIR=/tmp/mlib-dev python3 media-library/scripts/server.py --port 18100

# 前端开发（需先启动后端 :18100）
cd web && pnpm install && pnpm dev

# 前端构建（产物进 static/app/）
bash scripts/build-web.sh

# 前端单元测试
cd web && pnpm test

# NAS 端服务管理（以 picoclaw 用户运行）
bash /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/ensure.sh
/vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv/bin/python3 \
  /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/server.py --status
```

### 部署（先提交推送 GitHub，再 NAS pull 部署）

1. **在本仓库完成测试和提交**：审查 `git status` 与 `git diff`，按文件暂存本次变更并 `git commit`；新脚本、必要测试、文档和前端构建产物不能遗漏。确认提交不含凭证、账号私密配置或运行数据。
2. **推送后才能拉取部署**：先完成下面的 GitHub 推送，再确认 NAS 工作副本没有未提交改动；如有未知改动，先查明来源，不能强制覆盖。

```bash
# 本地：已完成本次 Git 提交后执行
git push origin main

# NAS：先检查工作副本，确认没有待保护的改动
ssh fnos 'git -C /vol1/picoclaw/repos/open-pic status --short'

# NAS：从 GitHub 拉取，然后仅预览同步差异
ssh fnos 'git -C /vol1/picoclaw/repos/open-pic pull --ff-only origin main && \
  rsync -ani --delete --exclude="venv" --exclude=".pytest_cache" --exclude="__pycache__" \
    /vol1/picoclaw/repos/open-pic/media-library/ \
    /vol1/picoclaw/.picoclaw/workspace/skills/media-library/'
```

3. **检查预览后同步代码**：确认没有未知文件被删除，且目标仅为技能代码目录，不是旁边的运行数据目录，才能执行实际同步；必须保留虚拟环境、账号名单、抓取断点和图库数据。

```bash
ssh fnos 'rsync -ai --delete --exclude="venv" --exclude=".pytest_cache" --exclude="__pycache__" \
  /vol1/picoclaw/repos/open-pic/media-library/ \
  /vol1/picoclaw/.picoclaw/workspace/skills/media-library/'
```

4. **按正确身份协调重启**：代码部署后显式重启；纯文档更新无需重启。服务属主为 `picoclaw`，`ssh fnos` 登录用户（`lindakun`）无权直接向其进程发信号；重启/停止时用 `ssh fnos 'echo "<sudo密码>" | sudo -S -u picoclaw <命令>'` 以 `picoclaw` 身份执行，sudo 密码见本地凭证文件。

   重启前检查实际进程、PID 记录、抓取任务及整点保活。PID 写入与清理使用独立文件锁，旧进程仅能清理自己的 PID；停止超时必须保留记录并返回失败，不能误报停止成功。状态检测结合健康接口与进程身份，PID 文件缺失不等于服务离线；停止操作必须验证实际服务进程，无权验证或发送信号时明确报错。升级旧版本时如发现 PID 缺失，应由服务运行用户识别当前监听进程后完成切换，不要反复重启。

```bash
# 以 picoclaw 身份执行（sudo 密码见本地凭证文件），确认无并发保活启动
S=/vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts
ssh fnos 'echo "<sudo密码>" | sudo -S -u picoclaw sh -c "\
  /vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv/bin/python3 \
    $S/server.py --stop && \
  bash $S/ensure.sh && \
  /vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv/bin/python3 \
    $S/server.py --status"'
```

5. **验证整条链路**：检查健康接口、用户前台 `/app/`、管理员前台 `/admin/`；涉及抓取脚本时先试运行，再检查实际定时执行日志与断点，不能只凭 `ensure.sh` 或调度状态判定恢复。

```bash
# 局域网中检查服务健康
curl -fsS --max-time 10 http://192.168.31.188:18100/healthz
```

```bash
# NAS picoclaw 会话中：不下载、不入库、不推进抓取断点
S=/vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts
bash "$S/x_scrape_cron.sh" --dry-run --batch 1 --limit 1
```
