# X 抓取视觉识别过滤与元数据生成设计

**日期**：2026-11-19
**状态**：待评审
**关联模块**：`media-library/scripts/x_scrape.py`、`media-library/scripts/x_scrape_cron.sh`、新增 `media-library/scripts/vision_filter.py`

## 1. 背景与目标

当前 `x_scrape.py` 仅通过像素（短边 ≥ 320px）与体积（图片 ≥ 20KB、视频 ≤ 30MB）做基础校验后即直接入库，缺少内容语义识别能力，导致非目标图片/视频（如纯风景、文字截图、广告海报、男性主体等）进入图库，且入库标题统一为 `@account X`、标签固定为 `X抓取,人物`（或附加 `X视频`），不利于后续搜索与筛选。

本次优化在抓取入库前引入在线视觉模型（OpenAI 兼容接口，默认模型 `cloudflare-workers-ai/@cf/qwen/qwen3.8-27b`），实现：
1. **内容过滤**：按“宽松女性人像”标准过滤图片与视频，仅保留主体为女性的媒体。
2. **元数据生成**：同步生成纯画面描述的中文标题与细分中文标签，提升 `/app/` 浏览与 FTS5 检索体验。
3. **可靠重试**：视觉接口异常时不污染 `seen_tweets` 断点，留待下轮定时任务自动重试。

## 2. 整体架构（抓取端前置过滤）

```text
x_scrape.py 下载媒体并完成基础校验（图片像素/体积、视频体积上限）
   │
   ├─[--no-vision 或 视觉开关关闭]───────────────────────────────┐
   │                                                               ▼
   └─[开启视觉识别]──▶ vision_filter.py
                         ├─ 图片：Pillow 缩放至长边 ≤ 768px → JPEG base64
                         ├─ 视频：ffmpeg 抽 20%/50%/80% 三帧拼图（失败降级首帧）→ JPEG base64
                         ▼
                    POST {base_url}/v1/chat/completions
                         │
                         ├─ API/网络/解析异常 ──▶ 返回 error，fail+1，推文不记入 seen_tweets（下轮重试）
                         ├─ keep == false     ──▶ 记录 reason 日志，skip_vision+1，不入库，推文记入 seen
                         └─ keep == true      ──▶ 使用生成 title + 合并去重 tags → POST /api/upload 入库
```

- **服务端零改动**：完全复用现有 `POST /api/upload` 接口，不修改 `server.py` 与数据库表结构。
- **`--dry-run` 零开销**：试运行模式不下载媒体，也不调用视觉 API。

## 3. 核心模块设计

### 3.1 `media-library/scripts/vision_filter.py`

独立无状态工具模块，仅依赖 Python 标准库、`Pillow` 及系统 `ffmpeg`/`ffprobe`，不引入额外第三方 SDK。

#### 配置加载优先级
1. 环境变量（最高优先级）：
   - `X_VISION_ENABLED`：是否启用，默认 `"1"`（`"0"`/`"false"`/`"no"` 为关闭）
   - `X_VISION_BASE_URL`：接口基地址，默认 `"https://sub.hhxxttxs.icu:8787"`
   - `X_VISION_API_KEY`：鉴权密钥（**禁止硬编码或提交 Git**）
   - `X_VISION_MODEL`：模型 ID，默认 `"cloudflare-workers-ai/@cf/qwen/qwen3.8-27b"`
   - `X_VISION_TIMEOUT`：单次请求超时秒数，默认 `45`
   - `X_VISION_PROMPT`：可选自定义判定提示词，覆盖默认规则
2. 运行数据目录配置文件：`{MEDIA_LIB_DIR}/vision_config.json`（不纳入 Git 版本库），字段结构与环境变量对应（`enabled`、`base_url`、`api_key`、`model`、`timeout`、`prompt`），便于 NAS 运行环境独立维护密钥与微调 Prompt。

当视觉过滤处于启用状态但 `api_key` 为空时，启动阶段或调用阶段明确报错并返回非零退出码，不静默放行。

#### 媒体预处理
- **图片预处理**：用 Pillow 打开并自动处理 EXIF 方向（`ImageOps.exif_transpose`），转为 `RGB`，按比例缩放至长边不超过 `768px`，编码为 JPEG（`quality=82`）并转 `data:image/jpeg;base64,...`。入库仍使用原始文件，保证画质无损。
- **视频抽帧**：
  1. 用 `ffprobe` 获取视频时长 `duration`。
  2. 若 `duration > 1.0` 秒，在 `0.2 * duration`、`0.5 * duration`、`0.8 * duration` 位置各抽取 1 帧并缩放至等高（高度 `360px`），横向拼接为 1 张三联图（JPEG）。
  3. 若 `ffprobe` 失败或视频过短，降级使用 `ffmpeg` 抽取首帧（长边 ≤ `768px`）。
  4. 单条视频仅发起 **1 次**视觉 API 调用，控制延迟与费用。

#### Prompt 与输出契约
要求模型以严格 JSON 格式返回：
```json
{
  "keep": true,
  "reason": "单人女性室内自拍",
  "title": "室内温柔日常自拍",
  "tags": ["自拍", "室内", "清纯", "日常"]
}
```
判定标准（宽松女性人像过滤）：
- **保留 (`keep: true`)**：画面主体为女性（单人或多人女性主体，不限真人摄影、写真、穿搭、自拍或二次元/插画女性角色）。
- **过滤 (`keep: false`)**：纯风景/建筑/美食/静物、纯文字或聊天截图、商品/广告海报、男性为主体、无法辨识人物的杂图。
- **视频补充说明**：提示词告知模型若输入为三联拼图，则代表视频的前中后三个片段，只要视频主体为女性即判定 `keep: true`。

#### 结果校验与容错
- 清理模型返回中可能包含的 `<think>...</think>` 推理块或 ` ```json ... ``` ` 包裹，再做 `json.loads`。
- 校验 `keep` 必须为布尔值（不接受模糊字符串）。
- `title` 清洗空白并限制长度（如 ≤ 30 字符）；若模型返回空标题，兜底使用 `@{account} X`。
- `tags` 清洗空白与特殊字符，去重后最多保留 5 个，每条 ≤ 12 字符，再与基础标签（`X抓取,人物` 及视频 `X视频`）合并去重。
- 对网络超时、HTTP 429、HTTP 5xx 最多自动重试 1 次（短暂退避 2 秒）；仍失败则向上抛出异常或返回错误结构。

### 3.2 `media-library/scripts/x_scrape.py` 集成

1. **CLI 参数**：
   - 新增 `--no-vision` 参数，显式跳过视觉过滤（用于紧急排障或对比测试）。
2. **启动检查**：
   - 非 `--dry-run` 且启用视觉过滤时，在抓取循环前校验配置完整性（如 `api_key` 是否已配置），避免跑完代理抓取才发现缺 Key。
3. **抓取统计字段**：
   - `stats` 新增 `"skip_vision": 0`，在每轮结束摘要 JSON 中一并输出，便于在 `x_scrape.log` 观测过滤量。
4. **断点语义保持不变**：
   - `keep == False` 视为“已正常处理的跳过项”，`download_and_store()` 返回 `True`，该推文若无其他失败媒体则记入 `seen_tweets`。
   - 视觉 API 调用失败（网络、鉴权、429/5xx、JSON 解析失败）时，`stats["fail"] += 1`，`download_and_store()` 返回 `False`，推文**不**记入 `seen_tweets`，留待下轮定时任务重试。

### 3.3 `media-library/scripts/x_scrape_cron.sh`

- 若使用环境变量方式配置，可在 shell 层透传（或直接由 `vision_filter.py` 从 `DATA/vision_config.json` 与环境变量读取，shell 无需硬编码任何密钥）。

## 4. 风险与应对

| 风险 | 应对措施 |
|---|---|
| 视觉 API 偶发返回非标准 JSON 或思考标签 | 解析器剥离 `<think>` 与 Markdown 代码块后提取 JSON；仍失败则视为异常，留待下轮重试 |
| 单轮抓取耗时增加触发锁冲突 | `x_scrape_cron.sh` 已通过 `setsid` + `flock -n` 互斥运行，单条调用设 45s 超时避免无限卡死 |
| 敏感 API Key 泄露 | Key 仅存于 NAS 运行数据目录 `vision_config.json` 或环境变量，仓库内仅保留配置示例与说明 |
| `ffmpeg` 在测试或精简环境缺失 | 视频抽帧逻辑封装独立函数，单元测试通过 mock 覆盖；运行环境验证 `ffmpeg` 可用性 |

## 5. 测试与验收计划

1. **单元测试（`media-library/scripts/test_vision_filter.py` & `test_x_scrape.py`）**：
   - 图片缩放与 base64 编码逻辑测试。
   - 视频三联抽帧命令构造与降级首帧逻辑测试（mock `subprocess`）。
   - JSON 解析容错测试（纯 JSON、Markdown 代码块、带 `<think>` 标签、非法响应抛错）。
   - `x_scrape.py` 集成测试（mock 视觉接口与上传接口）：
     - `keep=true`：验证生成标题与合并标签正确入库，推文记入 `seen_tweets`。
     - `keep=false`：验证不调用上传接口、`skip_vision` 递增、推文记入 `seen_tweets`。
     - API 异常：验证不调用上传接口、`fail` 递增、推文**不**记入 `seen_tweets`。
2. **线上部署后验收**：
   - NAS `git pull` 并同步到技能目录，在运行数据目录写入 `vision_config.json`（含 API Key）。
   - 执行 `x_scrape_cron.sh --dry-run --batch 1 --limit 1` 验证基础链路。
   - 执行一次真实小批量抓取（`--batch 1 --limit 2`），检查 `x_scrape.log` 中的视觉过滤日志、生成标题/标签以及 `/app/` 实际入库效果。
