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
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

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
from starlette.background import BackgroundTask

import ai_provider
import export_seo
import media_proc
import img_transform
import pipeline_config
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
    # 多规格导出（REQ-V2-20 C-13）：不传时保持旧行为（原图直出，文件名不变）
    preset: str = "original"
    format: str = ""
    quality: int = 85


# ---------- 核心服务工厂 ----------

# AI provider 工厂：默认读环境变量。测试或扩展可替换此函数，
# 无需改动业务代码（对应 B-08「provider 可替换」要求）。
AI_PROVIDER_FACTORY = ai_provider.get_provider


def create_app(data_dir: Optional[str] = None, port: int = 18100, start_workers: bool = True) -> FastAPI:
    global DATA, FILES, THUMBS, PREVIEWS, PLAY_DIR, IMG_CACHE_DIR, INDEX_JSON, DB_PATH, PIDFILE
    if data_dir:
        DATA = data_dir
        FILES = os.path.join(DATA, "files")
        THUMBS = os.path.join(DATA, "thumbs")
        PREVIEWS = os.path.join(DATA, "previews")
        PLAY_DIR = os.path.join(DATA, "play")
        IMG_CACHE_DIR = os.path.join(DATA, "imgcache")
        INDEX_JSON = os.path.join(DATA, "index.json")
        DB_PATH = os.path.join(DATA, "media.db")
        PIDFILE = os.path.join(DATA, "server.pid")

    ensure_dirs()
    db = MediaDB(DB_PATH)
    migrated = db.migrate_from_index_json(INDEX_JSON)
    if migrated:
        print(f"[migrate] 已从 index.json 无损迁移 {migrated} 条记录至 SQLite", file=sys.stderr)

    tasks = TaskManager(db=db, data_dir=DATA, scripts_dir=BASE, port=port)
    # 让后台任务与 HTTP 层共用同一个 provider 工厂（B-08 验收 5 的切换一致性）
    tasks.provider_factory = AI_PROVIDER_FACTORY

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

    def store_file(tmp_path: str, filename: str, title: str = "", tags: Optional[List[str]] = None, source: str = "",
                   synchronous: bool = False, license_name: str = "", license_url: str = "",
                   credit: str = "", copyright_holder: str = "", commercial_ok: bool = True
                   ) -> tuple[Dict[str, Any], bool, Optional[Dict[str, Any]]]:
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
                # 与锁外首次检查同款口径：软删除态先恢复，否则该资产
                # 会在回收站里"复活"失败、本次上传也拿不到可展示记录
                if existing.get("deleted_at"):
                    db.restore_items([item_id])
                    existing = db.get_item(item_id)
                return existing, False, None

            dest = os.path.join(FILES, item_id + ext)
            shutil.move(tmp_path, dest)
            try:
                os.chmod(dest, 0o644)
            except Exception:
                pass

            # 快速路径（REQ-V2-20 D-16）：只落盘 + 建记录，立即返回。
            # 元数据提取（ffprobe/Pillow）、缩略图生成、近重复检测
            # 全部下沉到 TaskManager，避免上传请求被重活占住。
            fast = synchronous == False
            meta = {}
            thumb_rel = None

            if not fast:
                meta = media_proc.extract_metadata(dest, ext)
                thumb_rel = media_proc.make_thumbnails(dest, THUMBS, item_id, ext)

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
                "width": meta.get("width", 0),
                "height": meta.get("height", 0),
                "aspect_ratio": meta.get("aspect_ratio", 1.0),
                "duration": meta.get("duration", 0.0),
                "fps": meta.get("fps", 0.0),
                "codec": meta.get("codec", ""),
                "dominant_color": meta.get("dominant_color", "#1a1d24"),
                "palette_json": json.dumps(meta.get("palette", []), ensure_ascii=False),
                "exif_json": json.dumps(meta.get("exif", {}), ensure_ascii=False),
                "phash": meta.get("phash", ""),
                # 授权字段（C-11）：可在上传时指定，默认保留一切权利
                "license": license_name or "",
                "license_url": license_url or "",
                "credit": credit or "",
                "copyright_holder": copyright_holder or "",
                "commercial_ok": commercial_ok,
                "ts": int(time.time()),
            }
            db.upsert_item(rec)

            if fast:
                # 提交异步处理任务；失败不影响入库（资产仍可通过原图访问）
                try:
                    job_id = tasks.enqueue("media_process", {"item_id": item_id})
                    rec["_job_id"] = job_id
                    rec["_processing"] = True
                except Exception as e:
                    print(f"[upload] 入队失败 {item_id}: {e}", file=sys.stderr)
            saved = db.get_item(item_id) or rec

            # 视频入库后异步生成悬停预览与兼容播放副本
            if rec["kind"] == "video" and start_workers:
                tasks.enqueue("video_postprocess", {"item_id": item_id})
            # AI 自动打标入队（B-07）：是否真正执行由任务内开关决定，
            # 未开启时任务标记 skipped，成本为零。
            if start_workers and rec["kind"] == "image":
                tasks.enqueue("ai_tagging", {"item_id": item_id})
            if start_workers:
                tasks.broadcast("library_updated", {"reason": "upload", "item_id": item_id})
            # 同步模式下才可能已算好近似重复；异步模式由任务完成后回传
            return saved, True, None

    def _find_by_short_id(short: str) -> Optional[Dict[str, Any]]:
        """按短 ID（id 前 6–8 位）定位资产，供 /a/ 语义路由使用（E-19）。

        短 ID 是 id 的前缀，命中多条时取最新一条，避免歧义报错。
        """
        short = (short or "").strip().lower()
        if not re.match(r"^[0-9a-f]{6,32}$", short):
            return None
        rows = db.find_by_id_prefix(short)
        return rows[0] if rows else None

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
                if not s:
                    # 后缀区间 bytes=-N：取文件最后 N 字节（部分播放器
                    # 会用这种方式探测文件尾部的 moov）
                    n = int(e)
                    if n <= 0:
                        raise ValueError
                    start = max(0, size - n)
                    end = size - 1
                else:
                    start = int(s)
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
        # 未启用新前端时，根路径直接进入管理后台
        return RedirectResponse(url="/admin", status_code=302)

    @app.get("/admin", response_class=HTMLResponse)
    @app.get("/admin/", response_class=HTMLResponse)
    def admin_shell():
        """管理员后台：旧版单页前端（完整管理能力）。

        旧前端的资源引用是绝对路径 /static/app.css 与 /static/app.js，
        因此原样托管即可，无需改写，两套前端互不干扰：
          /admin  -> 管理后台（旧单页：上传、删除、合集、回收站、任务、统计）
          /app    -> 用户主页（新前端：卡片流浏览、检索、筛选）
        """
        shell = _read_shell(STATIC_DIR)
        if shell is None:
            raise HTTPException(status_code=404, detail="旧前端不存在")
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    @app.get("/app", response_class=HTMLResponse)
    @app.get("/app/{spa_path:path}", response_class=HTMLResponse)
    def app_shell(spa_path: str = ""):
        """新前端 SPA 回退：非 assets 路径一律返回 index.html，由前端路由接管。"""
        shell = _read_shell(APP_DIR)
        if shell is None:
            raise HTTPException(status_code=404, detail="新前端未构建")
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    @app.get("/a/{slug_id}", response_class=HTMLResponse)
    def asset_page(slug_id: str, request: Request):
        """语义资产页 /a/{slug}-{shortId}（REQ-V2-20 E-19）。

        以短 ID 为准定位资产：slug 仅用于可读性与分享，冲突或改名不影响访问。
        请求已是 canonical 地址时直接渲染分享页——不能 307 到同一个地址，
        否则构成重定向死循环（sitemap 收录的全部 /a/ URL 此前都无法访问）。
        旧 /s/{id} 保留渲染并借 canonical 指向新地址，不破坏既有分享链接。
        """
        short = slug_id.rsplit("-", 1)[-1]
        it = _find_by_short_id(short)
        if not it:
            raise HTTPException(status_code=404, detail="资源不存在或已删除")
        # slug 缺失时先补齐，保证 canonical 与 sitemap 一致
        if not it.get("slug"):
            it["slug"] = db.ensure_slug(it["id"])
        canonical = export_seo.asset_path(it.get("slug") or "", it["id"])
        if f"/a/{slug_id}" != canonical:
            return RedirectResponse(url=canonical, status_code=301)
        return _render_share_html(it, request)

    @app.get("/s/{item_id}", response_class=HTMLResponse)
    def share_page(item_id: str, request: Request):
        it = db.get_item(item_id)
        if not it or it.get("deleted_at"):
            raise HTTPException(status_code=404, detail="资源不存在或已删除")
        return _render_share_html(it, request)

    def _render_share_html(it: Dict[str, Any], request: Request) -> HTMLResponse:
        """渲染资产分享页（/s/ 与 /a/ 共用）。

        浏览量计数做基础 bot 排除：sitemap 收录后爬虫会持续抓取，
        不排除的话 views 全是爬虫贡献，运营数据失真。
        """
        ua = request.headers.get("user-agent", "").lower()
        is_bot = any(s in ua for s in ("bot", "spider", "crawl", "slurp"))
        status = it.get("status") or "published"
        due = status == "draft" and int(it.get("publish_at") or 0) <= int(time.time())
        # 预览未发布/已归档资产不应污染公开浏览量（仅统计与前台可见口径一致的访问）
        if not is_bot and (status == "published" or due):
            db.increment_counter(it["id"], "views")
        base_url = str(request.base_url).rstrip("/")
        title_esc = html.escape(it["title"] or it["name"])
        thumb_url = f"{base_url}/t/{it['id']}.jpg"
        # OG 图/视频海报：缩略图缺失时图片回退到按需变换，避免分享卡片空白
        if it["kind"] == "image" and not os.path.isfile(os.path.join(THUMBS, f"{it['id']}.jpg")):
            thumb_url = f"{base_url}/img/{it['id']}?w=1200&fm=jpg"
        original_url = f"{base_url}/f/{it['file']}"
        if it["kind"] == "video":
            # 视频优先用后端生成的 H.264 兼容副本：HEVC/MKV 原文件在浏览器里
            # 直接播放会黑屏，分享页必须走 ?play=1（与灯箱同款口径）；
            # 兼容副本可能仍在转码或已丢失，只有真实存在时才指向它。
            has_play = bool(it.get("play_file")) and os.path.isfile(
                os.path.join(PLAY_DIR, it["play_file"])
            )
            media_url = f"{original_url}?play=1" if has_play else original_url
        else:
            # 图片展示走按需变换（1920 长边 WebP）：分享页直接塞原图
            # 会让 20MB 的素材拖慢首屏，而下载按钮仍指向原文件
            media_url = f"{base_url}/img/{it['id']}?w=1920&fm=webp"
        tags_list = [str(t) for t in (it.get("tags") or []) if t]
        tags_esc = html.escape(" ".join(f"#{t}" for t in tags_list))
        dim_info = f"{it['width']}×{it['height']}" if it.get("width") else ""
        ext_info = (it.get("ext") or "").lstrip(".").upper()
        size_bytes = int(it.get("size") or 0)
        if size_bytes >= 1024 * 1024:
            size_info = f"{size_bytes / (1024 * 1024):.2f} MB"
        elif size_bytes >= 1024:
            size_info = f"{size_bytes / 1024:.1f} KB"
        elif size_bytes > 0:
            size_info = f"{size_bytes} B"
        else:
            size_info = ""
        spec_parts = [p for p in (dim_info, ext_info, size_info) if p]
        if it["kind"] == "video" and it.get("duration"):
            total = int(round(float(it["duration"])))
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            spec_parts.insert(0, f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
        spec_esc = html.escape(" · ".join(spec_parts))
        desc_esc = html.escape(f"{it['kind'].upper()} · {dim_info} · {tags_esc}".strip(" ·"))
        og_type = "video.other" if it["kind"] == "video" else "website"
        # 语义 URL 与结构化数据（E-19）：slug 缺失时先补齐，保证 canonical 稳定
        if not it.get("slug"):
            it["slug"] = db.ensure_slug(it["id"])
        asset_rel = export_seo.asset_path(it.get("slug") or "", it["id"])
        canonical_url = f"{base_url}{asset_rel}"
        app_url = f"/app{asset_rel}"
        jsonld = json.dumps(
            export_seo.jsonld_for_item(it, base_url=base_url), ensure_ascii=False
        ).replace("</", "<\\/")

        # 主色板解析
        palette_list: List[str] = []
        try:
            raw_pal = json.loads(it.get("palette_json") or "[]")
            if isinstance(raw_pal, list):
                palette_list = [str(c) for c in raw_pal if re.match(r"^#[0-9a-fA-F]{6}$", str(c))][:4]
        except Exception:
            palette_list = []
        if not palette_list and re.match(r"^#[0-9a-fA-F]{6}$", str(it.get("dominant_color") or "")):
            palette_list = [str(it["dominant_color"])]

        swatches_html = "".join(
            f'<button type="button" class="swatch" data-hex="{html.escape(c.upper())}" '
            f'title="复制色值 {html.escape(c.upper())}">'
            f'<i class="swatch__dot" style="background:{html.escape(c)}"></i>'
            f'<span>{html.escape(c.upper())}</span></button>'
            for c in palette_list
        )
        tags_html = "".join(
            f'<a class="tag" href="/app/?tag={quote(t)}">#{html.escape(t)}</a>'
            for t in tags_list[:12]
        )
        author_esc = html.escape(str(it.get("author") or it.get("credit") or ""))
        license_esc = html.escape(str(it.get("license") or ""))
        notes_esc = html.escape(str(it.get("notes") or "").strip())
        personal_only = it.get("commercial_ok") == 0 or it.get("commercial_ok") is False
        added_date = time.strftime("%Y-%m-%d", time.localtime(int(it.get("ts") or time.time())))
        stage_tools = (
            '<div class="stage__tools" aria-label="看图底色">'
            '<button type="button" class="stage-bg is-on" data-bg="sunken" title="默认底色">默认</button>'
            '<button type="button" class="stage-bg" data-bg="dark" title="暗夜底色">暗底</button>'
            '<button type="button" class="stage-bg" data-bg="grid" title="透明棋盘格">透明格</button>'
            '</div>'
            if it["kind"] != "video"
            else ""
        )

        media_tag = (
            f'<video src="{media_url}" poster="{thumb_url}" controls autoplay playsinline '
            f'class="stage__media"></video>'
            if it["kind"] == "video"
            else f'<img id="stageImg" src="{media_url}" data-full="{original_url}" alt="{title_esc}" '
            f'class="stage__media stage__img" title="点击或按 Z 放大查看原图">'
        )

        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_esc} - MediaLib</title>
<link rel="canonical" href="{canonical_url}">
<script type="application/ld+json">{jsonld}</script>
<meta name="description" content="{desc_esc}">
<meta property="og:title" content="{title_esc}">
<meta property="og:url" content="{canonical_url}">
<meta property="og:description" content="{desc_esc}">
<meta property="og:type" content="{og_type}">
<meta property="og:image" content="{thumb_url}">
{f'<meta property="og:video" content="{media_url}">' if it["kind"] == "video" else ""}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title_esc}">
<meta name="twitter:image" content="{thumb_url}">
<script>
(function(){{try{{var m=localStorage.getItem('medialib.theme')||'auto';var d=m==='dark'||(m==='auto'&&window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.dataset.theme=d?'dark':'light';}}catch(e){{}}}})();
</script>
<style>
:root,html[data-theme="light"]{{--paper:#faf8f5;--surface:#fff;--sunken:#f4f0ea;--ink:#1a1815;--muted:#6f6a63;--rule:#e0d9cf;--accent:#8c6a4a;--accent-hover:#6f5238;--on-accent:#fdfcfa;--danger:#b04a3f;--danger-soft:#f7e8e6;--shadow:0 20px 56px rgba(26,24,21,.10);color-scheme:light}}
html[data-theme="dark"]{{--paper:#14120f;--surface:#1c1a16;--sunken:#0f0d0b;--ink:#ede8e1;--muted:#9c958c;--rule:#2b2721;--accent:#a8825e;--accent-hover:#8c6a4a;--on-accent:#14120f;--danger:#d9776c;--danger-soft:#2c1c19;--shadow:0 20px 56px rgba(0,0,0,.55);color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Segoe UI",sans-serif;min-height:100dvh;display:flex;flex-direction:column}}
.topbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px;border-bottom:1px solid var(--rule);background:var(--paper)}}
.brand{{display:inline-flex;align-items:center;gap:8px;font-weight:600;color:var(--ink);text-decoration:none;letter-spacing:-.02em}}
.brand__mark{{color:var(--accent)}}
.topbar__actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.icon-btn{{width:36px;height:36px;border-radius:8px;border:1px solid var(--rule);background:var(--surface);color:var(--muted);cursor:pointer;display:grid;place-items:center;font-size:.95rem}}
.icon-btn:hover{{color:var(--ink);background:var(--sunken)}}
.main{{flex:1;display:grid;grid-template-columns:minmax(0,1fr) 332px;gap:24px;max-width:1440px;width:100%;margin:0 auto;padding:24px 20px 32px;align-items:start}}
.stage{{background:var(--sunken);border:1px solid var(--rule);border-radius:12px;min-height:min(72dvh,760px);display:grid;grid-template-rows:minmax(0,1fr) auto;place-items:center;gap:14px;padding:20px 20px 14px;overflow:hidden;position:relative;transition:background-color .2s ease}}
.stage[data-bg="dark"]{{background:#12100d}}
.stage[data-bg="grid"]{{background-color:#d9d5ce;background-image:linear-gradient(45deg,#c4bfb7 25%,transparent 25%),linear-gradient(-45deg,#c4bfb7 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#c4bfb7 75%),linear-gradient(-45deg,transparent 75%,#c4bfb7 75%);background-size:20px 20px;background-position:0 0,0 10px,10px -10px,-10px 0}}
.stage__tools{{display:inline-flex;gap:2px;padding:3px;border-radius:999px;background:color-mix(in srgb,var(--surface) 90%,transparent);backdrop-filter:blur(8px);border:1px solid var(--rule)}}
.stage-bg{{border:none;background:transparent;color:var(--muted);font-size:.75rem;padding:3px 10px;border-radius:999px;cursor:pointer;transition:background-color .15s,color .15s}}
.stage-bg:hover{{color:var(--ink)}}
.stage-bg.is-on{{background:var(--accent);color:var(--on-accent);font-weight:500}}
.stage__media{{max-width:100%;max-height:calc(100dvh - 220px);width:auto;height:auto;object-fit:contain;border-radius:6px;box-shadow:var(--shadow)}}
.stage__img{{cursor:zoom-in;transition:transform .2s ease}}
.stage.is-zoomed{{position:fixed;inset:0;z-index:99;border-radius:0;border:none;background:rgba(18,16,13,.95);padding:20px;overflow:auto}}
.stage.is-zoomed .stage__tools{{display:none}}
.stage.is-zoomed .stage__media{{max-width:none;max-height:none;cursor:zoom-out;box-shadow:none}}
.aside{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:20px;display:flex;flex-direction:column;gap:16px}}
.title{{margin:0;font-size:1.25rem;line-height:1.35;word-break:break-word;overflow-wrap:anywhere}}
.badge-personal{{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:4px;font-size:.75rem;font-weight:500;background:var(--danger-soft);color:var(--danger);vertical-align:middle}}
.notes{{margin:0;padding:8px 12px;border-left:2px solid var(--accent);background:var(--sunken);border-radius:0 6px 6px 0;font-size:.8125rem;line-height:1.5;white-space:pre-wrap;word-break:break-word}}
.spec{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8125rem;color:var(--muted)}}
.meta-list{{margin:0;display:grid;gap:8px;font-size:.875rem;border-top:1px solid var(--rule);padding-top:14px}}
.meta-row{{display:flex;justify-content:space-between;gap:12px}}
.meta-row dt{{color:var(--muted)}}
.meta-row dd{{margin:0;text-align:right;word-break:break-word;font-variant-numeric:tabular-nums}}
.tags{{display:flex;flex-wrap:wrap;gap:6px}}
.tag{{font-size:.75rem;padding:2px 10px;border-radius:999px;background:var(--sunken);color:var(--muted);text-decoration:none;border:1px solid transparent;transition:border-color .15s,color .15s}}
.tag:hover{{color:var(--ink);border-color:var(--rule)}}
.swatches{{display:flex;gap:8px;flex-wrap:wrap}}
.swatch{{display:inline-flex;align-items:center;gap:7px;padding:4px 10px 4px 5px;border-radius:999px;border:1px solid var(--rule);background:var(--sunken);color:var(--ink);cursor:pointer;transition:transform .15s ease,border-color .15s ease}}
.swatch:hover{{transform:translateY(-1px);border-color:var(--accent)}}
.swatch__dot{{width:18px;height:18px;border-radius:50%;border:1px solid rgba(255,255,255,.28);box-shadow:inset 0 0 0 1px rgba(0,0,0,.18);flex-shrink:0}}
.swatch span{{font-size:.75rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted)}}
.actions{{display:flex;flex-direction:column;gap:8px;margin-top:4px}}
.btn{{display:inline-flex;align-items:center;justify-content:center;min-height:38px;padding:0 16px;border-radius:8px;font-size:.875rem;font-weight:500;text-decoration:none;cursor:pointer;border:1px solid var(--rule);background:var(--surface);color:var(--ink);transition:background-color .15s ease}}
.btn:hover{{background:var(--sunken)}}
.btn--primary{{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}}
.btn--primary:hover{{background:var(--accent-hover)}}
@media (max-width:900px){{.main{{grid-template-columns:1fr;padding:16px}}.stage{{min-height:48dvh}}.stage__media{{max-height:66dvh}}}}
</style>
</head>
<body>
<header class="topbar">
  <a class="brand" href="/app/"><span class="brand__mark">◐</span><span>MediaLib</span></a>
  <div class="topbar__actions">
    <button type="button" id="themeBtn" class="icon-btn" title="切换明暗主题" aria-label="切换明暗主题">◐</button>
    <a class="btn" href="{app_url}">在库中打开</a>
    <a class="btn btn--primary" href="/f/{it['file']}?dl=1" download>下载原文件</a>
  </div>
</header>
<main class="main">
  <div id="stage" class="stage">{media_tag}{stage_tools}</div>
  <aside class="aside">
    <h1 class="title">{title_esc}{'<span class="badge-personal">仅限个人使用</span>' if personal_only else ''}</h1>
    {f'<div class="spec">{spec_esc}</div>' if spec_esc else ''}
    {f'<blockquote class="notes">{notes_esc}</blockquote>' if notes_esc else ''}
    <dl class="meta-list">
      {f'<div class="meta-row"><dt>作者</dt><dd>{author_esc}</dd></div>' if author_esc else ''}
      {f'<div class="meta-row"><dt>授权</dt><dd>{license_esc}</dd></div>' if license_esc else ''}
      <div class="meta-row"><dt>入库时间</dt><dd>{added_date}</dd></div>
      <div class="meta-row"><dt>浏览 / 下载</dt><dd>{int(it.get("views") or 0)} / {int(it.get("downloads") or 0)}</dd></div>
    </dl>
    {f'<div class="tags">{tags_html}</div>' if tags_html else ''}
    {f'<div class="swatches">{swatches_html}</div>' if swatches_html else ''}
    <div class="actions">
      <button type="button" id="copyBtn" class="btn" data-url="{canonical_url}">复制分享链接 (C)</button>
      <a class="btn" href="/app/">浏览全部资产</a>
    </div>
  </aside>
</main>
<script>
(function(){{
  var root=document.documentElement,tb=document.getElementById('themeBtn');
  function syncTb(){{if(tb)tb.textContent=root.dataset.theme==='dark'?'☾':'☀';}}
  syncTb();
  if(tb){{tb.addEventListener('click',function(){{
    var next=root.dataset.theme==='dark'?'light':'dark';
    root.dataset.theme=next;syncTb();
    try{{localStorage.setItem('medialib.theme',next);}}catch(e){{}}
  }});}}
  var stage=document.getElementById('stage'),img=document.getElementById('stageImg');
  function toggleZoom(){{
    if(!img||!stage)return;
    if(!stage.classList.contains('is-zoomed')&&img.dataset.full){{img.src=img.dataset.full;}}
    stage.classList.toggle('is-zoomed');
  }}
  if(img){{img.addEventListener('click',toggleZoom);}}
  document.querySelectorAll('.stage-bg').forEach(function(b){{b.addEventListener('click',function(e){{
    e.stopPropagation();
    document.querySelectorAll('.stage-bg').forEach(function(x){{x.classList.remove('is-on');}});
    b.classList.add('is-on');
    var bg=b.dataset.bg||'sunken';
    if(bg==='sunken')stage.removeAttribute('data-bg');else stage.setAttribute('data-bg',bg);
  }});}});
  var cb=document.getElementById('copyBtn');
  function copyShare(){{
    if(!cb)return;
    if(navigator.clipboard)navigator.clipboard.writeText(cb.dataset.url||'');
    cb.textContent='✓ 已复制链接';setTimeout(function(){{cb.textContent='复制分享链接 (C)';}},1600);
  }}
  if(cb){{cb.addEventListener('click',copyShare);}}
  document.addEventListener('keydown',function(e){{
    if(e.key==='Escape'&&stage)stage.classList.remove('is-zoomed');
    if((e.key==='z'||e.key==='Z')&&img)toggleZoom();
    if((e.key==='c'||e.key==='C')&&!e.metaKey&&!e.ctrlKey)copyShare();
  }});
  document.querySelectorAll('.swatch').forEach(function(b){{b.addEventListener('click',function(){{
    var h=b.dataset.hex||'';if(navigator.clipboard)navigator.clipboard.writeText(h);
    var s=b.querySelector('span');if(s){{var o=s.textContent;s.textContent='已复制';setTimeout(function(){{s.textContent=o;}},1200);}}
  }});}});
}})();
</script>
</body>
</html>""")

    @app.get("/sitemap.xml")
    def sitemap(request: Request):
        """单文件 sitemap，仅收录 published（E-19 验收 2）。

        全库查询 + 拼装不便宜，加短缓存头让爬虫与浏览器复用结果。
        """
        items = db.list_published_items()
        xml = export_seo.sitemap_xml(items, base_url=str(request.base_url).rstrip("/"))
        return Response(
            content=xml,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.get("/robots.txt")
    def robots(request: Request):
        txt = export_seo.robots_txt(str(request.base_url).rstrip("/"))
        return Response(
            content=txt,
            media_type="text/plain",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": "2.0.0", "pid": os.getpid()}

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
            # 下载=再次分发：软删除资产不允许下载（须先恢复），
            # 普通浏览放行以保持回收站预览可用
            if it.get("deleted_at"):
                raise HTTPException(status_code=404, detail="资源已删除，请先从回收站恢复")
            # 文件缺失时不要先计数，否则下载统计会被 404 请求虚增
            if not os.path.isfile(os.path.join(FILES, it["file"])):
                raise HTTPException(status_code=404, detail="文件不存在")
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
        # fit 是外部输入，白名单外一律按 cover 处理，避免把任意字符串
        # 透传到图像处理层
        fit = fit if fit in ("cover", "contain", "fill") else "cover"
        w = img_transform.clamp_dimension(w)
        h = img_transform.clamp_dimension(h)
        # 未指定尺寸或非白名单档位：按原图返回，不落缓存
        # （避免把原图复制一份进缓存目录）
        if w is None and h is None:
            return _serve_range_file(request, src_path)
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
    def api_facets(
        kind: str = "",
        ext: str = "",
        orientation: str = "",
        platform: str = "",
        tag: str = "",
        exclude_tag: str = "",
        q: str = "",
        color: str = "",
        size_class: str = "",
    ):
        """分面统计（REQ-V2-20 B-10）。

        返回各筛选维度的可选值与计数，前端据此渲染分面面板并对零结果项置灰。
        关键词、标签、主色都参与上下文：否则筛选后其余维度的计数仍是全集，
        点选后结果数与徽标对不上。
        """
        tags_list = [t.strip() for t in tag.split(",") if t.strip()] if tag else []
        ex_list = [t.strip() for t in exclude_tag.split(",") if t.strip()] if exclude_tag else []
        return db.get_facets(
            kind=kind, ext=ext, orientation=orientation, platform=platform,
            tags=tags_list, exclude_tags=ex_list,
            q=q, color=color, size_class=size_class,
        )

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
        size_class: str = "",
        sort: str = "newest",
        deleted: bool = False,
        status: str = "",
        include_unpublished: bool = False,
        seed: int = Query(0, ge=0, le=2147483646),
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
            size_class=size_class,
            sort=sort,
            deleted=deleted,
            status=status,
            include_unpublished=include_unpublished,
            seed=seed,
        )
        return {"total": total, "items": items}

    @app.get("/api/item/{item_id}")
    def api_get_item(item_id: str, view: bool = False):
        if not re.match(r"^[0-9a-f]{6,32}$", item_id):
            raise HTTPException(status_code=404, detail="not found")
        it = db.get_item(item_id)
        if not it:
            raise HTTPException(status_code=404, detail="not found")
        # 已删除资产不计数不返回详情，与 /s/ 分享页口径一致
        if it.get("deleted_at"):
            raise HTTPException(status_code=404, detail="not found")
        if view:
            db.increment_counter(item_id, "views")
        return it

    @app.get("/api/item/{item_id}/similar")
    def api_similar_items(item_id: str, limit: int = Query(12, ge=1, le=30)):
        return {"items": db.find_similar(item_id, limit=limit)}

    @app.get("/api/resolve/{short_id}")
    def api_resolve_short(short_id: str):
        """按短 ID（6–8 位前缀）解析资产，供 SPA 的 /app/a/ 兼容路由定位。"""
        it = _find_by_short_id(short_id)
        if not it:
            raise HTTPException(status_code=404, detail="not found")
        return it

    class LicenseReq(BaseModel):
        license: Optional[str] = None
        license_url: Optional[str] = None
        credit: Optional[str] = None
        copyright_holder: Optional[str] = None
        commercial_ok: Optional[bool] = None
        license_expires_at: Optional[int] = None

    @app.patch("/api/item/{item_id}/license")
    def api_update_license(item_id: str, req: LicenseReq):
        """更新授权与可商用信息（REQ-V2-20 C-11）。"""
        if not re.match(r"^[0-9a-f]{6,32}$", item_id):
            raise HTTPException(status_code=404, detail="not found")
        if not db.get_item(item_id):
            raise HTTPException(status_code=404, detail="not found")
        fields = {k: v for k, v in req.model_dump().items() if v is not None}
        updated = db.update_license(item_id, **fields)
        return updated

    class StatusReq(BaseModel):
        status: str
        publish_at: Optional[int] = None

    @app.patch("/api/item/{item_id}/status")
    def api_set_status(item_id: str, req: StatusReq):
        """发布状态与定时发布（REQ-V2-20 C-12）。

        非法流转返回 409 并给出允许路径，而不是静默接受。
        """
        if not re.match(r"^[0-9a-f]{6,32}$", item_id):
            raise HTTPException(status_code=404, detail="not found")
        if not db.get_item(item_id):
            raise HTTPException(status_code=404, detail="not found")
        ok, msg = db.set_status(item_id, req.status, req.publish_at)
        if not ok:
            raise HTTPException(status_code=409, detail=msg)
        return {"ok": True, "item": db.get_item(item_id)}

    @app.post("/api/publish/sweep")
    def api_publish_sweep():
        """把到期的定时发布项落为 published（C-12 调度侧）。"""
        n = db.publish_due_items()
        return {"ok": True, "published": n}

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

        # 授权与署名（REQ-V2-20 C-11）：可在上传时一并指定
        license_name = str(form.get("license", "") or "")
        license_url = str(form.get("license_url", "") or "")
        credit = str(form.get("credit", "") or "")
        copyright_holder = str(form.get("copyright_holder", "") or "")
        commercial_raw = str(form.get("commercial_ok", "1") or "1").lower()
        commercial_ok = commercial_raw not in ("0", "false", "no")
        # 兼容 CLI 入库脚本：需要同步拿到元数据时传 synchronous=1
        sync_raw = str(form.get("synchronous", "") or "").lower()
        synchronous = sync_raw in ("1", "true", "yes")

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
                    if total_bytes == 0:
                        # 空文件不应进入资产库：既占记录又无法生成缩略图
                        os.remove(tp)
                        continue
                    files_to_save.append((tp, val.filename))

            if not files_to_save:
                raise HTTPException(status_code=400, detail="文件为空或未选择文件")

            out = []
            file_errors: List[str] = []
            for tp, fname in files_to_save:
                try:
                    rec, is_new, near_dup = store_file(
                        tp, fname, title=title, tags=tags, source=source,
                        synchronous=synchronous, license_name=license_name,
                        license_url=license_url, credit=credit,
                        copyright_holder=copyright_holder, commercial_ok=commercial_ok,
                    )
                except ValueError as e:
                    # 单个文件类型不支持不应让整批失败：
                    # 已成功入库的文件照常返回，错误按文件名回传
                    file_errors.append(f"{fname}: {e}")
                    continue
                rec = dict(rec)
                rec["duplicate"] = not is_new
                if near_dup and near_dup["id"] != rec["id"]:
                    rec["near_duplicate_id"] = near_dup["id"]
                out.append(rec)
            if not out and file_errors:
                raise HTTPException(status_code=400, detail="; ".join(file_errors))
            return {
                "ok": True,
                "count": len(out),
                "items": out,
                "errors": file_errors,
            }
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
        # 直接按 deleted_at 物理删：走 query_items(limit=100000) 在超大库会漏删
        removed = db.permanent_delete_all_trashed()
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
            # 画板不存在时返回 404，而不是静默 ok+0：前端会误报「已加入」
            if not db.get_collection(req.collection_id):
                raise HTTPException(status_code=404, detail="画板不存在")
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
    def api_download_zip(req: ZipReq, request: Request):
        """批量导出（REQ-V2-20 C-13）。

        改造点：
          1. 不再全内存打包——写临时文件后流式返回，内存峰值与原图体积无关
          2. 支持多规格导出（preset/format/quality），复用 export_seo 的渲染路径
          3. 包内强制附带 credits.txt 与 metadata.json
        """
        if not req.ids:
            raise HTTPException(status_code=400, detail="未选择任何文件")

        items: List[Dict[str, Any]] = []
        total_bytes = 0
        # 不再静默截断到 200 项：超过同步阈值会转异步任务，静默丢项
        # 会让用户以为「选了多少就导出多少」。重复 id 先去重。
        for iid in dict.fromkeys(req.ids):
            it = db.get_item(iid)
            if not it or it.get("deleted_at"):
                continue
            items.append(it)
            total_bytes += int(it.get("size") or 0)
        if not items:
            raise HTTPException(status_code=404, detail="没有可导出的文件")

        base_url = str(request.base_url).rstrip("/")
        # 超过阈值转异步任务，避免长请求（C-13 验收 2）
        if export_seo.needs_async(items, total_bytes):
            payload = {
                "ids": [i["id"] for i in items],
                "preset": req.preset,
                "format": req.format,
                "quality": req.quality,
                "base_url": base_url,
            }
            job_id = tasks.enqueue("export_zip", payload)
            return JSONResponse(
                status_code=202,
                content={
                    "async": True,
                    "job_id": job_id,
                    "count": len(items),
                    "message": "导出任务已提交，完成后在任务中心下载",
                },
            )

        # 同步导出也写临时文件后由 FileResponse 流式发送：
        # build_zip_memory 会把整包读进内存（最大 200MB），
        # 小批量导出没必要占用这么多内存
        fd, tmp_zip = tempfile.mkstemp(prefix="mlib-pack-", suffix=".zip", dir=DATA)
        os.close(fd)
        try:
            export_seo.build_zip_to_path(
                FILES,
                items,
                tmp_zip,
                preset=req.preset,
                fmt=req.format,
                quality=req.quality,
                base_url=base_url,
            )
        except Exception as e:
            try:
                os.remove(tmp_zip)
            except OSError:
                pass
            raise HTTPException(status_code=500, detail=f"导出失败: {e}")

        def _cleanup_pack(path: str = tmp_zip):
            try:
                os.remove(path)
            except OSError:
                pass

        return FileResponse(
            tmp_zip,
            media_type="application/zip",
            filename="medialib-pack.zip",
            background=BackgroundTask(_cleanup_pack),
        )

    @app.get("/api/exports/{name}")
    def api_download_export(name: str):
        """下载异步导出产物（REQ-V2-20 C-13）。"""
        if not re.match(r"^medialib-\d+\.zip$", name):
            raise HTTPException(status_code=404, detail="not found")
        exports_dir = os.path.join(DATA, "exports")
        _cleanup_old_exports(exports_dir)
        path = os.path.join(exports_dir, name)
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="导出文件不存在或已过期")
        return FileResponse(
            path,
            media_type="application/zip",
            filename=name,
            headers={"Cache-Control": "private, max-age=0, must-revalidate"},
        )

    def _cleanup_old_exports(exports_dir: str, keep_days: int = 7):
        """清理过期导出产物：exports 目录没有别的回收机制，ZIP 会无限堆积。"""
        try:
            cutoff = time.time() - keep_days * 86400
            for fn in os.listdir(exports_dir):
                fp = os.path.join(exports_dir, fn)
                if os.path.isfile(fp) and os.stat(fp).st_mtime < cutoff:
                    os.remove(fp)
        except OSError:
            pass

    # ---------- AI 自动打标（B-07） ----------

    class TagItemReq(BaseModel):
        item_id: str
        force: bool = False

    @app.post("/api/ai/tag")
    def api_ai_tag(req: TagItemReq):
        """手动触发单条打标（B-07）。

        与自动打标共用同一任务；未开启自动开关时，手动触发仍可执行。
        """
        # 先判能力再判资产：能力缺失时 501 更能说明问题（B-07 验收 4 的口径）
        prov = _ai_provider()
        if not prov.available():
            raise HTTPException(
                status_code=501,
                detail="AI 检索未启用：配置 MEDIA_LIB_AI_PROVIDER 与 API Key 后可用",
            )
        if not db.get_item(req.item_id):
            raise HTTPException(status_code=404, detail="not found")
        job_id = tasks.enqueue("ai_tagging", {"item_id": req.item_id, "force": req.force})
        return {"ok": True, "job_id": job_id}

    @app.get("/api/ai/tags/{item_id}")
    def api_ai_tags(item_id: str):
        """查看某资产的 AI 来源标签与已否决标签（B-07）。"""
        it = db.get_item(item_id)
        if not it:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "item_id": item_id,
            "tags": it.get("tags") or [],
            "rejected": db.rejected_tags(item_id),
        }

    # ---------- 运营事件与指标（D-18） ----------

    class EventsReq(BaseModel):
        events: List[Dict[str, Any]]

    class MetricsReq(BaseModel):
        metrics: List[Dict[str, Any]]

    @app.post("/api/events")
    def api_add_events(req: EventsReq):
        """批量埋点上报（D-18 验收 4：单次交互合并为一次请求）。

        埋点失败一律静默（返回 ok=false 而非 4xx/5xx），不能影响业务。
        """
        try:
            n = db.add_events(req.events)
            return {"ok": True, "accepted": n}
        except Exception:
            return {"ok": False, "accepted": 0}

    @app.get("/api/events/overview")
    def api_events_overview(days: int = Query(7, ge=1, le=90)):
        """运营看板数据：趋势、资产漏斗、零结果搜索词、设备与来源。"""
        return db.event_overview(days=days)

    @app.post("/api/metrics")
    def api_add_metrics(req: MetricsReq):
        """性能指标上报（默认关闭，由前端开关控制）。"""
        try:
            n = db.add_metrics(req.metrics)
            return {"ok": True, "accepted": n}
        except Exception:
            return {"ok": False, "accepted": 0}

    @app.get("/api/metrics/summary")
    def api_metrics_summary(
        name: str = "",
        days: int = Query(7, ge=1, le=90),
    ):
        """指标分位数（供 CLI 使用，不做前端看板）。"""
        return {"summary": db.metrics_summary(name=name, days=days)}

    # ---------- 人工精选（A-02） ----------

    class FeaturedReq(BaseModel):
        ids: List[str]

    @app.get("/api/featured")
    def api_get_featured():
        """当前人工精选排布（有序）。"""
        return {"ids": db.featured_ids(), "items": db.list_featured()}

    @app.patch("/api/featured")
    def api_set_featured(req: FeaturedReq):
        """整体替换精选排布（A-02 验收 2：返回后下一次请求即呈现新排布）。"""
        count = db.set_featured(req.ids)
        return {"ok": True, "count": count, "items": db.list_featured()}

    @app.get("/api/home/featured")
    def api_home_featured(limit: int = Query(12, ge=1, le=60)):
        """首页置顶区数据：人工精选优先，不足用最近上新补齐。"""
        return {"items": db.featured_items_for_home(limit=limit)}

    # ---------- AI 能力（B-07 / B-08） ----------

    def _ai_provider():
        # 每次取用都重新读环境变量：配好 Key 后无需重启即可切换（B-08 验收 5）
        return AI_PROVIDER_FACTORY()

    @app.get("/api/ai/status")
    def api_ai_status():
        """AI 能力状态（B-08 验收 4/5）：前端据此决定是否显示入口。

        未配置时返回 available=false，而不是报错——入口隐藏但站点正常。
        """
        prov = _ai_provider()
        model_version = prov.embed_model if hasattr(prov, "embed_model") else "none"
        return {
            "provider": prov.name,
            "available": prov.available(),
            "model_version": model_version,
            "embedded": db.count_embeddings(model_version),
            "pending": len(db.missing_embedding_ids(model_version, limit=1000)),
            "hint": "" if prov.available() else "AI 检索未启用：配置 MEDIA_LIB_AI_PROVIDER 与 API Key 后可用",
        }

    @app.get("/api/search/semantic")
    def api_search_semantic(
        q: str = "",
        limit: int = Query(24, ge=1, le=100),
        fuse: bool = True,
    ):
        """以文搜图（B-08）：向量召回 + 与关键词结果 RRF 融合。"""
        prov = _ai_provider()
        if not prov.available():
            # 501：功能不可用（验收 4 明确要求，不能用 500）
            raise HTTPException(
                status_code=501,
                detail="AI 检索未启用：配置 MEDIA_LIB_AI_PROVIDER 与 API Key 后可用",
            )
        q = (q or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="查询不能为空")

        try:
            qvec = prov.embed_text(q)
        except ai_provider.AIUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

        model_version = getattr(prov, "embed_model", "")
        rows = db.iter_embeddings(model_version)
        scored = []
        for row in rows:
            vec = ai_provider.unpack_vector(row["vec"])
            scored.append((ai_provider.cosine(qvec, vec), row["item_id"]))
        scored.sort(reverse=True)
        vec_ids = [iid for s, iid in scored if s > 0][: max(limit * 2, 40)]

        if fuse:
            kw_ids = db.keyword_search_ids(q, limit=max(limit * 2, 40))
            ids = ai_provider.rrf_fuse(kw_ids, vec_ids, limit=limit)
        else:
            ids = vec_ids[:limit]

        items = []
        for iid in ids:
            it = db.get_item(iid)
            if it and not it.get("deleted_at"):
                items.append(it)
        return {"q": q, "total": len(items), "items": items, "fused": fuse}

    @app.post("/api/search/by-image")
    async def api_search_by_image(request: Request):
        """以图搜图（B-08）：拖入/粘贴图片即返回相似资产。

        未配置 provider 时同样返回 501，前端据此隐藏入口。
        """
        prov = _ai_provider()
        if not prov.available():
            raise HTTPException(
                status_code=501,
                detail="AI 检索未启用：配置 MEDIA_LIB_AI_PROVIDER 与 API Key 后可用",
            )
        ctype = request.headers.get("content-type", "")
        if "multipart/form-data" not in ctype:
            raise HTTPException(status_code=400, detail="need multipart/form-data")
        form = await request.form()
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            raise HTTPException(status_code=400, detail="缺少 file 字段")
        # 以图搜图只用于取向量，无需原图全量进内存；限制 20MB 防误传大文件
        MAX_QUERY_IMAGE = 20 * 1024 * 1024
        data = await up.read(MAX_QUERY_IMAGE + 1)
        if not data:
            raise HTTPException(status_code=400, detail="文件为空")
        if len(data) > MAX_QUERY_IMAGE:
            raise HTTPException(status_code=413, detail="搜索图片不能超过 20MB")

        try:
            qvec = prov.embed_image(data)
        except ai_provider.AIUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))

        model_version = getattr(prov, "embed_model", "")
        scored = []
        for row in db.iter_embeddings(model_version):
            scored.append((ai_provider.cosine(qvec, ai_provider.unpack_vector(row["vec"])), row["item_id"]))
        scored.sort(reverse=True)

        items = []
        for score, iid in scored[:24]:
            if score <= 0:
                continue
            it = db.get_item(iid)
            if it and not it.get("deleted_at"):
                items.append(it)
        return {"total": len(items), "items": items}

    @app.post("/api/jobs/embedding-backfill")
    def api_embedding_backfill(limit: int = Query(200, ge=1, le=2000)):
        """向量回填任务（B-08 验收 5：配 Key 后跑一次即可启用）。"""
        prov = _ai_provider()
        if not prov.available():
            raise HTTPException(
                status_code=501,
                detail="AI 检索未启用：配置 MEDIA_LIB_AI_PROVIDER 与 API Key 后可用",
            )
        model_version = getattr(prov, "embed_model", "")
        ids = db.missing_embedding_ids(model_version, limit=limit)
        if not ids:
            return {"ok": True, "queued": 0, "message": "没有待回填的资产"}
        job_id = tasks.enqueue("embedding_backfill", {
            "ids": ids, "model_version": model_version,
        })
        return {"ok": True, "job_id": job_id, "queued": len(ids)}

    class RejectTagsReq(BaseModel):
        item_id: str
        tags: List[str]

    @app.post("/api/ai/reject-tags")
    def api_reject_tags(req: RejectTagsReq):
        """否决 AI 标签（B-07 验收 3）：记入黑名单并移除该标签。"""
        if not db.get_item(req.item_id):
            raise HTTPException(status_code=404, detail="not found")
        db.add_rejected_tags(req.item_id, req.tags)
        db.batch_tags([req.item_id], remove_tags=req.tags)
        return {"ok": True, "rejected": req.tags}

    # ---------- 客户选片与批注（C-14） ----------

    class ReviewLinkReq(BaseModel):
        collection_id: int
        title: str = ""
        message: str = ""
        expires_at: Optional[int] = None

    class ReviewMarkReq(BaseModel):
        item_id: str
        state: str = "pending"
        note: str = ""
        reviewer: str = ""

    @app.post("/api/reviews")
    def api_create_review(req: ReviewLinkReq):
        """为合集生成选片链接（C-14）。token 仅作访问标识，不承担鉴权。"""
        if not db.get_collection(req.collection_id):
            raise HTTPException(status_code=404, detail="合集不存在")
        link = db.create_review_link(
            req.collection_id, req.title, req.message, req.expires_at
        )
        return {"ok": True, "link": link, "url": f"/review/{link['token']}"}

    @app.get("/api/reviews")
    def api_list_reviews():
        return {"links": db.list_review_links()}

    @app.delete("/api/reviews/{token}")
    def api_revoke_review(token: str):
        if not db.revoke_review_link(token):
            raise HTTPException(status_code=404, detail="选片链接不存在")
        return {"ok": True}

    @app.get("/api/review/{token}")
    def api_review_detail(token: str):
        """选片页数据（对外可读，本版不含鉴权）。"""
        link = db.get_review_link(token)
        if not link:
            raise HTTPException(status_code=404, detail="选片链接无效或已失效")
        return {
            "ok": True,
            "link": link,
            "items": db.get_review_items(token),
        }

    @app.post("/api/review/{token}/mark")
    def api_review_mark(token: str, req: ReviewMarkReq):
        ok, msg = db.set_review_mark(
            token, req.item_id, req.state, req.note, req.reviewer
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"ok": True}

    @app.get("/api/review/{token}/summary")
    def api_review_summary(token: str):
        """库主侧批注汇总，按状态分组（C-14）。"""
        data = db.review_summary(token)
        if not data.get("ok"):
            raise HTTPException(status_code=404, detail="选片链接无效或已失效")
        return data

    class ReviewAcceptReq(BaseModel):
        target_collection_id: Optional[int] = None

    @app.post("/api/review/{token}/accept-selected")
    def api_review_accept(token: str, req: ReviewAcceptReq):
        """把「选中」批量加入指定合集（C-14 验收 3）。"""
        data = db.review_summary(token)
        if not data.get("ok"):
            raise HTTPException(status_code=404, detail="选片链接无效或已失效")
        ids = [x["id"] for x in data["states"].get("selected", [])]
        if not ids:
            return {"ok": True, "added": 0}
        if req.target_collection_id is None:
            added = len(ids)
        else:
            if not db.get_collection(req.target_collection_id):
                raise HTTPException(status_code=404, detail="目标合集不存在")
            added = db.add_to_collection(req.target_collection_id, ids)
        return {"ok": True, "added": added, "ids": ids}

    @app.get("/review/{token}", response_class=HTMLResponse)
    def review_page(token: str):
        """选片页外壳：复用新前端 SPA，由前端 /review/:token 路由接管。"""
        shell = _read_shell(APP_DIR)
        if shell is None:
            raise HTTPException(status_code=404, detail="新前端未构建")
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    # ---------- 标签治理（B-09） ----------

    class MergeTagsReq(BaseModel):
        source: str
        target: str

    class RenameTagReq(BaseModel):
        old: str
        new: str

    @app.get("/api/tags")
    def api_list_tags(limit: int = Query(200, ge=1, le=2000)):
        """标签治理列表：频次、层级、别名（B-09）。"""
        return {"tags": db.list_tag_admin(limit=limit)}

    @app.post("/api/tags/merge")
    def api_merge_tags(req: MergeTagsReq):
        res = db.merge_tags(req.source, req.target)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("message", "合并失败"))
        return res

    @app.post("/api/tags/rename")
    def api_rename_tag(req: RenameTagReq):
        res = db.rename_tag(req.old, req.new)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("message", "重命名失败"))
        return res

    # ---------- 个人工作区（C-15） ----------

    class LikeReq(BaseModel):
        item_id: str
        liked: bool = True

    @app.post("/api/like")
    def api_set_like(req: LikeReq):
        if not db.get_item(req.item_id):
            raise HTTPException(status_code=404, detail="not found")
        db.set_liked(req.item_id, req.liked)
        return {"ok": True, "liked": req.liked}

    @app.get("/api/likes")
    def api_list_likes():
        return {"ids": db.list_liked_ids()}

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
        if not db.get_collection(cid):
            raise HTTPException(status_code=404, detail="画板不存在")
        cnt = db.add_to_collection(cid, req.item_ids)
        return {"ok": True, "added": cnt}

    @app.delete("/api/collections/{cid}/items")
    def api_remove_collection_items(cid: int, req: CollectionItemsReq):
        cnt = db.remove_from_collection(cid, req.item_ids)
        return {"ok": True, "removed": cnt}

    # ---------- 任务队列与存储治理 ----------

    @app.get("/api/jobs")
    def api_list_jobs(limit: int = Query(50, ge=1, le=500)):
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
                # 周期心跳：长期无事件时中间代理/浏览器可能掐掉空闲连接，
                # 每 15s 补一个 ping 保活（客户端 EventSource 自动重连忽略 ping）
                import asyncio

                heartbeat = 0.0
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = q.get_nowait()
                        yield msg
                        heartbeat = 0.0
                    except Exception:
                        await asyncio.sleep(0.5)
                        heartbeat += 0.5
                        if heartbeat >= 15:
                            heartbeat = 0.0
                            yield "event: ping\ndata: {}\n\n"
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
            # 按需变换缓存（A-05）：纳入概览便于发现缓存膨胀
            "imgcache": img_transform.cache_stats(IMG_CACHE_DIR),
            "disk_total": disk.total,
            "disk_free": disk.free,
        }

    @app.post("/api/storage/repair")
    def api_storage_repair():
        res = repair_library(db, verbose=False)
        return {"ok": True, **res}

    # ---------- 定时采集与存量后处理运维中心 ----------

    class PipelineConfigUpdateReq(BaseModel):
        scrape: Optional[Dict[str, Any]] = None
        postprocess: Optional[Dict[str, Any]] = None
        vision: Optional[Dict[str, Any]] = None
        accounts_text: Optional[str] = None

    class PipelineActionReq(BaseModel):
        action: str
        proxy: Optional[str] = None

    @app.get("/api/pipeline/config")
    def api_get_pipeline_config():
        return pipeline_config.get_public_config(DATA)

    @app.put("/api/pipeline/config")
    def api_put_pipeline_config(req: PipelineConfigUpdateReq):
        try:
            return pipeline_config.validate_and_save_config(
                DATA, req.model_dump(exclude_none=True)
            )
        except pipeline_config.ConfigValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/pipeline/status")
    def api_get_pipeline_status(
        log_type: str = Query("x_scrape"),
        lines: int = Query(120, ge=10, le=500),
    ):
        return pipeline_config.get_pipeline_status(
            DATA, db=db, log_type=log_type, lines=lines
        )

    @app.post("/api/pipeline/action")
    def api_post_pipeline_action(req: PipelineActionReq):
        try:
            return pipeline_config.trigger_pipeline_action(
                DATA, BASE, req.action, payload=req.model_dump(exclude_none=True)
            )
        except pipeline_config.ConfigValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except pipeline_config.PipelineBusyError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app


def repair_library(db: MediaDB, verbose: bool = True) -> Dict[str, Any]:
    """一致性自检：剔除磁盘缺失的孤儿记录、补全缺失缩略图、报告残留文件。

    必须带 include_unpublished：草稿/归档同样占磁盘、同样需要缩略图，
    只扫可见资产会让它们永远得不到修复。
    """
    _, items = db.query_items(limit=100000, offset=0, include_unpublished=True)
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
    orphan_set = set(orphans)
    known = {it["file"] for it in items if it["id"] not in orphan_set}
    try:
        stray = [f for f in os.listdir(FILES) if f not in known]
    except FileNotFoundError:
        stray = []
    if verbose:
        print(f"[repair] 剔除孤儿 {len(orphans)} 条，补齐缩略图 {fixed_thumb} 个，磁盘未索引残留 {len(stray)} 个")
    return {"orphans_removed": len(orphans), "fixed_thumbs": fixed_thumb, "stray_files": len(stray)}


# ---------- 进程管理（兼容原有 CLI） ----------

def _read_pid() -> Optional[int]:
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        return pid if pid > 0 else None
    except (OSError, ValueError):
        return None


@contextmanager
def _pid_guard():
    with open(PIDFILE + ".lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _health_status(port: int) -> dict:
    try:
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            data = json.load(r)
        return data if isinstance(data, dict) and data.get("ok") is True else {}
    except (OSError, ValueError):
        return {}


def _is_server_process(pid: int, port: int) -> bool:
    if sys.platform != "linux":
        return _health_status(port).get("pid") == pid
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv = [os.fsdecode(v) for v in f.read().split(b"\0") if v]
        index = 1
        while index < len(argv) and argv[index] in ("-B", "-u", "-E", "-I", "-s", "-S"):
            index += 1
        if index >= len(argv) or os.path.realpath(argv[index]) != os.path.realpath(__file__):
            return False
        options = argv[index + 1:]
        process_port = 18100
        for position, option in enumerate(options):
            if option == "--port":
                process_port = int(options[position + 1])
            elif option.startswith("--port="):
                process_port = int(option.partition("=")[2])
        return process_port == port and not any(flag in options for flag in ("--stop", "--status", "--repair"))
    except (OSError, ValueError, IndexError):
        return False


def _listening_server_pid(port: int) -> Optional[int]:
    if sys.platform != "linux":
        return None
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                for line in f.readlines()[1:]:
                    row = line.split()
                    if row[3] == "0A" and int(row[1].split(":")[1], 16) == port:
                        inodes.add(f"socket:[{row[9]}]")
        except FileNotFoundError:
            continue
    if not inodes:
        return None
    for name in os.listdir("/proc"):
        if not name.isdigit() or not _is_server_process(int(name), port):
            continue
        try:
            for fd in os.listdir(f"/proc/{name}/fd"):
                try:
                    if os.readlink(f"/proc/{name}/fd/{fd}") in inodes:
                        return int(name)
                except OSError:
                    continue
        except PermissionError:
            continue
        except FileNotFoundError:
            continue
    return None


def _server_pid(port: int) -> Optional[int]:
    reported = _health_status(port).get("pid")
    if isinstance(reported, int) and reported > 0 and _is_server_process(reported, port):
        return reported
    listening = _listening_server_pid(port)
    if listening is not None:
        return listening
    recorded = _read_pid()
    return recorded if recorded and _is_server_process(recorded, port) else None


def _remove_own_pid(pid: int):
    with _pid_guard():
        if _read_pid() == pid:
            os.remove(PIDFILE)


def cmd_start(port: int, host: str) -> int:
    ensure_dirs()
    with _pid_guard():
        pid = _server_pid(port)
        if pid or _health_status(port):
            print(f"已在运行 pid={pid or '未知'}  http://{host}:{port}/")
            return 0
        with open(PIDFILE, "w") as f:
            f.write(str(os.getpid()))
    print(f"serving on http://{host}:{port}/  data={DATA}")
    sys.stdout.flush()
    try:
        app = create_app(port=port)
        # 优雅退出限时 5 秒：管理台常驻打开 SSE（/api/jobs/stream）连接时，
        # 默认的无限等待会让 SIGTERM 后的进程长期不退出（--stop 超时失败、
        # 旧进程占着 PID 记录导致 ensure.sh 无法拉起新实例）
        uvicorn.run(app, host=host, port=port, log_level="warning",
                    timeout_graceful_shutdown=5)
    except KeyboardInterrupt:
        pass
    finally:
        _remove_own_pid(os.getpid())
    return 0


def cmd_stop(port: int = 18100) -> int:
    ensure_dirs()
    pid = _server_pid(port)
    if pid is None:
        if _health_status(port):
            print("服务在线但无法验证 PID，请以服务运行用户执行停止操作")
            return 1
        print("未运行")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            time.sleep(0.1)
            recorded = _read_pid()
            if (not _is_server_process(pid, port) or recorded not in (None, pid)
                    or (recorded != pid and not _health_status(port))):
                _remove_own_pid(pid)
                print(f"已停止 pid={pid}")
                return 0
        print(f"停止尚未完成 pid={pid}，保留 PID 记录，未强制终止")
        return 1
    except ProcessLookupError:
        _remove_own_pid(pid)
        print(f"进程已退出 pid={pid}")
        return 0
    except PermissionError:
        print(f"无权停止 pid={pid}，请以服务运行用户执行")
        return 1


def cmd_status(port: int) -> int:
    health = _health_status(port)
    if health:
        pid = _server_pid(port)
        print(f"运行中 pid={pid or '未知（PID 记录缺失或不可访问）'} 端口={port} 健康检查正常")
        return 0
    pid = _server_pid(port)
    print(f"进程存在但服务未就绪 pid={pid}" if pid else "未运行")
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
        return cmd_stop(a.port)
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
