#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 9 轮（R22）回归

覆盖分享页移动端细节：
  1. 提供 theme-color 并随明暗主题同步（首批渲染前 + 切换后）
  2. 手机顶栏吸顶，长页滚动时下载入口始终可达
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
        "title": "分享页主题色样例",
        "size": 128,
        "width": 1200,
        "height": 800,
        "ts": 1700000000,
    })
    return iid


def test_share_page_theme_color_syncs(client):
    iid = _seed_share_item(client)
    html = client.get(f"/s/{iid}").text

    assert '<meta name="theme-color" content="#faf8f5">' in html
    # 首屏前置脚本与主题切换都要更新地址栏颜色
    assert "tm.setAttribute('content'" in html
    assert "syncMeta" in html
    assert "#14120f" in html


def test_share_page_mobile_topbar_sticky(client):
    iid = _seed_share_item(client)
    html = client.get(f"/s/{iid}").text

    assert ".topbar{position:sticky;top:0;z-index:20" in html
