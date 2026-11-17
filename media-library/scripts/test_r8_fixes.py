#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 8 批修复（R8）的回归测试

覆盖：
  1. 重启后 pending/running 任务复位并可重新入队（内存队列不落盘的补偿）
  2. 分面统计的标签上下文：选标签后其余维度计数随标签收窄
  3. exports 导出产物过期清理
  4. /api/jobs limit 上限校验
"""

import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as srv


@pytest.fixture()
def client(tmp_path):
    app = srv.create_app(data_dir=str(tmp_path), start_workers=False)
    with TestClient(app) as c:
        yield c


def _upload_png(c: TestClient, name: str, color=(180, 40, 90)) -> dict:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    buf.seek(0)
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", buf, "image/png")},
        data={"synchronous": "1", "title": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_interrupted_jobs_are_reset_and_requeued(client):
    """重启恢复：pending/running 复位为 pending，list_pending_job_ids 可取回。"""
    db = client.app.state.db
    j1 = db.create_job("media_process", {"item_id": "a"})
    j2 = db.create_job("ai_tagging", {"item_id": "b"})
    # 模拟重启时正在跑的任务
    db.update_job(j2, status="running", progress=50)

    n = db.requeue_interrupted_jobs()
    assert n == 2
    pending = db.list_pending_job_ids()
    assert j1 in pending and j2 in pending
    # 状态已复位，worker 取到后可正常执行
    assert db.get_job(j2)["status"] == "pending"


def test_facets_respect_tag_context(client):
    """选标签后，其余分面维度计数应随标签收窄。"""
    a = _upload_png(client, "tag-a", color=(180, 40, 90))
    _upload_png(client, "tag-b", color=(40, 90, 180))
    # 只给 A 打标签
    r = client.post("/api/items/batch", json={"ids": [a["id"]], "action": "add_tags", "tags": ["精华"]})
    assert r.status_code == 200

    # 不带标签上下文：platform 分面含两条
    base = client.get("/api/facets").json()
    total_all = base["total"]
    assert total_all == 2

    # 带标签上下文：total 与 kind 计数都只反映打了标签的资产
    filt = client.get("/api/facets", params={"tag": "精华"}).json()
    assert filt["total"] == 1
    kinds = {x["value"]: x["count"] for x in filt["kind"]}
    assert kinds.get("image") == 1


def test_exports_cleanup_removes_expired(client, tmp_path):
    """下载导出产物时清理 7 天前的旧 ZIP。"""
    exports_dir = os.path.join(str(tmp_path), "exports")
    os.makedirs(exports_dir, exist_ok=True)
    old = os.path.join(exports_dir, "medialib-999.zip")
    with open(old, "wb") as f:
        f.write(b"old")
    # 把 mtime 拨到 8 天前
    eight_days_ago = time.time() - 8 * 86400
    os.utime(old, (eight_days_ago, eight_days_ago))

    # 下载一个不存在的产物触发清理钩子（404 无妨）
    client.get("/api/exports/medialib-1000.zip")
    assert not os.path.isfile(old), "过期导出产物应被清理"


def test_jobs_limit_capped(client):
    """/api/jobs limit 上限 500，超限返回 422。"""
    assert client.get("/api/jobs", params={"limit": 10}).status_code == 200
    r = client.get("/api/jobs", params={"limit": 99999})
    assert r.status_code == 422
