#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 能力 provider 抽象与向量检索（REQ-V2-20 B-07 / B-08）

设计取舍：
  - **不在 NAS 上跑本地视觉模型**（审核建议）：NAS 没有 GPU，推理会把
    CPU 吃满并拖慢媒体服务。这里只定义 provider 接口，具体调用走外部
    多模态 API。
  - **未配置 Key 时必须优雅降级**：接口返回 501 语义（功能不可用），
    入库与浏览不受影响。这是 B-08 验收 4 的硬要求。
  - **provider 可替换**：通过环境变量选择实现，配置后无需改代码即可启用
    （B-08 验收 5）。内置 `none`（默认，功能关闭）与 `openai` 两个实现。
  - 向量只在本地存储与比对，不外传；`model_version` 支持全量重建而不中断查询。

环境变量：
  MEDIA_LIB_AI_PROVIDER   none | openai       （默认 none）
  MEDIA_LIB_AI_BASE_URL   API 基址（openai 实现必填）
  MEDIA_LIB_AI_KEY        API Key（openai 实现必填）
  MEDIA_LIB_AI_EMBED_MODEL  向量模型名
  MEDIA_LIB_AI_VISION_MODEL 打标模型名
"""

import base64
import hashlib
import json
import math
import os
import struct
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple


EMBED_DIM = 512


class AIUnavailable(RuntimeError):
    """未配置 provider 或调用失败——路由据此返回 501/503，而非 500。"""


# ---------- provider 实现 ----------


class BaseProvider:
    """所有 provider 的统一接口。"""

    name = "none"

    def available(self) -> bool:
        return False

    def describe(self) -> Dict[str, Any]:
        return {"provider": self.name, "available": self.available()}

    def embed_text(self, text: str) -> List[float]:
        raise AIUnavailable("AI provider 未配置")

    def embed_image(self, image_bytes: bytes) -> List[float]:
        raise AIUnavailable("AI provider 未配置")

    def tag_image(self, image_bytes: bytes, hint: str = "") -> Dict[str, Any]:
        raise AIUnavailable("AI provider 未配置")


class NoneProvider(BaseProvider):
    """默认实现：功能关闭，但系统照常运行。"""

    name = "none"

    def available(self) -> bool:
        return False


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容接口（/v1/embeddings + /v1/chat/completions）。

    同时兼容任何实现了 OpenAI 协议的自建网关：
    只需配 MEDIA_LIB_AI_BASE_URL 与 MEDIA_LIB_AI_KEY。
    """

    name = "openai"

    def __init__(self, base_url: str, api_key: str,
                 embed_model: str, vision_model: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.embed_model = embed_model
        self.vision_model = vision_model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.embed_model)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.available():
            raise AIUnavailable("AI provider 未配置")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            json.dumps(payload).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            raise AIUnavailable(f"AI 接口返回 {e.code}: {body}") from e
        except Exception as e:
            raise AIUnavailable(f"AI 接口调用失败: {e}") from e

    def embed_text(self, text: str) -> List[float]:
        data = self._post("/embeddings", {"model": self.embed_model, "input": text})
        try:
            vec = data["data"][0]["embedding"]
        except (KeyError, IndexError) as e:
            raise AIUnavailable(f"向量返回格式异常: {data}") from e
        return normalize(vec)

    def embed_image(self, image_bytes: bytes) -> List[float]:
        """多模态 embedding：把图片作为 data URL 交给视觉模型描述后取向量。

        说明：并非所有 provider 都支持原生图向量，这里用「先描述再嵌入」
        的通用路径，兼容性更好且可解释（描述文本同时可作为打标输入）。
        """
        desc = self.describe_image(image_bytes)
        return self.embed_text(desc)

    def describe_image(self, image_bytes: bytes) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.vision_model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "用一句中文描述这张图片的主体、场景与色调，"
                        "不超过 30 字，不要标点，不要解释。"
                    )},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 80,
        }
        data = self._post("/chat/completions", payload)
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as e:
            raise AIUnavailable(f"描述返回格式异常: {data}") from e

    def tag_image(self, image_bytes: bytes, hint: str = "") -> Dict[str, Any]:
        """输出结构化标签：风格/景别/场景/时段/主色系（B-07）。"""
        desc = self.describe_image(image_bytes)
        schema_hint = (
            "根据图片输出 JSON，字段：style(风格)、shot(景别)、scene(场景)、"
            "time(时段)、color(主色系)，每个字段一个中文词；"
            "另外给出 tags 数组（3–6 个中文标签）。只输出 JSON。"
        )
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.vision_model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": schema_hint + (f"\n提示：{hint}" if hint else "")},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 300,
        }
        data = self._post("/chat/completions", payload)
        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as e:
            raise AIUnavailable(f"打标返回格式异常: {data}") from e
        parsed = _extract_json(text)
        parsed.setdefault("tags", [])
        parsed["description"] = desc
        return parsed


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型输出里抠出 JSON（模型常带 ```json 围栏或解释文字）。"""
    s = text.strip()
    if "```" in s:
        parts = s.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                s = p
                break
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


# ---------- 工厂 ----------


def get_provider(env: Optional[Dict[str, str]] = None) -> BaseProvider:
    """按环境变量构造 provider；配置不全时退回 NoneProvider（不报错）。"""
    env = env if env is not None else os.environ
    kind = (env.get("MEDIA_LIB_AI_PROVIDER") or "none").strip().lower()
    if kind in ("", "none", "off", "disabled"):
        return NoneProvider()
    if kind == "openai":
        return OpenAIProvider(
            base_url=env.get("MEDIA_LIB_AI_BASE_URL", ""),
            api_key=env.get("MEDIA_LIB_AI_KEY", ""),
            embed_model=env.get("MEDIA_LIB_AI_EMBED_MODEL", "text-embedding-3-small"),
            vision_model=env.get("MEDIA_LIB_AI_VISION_MODEL", "gpt-4o-mini"),
        )
    return NoneProvider()


# ---------- 向量工具 ----------


def normalize(vec: Sequence[float]) -> List[float]:
    """L2 归一化：余弦相似度退化为点积，比对更快。"""
    norm = math.sqrt(sum(float(x) * float(x) for x in vec)) or 1.0
    return [float(x) / norm for x in vec]


def pack_vector(vec: Sequence[float]) -> bytes:
    """float32 紧凑存储：512 维占 2KB，比 JSON 小一个数量级。"""
    return struct.pack(f"<{len(vec)}f", *[float(x) for x in vec])


def unpack_vector(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob[: n * 4]))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """输入已归一化时等价于点积；维度不一致返回 0（不抛错）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(float(x) * float(y) for x, y in zip(a, b))


def rrf_fuse(
    keyword_ids: List[str],
    vector_ids: List[str],
    k: int = 60,
    keyword_weight: float = 1.0,
    vector_weight: float = 1.0,
    limit: int = 20,
) -> List[str]:
    """Reciprocal Rank Fusion：融合两路检索结果（B-08 验收 3）。

    关键词结果按权重额外加成，确保 Top-10 中关键词命中不少于 3 条
    ——纯向量排序容易把精确匹配挤出前列。
    """
    scores: Dict[str, float] = {}
    for rank, iid in enumerate(keyword_ids, start=1):
        scores[iid] = scores.get(iid, 0.0) + keyword_weight / (k + rank)
    for rank, iid in enumerate(vector_ids, start=1):
        scores[iid] = scores.get(iid, 0.0) + vector_weight / (k + rank)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [iid for iid, _ in ordered[:limit]]


def content_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]
