#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能预算检查（REQ-V2-20 D-18 性能侧）

设计取舍：
  内网单用户场景下，RUM 分位数看板的 ROI 很低（审核意见），
  因此不建看板，改为一个可 CI 化的脚本：给定构建产物与页面，
  实测首包体积、静态资源总量与关键接口耗时，超出预算即退出码非 0。

用法：
  python3 scripts/perf_report.py --base http://192.168.31.188:18100
  python3 scripts/perf_report.py --base http://127.0.0.1:18100 --json
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import gzip
import io


# 预算（D-18）：JS 首包 gzip ≤ 120KB，接口 P95 预算见各项
BUDGET = {
    "js_first_gzip_kb": 120,
    "assets_total_gzip_kb": 400,
    "api_items_ms": 300,
    "api_facets_ms": 200,
    "api_item_ms": 120,
}


def fetch(url: str, timeout: float = 10.0):
    """返回 (status, body_bytes, elapsed_ms, headers)"""
    start = time.time()
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            elapsed = (time.time() - start) * 1000
            headers = dict(resp.headers)
            # 服务端可能已 gzip；这里只关心线上实际传输体积
            return resp.status, raw, elapsed, headers
    except urllib.error.HTTPError as e:
        return e.code, b"", (time.time() - start) * 1000, {}
    except Exception as e:
        return 0, str(e).encode(), (time.time() - start) * 1000, {}


def gzip_size(data: bytes) -> int:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        gz.write(data)
    return len(buf.getvalue())


def parse_entry_assets(html: str) -> list[str]:
    """从外壳 HTML 提取入口 JS/CSS 资源路径。"""
    out = []
    for token in ("src=\"", "href=\""):
        idx = 0
        while True:
            i = html.find(token, idx)
            if i < 0:
                break
            start = i + len(token)
            end = html.find('"', start)
            path = html[start:end]
            idx = end
            if path.startswith("/") and (path.endswith(".js") or path.endswith(".css")):
                out.append(path)
    return sorted(set(out))


def check(base: str) -> dict:
    base = base.rstrip("/")
    report: dict = {"base": base, "checks": [], "ok": True}

    def add(name: str, value, budget, unit: str = ""):
        passed = value <= budget if isinstance(value, (int, float)) else False
        report["checks"].append({
            "name": name, "value": value, "budget": budget,
            "unit": unit, "passed": passed,
        })
        if not passed:
            report["ok"] = False

    # 1. 前端外壳与首包体积
    status, body, ms, headers = fetch(f"{base}/app/")
    if status != 200:
        report["checks"].append({"name": "app_shell", "value": status, "budget": 200,
                                 "unit": "", "passed": False})
        report["ok"] = False
        return report
    html = body.decode("utf-8", "replace")
    assets = parse_entry_assets(html)

    js_total = 0
    css_total = 0
    # 同一资源可能被多个入口引用，按路径去重，避免重复累加（实测踩到）
    for path in dict.fromkeys(assets):
        st, data, _, hdr = fetch(f"{base}{path}")
        if st != 200:
            continue
        # 若服务端未压缩，按本地 gzip 估算
        enc = (hdr.get("Content-Encoding") or "").lower()
        size = len(data) if "gzip" in enc else gzip_size(data)
        if path.endswith(".js"):
            js_total += size
        else:
            css_total += size

    add("js_first_gzip_kb", round(js_total / 1024, 1), BUDGET["js_first_gzip_kb"], "KB")
    add("assets_total_gzip_kb", round((js_total + css_total) / 1024, 1),
        BUDGET["assets_total_gzip_kb"], "KB")

    # 2. 关键接口耗时（单次采样，内网环境下足以暴露退化）
    for name, path in (
        ("api_items_ms", "/api/items?limit=48"),
        ("api_facets_ms", "/api/facets"),
        ("api_item_ms", "/api/stats"),
    ):
        st, _, elapsed, _ = fetch(f"{base}{path}")
        if st != 200:
            report["checks"].append({"name": name, "value": st, "budget": 200,
                                     "unit": "", "passed": False})
            report["ok"] = False
            continue
        add(name, round(elapsed, 1), BUDGET[name], "ms")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="MediaLib 性能预算检查（D-18）")
    ap.add_argument("--base", default="http://127.0.0.1:18100", help="站点基址")
    ap.add_argument("--json", action="store_true", help="仅输出 JSON")
    ap.add_argument("--metrics", action="store_true",
                    help="附带输出已上报性能指标的 P50/P75/P95（需前端开关开启过）")
    args = ap.parse_args()

    report = check(args.base)
    if args.metrics:
        st, body, _, _ = fetch(f"{args.base}/api/metrics/summary?days=7")
        if st == 200:
            try:
                report["metrics"] = json.loads(body).get("summary", [])
            except Exception:
                report["metrics"] = []
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"性能预算检查：{report['base']}")
        print("-" * 56)
        for c in report["checks"]:
            mark = "✓" if c["passed"] else "✗"
            print(f"{mark} {c['name']:<24} {c['value']:>10} / {c['budget']} {c['unit']}")
        print("-" * 56)
        metrics = report.get("metrics") or []
        if metrics:
            print("实测指标（近 7 日）：")
            for m in metrics:
                print(f"  {m['name']:<10} n={m['count']:<5} "
                      f"p50={m['p50']} p75={m['p75']} p95={m['p95']}")
            print("-" * 56)
        print("结论：" + ("全部达标" if report["ok"] else "存在超出预算项"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
