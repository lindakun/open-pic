#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运营事件与指标测试（REQ-V2-20 D-18）"""

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
    for i in range(2):
        database.upsert_item({
            "id": f"aaaaaa{i}" + "0" * 9, "file": f"f{i}.jpg", "kind": "image",
            "ext": ".jpg", "name": f"f{i}.jpg", "title": f"资产{i}", "size": 100,
            "width": 100, "height": 100, "ts": int(time.time()),
        })
    database._ids = [f"aaaaaa{i}" + "0" * 9 for i in range(2)]
    return database


def test_add_events_batches(db):
    n = db.add_events([
        {"type": "impression", "item_id": db._ids[0], "device": "desktop"},
        {"type": "view", "item_id": db._ids[0], "device": "desktop"},
        {"type": "download", "item_id": db._ids[0], "device": "mobile"},
    ])
    assert n == 3


def test_add_events_skips_invalid_type(db):
    """非法类型跳过，不报错——埋点不该影响业务。"""
    n = db.add_events([
        {"type": "view", "item_id": db._ids[0]},
        {"type": "not_a_type", "item_id": db._ids[0]},
        {"type": "", "item_id": db._ids[0]},
    ])
    assert n == 1


def test_add_events_empty_is_noop(db):
    assert db.add_events([]) == 0


def test_funnel_sums_by_type(db):
    iid = db._ids[0]
    for _ in range(5):
        db.add_events([{"type": "impression", "item_id": iid}])
    for _ in range(3):
        db.add_events([{"type": "view", "item_id": iid}])
    db.add_events([{"type": "download", "item_id": iid}])

    ov = db.event_overview(days=7)
    row = next(r for r in ov["funnel"] if r["item_id"] == iid)
    assert row["impressions"] == 5
    assert row["views"] == 3
    assert row["downloads"] == 1
    # 漏斗单调：曝光 ≥ 点击 ≥ 下载
    assert row["impressions"] >= row["views"] >= row["downloads"]


def test_funnel_includes_title(db):
    iid = db._ids[0]
    db.add_events([{"type": "view", "item_id": iid}])
    ov = db.event_overview(days=7)
    row = next(r for r in ov["funnel"] if r["item_id"] == iid)
    assert row["title"] == "资产0"


def test_zero_result_searches_listed(db):
    """零结果搜索词能在看板筛出（D-18 验收 3）。"""
    db.add_events([
        {"type": "search", "meta": {"q": "不存在的词", "result_count": 0}},
        {"type": "search", "meta": {"q": "不存在的词", "result_count": 0}},
        {"type": "search", "meta": {"q": "城市", "result_count": 12}},
    ])
    ov = db.event_overview(days=7)
    words = {z["q"]: z["count"] for z in ov["zero_result_searches"]}
    assert words.get("不存在的词") == 2
    assert "城市" not in words


def test_trend_grouped_by_day_and_type(db):
    db.add_events([{"type": "view"}, {"type": "view"}, {"type": "download"}])
    ov = db.event_overview(days=7)
    total = sum(t["cnt"] for t in ov["trend"])
    assert total == 3


def test_device_and_referrer_distribution(db):
    db.add_events([
        {"type": "view", "device": "desktop", "referrer": "direct"},
        {"type": "view", "device": "desktop", "referrer": "direct"},
        {"type": "view", "device": "mobile", "referrer": "search"},
    ])
    ov = db.event_overview(days=7)
    devices = {d["device"]: d["cnt"] for d in ov["devices"]}
    assert devices["desktop"] == 2
    refs = {r["referrer"]: r["cnt"] for r in ov["referrers"]}
    assert refs["direct"] == 2


def test_events_outside_window_excluded(db):
    old = int(time.time()) - 30 * 86400
    db.add_events([{"type": "view", "ts": old}])
    ov = db.event_overview(days=7)
    assert sum(t["cnt"] for t in ov["trend"]) == 0
    # 放宽窗口后又能看到
    ov30 = db.event_overview(days=60)
    assert sum(t["cnt"] for t in ov30["trend"]) == 1


# ---------- 指标 ----------


def test_add_metrics_and_percentiles(db):
    db.add_metrics([
        {"name": "LCP", "value": v, "page_type": "home", "device": "desktop"}
        for v in [100, 200, 300, 400, 500]
    ])
    summary = db.metrics_summary(name="LCP", days=7)
    row = summary[0]
    assert row["name"] == "LCP"
    assert row["count"] == 5
    assert row["p50"] == 300
    assert row["p95"] >= 400


def test_add_metrics_skips_bad_values(db):
    n = db.add_metrics([
        {"name": "CLS", "value": 0.01},
        {"name": "", "value": 1},
        {"name": "INP", "value": "abc"},
    ])
    assert n == 1


def test_metrics_summary_empty(db):
    assert db.metrics_summary(days=7) == []
