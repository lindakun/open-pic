#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 15 批修复（R15）的回归测试

覆盖：
  1. Range 后缀区间 bytes=-N 正确返回文件尾部
  2. sitemap 收录新前端规范入口 /app/
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


def _upload_png(c: TestClient, name: str = "range") -> dict:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (70, 100, 190)).save(buf, "PNG")
    buf.seek(0)
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", buf, "image/png")},
        data={"synchronous": "1", "title": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_range_suffix_returns_tail(client):
    it = _upload_png(client)
    full = client.get(f"/f/{it['file']}")
    assert full.status_code == 200
    size = len(full.content)

    r = client.get(f"/f/{it['file']}", headers={"Range": "bytes=-10"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {size - 10}-{size - 1}/{size}"
    assert len(r.content) == 10
    assert r.content == full.content[-10:]


def test_range_suffix_zero_rejected(client):
    it = _upload_png(client)
    r = client.get(f"/f/{it['file']}", headers={"Range": "bytes=-0"})
    assert r.status_code == 416


def test_sitemap_includes_app_entry(client):
    _upload_png(client)
    xml = client.get("/sitemap.xml").text
    assert "/app/" in xml
    assert "/app/browse" in xml
