#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在线视觉模型过滤与元数据生成模块。

通过 OpenAI 兼容接口（默认 cloudflare-workers-ai/@cf/qwen/qwen3.8-27b）
对抓取到的图片及视频抽帧拼图进行宽松女性人像识别，
同步生成中文画面标题与细分中文标签。
"""
import json
import os
import re

DEFAULT_BASE_URL = "https://sub.hhxxttxs.icu:8787"
DEFAULT_MODEL = "cloudflare-workers-ai/@cf/qwen/qwen3.8-27b"
DEFAULT_TIMEOUT = 45

DEFAULT_PROMPT = (
    "你是一个图片库内容审核与标注助手。请判断图片主体是否为女性人像（宽松标准："
    "包括真人摄影、自拍、写真、穿搭、街拍，以及二次元/插画女性角色；"
    "若输入为横向拼接的三联图，代表视频的前中后三个片段，只要视频主体为女性即保留）。\n"
    "以下情况请过滤（keep=false）：纯风景/建筑/美食/静物、纯文字或聊天截图、"
    "纯商品或广告海报、男性为主体、无法辨识人物的杂图。\n\n"
    "请仅返回严格合法的 JSON 对象，不要输出任何额外说明或 Markdown 标记：\n"
    '{"keep": true/false, "reason": "不超过20字的简短原因", '
    '"title": "6到15字的中文画面描述标题（过滤时可为空字符串）", '
    '"tags": ["3到5个中文标签，覆盖风格/穿搭/场景/画风，过滤时可为空数组"]}'
)


class VisionError(RuntimeError):
    """视觉识别配置缺失、接口异常或响应解析失败"""


def _parse_bool(val, default=True):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("0", "false", "no", "off"):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
    return default


def load_config(data_dir=None):
    """加载视觉配置，优先级：环境变量 > DATA/vision_config.json > 默认值"""
    file_cfg = {}
    if data_dir:
        cfg_path = os.path.join(data_dir, "vision_config.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    file_cfg = loaded
            except Exception as e:
                raise VisionError(f"读取 vision_config.json 失败: {e}") from e

    enabled_raw = os.environ.get("X_VISION_ENABLED")
    if enabled_raw is None:
        enabled = _parse_bool(file_cfg.get("enabled"), default=True)
    else:
        enabled = _parse_bool(enabled_raw, default=True)

    base_url = (
        os.environ.get("X_VISION_BASE_URL")
        or file_cfg.get("base_url")
        or DEFAULT_BASE_URL
    ).strip().rstrip("/")

    api_key = (
        os.environ.get("X_VISION_API_KEY")
        or file_cfg.get("api_key")
        or ""
    ).strip()

    model = (
        os.environ.get("X_VISION_MODEL")
        or file_cfg.get("model")
        or DEFAULT_MODEL
    ).strip()

    timeout_raw = os.environ.get("X_VISION_TIMEOUT")
    if timeout_raw is not None:
        try:
            timeout = int(timeout_raw)
        except ValueError as e:
            raise VisionError(f"无效的 X_VISION_TIMEOUT: {timeout_raw}") from e
    else:
        timeout = int(file_cfg.get("timeout") or DEFAULT_TIMEOUT)

    prompt = (
        os.environ.get("X_VISION_PROMPT")
        or file_cfg.get("prompt")
        or DEFAULT_PROMPT
    ).strip()

    return {
        "enabled": enabled,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout": max(5, timeout),
        "prompt": prompt,
    }


def parse_vision_response(raw):
    """解析模型返回文本，容错剥离 <think> 与 Markdown 代码块，严格校验字段"""
    if not raw or not isinstance(raw, str):
        raise VisionError("视觉模型返回为空")

    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    data = None
    try:
        data = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except Exception as e:
                raise VisionError(f"视觉模型 JSON 解析失败: {e}") from e
        else:
            raise VisionError(f"视觉模型未返回 JSON: {text[:120]}")

    if not isinstance(data, dict):
        raise VisionError("视觉模型返回格式非 JSON 对象")

    keep = data.get("keep")
    if not isinstance(keep, bool):
        raise VisionError(f"视觉模型缺少有效布尔字段 keep: {keep!r}")

    reason = str(data.get("reason") or "").strip()[:80]
    title = re.sub(r"\s+", " ", str(data.get("title") or "")).strip()[:30]

    tags_raw = data.get("tags") or []
    tags = []
    seen = set()
    if isinstance(tags_raw, list):
        for t in tags_raw:
            s = re.sub(r"[,，\s]+", "", str(t or "")).strip()[:12]
            if s and s.lower() not in seen:
                seen.add(s.lower())
                tags.append(s)
            if len(tags) >= 5:
                break

    return {
        "keep": keep,
        "reason": reason,
        "title": title,
        "tags": tags,
    }
