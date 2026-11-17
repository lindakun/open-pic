#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能预算脚本测试（REQ-V2-20 D-18）"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))

import perf_report


def test_parse_entry_assets_extracts_js_and_css():
    html = '<script src="/app/assets/index.abc.js"></script><link href="/app/assets/x.css" rel="stylesheet">'
    assets = perf_report.parse_entry_assets(html)
    assert "/app/assets/index.abc.js" in assets
    assert "/app/assets/x.css" in assets


def test_parse_entry_assets_ignores_external():
    html = '<script src="https://cdn.example.com/a.js"></script>'
    assert perf_report.parse_entry_assets(html) == []


def test_gzip_size_compresses():
    data = b"a" * 10000
    assert perf_report.gzip_size(data) < len(data)


def test_budget_report_fails_when_over(monkeypatch):
    """超预算时 report.ok 为 False（CI 依赖此语义）。"""
    def fake_fetch(url, timeout=10.0):
        if url.endswith("/app/"):
            return 200, b'<script src="/app/a.js"></script>', 1.0, {}
        # 用不可压缩数据模拟真实 JS：重复字符会被 gzip 压到极小，
        # 用伪随机字节才反映真实产物体积（实测踩到）
        import random
        random.seed(7)
        payload = bytes(random.getrandbits(8) for _ in range(200000))
        return 200, payload, 1.0, {}

    monkeypatch.setattr(perf_report, "fetch", fake_fetch)
    rep = perf_report.check("http://x")
    assert rep["ok"] is False
    js = next(c for c in rep["checks"] if c["name"] == "js_first_gzip_kb")
    assert js["passed"] is False
