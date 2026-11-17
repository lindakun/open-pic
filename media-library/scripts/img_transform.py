#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按需图像变换与磁盘缓存（REQ-V2-20 A-05）

设计要点：
  1. 统一入口 /img/{id}?w=&h=&fit=&fm=&q=，前端不再自行拼接 _md.webp 之类文件名
  2. 产物落盘缓存，键为 (item_id, w, h, fit, fm, q)，带 LRU 淘汰
  3. AVIF 为渐进增强：编码器缺失或失败时自动回退 WebP，绝不让请求失败
  4. 旧的 /t/ /f/ /p/ 路径与存量 _sm/_md/_lg 完全不受影响（v1 契约兼容）

缓存目录：{data_dir}/imgcache/
清理策略：总容量超过上限时，按 mtime 从旧到新删除，直到低于上限。
"""

import hashlib
import os
import threading
import time
from typing import Optional, Tuple

# 允许的宽度档位（白名单，防止任意尺寸刷爆磁盘）
ALLOWED_WIDTHS = {320, 360, 640, 720, 960, 1280, 1440, 1920, 2560, 3840}
MAX_DIMENSION = 4096

# 缓存容量上限（字节），默认 4GB
CACHE_LIMIT_BYTES = int(os.environ.get("MEDIA_LIB_IMGCACHE_BYTES", str(4 * 1024**3)))

# 各格式的质量默认值与上限
DEFAULT_QUALITY = {"webp": 82, "avif": 60, "jpeg": 85, "png": None}

# 允许的输出格式
ALLOWED_FORMATS = {"webp", "avif", "jpeg", "png"}

_FORMAT_ALIAS = {"jpg": "jpeg", "jpe": "jpeg"}

# 缓存清理互斥，避免并发请求同时扫描目录
_clean_lock = threading.Lock()
_last_clean = [0.0]


def normalize_format(fm: str) -> str:
    """归一化格式参数；未知值回退 webp。"""
    f = (fm or "webp").lower().strip().lstrip(".")
    f = _FORMAT_ALIAS.get(f, f)
    return f if f in ALLOWED_FORMATS else "webp"


def normalize_quality(fm: str, q: Optional[int]) -> Optional[int]:
    """归一化质量参数，按格式取合理区间。"""
    if fm == "png":
        return None
    default = DEFAULT_QUALITY.get(fm, 82)
    if q is None:
        return default
    return max(30, min(int(q), 100))


def clamp_dimension(value: Optional[int]) -> Optional[int]:
    """限制输出尺寸，防止超大尺寸攻击性与资源浪费。"""
    if value is None or value <= 0:
        return None
    return min(int(value), MAX_DIMENSION)


def cache_key(item_id: str, w: Optional[int], h: Optional[int], fit: str,
              fm: str, q: Optional[int], src_mtime: int) -> str:
    """缓存键：源文件 mtime 参与计算，源变更后自动失效。"""
    raw = f"{item_id}|{w}|{h}|{fit}|{fm}|{q}|{src_mtime}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def cache_path(cache_dir: str, key: str, fm: str) -> str:
    ext = "jpg" if fm == "jpeg" else fm
    # 两级分片，避免单目录文件过多
    return os.path.join(cache_dir, key[:2], f"{key}.{ext}")


def content_type(fm: str) -> str:
    return {
        "webp": "image/webp",
        "avif": "image/avif",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }.get(fm, "image/webp")


def transform(
    src_path: str,
    dest_path: str,
    w: Optional[int],
    h: Optional[int],
    fit: str,
    fm: str,
    q: Optional[int],
) -> bool:
    """把源图变换为目标尺寸与格式，成功返回 True。

    fit 语义：
      - 'cover'：等比缩放到覆盖目标框后居中裁剪（默认，适合卡片）
      - 'contain'：等比缩放到完整放入目标框，不足处留纸色背景
      - 'inside'：仅等比缩放，不裁剪也不补边
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False

    try:
        with Image.open(src_path) as raw:
            im = ImageOps.exif_transpose(raw)
            # 透明图统一贴纸色背景：浅色纸感主题下用暖白，避免出现黑边
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (250, 248, 245))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")

            target = _resolve_target(im.size, w, h, fit)
            if target and target != im.size:
                if fit == "cover" and w and h:
                    # 先等比放大到覆盖，再居中裁切
                    im = ImageOps.fit(im, (w, h), method=Image.LANCZOS, centering=(0.5, 0.5))
                else:
                    im = im.resize(target, Image.LANCZOS)

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            if fm == "png":
                im.save(dest_path, "PNG", optimize=True)
            elif fm == "jpeg":
                im.save(dest_path, "JPEG", quality=q or 85, optimize=True, progressive=True)
            elif fm == "avif":
                return _save_avif(im, dest_path, q or 60)
            else:
                im.save(dest_path, "WEBP", quality=q or 82, method=4)
            return os.path.getsize(dest_path) > 0
    except Exception:
        # 单张变换失败不应影响请求，交由上层回退
        return False


def _save_avif(im, dest_path: str, quality: int) -> bool:
    """AVIF 编码：编码器缺失时返回 False，由上层回退 WebP。"""
    try:
        im.save(dest_path, "AVIF", quality=quality)
        return os.path.getsize(dest_path) > 0
    except Exception:
        return False


def _resolve_target(size: Tuple[int, int], w: Optional[int], h: Optional[int],
                    fit: str) -> Optional[Tuple[int, int]]:
    """计算目标尺寸；只给一个维度时按比例推另一个。"""
    sw, sh = size
    if not w and not h:
        return None

    if w and h:
        if fit == "cover":
            # cover 由 ImageOps.fit 处理，这里返回目标框
            return (w, h)
        # contain / inside：等比缩放到能放进 w×h
        scale = min(w / sw, h / sh)
        return (max(1, int(sw * scale)), max(1, int(sh * scale)))

    if w:
        return (w, max(1, int(sh * (w / sw))))
    return (max(1, int(sw * (h / sh))), h)  # type: ignore[operator]


def touch(path: str) -> None:
    """更新访问时间，供 LRU 使用。"""
    try:
        os.utime(path, None)
    except OSError:
        pass


def maybe_cleanup(cache_dir: str, limit_bytes: int = CACHE_LIMIT_BYTES,
                  interval_sec: int = 300) -> None:
    """按容量上限做 LRU 清理；节流到每 interval 秒最多一次。"""
    now = time.time()
    if now - _last_clean[0] < interval_sec:
        return
    if not _clean_lock.acquire(blocking=False):
        return
    try:
        _last_clean[0] = now
        _cleanup_locked(cache_dir, limit_bytes)
    finally:
        _clean_lock.release()


def _cleanup_locked(cache_dir: str, limit_bytes: int) -> None:
    if not os.path.isdir(cache_dir):
        return

    entries = []
    total = 0
    for root, _dirs, files in os.walk(cache_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, path))
            total += st.st_size

    if total <= limit_bytes:
        return

    # 从最旧开始删，直到回落到上限的 90%（留出余量，避免频繁清理）
    target = int(limit_bytes * 0.9)
    entries.sort(key=lambda e: e[0])
    for _mtime, size, path in entries:
        if total <= target:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            continue


def cache_stats(cache_dir: str) -> dict:
    """缓存占用统计，供 /api/storage/summary 使用。"""
    total = 0
    count = 0
    if os.path.isdir(cache_dir):
        for root, _dirs, files in os.walk(cache_dir):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    count += 1
                except OSError:
                    continue
    return {"bytes": total, "files": count, "limit_bytes": CACHE_LIMIT_BYTES}


# ---------- 导出前的 EXIF 隐私清洗（REQ-V2-20 C-11） ----------

# 需要剥离的敏感标签：GPS 位置与设备唯一标识
_SENSITIVE_EXIF = {
    34853,  # GPSInfo
    42033,  # BodySerialNumber
    42034,  # CameraOwnerName
    272,    # Model（机型，常与设备指纹关联）
}


def sanitize_copy(src_path: str, dest_path: str, fmt: str = "jpeg",
                  quality: int = 90) -> bool:
    """生成剥离隐私信息的导出副本，原图不做任何修改。

    清洗范围：
      - GPS 全部标签（拍摄地点）
      - 机身序列号 / 相机所有者
      - 机型字段

    保留：拍摄时间、光圈/快门/ISO 等无隐私风险的参数。

    实现说明：Pillow 写文件时默认不携带 EXIF，因此"重新编码"本身
    即完成了清洗；此处额外显式过滤，防止将来引入 EXIF 透传逻辑时回归。
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False

    try:
        with Image.open(src_path) as raw:
            im = ImageOps.exif_transpose(raw)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (250, 248, 245))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")

            # 显式构造干净的 EXIF：只保留无隐私风险的标签
            clean_exif = _clean_exif(raw)

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            save_kwargs = {}
            if clean_exif is not None:
                save_kwargs["exif"] = clean_exif

            if fmt == "png":
                im.save(dest_path, "PNG", optimize=True)
            elif fmt == "webp":
                im.save(dest_path, "WEBP", quality=quality, method=4, **save_kwargs)
            else:
                im.save(dest_path, "JPEG", quality=quality, optimize=True,
                        progressive=True, **save_kwargs)
            return os.path.getsize(dest_path) > 0
    except Exception:
        return False


def _clean_exif(raw_image):
    """从原图 EXIF 中剔除敏感项，返回可用于保存的 exif 字节。"""
    try:
        exif = raw_image.getexif()
        if not exif:
            return None
        for tag in list(exif.keys()):
            if tag in _SENSITIVE_EXIF:
                del exif[tag]
        return exif.tobytes()
    except Exception:
        # 读取失败时返回 None：不带 EXIF 保存，等同全量清洗
        return None
