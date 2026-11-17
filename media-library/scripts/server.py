#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人图片/视频库服务（FastAPI + SQLite WAL + FTS5 商业化架构）

用法：
  python3 server.py --port 18100
  python3 server.py --stop
  python3 server.py --status
  python3 server.py --repair
"""

import argparse
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import quote

# 确保同目录模块可导入
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import media_proc
import img_transform
from db import MediaDB
from tasks import TaskManager

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(BASE)))
DATA = os.environ.get("MEDIA_LIB_DIR") or os.path.join(WORKSPACE, "media-library")
FILES = os.path.join(DATA, "files")
THUMBS = os.path.join(DATA, "thumbs")
PREVIEWS = os.path.join(DATA, "previews")
PLAY_DIR = os.path.join(DATA, "play")
# 按需变换缓存目录（A-05）
IMG_CACHE_DIR = os.path.join(DATA, "imgcache")
INDEX_JSON = os.path.join(DATA, "index.json")
DB_PATH = os.path.join(DATA, "media.db")
PIDFILE = os.path.join(DATA, "server.pid")
STATIC_DIR = os.path.join(BASE, "static")
# 新前端（Vite + Vue3）构建产物目录；旧前端仍在 STATIC_DIR 根下
APP_DIR = os.path.join(STATIC_DIR, "app")
# 双前端切换开关：legacy = 旧单页，next = 新前端（REQ-V2-20 §7.1）
# 未显式配置时，若新前端产物存在则默认使用新前端
FRONTEND_MODE = os.environ.get("MEDIA_LIB_FRONTEND", "").lower()

MAX_UPLOAD = 1024 * 1024 * 1024  # 1GB

_id_locks: Dict[str, threading.Lock] = {}
_id_locks_guard = threading.Lock()


def _id_lock(item_id: str) -> threading.Lock:
    with _id_locks_guard:
        lk = _id_locks.get(item_id)
        if lk is None:
            lk = threading.Lock()
            _id_locks[item_id] = lk
        return lk


def ensure_dirs():
    for d in (DATA, FILES, THUMBS, PREVIEWS, PLAY_DIR):
        os.makedirs(d, exist_ok=True)


# ---------- 请求体模型 ----------

class DeleteReq(BaseModel):
    id: str = ""
    ids: Optional[List[str]] = None
    permanent: bool = False


class RestoreReq(BaseModel):
    ids: List[str]


class UpdateItemReq(BaseModel):
    title: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    author: Optional[str] = None
    notes: Optional[str] = None


class BatchReq(BaseModel):
    ids: List[str]
    action: str  # add_tags | remove_tags | add_collection | delete | restore | permanent_delete
    tags: Optional[List[str]] = None
    collection_id: Optional[int] = None


class IngestUrlReq(BaseModel):
    url: str
    tags: str = ""
    title: str = ""


class CollectionReq(BaseModel):
    name: str
    description: str = ""


class CollectionUpdateReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_item_id: Optional[str] = None


class CollectionItemsReq(BaseModel):
    item_ids: List[str]


class ZipReq(BaseModel):
    ids: List[str]


# ---------- 核心服务工厂 ----------

def create_app(data_dir: Optional[str] = None, port: int = 18100, start_workers: bool = True) -> FastAPI:
    global DATA, FILES, THUMBS, PREVIEWS, PLAY_DIR, INDEX_JSON, DB_PATH, PIDFILE
    if data_dir:
        DATA = data_dir
        FILES = os.path.join(DATA, "files")
        THUMBS = os.path.join(DATA, "thumbs")
        PREVIEWS = os.path.join(DATA, "previews")
        PLAY_DIR = os.path.join(DATA, "play")
        INDEX_JSON = os.path.join(DATA, "index.json")
        DB_PATH = os.path.join(DATA, "media.db")
        PIDFILE = os.path.join(DATA, "server.pid")

    ensure_dirs()
    db = MediaDB(DB_PATH)
    migrated = db.migrate_from_index_json(INDEX_JSON)
    if migrated:
        print(f"[migrate] 已从 index.json 无损迁移 {migrated} 条记录至 SQLite", file=sys.stderr)

    tasks = TaskManager(db=db, data_dir=DATA, scripts_dir=BASE, port=port)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_workers:
            tasks.start(num_workers=2)
            # 若存在未提取宽高的存量记录，自动后台排队回填
            _, sample = db.query_items(limit=5, offset=0)
            if any(it.get("width", 0) == 0 for it in sample):
                tasks.enqueue("backfill_metadata", {"auto": True})
        yield
        tasks.stop()

    app = FastAPI(title="MediaLib API", version="2.0.0", lifespan=lifespan)
    app.state.db = db
    app.state.tasks = tasks
    app.state.data_dir = DATA

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if os.path.isdir(STATIC_DIR):
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # 新前端的静态资源（带 hash，可长缓存）
    _app_assets = os.path.join(APP_DIR, "assets")
    if os.path.isdir(_app_assets):
        app.mount("/app/assets", StaticFiles(directory=_app_assets), name="app-assets")

    # ---------- 辅助函数 ----------

    def store_file(tmp_path: str, filename: str, title: str = "", tags: Optional[List[str]] = None, source: str = "") -> tuple[Dict[str, Any], bool, Optional[Dict[str, Any]]]:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in media_proc.IMAGE_EXT and ext not in media_proc.VIDEO_EXT:
            raise ValueError(f"不支持的文件类型: {ext or '(无扩展名)'}")

        h = hashlib.sha1()
        size = 0
        with open(tmp_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 256)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        item_id = h.hexdigest()[:16]

        existing = db.get_item(item_id)
        if existing:
            if existing.get("deleted_at"):
                db.restore_items([item_id])
                existing = db.get_item(item_id)
            return existing, False, None

        with _id_lock(item_id):
            existing = db.get_item(item_id)
            if existing:
                return existing, False, None

            dest = os.path.join(FILES, item_id + ext)
            shutil.move(tmp_path, dest)
            try:
                os.chmod(dest, 0o644)
            except Exception:
                pass

            meta = media_proc.extract_metadata(dest, ext)
            thumb_rel = media_proc.make_thumbnails(dest, THUMBS, item_id, ext)
            near_dup = db.find_near_duplicate(meta.get("phash", "")) if ext in media_proc.IMAGE_EXT else None

            rec = {
                "id": item_id,
                "file": item_id + ext,
                "thumb": thumb_rel,
                "kind": "video" if ext in media_proc.VIDEO_EXT else "image",
                "ext": ext,
                "name": os.path.basename(filename),
                "title": media_proc.clean_title(title, filename, source),
                "tags": tags or [],
                "source": source or "",
                "source_platform": db.detect_platform(source or ""),
                "size": size,
                "width": meta["width"],
                "height": meta["height"],
                "aspect_ratio": meta["aspect_ratio"],
                "duration": meta["duration"],
                "fps": meta["fps"],
                "codec": meta["codec"],
                "dominant_color": meta["dominant_color"],
                "palette_json": json.dumps(meta["palette"], ensure_ascii=False),
                "exif_json": json.dumps(meta["exif"], ensure_ascii=False),
                "phash": meta["phash"],
                "ts": int(time.time()),
            }
            db.upsert_item(rec)
            saved = db.get_item(item_id) or rec

            # 视频入库后异步生成悬停预览与兼容播放副本
            if rec["kind"] == "video" and start_workers:
                tasks.enqueue("video_postprocess", {"item_id": item_id})
            if start_workers:
                tasks.broadcast("library_updated", {"reason": "upload", "item_id": item_id})
            return saved, True, near_dup

    def _serve_range_file(request: Request, path: str, download_name: Optional[str] = None, ctype: Optional[str] = None, immutable: bool = True) -> Response:
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="not found")
        stat = os.stat(path)
        size = stat.st_size
        etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
        if request.headers.get("if-none-match") == etag and not download_name:
            return Response(status_code=304, headers={"ETag": etag})

        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        headers = {
            "Accept-Ranges": "bytes",
            "ETag": etag,
        }
        if immutable and not download_name:
            headers["Cache-Control"] = "public, max-age=2592000, immutable"
        if download_name:
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(download_name)

        rng = request.headers.get("range")
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            try:
                start = int(s) if s else 0
                end = int(e) if e else size - 1
                end = min(end, size - 1)
                if start > end or start < 0:
                    raise ValueError
                length = end - start + 1
            except ValueError:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

            def iter_range():
                with open(path, "rb") as f:
                    f.seek(start)
                    left = length
                    while left > 0:
                        chunk = f.read(min(65536, left))
                        if not chunk:
                            break
                        left -= len(chunk)
                        yield chunk

            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            headers["Content-Length"] = str(length)
            return StreamingResponse(iter_range(), status_code=206, media_type=ctype, headers=headers)

        return FileResponse(path, media_type=ctype, headers=headers)

    # ---------- 页面路由 ----------

    def _use_next_frontend() -> bool:
        """是否使用新前端：显式开关优先，否则看构建产物是否存在。"""
        if FRONTEND_MODE == "legacy":
            return False
        if FRONTEND_MODE == "next":
            return True
        return os.path.isfile(os.path.join(APP_DIR, "index.html"))

    def _read_shell(directory: str) -> Optional[str]:
        idx_file = os.path.join(directory, "index.html")
        if os.path.isfile(idx_file):
            with open(idx_file, "r", encoding="utf-8") as f:
                return f.read()
        return None

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    def index_page():
        """站点入口。

        新前端构建产物使用 /app/ 作为 base（资源路径绝对），
        因此启用新前端时从 / 重定向到 /app/，保持路由 base 一致。
        旧前端模式则直接返回旧单页。
        """
        if _use_next_frontend() and os.path.isfile(os.path.join(APP_DIR, "index.html")):
            return RedirectResponse(url="/app/", status_code=302)
        shell = _read_shell(STATIC_DIR)
        if shell is not None:
            return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>MediaLib</h1><p>static/index.html missing</p>")

    @app.get("/app", response_class=HTMLResponse)
    @app.get("/app/{spa_path:path}", response_class=HTMLResponse)
    def app_shell(spa_path: str = ""):
        """新前端 SPA 回退：非 assets 路径一律返回 index.html，由前端路由接管。"""
        shell = _read_shell(APP_DIR)
        if shell is None:
            raise HTTPException(status_code=404, detail="新前端未构建")
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    @app.get("/s/{item_id}", response_class=HTMLResponse)
    def share_page(item_id: str, request: Request):
        it = db.get_item(item_id)
        if not it or it.get("deleted_at"):
            raise HTTPException(status_code=404, detail="资源不存在或已删除")
        db.increment_counter(item_id, "views")
        base_url = str(request.base_url).rstrip("/")
        title_esc = html.escape(it["title"] or it["name"])
        thumb_url = f"{base_url}/t/{it['id']}.jpg"
        media_url = f"{base_url}/f/{it['file']}"
        tags_esc = html.escape(" ".join(f"#{t}" for t in it.get("tags", [])))
        dim_info = f"{it['width']}×{it['height']}" if it.get("width") else ""
        desc_esc = html.escape(f"{it['kind'].upper()} · {dim_info} · {tags_esc}".strip(" ·"))
        og_type = "video.other" if it["kind"] == "video" else "website"
        media_tag = (
            f'<video src="{media_url}" controls autoplay playsinline style="max-width:92vw;max-height:76vh;border-radius:10px"></video>'
            if it["kind"] == "video"
            else f'<img src="{media_url}" alt="{title_esc}" style="max-width:92vw;max-height:76vh;border-radius:10px;object-fit:contain">'
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_esc} - MediaLib 分享</title>
<meta property="og:title" content="{title_esc}">
<meta property="og:description" content="{desc_esc}">
<meta property="og:type" content="{og_type}">
<meta property="og:image" content="{thumb_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title_esc}">
<meta name="twitter:image" content="{thumb_url}">
<style>
body{{margin:0;background:#0b0c10;color:#e6e8ef;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}}
.card{{background:#141720;border:1px solid #242938;border-radius:14px;padding:20px;max-width:96vw;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.55)}}
.meta{{margin-top:14px;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;color:#9aa2b6;font-size:13px}}
.btn{{background:#3b66f5;color:#fff;text-decoration:none;padding:7px 14px;border-radius:8px;font-weight:500}}
.btn.ghost{{background:#1f2433;color:#cfd5e6}}
</style>
</head>
<body>
<div class="card">
  {media_tag}
  <div class="meta">
    <strong style="color:#fff;font-size:15px">{title_esc}</strong>
    <span>{desc_esc}</span>
    <a class="btn" href="/f/{it['file']}?dl=1" download>下载原文件</a>
    <a class="btn ghost" href="/">进入图片库</a>
  </div>
</div>
</body>
</html>""")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": "2.0.0"}

    # ---------- 媒体文件分发 ----------

    @app.get("/f/{file_id}")
    def serve_file(file_id: str, request: Request, dl: Optional[str] = None, play: Optional[str] = None):
        iid = file_id.split(".")[0]
        if not re.match(r"^[0-9a-f]{6,32}$", iid):
            raise HTTPException(status_code=404, detail="not found")
        it = db.get_item(iid)
        if not it:
            raise HTTPException(status_code=404, detail="not found")
        if dl:
            db.increment_counter(iid, "downloads")
        # 若请求兼容播放副本且存在
        if play and it.get("play_file"):
            p_path = os.path.join(PLAY_DIR, it["play_file"])
            if os.path.isfile(p_path):
                return _serve_range_file(request, p_path, ctype="video/mp4")
        fpath = os.path.join(FILES, it["file"])
        return _serve_range_file(request, fpath, download_name=it["name"] if dl else None)

    @app.get("/t/{thumb_name}")
    def serve_thumb(thumb_name: str, request: Request):
        if not re.match(r"^[0-9a-f]{6,32}(?:_(?:sm|md|lg))?\.(?:jpg|webp)$", thumb_name):
            raise HTTPException(status_code=404, detail="not found")
        tp = os.path.join(THUMBS, thumb_name)
        if not os.path.isfile(tp):
            # 回退到基础 jpg
            iid = thumb_name.split("_")[0].split(".")[0]
            fallback = os.path.join(THUMBS, f"{iid}.jpg")
            if os.path.isfile(fallback):
                return _serve_range_file(request, fallback, ctype="image/jpeg")
            raise HTTPException(status_code=404, detail="not found")
        ctype = "image/webp" if thumb_name.endswith(".webp") else "image/jpeg"
        return _serve_range_file(request, tp, ctype=ctype)

    @app.get("/img/{item_id}")
    def serve_transformed(
        item_id: str,
        request: Request,
        w: Optional[int] = None,
        h: Optional[int] = None,
        fit: str = "cover",
        fm: str = "webp",
        q: Optional[int] = None,
    ):
        """按需图像变换（REQ-V2-20 A-05）。

        统一入口，替代前端自行拼接 _sm/_md/_lg 文件名。
        产物磁盘缓存 + LRU 淘汰；AVIF 失败自动回退 WebP。
        """
        if not re.match(r"^[0-9a-f]{6,32}$", item_id):
            raise HTTPException(status_code=404, detail="not found")

        it = db.get_item(item_id)
        if not it or it.get("deleted_at"):
            raise HTTPException(status_code=404, detail="not found")
        if it["kind"] == "video":
            # 视频走原有 poster / file 路由，不在变换端点处理
            raise HTTPException(status_code=400, detail="视频请使用 /t/ 或 /p/")

        src_path = os.path.join(FILES, it["file"])
        if not os.path.isfile(src_path):
            raise HTTPException(status_code=404, detail="源文件不存在")

        fmt = img_transform.normalize_format(fm)
        w = img_transform.clamp_dimension(w)
        h = img_transform.clamp_dimension(h)
        # 未指定尺寸时按原图返回，但不出缓存（避免把原图复制一份）
        quality = img_transform.normalize_quality(fmt, q)
        src_mtime = int(os.stat(src_path).st_mtime)

        key = img_transform.cache_key(item_id, w, h, fit, fmt, quality, src_mtime)
        cached = img_transform.cache_path(IMG_CACHE_DIR, key, fmt)

        if os.path.isfile(cached):
            img_transform.touch(cached)
            return _serve_range_file(request, cached, ctype=img_transform.content_type(fmt))

        # 未命中：生成并落缓存
        ok = img_transform.transform(src_path, cached, w, h, fit, fmt, quality)
        if not ok and fmt == "avif":
            # AVIF 编码器缺失或失败：回退 WebP，保证请求不失败
            fmt = "webp"
            quality = img_transform.normalize_quality(fmt, q)
            key = img_transform.cache_key(item_id, w, h, fit, fmt, quality, src_mtime)
            cached = img_transform.cache_path(IMG_CACHE_DIR, key, fmt)
            if os.path.isfile(cached):
                img_transform.touch(cached)
            else:
                ok = img_transform.transform(src_path, cached, w, h, fit, fmt, quality)

        if not ok or not os.path.isfile(cached):
            # 变换彻底失败：回退原文件，绝不返回错误页
            return _serve_range_file(request, src_path)

        img_transform.maybe_cleanup(IMG_CACHE_DIR)
        return _serve_range_file(request, cached, ctype=img_transform.content_type(fmt))

    @app.get("/p/{preview_name}")
    def serve_preview(preview_name: str, request: Request):
        if not re.match(r"^[0-9a-f]{6,32}\.webp$", preview_name):
            raise HTTPException(status_code=404, detail="not found")
        pp = os.path.join(PREVIEWS, preview_name)
        return _serve_range_file(request, pp, ctype="image/webp")

    # ---------- 查询与统计 API ----------

    @app.get("/api/stats")
    def api_stats():
        return db.get_stats()

    @app.get("/api/analytics")
    def api_analytics():
        return db.get_analytics()

    @app.get("/api/facets")
    def api_facets(kind: str = "", ext: str = "", orientation: str = "", platform: str = ""):
        """分面统计（REQ-V2-20 B-10）。

        返回各筛选维度的可选值与计数，前端据此渲染分面面板并对零结果项置灰。
        """
        return db.get_facets(kind=kind, ext=ext, orientation=orientation, platform=platform)

    @app.get("/api/items")
    def api_items(
        limit: int = Query(60, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str = "",
        tag: str = "",
        exclude_tag: str = "",
        kind: str = "",
        ext: str = "",
        orientation: str = "",
        platform: str = "",
        collection_id: Optional[int] = None,
        color: str = "",
        sort: str = "newest",
        deleted: bool = False,
    ):
        tags_list = [t.strip() for t in tag.split(",") if t.strip()] if tag else []
        ex_list = [t.strip() for t in exclude_tag.split(",") if t.strip()] if exclude_tag else []
        total, items = db.query_items(
            limit=limit,
            offset=offset,
            q=q,
            tags=tags_list,
            exclude_tags=ex_list,
            kind=kind,
            ext=ext,
            orientation=orientation,
            platform=platform,
            collection_id=collection_id,
            color=color,
            sort=sort,
            deleted=deleted,
        )
        return {"total": total, "items": items}

    @app.get("/api/item/{item_id}")
    def api_get_item(item_id: str, view: bool = False):
        if not re.match(r"^[0-9a-f]{6,32}$", item_id):
            raise HTTPException(status_code=404, detail="not found")
        it = db.get_item(item_id)
        if not it:
            raise HTTPException(status_code=404, detail="not found")
        if view:
            db.increment_counter(item_id, "views")
        return it

    @app.get("/api/item/{item_id}/similar")
    def api_similar_items(item_id: str, limit: int = Query(12, ge=1, le=30)):
        return {"items": db.find_similar(item_id, limit=limit)}

    @app.patch("/api/item/{item_id}")
    def api_update_item(item_id: str, req: UpdateItemReq):
        fields = req.model_dump(exclude_none=True)
        updated = db.update_item(item_id, fields)
        if not updated:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True, "item": updated}

    # ---------- 上传与入库 ----------

    @app.post("/api/upload")
    async def api_upload(request: Request):
        ctype = request.headers.get("content-type", "")
        if "multipart/form-data" not in ctype:
            raise HTTPException(status_code=400, detail="need multipart/form-data")

        form = await request.form()
        title = str(form.get("title", "") or "")
        source = str(form.get("source", "") or "")
        tags_raw = str(form.get("tags", "") or "")
        tags = [t.strip() for t in re.split(r"[,，\s]+", tags_raw) if t.strip()]

        files_to_save: List[tuple[str, str]] = []
        tmpdir = tempfile.mkdtemp(prefix="mlib-", dir=DATA)
        try:
            for key, val in form.multi_items():
                if hasattr(val, "filename") and getattr(val, "filename", None):
                    tp = os.path.join(tmpdir, f"up-{len(files_to_save)}")
                    total_bytes = 0
                    with open(tp, "wb") as out_f:
                        while True:
                            chunk = await val.read(1024 * 512)
                            if not chunk:
                                break
                            total_bytes += len(chunk)
                            if total_bytes > MAX_UPLOAD:
                                raise HTTPException(status_code=413, detail="too large")
                            out_f.write(chunk)
                    files_to_save.append((tp, val.filename))

            if not files_to_save:
                raise HTTPException(status_code=400, detail="no file field")

            out = []
            for tp, fname in files_to_save:
                rec, is_new, near_dup = store_file(tp, fname, title=title, tags=tags, source=source)
                rec = dict(rec)
                rec["duplicate"] = not is_new
                if near_dup and near_dup["id"] != rec["id"]:
                    rec["near_duplicate_id"] = near_dup["id"]
                out.append(rec)
            return {"ok": True, "count": len(out), "items": out}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @app.post("/api/ingest-url")
    def api_ingest_url(req: IngestUrlReq):
        url = req.url.strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="请输入合法的 http/https 链接")
        job_id = tasks.enqueue("ingest_url", {"url": url, "tags": req.tags, "title": req.title})
        return {"ok": True, "job_id": job_id}

    # ---------- 批量、删除、恢复、ZIP 打包 ----------

    def _physical_remove_items(removed_rows: List[Dict[str, Any]]):
        for r in removed_rows:
            candidates = [
                os.path.join(FILES, r["file"]),
                os.path.join(THUMBS, r.get("thumb") or ""),
                os.path.join(THUMBS, f"{r['id']}_sm.webp"),
                os.path.join(THUMBS, f"{r['id']}_md.webp"),
                os.path.join(THUMBS, f"{r['id']}_lg.webp"),
                os.path.join(PREVIEWS, r.get("preview_file") or ""),
                os.path.join(PLAY_DIR, r.get("play_file") or ""),
            ]
            for f in candidates:
                if f and os.path.isfile(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

    @app.post("/api/delete")
    def api_delete(req: DeleteReq):
        target_ids = list(req.ids or [])
        if req.id:
            target_ids.append(req.id)
        if not target_ids:
            return {"ok": False, "count": 0}
        if req.permanent:
            removed = db.permanent_delete(target_ids)
            _physical_remove_items(removed)
            return {"ok": bool(removed), "id": req.id, "count": len(removed)}
        cnt = db.soft_delete(target_ids)
        return {"ok": cnt > 0, "id": req.id, "count": cnt}

    @app.post("/api/restore")
    def api_restore(req: RestoreReq):
        cnt = db.restore_items(req.ids)
        return {"ok": cnt > 0, "count": cnt}

    @app.post("/api/trash/empty")
    def api_empty_trash():
        _, trashed = db.query_items(limit=100000, offset=0, deleted=True)
        ids = [it["id"] for it in trashed]
        removed = db.permanent_delete(ids)
        _physical_remove_items(removed)
        return {"ok": True, "count": len(removed)}

    @app.post("/api/items/batch")
    def api_batch(req: BatchReq):
        if not req.ids:
            return {"ok": False, "count": 0}
        if req.action == "add_tags":
            cnt = db.batch_tags(req.ids, add_tags=req.tags or [])
            return {"ok": True, "count": cnt}
        if req.action == "remove_tags":
            cnt = db.batch_tags(req.ids, remove_tags=req.tags or [])
            return {"ok": True, "count": cnt}
        if req.action == "add_collection" and req.collection_id is not None:
            cnt = db.add_to_collection(req.collection_id, req.ids)
            return {"ok": True, "count": cnt}
        if req.action == "delete":
            cnt = db.soft_delete(req.ids)
            return {"ok": True, "count": cnt}
        if req.action == "restore":
            cnt = db.restore_items(req.ids)
            return {"ok": True, "count": cnt}
        if req.action == "permanent_delete":
            removed = db.permanent_delete(req.ids)
            _physical_remove_items(removed)
            return {"ok": True, "count": len(removed)}
        raise HTTPException(status_code=400, detail="不支持的批量操作")

    @app.post("/api/items/download-zip")
    def api_download_zip(req: ZipReq):
        if not req.ids:
            raise HTTPException(status_code=400, detail="未选择任何文件")
        buf = io.BytesIO()
        used_names: Dict[str, int] = {}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for iid in req.ids[:100]:
                it = db.get_item(iid)
                if not it:
                    continue
                fpath = os.path.join(FILES, it["file"])
                if not os.path.isfile(fpath):
                    continue
                arcname = it["name"] or it["file"]
                if arcname in used_names:
                    used_names[arcname] += 1
                    stem, ext = os.path.splitext(arcname)
                    arcname = f"{stem}_{used_names[arcname]}{ext}"
                else:
                    used_names[arcname] = 0
                zf.write(fpath, arcname=arcname)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=medialib-pack.zip"},
        )

    # ---------- 画板（Collections） ----------

    @app.get("/api/collections")
    def api_list_collections():
        return {"collections": db.list_collections()}

    @app.post("/api/collections")
    def api_create_collection(req: CollectionReq):
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="画板名称不能为空")
        return {"ok": True, "collection": db.create_collection(req.name, req.description)}

    @app.patch("/api/collections/{cid}")
    def api_update_collection(cid: int, req: CollectionUpdateReq):
        col = db.update_collection(cid, name=req.name, description=req.description, cover_item_id=req.cover_item_id)
        if not col:
            raise HTTPException(status_code=404, detail="画板不存在")
        return {"ok": True, "collection": col}

    @app.delete("/api/collections/{cid}")
    def api_delete_collection(cid: int):
        ok = db.delete_collection(cid)
        return {"ok": ok}

    @app.post("/api/collections/{cid}/items")
    def api_add_collection_items(cid: int, req: CollectionItemsReq):
        cnt = db.add_to_collection(cid, req.item_ids)
        return {"ok": True, "added": cnt}

    @app.delete("/api/collections/{cid}/items")
    def api_remove_collection_items(cid: int, req: CollectionItemsReq):
        cnt = db.remove_from_collection(cid, req.item_ids)
        return {"ok": True, "removed": cnt}

    # ---------- 任务队列与存储治理 ----------

    @app.get("/api/jobs")
    def api_list_jobs(limit: int = 50):
        return {"jobs": db.list_jobs(limit=limit)}

    @app.post("/api/jobs/backfill")
    def api_trigger_backfill():
        job_id = tasks.enqueue("backfill_metadata", {"manual": True})
        return {"ok": True, "job_id": job_id}

    @app.get("/api/jobs/stream")
    async def api_jobs_stream(request: Request):
        q = tasks.subscribe()

        async def event_gen():
            try:
                yield "event: ping\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = q.get_nowait()
                        yield msg
                    except Exception:
                        await __import__("asyncio").sleep(0.5)
            finally:
                tasks.unsubscribe(q)

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    @app.get("/api/storage/summary")
    def api_storage_summary():
        def dir_size(d):
            total = 0
            cnt = 0
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    fp = os.path.join(d, fn)
                    if os.path.isfile(fp):
                        total += os.path.getsize(fp)
                        cnt += 1
            return {"bytes": total, "files": cnt}

        disk = shutil.disk_usage(DATA)
        return {
            "files": dir_size(FILES),
            "thumbs": dir_size(THUMBS),
            "previews": dir_size(PREVIEWS),
            "play": dir_size(PLAY_DIR),
            "disk_total": disk.total,
            "disk_free": disk.free,
        }

    @app.post("/api/storage/repair")
    def api_storage_repair():
        res = repair_library(db, verbose=False)
        return {"ok": True, **res}

    return app


def repair_library(db: MediaDB, verbose: bool = True) -> Dict[str, Any]:
    """一致性自检：剔除磁盘缺失的孤儿记录、补全缺失缩略图、报告残留文件"""
    _, items = db.query_items(limit=100000, offset=0)
    orphans, fixed_thumb = [], 0
    for it in items:
        fpath = os.path.join(FILES, it["file"])
        if not os.path.isfile(fpath):
            orphans.append(it["id"])
            continue
        tpath = os.path.join(THUMBS, it.get("thumb") or f"{it['id']}.jpg")
        if not os.path.isfile(tpath):
            tname = media_proc.make_thumbnails(fpath, THUMBS, it["id"], it["ext"])
            if tname:
                db.update_item(it["id"], {"thumb": tname})
                fixed_thumb += 1
    if orphans:
        db.permanent_delete(orphans)
    known = {it["file"] for it in items if it["id"] not in set(orphans)}
    try:
        stray = [f for f in os.listdir(FILES) if f not in known]
    except FileNotFoundError:
        stray = []
    if verbose:
        print(f"[repair] 剔除孤儿 {len(orphans)} 条，补齐缩略图 {fixed_thumb} 个，磁盘未索引残留 {len(stray)} 个")
    return {"orphans_removed": len(orphans), "fixed_thumbs": fixed_thumb, "stray_files": len(stray)}


# ---------- 进程管理（兼容原有 CLI） ----------

def cmd_start(port: int, host: str) -> int:
    ensure_dirs()
    if os.path.exists(PIDFILE):
        try:
            with open(PIDFILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"已在运行 pid={pid}  http://{host}:{port}/")
            return 0
        except Exception:
            pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    print(f"serving on http://{host}:{port}/  data={DATA}")
    sys.stdout.flush()
    app = create_app(port=port)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(PIDFILE)
        except Exception:
            pass
    return 0


def cmd_stop() -> int:
    if not os.path.exists(PIDFILE):
        print("未运行")
        return 0
    with open(PIDFILE) as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        print(f"已停止 pid={pid}")
    except ProcessLookupError:
        print("进程不存在，清理 pid 文件")
    except Exception as e:
        print(f"停止失败: {e}")
        return 1
    try:
        os.remove(PIDFILE)
    except Exception:
        pass
    return 0


def cmd_status(port: int) -> int:
    ensure_dirs()
    if os.path.exists(PIDFILE):
        with open(PIDFILE) as f:
            pid = f.read().strip()
        try:
            os.kill(int(pid), 0)
            db = MediaDB(DB_PATH)
            st = db.get_stats()
            print(f"运行中 pid={pid} 端口={port} 项目数={st['total']}")
            return 0
        except Exception:
            print("pid 文件存在但进程已死")
            return 1
    print("未运行")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18100)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--repair", action="store_true")
    a = ap.parse_args()
    if a.stop:
        return cmd_stop()
    if a.status:
        return cmd_status(a.port)
    if a.repair:
        ensure_dirs()
        db = MediaDB(DB_PATH)
        db.migrate_from_index_json(INDEX_JSON)
        repair_library(db, verbose=True)
        return 0
    return cmd_start(a.port, a.host)


if __name__ == "__main__":
    sys.exit(main())
