#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 7 轮（R20）回归

覆盖：
  1. 前台分面计数只统计公开可见资产（未到期草稿/归档不参与）
  2. 分享页浏览计数不包含未到期草稿
  3. 分享页视频规格包含可读时长
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


def _seed(client: TestClient, count: int) -> list:
    db = client.app.state.db
    ids = []
    for i in range(count):
        iid = f"{i + 1:08x}00000000"
        db.upsert_item({
            "id": iid,
            "file": f"{iid}.jpg",
            "kind": "image",
            "ext": ".jpg",
            "name": f"{iid}.jpg",
            "title": f"seed-{i}",
            "size": 128,
            "width": 40,
            "height": 30,
            "ts": 1700000000 + i,
        })
        ids.append(iid)
    return ids


def test_facets_only_public_visible(client):
    ids = _seed(client, 4)
    db = client.app.state.db
    now = int(time.time())
    assert db.set_status(ids[1], "draft", publish_at=now - 60)[0]
    assert db.set_status(ids[2], "draft", publish_at=now + 3600)[0]
    assert db.set_status(ids[3], "archived")[0]

    facets = client.get("/api/facets").json()
    image = next(k for k in facets["kind"] if k["value"] == "image")
    # published + 已到期的定时草稿
    assert image["count"] == 2


def test_share_views_skip_unpublished(client):
    ids = _seed(client, 3)
    db = client.app.state.db
    now = int(time.time())
    assert db.set_status(ids[1], "draft", publish_at=now + 3600)[0]
    assert db.set_status(ids[2], "archived")[0]

    client.get(f"/s/{ids[0]}")
    client.get(f"/s/{ids[1]}")
    client.get(f"/s/{ids[2]}")

    assert db.get_item(ids[0])["views"] == 1
    assert db.get_item(ids[1])["views"] == 0
    assert db.get_item(ids[2])["views"] == 0


def test_share_meta_shows_readable_duration(client):
    iid = "abcdef0100000000"
    client.app.state.db.upsert_item({
        "id": iid,
        "file": f"{iid}.mp4",
        "kind": "video",
        "ext": ".mp4",
        "name": f"{iid}.mp4",
        "title": "演示视频",
        "size": 128,
        "width": 1920,
        "height": 1080,
        "duration": 125,
        "ts": 1700000000,
    })

    html = client.get(f"/s/{iid}").text
    assert "2:05" in html
