import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as db_mod
import library_postprocess as lp


def _make_item(db, item_id, *, kind="image", title="old title", width=1000, height=1000,
               size=100000, duration=0.0, phash="", tags=None, ts=1000):
    rel_file = f"{item_id}.{'mp4' if kind == 'video' else 'jpg'}"
    db.upsert_item({
        "id": item_id,
        "file": rel_file,
        "kind": kind,
        "ext": ".mp4" if kind == "video" else ".jpg",
        "name": rel_file,
        "title": title,
        "source": "https://x.com/demo",
        "source_platform": "X",
        "size": size,
        "width": width,
        "height": height,
        "aspect_ratio": round(width / max(1, height), 3),
        "duration": duration,
        "phash": phash,
        "ts": ts,
        "updated_at": ts,
        "tags": tags or ["X抓取", "人物"],
    })
    return rel_file


@pytest.fixture()
def env_db(tmp_path, monkeypatch):
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    database = db_mod.MediaDB(str(tmp_path / "media.db"))
    monkeypatch.setattr(lp, "DATA", str(tmp_path))
    monkeypatch.setattr(lp, "LOG_PATH", str(tmp_path / "postprocess.log"))
    monkeypatch.setattr(lp, "log", lambda *a, **kw: None)
    return tmp_path, files_dir, database


def test_backfill_missing_video_phash(env_db, monkeypatch):
    tmp_path, files_dir, database = env_db
    f1 = _make_item(database, "vid1", kind="video", duration=5.0, phash="")
    f2 = _make_item(database, "vid2", kind="video", duration=5.0, phash="0f0f0f0f0f0f0f0f")
    (files_dir / f1).write_bytes(b"v1")
    (files_dir / f2).write_bytes(b"v2")

    called = []
    monkeypatch.setattr(lp, "compute_video_dhash", lambda path, dur=0.0: called.append(path) or "aaaaaaaaaaaaaaaa")

    n = lp.backfill_missing_phashes(database, str(tmp_path), dry_run=False)
    assert n == 1
    assert len(called) == 1
    assert database.get_item("vid1")["phash"] == "aaaaaaaaaaaaaaaa"
    assert database.get_item("vid2")["phash"] == "0f0f0f0f0f0f0f0f"


def test_dedup_images_keeps_highest_resolution_and_merges_tags(env_db):
    tmp_path, _, database = env_db
    # low_res 早入库但像素低；high_res 后入库但像素高
    _make_item(database, "low1", width=900, height=1200, size=80000, phash="ffffffffffffffff", tags=["X抓取", "旧标签"], ts=100)
    _make_item(database, "high1", width=2000, height=2666, size=300000, phash="fffffffffffffffe", tags=["X抓取", "人物"], ts=200)
    _make_item(database, "other1", width=1080, height=1080, size=120000, phash="0000000000000000", tags=["X抓取"], ts=300)

    removed = lp.deduplicate_items(database, max_dist=4, dry_run=False)
    assert removed == 1
    assert database.get_item("low1")["deleted_at"] is not None
    kept = database.get_item("high1")
    assert kept["deleted_at"] is None
    assert set(kept["tags"]) == {"X抓取", "人物", "旧标签"}
    assert database.get_item("other1")["deleted_at"] is None


def test_dedup_videos_respects_duration_diff(env_db):
    _, _, database = env_db
    _make_item(database, "va", kind="video", width=720, height=1280, duration=10.0, phash="1111111111111111", ts=100)
    _make_item(database, "vb", kind="video", width=1080, height=1920, duration=10.8, phash="1111111111111111", ts=200)
    _make_item(database, "vc", kind="video", width=720, height=1280, duration=25.0, phash="1111111111111111", ts=300)

    removed = lp.deduplicate_items(database, max_dist=4, dry_run=False)
    assert removed == 1
    assert database.get_item("va")["deleted_at"] is not None
    assert database.get_item("vb")["deleted_at"] is None
    assert database.get_item("vc")["deleted_at"] is None


def test_vision_backfill_updates_rejects_and_retries_on_error(env_db, monkeypatch):
    tmp_path, files_dir, database = env_db
    for item_id, tags in [
        ("done1", ["X抓取", "AI已标注"]),
        ("keep1", ["X抓取", "人物"]),
        ("drop1", ["X抓取", "人物"]),
        ("err1", ["X抓取", "人物"]),
    ]:
        f = _make_item(database, item_id, title=f"@demo {item_id}", tags=tags, phash="abcd" * 4)
        (files_dir / f).write_bytes(b"img")

    calls = []

    def fake_analyze(path, kind, cfg):
        name = Path(path).stem
        calls.append(name)
        if name == "keep1":
            return {"keep": True, "reason": "女性写真", "title": "海边白裙少女写真", "tags": ["海边", "白裙", "人物"]}
        if name == "drop1":
            return {"keep": False, "reason": "纯文字截图", "title": "", "tags": []}
        raise lp.vision_filter.VisionError("timeout")

    monkeypatch.setattr(lp.vision_filter, "analyze_media", fake_analyze)

    cfg = {"enabled": True, "api_key": "test-key"}
    res = lp.backfill_vision_metadata(database, str(tmp_path), cfg, batch=10, dry_run=False)
    assert "done1" not in calls
    assert res == {"processed": 3, "updated": 1, "rejected": 1, "failed": 1}

    k = database.get_item("keep1")
    assert k["title"] == "海边白裙少女写真"
    assert k["deleted_at"] is None
    assert set(k["tags"]) == {"X抓取", "人物", "海边", "白裙", "AI已标注"}

    d = database.get_item("drop1")
    assert d["deleted_at"] is not None
    assert "AI已标注" in d["tags"]

    e = database.get_item("err1")
    assert e["deleted_at"] is None
    assert "AI已标注" not in e["tags"]


def test_dry_run_makes_no_changes_and_skips_api(env_db, monkeypatch):
    tmp_path, files_dir, database = env_db
    f1 = _make_item(database, "d1", width=900, height=1200, phash="aaaa" * 4, tags=["X抓取"])
    f2 = _make_item(database, "d2", width=1800, height=2400, phash="aaaa" * 4, tags=["X抓取"])
    (files_dir / f1).write_bytes(b"1")
    (files_dir / f2).write_bytes(b"2")

    monkeypatch.setattr(lp.vision_filter, "analyze_media", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call")))

    removed = lp.deduplicate_items(database, max_dist=4, dry_run=True)
    res = lp.backfill_vision_metadata(database, str(tmp_path), {"enabled": True, "api_key": "k"}, batch=10, dry_run=True)
    assert removed == 1
    assert res["processed"] == 2
    assert database.get_item("d1")["deleted_at"] is None
    assert database.get_item("d2")["title"] == "old title"
