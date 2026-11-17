#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""异步任务队列与 SSE 事件广播"""

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import media_proc
from db import MediaDB


class TaskManager:
    """后台异步任务调度器（URL 抓取、视频预览/转码、存量元数据回填）"""

    def __init__(self, db: MediaDB, data_dir: str, scripts_dir: str, port: int = 18100):
        self.db = db
        self.data_dir = data_dir
        self.scripts_dir = scripts_dir
        self.port = port
        self.files_dir = os.path.join(data_dir, "files")
        self.thumbs_dir = os.path.join(data_dir, "thumbs")
        self.previews_dir = os.path.join(data_dir, "previews")
        self.play_dir = os.path.join(data_dir, "play")

        self._q: "queue.Queue[Optional[int]]" = queue.Queue()
        self._subscribers: List[TupleQueue] = []
        self._sub_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._workers: List[threading.Thread] = []

    def start(self, num_workers: int = 2):
        if self._workers:
            return
        for idx in range(num_workers):
            t = threading.Thread(target=self._worker_loop, name=f"mlib-worker-{idx}", daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self):
        self._stop_event.set()
        for _ in self._workers:
            self._q.put(None)

    def subscribe(self) -> "queue.Queue[str]":
        q: "queue.Queue[str]" = queue.Queue(maxsize=100)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[str]"):
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast(self, event: str, data: Dict[str, Any]):
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        with self._sub_lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def enqueue(self, job_type: str, payload: Dict[str, Any]) -> int:
        job_id = self.db.create_job(job_type, payload)
        self.broadcast("job", {"id": job_id, "job_type": job_type, "status": "pending", "progress": 0, "message": "排队中"})
        self._q.put(job_id)
        return job_id

    def _update(self, job_id: int, status: str, progress: int, message: str, result: Optional[Dict[str, Any]] = None):
        self.db.update_job(job_id, status=status, progress=progress, message=message, result=result)
        self.broadcast("job", {
            "id": job_id,
            "status": status,
            "progress": progress,
            "message": message,
            "result": result or {},
        })

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                job_id = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if job_id is None:
                break
            try:
                self._run_job(job_id)
            except Exception as e:
                self._update(job_id, "failed", 100, f"异常: {e}")
            finally:
                self._q.task_done()

    def _run_job(self, job_id: int):
        jobs = self.db.list_jobs(limit=200)
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            return
        jtype = job["job_type"]
        payload = job["payload"]

        if jtype == "ingest_url":
            self._handle_ingest_url(job_id, payload)
        elif jtype == "video_postprocess":
            self._handle_video_postprocess(job_id, payload)
        elif jtype == "backfill_metadata":
            self._handle_backfill(job_id)
        else:
            self._update(job_id, "failed", 100, f"未知任务类型: {jtype}")

    def _handle_ingest_url(self, job_id: int, payload: Dict[str, Any]):
        url = payload.get("url", "").strip()
        tags = payload.get("tags", "")
        title = payload.get("title", "")
        if not url:
            self._update(job_id, "failed", 100, "URL 不能为空")
            return
        self._update(job_id, "running", 15, f"正在解析并抓取: {url[:60]}")
        ingest_py = os.path.join(self.scripts_dir, "ingest.py")
        cmd = [sys.executable, ingest_py, url, "--no-start"]
        if tags:
            cmd += ["--tags", tags]
        if title:
            cmd += ["--title", title]
        env = os.environ.copy()
        env["MEDIA_LIB_API"] = f"http://127.0.0.1:{self.port}"
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
            out_msg = (proc.stderr or proc.stdout or "").strip()
            lines = [ln for ln in out_msg.splitlines() if ln.strip()]
            summary = lines[-1] if lines else ("入库完成" if proc.returncode == 0 else "抓取失败")
            if proc.returncode == 0:
                self._update(job_id, "done", 100, summary, {"log": lines[-10:]})
                self.broadcast("library_updated", {"reason": "ingest_url"})
            else:
                self._update(job_id, "failed", 100, summary, {"log": lines[-10:]})
        except subprocess.TimeoutExpired:
            self._update(job_id, "failed", 100, "抓取超时（>300s）")
        except Exception as e:
            self._update(job_id, "failed", 100, f"执行失败: {e}")

    def _handle_video_postprocess(self, job_id: int, payload: Dict[str, Any]):
        item_id = payload.get("item_id")
        if not item_id:
            return
        it = self.db.get_item(item_id)
        if not it or it["kind"] != "video":
            self._update(job_id, "done", 100, "跳过非视频项")
            return
        src = os.path.join(self.files_dir, it["file"])
        if not os.path.isfile(src):
            self._update(job_id, "failed", 100, "源文件不存在")
            return
        self._update(job_id, "running", 25, "生成视频悬停预览动图")
        prev = media_proc.make_video_preview(src, self.previews_dir, item_id)
        updates: Dict[str, Any] = {}
        if prev:
            updates["preview_file"] = prev
        self._update(job_id, "running", 60, "生成兼容播放副本 (H.264/faststart)")
        play = media_proc.make_compatible_mp4(src, self.play_dir, item_id, codec=it.get("codec", ""), ext=it.get("ext", ""))
        if play:
            updates["play_file"] = play
        if updates:
            self.db.update_item(item_id, updates)
        self._update(job_id, "done", 100, "视频后处理完成", updates)
        self.broadcast("library_updated", {"reason": "video_postprocess", "item_id": item_id})

    def _handle_backfill(self, job_id: int):
        _, items = self.db.query_items(limit=100000, offset=0)
        total = len(items)
        if total == 0:
            self._update(job_id, "done", 100, "暂无需要回填的条目")
            return
        updated = 0
        for idx, it in enumerate(items, 1):
            src = os.path.join(self.files_dir, it["file"])
            if not os.path.isfile(src):
                continue
            needs_meta = (it.get("width", 0) == 0) or (not it.get("phash") and it["kind"] == "image")
            needs_webp = not os.path.isfile(os.path.join(self.thumbs_dir, f"{it['id']}_md.webp"))
            needs_preview = it["kind"] == "video" and not it.get("preview_file")

            fields: Dict[str, Any] = {}
            if needs_meta:
                meta = media_proc.extract_metadata(src, it["ext"])
                fields.update({
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
                })
            # 清洗无意义 tmp* 标题
            cleaned = media_proc.clean_title(it["title"], it["name"], it.get("source", ""))
            if cleaned != it["title"]:
                fields["title"] = cleaned

            if needs_webp:
                tname = media_proc.make_thumbnails(src, self.thumbs_dir, it["id"], it["ext"])
                if tname:
                    fields["thumb"] = tname

            if needs_preview:
                prev = media_proc.make_video_preview(src, self.previews_dir, it["id"])
                if prev:
                    fields["preview_file"] = prev

            if fields:
                self.db.update_item(it["id"], fields)
                updated += 1

            if idx % 10 == 0 or idx == total:
                pct = int(idx * 100 / total)
                self._update(job_id, "running", pct, f"回填进度 {idx}/{total}（已更新 {updated}）")

        self._update(job_id, "done", 100, f"回填完成，共更新 {updated}/{total} 项", {"updated": updated, "total": total})
        self.broadcast("library_updated", {"reason": "backfill"})


TupleQueue = "queue.Queue[str]"
