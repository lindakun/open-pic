# 管理后台定时抓取与后处理可视化维护中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/admin/` 管理后台新增「⚙ 采集与后处理」可视化运维中心，统一配置定时抓取、存量后处理、在线视觉模型与 X 账号白名单，并提供锁状态监控、日志查看、代理探活、游标重置与一键触发能力。

**Architecture:** 采用运行数据目录（`MEDIA_LIB_DIR`）下的 `pipeline_config.json` 作为统一配置中心，向后同步兼容 `vision_config.json` 与 `x_accounts.txt`，实现代码与生产配置完全隔离。改造 `x_scrape_cron.sh`、`library_postprocess_cron.sh`、`x_scrape.py`、`library_postprocess.py` 与 `vision_filter.py` 支持「CLI > 环境变量 > 配置文件 > 默认常量」四级优先级，并在 `server.py` 与 `/admin/` 前端提供完整的配置、状态与动作接口及界面。

**Tech Stack:** Python 3, FastAPI, SQLite, Bash (`flock`/`setsid`), Vanilla HTML/CSS/JS

---

## File Structure

- **Create:** `media-library/scripts/pipeline_config.py` — 配置加载、严格校验、原子持久化、API Key 脱敏、文件锁状态探测、日志尾部读取、游标重置、代理连通性测试与脚本触发。
- **Create:** `media-library/scripts/test_pipeline_config.py` — 覆盖配置读写、脱敏、校验、优先级联动、锁冲突与 API 路由的回归测试。
- **Modify:** `media-library/scripts/vision_filter.py` — `load_config` 优先读取 `pipeline_config.json` 的 `vision` 节，缺失时回退 `vision_config.json`。
- **Modify:** `media-library/scripts/x_scrape_cron.sh` — 仅在环境变量显式非空时传入 CLI 参数，交由 `x_scrape.py` 读取 `pipeline_config.json`。
- **Modify:** `media-library/scripts/x_scrape.py` — 支持四级参数优先级（CLI > 环境变量 > `pipeline_config.json` > 默认值），包括 `batch`、`limit`、`max_mb`、`tags`、`proxy`、`timeout`、`min_px`、`min_img_kb` 及 `ai_tag`。
- **Modify:** `media-library/scripts/library_postprocess_cron.sh` — 仅在环境变量显式非空时传入 CLI 参数，交由 `library_postprocess.py` 读取 `pipeline_config.json`。
- **Modify:** `media-library/scripts/library_postprocess.py` — 支持四级参数优先级（CLI > 环境变量 > `pipeline_config.json` > 默认值），包括 `batch`、`phash_limit`、`max_dist`、`ai_tag`、`skip_dedup`、`skip_vision`。
- **Modify:** `media-library/scripts/test_x_scrape.py` — 适配 `x_scrape_cron.sh` 改造后的默认参数与环境变量覆盖测试。
- **Modify:** `media-library/scripts/server.py` — 新增 `GET /api/pipeline/config`、`PUT /api/pipeline/config`、`GET /api/pipeline/status`、`POST /api/pipeline/action` 四个接口。
- **Modify:** `media-library/scripts/static/index.html`、`media-library/scripts/static/app.css`、`media-library/scripts/static/app.js` — 新增「⚙ 采集与后处理」导航项、状态监控卡片、配置表单、账号白名单编辑器与日志查看器。

---

### Task 1: 实现 `pipeline_config.py` 核心配置管理、校验、脱敏与状态探测

**Files:**
- Create: `media-library/scripts/pipeline_config.py`
- Create: `media-library/scripts/test_pipeline_config.py`
- Modify: `media-library/scripts/vision_filter.py`

- [ ] **Step 1: 编写 `test_pipeline_config.py` 基础配置、脱敏、校验与状态测试**

Testing default config loading, saving, `vision_config.json` sync, API Key masking & preservation, validation errors on invalid params/accounts, lock detection, and cursor reset.

- [ ] **Step 2: 运行 pytest 验证测试失败**

Run: `pytest -v media-library/scripts/test_pipeline_config.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'pipeline_config'`)

- [ ] **Step 3: 实现 `media-library/scripts/pipeline_config.py` 并更新 `vision_filter.py`**

Implement `DEFAULT_CONFIG`, `load_pipeline_config`, `get_public_config`, `validate_and_save_config`, `get_pipeline_status`, `reset_scrape_cursor`, `test_proxy_connectivity`, and `trigger_pipeline_action`.

- [ ] **Step 4: 运行 pytest 验证通过**

Run: `pytest -v media-library/scripts/test_pipeline_config.py`
Expected: PASS

---

### Task 2: 改造 `x_scrape.py`、`x_scrape_cron.sh`、`library_postprocess.py`、`library_postprocess_cron.sh` 四级参数优先级

**Files:**
- Modify: `media-library/scripts/x_scrape_cron.sh`
- Modify: `media-library/scripts/x_scrape.py`
- Modify: `media-library/scripts/library_postprocess_cron.sh`
- Modify: `media-library/scripts/library_postprocess.py`
- Modify: `media-library/scripts/test_x_scrape.py`
- Modify: `media-library/scripts/test_pipeline_config.py`

- [ ] **Step 1: 在 `test_pipeline_config.py` 中编写优先级联动测试**

Test that `x_scrape.py` and `library_postprocess.py` read saved values from `pipeline_config.json` when CLI flags/env vars are omitted, and CLI flags override `pipeline_config.json`.

- [ ] **Step 2: 修改 `x_scrape_cron.sh`、`x_scrape.py`、`library_postprocess_cron.sh`、`library_postprocess.py` 及 `test_x_scrape.py`**

Update CLI default handling (`None` sentinel in `argparse`) and resolve values via `CLI > ENV > pipeline_config.json > DEFAULT`.

- [ ] **Step 3: 运行全量后端与脚本测试**

Run: `pytest -v media-library/scripts/test_pipeline_config.py media-library/scripts/test_x_scrape.py media-library/scripts/test_library_postprocess.py`
Expected: PASS

---

### Task 3: 在 `server.py` 中挂载 `/api/pipeline/*` 路由并补齐集成测试

**Files:**
- Modify: `media-library/scripts/server.py`
- Modify: `media-library/scripts/test_pipeline_config.py`

- [ ] **Step 1: 在 `test_pipeline_config.py` 中添加 FastAPI TestClient 路由测试**

Test `GET /api/pipeline/config`, `PUT /api/pipeline/config`, `GET /api/pipeline/status`, and `POST /api/pipeline/action` (including 400 on bad input and 409 when lock is held).

- [ ] **Step 2: 在 `server.py` 中实现 4 个 API 端点**

Add `/api/pipeline/config` (GET/PUT), `/api/pipeline/status` (GET), `/api/pipeline/action` (POST).

- [ ] **Step 3: 运行 pytest 验证所有服务端测试通过**

Run: `pytest -v media-library/scripts/test_pipeline_config.py media-library/scripts/test_server.py`
Expected: PASS

---

### Task 4: 实现管理员前台（`/admin/`）「⚙ 采集与后处理」视图

**Files:**
- Modify: `media-library/scripts/static/index.html`
- Modify: `media-library/scripts/static/app.css`
- Modify: `media-library/scripts/static/app.js`

- [ ] **Step 1: 修改 `index.html` 添加侧边栏导航项与 `#pipelineView` 面板结构**

Add `data-nav="pipeline"` in sidebar and `#pipelineView` section inside `#mainArea`.

- [ ] **Step 2: 修改 `app.css` 添加运维中心响应式卡片、表单、状态徽标与日志终端样式**

Use existing CSS variables (`--bg-elev`, `--bg-card`, `--border`, `--text`, `--text-muted`, `--primary`, `--danger`).

- [ ] **Step 3: 修改 `app.js` 实现配置加载、保存、代理测试、游标重置、手动触发/试运行与日志切换**

Integrate `pipeline` into `syncNavUI()`, bind all actions and log tabs, and show running badge if any task is active.

- [ ] **Step 4: 运行全量回归测试并验证**

Run: `pytest -v media-library/scripts/test_server.py media-library/scripts/test_x_scrape.py media-library/scripts/test_library_postprocess.py media-library/scripts/test_pipeline_config.py`
Expected: PASS
