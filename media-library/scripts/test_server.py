#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MediaLib 2.0 本地集成测试（FastAPI + SQLite + 媒体处理）"""

import io
import json
import os
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import server as S


def _make_png_bytes(w=400, h=300, color=(40, 120, 220)) -> bytes:
    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    data_dir = str(tmp_path / "mlib_data")
    os.makedirs(os.path.join(data_dir, "files"), exist_ok=True)
    # 预先写入一条旧版 index.json 测试无损迁移
    legacy_file = os.path.join(data_dir, "files", "abcdef1234567890.png")
    with open(legacy_file, "wb") as f:
        f.write(_make_png_bytes(200, 200, (200, 50, 50)))
    with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump([{
            "id": "abcdef1234567890",
            "file": "abcdef1234567890.png",
            "thumb": None,
            "kind": "image",
            "ext": ".png",
            "name": "legacy.png",
            "title": "历史迁移图",
            "tags": ["旧图", "测试"],
            "source": "https://x.com/user/status/12345",
            "size": os.path.getsize(legacy_file),
            "ts": 1700000000,
        }], f, ensure_ascii=False)

    app = S.create_app(data_dir=data_dir, port=18199, start_workers=False)
    with TestClient(app) as c:
        yield c


def test_migration_and_stats(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True

    st = client.get("/api/stats").json()
    assert st["total"] == 1
    assert st["tags"]["旧图"] == 1
    assert st["platforms"][0]["name"] == "X"


def test_upload_metadata_thumbs_and_search(client):
    png = _make_png_bytes(640, 360, (30, 150, 240))
    r = client.post(
        "/api/upload",
        data={"tags": "风景,壁纸", "source": "https://x.com/demo/status/987654321"},
        files={"file": ("tmpxyz9988.png", png, "image/png")},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["count"] == 1
    it = d["items"][0]
    assert it["width"] == 640 and it["height"] == 360
    assert it["title"].startswith("X @demo")  # 自动清洗 tmp* 标题
    assert it["phash"] != ""

    # 多规格 WebP 缩略图与 ETag 304 协商
    t_resp = client.get(f"/t/{it['id']}_md.webp")
    assert t_resp.status_code == 200
    assert "etag" in t_resp.headers
    t_304 = client.get(f"/t/{it['id']}_md.webp", headers={"If-None-Match": t_resp.headers["etag"]})
    assert t_304.status_code == 304

    # 全文检索 & 方向筛选
    sr = client.get("/api/items", params={"q": "demo", "tag": "风景", "orientation": "landscape"}).json()
    assert sr["total"] == 1 and sr["items"][0]["id"] == it["id"]


def test_edit_collections_zip_and_trash(client):
    png = _make_png_bytes(300, 500, (120, 200, 90))
    it = client.post(
        "/api/upload",
        data={"title": "竖版海报", "tags": "设计"},
        files={"file": ("poster.png", png, "image/png")},
    ).json()["items"][0]
    iid = it["id"]

    # 行内编辑
    up = client.patch(f"/api/item/{iid}", json={"title": "新标题", "tags": ["海报", "精选"], "notes": "商业可用"})
    assert up.status_code == 200 and up.json()["item"]["title"] == "新标题"

    # 画板创建与关联
    col = client.post("/api/collections", json={"name": "商业灵感集", "description": "demo"}).json()["collection"]
    client.post(f"/api/collections/{col['id']}/items", json={"item_ids": [iid]})
    col_items = client.get("/api/items", params={"collection_id": col["id"]}).json()
    assert col_items["total"] == 1

    # 批量 ZIP 下载
    zr = client.post("/api/items/download-zip", json={"ids": [iid]})
    assert zr.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(zr.content))
    assert "poster.png" in zf.namelist()

    # 独立分享页 OG Meta
    sh = client.get(f"/s/{iid}")
    assert sh.status_code == 200 and 'property="og:title" content="新标题"' in sh.text

    # 软删除 -> 回收站可见 -> 恢复 -> 彻底删除
    client.post("/api/delete", json={"id": iid})
    assert client.get("/api/items", params={"q": "新标题"}).json()["total"] == 0
    assert client.get("/api/items", params={"deleted": True}).json()["total"] == 1

    client.post("/api/restore", json={"ids": [iid]})
    assert client.get("/api/items", params={"q": "新标题"}).json()["total"] == 1

    client.post("/api/delete", json={"id": iid, "permanent": True})
    assert client.get("/api/items", params={"deleted": True}).json()["total"] == 0
