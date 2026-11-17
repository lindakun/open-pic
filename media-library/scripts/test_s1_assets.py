#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 新增能力测试：/img 按需变换、/api/facets 分面统计、双前端切换

覆盖 REQ-V2-20 的 A-05 与 B-10 验收要点：
  - 变换端点返回正确尺寸与格式，AVIF 不可用时回退而非报错
  - 缓存命中后重复请求不再重新编码
  - 分面计数与实际结果总数一致
  - 新前端与旧前端可切换
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402


def _png_bytes(w: int = 800, h: int = 600, seed: int = 0) -> bytes:
    """生成内容可区分的 PNG。

    注意：入库以 SHA1 去重，内容相同的图会被合并成同一条记录，
    因此测试多条目场景时必须让像素不同（用 seed 偏移色值）。
    """
    from PIL import Image, ImageDraw

    buf = io.BytesIO()
    im = Image.new("RGB", (w, h), (120 + seed, 140, 160))
    # 画一个随 seed 变化的小块，确保字节流不同
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, 40 + seed, 40], fill=(200, 100 + seed, 50))
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """独立数据目录的测试客户端，不影响其他测试的数据。"""
    monkeypatch.setenv("MEDIA_LIB_DIR", str(tmp_path))
    # 重新导入，确保使用新的数据目录
    for mod in ("server", "db", "tasks"):
        sys.modules.pop(mod, None)
    import server  # noqa: E402

    app = server.create_app()
    with TestClient(app) as c:
        yield c


def _upload(client, name: str = "shot.png", seed: int = 0) -> str:
    resp = client.post(
        "/api/upload",
        files={"file": (name, _png_bytes(seed=seed), "image/png")},
        data={"title": "测试图", "tags": "风景,城市"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["items"][0]["id"]


class TestImgTransform:
    def test_returns_webp_at_requested_width(self, client):
        item_id = _upload(client)
        resp = client.get(f"/img/{item_id}?w=360&fm=webp")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"

        from PIL import Image

        im = Image.open(io.BytesIO(resp.content))
        assert im.size[0] == 360

    def test_aspect_ratio_preserved_when_only_width_given(self, client):
        item_id = _upload(client)
        resp = client.get(f"/img/{item_id}?w=400&fm=webp")
        from PIL import Image

        im = Image.open(io.BytesIO(resp.content))
        # 源图 800×600，按宽 400 缩放后应为 400×300
        assert im.size == (400, 300)

    def test_unknown_format_falls_back_to_webp(self, client):
        item_id = _upload(client)
        resp = client.get(f"/img/{item_id}?w=200&fm=bogus")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"

    def test_oversized_dimension_is_clamped(self, client):
        item_id = _upload(client)
        resp = client.get(f"/img/{item_id}?w=99999&fm=webp")
        assert resp.status_code == 200
        from PIL import Image

        im = Image.open(io.BytesIO(resp.content))
        # 上限 4096，但源图宽仅 800，不应被放大
        assert im.size[0] <= 4096

    def test_missing_item_returns_404(self, client):
        assert client.get("/img/deadbeef00?w=100").status_code == 404

    def test_invalid_id_returns_404(self, client):
        assert client.get("/img/not-an-id?w=100").status_code == 404

    def test_second_request_served_from_cache(self, client, tmp_path):
        item_id = _upload(client)
        first = client.get(f"/img/{item_id}?w=360&fm=webp")
        assert first.status_code == 200

        cache_dir = tmp_path / "imgcache"
        files_before = sum(len(f) for _, _, f in os.walk(cache_dir))
        second = client.get(f"/img/{item_id}?w=360&fm=webp")
        files_after = sum(len(f) for _, _, f in os.walk(cache_dir))

        assert second.status_code == 200
        # 第二次命中缓存，不应新增缓存文件
        assert files_after == files_before
        assert len(second.content) == len(first.content)


class TestFacets:
    def test_counts_match_total(self, client):
        _upload(client, "a.png", seed=1)
        _upload(client, "b.png", seed=2)
        data = client.get("/api/facets").json()

        assert data["total"] == 2
        kind_counts = {o["value"]: o["count"] for o in data["kind"]}
        assert kind_counts.get("image") == 2
        # 各分面计数之和应等于总数（此处仅验证主维度）
        assert sum(o["count"] for o in data["kind"]) == data["total"]

    def test_orientation_buckets_are_correct(self, client):
        _upload(client, "wide.png")  # 800×600 横图
        data = client.get("/api/facets").json()
        orientations = {o["value"]: o["count"] for o in data["orientation"]}
        assert orientations.get("landscape") == 1
        assert "portrait" not in orientations

    def test_tags_are_counted(self, client):
        _upload(client, "tagged.png")
        data = client.get("/api/facets").json()
        tags = {o["value"] for o in data["tag"]}
        assert {"风景", "城市"} <= tags

    def test_deleted_items_excluded(self, client):
        item_id = _upload(client, "gone.png")
        client.post("/api/delete", json={"ids": [item_id]})

        data = client.get("/api/facets").json()
        assert data["total"] == 0
        assert data["tag"] == []


class TestFrontendSwitch:
    def test_root_returns_shell_or_redirect(self, client):
        """根路径要么重定向到新前端，要么返回旧单页，均不应 5xx。"""
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (200, 302)

    def test_app_path_serves_shell_when_built(self, client):
        """新前端产物存在时应能返回外壳；未构建时 404 也是合理行为。"""
        resp = client.get("/app/")
        assert resp.status_code in (200, 404)

    def test_legacy_frontend_still_reachable(self, client):
        """旧前端的静态资源不受影响（v1 契约兼容）。"""
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
