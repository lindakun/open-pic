#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 13 批修复（R13）的回归测试

覆盖：
  1. 空文件上传被拒绝（不产生无法处理的资产记录）
  2. 分享页图片展示走 /img/ 变换，下载仍指向原文件
  3. 已到期的定时草稿不再重复计入 stats.drafts
  4. 批量移除标签接口可用
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


def _upload_png(c: TestClient, name: str, tags: str = "") -> dict:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (70, 100, 190)).save(buf, "PNG")
    buf.seek(0)
    data = {"synchronous": "1", "title": name}
    if tags:
        data["tags"] = tags
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", buf, "image/png")},
        data=data,
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_empty_upload_rejected(client):
    r = client.post(
        "/api/upload",
        files={"file": ("empty.png", b"", "image/png")},
        data={"synchronous": "1"},
    )
    assert r.status_code == 400
    assert "空" in r.json()["detail"]
    assert client.get("/api/stats").json()["total"] == 0


def test_share_page_image_uses_transform(client):
    it = _upload_png(client, "share")
    html = client.get(f"/s/{it['id']}").text
    assert f"/img/{it['id']}?w=1920" in html
    # 下载入口仍指向原文件
    assert f"/f/{it['file']}?dl=1" in html


def test_scheduled_draft_not_double_counted(client):
    it = _upload_png(client, "due")
    client.patch(f"/api/item/{it['id']}/status", json={"status": "draft"})
    db = client.app.state.db
    with db.connect() as conn:
        conn.execute(
            "UPDATE items SET status='draft', publish_at=? WHERE id=?",
            (int(time.time()) - 5, it["id"]),
        )
        conn.commit()

    st = client.get("/api/stats").json()
    assert st["total"] == 1
    assert st["drafts"] == 0, "已到期的定时草稿被重复计入 drafts"


def test_batch_remove_tags(client):
    it = _upload_png(client, "tagged", tags="风景,城市")
    r = client.post(
        "/api/items/batch",
        json={"ids": [it["id"]], "action": "remove_tags", "tags": ["城市"]},
    )
    assert r.status_code == 200
    tags = client.get(f"/api/item/{it['id']}").json()["tags"]
    assert tags == ["风景"]
