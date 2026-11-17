# CLAUDE.md

本文件为在 `/Users/linda/code/open-pic` 仓库中工作的 Claude Code 提供项目架构、约定与工作流指引。

## 项目概览

`open-pic`（服务名：`MediaLib`）是一个面向商业网站标准的个人/团队图片与视频资产平台，前身为 NAS 上基于 Python 标准库的轻量技能 `media-library`，现已升级为 **FastAPI + SQLite（WAL + FTS5）+ 独立静态前端** 架构。

- **线上访问地址**：`http://192.168.31.188:18100/`
- **NAS 部署路径**：
  - 技能代码：`/vol1/picoclaw/.picoclaw/workspace/skills/media-library`
  - 虚拟环境：`/vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv`
  - 数据目录：`/vol1/picoclaw/.picoclaw/workspace/media-library`（`files/`、`thumbs/`、`previews/`、`play/`、`media.db`）

## 目录结构

```text
open-pic/
├── CLAUDE.md                        # 项目开发与部署规范（本文件）
├── REQUIREMENTS.md                  # 商业化 20 点优化需求及落地状态
├── requirements.txt                 # Python 依赖（FastAPI/Uvicorn/Pillow/Pytest）
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
        └── static/                  # 独立前端（index.html / app.css / app.js）
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

## 常用命令

```bash
# 本地运行集成测试
pytest -v media-library/scripts/test_server.py

# 本地启动开发服务（默认数据目录可通过 MEDIA_LIB_DIR 指定）
MEDIA_LIB_DIR=/tmp/mlib-dev python3 media-library/scripts/server.py --port 18100

# NAS 端服务管理（以 picoclaw 用户运行）
bash /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/ensure.sh
/vol1/picoclaw/.picoclaw/workspace/skills/media-library/venv/bin/python3 \
  /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/server.py --status
```
