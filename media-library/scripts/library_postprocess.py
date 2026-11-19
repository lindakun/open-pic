#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图库存量后处理模块（定时独立运行）：
  1. Phase 1（零 API 费用）：为缺失 phash 的视频/图片计算 dHash 回填，
     并在全库范围内做精确近似去重（合并标签后将低画质/晚入库副本软删除进回收站）。
  2. Phase 2（分批视觉识别）：对不含「AI已标注」标签的存量图片/视频调用视觉模型，
     补齐中文标题与细分标签，并将不符合女性人像条件的存量素材软删除进回收站。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db as db_mod
import media_proc
import pipeline_config
import vision_filter

DATA = os.environ.get("MEDIA_LIB_DIR", "/vol1/picoclaw/.picoclaw/workspace/media-library")
LOG_PATH = os.path.join(DATA, "postprocess.log")

log_fp = None


def log(msg, echo=True):
    line = msg if msg.startswith("[") else f"[{time.strftime('%H:%M:%S')}] {msg}"
    if echo:
        print(line, file=sys.stderr, flush=True)
    if log_fp:
        try:
            log_fp.write(line + "\n")
            log_fp.flush()
        except Exception:
            pass


def rotate_log():
    """日志超过 5MB 时截断，保留尾部 2000 行"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 5 * 1024 * 1024:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-2000:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except Exception:
        pass


def compute_image_dhash(path):
    """计算本地图片 64-bit dHash"""
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            return media_proc._compute_dhash_pil(im)
    except Exception:
        return ""


def compute_video_dhash(path, duration=0.0):
    """抽取视频中间帧（失败降级首帧）计算 64-bit dHash"""
    with tempfile.TemporaryDirectory(prefix="xpp-dhash-") as tmpdir:
        out = os.path.join(tmpdir, "frame.jpg")
        cmds = []
        if duration and duration > 1.0:
            cmds.append([
                "ffmpeg", "-y", "-ss", f"{duration * 0.5:.2f}",
                "-i", path, "-frames:v", "1", "-q:v", "3", out,
            ])
        cmds.append([
            "ffmpeg", "-y", "-i", path, "-frames:v", "1", "-q:v", "3", out,
        ])
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                    return compute_image_dhash(out)
            except Exception:
                continue
    return ""


def backfill_missing_phashes(database, data_dir, limit=50, dry_run=False):
    """Phase 1a: 为缺失 phash 的活跃图片和视频计算并回填 dHash"""
    sql = (
        "SELECT id, file, kind, duration FROM items "
        "WHERE deleted_at IS NULL AND (phash IS NULL OR phash='') "
        "ORDER BY ts DESC"
    )
    params = ()
    if limit and limit > 0:
        sql += " LIMIT ?"
        params = (limit,)
    with database.connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return 0

    if dry_run:
        log(f"[dry] 待回填 phash 素材 {len(rows)} 条")
        return len(rows)

    filled = 0
    for r in rows:
        fpath = os.path.join(data_dir, "files", r["file"])
        if not os.path.exists(fpath):
            log(f"  ! 缺失文件跳过 phash 回填: {r['id']} ({r['file']})")
            continue
        if r["kind"] == "video":
            dh = compute_video_dhash(fpath, float(r["duration"] or 0.0))
        else:
            dh = compute_image_dhash(fpath)
        if dh:
            database.update_item(r["id"], {"phash": dh})
            filled += 1
    log(f"Phase 1a 完成：回填 phash {filled}/{len(rows)} 条")
    return filled


def _hamming_int(a_int, b_int):
    return (a_int ^ b_int).bit_count()


def _merge_tags(*tag_lists):
    out, seen = [], set()
    for lst in tag_lists:
        for t in lst or []:
            s = str(t or "").strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
    return out


def deduplicate_items(database, max_dist=4, dry_run=False):
    """Phase 1b: 按 kind 分组进行全库精确 dHash 近似去重"""
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT id, kind, width, height, size, duration, phash, ts "
            "FROM items WHERE deleted_at IS NULL AND phash IS NOT NULL AND phash != ''"
        ).fetchall()

    by_kind = {"image": [], "video": []}
    for r in rows:
        try:
            ph_int = int(r["phash"], 16)
        except ValueError:
            continue
        by_kind.setdefault(r["kind"], []).append({
            "id": r["id"],
            "kind": r["kind"],
            "px": int(r["width"] or 0) * int(r["height"] or 0),
            "size": int(r["size"] or 0),
            "duration": float(r["duration"] or 0.0),
            "ts": int(r["ts"] or 0),
            "ph_int": ph_int,
        })

    total_removed = 0
    for kind, items in by_kind.items():
        n = len(items)
        if n < 2:
            continue
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(n):
            a = items[i]
            for j in range(i + 1, n):
                b = items[j]
                if kind == "video" and abs(a["duration"] - b["duration"]) > 1.5:
                    continue
                if _hamming_int(a["ph_int"], b["ph_int"]) <= max_dist:
                    union(i, j)

        groups = {}
        for idx in range(n):
            groups.setdefault(find(idx), []).append(items[idx])

        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda it: (-it["px"], -it["size"], it["ts"], it["id"]))
            keep = group[0]
            dups = group[1:]
            total_removed += len(dups)
            dup_ids = [d["id"] for d in dups]

            if dry_run:
                log(f"[dry] 近似重复组({kind}): 保留 {keep['id']} ({keep['px']}px), 软删除 {dup_ids}")
                continue

            keep_item = database.get_item(keep["id"])
            tag_lists = [keep_item["tags"] if keep_item else []]
            for d_id in dup_ids:
                d_item = database.get_item(d_id)
                if d_item:
                    tag_lists.append(d_item["tags"])
            merged = _merge_tags(*tag_lists)
            database.update_item(keep["id"], {"tags": merged})
            database.soft_delete(dup_ids)
            log(f"  ✓ 近似去重({kind}): 保留 {keep['id']}，软删除 {dup_ids}")

    return total_removed


def backfill_vision_metadata(database, data_dir, vision_cfg, batch=15, dry_run=False, ai_tag=None):
    """Phase 2: 对尚未带有 AI已标注 标签的活跃素材分批进行视觉识别与元数据补齐"""
    if not ai_tag:
        ai_tag = (
            os.environ.get("X_POSTPROCESS_TAG", "").strip()
            or str(pipeline_config.load_pipeline_config(data_dir).get("postprocess", {}).get("ai_tag") or "AI已标注").strip()
            or "AI已标注"
        )
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM items "
            "WHERE deleted_at IS NULL "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM item_tags it JOIN tags t ON t.id = it.tag_id "
            "  WHERE it.item_id = items.id AND t.name = ?"
            ") "
            "ORDER BY ts DESC LIMIT ?",
            (ai_tag, batch),
        ).fetchall()

    stats = {"processed": 0, "updated": 0, "rejected": 0, "failed": 0}
    if not rows:
        return stats

    for r in rows:
        item = database.get_item(r["id"])
        if not item:
            continue
        stats["processed"] += 1
        fpath = os.path.join(data_dir, "files", item["file"])

        if dry_run:
            log(f"[dry] 待视觉标注: {item['id']} ({item['kind']}) title={item['title']!r}")
            continue

        if not os.path.exists(fpath):
            log(f"  ! 文件不存在，跳过标注: {item['id']} ({item['file']})")
            stats["failed"] += 1
            continue

        vkind = "video" if item["kind"] == "video" else "photo"
        try:
            vres = vision_filter.analyze_media(fpath, vkind, vision_cfg)
        except Exception as e:
            log(f"  ✗ 视觉识别失败 {item['id']}：{e}")
            stats["failed"] += 1
            continue

        if not vres["keep"]:
            merged = _merge_tags(item["tags"], [ai_tag])
            database.update_item(item["id"], {"tags": merged})
            database.soft_delete([item["id"]])
            log(f"  - 存量淘汰进回收站 {item['id']}：{vres.get('reason') or '不符合条件'}")
            stats["rejected"] += 1
            continue

        new_title = vres.get("title") or item["title"]
        merged = _merge_tags(item["tags"], vres.get("tags") or [], [ai_tag])
        database.update_item(item["id"], {"title": new_title, "tags": merged})
        log(f"  ✓ 补齐 {item['id']}: {new_title} | +{vres.get('tags') or []}")
        stats["updated"] += 1

    return stats


def main():
    global log_fp
    p = argparse.ArgumentParser(description="图库存量后处理：视频指纹回填、全库去重、视觉标题/标签补齐")
    p.add_argument("--batch", type=int, default=None, help="每轮视觉识别处理上限（0=跳过视觉阶段，默认读取配置或 50）")
    p.add_argument("--phash-limit", type=int, default=None, help="每轮视频/图片 phash 回填上限（0=全部，默认读取配置或 50）")
    p.add_argument("--max-dist", type=int, default=None, help="近似去重 dHash 最大汉明距离（默认读取配置或 4）")
    p.add_argument("--skip-dedup", action="store_true", help="跳过 Phase 1 指纹回填与去重")
    p.add_argument("--skip-vision", action="store_true", help="跳过 Phase 2 视觉识别补齐")
    p.add_argument("--dry-run", action="store_true", help="试运行，不修改数据库也不调用视觉 API")
    p.add_argument("--quiet", action="store_true", help="不往 stderr 打日志")
    args = p.parse_args()

    # 四级优先级：CLI > 环境变量 > pipeline_config.json > 默认值
    pcfg = pipeline_config.load_pipeline_config(DATA)
    ppcfg = pcfg.get("postprocess", {})

    if args.batch is None:
        env_b = os.environ.get("X_POSTPROCESS_BATCH", "").strip()
        args.batch = int(env_b) if env_b else int(ppcfg.get("batch", 50))
    if args.phash_limit is None:
        env_p = os.environ.get("X_POSTPROCESS_PHASH_LIMIT", "").strip()
        args.phash_limit = int(env_p) if env_p else int(ppcfg.get("phash_limit", 50))
    if args.max_dist is None:
        env_d = os.environ.get("X_POSTPROCESS_MAX_DIST", "").strip()
        args.max_dist = int(env_d) if env_d else int(ppcfg.get("max_dist", 4))

    args.skip_dedup = bool(args.skip_dedup or ppcfg.get("skip_dedup", False))
    args.skip_vision = bool(args.skip_vision or ppcfg.get("skip_vision", False))
    ai_tag = (
        os.environ.get("X_POSTPROCESS_TAG", "").strip()
        or str(ppcfg.get("ai_tag") or "AI已标注").strip()
        or "AI已标注"
    )

    if args.batch < 0 or args.phash_limit < 0 or args.max_dist < 0:
        p.error("batch、phash-limit 和 max-dist 不能为负")

    db_path = os.path.join(DATA, "media.db")
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}", file=sys.stderr)
        return 2

    vision_cfg = None
    if not args.dry_run and not args.skip_vision and args.batch > 0:
        try:
            vision_cfg = vision_filter.load_config(DATA)
        except Exception as e:
            print(f"视觉配置加载失败: {e}", file=sys.stderr)
            return 5
        if vision_cfg.get("enabled") and not vision_cfg.get("api_key"):
            print("已启用视觉识别但未配置 API Key（X_VISION_API_KEY 或 vision_config.json）", file=sys.stderr)
            return 5

    log_fp = None
    if not args.dry_run:
        rotate_log()
        log_fp = open(LOG_PATH, "a", encoding="utf-8")

    log(f"=== 开始存量后处理 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", echo=not args.quiet)
    database = db_mod.MediaDB(db_path)

    summary = {"phash_filled": 0, "dedup_removed": 0, "processed": 0, "updated": 0, "rejected": 0, "failed": 0}
    try:
        if not args.skip_dedup:
            summary["phash_filled"] = backfill_missing_phashes(
                database, DATA, limit=args.phash_limit, dry_run=args.dry_run
            )
            summary["dedup_removed"] = deduplicate_items(database, max_dist=args.max_dist, dry_run=args.dry_run)

        if not args.skip_vision and args.batch > 0:
            if args.dry_run or (vision_cfg and vision_cfg.get("enabled")):
                vstats = backfill_vision_metadata(
                    database, DATA, vision_cfg, batch=args.batch, dry_run=args.dry_run, ai_tag=ai_tag
                )
                summary.update(vstats)

        log(f"完成：{json.dumps(summary, ensure_ascii=False)}", echo=not args.quiet)
        log(f"=== 结束 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", echo=not args.quiet)
    finally:
        if log_fp:
            log_fp.close()
            log_fp = None

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
