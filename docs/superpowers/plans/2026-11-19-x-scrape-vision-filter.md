# X 抓取视觉识别过滤与元数据生成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `x_scrape.py` 引入基于 OpenAI 兼容接口（`qwen3.8-27b`）的在线视觉识别模块，实现图片与视频（抽帧拼图）的宽松女性人像过滤，并自动生成中文标题与细分标签，API 异常时保留推文断点待下轮重试。

**Architecture:** 新增独立模块 `media-library/scripts/vision_filter.py` 封装配置加载（环境变量 + 运行数据目录 `vision_config.json`）、图片缩放编码、视频 `ffmpeg` 三联抽帧、API 请求与重试及 JSON 容错解析。`x_scrape.py` 在 `download_and_store()` 完成基础校验后、调用 `upload()` 前触发视觉判定，并新增 `--no-vision` 参数与 `skip_vision` 统计计数。

**Tech Stack:** Python 3 标准库 (`urllib.request`, `json`, `subprocess`, `base64`), Pillow, ffmpeg/ffprobe, pytest

---

### 文件映射

- Create: `media-library/scripts/vision_filter.py` — 视觉配置加载、图片/视频抽帧编码、OpenAI 兼容接口调用与结果解析
- Create: `media-library/scripts/test_vision_filter.py` — `vision_filter.py` 单元测试
- Modify: `media-library/scripts/x_scrape.py` — 集成视觉过滤、新增 `--no-vision` 参数、`skip_vision` 统计及配置预检
- Modify: `media-library/scripts/test_x_scrape.py` — 适配现有 fixture 并新增视觉过滤集成测试用例
- Modify: `media-library/SKILL.md` — 补充视觉识别环境变量与 `vision_config.json` 说明

---

### Task 1: 实现 `vision_filter.py` 配置加载与 JSON 容错解析

**Files:**
- Create: `media-library/scripts/vision_filter.py`
- Create: `media-library/scripts/test_vision_filter.py`

- [ ] **Step 1: 编写配置加载与 JSON 解析的失败测试**

在 `media-library/scripts/test_vision_filter.py` 写入：
```python
import json
from pathlib import Path
import pytest

import vision_filter as vf


def test_load_config_prefers_env_over_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "vision_config.json"
    cfg_file.write_text(json.dumps({
        "enabled": True,
        "base_url": "https://file.example.com",
        "api_key": "file-key",
        "model": "file-model",
        "timeout": 20,
    }), encoding="utf-8")

    monkeypatch.setenv("X_VISION_API_KEY", "env-key")
    monkeypatch.setenv("X_VISION_TIMEOUT", "60")
    monkeypatch.delenv("X_VISION_ENABLED", raising=False)

    cfg = vf.load_config(str(tmp_path))
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "https://file.example.com"
    assert cfg["api_key"] == "env-key"
    assert cfg["model"] == "file-model"
    assert cfg["timeout"] == 60


@pytest.mark.parametrize("raw,expected_keep,expected_title,expected_tags", [
    (
        '{"keep": true, "reason": "单人女性", "title": "海边白裙少女写真", "tags": ["海边", "连衣裙", "海边", "清纯"]}',
        True,
        "海边白裙少女写真",
        ["海边", "连衣裙", "清纯"],
    ),
    (
        '<think>分析画面中是一名女性...</think>\n```json\n{"keep": true, "reason": "ok", "title": " 室内温柔自拍 ", "tags": ["自拍", "室内", ""]}\n```',
        True,
        "室内温柔自拍",
        ["自拍", "室内"],
    ),
    (
        '{"keep": false, "reason": "纯风景照", "title": "", "tags": []}',
        False,
        "",
        [],
    ),
])
def test_parse_vision_response_valid(raw, expected_keep, expected_title, expected_tags):
    res = vf.parse_vision_response(raw)
    assert res["keep"] is expected_keep
    assert res["title"] == expected_title
    assert res["tags"] == expected_tags


@pytest.mark.parametrize("raw", [
    "",
    "not json",
    '{"keep": "yes", "title": "abc"}',
    '{"reason": "missing keep"}',
])
def test_parse_vision_response_invalid_raises(raw):
    with pytest.raises(vf.VisionError):
        vf.parse_vision_response(raw)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest -v media-library/scripts/test_vision_filter.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'vision_filter'`)

- [ ] **Step 3: 实现 `vision_filter.py` 的配置加载、Prompt 与解析逻辑**

在 `media-library/scripts/vision_filter.py` 写入基础结构、`VisionError`、`load_config`、`parse_vision_response`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest -v media-library/scripts/test_vision_filter.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add media-library/scripts/vision_filter.py media-library/scripts/test_vision_filter.py
git commit -m "feat(vision): 添加视觉过滤配置加载与响应解析"
```

---

### Task 2: 实现图片缩放编码与视频三联抽帧编码

**Files:**
- Modify: `media-library/scripts/vision_filter.py`
- Modify: `media-library/scripts/test_vision_filter.py`

- [ ] **Step 1: 编写图片缩放编码与视频抽帧的失败测试**

在 `media-library/scripts/test_vision_filter.py` 追加：
- `test_encode_image_resizes_large_image`：构造 2000x1000 测试图，验证缩放后长边 ≤ 768px 且返回有效 `data:image/jpeg;base64,...`。
- `test_encode_video_frames_triplet_and_fallback`：mock `subprocess.run` 与时长探测，验证正常视频生成横向拼接三联图，短片/探测失败时降级抽首帧。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest -v media-library/scripts/test_vision_filter.py`
Expected: FAIL (`AttributeError: module 'vision_filter' has no attribute 'encode_image_base64'`)

- [ ] **Step 3: 实现 `encode_image_base64` 与 `encode_video_frames_base64`**

在 `media-library/scripts/vision_filter.py` 实现图片 Pillow 缩放编码与视频 `ffprobe` + `ffmpeg` 三联抽帧（含单帧降级与临时目录清理）。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest -v media-library/scripts/test_vision_filter.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add media-library/scripts/vision_filter.py media-library/scripts/test_vision_filter.py
git commit -m "feat(vision): 实现图片缩放与视频三联抽帧编码"
```

---

### Task 3: 实现 OpenAI 兼容视觉接口调用与重试

**Files:**
- Modify: `media-library/scripts/vision_filter.py`
- Modify: `media-library/scripts/test_vision_filter.py`

- [ ] **Step 1: 编写 API 调用成功、重试与异常测试**

在 `media-library/scripts/test_vision_filter.py` 追加：
- `test_call_vision_api_success`：mock `urllib.request.urlopen` 返回 OpenAI chat completions 格式，验证请求 URL、Authorization header、model 及返回解析结果。
- `test_call_vision_api_retries_once_on_transient_error`：首次 502/超时，第二次成功，验证重试 1 次后成功返回。
- `test_call_vision_api_raises_after_retry_exhausted`：连续失败抛出 `VisionError`。
- `test_analyze_media_requires_api_key`：开启状态缺 `api_key` 时抛出 `VisionError`。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest -v media-library/scripts/test_vision_filter.py`
Expected: FAIL

- [ ] **Step 3: 实现 `call_vision_api` 与统一入口 `analyze_media`**

在 `media-library/scripts/vision_filter.py` 实现 `call_vision_api` 和 `analyze_media(path, kind, config)`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest -v media-library/scripts/test_vision_filter.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add media-library/scripts/vision_filter.py media-library/scripts/test_vision_filter.py
git commit -m "feat(vision): 实现 OpenAI 兼容视觉接口调用与重试"
```

---

### Task 4: 集成到 `x_scrape.py` 与更新文档

**Files:**
- Modify: `media-library/scripts/x_scrape.py`
- Modify: `media-library/scripts/test_x_scrape.py`
- Modify: `media-library/SKILL.md`

- [ ] **Step 1: 编写 `x_scrape.py` 视觉过滤集成测试**

在 `media-library/scripts/test_x_scrape.py`：
- 更新 `scraper` fixture 默认关闭视觉过滤（`monkeypatch.setenv("X_VISION_ENABLED", "0")`）以保持现有 32 条基础测试语义不变。
- 更新 `stats()` 辅助函数包含 `"skip_vision": 0`。
- 新增 3 个核心集成测试：
  1. `test_vision_keep_uses_generated_title_and_tags`：开启视觉过滤且 `keep=True`，验证 `upload()` 收到生成的 `title` 和合并去重后的 `tags`，`stats["new"] == 1`，推文记入 `seen_tweets`。
  2. `test_vision_reject_skips_upload_and_marks_seen`：`keep=False`，验证不调用 `upload()`，`stats["skip_vision"] == 1`，推文记入 `seen_tweets`。
  3. `test_vision_error_fails_without_marking_seen`：视觉接口抛出 `VisionError`，验证不调用 `upload()`，`stats["fail"] == 1`，推文**不**记入 `seen_tweets`（留待下轮重试）。
  4. `test_no_vision_flag_bypasses_vision_filter`：传入 `--no-vision` 时绕过视觉检查直接入库。

- [ ] **Step 2: 运行测试验证新测试失败**

Run: `pytest -v media-library/scripts/test_x_scrape.py -k vision`
Expected: FAIL

- [ ] **Step 3: 修改 `x_scrape.py` 集成 `vision_filter`**

在 `media-library/scripts/x_scrape.py`：
- 引入 `vision_filter`
- 新增 `--no-vision` CLI 参数
- `main()` 中非 `--dry-run` 且启用视觉识别时校验配置（缺少 `api_key` 返回非零退出码 `5` 并写日志）
- `stats` 初始化新增 `"skip_vision": 0`
- `download_and_store()` 在 `verify_image` / 视频大小检查通过后调用 `vision_filter.analyze_media()`：
  - 异常：`log` 错误，`stats["fail"] += 1`，返回 `False`
  - `not res["keep"]`：`log` 跳过原因，`stats["skip_vision"] += 1`，返回 `True`
  - `res["keep"]`：使用 `res["title"] or f"@{account} X"`，合并 `res["tags"]` 与基础标签（去重保序），再调用 `upload()`

- [ ] **Step 4: 更新 `media-library/SKILL.md`**

补充 `X_VISION_ENABLED`、`X_VISION_BASE_URL`、`X_VISION_API_KEY`、`X_VISION_MODEL`、`X_VISION_TIMEOUT` 及 `vision_config.json` 说明。

- [ ] **Step 5: 运行全部测试验证通过**

Run: `pytest -v media-library/scripts/test_vision_filter.py media-library/scripts/test_x_scrape.py media-library/scripts/test_server.py`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add media-library/scripts/x_scrape.py media-library/scripts/test_x_scrape.py media-library/SKILL.md
git commit -m "feat(x-scrape): 集成在线视觉过滤与标题标签自动生成"
```
