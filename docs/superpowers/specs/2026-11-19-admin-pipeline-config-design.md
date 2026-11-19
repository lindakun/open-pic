# 管理后台定时抓取与后处理可视化维护中心设计

**日期**：2026-11-19
**状态**：待评审
**关联模块**：
- 新增：`media-library/scripts/pipeline_config.py`、`media-library/scripts/test_pipeline_config.py`
- 修改：`media-library/scripts/vision_filter.py`、`media-library/scripts/x_scrape.py`、`media-library/scripts/x_scrape_cron.sh`、`media-library/scripts/library_postprocess.py`、`media-library/scripts/library_postprocess_cron.sh`、`media-library/scripts/server.py`
- 管理员前端：`media-library/scripts/static/index.html`、`media-library/scripts/static/app.css`、`media-library/scripts/static/app.js`

---

## 1. 背景与目标

当前 `open-pic`（MediaLib）的定时自动抓取（`x_scrape_cron.sh` / `x_scrape.py`）、存量后处理（`library_postprocess_cron.sh` / `library_postprocess.py`）与在线视觉过滤（`vision_filter.py`）存在大量分散在代码常量、Shell 脚本默认展开、环境变量及独立配置文件（`x_accounts.txt`、`vision_config.json`）中的运行参数。每次调整批次大小、过滤阈值、视觉 Prompt、代理地址或增删 X 账号时，都需要 SSH 登录 NAS 手工改文件或改脚本并重新部署，维护成本高且容易出错。

本方案在管理员前台（`/admin/`）新增**「⚙ 采集与后处理」全量运维工作台**，实现：
1. **核心参数可视化配置**：统一管理定时抓取、存量后处理、在线视觉模型三大模块的所有运行参数。
2. **X 账号白名单与游标维护**：在线编辑 `x_accounts.txt`，实时查看轮转游标进度并支持重置。
3. **运行状态监控与手动触发**：展示任务锁状态（运行中/空闲）、待处理存量进度（待回填 `phash` 数、待视觉标注数）、最近日志尾部，并支持在网页端一键触发正式运行或试运行（Dry-run）。
4. **数据与代码严格隔离**：所有配置保存在运行数据目录（`MEDIA_LIB_DIR`），Git 拉取与 `rsync --delete` 部署绝不覆盖生产配置与密钥。

---

## 2. 架构与存储选型

### 2.1 存储方案对比

| 方案 | 做法 | 优缺点评估 | 结论 |
| :--- | :--- | :--- | :--- |
| **方案 1（采用）：数据目录 JSON 配置中心 + 原生文件兼容** | 在 `DATA/` 下维护 `pipeline_config.json`（同步兼容 `vision_config.json`），账号名单直接读写 `DATA/x_accounts.txt` | **优点**：① 位于运行数据目录，部署代码不覆盖；② `x_scrape.py` 无需引入 SQLite 依赖，零数据库锁竞争；③ 天然支持多行 Prompt 与结构化校验；④ 向后兼容现有 `x_accounts.txt` 与 `vision_config.json`。 | **采用** |
| **方案 2：SQLite `settings` 表** | 在 `media.db` 新增键值表 | `x_scrape.py` 原本仅通过 HTTP API 与服务端交互，直连 SQLite 破坏边界且 Shell 脚本读取不便。 | 不采用 |
| **方案 3：生成 `.env` 文件** | 后端生成 Shell `.env` 供 cron `source` | 多行 Prompt、特殊字符及列表在 Shell `.env` 中转义脆弱。 | 不采用 |

### 2.2 参数生效优先级

为彻底解决现有 `x_scrape_cron.sh` 与 `library_postprocess_cron.sh` 在 Shell 层写死默认值（如 `--batch "${X_SCRAPE_BATCH:-14}"`）导致配置文件无法生效的问题，统一确立 4 级优先级：

```text
1. 显式 CLI 参数（人工诊断临时传入，如 --batch 1 --dry-run）  [最高优先级]
2. 显式环境变量（如 X_SCRAPE_BATCH、X_VISION_MODEL 等非空时）
3. 运行数据目录配置文件（DATA/pipeline_config.json 与 DATA/vision_config.json）
4. 代码内置默认值（DEFAULT_CONFIG 常量）                      [最低优先级]
```

**Shell 入口改造规则**：
- `x_scrape_cron.sh` 与 `library_postprocess_cron.sh` 不再写死 `:-14`、`:-50` 等回退值；仅当环境变量显式非空时才向 Python 脚本追加对应 CLI flag，否则交由 Python 脚本从 `pipeline_config.py` 读取管理前端保存的值。

---

## 3. 配置模型与参数全集

配置文件路径：`{MEDIA_LIB_DIR}/pipeline_config.json`（采用 `.tmp` 临时文件 + `os.replace` 原子写盘）。

```json
{
  "scrape": {
    "batch": 14,
    "limit": 4,
    "max_mb": 30.0,
    "tags": ["X抓取", "人物"],
    "proxy": "http://127.0.0.1:7890",
    "timeout": 30,
    "min_px": 320,
    "min_img_kb": 20
  },
  "postprocess": {
    "batch": 50,
    "phash_limit": 50,
    "max_dist": 4,
    "ai_tag": "AI已标注",
    "skip_dedup": false,
    "skip_vision": false
  },
  "vision": {
    "enabled": true,
    "base_url": "https://sub.hhxxttxs.icu:8787",
    "api_key": "sk-...",
    "model": "cloudflare-workers-ai/@cf/qwen/qwen3.8-27b",
    "timeout": 45,
    "prompt": "你是一个图片库内容审核与标注助手..."
  },
  "updated_at": 1763539200
}
```

### 3.1 定时抓取参数（`scrape`）

| 字段 | 类型 | 默认值 | 校验规则 | 对应原位置 |
| :--- | :--- | :--- | :--- | :--- |
| `batch` | `int` | `14` | `0 <= batch <= 500`（`0` 表示每次全量账号） | `x_scrape_cron.sh` `X_SCRAPE_BATCH` |
| `limit` | `int` | `4` | `0 <= limit <= 50`（`0` 表示主页全部推文） | `x_scrape_cron.sh` `X_SCRAPE_LIMIT` |
| `max_mb` | `float` | `30.0` | `1.0 <= max_mb <= 2048.0` | `x_scrape_cron.sh` `X_SCRAPE_MAX_MB` |
| `tags` | `list[str]` | `["X抓取", "人物"]` | 非空字符串数组，单标签 `<= 20` 字符 | `x_scrape_cron.sh` `X_SCRAPE_TAGS` |
| `proxy` | `str` | `"http://127.0.0.1:7890"` | 允许为空（直连）或 `http(s)://`、`socks5://` | `x_scrape.py` `X_SCRAPE_PROXY` |
| `timeout` | `int` | `30` | `5 <= timeout <= 300` | `x_scrape.py` `--timeout` |
| `min_px` | `int` | `320` | `64 <= min_px <= 4096` | `x_scrape.py` `MIN_PX` |
| `min_img_kb` | `int` | `20` | `1 <= min_img_kb <= 10240` | `x_scrape.py` `MIN_IMG_BYTES` |

### 3.2 存量后处理参数（`postprocess`）

| 字段 | 类型 | 默认值 | 校验规则 | 对应原位置 |
| :--- | :--- | :--- | :--- | :--- |
| `batch` | `int` | `50` | `0 <= batch <= 500`（`0` 跳过视觉阶段） | `library_postprocess_cron.sh` `X_POSTPROCESS_BATCH` |
| `phash_limit` | `int` | `50` | `0 <= phash_limit <= 5000`（`0` 不限） | `library_postprocess_cron.sh` `X_POSTPROCESS_PHASH_LIMIT` |
| `max_dist` | `int` | `4` | `0 <= max_dist <= 16` | `library_postprocess_cron.sh` `X_POSTPROCESS_MAX_DIST` |
| `ai_tag` | `str` | `"AI已标注"` | 非空字符串，`1 <= len <= 20`，不含逗号/空白 | `X_POSTPROCESS_TAG`（抓取与后处理共用） |
| `skip_dedup` | `bool` | `false` | 布尔值 | `library_postprocess.py` `--skip-dedup` |
| `skip_vision` | `bool` | `false` | 布尔值 | `library_postprocess.py` `--skip-vision` |

### 3.3 在线视觉模型参数（`vision`）

| 字段 | 类型 | 默认值 | 校验规则 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `enabled` | `bool` | `true` | 布尔值 | 总开关 |
| `base_url` | `str` | `"https://sub.hhxxttxs.icu:8787"` | `http://` 或 `https://` 开头 | 自动去除末尾 `/` |
| `api_key` | `str` | `""` | 字符串 | **读取接口脱敏**：GET 仅返回 `api_key_masked`（如 `sk-****abcd`）与 `has_api_key`；PUT 时若传空字符串或未传则保留原密钥，支持显式 `clear_api_key: true` 清空 |
| `model` | `str` | `"cloudflare-workers-ai/@cf/qwen/qwen3.8-27b"` | 非空字符串 | 视觉模型 ID |
| `timeout` | `int` | `45` | `5 <= timeout <= 300` | 单次请求超时秒数 |
| `prompt` | `str` | `DEFAULT_PROMPT` | 非空字符串，`len <= 4000` | 支持前端一键恢复默认 Prompt |

> **向后兼容策略**：
> - 读取时：若 `pipeline_config.json` 中 `vision` 字段缺失，自动回退读取 `DATA/vision_config.json`。
> - 保存时：更新 `pipeline_config.json` 的同时，同步把 `vision` 节写入 `DATA/vision_config.json`，确保任何外部脚本直接调用 `vision_filter.load_config(DATA)` 均获得最新配置。

### 3.4 X 账号白名单（`DATA/x_accounts.txt`）

- 保持原有行文本格式：每行一个账号（允许 `#` 注释行与空行，支持自动剥离 `@` 前缀）。
- 保存校验：非注释行去掉首尾空白与前导 `@` 后，必须匹配 `^[A-Za-z0-9_]{1,15}$`；若某行格式非法，API 返回 `400 Bad Request` 并指出具体行号与内容，拒绝写入损坏数据。

---

## 4. 后端 API 设计（`server.py` & `pipeline_config.py`）

### 4.1 `GET /api/pipeline/config`
返回当前生效的配置、默认值参考以及账号名单文本：
```json
{
  "scrape": { ... },
  "postprocess": { ... },
  "vision": {
    "enabled": true,
    "base_url": "https://sub.hhxxttxs.icu:8787",
    "has_api_key": true,
    "api_key_masked": "sk-****9f2a",
    "model": "cloudflare-workers-ai/@cf/qwen/qwen3.8-27b",
    "timeout": 45,
    "prompt": "..."
  },
  "defaults": {
    "vision_prompt": "你是一个图片库内容审核与标注助手..."
  },
  "accounts_text": "# 主力账号\naccount_a\naccount_b\n",
  "accounts_list": ["account_a", "account_b"],
  "accounts_count": 2,
  "updated_at": 1763539200
}
```

### 4.2 `PUT /api/pipeline/config`
保存配置与账号名单（支持全量或分块提交）：
- 请求体包含可选的 `scrape`、`postprocess`、`vision`（含可选明文 `api_key` 或 `clear_api_key`）、`accounts_text`。
- 校验通过后原子写入 `pipeline_config.json`、`vision_config.json` 及 `x_accounts.txt`，返回更新后的脱敏配置结构。

### 4.3 `GET /api/pipeline/status`
查询参数：`log_type`（可选：`x_scrape` | `x_scrape_runner` | `postprocess` | `postprocess_runner`，默认 `x_scrape`），`lines`（默认 `120`，上限 `500`）。

返回运行状态、游标进度、存量待处理统计与日志尾部：
```json
{
  "scrape": {
    "running": false,
    "cursor": 14,
    "accounts_count": 42,
    "next_account": "some_user",
    "last_run_ts": 1763535600
  },
  "postprocess": {
    "running": false,
    "missing_phash_count": 12,
    "untagged_vision_count": 85
  },
  "log": {
    "type": "x_scrape",
    "path": "x_scrape.log",
    "content": "[12:15:01] === 开始抓取 ... ===\n...",
    "updated_at": 1763535650
  }
}
```
- **锁状态探测（`running`）**：使用 `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` 非阻塞试探 `DATA/x_scrape.lock` 与 `DATA/postprocess.lock`。若获锁失败（`BlockingIOError` / `EAGAIN`）说明后台任务正在运行；若获锁成功则立即释放锁并返回 `running: false`。

### 4.4 `POST /api/pipeline/action`
执行运维动作：
- 请求体：`{"action": "run_scrape" | "dry_run_scrape" | "run_postprocess" | "dry_run_postprocess" | "reset_cursor" | "test_proxy"}`
- 行为说明：
  1. `reset_cursor`：若抓取未在运行，将 `DATA/x_scrape_state.json` 中的 `cursor` 重置为 `0`（保留 `accounts` 的 `seen_tweets` 断点不丢失）。
  2. `test_proxy`：使用当前保存或传入的 `proxy` 请求 `https://x.com/robots.txt`（10s 超时），返回 `{"ok": true/false, "status": 200, "elapsed_ms": 340, "error": ""}`。
  3. `run_scrape` / `run_postprocess`：先探测对应 `.lock`，若已在运行则返回 `409 Conflict`；否则调用 `bash x_scrape_cron.sh` 或 `bash library_postprocess_cron.sh`（脚本内部自带 `setsid nohup` 后台分离与 `flock` 互斥，立即返回 `{"ok": true, "message": "已投递后台执行"}`）。
  4. `dry_run_scrape` / `dry_run_postprocess`：以小批量参数同步或后台触发试运行（抓取：`--dry-run --batch 2 --limit 2`，超时 45s；后处理：`--dry-run`），直接返回试运行标准错误/输出摘要供管理员即时预览。

---

## 5. 管理员前端（`/admin/`）交互与界面设计

遵循 `/admin/` 现有原生 HTML/CSS/JS 架构与深浅色 CSS 变量体系（`--bg-elev`、`--border`、`--primary` 等），不引入第三方框架：

1. **导航栏入口**：
   - 在 `index.html` 左侧边栏 `.nav-group` 新增一项：
     `<div class="nav-item" data-nav="pipeline"><span>⚙ 采集与后处理</span><b id="badgePipeline" hidden>运行中</b></div>`
   - 切换至 `pipeline` 视图时，隐藏顶栏仅针对画廊生效的筛选控件（`[data-gallery-only="1"]`），展示 `#pipelineView` 主面板。

2. **页面四宫格/分栏布局（`#pipelineView`）**：
   - **顶部状态与快捷操作栏**：
     - 展示两个状态卡片：
       - **X 定时采集状态**：空闲/运行中徽标、轮转游标（`14 / 42`，下一顺位 `@xxx`）、按钮组：`[▶ 立即采集]`、`[🔍 试运行]`、`[↺ 重置游标]`。
       - **存量后处理状态**：空闲/运行中徽标、待回填指纹数（`N` 项）、待视觉标注数（`M` 项）、按钮组：`[▶ 立即后处理]`、`[🔍 试运行]`。
   - **左栏：参数配置表单**：
     - **卡片 1：X 定时抓取参数**：每轮账号数 `batch`、每账号推文上限 `limit`、视频上限 `max_mb`、默认入库标签 `tags`、代理地址 `proxy`（附 `[测试连通性]` 按钮）、请求超时 `timeout`、图片最小短边 `min_px`、最小体积 `min_img_kb`。
     - **卡片 2：存量后处理参数**：每轮视觉批大小 `batch`、每轮指纹回填上限 `phash_limit`、近似去重最大汉明距离 `max_dist`、完成标记标签 `ai_tag`、阶段开关（启用指纹去重 / 启用存量视觉补齐）。
     - **卡片 3：在线视觉模型配置**：启用开关 `enabled`、接口地址 `base_url`、模型名称 `model`、超时秒数 `timeout`、API Key 输入框（占位显示当前脱敏掩码 `sk-****xxxx`，留空不改动）、视觉审核 Prompt 多行文本域（附 `[恢复默认 Prompt]` 按钮）。
   - **右栏上：X 账号白名单编辑器**：
     - 显示有效账号计数徽标，提供等宽字体多行文本框编辑 `x_accounts.txt`，底部附格式提示（每行一个账号，支持 `#` 注释）。
   - **右栏下：实时日志查看器**：
     - 顶部 Tab 切换：`抓取日志 (x_scrape.log)` / `抓取进程 (runner)` / `后处理日志 (postprocess.log)` / `后处理进程 (runner)`，附 `[↻ 刷新日志]` 按钮与自动滚动到底部。
   - **底部/右上常驻保存栏**：
     - `[💾 保存全部配置]` 按钮，保存成功后弹出 Toast 提示并刷新状态面板。

---

## 6. 测试与验收计划

新增 `media-library/scripts/test_pipeline_config.py`，覆盖以下测试场景：
1. **默认配置与持久化**：空目录加载返回完整默认值；写入后再次读取字段一致；`vision_config.json` 同步写入并可被 `vision_filter.load_config()` 正确读取。
2. **API Key 脱敏与留空保留**：已配置 `api_key` 时，`GET /api/pipeline/config` 不泄露明文（仅返回掩码）；`PUT` 时 `api_key` 传空字符串保留原 Key，传新值则更新，传 `clear_api_key=True` 则清空。
3. **参数与账号名单校验**：负数 `batch`、越界 `max_dist`、非法 X 账号名（如含空格、超 15 字符、特殊符号）返回 HTTP 400 并携带明确错误说明，且不破坏原文件。
4. **优先级联动测试**：
   - 未传 CLI 与环境变量时，`x_scrape.py` 与 `library_postprocess.py` 自动采用 `pipeline_config.json` 中保存的参数。
   - 显式传入 CLI 参数（如 `--batch 3`）时覆盖配置文件参数。
5. **状态探测与游标重置**：
   - 模拟持有 `x_scrape.lock` 文件锁时，`GET /api/pipeline/status` 返回 `scrape.running == True`，且 `POST /api/pipeline/action` 触发 `run_scrape` 返回 `409`。
   - 调用 `reset_cursor` 后，`x_scrape_state.json` 中 `cursor == 0` 且原有 `accounts` 已见推文记录完好无损。
