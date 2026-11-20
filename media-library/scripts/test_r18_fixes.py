#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 5 轮（R18）的回归测试

覆盖：
  1. sitemap 收录已到期的定时发布草稿，排除未到期草稿
  2. 文件缺失时下载计数不虚增
  3. 标签治理计数不包含回收站资产
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


def _seed_items(client: TestClient, count: int) -> list:
    db = client.app.state.db
    ids = []
    for i in range(count):
        iid = f"{i + 1:08x}00000000"
        db.upsert_item({
            "id": iid,
            "file": f"{iid}.png",
            "kind": "image",
            "ext": ".png",
            "name": f"{iid}.png",
            "title": f"seed-{i}",
            "size": 128,
            "width": 40,
            "height": 30,
            "ts": 1700000000 + i,
        })
        ids.append(iid)
    return ids


def test_sitemap_includes_due_scheduled_draft(client):
    ids = _seed_items(client, 3)
    db = client.app.state.db
    now = int(time.time())
    assert db.set_status(ids[1], "draft", publish_at=now - 60)[0]
    assert db.set_status(ids[2], "draft", publish_at=now + 3600)[0]

    xml = client.get("/sitemap.xml").text
    assert f"asset-{ids[0][:8]}" in xml
    assert f"asset-{ids[1][:8]}" in xml
    assert f"asset-{ids[2][:8]}" not in xml


def test_download_counter_skips_missing_file(client):
    iid = _seed_items(client, 1)[0]
    db = client.app.state.db

    res = client.get(f"/f/{iid}.png", params={"dl": "1"})
    assert res.status_code == 404
    assert db.get_item(iid)["downloads"] == 0


def test_tag_admin_count_excludes_trashed(client):
    iid = _seed_items(client, 1)[0]
    db = client.app.state.db
    db.set_tags_with_source(iid, ["风景"], source="manual")
    assert client.get("/api/tags").json()["tags"][0]["count"] == 1

    db.soft_delete([iid])
    tags = client.get("/api/tags").json()["tags"]
    tag = next(t for t in tags if t["name"] == "风景")
    assert tag["count"] == 0
