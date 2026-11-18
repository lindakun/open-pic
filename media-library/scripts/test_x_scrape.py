import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture()
def scraper(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("x_scrape", Path(__file__).with_name("x_scrape.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DATA", str(tmp_path))
    monkeypatch.setattr(module, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(module, "LOG_PATH", str(tmp_path / "scrape.log"))
    monkeypatch.setattr(module, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "proxy_alive", lambda: True)
    monkeypatch.setattr(module, "api_ok", lambda: True)
    yield module
    if module.log_fp:
        module.log_fp.close()


def photo(tid="101", index=1, width=1080, height=1439):
    return {
        "type": "photo",
        "expanded_url": f"https://x.com/demo/status/{tid}/photo/{index}",
        "media_url_https": f"https://pbs.twimg.com/media/{tid}_{index}.jpg",
        "original_info": {"width": width, "height": height},
    }


def entry(tid="101", media=None):
    return {
        "tweet_id": tid,
        "is_retweet": False,
        "source_id": tid,
        "media": [photo(tid)] if media is None else media,
    }


def timeline(entries):
    payload = [
        {"entry_id": "tweet-" + e["tweet_id"], "rest_id": "999", "media_entities2": e["media"]}
        for e in entries
    ]
    raw = json.dumps(payload, separators=(",", ":")).replace('"', '\\"')
    return (" " * 5500 + raw).encode()


def stats():
    return dict.fromkeys(("accounts", "scanned", "new", "skip_dup", "skip_big", "skip_small", "fail", "no_new", "bytes"), 0)


def args(**kwargs):
    return SimpleNamespace(**{"limit": 4, "max_mb": 30, "timeout": 5, "tags": ["X抓取", "人物"], **kwargs})


def mock_timeline(scraper, monkeypatch, entries):
    monkeypatch.setattr(scraper, "http_get", lambda *a, **kw: (timeline(entries), "text/html", "https://x.com/demo"))


def test_parse_original_and_retweet(scraper):
    raw = timeline([entry("101"), entry("102", [photo("88", 1), photo("88", 2)])])
    parsed = scraper.parse_timeline(raw.decode())
    assert [(e["tweet_id"], e["source_id"], e["is_retweet"]) for e in parsed] == [
        ("101", "101", False), ("102", "88", True),
    ]
    assert len(parsed[1]["media"]) == 2


@pytest.mark.parametrize("html", ["", "<html></html>", '"entry_id":"tweet-101","media_entities2":[{'])
def test_parse_invalid_page(scraper, html):
    assert scraper.parse_timeline(html) == []


def test_balanced_arrays_ignore_brackets_in_strings(scraper):
    value = '[{"alt":"a ] and [ character","nested":[1,2]}]'
    assert scraper._extract_balanced(value + " trailing", 0) == len(value)


def test_best_mp4_ignores_hls(scraper):
    variants = [
        {"content_type": "application/x-mpegURL", "url": "stream.m3u8", "bitrate": 999999},
        {"content_type": "video/mp4", "url": "low.mp4", "bitrate": 100},
        {"content_type": "video/mp4", "url": "high.mp4", "bitrate": 200},
    ]
    assert scraper.pick_best_mp4(variants)["url"] == "high.mp4"
    assert scraper.pick_best_mp4(variants[:1]) is None


def test_media_original_size_and_small_filter(scraper):
    images = [photo(width=200), photo(index=2)]
    images[1]["media_url_https"] += "?format=jpg"
    items = scraper.media_items(entry(media=images))
    assert items[0]["skip_reason"]
    assert items[1]["skip_reason"] == ""
    assert items[1]["url"].endswith("?format=jpg&name=orig")


def test_oversized_video_is_skipped_before_download(scraper):
    video = {
        "type": "video",
        "video_info": {"duration_millis": 60000, "variants": [
            {"content_type": "video/mp4", "url": "https://video.twimg.com/test.mp4", "bitrate": 10000000},
        ]},
    }
    assert scraper.media_items(entry(media=[video]), max_mb=30)[0]["skip_reason"]


def test_twenty_to_sixty_kb_original_is_accepted(scraper, tmp_path):
    from PIL import Image
    path = tmp_path / "image.jpg"
    Image.new("RGB", (1080, 1439)).save(path)
    with path.open("ab") as f:
        f.write(b"\0" * max(0, 30000 - path.stat().st_size))
    assert 20 * 1024 < path.stat().st_size < 60 * 1024
    assert scraper.verify_image(str(path))[0] is True


def test_tweet_limit_does_not_drop_remaining_media(scraper, monkeypatch):
    mock_timeline(scraper, monkeypatch, [entry("101", [photo("101", 1), photo("101", 2)]), entry("102")])
    downloaded = []
    monkeypatch.setattr(scraper, "download_and_store", lambda it, *a: downloaded.append(it["name"]) or True)
    state = {"accounts": {}, "cursor": 0}
    scraper.scrape_account("demo", state, args(limit=1), stats())
    assert len(downloaded) == 2
    assert scraper.seen_set(state, "demo") == {"101"}
    assert scraper.seen_set(scraper.load_state(), "demo") == {"101"}


def test_failed_tweet_is_retryable_and_still_counts_toward_limit(scraper, monkeypatch):
    mock_timeline(scraper, monkeypatch, [entry("101"), entry("102")])
    downloaded = []
    monkeypatch.setattr(scraper, "download_and_store", lambda it, *a: downloaded.append(it["name"]) or False)
    state = {"accounts": {}, "cursor": 0}
    scraper.scrape_account("demo", state, args(limit=1), stats())
    assert len(downloaded) == 1
    assert scraper.seen_set(state, "demo") == set()


def test_partially_failed_tweet_not_marked_seen(scraper, monkeypatch):
    mock_timeline(scraper, monkeypatch, [entry("101", [photo("101", 1), photo("101", 2)])])
    outcomes = iter([True, False])
    monkeypatch.setattr(scraper, "download_and_store", lambda *a: next(outcomes))
    state = {"accounts": {}, "cursor": 0}
    scraper.scrape_account("demo", state, args(), stats())
    assert scraper.seen_set(state, "demo") == set()


@pytest.mark.parametrize("already_seen", [False, True])
def test_dry_run_does_not_change_seen_or_last_run(scraper, monkeypatch, already_seen):
    mock_timeline(scraper, monkeypatch, [entry("101")])
    monkeypatch.setattr(scraper, "download_and_store", lambda *a: pytest.fail("dry-run downloaded media"))
    state = {"accounts": {"demo": {"seen_tweets": ["101"] if already_seen else [], "last_run": 123}}, "cursor": 19}
    before = copy.deepcopy(state)
    scraper.scrape_account("demo", state, args(), stats(), dry_run=True)
    assert state == before
    assert not Path(scraper.STATE_PATH).exists()


@pytest.mark.parametrize("response,success,counter", [
    ({"id": "abc"}, True, "new"),
    ({"id": "abc", "duplicate": True}, True, "skip_dup"),
    ({"error": "upload failed"}, False, "fail"),
])
def test_download_upload_and_cleanup(scraper, monkeypatch, tmp_path, response, success, counter):
    download = tmp_path / "download"
    download.mkdir()
    monkeypatch.setattr(scraper.tempfile, "mkdtemp", lambda **kw: str(download))
    monkeypatch.setattr(scraper, "http_get", lambda *a, **kw: (b"image", "image/jpeg", ""))
    monkeypatch.setattr(scraper, "verify_image", lambda path: (True, "1080x1439"))
    uploaded = []

    def upload(path, name, tags, **kwargs):
        assert Path(path).read_bytes() == b"image"
        uploaded.append((name, tags, kwargs))
        return response

    monkeypatch.setattr(scraper, "upload", upload)
    result = stats()
    tweet = entry()
    item = scraper.media_items(tweet)[0]
    assert scraper.download_and_store(item, tweet, "demo", args(), result) is success
    assert result[counter] == 1
    assert len(uploaded) == 1
    assert not download.exists()


def test_seen_state_merges_existing_ids(scraper):
    state = {"accounts": {"demo": {"seen_tweets": ["99"], "last_run": 0}}, "cursor": 19}
    scraper.mark_seen(state, "demo", ["102", "101", "99"])
    scraper.save_state(state)
    assert scraper.load_state()["accounts"]["demo"]["seen_tweets"] == ["99", "101", "102"]
    assert scraper.load_state()["cursor"] == 19


def test_corrupt_state_does_not_reset_deduplication(scraper):
    path = Path(scraper.STATE_PATH)
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        scraper.load_state()
    assert path.read_text() == "broken"


def test_account_list_deduplicates_without_reordering(scraper, tmp_path):
    path = tmp_path / "accounts.txt"
    path.write_text("# comment\n@Demo\nother\n\nDEMO\n", encoding="utf-8")
    assert scraper.load_accounts(SimpleNamespace(file=str(path), accounts=["@third"])) == ["Demo", "other", "third"]


@pytest.mark.parametrize("account", ["../bad", "bad/name", "bad?x=1", "bad\r\nheader", "x" * 16])
def test_account_names_are_validated(scraper, account):
    with pytest.raises(ValueError):
        scraper.load_accounts(SimpleNamespace(file=None, accounts=[account]))


def test_batch_resumes_saved_cursor(scraper, monkeypatch, tmp_path):
    accounts = tmp_path / "accounts.txt"
    accounts.write_text("\n".join(f"acct{i}" for i in range(20)), encoding="utf-8")
    scraper.save_state({"accounts": {}, "cursor": 19})
    visited = []
    monkeypatch.setattr(scraper, "scrape_account", lambda account, *a, **kw: visited.append(account))
    monkeypatch.setattr(sys, "argv", ["x_scrape.py", "--file", str(accounts), "--batch", "7"])
    assert scraper.main() == 0
    assert visited == ["acct19", "acct0", "acct1", "acct2", "acct3", "acct4", "acct5"]
    assert scraper.load_state()["cursor"] == 6


def test_main_dry_run_preserves_cursor_and_log(scraper, monkeypatch):
    scraper.save_state({"accounts": {}, "cursor": 1})
    before = Path(scraper.STATE_PATH).read_bytes()
    Path(scraper.LOG_PATH).write_text("existing log", encoding="utf-8")
    monkeypatch.setattr(scraper, "api_ok", lambda: pytest.fail("dry-run checked upload service"))
    monkeypatch.setattr(scraper, "scrape_account", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["x_scrape.py", "demo", "other", "--batch", "1", "--dry-run"])
    assert scraper.main() == 0
    assert Path(scraper.STATE_PATH).read_bytes() == before
    assert Path(scraper.LOG_PATH).read_text() == "existing log"


def test_failed_scrape_returns_nonzero(scraper, monkeypatch):
    def fail(account, state, options, result, **kwargs):
        result["fail"] += 1
    monkeypatch.setattr(scraper, "scrape_account", fail)
    monkeypatch.setattr(sys, "argv", ["x_scrape.py", "demo"])
    assert scraper.main() == 1


@pytest.mark.parametrize("flag,value", [("--batch", "-1"), ("--limit", "-1"), ("--max-mb", "0"), ("--timeout", "0")])
def test_invalid_limits_rejected(scraper, monkeypatch, flag, value):
    monkeypatch.setattr(sys, "argv", ["x_scrape.py", "demo", flag, value])
    with pytest.raises(SystemExit) as error:
        scraper.main()
    assert error.value.code == 2


@pytest.fixture()
def wrapper(tmp_path):
    if os.name != "posix" or shutil.which("flock") is None:
        pytest.skip("requires Linux bash/flock")
    scripts = tmp_path / "skill with spaces" / "scripts"
    scripts.mkdir(parents=True)
    cron = scripts / "x_scrape_cron.sh"
    shutil.copyfile(Path(__file__).with_name(cron.name), cron)
    ensure = scripts / "ensure.sh"
    ensure.write_text('printf started > "$STARTED"\nexit "${ENSURE_EXIT:-0}"\n')
    python = scripts.parent / "venv" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CAPTURE"\nexit "${PYTHON_EXIT:-0}"\n')
    python.chmod(0o755)
    data = tmp_path / "data with spaces"
    data.mkdir()
    env = {**os.environ, "MEDIA_LIB_DIR": str(data), "CAPTURE": str(tmp_path / "args"), "STARTED": str(tmp_path / "started")}
    for key in list(env):
        if key.startswith("X_SCRAPE_"):
            env.pop(key)
    return cron, data, env


def run_wrapper(wrapper, *args, extra_env=None):
    cron, data, env = wrapper
    return subprocess.run(["bash", str(cron), *args], env={**env, **(extra_env or {})}, capture_output=True, text=True, timeout=10)


def test_wrapper_defaults_and_paths_with_spaces(wrapper):
    result = run_wrapper(wrapper)
    assert result.returncode == 0, result.stderr
    cron, data, env = wrapper
    captured = Path(env["CAPTURE"]).read_text().splitlines()
    assert captured == [str(cron.with_name("x_scrape.py")), "--file", str(data / "x_accounts.txt"), "--batch", "7", "--limit", "4", "--max-mb", "30", "--tags", "X抓取,人物"]
    assert Path(env["STARTED"]).exists()


def test_wrapper_dry_run_does_not_start_service(wrapper):
    result = run_wrapper(wrapper, "--dry-run")
    assert result.returncode == 0
    assert not Path(wrapper[2]["STARTED"]).exists()
    assert Path(wrapper[2]["CAPTURE"]).read_text().splitlines()[-1] == "--dry-run"


def test_wrapper_lock_prevents_overlapping_runs(wrapper):
    import fcntl
    with (wrapper[1] / "x_scrape.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_wrapper(wrapper)
    assert result.returncode == 0
    assert not Path(wrapper[2]["CAPTURE"]).exists()
    assert not Path(wrapper[2]["STARTED"]).exists()


@pytest.mark.parametrize("variable,code", [("ENSURE_EXIT", "7"), ("PYTHON_EXIT", "9")])
def test_wrapper_propagates_failure(wrapper, variable, code):
    assert run_wrapper(wrapper, extra_env={variable: code}).returncode == int(code)
