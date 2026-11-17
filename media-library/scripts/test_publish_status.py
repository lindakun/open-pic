#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策展状态与定时发布测试（REQ-V2-20 C-12）"""

import os
import sys
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import MediaDB


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    database = MediaDB(os.path.join(d, "media.db"))
    for i in range(3):
        database.upsert_item({
            "id": f"aaaaaa{i}0" + "0" * 6,
            "file": f"f{i}.jpg",
            "kind": "image",
            "ext": ".jpg",
            "name": f"f{i}.jpg",
            "title": f"资产{i}",
            "size": 100,
            "width": 100,
            "height": 100,
            "ts": int(time.time()),
        })
    return database


def test_default_query_only_published(db):
    """默认查询只返回 published（C-12 验收 3）。"""
    ids = [r["id"] for r in db.query_items(limit=10)[1]]
    assert len(ids) == 3

    db.set_status(ids[0], "draft")
    total, items = db.query_items(limit=10)
    assert total == 2
    assert ids[0] not in [i["id"] for i in items]


def test_invalid_transition_rejected(db):
    """archived 不能直接回 published（C-12 验收 1）。"""
    iid = db.query_items(limit=1)[1][0]["id"]
    ok, _ = db.set_status(iid, "archived")
    assert ok
    ok, msg = db.set_status(iid, "published")
    assert ok is False
    assert "archived" in msg and "published" in msg


def test_valid_transition_chain(db):
    iid = db.query_items(limit=1)[1][0]["id"]
    assert db.set_status(iid, "draft")[0]
    assert db.set_status(iid, "published")[0]
    assert db.set_status(iid, "archived")[0]
    assert db.set_status(iid, "draft")[0]


def test_scheduled_publish_lazy_query(db):
    """定时发布到期后查询侧即时可见（惰性兜底）。"""
    iid = db.query_items(limit=1)[1][0]["id"]
    future = int(time.time()) + 3600
    db.set_status(iid, "draft", publish_at=future)

    assert db.query_items(limit=10)[0] == 2  # 未到期，不可见

    # 直接改到过去时间模拟到期
    db.set_status(iid, "draft", publish_at=int(time.time()) - 1)
    total, items = db.query_items(limit=10)
    assert total == 3
    assert iid in [i["id"] for i in items]


def test_publish_sweep_promotes_due_items(db):
    """调度侧扫描把到期项落为 published（与查询侧互补）。"""
    iid = db.query_items(limit=1)[1][0]["id"]
    db.set_status(iid, "draft", publish_at=int(time.time()) - 1)

    assert db.publish_due_items() == 1
    # 状态已真的变成 published，不只是查询兜底
    assert db.get_item(iid)["status"] == "published"


def test_unpublished_excluded_from_sitemap_source(db):
    """draft 不出现在 sitemap 数据源（C-12 验收 3）。"""
    iid = db.query_items(limit=1)[1][0]["id"]
    db.set_status(iid, "draft", publish_at=None)
    ids = [r["id"] for r in db.list_published_items()]
    assert iid not in ids


def test_include_unpublished_lists_all(db):
    iid = db.query_items(limit=1)[1][0]["id"]
    db.set_status(iid, "draft")
    total, _ = db.query_items(limit=10, include_unpublished=True)
    assert total == 3
