#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI provider 与语义检索测试（REQ-V2-20 B-07 / B-08）

重点覆盖「未配置时优雅降级」——这是 B-08 验收 4 的硬要求：
接口必须返回 501 语义而不是 500，且入库与浏览完全不受影响。
"""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_provider
from db import MediaDB


# ---------- provider 抽象 ----------


def test_default_provider_is_unavailable():
    prov = ai_provider.get_provider({})
    assert prov.name == "none"
    assert prov.available() is False


def test_openai_provider_needs_full_config():
    partial = ai_provider.get_provider({
        "MEDIA_LIB_AI_PROVIDER": "openai",
        "MEDIA_LIB_AI_BASE_URL": "https://api.example.com/v1",
    })
    assert prov_partial_unavailable(partial)


def prov_partial_unavailable(prov) -> bool:
    return prov.available() is False


def test_openai_provider_available_with_config():
    prov = ai_provider.get_provider({
        "MEDIA_LIB_AI_PROVIDER": "openai",
        "MEDIA_LIB_AI_BASE_URL": "https://api.example.com/v1",
        "MEDIA_LIB_AI_KEY": "sk-test",
        "MEDIA_LIB_AI_EMBED_MODEL": "text-embedding-3-small",
    })
    assert prov.name == "openai"
    assert prov.available() is True


def test_unavailable_provider_raises_aiunavailable():
    prov = ai_provider.get_provider({})
    with pytest.raises(ai_provider.AIUnavailable):
        prov.embed_text("黄昏下的城市天际线")


def test_extract_json_handles_fenced_output():
    text = '```json\n{"style": "极简", "tags": ["城市", "夜景"]}\n```'
    data = ai_provider._extract_json(text)
    assert data["style"] == "极简"
    assert data["tags"] == ["城市", "夜景"]


def test_extract_json_tolerates_prose():
    text = '这是结果：{"scene": "自然"} 希望有帮助'
    assert ai_provider._extract_json(text)["scene"] == "自然"


def test_extract_json_bad_input_returns_empty():
    assert ai_provider._extract_json("完全不是 JSON") == {}


# ---------- 向量工具 ----------


def test_normalize_makes_unit_vector():
    vec = ai_provider.normalize([3.0, 4.0])
    assert abs(sum(x * x for x in vec) - 1.0) < 1e-6


def test_pack_unpack_roundtrip():
    vec = ai_provider.normalize([0.1 * i for i in range(512)])
    blob = ai_provider.pack_vector(vec)
    assert len(blob) == 512 * 4
    back = ai_provider.unpack_vector(blob)
    assert len(back) == 512
    assert abs(back[10] - vec[10]) < 1e-6


def test_cosine_dimension_mismatch_returns_zero():
    assert ai_provider.cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_identical_is_one():
    v = ai_provider.normalize([1.0, 2.0, 3.0])
    assert abs(ai_provider.cosine(v, v) - 1.0) < 1e-6


# ---------- RRF 融合 ----------


def test_rrf_keeps_keyword_hits_in_top10():
    """关键词命中不得被向量结果全量挤出（B-08 验收 3）。"""
    kw = [f"kw{i}" for i in range(10)]
    vec = [f"v{i}" for i in range(40)]
    fused = ai_provider.rrf_fuse(kw, vec, limit=10)
    assert len([i for i in fused if i.startswith("kw")]) >= 3


def test_rrf_prefers_items_in_both_lists():
    kw = ["a", "b", "c"]
    vec = ["c", "d", "e"]
    fused = ai_provider.rrf_fuse(kw, vec, limit=5)
    # 同时出现在两路的 c 应排最前
    assert fused[0] == "c"


def test_rrf_limit_respected():
    fused = ai_provider.rrf_fuse([f"k{i}" for i in range(50)], [], limit=7)
    assert len(fused) == 7


# ---------- 数据层 ----------


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    database = MediaDB(os.path.join(d, "media.db"))
    for i in range(5):
        database.upsert_item({
            "id": f"aaaaaa{i}" + "0" * 9,
            "file": f"f{i}.jpg", "kind": "image", "ext": ".jpg",
            "name": f"f{i}.jpg", "title": f"城市夜景 {i}", "size": 100,
            "width": 100, "height": 100, "ts": int(time.time()),
        })
    return database


def test_embedding_upsert_and_read(db):
    vec = ai_provider.normalize([0.5] * 512)
    db.upsert_embedding("aaaaaa0" + "0" * 9, ai_provider.pack_vector(vec), "m1")
    row = db.get_embedding("aaaaaa0" + "0" * 9)
    assert row["model_version"] == "m1"
    assert row["dim"] == 512


def test_iter_embeddings_filters_by_model(db):
    ids = [f"aaaaaa{i}" + "0" * 9 for i in range(3)]
    for i, iid in enumerate(ids):
        db.upsert_embedding(iid, ai_provider.pack_vector([1.0] * 512), "m1" if i < 2 else "m2")
    assert len(db.iter_embeddings("m1")) == 2
    assert len(db.iter_embeddings()) == 3


def test_missing_embedding_ids_tracks_pending(db):
    assert len(db.missing_embedding_ids("m1", limit=10)) == 5
    db.upsert_embedding("aaaaaa0" + "0" * 9, ai_provider.pack_vector([1.0] * 512), "m1")
    assert len(db.missing_embedding_ids("m1", limit=10)) == 4


def test_rejected_tags_persist(db):
    iid = "aaaaaa0" + "0" * 9
    db.add_rejected_tags(iid, ["赛博朋克", "夜景"])
    assert set(db.rejected_tags(iid)) == {"赛博朋克", "夜景"}


def test_ai_tags_marked_with_source(db):
    iid = "aaaaaa0" + "0" * 9
    db.set_tags_with_source(iid, ["极简", "城市"], source="ai")
    item = db.get_item(iid)
    assert "极简" in item["tags"]
    # AI 标签可被检索到（FTS 已同步）
    total, _ = db.query_items(q="极简", limit=10)
    assert total == 1


# ---------- API 降级（B-08 验收 4） ----------


def test_api_returns_501_when_provider_unconfigured(monkeypatch):
    """未配置 provider 时语义检索返回 501，而非 500。"""
    from fastapi.testclient import TestClient

    monkeypatch.delenv("MEDIA_LIB_AI_PROVIDER", raising=False)
    monkeypatch.delenv("MEDIA_LIB_AI_KEY", raising=False)
    import server

    app = server.create_app(data_dir=tempfile.mkdtemp(), port=18299, start_workers=False)
    client = TestClient(app)

    r = client.get("/api/search/semantic", params={"q": "黄昏下的城市天际线"})
    assert r.status_code == 501
    assert "未启用" in r.json()["detail"]

    r2 = client.post("/api/search/by-image")
    assert r2.status_code == 501

    r3 = client.post("/api/jobs/embedding-backfill")
    assert r3.status_code == 501


def test_api_ai_status_reports_unavailable_not_error(monkeypatch):
    """状态接口在未配置时返回 available=false，不报错（前端据此隐藏入口）。"""
    from fastapi.testclient import TestClient

    monkeypatch.delenv("MEDIA_LIB_AI_PROVIDER", raising=False)
    import server

    app = server.create_app(data_dir=tempfile.mkdtemp(), port=18298, start_workers=False)
    client = TestClient(app)

    r = client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["provider"] == "none"
    assert "未启用" in body["hint"]


def test_api_semantic_works_with_fake_provider(monkeypatch):
    """配置 provider 后无需改代码即可启用（B-08 验收 5 的切换演练）。"""
    from fastapi.testclient import TestClient
    import server

    class FakeProvider(ai_provider.BaseProvider):
        name = "fake"
        embed_model = "fake-v1"

        def available(self) -> bool:
            return True

        def embed_text(self, text: str):
            return ai_provider.normalize([1.0] + [0.0] * 511)

        def embed_image(self, image_bytes: bytes):
            return ai_provider.normalize([1.0] + [0.0] * 511)

    app = server.create_app(data_dir=tempfile.mkdtemp(), port=18297, start_workers=False)
    client = TestClient(app)

    # 先造一条资产并写入向量
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 150), (30, 40, 50)).save(buf, format="JPEG")
    buf.seek(0)
    up = client.post("/api/upload", files={"file": ("t.jpg", buf, "image/jpeg")},
                     data={"tags": "城市"})
    assert up.status_code == 200
    iid = up.json()["items"][0]["id"]

    db = app.state.db
    db.upsert_embedding(iid, ai_provider.pack_vector(
        ai_provider.normalize([1.0] + [0.0] * 511)), "fake-v1")

    monkeypatch.setattr(server, "AI_PROVIDER_FACTORY", lambda: FakeProvider())
    r = client.get("/api/search/semantic", params={"q": "夜景", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(i["id"] == iid for i in body["items"])
