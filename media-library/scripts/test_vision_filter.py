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


def test_encode_image_resizes_large_image(tmp_path):
    import base64
    import io
    from PIL import Image

    img_path = tmp_path / "big.png"
    Image.new("RGBA", (2000, 1000), (255, 120, 80, 255)).save(img_path)

    data_url = vf.encode_image_base64(str(img_path), max_side=768)
    assert data_url.startswith("data:image/jpeg;base64,")

    raw = base64.b64decode(data_url.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as out_im:
        assert max(out_im.size) == 768
        assert out_im.size == (768, 384)


def test_encode_video_frames_triplet_and_fallback(tmp_path, monkeypatch):
    import base64
    import io
    import subprocess
    from PIL import Image

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-mp4")

    # 用 mock ffprobe + ffmpeg：每次 ffmpeg 输出一张 160x120 帧图
    def fake_run(cmd, **kwargs):
        exe = cmd[0]
        if exe == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout="10.0\n", stderr="")
        if exe == "ffmpeg":
            out_file = cmd[-1]
            Image.new("RGB", (320, 240), (100, 150, 200)).save(out_file)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(vf.subprocess, "run", fake_run)
    data_url = vf.encode_video_frames_base64(str(video_path))
    assert data_url.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as stitched:
        # 3 帧横向拼接，高度统一为 360 -> 每帧 480x360，拼接后 1440x360，再限制长边 <= 1024
        assert stitched.width <= 1024
        assert stitched.width > stitched.height

    # 探测失败时降级抽首帧
    def fake_run_fallback(cmd, **kwargs):
        exe = cmd[0]
        if exe == "ffprobe":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="err")
        if exe == "ffmpeg":
            out_file = cmd[-1]
            Image.new("RGB", (400, 300), (50, 50, 50)).save(out_file)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(vf.subprocess, "run", fake_run_fallback)
    fallback_url = vf.encode_video_frames_base64(str(video_path))
    assert fallback_url.startswith("data:image/jpeg;base64,")

