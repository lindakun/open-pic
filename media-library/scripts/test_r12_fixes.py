#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 12 批修复（R12）的回归测试

覆盖：
  1. clean_title 不再误删域名首字符（lstrip("www.") 缺陷）
  2. 修复自检覆盖草稿/归档资产
  3. 分享页视频优先使用兼容播放副本（?play=1）
  4. 导出 PNG 保留透明通道；ZIP 条目名清洗路径穿越并正确去重
"""

import io
import os
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_seo
import media_proc
import server as srv


@pytest.fixture()
def client(tmp_path):
    app = srv.create_app(data_dir=str(tmp_path), start_workers=False)
    with TestClient(app) as c:
        yield c


def _upload_png(c: TestClient, name: str, size=(40, 30), color=(70, 100, 190)) -> dict:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    r = c.post(
        "/api/upload",
        files={"file": (f"{name}.png", buf, "image/png")},
        data={"synchronous": "1", "title": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_clean_title_keeps_domain_prefix():
    # web.com 的首字母 w 不应被 lstrip 的字符集剥掉
    title = media_proc.clean_title("tmpabcd1234", "tmpabcd1234.png", "https://web.com/a/photo.jpg")
    assert title.startswith("web.com/"), title
    # 真正的 www. 前缀仍应去掉
    title2 = media_proc.clean_title("tmpabcd1234", "tmpabcd1234.png", "https://www.example.com/a/photo.jpg")
    assert title2.startswith("example.com/"), title2


def test_repair_includes_drafts(client, tmp_path):
    it = _upload_png(client, "draft-orphan")
    client.patch(f"/api/item/{it['id']}/status", json={"status": "draft"})
    # 模拟磁盘文件丢失
    os.remove(os.path.join(str(tmp_path), "files", it["file"]))

    res = client.post("/api/storage/repair").json()
    assert res["orphans_removed"] == 1, "草稿资产未被一致性自检覆盖"


def test_share_page_video_uses_play_copy(client):
    # 快速路径上传一个视频（不生成缩略图），再补 play_file
    r = client.post(
        "/api/upload",
        files={"file": ("clip.mp4", b"not-a-real-video", "video/mp4")},
        data={"synchronous": "0", "title": "演示视频"},
    )
    assert r.status_code == 200, r.text
    it = r.json()["items"][0]
    client.app.state.db.update_item(it["id"], {"play_file": f"{it['id']}.mp4"})

    html = client.get(f"/s/{it['id']}").text
    assert "?play=1" in html, "分享页视频未使用兼容播放副本"
    assert f'<meta property="og:video" content="' in html


def _rgba_png(path: str):
    im = Image.new("RGBA", (800, 800), (200, 40, 40, 255))
    # 左半透明：留出足够面积，避免缩放插值把边缘 alpha 混合掉
    for x in range(400):
        for y in range(800):
            im.putpixel((x, y), (0, 0, 0, 0))
    im.save(path)


def test_export_png_keeps_transparency(tmp_path):
    _rgba_png(str(tmp_path / "alpha.png"))
    item = {
        "id": "aaaa1111bbbb2222", "file": "alpha.png", "name": "alpha.png",
        "title": "透明图", "kind": "image",
    }
    data, ext = export_seo.render_variant(
        str(tmp_path), item, preset="640", fmt="png"
    )
    assert ext == "png"
    out = Image.open(io.BytesIO(data))
    assert out.mode in ("RGBA", "LA", "P"), f"导出后丢失透明通道: {out.mode}"
    assert out.convert("RGBA").getpixel((10, 10))[3] == 0


def test_zip_names_are_sanitized_and_deduped(tmp_path):
    Image.new("RGB", (10, 10), (1, 2, 3)).save(tmp_path / "a.jpg")
    item = {
        "id": "cccc3333dddd4444", "file": "a.jpg",
        "name": "../../evil.jpg", "title": "evil", "kind": "image",
    }
    out = str(tmp_path / "pack.zip")
    export_seo.build_zip_to_path(
        str(tmp_path), [item, dict(item), dict(item)], out, preset="original", fmt=""
    )
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "evil.jpg" in names
    assert "evil_1.jpg" in names
    assert "evil_2.jpg" in names
    assert all(".." not in n and not n.startswith("/") for n in names)
