#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出与 SEO 单元测试（REQ-V2-20 C-13 / E-19）"""

import io
import json
import os
import sys
import tempfile
import zipfile

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import export_seo


@pytest.fixture()
def files_dir():
    d = tempfile.mkdtemp()
    for name, size, color in [
        ("a.jpg", (1600, 1200), (200, 120, 90)),
        ("b.png", (800, 800), (90, 120, 200)),
    ]:
        Image.new("RGB", size, color).save(os.path.join(d, name))
    return d


def make_item(**kw):
    base = {
        "id": "abcdef1234567890",
        "file": "a.jpg",
        "name": "a.jpg",
        "title": "Sunset Coast",
        "author": "Linda",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "copyright_holder": "Linda Studio",
        "commercial_ok": 1,
        "kind": "image",
        "width": 1600,
        "height": 1200,
        "duration": 0,
        "ts": 1700000000,
        "updated_at": 1700000000,
        "dominant_color": "#20180f",
        "tags": ["海", "风景"],
        "slug": "sunset-coast",
    }
    base.update(kw)
    return base


# ---------- C-13 导出 ----------


def test_render_variant_resizes_to_preset(files_dir):
    data, ext = export_seo.render_variant(files_dir, make_item(), preset="640", fmt="jpeg")
    im = Image.open(io.BytesIO(data))
    assert max(im.size) == 640
    assert ext == "jpg"


def test_render_variant_original_passthrough_bytes(files_dir):
    """原图 + 同格式：直接返回原字节，不重编码。"""
    src = os.path.join(files_dir, "a.jpg")
    with open(src, "rb") as fh:
        raw = fh.read()
    data, _ = export_seo.render_variant(files_dir, make_item(), preset="original", fmt="jpeg")
    assert data == raw


def test_render_variant_strips_gps_exif(files_dir):
    """导出副本剥离 GPS；原图字节不变（C-11 验收）。"""
    from PIL import Image as PILImage

    path = os.path.join(files_dir, "geo.jpg")
    im = PILImage.new("RGB", (400, 300), (10, 20, 30))
    # 写入 GPS（0x8825）与机型（0x0110）
    exif = im.getexif()
    exif[0x0110] = "SecretCam"
    exif[0x8825] = {1: "N", 2: (39, 54, 0)}
    im.save(path, exif=exif)
    with open(path, "rb") as fh:
        before = fh.read()

    data, _ = export_seo.render_variant(
        files_dir, make_item(file="geo.jpg", name="geo.jpg"), preset="640", fmt="jpeg"
    )
    out = Image.open(io.BytesIO(data))
    out_exif = out.getexif()
    assert 0x8825 not in out_exif
    assert out_exif.get(0x0110) in (None, "")

    with open(path, "rb") as fh:
        assert fh.read() == before  # 原图未改


def test_zip_contains_credits_and_metadata(files_dir):
    items = [make_item(), make_item(id="bbb", file="b.png", name="b.png", title="Blue")]
    data = export_seo.build_zip_memory(files_dir, items, base_url="http://nas:18100")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "credits.txt" in names
        assert "metadata.json" in names
        credits = zf.read("credits.txt").decode()
        assert "Sunset Coast" in credits
        assert "CC-BY-4.0" in credits
        assert "Linda" in credits
        assert "http://nas:18100/a/" in credits
        meta = json.loads(zf.read("metadata.json"))
        assert meta["count"] == 2


def test_zip_survives_missing_file(files_dir):
    """单条缺失不中断整包，其余条目仍打包。"""
    items = [make_item(), make_item(id="ccc", file="missing.jpg", name="missing.jpg")]
    data = export_seo.build_zip_memory(files_dir, items)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert any(n.endswith("a.jpg") for n in zf.namelist())


def test_needs_async_thresholds():
    assert export_seo.needs_async([make_item()] * 20, 1024) is False
    assert export_seo.needs_async([make_item()] * 21, 1024) is True
    assert export_seo.needs_async([make_item()], 201 * 1024 * 1024) is True


# ---------- E-19 slug / SEO ----------


def test_slug_from_ascii_title():
    assert export_seo.build_slug("Sunset  Coast!", "abcdef1234") == "sunset-coast"


def test_slug_collision_appends_suffix():
    existing = ["sunset-coast"]
    s = export_seo.build_slug("Sunset Coast", "abcdef1234567890", existing)
    assert s != "sunset-coast"
    assert s.startswith("sunset-coast")


def test_slug_chinese_falls_back_to_asset():
    """无拼音表时中文标题退化为 asset，但路径仍由 shortId 保证唯一。"""
    s = export_seo.build_slug("日落海岸", "abcdef1234567890")
    assert s == "asset"
    assert export_seo.asset_path(s, "abcdef1234567890") == "/a/asset-abcdef12"


def test_jsonld_imageobject():
    ld = export_seo.jsonld_for_item(make_item(), base_url="http://nas:18100")
    assert ld["@type"] == "ImageObject"
    assert ld["name"] == "Sunset Coast"
    assert ld["creator"]["name"] == "Linda"
    assert ld["license"].startswith("https://creativecommons.org")
    assert ld["contentUrl"].endswith("/f/a.jpg")
    assert ld["mainEntityOfPage"]["@type"] == "BreadcrumbList"


def test_jsonld_videoobject_has_duration():
    ld = export_seo.jsonld_for_item(
        make_item(kind="video", duration=12.4, file="v.mp4"), base_url="http://nas"
    )
    assert ld["@type"] == "VideoObject"
    assert ld["duration"] == "PT12S"


def test_sitemap_counts_match_items():
    items = [make_item(), make_item(id="bbb")]
    xml = export_seo.sitemap_xml(items, base_url="http://nas:18100")
    assert xml.count("<loc>") == 2 + len(items)  # 两个固定页 + 每个资产一页
    assert "/a/sunset-coast-abcdef12" in xml


def test_robots_points_to_sitemap():
    txt = export_seo.robots_txt("http://nas:18100")
    assert "Sitemap: http://nas:18100/sitemap.xml" in txt
