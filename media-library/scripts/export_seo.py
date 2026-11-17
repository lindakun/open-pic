#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出与 SEO 支持（REQ-V2-20 C-13 / E-19）

本模块刻意与 server.py 解耦，只依赖 db 与 media_proc，便于单测。

- ExportService：多规格导出 + 流式 ZIP + credits.txt / metadata.json
- slug 生成与冲突消解
- JSON-LD / sitemap.xml / robots.txt 生成
"""

import io
import json
import os
import re
import tempfile
import time
import unicodedata
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow 是硬依赖，缺失时导出降级
    Image = None  # type: ignore


# 导出预设：长边像素（None = 原图）
EXPORT_PRESETS: Dict[str, Optional[int]] = {
    "original": None,
    "2560": 2560,
    "1920": 1920,
    "1280": 1280,
    "640": 640,
}

SUPPORTED_FORMATS = ("jpeg", "webp", "avif", "png")

# 异步阈值（C-13 验收：>20 项或 >200MB 转异步）
ZIP_SYNC_MAX_ITEMS = 20
ZIP_SYNC_MAX_BYTES = 200 * 1024 * 1024

# EXIF 隐私字段：对外导出副本必须剥离（C-11）
_STRIP_EXIF_IDS = {
    0x0112,  # Orientation 保留在像素重采样后已无意义
    0x8825,  # GPSInfo
    0xA430,  # CameraOwnerName
    0xA431,  # BodySerialNumber
    0xA435,  # LensSerialNumber
}


# ---------- slug（E-19） ----------

_PINYIN_FALLBACK = {
    # 常见字的最小映射，避免为内网部署引入完整拼音词典依赖。
    # 未覆盖的字直接丢弃，slug 仍能靠 shortId 保证唯一可访问。
}


def _slugify_ascii(text: str) -> str:
    """把任意标题转为 URL 安全 slug。

    中文无拼音表时退化为空，此时 slug 只保留 ASCII 部分；
    资产页始终带 shortId 保证唯一，故空 slug 不影响可访问性。
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    # 只保留字母数字与分隔符
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = "".join(_PINYIN_FALLBACK.get(c, c) for c in text)
    # 中文在无拼音表时无法进入 URL，剔除
    text = re.sub(r"[\u4e00-\u9fff]+", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:60].strip("-")


def build_slug(title: str, item_id: str, existing: Iterable[str] = ()) -> str:
    """生成唯一 slug；冲突时追加序号而非报错（E-19 验收 1）。"""
    base = _slugify_ascii(title) or "asset"
    taken = set(existing)
    if base not in taken:
        return base
    short = item_id[:6]
    candidate = f"{base}-{short}"
    if candidate not in taken:
        return candidate
    n = 2
    while f"{candidate}-{n}" in taken:
        n += 1
    return f"{candidate}-{n}"


def asset_path(slug: str, item_id: str) -> str:
    """资产页路径：/a/{slug}-{shortId}（E-19）。"""
    s = slug or "asset"
    return f"/a/{s}-{item_id[:8]}"


# ---------- 导出（C-13） ----------


def _open_source(files_dir: str, item: Dict[str, Any]):
    path = os.path.join(files_dir, item["file"])
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


def render_variant(
    files_dir: str,
    item: Dict[str, Any],
    preset: str = "original",
    fmt: str = "jpeg",
    quality: int = 85,
) -> Tuple[bytes, str]:
    """按预设长边与格式渲染导出副本，返回 (bytes, 扩展名)。

    - preset=original 且 fmt 与原图一致时直接返回原字节（不重编码，避免画质损失）
    - EXIF 剥离：只对重新编码的副本生效；原图字节不受影响（C-11 验收）
    """
    # fmt 为空表示"保持原格式"（旧契约：原图直出，文件名不变）
    if not fmt:
        if EXPORT_PRESETS.get(preset) is None:
            src = _open_source(files_dir, item)
            with open(src, "rb") as fh:
                return fh.read(), os.path.splitext(src)[1].lstrip(".").lower() or "bin"
        fmt = "jpeg"
    if fmt not in SUPPORTED_FORMATS:
        fmt = "jpeg"
    if preset not in EXPORT_PRESETS:
        preset = "original"
    quality = max(40, min(100, int(quality)))

    src = _open_source(files_dir, item)
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    ext_norm = "jpeg" if ext == "jpg" else ext

    # 原图直出：仅当不需要缩放与转码
    if EXPORT_PRESETS[preset] is None and fmt == ext_norm:
        with open(src, "rb") as fh:
            return fh.read(), f"jpg" if fmt == "jpeg" else fmt

    if Image is None:
        with open(src, "rb") as fh:
            return fh.read(), ext or "jpg"

    im = Image.open(src)
    im.load()

    long_edge = EXPORT_PRESETS[preset]
    if long_edge and max(im.size) > long_edge:
        ratio = long_edge / max(im.size)
        new_size = (max(1, round(im.width * ratio)), max(1, round(im.height * ratio)))
        im = im.resize(new_size, Image.LANCZOS)

    out_ext = "jpg" if fmt == "jpeg" else fmt
    buf = io.BytesIO()

    # 剥离隐私 EXIF：重建图像对象，不复制 info/exif。
    # PNG 保留透明通道（RGBA/LA/P）；其余格式必须转 RGB，
    # 否则 JPEG 无法保存 alpha，会报错或出现黑底。
    if fmt == "png":
        clean = im if im.mode in ("RGB", "RGBA", "L", "LA", "P") else im.convert("RGBA")
    else:
        clean = im if im.mode in ("RGB", "L") else im.convert("RGB")
    if fmt in ("jpeg", "webp", "avif"):
        if clean.mode != "RGB":
            clean = clean.convert("RGB")
        if fmt == "jpeg":
            clean.save(buf, format="JPEG", quality=quality, optimize=True)
        elif fmt == "webp":
            clean.save(buf, format="WEBP", quality=quality, method=4)
        else:  # avif：Pillow ≥9.1 支持；缺失时回退 WebP（A-05 同样的降级策略）
            try:
                clean.save(buf, format="AVIF", quality=quality)
            except Exception:
                buf = io.BytesIO()
                out_ext = "webp"
                clean.save(buf, format="WEBP", quality=quality, method=4)
    else:  # png
        clean.save(buf, format="PNG", optimize=True)

    return buf.getvalue(), out_ext


def credits_text(items: List[Dict[str, Any]], base_url: str = "") -> str:
    """生成 credits.txt（C-13 验收 1：标题、作者、许可、URL）。"""
    lines = ["MediaLib 导出署名清单", "=" * 32, ""]
    for it in items:
        lines.append(f"标题：{it.get('title') or it.get('name') or it.get('id')}")
        lines.append(f"作者：{it.get('author') or it.get('credit') or '未标注'}")
        lic = it.get("license") or "未声明"
        lines.append(f"许可：{lic}")
        if it.get("license_url"):
            lines.append(f"许可地址：{it['license_url']}")
        if it.get("copyright_holder"):
            lines.append(f"版权方：{it['copyright_holder']}")
        if base_url:
            lines.append(f"URL：{base_url.rstrip('/')}{asset_path(it.get('slug', ''), it['id'])}")
        lines.append(f"文件：{it.get('name') or it.get('file')}")
        lines.append("")
    return "\n".join(lines)


def metadata_json(items: List[Dict[str, Any]]) -> str:
    payload = {
        "generator": "MediaLib",
        "exported_at": int(time.time()),
        "count": len(items),
        "items": [
            {
                "id": it.get("id"),
                "title": it.get("title"),
                "author": it.get("author"),
                "license": it.get("license"),
                "license_url": it.get("license_url"),
                "commercial_ok": bool(it.get("commercial_ok", 1)),
                "width": it.get("width"),
                "height": it.get("height"),
                "file": it.get("name") or it.get("file"),
            }
            for it in items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_arc_stem(name: str, fallback: str) -> str:
    """把用户文件名清洗成安全的 ZIP 条目名。

    只取 basename 并剔除路径分隔符/控制字符：multipart 上传的文件名
    完全由客户端提供，带 `../` 的条目会在解压时写到目标目录之外。
    """
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", stem).strip(" .")
    return stem or fallback


def build_zip_to_path(
    files_dir: str,
    items: List[Dict[str, Any]],
    out_path: str,
    preset: str = "jpeg",
    fmt: str = "jpeg",
    quality: int = 85,
    base_url: str = "",
) -> Dict[str, Any]:
    """把导出包写到磁盘（C-13：不再全内存打包）。

    返回 {count, bytes, failures}。单条失败不中断整体导出。
    """
    used: Dict[str, int] = {}
    failures: List[str] = []
    written = 0

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for it in items:
            try:
                data, ext = render_variant(files_dir, it, preset=preset, fmt=fmt, quality=quality)
            except Exception as e:  # 单条失败只记录，不影响整包
                failures.append(f"{it.get('id')}: {e}")
                continue
            stem = _safe_arc_stem(it.get("name") or it["file"], it["id"])
            arcname = f"{stem}.{ext}"
            if arcname in used:
                # 序号也要继续探测，避免 _1 已被另一个同名文件占用
                n = used[arcname] + 1
                while f"{stem}_{n}.{ext}" in used:
                    n += 1
                used[arcname] = n
                arcname = f"{stem}_{n}.{ext}"
            used.setdefault(arcname, 0)
            zf.writestr(arcname, data)
            written += 1

        # 署名与元数据始终附在包内（C-13 验收 1）
        zf.writestr("credits.txt", credits_text(items, base_url=base_url))
        zf.writestr("metadata.json", metadata_json(items))

    return {"count": written, "bytes": os.path.getsize(out_path), "failures": failures}


def build_zip_memory(
    files_dir: str,
    items: List[Dict[str, Any]],
    preset: str = "original",
    fmt: str = "jpeg",
    quality: int = 85,
    base_url: str = "",
) -> bytes:
    """小批量同步导出：写临时文件再读回，避免全内存拼装大包。"""
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        build_zip_to_path(
            files_dir, items, tmp, preset=preset, fmt=fmt, quality=quality, base_url=base_url
        )
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def needs_async(items: List[Dict[str, Any]], total_bytes: int) -> bool:
    """是否转异步任务（C-13：>20 项或 >200MB）。"""
    return len(items) > ZIP_SYNC_MAX_ITEMS or total_bytes > ZIP_SYNC_MAX_BYTES


# ---------- SEO（E-19） ----------


def jsonld_for_item(item: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    """生成 schema.org ImageObject / VideoObject + BreadcrumbList。"""
    base = base_url.rstrip("/")
    is_video = item.get("kind") == "video"
    content_url = f"{base}/f/{item.get('file', '')}"
    data: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "VideoObject" if is_video else "ImageObject",
        "name": item.get("title") or item.get("name") or item.get("id"),
        "contentUrl": content_url,
        "thumbnailUrl": f"{base}/t/{item.get('id')}.jpg",
        "uploadDate": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(item.get("ts", 0))),
        "identifier": item.get("id"),
    }
    if item.get("width") and item.get("height"):
        data["width"] = {"@type": "QuantitativeValue", "value": item["width"]}
        data["height"] = {"@type": "QuantitativeValue", "value": item["height"]}
    if is_video and item.get("duration"):
        data["duration"] = f"PT{int(item['duration'])}S"
    if item.get("author"):
        data["creator"] = {"@type": "Person", "name": item["author"]}
    if item.get("license"):
        data["license"] = item.get("license_url") or item["license"]
    if item.get("copyright_holder"):
        data["copyrightHolder"] = {"@type": "Organization", "name": item["copyright_holder"]}
    if item.get("dominant_color"):
        data["color"] = item["dominant_color"]
    if item.get("tags"):
        data["keywords"] = ",".join(item["tags"])

    data["mainEntityOfPage"] = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "MediaLib", "item": f"{base}/"},
            {"@type": "ListItem", "position": 2, "name": "浏览", "item": f"{base}/app/browse"},
            {
                "@type": "ListItem",
                "position": 3,
                "name": item.get("title") or item.get("id"),
                "item": f"{base}{asset_path(item.get('slug', ''), item.get('id', ''))}",
            },
        ],
    }
    return data


def sitemap_xml(items: List[Dict[str, Any]], base_url: str = "") -> str:
    """单文件 sitemap（E-19：当前体量无需分片）。"""
    base = base_url.rstrip("/")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in ("/", "/app/browse"):
        parts.append(f"  <url><loc>{base}{path}</loc></url>")
    for it in items:
        loc = f"{base}{asset_path(it.get('slug', ''), it['id'])}"
        lastmod = time.strftime("%Y-%m-%d", time.localtime(it.get("updated_at") or it.get("ts") or 0))
        parts.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
    parts.append("</urlset>")
    return "\n".join(parts)


def robots_txt(base_url: str = "") -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {base_url.rstrip('/')}/sitemap.xml\n"
