#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 7 批修复（R7）的回归测试

覆盖：
  1. 任务队列积压超 200 条时老任务不被丢弃（get_job 精确查询）
  2. /f/ 兼容播放副本路由（?play=1 → play_file）
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as srv
from tasks import TaskManager


@pytest.fixture()
def client(tmp_path):
    app = srv.create_app(data_dir=str(tmp_path), start_workers=False)
    with TestClient(app) as c:
        yield c


def test_queued_jobs_beyond_200_are_found(client):
    """批量上传会积压数百个任务；worker 必须按 id 精确取任务，
    不能靠 list_jobs(limit=200) 倒序截断翻找（会静默丢弃老任务）。"""
    tasks: TaskManager = client.app.state.tasks
    db = client.app.state.db

    # 直接向 DB 建第 1 个任务，再灌 250 条新任务把它挤出列表窗口
    old_id = db.create_job("backfill_metadata", {"manual": True})
    for _ in range(250):
        db.create_job("media_process", {"item_id": "x"})
    # list_jobs 只能看到最新 200 条，老任务不在其中
    listed_ids = {j["id"] for j in db.list_jobs(limit=200)}
    assert old_id not in listed_ids
    # 但 get_job 必须能精确找到（worker 依赖此行为）
    job = db.get_job(old_id)
    assert job is not None
    assert job["job_type"] == "backfill_metadata"
    # TaskManager._run_job 对不存在的 id 静默返回，存在的 id 进入分发
    assert job["payload"] == {"manual": True}


def test_play_param_serves_play_file(client, tmp_path):
    """?play=1 应优先返回兼容播放副本（H.264），缺失时回退原图。"""
    import io
    import shutil
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 200, 80)).save(buf, "PNG")
    buf.seek(0)
    r = client.post(
        "/api/upload",
        files={"file": ("g.png", buf, "image/png")},
        data={"synchronous": "1", "title": "play-test"},
    )
    it = r.json()["items"][0]
    iid, fname = it["id"], it["file"]

    data_dir = str(tmp_path)
    # 无播放副本：play=1 回退原图，可正常取到
    r = client.get(f"/f/{fname}", params={"play": "1"})
    assert r.status_code == 200

    # 写入一个假的播放副本并登记到 DB，再请求：应命中副本内容而非原图
    play_dir = os.path.join(data_dir, "play")
    os.makedirs(play_dir, exist_ok=True)
    with open(os.path.join(play_dir, f"{iid}.mp4"), "wb") as f:
        f.write(b"FAKE-COMPATIBLE-MP4")
    client.app.state.db.update_item(iid, {"play_file": f"{iid}.mp4"})
    r = client.get(f"/f/{fname}", params={"play": "1"})
    assert r.status_code == 200
    assert b"FAKE-COMPATIBLE-MP4" in r.content
