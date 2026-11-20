#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环第 4 轮（R17）的回归测试

覆盖：
  1. 随机排序使用 seed 后分页稳定（不重复、不漏项）
  2. 画板计数只统计当前可见（未删除且已发布/到期）的资产
  3. 热门浏览 Top10 不再包含 0 浏览量的资产
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


def test_random_sort_is_stable_across_pages(client):
    _seed_items(client, 30)
    page1 = client.get("/api/items", params={"sort": "random", "seed": 123, "limit": 10, "offset": 0}).json()
    page1_again = client.get("/api/items", params={"sort": "random", "seed": 123, "limit": 10, "offset": 0}).json()
    page2 = client.get("/api/items", params={"sort": "random", "seed": 123, "limit": 10, "offset": 10}).json()

    first_ids = [it["id"] for it in page1["items"]]
    assert first_ids == [it["id"] for it in page1_again["items"]]
    assert len(first_ids) == 10
    assert not set(first_ids) & {it["id"] for it in page2["items"]}


def test_collection_count_only_visible_items(client):
    ids = _seed_items(client, 3)
    db = client.app.state.db
    col = db.create_collection("可见计数")
    db.add_to_collection(col["id"], ids)
    db.soft_delete([ids[0]])
    db.set_status(ids[1], "draft")

    data = client.get("/api/collections").json()
    target = next(c for c in data["collections"] if c["id"] == col["id"])
    assert target["item_count"] == 1


def test_top_viewed_skips_zero_views(client):
    ids = _seed_items(client, 2)
    db = client.app.state.db
    db.increment_counter(ids[0], "views")

    data = client.get("/api/analytics").json()
    assert [it["id"] for it in data["top_viewed"]] == [ids[0]]
