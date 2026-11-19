import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vision_filter as vf


def test_load_config_prefers_env_over_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "vision_config.json"
    cfg_file.write_text(json.dumps({
        "enabled": True,
        "base_url": "https://file.example.com",
        "api_key": "file-key",
        "model": "file-model",
        "timeout": 20,
    }), encoding="utf-8")

    monkeypatch.setenv("X_VISION_API_KEY", "env-key")
    monkeypatch.setenv("X_VISION_TIMEOUT", "60")
    monkeypatch.delenv("X_VISION_ENABLED", raising=False)

    cfg = vf.load_config(str(tmp_path))
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "https://file.example.com"
    assert cfg["api_key"] == "env-key"
    assert cfg["model"] == "file-model"
    assert cfg["timeout"] == 60


@pytest.mark.parametrize("raw,expected_keep,expected_title,expected_tags", [
    (
        '{"keep": true, "reason": "单人女性", "title": "海边白裙少女写真", "tags": ["海边", "连衣裙", "海边", "清纯"]}',
        True,
        "海边白裙少女写真",
        ["海边", "连衣裙", "清纯"],
    ),
    (
        '<think>分析画面中是一名女性...</think>\n```json\n{"keep": true, "reason": "ok", "title": " 室内温柔自拍 ", "tags": ["自拍", "室内", ""]}\n```',
        True,
        "室内温柔自拍",
        ["自拍", "室内"],
    ),
    (
        '{"keep": false, "reason": "纯风景照", "title": "", "tags": []}',
        False,
        "",
        [],
    ),
])
def test_parse_vision_response_valid(raw, expected_keep, expected_title, expected_tags):
    res = vf.parse_vision_response(raw)
    assert res["keep"] is expected_keep
    assert res["title"] == expected_title
    assert res["tags"] == expected_tags


@pytest.mark.parametrize("raw", [
    "",
    "not json",
    '{"keep": "yes", "title": "abc"}',
    '{"reason": "missing keep"}',
])
def test_parse_vision_response_invalid_raises(raw):
    with pytest.raises(vf.VisionError):
        vf.parse_vision_response(raw)
