#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import fcntl
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as db_mod
import pipeline_config as pc
import vision_filter


def test_default_config_and_persistence(tmp_path):
    # 空目录加载返回完整默认值
    cfg = pc.load_pipeline_config(str(tmp_path))
    assert cfg["scrape"]["batch"] == 14
    assert cfg["scrape"]["limit"] == 4
    assert cfg["scrape"]["max_mb"] == 30.0
    assert cfg["scrape"]["tags"] == ["X抓取", "人物"]
    assert cfg["scrape"]["min_px"] == 320
    assert cfg["scrape"]["min_img_kb"] == 20
    assert cfg["postprocess"]["batch"] == 50
    assert cfg["postprocess"]["phash_limit"] == 50
    assert cfg["postprocess"]["max_dist"] == 4
    assert cfg["postprocess"]["ai_tag"] == "AI已标注"
    assert cfg["vision"]["enabled"] is True
    assert cfg["vision"]["model"] == vision_filter.DEFAULT_MODEL

    # 保存配置与账号白名单
    pub = pc.validate_and_save_config(
        str(tmp_path),
        {
            "scrape": {
                "batch": 20,
                "limit": 6,
                "max_mb": 45.5,
                "tags": ["X抓取", "街拍"],
                "proxy": "http://127.0.0.1:7890",
                "timeout": 40,
                "min_px": 400,
                "min_img_kb": 30,
            },
            "postprocess": {
                "batch": 30,
                "phash_limit": 80,
                "max_dist": 3,
                "ai_tag": "AI精选",
                "skip_dedup": False,
                "skip_vision": True,
            },
            "vision": {
                "enabled": True,
                "base_url": "https://api.example.com/",
                "api_key": "sk-secret123456",
                "model": "test-vision-model",
                "timeout": 60,
                "prompt": "自定义视觉审核提示词",
            },
            "accounts_text": "# 主力账号\n@User_One\nuser_two\n",
        },
    )

    assert pub["scrape"]["batch"] == 20
    assert pub["postprocess"]["ai_tag"] == "AI精选"
    assert pub["vision"]["base_url"] == "https://api.example.com"
    assert pub["vision"]["has_api_key"] is True
    assert pub["vision"]["api_key_masked"] == "sk-****3456"
    assert "api_key" not in pub["vision"]
    assert pub["accounts_list"] == ["User_One", "user_two"]
    assert pub["accounts_count"] == 2

    # 校验 vision_config.json 同步写入且可被 vision_filter.load_config 读取
    vcfg = vision_filter.load_config(str(tmp_path))
    assert vcfg["base_url"] == "https://api.example.com"
    assert vcfg["api_key"] == "sk-secret123456"
    assert vcfg["model"] == "test-vision-model"
    assert vcfg["timeout"] == 60
    assert vcfg["prompt"] == "自定义视觉审核提示词"


def test_api_key_masking_and_preservation(tmp_path):
    pc.validate_and_save_config(
        str(tmp_path),
        {"vision": {"api_key": "sk-abcdefgh9876"}},
    )
    pub1 = pc.get_public_config(str(tmp_path))
    assert pub1["vision"]["has_api_key"] is True
    assert pub1["vision"]["api_key_masked"] == "sk-****9876"
    assert "api_key" not in pub1["vision"]

    # 传空字符串保留原 Key
    pc.validate_and_save_config(
        str(tmp_path),
        {"vision": {"api_key": "", "timeout": 55}},
    )
    raw2 = pc.load_pipeline_config(str(tmp_path))
    assert raw2["vision"]["api_key"] == "sk-abcdefgh9876"
    assert raw2["vision"]["timeout"] == 55

    # 显式 clear_api_key=True 清空
    pub3 = pc.validate_and_save_config(
        str(tmp_path),
        {"vision": {"clear_api_key": True}},
    )
    assert pub3["vision"]["has_api_key"] is False
    assert pub3["vision"]["api_key_masked"] == ""
    assert pc.load_pipeline_config(str(tmp_path))["vision"]["api_key"] == ""


def test_validation_rejects_invalid_params_and_accounts(tmp_path):
    accts_file = tmp_path / "x_accounts.txt"
    accts_file.write_text("good_user\n", encoding="utf-8")

    with pytest.raises(pc.ConfigValidationError):
        pc.validate_and_save_config(str(tmp_path), {"scrape": {"batch": -1}})

    with pytest.raises(pc.ConfigValidationError):
        pc.validate_and_save_config(str(tmp_path), {"postprocess": {"max_dist": 20}})

    with pytest.raises(pc.ConfigValidationError):
        pc.validate_and_save_config(str(tmp_path), {"scrape": {"proxy": "ftp://bad"}})

    with pytest.raises(pc.ConfigValidationError) as exc_info:
        pc.validate_and_save_config(
            str(tmp_path),
            {"accounts_text": "valid_user\nbad user with spaces\n"},
        )
    assert "第 2 行" in str(exc_info.value)
    # 原账号文件未被破坏
    assert accts_file.read_text(encoding="utf-8") == "good_user\n"


def test_status_lock_detection_and_cursor_reset(tmp_path):
    db_path = tmp_path / "media.db"
    database = db_mod.MediaDB(str(db_path))
    # 写入两条测试素材：一条缺 phash，两条都未打 AI已标注
    database.upsert_item({
        "id": "item1", "file": "item1.jpg", "kind": "image", "ext": ".jpg",
        "name": "item1.jpg", "title": "t1", "phash": "", "tags": ["X抓取"], "ts": 100,
    })
    database.upsert_item({
        "id": "item2", "file": "item2.jpg", "kind": "image", "ext": ".jpg",
        "name": "item2.jpg", "title": "t2", "phash": "abcd" * 4, "tags": ["X抓取"], "ts": 200,
    })

    (tmp_path / "x_accounts.txt").write_text("acct_a\nacct_b\nacct_c\n", encoding="utf-8")
    (tmp_path / "x_scrape_state.json").write_text(
        json.dumps({
            "cursor": 2,
            "accounts": {"acct_a": {"seen_tweets": ["111", "222"], "last_run": 1700000000}},
        }),
        encoding="utf-8",
    )
    (tmp_path / "x_scrape.log").write_text("line1\nline2\n", encoding="utf-8")

    # 模拟持有 x_scrape.lock
    lock_f = open(tmp_path / "x_scrape.lock", "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        st = pc.get_pipeline_status(str(tmp_path), db=database, log_type="x_scrape", lines=50)
        assert st["scrape"]["running"] is True
        assert st["scrape"]["cursor"] == 2
        assert st["scrape"]["accounts_count"] == 3
        assert st["scrape"]["next_account"] == "acct_c"
        assert st["scrape"]["last_run_ts"] == 1700000000
        assert st["postprocess"]["running"] is False
        assert st["postprocess"]["missing_phash_count"] == 1
        assert st["postprocess"]["untagged_vision_count"] == 2
        assert "line2" in st["log"]["content"]

        # 持有锁时不允许 reset_cursor 或 run_scrape
        with pytest.raises(pc.PipelineBusyError):
            pc.reset_scrape_cursor(str(tmp_path))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

    # 释放锁后重置游标，保留 seen_tweets
    res = pc.reset_scrape_cursor(str(tmp_path))
    assert res["cursor"] == 0
    saved_state = json.loads((tmp_path / "x_scrape_state.json").read_text(encoding="utf-8"))
    assert saved_state["cursor"] == 0
    assert saved_state["accounts"]["acct_a"]["seen_tweets"] == ["111", "222"]


def test_x_scrape_priority_from_pipeline_config(tmp_path, monkeypatch):
    import x_scrape

    monkeypatch.setattr(x_scrape, "DATA", str(tmp_path))
    monkeypatch.setattr(x_scrape, "STATE_PATH", str(tmp_path / "x_scrape_state.json"))
    monkeypatch.setattr(x_scrape, "LOG_PATH", str(tmp_path / "x_scrape.log"))
    monkeypatch.setattr(x_scrape, "log", lambda *a, **kw: None)
    monkeypatch.setattr(x_scrape, "proxy_alive", lambda: True)
    monkeypatch.setattr(x_scrape, "api_ok", lambda: True)
    for k in ("X_SCRAPE_BATCH", "X_SCRAPE_LIMIT", "X_SCRAPE_MAX_MB", "X_SCRAPE_TAGS", "X_SCRAPE_PROXY"):
        monkeypatch.delenv(k, raising=False)

    accts_file = tmp_path / "x_accounts.txt"
    accts_file.write_text("u1\nu2\nu3\nu4\nu5\n", encoding="utf-8")

    pc.validate_and_save_config(
        str(tmp_path),
        {
            "scrape": {
                "batch": 2,
                "limit": 3,
                "max_mb": 18.0,
                "tags": ["定投", "人像"],
                "proxy": "http://127.0.0.1:9999",
                "timeout": 25,
                "min_px": 500,
                "min_img_kb": 40,
            },
            "vision": {"enabled": False},
        },
    )

    visited = []
    captured_args = []

    def fake_scrape(acct, st, args, stats, dry_run=False):
        visited.append(acct)
        captured_args.append(args)

    monkeypatch.setattr(x_scrape, "scrape_account", fake_scrape)

    # 1. 不传 CLI 参数时，采用 pipeline_config.json 的配置（batch=2）
    monkeypatch.setattr(sys, "argv", ["x_scrape.py", "--file", str(accts_file)])
    assert x_scrape.main() == 0
    assert visited == ["u1", "u2"]
    assert captured_args[0].limit == 3
    assert captured_args[0].max_mb == 18.0
    assert captured_args[0].tags == ["定投", "人像"]
    assert captured_args[0].timeout == 25
    assert x_scrape.MIN_PX == 500
    assert x_scrape.MIN_IMG_BYTES == 40 * 1024
    assert x_scrape.PROXY == "http://127.0.0.1:9999"

    # 2. 显式传入 CLI 参数（--batch 1 --limit 1）时覆盖配置文件
    visited.clear()
    captured_args.clear()
    monkeypatch.setattr(sys, "argv", ["x_scrape.py", "--file", str(accts_file), "--batch", "1", "--limit", "1"])
    assert x_scrape.main() == 0
    assert visited == ["u3"]
    assert captured_args[0].limit == 1


def test_postprocess_priority_from_pipeline_config(tmp_path, monkeypatch):
    import library_postprocess as lp

    monkeypatch.setattr(lp, "DATA", str(tmp_path))
    monkeypatch.setattr(lp, "LOG_PATH", str(tmp_path / "postprocess.log"))
    monkeypatch.setattr(lp, "log", lambda *a, **kw: None)
    for k in ("X_POSTPROCESS_BATCH", "X_POSTPROCESS_PHASH_LIMIT", "X_POSTPROCESS_MAX_DIST", "X_POSTPROCESS_TAG"):
        monkeypatch.delenv(k, raising=False)

    db_mod.MediaDB(str(tmp_path / "media.db"))
    pc.validate_and_save_config(
        str(tmp_path),
        {
            "postprocess": {
                "batch": 12,
                "phash_limit": 34,
                "max_dist": 6,
                "ai_tag": "自定义AI标",
                "skip_dedup": False,
                "skip_vision": False,
            },
            "vision": {"enabled": False},
        },
    )

    recorded = {}

    def fake_phash(db, data_dir, limit=50, dry_run=False):
        recorded["phash_limit"] = limit
        return 0

    def fake_dedup(db, max_dist=4, dry_run=False):
        recorded["max_dist"] = max_dist
        return 0

    def fake_vision(db, data_dir, vision_cfg, batch=15, dry_run=False, ai_tag=None):
        recorded["batch"] = batch
        recorded["ai_tag"] = ai_tag
        return {"processed": 0, "updated": 0, "rejected": 0, "failed": 0}

    monkeypatch.setattr(lp, "backfill_missing_phashes", fake_phash)
    monkeypatch.setattr(lp, "deduplicate_items", fake_dedup)
    monkeypatch.setattr(lp, "backfill_vision_metadata", fake_vision)

    # 1. 不传 CLI 参数（仅 --dry-run），采用 pipeline_config.json
    monkeypatch.setattr(sys, "argv", ["library_postprocess.py", "--dry-run"])
    assert lp.main() == 0
    assert recorded["phash_limit"] == 34
    assert recorded["max_dist"] == 6
    assert recorded["batch"] == 12
    assert recorded["ai_tag"] == "自定义AI标"

    # 2. 显式传入 CLI 参数（--batch 5 --max-dist 2）覆盖配置文件
    recorded.clear()
    monkeypatch.setattr(sys, "argv", ["library_postprocess.py", "--dry-run", "--batch", "5", "--max-dist", "2"])
    assert lp.main() == 0
    assert recorded["batch"] == 5
    assert recorded["max_dist"] == 2


def test_server_pipeline_api_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    import server

    app = server.create_app(data_dir=str(tmp_path), start_workers=False)
    client = TestClient(app)

    # 1. GET /api/pipeline/config
    r = client.get("/api/pipeline/config")
    assert r.status_code == 200
    data = r.json()
    assert data["scrape"]["batch"] == 14
    assert data["postprocess"]["batch"] == 50
    assert data["vision"]["has_api_key"] is False

    # 2. PUT /api/pipeline/config 成功更新
    r = client.put(
        "/api/pipeline/config",
        json={
            "scrape": {"batch": 16, "limit": 5, "tags": ["X抓取", "写真"]},
            "vision": {"api_key": "sk-livekey9988", "enabled": True},
            "accounts_text": "# 测试\ndemo_acct\n@second_acct\n",
        },
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["scrape"]["batch"] == 16
    assert updated["vision"]["has_api_key"] is True
    assert updated["vision"]["api_key_masked"] == "sk-****9988"
    assert updated["accounts_count"] == 2

    # 3. PUT /api/pipeline/config 非法参数返回 400
    r_bad = client.put(
        "/api/pipeline/config",
        json={"accounts_text": "bad account name!"},
    )
    assert r_bad.status_code == 400
    assert "第 1 行" in r_bad.json()["detail"]

    # 4. GET /api/pipeline/status 与锁冲突 409
    (tmp_path / "x_scrape_state.json").write_text(
        json.dumps({"cursor": 1, "accounts": {"demo_acct": {"seen_tweets": ["1"], "last_run": 123456}}}),
        encoding="utf-8",
    )
    r_st = client.get("/api/pipeline/status?log_type=x_scrape&lines=50")
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["scrape"]["cursor"] == 1
    assert st["scrape"]["next_account"] == "second_acct"

    # 模拟持有锁时触发 run_scrape 返回 409
    lock_f = open(tmp_path / "x_scrape.lock", "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        r_conflict = client.post("/api/pipeline/action", json={"action": "run_scrape"})
        assert r_conflict.status_code == 409
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

    # 5. reset_cursor 重置游标但保留 seen_tweets
    r_reset = client.post("/api/pipeline/action", json={"action": "reset_cursor"})
    assert r_reset.status_code == 200
    assert r_reset.json()["cursor"] == 0
    st_after = client.get("/api/pipeline/status").json()
    assert st_after["scrape"]["cursor"] == 0
    assert st_after["scrape"]["next_account"] == "demo_acct"


