#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 10 批修复（R10）的回归测试

覆盖：
  1. 编辑保存标签不重置既有标签来源（ai 标识保留）
  2. 清空回收站不受分页上限约束（新增 permanent_delete_all_trashed）
  3. /img/ 非白名单宽度不落缓存、直接回原图
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


def _upload_png(c: TestClient, name: str, color=(70, 100, 190)) -> dict:
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


def test_update_tags_preserves_source(client):
    """先以 ai 来源挂标签，再整体保存标签，来源不应被重置成 manual。"""
    it = _upload_png(client, "src-keep")
    iid = it["id"]
    db = client.app.state.db
    db.set_tags_with_source(iid, ["风光", "夜景"], source="ai")

    # 整体保存（模拟 PATCH /api/item 的 tags 路径），ai 标签 + 新 manual 标签
    r = client.patch(f"/api/item/{iid}", json={"tags": ["风光", "夜景", "精选"]})
    assert r.status_code == 200

    with db.connect() as conn:
        rows = {r["name"]: r["source"] for r in conn.execute(
            "SELECT t.name, it.source FROM item_tags it"
            " JOIN tags t ON t.id=it.tag_id WHERE it.item_id=?",
            (iid,),
        ).fetchall()}
    assert rows.get("风光") == "ai", "既有 ai 标签被重置为 manual"
    assert rows.get("夜景") == "ai"
    assert rows.get("精选") == "manual", "新标签应为 manual"


def test_empty_trash_no_row_limit(client):
    """清空回收站直接按 deleted_at 物理删，无需经过分页查询。"""
    a = _upload_png(client, "t1", color=(10, 10, 10))
    b = _upload_png(client, "t2", color=(20, 20, 20))
    client.post("/api/delete", json={"ids": [a["id"], b["id"]]})

    r = client.post("/api/trash/empty")
    assert r.status_code == 200
    assert r.json()["count"] == 2
    # 再删一次：0 条，幂等
    assert client.post("/api/trash/empty").json()["count"] == 0


def test_img_no_width_serves_original_without_cache(client, tmp_path):
    """/img/ 不带尺寸参数直接回原图，不复制进缓存目录（A-05 原契约）。"""
    it = _upload_png(client, "cache-test")
    r = client.get(f"/img/{it['id']}")
    assert r.status_code == 200
    cache_dir = os.path.join(str(tmp_path), "imgcache")
    assert not os.path.isdir(cache_dir) or not any(
        os.listdir(os.path.join(cache_dir, d)) for d in os.listdir(cache_dir)
    ), "无尺寸请求不应落缓存"
