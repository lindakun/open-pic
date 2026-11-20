#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 3 轮（R16）的回归测试

覆盖：
  1. 批量导出不再静默截断到 200 项（超阈值转异步并返回完整数量）
  2. 批量导出对重复 id 去重后计数
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


def _seed_items(client: TestClient, count: int) -> list:
    """直接写库：异步导出只读数据库，不要求文件真实存在。"""
    db = client.app.state.db
    ids = []
    for i in range(count):
        iid = f"{i:016x}"
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


def test_download_zip_keeps_all_ids_over_200(client):
    ids = _seed_items(client, 205)
    r = client.post("/api/items/download-zip", json={"ids": ids})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["async"] is True
    assert body["count"] == 205


def test_download_zip_dedupes_ids(client):
    ids = _seed_items(client, 21)
    r = client.post("/api/items/download-zip", json={"ids": ids + ids[:5]})
    assert r.status_code == 202, r.text
    assert r.json()["count"] == 21
