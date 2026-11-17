#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 9 批修复（R9）的回归测试

覆盖：
  1. /a/{slug}-{shortId} canonical 地址直接渲染（不再重定向死循环）
  2. /a/ 带 slug 的非 canonical 地址 301 到 canonical
  3. /s/ 旧分享链接直接渲染（canonical 指向 /a/）
  4. /api/item/{id} 已删除资产返回 404（不计数不返回详情）
  5. /api/resolve/{short} 短 ID 解析
  6. 分享页 bot UA 不计浏览量
"""

import io
import os
import sys

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


def _upload_png(c: TestClient, name: str, color=(90, 130, 60)) -> dict:
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


def _canonical(c: TestClient, iid: str) -> str:
    it = c.get(f"/api/item/{iid}").json()
    slug = it.get("slug") or ""
    if not slug:
        # 触发 /a/ 路由生成 slug
        r = c.get(f"/a/asset-{iid[:8]}", follow_redirects=False)
        assert r.status_code == 301
        it = c.get(f"/api/item/{iid}").json()
        slug = it["slug"]
    import export_seo
    return export_seo.asset_path(slug, iid)


def test_asset_page_canonical_no_loop(client):
    """canonical 地址直接 200 渲染，不能重定向到自身（死循环回归）。"""
    it = _upload_png(client, "loop-test")
    canon = _canonical(client, it["id"])

    r = client.get(canon, follow_redirects=False)
    assert r.status_code == 200, f"canonical 地址不应重定向（当前 {r.status_code}）"
    assert "loop-test" in r.text

    # 非 canonical（旧 slug / 纯短 ID）→ 301 到 canonical
    r = client.get(f"/a/whatever-{it['id'][:8]}", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"].endswith(canon)


def test_s_page_renders_with_canonical(client):
    """/s/ 旧链接 200 渲染，canonical 指向 /a/。"""
    it = _upload_png(client, "s-page")
    canon = _canonical(client, it["id"])
    r = client.get(f"/s/{it['id']}")
    assert r.status_code == 200
    assert f'<link rel="canonical" href="http://testserver{canon}">' in r.text


def test_deleted_item_api_404(client):
    """已删除资产 API 详情返回 404，浏览计数不增加。"""
    it = _upload_png(client, "del-view")
    iid = it["id"]
    before = client.get(f"/api/item/{iid}").json()["views"]
    client.post("/api/delete", json={"ids": [iid]})

    r = client.get(f"/api/item/{iid}")
    assert r.status_code == 404
    r = client.get(f"/api/item/{iid}", params={"view": "true"})
    assert r.status_code == 404
    # 恢复后计数未变
    client.post("/api/restore", json={"ids": [iid]})
    after = client.get(f"/api/item/{iid}").json()["views"]
    assert after == before


def test_resolve_short_id(client):
    """短 ID 解析端点：命中返回资产，未命中 404。"""
    it = _upload_png(client, "resolve-me")
    short = it["id"][:8]
    r = client.get(f"/api/resolve/{short}")
    assert r.status_code == 200
    assert r.json()["id"] == it["id"]
    assert client.get("/api/resolve/00000000").status_code == 404


def test_share_page_bot_no_view_count(client):
    """bot UA 抓分享页不刷浏览量。"""
    it = _upload_png(client, "bot-view")
    iid = it["id"]
    before = client.get(f"/api/item/{iid}").json()["views"]
    client.get(f"/s/{iid}", headers={"User-Agent": "Googlebot/2.1"})
    after = client.get(f"/api/item/{iid}").json()["views"]
    assert after == before
