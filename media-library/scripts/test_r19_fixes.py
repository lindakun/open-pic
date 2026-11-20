#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 6 轮（R19）回归

覆盖：
  1. 分享页只在兼容播放副本真实存在时才指向 ?play=1
  2. 图片分享页缩略图缺失时 OG 图回退到按需变换
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as srv


@pytest.fixture()
def client(tmp_path):
    app = srv.create_app(data_dir=str(tmp_path), start_workers=False)
    with TestClient(app) as c:
        yield c


def _seed(client: TestClient, **overrides) -> str:
    iid = "abcd1234deadbeef"
    data = {
        "id": iid,
        "file": f"{iid}.mkv",
        "kind": "video",
        "ext": ".mkv",
        "name": f"{iid}.mkv",
        "title": "分享测试",
        "size": 128,
        "width": 1920,
        "height": 1080,
        "ts": 1700000000,
    }
    data.update(overrides)
    client.app.state.db.upsert_item(data)
    return iid


def test_share_page_play_copy_requires_existing_file(client):
    iid = _seed(client, play_file="abcd1234deadbeef.mp4")

    html = client.get(f"/s/{iid}").text
    assert f"/f/{iid}.mkv" in html
    assert "?play=1" not in html

    os.makedirs(srv.PLAY_DIR, exist_ok=True)
    with open(os.path.join(srv.PLAY_DIR, f"{iid}.mp4"), "wb") as f:
        f.write(b"fake")

    html = client.get(f"/s/{iid}").text
    assert "?play=1" in html


def test_share_page_og_image_falls_back_for_missing_thumb(client):
    iid = _seed(client, file="abcd1234deadbeef.jpg", kind="image", ext=".jpg",
                name="abcd1234deadbeef.jpg", play_file=None)

    html = client.get(f"/s/{iid}").text
    assert f"/img/{iid}?w=1200" in html
