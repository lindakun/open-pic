#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 自动打标测试（REQ-V2-20 B-07）

关键约束：
  - 默认关闭（外部 API 有成本），未开启时任务 skipped 而非 failed
  - provider 未配置时同样 skipped，不影响入库
  - 人工否决过的标签不再写入
"""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_provider
import tasks as tasks_mod
from db import MediaDB


class FakeProvider(ai_provider.BaseProvider):
    name = "fake"
    embed_model = "fake-v1"

    def __init__(self, tags=None):
        self._tags = tags or ["极简", "特写", "室内", "夜景", "冷色"]

    def available(self) -> bool:
        return True

    def tag_image(self, image_bytes, hint=""):
        return {
            "style": "极简",
            "shot": "特写",
            "scene": "室内",
            "time": "夜景",
            "color": "冷色",
            "tags": self._tags,
            "description": "室内冷色特写",
        }


class StubTaskManager(tasks_mod.TaskManager):
    """只测打标逻辑，不启动工作线程。"""

    def __init__(self, db, data_dir, provider=None):
        super().__init__(db=db, data_dir=data_dir, scripts_dir=".", port=0)
        self._captured = []
        self.provider_factory = (lambda: provider) if provider else (lambda: ai_provider.get_provider())

    def _update(self, job_id, status, progress, message, result=None):
        self._captured.append(
            {"status": status, "message": message, "result": result or {}}
        )

    def broadcast(self, *a, **kw):
        pass


@pytest.fixture()
def env(tmp_path):
    data_dir = tmp_path
    (data_dir / "files").mkdir()
    (data_dir / "thumbs").mkdir()
    db = MediaDB(str(data_dir / "media.db"))
    iid = "aaaaaa11" + "0" * 8
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (100, 80), (10, 20, 30)).save(str(data_dir / "files" / f"{iid}.jpg"))
    db.upsert_item({
        "id": iid, "file": f"{iid}.jpg", "kind": "image", "ext": ".jpg",
        "name": "a.jpg", "title": "测试图", "size": 100, "width": 100,
        "height": 80, "ts": int(time.time()),
    })
    return db, str(data_dir), iid


def test_autotag_disabled_by_default(env, monkeypatch):
    """默认不开自动打标：任务 skipped，不产生 API 调用。"""
    db, data_dir, iid = env
    monkeypatch.delenv("MEDIA_LIB_AI_AUTOTAG", raising=False)
    tm = StubTaskManager(db, data_dir, provider=FakeProvider())
    tm._handle_ai_tagging(1, {"item_id": iid})

    assert tm._captured[-1]["status"] == "skipped"
    assert "未开启" in tm._captured[-1]["message"]
    assert not db.get_item(iid)["tags"]


def test_autotag_skipped_when_provider_missing(env, monkeypatch):
    db, data_dir, iid = env
    monkeypatch.setenv("MEDIA_LIB_AI_AUTOTAG", "1")
    tm = StubTaskManager(db, data_dir, provider=ai_provider.NoneProvider())
    tm._handle_ai_tagging(1, {"item_id": iid})

    assert tm._captured[-1]["status"] == "skipped"
    assert "未配置" in tm._captured[-1]["message"]


def test_autotag_writes_structured_and_free_tags(env, monkeypatch):
    db, data_dir, iid = env
    monkeypatch.setenv("MEDIA_LIB_AI_AUTOTAG", "1")
    tm = StubTaskManager(db, data_dir, provider=FakeProvider())
    tm._handle_ai_tagging(1, {"item_id": iid})

    assert tm._captured[-1]["status"] == "done"
    tags = db.get_item(iid)["tags"]
    # 自由标签 + 结构化字段（风格/景别/场景/时段/主色）都进入标签
    for t in ["极简", "特写", "室内", "夜景", "冷色"]:
        assert t in tags
    # 去重：结构化字段与自由标签重叠时不重复
    assert len(tags) == len(set(tags))


def test_autotag_respects_rejections(env, monkeypatch):
    """人工否决过的标签不再写入（B-07 验收 3）。"""
    db, data_dir, iid = env
    monkeypatch.setenv("MEDIA_LIB_AI_AUTOTAG", "1")
    db.add_rejected_tags(iid, ["极简", "夜景"])

    tm = StubTaskManager(db, data_dir, provider=FakeProvider())
    tm._handle_ai_tagging(1, {"item_id": iid})

    tags = db.get_item(iid)["tags"]
    assert "极简" not in tags
    assert "夜景" not in tags
    assert "特写" in tags


def test_autotag_skips_video(env, monkeypatch):
    db, data_dir, iid = env
    monkeypatch.setenv("MEDIA_LIB_AI_AUTOTAG", "1")
    vid = "bbbbbb22" + "0" * 8
    db.upsert_item({
        "id": vid, "file": "v.mp4", "kind": "video", "ext": ".mp4",
        "name": "v.mp4", "title": "视频", "size": 1, "width": 1, "height": 1,
        "ts": int(time.time()),
    })
    tm = StubTaskManager(db, data_dir, provider=FakeProvider())
    tm._handle_ai_tagging(1, {"item_id": vid})
    assert tm._captured[-1]["status"] == "skipped"
    assert "仅对图片" in tm._captured[-1]["message"]


def test_autotag_failure_marked_failed(env, monkeypatch):
    db, data_dir, iid = env
    monkeypatch.setenv("MEDIA_LIB_AI_AUTOTAG", "1")

    class Boom(ai_provider.BaseProvider):
        name = "boom"
        def available(self): return True
        def tag_image(self, b, hint=""): raise RuntimeError("api down")

    tm = StubTaskManager(db, data_dir, provider=Boom())
    tm._handle_ai_tagging(1, {"item_id": iid})
    assert tm._captured[-1]["status"] == "failed"
    assert "api down" in tm._captured[-1]["message"]


def test_tag_endpoint_501_when_unconfigured(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    monkeypatch.delenv("MEDIA_LIB_AI_PROVIDER", raising=False)
    app = server.create_app(data_dir=tempfile.mkdtemp(), port=18290, start_workers=False)
    client = TestClient(app)

    r = client.post("/api/ai/tag", json={"item_id": "abc123"})
    assert r.status_code == 501
