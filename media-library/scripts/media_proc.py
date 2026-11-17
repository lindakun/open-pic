#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""媒体处理核心：元数据提取、主色调分析、dHash 感知哈希、多规格 WebP 缩略图、视频预览与转码"""

import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi"}

# 缩略图规格
THUMB_SIZES = {
    "sm": 360,
    "md": 720,
    "lg": 1440,
}

_TMP_NAME_RE = re.compile(r"^(?:tmp[a-z0-9_]{4,}|img_?\d{4,}|image_?\d*|photo_?\d*|[0-9a-f]{12,})$", re.I)


def clean_title(raw_title: str, filename: str, source: str = "") -> str:
    """清洗临时文件名（如 tmprpjgn3nr），尽量生成可读标题"""
    t = (raw_title or "").strip()
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    if not t:
        t = stem
    if _TMP_NAME_RE.match(t) and source:
        parsed = urlparse(source)
        host = parsed.netloc.lower().lstrip("www.")
        parts = [p for p in parsed.path.split("/") if p]
        if "x.com" in host or "twitter.com" in host:
            if len(parts) >= 3 and parts[1] == "status":
                return f"X @{parts[0]} ({parts[2][-6:]})"
        if parts:
            tail = parts[-1][:32]
            if not _TMP_NAME_RE.match(tail):
                return f"{host}/{tail}" if host else tail
        if host:
            return f"来自 {host} 的素材"
    return t or stem or "未命名素材"


def _compute_dhash_pil(im) -> str:
    """计算 64-bit dHash 并返回 16 位十六进制字符串"""
    try:
        from PIL import Image
        gray = im.convert("L").resize((9, 8), Image.BILINEAR)
        pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())
        bits = 0
        for row in range(8):
            offset = row * 9
            for col in range(8):
                bits = (bits << 1) | (1 if pixels[offset + col] > pixels[offset + col + 1] else 0)
        return f"{bits:016x}"
    except Exception:
        return ""


def _extract_palette_pil(im, k: int = 3) -> Tuple[str, List[str]]:
    """提取主色调及前 K 个代表色（Hex）"""
    try:
        from PIL import Image
        small = im.convert("RGB").resize((48, 48), Image.BILINEAR)
        quant = small.quantize(colors=k, method=Image.MEDIANCUT)
        pal = quant.getpalette() or []
        counts = quant.getcolors() or []
        counts.sort(reverse=True, key=lambda x: x[0])
        hexes = []
        for _, idx in counts[:k]:
            base = idx * 3
            if base + 2 < len(pal):
                hexes.append(f"#{pal[base]:02x}{pal[base+1]:02x}{pal[base+2]:02x}")
        dominant = hexes[0] if hexes else "#1a1d24"
        return dominant, hexes
    except Exception:
        return "#1a1d24", []


def _extract_exif_pil(im) -> Dict[str, Any]:
    """提取基础 EXIF 字段（相机、镜头、拍摄时间）"""
    out: Dict[str, Any] = {}
    try:
        from PIL import ExifTags
        exif = im.getexif()
        if not exif:
            return out
        tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        for key, target in (
            ("Make", "make"),
            ("Model", "model"),
            ("DateTimeOriginal", "taken_at"),
            ("DateTime", "date_time"),
        ):
            val = tag_map.get(key)
            if val:
                out[target] = str(val).strip()[:64]
    except Exception:
        pass
    return out


def probe_video(src: str) -> Dict[str, Any]:
    """通过 ffprobe 提取视频宽高、时长、帧率、编码"""
    info: Dict[str, Any] = {
        "width": 0,
        "height": 0,
        "aspect_ratio": 1.0,
        "duration": 0.0,
        "fps": 0.0,
        "codec": "",
    }
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", src,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode != 0:
            return info
        data = json.loads(res.stdout or "{}")
        fmt = data.get("format", {})
        if fmt.get("duration"):
            info["duration"] = round(float(fmt["duration"]), 2)
        for st in data.get("streams", []):
            if st.get("codec_type") == "video":
                w = int(st.get("width") or 0)
                h = int(st.get("height") or 0)
                info["width"] = w
                info["height"] = h
                if w > 0 and h > 0:
                    info["aspect_ratio"] = round(w / h, 4)
                info["codec"] = str(st.get("codec_name") or "")
                r_fps = st.get("avg_frame_rate") or st.get("r_frame_rate") or ""
                if "/" in r_fps:
                    num, den = r_fps.split("/", 1)
                    if float(den) > 0:
                        info["fps"] = round(float(num) / float(den), 2)
                if not info["duration"] and st.get("duration"):
                    info["duration"] = round(float(st["duration"]), 2)
                break
    except Exception:
        pass
    return info


def extract_metadata(src: str, ext: str) -> Dict[str, Any]:
    """统一提取图片/视频元数据"""
    ext = ext.lower()
    meta: Dict[str, Any] = {
        "width": 0,
        "height": 0,
        "aspect_ratio": 1.0,
        "duration": 0.0,
        "fps": 0.0,
        "codec": "",
        "dominant_color": "#1a1d24",
        "palette": [],
        "exif": {},
        "phash": "",
    }
    if ext in IMAGE_EXT:
        try:
            from PIL import Image, ImageOps
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                w, h = im.size
                meta["width"] = w
                meta["height"] = h
                if w > 0 and h > 0:
                    meta["aspect_ratio"] = round(w / h, 4)
                meta["phash"] = _compute_dhash_pil(im)
                dom, pal = _extract_palette_pil(im)
                meta["dominant_color"] = dom
                meta["palette"] = pal
                meta["exif"] = _extract_exif_pil(im)
        except Exception as e:
            print(f"[meta] 图片提取失败 {src}: {e}", file=sys.stderr)
    elif ext in VIDEO_EXT:
        meta.update(probe_video(src))
    return meta


def _prepare_rgb_image(im):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (18, 18, 22))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def make_thumbnails(src: str, thumbs_dir: str, item_id: str, ext: str) -> Optional[str]:
    """生成向后兼容的 {id}.jpg（640px）以及 sm/md/lg 多规格 WebP 缩略图

    返回主缩略图文件名（{id}.jpg），失败返回 None。
    """
    os.makedirs(thumbs_dir, exist_ok=True)
    jpg_path = os.path.join(thumbs_dir, f"{item_id}.jpg")
    ext = ext.lower()

    if ext in IMAGE_EXT:
        try:
            from PIL import Image
            with Image.open(src) as raw:
                rgb = _prepare_rgb_image(raw)
                # 兼容主缩略图
                c640 = rgb.copy()
                c640.thumbnail((640, 640), Image.LANCZOS)
                c640.save(jpg_path, "JPEG", quality=82, optimize=True)
                # 多规格 WebP
                for tag, px in THUMB_SIZES.items():
                    wp = os.path.join(thumbs_dir, f"{item_id}_{tag}.webp")
                    cw = rgb.copy()
                    cw.thumbnail((px, px * 2), Image.LANCZOS)
                    cw.save(wp, "WEBP", quality=80, method=4)
            return f"{item_id}.jpg"
        except Exception as e:
            print(f"[thumb] Pillow 失败 {src}: {e}", file=sys.stderr)

    # 视频或 Pillow 失败时回退 ffmpeg 抽帧，再用 Pillow 压多规格 WebP
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if ext in VIDEO_EXT:
        args += ["-ss", "0.5"]
    args += ["-i", src, "-frames:v", "1", "-vf", "scale=1440:-1", jpg_path]
    try:
        subprocess.run(args, timeout=90, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:
        # 极短视频（<0.5s）时 -ss 越界会取不到帧：去掉起点重试一次
        if ext in VIDEO_EXT:
            retry = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                     "-i", src, "-frames:v", "1", "-vf", "scale=1440:-1", jpg_path]
            try:
                subprocess.run(retry, timeout=90, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except Exception as e2:
                print(f"[thumb] ffmpeg 失败 {src}: {e2}", file=sys.stderr)
                return None
        else:
            print(f"[thumb] ffmpeg 失败 {src}: {e}", file=sys.stderr)
            return None
    if os.path.exists(jpg_path) and os.path.getsize(jpg_path) > 0:
        try:
            from PIL import Image
            with Image.open(jpg_path) as frame:
                rgb = _prepare_rgb_image(frame)
                for tag, px in THUMB_SIZES.items():
                    wp = os.path.join(thumbs_dir, f"{item_id}_{tag}.webp")
                    cw = rgb.copy()
                    cw.thumbnail((px, px * 2), Image.LANCZOS)
                    cw.save(wp, "WEBP", quality=80, method=4)
                # 主 jpg 控制在 640px
                c640 = rgb.copy()
                c640.thumbnail((640, 640), Image.LANCZOS)
                c640.save(jpg_path, "JPEG", quality=82, optimize=True)
        except Exception:
            pass
        return f"{item_id}.jpg"
    return None


def make_video_preview(src: str, previews_dir: str, item_id: str) -> Optional[str]:
    """为视频生成 3 秒悬停动态 WebP 预览图"""
    os.makedirs(previews_dir, exist_ok=True)
    out_name = f"{item_id}.webp"
    out_path = os.path.join(previews_dir, out_name)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_name
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", "0.5", "-t", "3", "-i", src,
        "-vf", "fps=6,scale=360:-1:flags=lanczos",
        "-loop", "0", "-c:v", "libwebp", "-quality", "65",
        out_path,
    ]
    try:
        subprocess.run(cmd, timeout=60, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_name
    except Exception:
        pass
    return None


def make_compatible_mp4(src: str, play_dir: str, item_id: str, codec: str = "", ext: str = "") -> Optional[str]:
    """对非 H.264 或非 MP4 视频生成浏览器兼容播放副本（H.264 + AAC + faststart）"""
    os.makedirs(play_dir, exist_ok=True)
    out_name = f"{item_id}.mp4"
    out_path = os.path.join(play_dir, out_name)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_name

    # 如果已经是 mp4 且是 h264，只需快速重封装 faststart（无需重编码）
    if ext.lower() == ".mp4" and codec.lower() == "h264":
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", src, "-c", "copy", "-movflags", "+faststart", out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
    try:
        subprocess.run(cmd, timeout=300, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_name
    except Exception as e:
        print(f"[transcode] 失败 {src}: {e}", file=sys.stderr)
    return None
