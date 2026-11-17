#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 新能力测试：授权署名（C-11）与管线异步化（D-16）

验收要点：
  - 上传默认走异步：接口立即返回，元数据随后由后台任务补齐
  - 同步模式仍可用（CLI/ingest.py 兼容路径）
  - 授权字段可写入与更新，commercial_ok 布尔语义正确
  - 导出前的 EXIF 清洗函数可用
"""

import io
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _png_bytes(w: int = 800, h: int = 600, seed: int = 0) -> bytes:
    from PIL import Image, ImageDraw

    buf = io.BytesIO()
    im = Image.new("RGB", (w, h), (120 + seed, 140, 160))
    ImageDraw.Draw(im).rectangle([0, 0, 40 + seed, 40], fill=(200, 100 + seed, 50))
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_LIB_DIR", str(tmp_path))
    for mod in ("server", "db", "tasks"):
        sys.modules.pop(mod, None)
    import server

    app = server.create_app()
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _upload(client, name="a.png", seed=0, **extra):
    data = {"title": "测试", "tags": "风景", "synchronous": "1"}
    data.update(extra)
    resp = client.post(
        "/api/upload",
        files={"file": (name, _png_bytes(seed=seed), "image/png")},
        data=data,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"][0]


class TestAsyncPipeline:
    def test_async_upload_returns_fast_without_metadata(self, client):
        """异步模式下立即返回，宽高为 0（由后台补齐）。"""
        started = time.time()
        resp = client.post(
            "/api/upload",
            files={"file": ("fast.png", _png_bytes(seed=7), "image/png")},
            data={"title": "异步"},
        )
        elapsed = time.time() - started
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        # 关键：不在请求内做元数据提取
        assert item["width"] == 0
        # 上传本身应是毫秒级（宽松上限，避免 CI 抖动误判）
        assert elapsed < 2.0

    def test_async_upload_enqueues_job(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("job.png", _png_bytes(seed=8), "image/png")},
            data={"title": "任务"},
        )
        item_id = resp.json()["items"][0]["id"]
        jobs = client.get("/api/jobs?limit=20").json()["jobs"]
        matching = [j for j in jobs if j["job_type"] == "media_process"
                    and j["payload"].get("item_id") == item_id]
        assert matching, "应创建 media_process 任务"

    def test_synchronous_mode_still_returns_metadata(self, client):
        """CLI/ingest.py 兼容路径：synchronous=1 时同步拿到宽高与缩略图。"""
        item = _upload(client, "sync.png", seed=9)
        assert item["width"] == 800
        assert item["height"] == 600
        assert item["thumb"]


class TestLicense:
    def test_upload_with_license_fields(self, client):
        item = _upload(
            client, "lic.png", seed=11,
            license="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            credit="Photo by Demo",
            copyright_holder="Demo Studio",
            commercial_ok="0",
        )
        assert item["license"] == "CC-BY-4.0"
        assert item["credit"] == "Photo by Demo"
        assert item["copyright_holder"] == "Demo Studio"
        # 字符串 "0" 应解析为不可商用
        assert item["commercial_ok"] == 0

    def test_default_is_commercial_ok(self, client):
        item = _upload(client, "def.png", seed=12)
        assert item["commercial_ok"] == 1

    def test_update_license(self, client):
        item = _upload(client, "upd.png", seed=13)
        resp = client.patch(
            f"/api/item/{item['id']}/license",
            json={
                "license": "CC0-1.0",
                "commercial_ok": True,
                "credit": "Updated credit",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["license"] == "CC0-1.0"
        assert body["credit"] == "Updated credit"
        assert body["commercial_ok"] == 1

    def test_update_license_missing_item(self, client):
        assert client.patch("/api/item/deadbeef00/license",
                            json={"license": "CC0"}).status_code == 404

    def test_license_unknown_field_ignored(self, client):
        """非白名单字段不得写入（防注入任意列）。"""
        item = _upload(client, "inj.png", seed=14)
        resp = client.patch(
            f"/api/item/{item['id']}/license",
            json={"license": "CC0", "views": 99999},
        )
        assert resp.status_code == 200
        assert resp.json()["views"] == 0

    def test_license_persists_across_reads(self, client):
        item = _upload(client, "per.png", seed=15, license="MIT")
        got = client.get(f"/api/item/{item['id']}").json()
        assert got["license"] == "MIT"


class TestExifSanitize:
    """导出副本的隐私清洗（C-11 验收第 2 条）。"""

    def _make_jpeg_with_gps(self, path):
        from PIL import Image

        im = Image.new("RGB", (400, 300), (100, 150, 200))
        exif = im.getexif()
        exif[34853] = {2: (39.9, 116.4)}      # GPSInfo
        exif[272] = "SecretPhone"              # Model
        exif[306] = "2024:01:01 10:00:00"      # DateTime，应保留
        im.save(path, "JPEG", exif=exif)

    def test_gps_and_model_removed_datetime_kept(self, tmp_path):
        import img_transform
        from PIL import Image

        src = str(tmp_path / "src.jpg")
        out = str(tmp_path / "out.jpg")
        self._make_jpeg_with_gps(src)

        assert img_transform.sanitize_copy(src, out, "jpeg") is True

        with Image.open(out) as im:
            keys = list(im.getexif().keys())
        assert 34853 not in keys, "GPS 必须剥离"
        assert 272 not in keys, "机型必须剥离"
        assert 306 in keys, "拍摄时间应保留"

    def test_original_file_untouched(self, tmp_path):
        import img_transform
        from PIL import Image

        src = str(tmp_path / "orig.jpg")
        self._make_jpeg_with_gps(src)
        before = open(src, "rb").read()

        img_transform.sanitize_copy(src, str(tmp_path / "copy.jpg"), "jpeg")

        assert open(src, "rb").read() == before
        with Image.open(src) as im:
            assert 34853 in list(im.getexif().keys())

    def test_sanitize_missing_source_returns_false(self, tmp_path):
        import img_transform

        assert img_transform.sanitize_copy(
            str(tmp_path / "nope.jpg"), str(tmp_path / "o.jpg")
        ) is False
