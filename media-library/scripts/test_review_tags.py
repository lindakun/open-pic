#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选片、标签治理与个人工作区测试（REQ-V2-20 C-14 / B-09 / C-15）"""

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
    for i in range(4):
        iid = f"aaaaaa{i}" + "0" * 9
        ids.append(iid)
        database.upsert_item({
            "id": iid,
            "file": f"f{i}.jpg",
            "kind": "image",
            "ext": ".jpg",
            "name": f"f{i}.jpg",
            "title": f"资产{i}",
            "size": 100,
            "width": 100,
            "height": 100,
            "ts": int(time.time()),
            "tags": ["海边"] if i < 2 else ["城市"],
        })
    database._test_ids = ids
    return database


def _make_collection(db, ids):
    col = db.create_collection("选片集")
    db.add_to_collection(col["id"], ids)
    return col


# ---------- C-14 客户选片 ----------


def test_review_link_create_and_resolve(db):
    col = _make_collection(db, db._test_ids[:3])
    link = db.create_review_link(col["id"], title="客户A选片")
    assert link["token"]
    assert db.get_review_link(link["token"])["collection_id"] == col["id"]


def test_review_mark_persists_and_summarizes(db):
    """标记与批注写库后，汇总按状态分组（C-14 验收 1/2）。"""
    col = _make_collection(db, db._test_ids[:3])
    token = db.create_review_link(col["id"])["token"]

    assert db.set_review_mark(token, db._test_ids[0], "selected", "就用这张", "客户A")[0]
    assert db.set_review_mark(token, db._test_ids[1], "rejected", "色调偏冷")[0]
    # 重复标记走 upsert，不报错也不产生重复行
    assert db.set_review_mark(token, db._test_ids[0], "selected", "改用横幅裁切")[0]

    summary = db.review_summary(token)
    assert summary["ok"]
    assert len(summary["states"]["selected"]) == 1
    assert summary["states"]["selected"][0]["note"] == "改用横幅裁切"
    assert len(summary["states"]["rejected"]) == 1
    assert len(summary["states"]["unmarked"]) == 1
    assert summary["total"] == 3


def test_review_mark_rejects_item_outside_collection(db):
    col = _make_collection(db, db._test_ids[:1])
    token = db.create_review_link(col["id"])["token"]
    ok, msg = db.set_review_mark(token, db._test_ids[3], "selected")
    assert ok is False
    assert "范围" in msg


def test_review_mark_rejects_bad_state(db):
    col = _make_collection(db, db._test_ids[:1])
    token = db.create_review_link(col["id"])["token"]
    ok, _ = db.set_review_mark(token, db._test_ids[0], "approved")
    assert ok is False


def test_revoked_link_becomes_invalid(db):
    col = _make_collection(db, db._test_ids[:1])
    token = db.create_review_link(col["id"])["token"]
    assert db.get_review_link(token)
    assert db.revoke_review_link(token)
    assert db.get_review_link(token) is None


def test_expired_link_invalid(db):
    col = _make_collection(db, db._test_ids[:1])
    token = db.create_review_link(col["id"], expires_at=int(time.time()) - 10)["token"]
    assert db.get_review_link(token) is None


def test_deleted_item_excluded_from_review(db):
    col = _make_collection(db, db._test_ids[:2])
    token = db.create_review_link(col["id"])["token"]
    db.soft_delete([db._test_ids[0]])
    assert len(db.get_review_items(token)) == 1


# ---------- B-09 标签治理 ----------


def test_merge_tags_moves_items_and_keeps_alias(db):
    """合并后资产归目标、源标签消失、旧名可作别名解析（B-09 验收 1）。"""
    res = db.merge_tags("海边", "城市")
    assert res["ok"], res
    assert res["moved"] == 2

    names = [t["name"] for t in db.list_tag_admin()]
    assert "海边" not in names
    # 历史深链 ?tag=海边 自动归一到 城市
    assert db.resolve_tag_alias("海边") == "城市"

    total, items = db.query_items(tags=["城市"], limit=10)
    assert total == 4


def test_alias_filters_resolve_to_target(db):
    """合并后按旧标签名筛选仍能命中（B-09 验收 1：历史深链可用）。"""
    db.merge_tags("海边", "城市")
    total, items = db.query_items(tags=["海边"], limit=10)
    assert total == 4  # 海边的 2 项已并入城市，合计 4

    # 排除条件同样走别名
    total2, _ = db.query_items(exclude_tags=["海边"], limit=10)
    assert total2 == 0


def test_rename_survives_restart(tmp_path):
    """重命名写库后新进程仍可检索（B-09 验收 2 的持久性）。"""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "m.db")
    a = MediaDB(path)
    a.upsert_item({
        "id": "cccccc111", "file": "c.jpg", "kind": "image", "ext": ".jpg",
        "name": "c.jpg", "title": "测试", "size": 1, "width": 10, "height": 10,
        "ts": int(time.time()), "tags": ["旧名"],
    })
    assert a.rename_tag("旧名", "新名")["ok"]

    b = MediaDB(path)
    total, _ = b.query_items(q="新名", limit=10)
    assert total == 1


def test_merge_tags_rejects_missing(db):
    assert db.merge_tags("不存在", "城市")["ok"] is False
    assert db.merge_tags("城市", "城市")["ok"] is False


def test_rename_tag_syncs_search(db):
    """重命名后新名可被检索命中（B-09 验收 2）。"""
    res = db.rename_tag("海边", "海岸线")
    assert res["ok"], res
    total, items = db.query_items(q="海岸线", limit=10)
    assert total == 2
    assert all("海岸线" in (i.get("tags") or []) for i in items)


def test_rename_tag_rejects_duplicate(db):
    res = db.rename_tag("海边", "城市")
    assert res["ok"] is False
    assert "合并" in res["message"]


def test_tag_admin_counts(db):
    tags = {t["name"]: t["count"] for t in db.list_tag_admin()}
    assert tags["海边"] == 2
    assert tags["城市"] == 2


# ---------- C-15 个人工作区 ----------


def test_like_toggle_and_list(db):
    iid = db._test_ids[0]
    assert db.set_liked(iid, True)
    assert db.list_liked_ids() == [iid]
    assert db.set_liked(iid, False)
    assert db.list_liked_ids() == []


def test_like_excludes_deleted(db):
    iid = db._test_ids[0]
    db.set_liked(iid, True)
    db.soft_delete([iid])
    assert db.list_liked_ids() == []
