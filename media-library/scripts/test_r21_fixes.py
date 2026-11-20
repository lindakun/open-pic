#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 8 轮（R21）回归

覆盖：
  1. 分享页移动端适配：viewport-fit=cover、底部安全区与 44px 主按钮
  2. 分享页手机顶栏收敛为单行（隐藏次要“在库中打开”入口）
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


def _seed_share_item(client: TestClient, iid: str = "abcdef0100000000") -> str:
    client.app.state.db.upsert_item({
        "id": iid,
        "file": f"{iid}.jpg",
        "kind": "image",
        "ext": ".jpg",
        "name": f"{iid}.jpg",
        "title": "分享页移动端样例",
        "size": 128,
        "width": 1200,
        "height": 800,
        "ts": 1700000000,
    })
    return iid


def test_share_page_mobile_viewport_and_safe_area(client):
    iid = _seed_share_item(client)
    html = client.get(f"/s/{iid}").text

    assert 'viewport-fit=cover' in html
    assert "env(safe-area-inset-bottom,0px)" in html
    assert "env(safe-area-inset-top,0px)" in html
    assert "min-height:44px" in html


def test_share_page_mobile_topbar_keeps_primary_download(client):
    iid = _seed_share_item(client)
    html = client.get(f"/s/{iid}").text

    # 手机端隐藏次要的在库入口，保留下载主按钮
    assert ".topbar__actions .btn:not(.btn--primary){display:none}" in html
    assert 'class="btn btn--primary"' in html
