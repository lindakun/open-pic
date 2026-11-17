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
        # provider 工厂：默认读环境变量，可由 app 注入以保持一致
        self.provider_factory = None

    def start(self, num_workers: int = 2):
        if self._workers:
            return
        self._stop_event.clear()
        for idx in range(num_workers):
            t = threading.Thread(target=self._worker_loop, name=f"mlib-worker-{idx}", daemon=True)
            t.start()
            self._workers.append(t)
        self._recover_pending_jobs()

    def _recover_pending_jobs(self):
        """重启后恢复未完成任务。

        队列本身在内存里，进程重启即丢；但任务行落在 ingest_jobs 表。
        启动时把 pending/running 复位后按创建顺序重新入队，
        否则重启前正在批量上传的资产会永远停留在"无缩略图"状态。
        """
        try:
            n = self.db.requeue_interrupted_jobs()
            ids = self.db.list_pending_job_ids()
            for jid in ids:
                self._q.put(jid)
            if ids:
                print(f"[tasks] 已恢复 {len(ids)} 个中断任务（复位 {n} 条）", file=sys.stderr)
                self.broadcast("job", {"id": 0, "status": "pending", "progress": 0,
                                       "message": f"恢复 {len(ids)} 个中断任务"})
        except Exception as e:
            print(f"[tasks] 恢复中断任务失败: {e}", file=sys.stderr)

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
        # 按 id 精确查询：list_jobs(limit=200) 按 id 倒序截断，
        # 批量上传积压超 200 条时老任务会被误判不存在而静默丢弃（实测踩到）
        job = self.db.get_job(job_id)
        if not job:
            return
        jtype = job["job_type"]
        payload = job["payload"]

        if jtype == "ingest_url":
            self._handle_ingest_url(job_id, payload)
        elif jtype == "video_postprocess":
            self._handle_video_postprocess(job_id, payload)
        elif jtype == "media_process":
            self._handle_media_process(job_id, payload)
        elif jtype == "backfill_metadata":
            self._handle_backfill(job_id)
        elif jtype == "export_zip":
            self._handle_export_zip(job_id, payload)
        elif jtype == "embedding_backfill":
            self._handle_embedding_backfill(job_id, payload)
        elif jtype == "ai_tagging":
            self._handle_ai_tagging(job_id, payload)
        else:
            self._update(job_id, "failed", 100, f"未知任务类型: {jtype}")

    def _handle_ai_tagging(self, job_id: int, payload: Dict[str, Any]):
        """入库后 AI 自动打标（REQ-V2-20 B-07）。

        默认关闭：外部多模态 API 有成本，且打标质量需人工抽检后才能作为默认行为。
        通过 MEDIA_LIB_AI_AUTOTAG=1 开启；provider 未配置时标记 skipped，
        不影响入库与浏览（B-07 验收 4 的同款口径）。
        """
        import ai_provider

        if os.environ.get("MEDIA_LIB_AI_AUTOTAG", "").strip().lower() not in ("1", "true", "yes", "on"):
            self._update(job_id, "skipped", 100, "AI 自动打标未开启（MEDIA_LIB_AI_AUTOTAG=1 启用）")
            return

        item_id = payload.get("item_id", "")
        item = self.db.get_item(item_id) if item_id else None
        if not item:
            self._update(job_id, "failed", 100, "资产不存在")
            return
        if item.get("kind") != "image":
            self._update(job_id, "skipped", 100, "仅对图片打标")
            return

        factory = getattr(self, "provider_factory", None) or ai_provider.get_provider
        prov = factory()
        if not prov.available():
            self._update(job_id, "skipped", 100, "AI provider 未配置，跳过打标")
            return

        src = os.path.join(self.files_dir, item["file"])
        if not os.path.isfile(src):
            self._update(job_id, "failed", 100, "源文件缺失")
            return

        self._update(job_id, "running", 20, "调用视觉模型打标")
        try:
            with open(src, "rb") as fh:
                data = fh.read()
            result = prov.tag_image(data, hint=item.get("title") or "")
        except Exception as e:
            self._update(job_id, "failed", 100, f"打标失败: {e}")
            return

        # 结构化字段（风格/景别/场景/时段/主色）与自由 tags 合并成标签
        structured = [
            result.get("style"), result.get("shot"), result.get("scene"),
            result.get("time"), result.get("color"),
        ]
        tags = [str(t).strip() for t in (result.get("tags") or []) if str(t).strip()]
        tags += [s for s in structured if isinstance(s, str) and s.strip()]

        # 过滤人工否决过的组合（B-07 验收 3）
        rejected = set(self.db.rejected_tags(item_id))
        tags = [t for t in dict.fromkeys(tags) if t not in rejected]

        written = self.db.set_tags_with_source(item_id, tags, source="ai")
        self._update(
            job_id, "done", 100, f"已生成 {written} 个 AI 标签",
            {"item_id": item_id, "tags": tags[:20], "description": result.get("description", "")},
        )
        self.broadcast("media_ready", {"item_id": item_id, "ai_tags": tags[:20]})

    def _handle_embedding_backfill(self, job_id: int, payload: Dict[str, Any]):
        """批量生成向量（REQ-V2-20 B-08 验收 5）。

        单条失败不影响整体：跳过并累计失败数。
        provider 未配置时任务标记 skipped 而非 failed（B-07 验收 4 的同款口径）。
        """
        import ai_provider

        ids = payload.get("ids") or []
        model_version = payload.get("model_version") or ""
        if not ids:
            self._update(job_id, "done", 100, "没有待回填的资产")
            return

        # 走与 HTTP 层相同的工厂，避免测试或扩展替换 provider 后
        # 任务线程仍读环境变量而导致不一致（实测踩到）
        factory = getattr(self, "provider_factory", None) or ai_provider.get_provider
        prov = factory()
        if not prov.available():
            self._update(job_id, "skipped", 100, "AI provider 未配置，跳过向量回填")
            return

        ok = 0
        failed = 0
        total = len(ids)
        for idx, iid in enumerate(ids, start=1):
            item = self.db.get_item(iid)
            if not item:
                failed += 1
                continue
            path = os.path.join(self.files_dir, item["file"])
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                vec = prov.embed_image(data)
                self.db.upsert_embedding(
                    iid, ai_provider.pack_vector(vec), model_version,
                    dim=len(vec), source_text=item.get("title") or "",
                )
                ok += 1
            except Exception:
                failed += 1
            if idx % 5 == 0 or idx == total:
                self._update(
                    job_id, "running", int(idx * 100 / total),
                    f"已处理 {idx}/{total}（成功 {ok}，失败 {failed}）",
                )

        self._update(
            job_id, "done", 100, f"向量回填完成：成功 {ok}，失败 {failed}",
            {"ok": ok, "failed": failed, "model_version": model_version},
        )
        self.broadcast("library_updated", {"reason": "embedding_backfill"})

    def _handle_export_zip(self, job_id: int, payload: Dict[str, Any]):
        """异步批量导出（REQ-V2-20 C-13）。

        产物落在数据目录 exports/ 下，任务结果里回传下载文件名；
        不在请求线程里做 IO，也不把整包读进内存。
        """
        import export_seo

        ids = payload.get("ids") or []
        if not ids:
            self._update(job_id, "failed", 100, "缺少导出项")
            return
        items = []
        for iid in ids:
            it = self.db.get_item(iid)
            if it and not it.get("deleted_at"):
                items.append(it)
        if not items:
            self._update(job_id, "failed", 100, "没有可导出的文件")
            return

        out_dir = os.path.join(self.data_dir, "exports")
        os.makedirs(out_dir, exist_ok=True)
        name = f"medialib-{job_id}.zip"
        out_path = os.path.join(out_dir, name)

        self._update(job_id, "running", 10, f"正在导出 {len(items)} 项")
        try:
            result = export_seo.build_zip_to_path(
                self.files_dir,
                items,
                out_path,
                preset=payload.get("preset", "original"),
                fmt=payload.get("format", "jpeg"),
                quality=int(payload.get("quality", 85)),
                base_url=payload.get("base_url", ""),
            )
        except Exception as e:
            self._update(job_id, "failed", 100, f"导出失败: {e}")
            return

        msg = f"已导出 {result['count']} 项"
        if result["failures"]:
            msg += f"，{len(result['failures'])} 项失败"
        self._update(
            job_id, "done", 100, msg,
            {"file": name, "count": result["count"], "bytes": result["bytes"],
             "failures": result["failures"][:10]},
        )
        self.broadcast("library_updated", {"reason": "export_zip"})

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

    def _handle_media_process(self, job_id: int, payload: Dict[str, Any]):
        """异步补齐媒体处理结果（REQ-V2-20 D-16）。

        上传接口只落盘 + 建记录后立即返回，元数据提取、缩略图生成、
        近重复检测这些重活在此完成。失败不影响资产可用性，
        仅标记 failed 并保留原图可访问。
        """
        import media_proc

        item_id = payload.get("item_id", "")
        if not item_id:
            self._update(job_id, "failed", 100, "缺少 item_id")
            return

        item = self.db.get_item(item_id)
        if not item:
            self._update(job_id, "failed", 100, "资产不存在")
            return

        data_dir = self.data_dir
        files_dir = os.path.join(data_dir, "files")
        thumbs_dir = os.path.join(data_dir, "thumbs")
        src = os.path.join(files_dir, item["file"])
        if not os.path.isfile(src):
            self._update(job_id, "failed", 100, "源文件缺失")
            return

        try:
            self._update(job_id, "running", 10, "提取元数据")
            meta = media_proc.extract_metadata(src, item["ext"])

            self._update(job_id, "running", 50, "生成缩略图")
            thumb_rel = media_proc.make_thumbnails(src, thumbs_dir, item_id, item["ext"])

            self._update(job_id, "running", 80, "检测近似重复")
            near_dup = None
            if item["ext"] in media_proc.IMAGE_EXT and meta.get("phash"):
                near_dup = self.db.find_near_duplicate(meta.get("phash", ""), exclude_id=item_id)

            self.db.update_media_fields(
                item_id,
                width=meta["width"],
                height=meta["height"],
                aspect_ratio=meta["aspect_ratio"],
                duration=meta["duration"],
                fps=meta["fps"],
                codec=meta["codec"],
                dominant_color=meta["dominant_color"],
                palette_json=json.dumps(meta["palette"], ensure_ascii=False),
                exif_json=json.dumps(meta["exif"], ensure_ascii=False),
                phash=meta["phash"],
                thumb=thumb_rel,
            )

            result = {"item_id": item_id}
            if near_dup:
                result["near_duplicate_id"] = near_dup["id"]
            self._update(job_id, "done", 100, "处理完成", result)
            self.broadcast("media_ready", {"item_id": item_id, **result})
        except Exception as e:
            self._update(job_id, "failed", 100, f"处理失败: {e}")

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
        # 草稿/归档也要回填：它们只是不可见，不是不需要缩略图与元数据
        _, items = self.db.query_items(limit=100000, offset=0, include_unpublished=True)
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
