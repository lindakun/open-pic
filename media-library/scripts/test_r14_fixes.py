#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 14 批修复（R14）的回归测试

覆盖：
  1. 批量加入不存在的画板返回 404（不再静默 ok+0）
  2. 多文件上传中单个不支持类型不拖垮整批
  3. /img/ 的 fit 参数白名单校验
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


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (70, 100, 190)).save(buf, "PNG")
    return buf.getvalue()


def _upload_png(c: TestClient, name: str = "a") -> dict:
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", _png_bytes(), "image/png")},
        data={"synchronous": "1", "title": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_batch_add_to_missing_collection_404(client):
    it = _upload_png(client)
    r = client.post(
        "/api/items/batch",
        json={"ids": [it["id"]], "action": "add_collection", "collection_id": 9999},
    )
    assert r.status_code == 404
    assert "画板" in r.json()["detail"]


def test_multi_upload_skips_unsupported_type(client):
    files = [
        ("files", ("good.png", _png_bytes(), "image/png")),
        ("files", ("notes.txt", b"hello", "text/plain")),
    ]
    r = client.post("/api/upload", files=files, data={"synchronous": "1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["name"].endswith(".png")
    assert len(body["errors"]) == 1
    assert "notes.txt" in body["errors"][0]


def test_img_fit_is_whitelisted(client):
    it = _upload_png(client)
    r = client.get(f"/img/{it['id']}", params={"w": 100, "fit": "evil"})
    assert r.status_code == 200
    assert r.headers["content-type"] in ("image/webp", "image/jpeg", "image/png")
