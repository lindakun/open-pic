#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工精选排布测试（REQ-V2-20 A-02 遗留项）"""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import MediaDB


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    database = MediaDB(os.path.join(d, "media.db"))
    ids = []
    for i in range(6):
        iid = f"aaaaaa{i}" + "0" * 9
        ids.append(iid)
        database.upsert_item({
            "id": iid, "file": f"f{i}.jpg", "kind": "image", "ext": ".jpg",
            "name": f"f{i}.jpg", "title": f"资产{i}", "size": 100,
            "width": 100, "height": 100,
            # 时间递增：ts 越大越新，用于验证排序不被覆盖
            "ts": int(time.time()) + i,
        })
    database._ids = ids
    return database


def test_set_featured_preserves_order(db):
    """顺序即位置，与 ts 无关（人工排布优先）。"""
    picked = [db._ids[3], db._ids[0], db._ids[5]]
    assert db.set_featured(picked) == 3
    assert db.featured_ids() == picked
    assert [i["id"] for i in db.list_featured()] == picked


def test_set_featured_replaces_previous(db):
    db.set_featured([db._ids[0], db._ids[1]])
    db.set_featured([db._ids[2]])
    assert db.featured_ids() == [db._ids[2]]


def test_featured_skips_deleted_and_unpublished(db):
    db.set_featured([db._ids[0], db._ids[1], db._ids[2]])
    db.soft_delete([db._ids[1]])
    db.set_status(db._ids[2], "draft")

    ids = [i["id"] for i in db.list_featured()]
    assert ids == [db._ids[0]]
    # 原始排布仍保留（恢复后自动回位）
    assert db.featured_ids() == [db._ids[0], db._ids[1], db._ids[2]]


def test_home_featured_falls_back_to_recent(db):
    """没有人工精选时用最近上新补齐，首页不出现空白区。"""
    items = db.featured_items_for_home(limit=4)
    assert len(items) == 4
    # 最近上新在前（ts 最大的）
    assert items[0]["id"] == db._ids[5]


def test_home_featured_prefers_manual_picks(db):
    db.set_featured([db._ids[2]])
    items = db.featured_items_for_home(limit=3)
    assert items[0]["id"] == db._ids[2]
    assert len(items) == 3
    # 补齐项不与精选重复
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))


def test_home_featured_excludes_deleted(db):
    db.soft_delete([db._ids[5]])
    items = db.featured_items_for_home(limit=6)
    assert db._ids[5] not in [i["id"] for i in items]
