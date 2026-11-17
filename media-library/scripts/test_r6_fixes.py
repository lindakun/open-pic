#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 6 批修复（R6）的回归测试

覆盖：
  1. 分面统计应用筛选上下文（B-10）：选类型后，其余维度的计数随之收窄
  2. 回收站视图不做发布状态过滤：draft/archived 软删除资产仍可见
  3. /f/ 直链：软删除资产浏览放行（回收站预览），下载 dl=1 拦截
  4. /api/collections 返回 {collections:[...]} 契约（前端解构依赖）
  5. 存储概览包含 imgcache 统计（A-05 缓存可见性）
"""

import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as srv


@pytest.fixture()
def client(tmp_path):
    app = srv.create_app(data_dir=str(tmp_path), start_workers=False)
    with TestClient(app) as c:
        yield c


def _upload_png(c: TestClient, name: str, extra: dict = None, color=(200, 60, 60)) -> dict:
    """上传一张 Pillow 生成的 PNG 并返回资产记录（颜色可变以绕开内容去重）。"""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    buf.seek(0)
    data = {"title": name}
    data.update(extra or {})
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", buf, "image/png")},
        data={"synchronous": "1", **data},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_facets_respect_filter_context(client):
    """分面计数应随筛选上下文收窄，而不是永远全库统计。"""
    _upload_png(client, "img-a")
    _upload_png(client, "img-b", color=(60, 60, 200))
    # 上传一个视频（最小 mp4，仅用于 kind 区分；同步路径可能提取失败，无妨）
    import io
    mp4 = io.BytesIO(b"\x00" * 64)
    r = client.post(
        "/api/upload",
        files={"file": ("v.mp4", mp4, "video/mp4")},
        data={"synchronous": "1", "title": "v"},
    )
    assert r.status_code == 200

    # 不筛选：kind 分面里 image=2
    base = client.get("/api/facets").json()
    kinds = {x["value"]: x["count"] for x in base["kind"]}
    assert kinds.get("image") == 2

    # 选 kind=video：ext 分面只统计视频（.png 应消失），
    # kind 自身维度不受自身筛选影响（仍是全集）
    filt = client.get("/api/facets", params={"kind": "video"}).json()
    exts = {x["value"]: x["count"] for x in filt["ext"]}
    assert ".png" not in exts, "选视频后 ext 分面不应再出现 .png 的全集计数"
    kinds2 = {x["value"]: x["count"] for x in filt["kind"]}
    assert kinds2.get("image", 0) >= 1, "kind 自身维度应排除自身筛选"


def test_trash_shows_unpublished_deleted_items(client):
    """回收站视图必须能看到 draft/archived 的软删除资产（幽灵资产回归）。"""
    it = _upload_png(client, "ghost")
    iid = it["id"]
    # 置为 draft 再软删除
    r = client.patch(f"/api/item/{iid}/status", json={"status": "draft"})
    assert r.status_code == 200, r.text
    r = client.post("/api/delete", json={"ids": [iid]})
    assert r.status_code == 200

    # 回收站查询：deleted=True 时不应被 status 过滤掉
    res = client.get("/api/items", params={"deleted": "true"}).json()
    ids = [x["id"] for x in res["items"]]
    assert iid in ids, "draft 软删除资产在回收站不可见（幽灵资产）"

    # 恢复应成功
    r = client.post("/api/restore", json={"ids": [iid]})
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_file_download_blocked_for_deleted(client):
    """/f/ 浏览放行软删除资产，下载 dl=1 拦截。"""
    it = _upload_png(client, "del-dl")
    iid, fname = it["id"], it["file"]
    r = client.post("/api/delete", json={"ids": [iid]})
    assert r.status_code == 200

    # 普通浏览（回收站预览）：可用
    r = client.get(f"/f/{fname}")
    assert r.status_code == 200
    # 下载：拦截
    r = client.get(f"/f/{fname}", params={"dl": "1"})
    assert r.status_code == 404


def test_collections_response_shape(client):
    """批量条「加入画板」依赖 {collections:[...]} 包装结构。"""
    r = client.post("/api/collections", json={"name": "c1"})
    assert r.status_code == 200
    r = client.get("/api/collections")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("collections"), list)
    assert body["collections"][0]["name"] == "c1"


def test_storage_summary_includes_imgcache(client):
    """存储概览应包含 imgcache 统计（A-05）。"""
    r = client.get("/api/storage/summary")
    assert r.status_code == 200
    body = r.json()
    assert "imgcache" in body
    assert "limit_bytes" in body["imgcache"]
