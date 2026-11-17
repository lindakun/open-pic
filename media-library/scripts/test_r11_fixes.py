#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 11 批修复（R11）的回归测试

覆盖：
  1. 分面计数纳入关键词上下文（搜索后其余分面不再显示全库计数）
  2. 分辨率分桶筛选与分面打通（size_class）
  3. /api/stats 只统计可见资产（草稿不计入 total），并单独暴露 drafts
"""

import io
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as srv


@pytest.fixture()
def client(tmp_path):
    app = srv.create_app(data_dir=str(tmp_path), start_workers=False)
    with TestClient(app) as c:
        yield c


def _upload_png(
    c: TestClient,
    name: str,
    size=(40, 30),
    color=(70, 100, 190),
    tags: str = "",
    title: str = "",
) -> dict:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    data = {"synchronous": "1", "title": title or name}
    if tags:
        data["tags"] = tags
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", buf, "image/png")},
        data=data,
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_facets_respect_keyword_context(client):
    _upload_png(client, "sunset", color=(220, 90, 40), tags="风光", title="海边日落")
    _upload_png(client, "city", color=(40, 70, 150), tags="城市", title="城市夜景")

    base = client.get("/api/facets").json()
    assert base["total"] == 2

    filtered = client.get("/api/facets", params={"q": "日落"}).json()
    assert filtered["total"] == 1, "分面 total 未纳入关键词上下文"
    kind_counts = {o["value"]: o["count"] for o in filtered["kind"]}
    assert kind_counts.get("image") == 1, "分面 kind 计数仍是全库"
    tags = {o["value"] for o in filtered["tag"]}
    assert "风光" in tags and "城市" not in tags


def test_size_class_filter_and_facet(client):
    _upload_png(client, "small", size=(40, 30))
    _upload_png(client, "hd", size=(2000, 1000))

    hd = client.get("/api/items", params={"size_class": "hd"}).json()
    assert hd["total"] == 1
    assert hd["items"][0]["width"] == 2000

    small = client.get("/api/items", params={"size_class": "small"}).json()
    assert small["total"] == 1
    assert small["items"][0]["width"] == 40

    facets = client.get("/api/facets").json()
    buckets = {o["value"]: o["count"] for o in facets["size_class"]}
    assert buckets.get("hd") == 1
    assert buckets.get("small") == 1


def test_stats_excludes_drafts(client):
    it = _upload_png(client, "draft", title="草稿图")
    assert client.get("/api/stats").json()["total"] == 1

    # published -> draft 是允许的流转
    r = client.patch(f"/api/item/{it['id']}/status", json={"status": "draft"})
    assert r.status_code == 200, r.text

    st = client.get("/api/stats").json()
    assert st["total"] == 0, "草稿不应计入站点可见总数"
    assert st["images"] == 0
    assert st["drafts"] == 1
    assert "草稿图" not in st["tags"], "草稿资产的标签不应出现在标签云"
    # 列表口径与统计一致
    assert client.get("/api/items").json()["total"] == 0


def test_scheduled_draft_visible_in_stats(client):
    it = _upload_png(client, "scheduled", title="定时发布")
    due = int(time.time()) - 5
    client.patch(f"/api/item/{it['id']}/status", json={"status": "draft"})
    # 允许 draft -> published，但这里直接写 publish_at 模拟到期的定时草稿
    db = client.app.state.db
    with db.connect() as conn:
        conn.execute(
            "UPDATE items SET status='draft', publish_at=? WHERE id=?", (due, it["id"])
        )
        conn.commit()

    st = client.get("/api/stats").json()
    assert st["total"] == 1, "已到期的定时草稿应视为可见"
    assert client.get("/api/items").json()["total"] == 1
