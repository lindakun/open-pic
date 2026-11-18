# CLAUDE.md

本文件为在 `/Users/linda/code/open-pic` 仓库中工作的 Claude Code 提供项目架构、约定与工作流指引。

## 项目概览

`open-pic`（服务名：`MediaLib`）是一个面向商业网站标准的个人/团队图片与视频资产平台，前身为 NAS 上基于 Python 标准库的轻量技能 `media-library`，现已升级为 **FastAPI + SQLite（WAL + FTS5）+ 独立静态前端** 架构。

- **线上访问地址**：`http://192.168.31.188:18100/`
- **NAS 部署路径**：
  - Git 工作副本：`/vol1/picoclaw/repos/open-pic`（跟踪 GitHub `origin/main`）
  - 技能代码：`/vol1/picoclaw/.picoclaw/workspace/skills/media-library`
  - 虚拟环境：`/vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv`
  - 数据目录：`/vol1/picoclaw/.picoclaw/workspace/media-library`（`files/`、`thumbs/`、`previews/`、`play/`、`media.db`）

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
        ├── db.py                    # SQLite WAL + FTS5 仓储、软删除、画板、任务表
        ├── media_proc.py            # 元数据提取、主色调、dHash、多规格 WebP、视频预览/转码
        ├── tasks.py                 # 后台异步任务队列与 SSE 事件广播
        ├── ingest.py                # 链接/网页/yt-dlp 采集入库 CLI（picoclaw 入口）
        ├── ensure.sh                # 幂等守护拉起脚本（优先使用 venv）
        ├── learn.py                 # 经验记录工具
        ├── test_server.py           # FastAPI + SQLite 集成测试
        └── static/                  # 前端目录
            ├── index.html/app.css/app.js   # 旧前端（legacy 回退用）
            └── app/                        # 新前端构建产物（勿手改）
```

## 核心开发约定

1. **保持 CLI 与入库契约向后兼容**：
   - `ingest.py` 与 `ensure.sh` 依赖 `GET /api/stats` 探活、`POST /api/upload` 上传，以及 `server.py --port/--stop/--status/--repair` CLI 参数，修改时不可破坏兼容。
2. **文件与存储规范**：
   - 内容以 `SHA1[:16]` 作为唯一 `id`，不可变媒体资源（`/f/`、`/t/`、`/p/`）必须携带 `ETag` 与 `Cache-Control: immutable`，视频流必须支持 `Range` 206。
   - 删除操作默认走软删除（`deleted_at`），仅在回收站清空或显式 `permanent=true` 时物理删盘。
3. **重活不阻塞主线程/锁**：
   - `ffmpeg` 转码、动态预览生成、全库元数据回填等耗时任务一律走 `TaskManager` 异步队列，并通过 `/api/jobs/stream`（SSE）推送状态。
4. **语言与注释**：
   - 代码注释与文档统一使用中文。

5. **前端重构约定（v2.0）**：
   - 新前端源码在 `web/`，构建产物输出到 `media-library/scripts/static/app/`，**产物纳入版本库**，NAS 端从远程仓库 pull 即可获得产物（无需在 NAS 构建）；**部署仍须显式重启服务**，见第 6 条。
   - `static/app/` 为构建产物，**禁止手改**；所有改动在 `web/src/` 内完成并重新 `bash scripts/build-web.sh`。
   - 双前端切换：环境变量 `MEDIA_LIB_FRONTEND=next|legacy`，未设置时依据产物存在性自动判定。旧前端保留至重构验收通过。
   - 样式只消费 `web/src/styles/tokens.css` 的语义变量，组件内禁止硬编码颜色（浅色编辑纸感为设计基准）。

6. **部署约定：`push GitHub → NAS pull → 显式重启`**：
   - 唯一远程仓库为 GitHub（`origin`: `https://github.com/lindakun/open-pic.git`），**禁止推送到 NAS 裸仓库**。
   - 顺序固定：先 `git push origin main` 推送到 GitHub，再由 NAS 端从 GitHub 拉取并 `rsync` 同步到部署目录，**最后显式重启服务**。不要把本地未提交的改动直接拷到 NAS。
   - **必须显式重启**：`ensure.sh` 只保证「有进程在跑」，不会重启已在运行的旧进程。仅 pull 后直接 `ensure.sh`，服务仍是旧代码（表现为新路由 404）。重启用 `--stop` + `ensure.sh`。
   - 部署后用 `--status`、`/healthz` 及新产物/新接口做一次线上验证，不要只凭「进程在跑」判定上线成功。

## 常用命令

```bash
# 本地运行集成测试
pytest -v media-library/scripts/test_server.py

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

### 部署（push GitHub → NAS pull → 显式重启）

```bash
# 1. 本地：提交后推送到 GitHub 远程仓库（origin）
git push origin main

# 2. NAS：从 GitHub 持久化工作副本 pull 并同步到技能部署目录（保留 venv）
ssh fnos 'git -C /vol1/picoclaw/repos/open-pic pull --ff-only origin main && \
  rsync -a --delete --exclude="venv" --exclude=".pytest_cache" \
    /vol1/picoclaw/repos/open-pic/media-library/ \
    /vol1/picoclaw/.picoclaw/workspace/skills/media-library/'

# 3. NAS：显式重启（ensure.sh 不会重启旧进程，这步不能省）
ssh fnos 'cd /vol1/picoclaw/.picoclaw/workspace/skills/media-library && \
  venv/bin/python3 scripts/server.py --stop && sleep 2 && bash scripts/ensure.sh'

# 4. 线上验证
curl -s http://192.168.31.188:18100/healthz
ssh fnos 'cd .../media-library && venv/bin/python3 scripts/server.py --status'
```
