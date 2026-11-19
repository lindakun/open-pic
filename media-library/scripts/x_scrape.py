#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 X（Twitter）指定账号主页抓取最新图片/视频并入库。

设计前提（务必先读）：
  * 走游客态 HTML，**不需要登录**，但**每次只能拿到最新约 5 条推文**。
    ?max_id= / ?cursor= / /with_replies 全部无效，翻不了页
    → 只能靠高频轮询 + 已见推文游标兜住。
  * **必须走住宅 IP**（家宽代理）。机房 IP（如 152）访问 x.com 一律 403。
  * 页面里媒体结构的字段名是 `media_entities2`，且整段 JSON 是**双重转义**的，
    必须先把 \\" 还原成 " 才能解析。

用法：
  python3 x_scrape.py --file ../../../media-library/x_accounts.txt \
      --limit 4 --max-mb 30 --batch 7 --tags "X抓取,人物"
  python3 x_scrape.py someaccount --dry-run        # 只看会抓什么，不入库
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
import vision_filter

DATA = os.environ.get("MEDIA_LIB_DIR", "/vol1/picoclaw/.picoclaw/workspace/media-library")
STATE_PATH = os.path.join(DATA, "x_scrape_state.json")
LOG_PATH = os.path.join(DATA, "x_scrape.log")
LOCK_PATH = os.path.join(DATA, "x_scrape.lock")

API = os.environ.get("MEDIA_LIB_API", "http://127.0.0.1:18100")
PROXY = os.environ.get("X_SCRAPE_PROXY", "http://127.0.0.1:7890")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 图片真实像素下限：低于此判为缩略图/表情，丢弃
MIN_PX = 320
# 图片体积下限：X 原图压缩很狠，1080x1439 正经图可能只有 56KB，
# 早期用 60KB 会被误杀，故只以体积做兜底防 0 字节/损坏
MIN_IMG_BYTES = 20 * 1024

log_fp = None


# ------------------------------------------------------------------ 日志

def log(msg, echo=True):
    line = msg if msg.startswith("[") else f"[{time.strftime('%H:%M:%S')}] {msg}"
    if echo:
        print(line, file=sys.stderr, flush=True)
    if log_fp:
        try:
            log_fp.write(line + "\n")
            log_fp.flush()
        except Exception:
            pass


def rotate_log():
    """日志超过 5MB 时截断，保留尾部 2000 行"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 5 * 1024 * 1024:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-2000:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except Exception:
        pass


# ------------------------------------------------------------------ 状态

def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        st = {}
    st.setdefault("accounts", {})
    st.setdefault("cursor", 0)
    return st


def save_state(st):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def seen_set(st, account):
    return set(st["accounts"].get(account, {}).get("seen_tweets", []))


def mark_seen(st, account, tweet_ids):
    """只记录**真正处理完**的推文（limit 中断的绝不写，否则永远抓不到）"""
    rec = st["accounts"].setdefault(account, {"seen_tweets": [], "last_run": 0})
    cur = set(rec.get("seen_tweets", []))
    cur.update(tweet_ids)
    rec["seen_tweets"] = sorted(cur, key=int)
    rec["last_run"] = int(time.time())


# ------------------------------------------------------------------ HTTP

def _opener(use_proxy=True):
    if use_proxy and PROXY:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    return urllib.request.build_opener()


def http_get(url, timeout=30, use_proxy=True, referer=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json,image/*,video/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        **({"Referer": referer} if referer else {}),
    })
    with _opener(use_proxy).open(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", ""), r.geturl()


def proxy_alive():
    """代理探活：拉一个轻量地址，能连上就认为代理可用"""
    try:
        req = urllib.request.Request("https://x.com/robots.txt",
                                     headers={"User-Agent": UA})
        with _opener(True).open(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        log(f"代理探活失败：{type(e).__name__}: {e}")
        return False


# ------------------------------------------------------------------ 解析

def _extract_balanced(s, start):
    """start 指向 '[' 或 '{'，返回配对结束后的下标；解析失败返回 -1"""
    open_ch = s[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < len(s):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1


def parse_timeline(html):
    """
    从主页 HTML 提取 [{'tweet_id', 'is_retweet', 'source_id', 'media': [...]}, ...]

    归属判定依据：页面里每个主页条目都有 `entry_id:"tweet-<数字>"` 锚点，
    其后最近的 `media_entities2` 数组就属于该条目。比猜 rest_id 稳得多
    ——条目内的第一个 rest_id 往往是被转发者的用户 id，不是推文 id。
    """
    if not html:
        return []
    # 内嵌 JSON 是双重转义：\" -> "
    un = html.replace('\\"', '"')

    entries = [(m.start(), m.group(1))
               for m in re.finditer(r'"entry_id":"tweet-(\d+)"', un)]
    if not entries:
        return []

    out = []
    for i, (pos, tid) in enumerate(entries):
        # 本条目的范围：到下一个 entry_id 为止（最后一个条目取到尾）
        end = entries[i + 1][0] if i + 1 < len(entries) else len(un)
        seg = un[pos:end]

        mpos = seg.find('"media_entities2":[')
        if mpos < 0:
            continue
        b = seg.find("[", mpos)
        e = _extract_balanced(seg, b)
        if e < 0:
            continue
        try:
            arr = json.loads(seg[b:e])
        except Exception as ex:
            log(f"  ! media_entities2 解析失败 {tid}: {ex}")
            continue
        if not arr:
            continue

        # 原推文 ID：从 expanded_url 里抽 /status/<id>/photo|video
        source_id = None
        for it in arr:
            mm = re.search(r"/status/(\d+)/(?:photo|video)",
                           it.get("expanded_url", "") or "")
            if mm:
                source_id = mm.group(1)
                break

        out.append({
            "tweet_id": tid,
            "is_retweet": bool(source_id and source_id != tid),
            "source_id": source_id or tid,
            "media": arr,
        })
    return out


def pick_best_mp4(variants):
    """从 video_info.variants 里挑最高码率的 mp4；不用 m3u8（省掉 ffmpeg 合并）"""
    best = None
    for v in variants or []:
        if (v.get("content_type") or "").lower() != "video/mp4":
            continue
        if not v.get("url"):
            continue
        br = v.get("bitrate") or 0
        if best is None or br > (best.get("bitrate") or 0):
            best = v
    return best


def media_items(entry, max_mb=30):
    """
    展平为 [{'url','kind','ext','name','px','est_mb','skip_reason'}]
    kind: photo / video
    """
    tid = entry["tweet_id"]
    items = []
    for idx, m in enumerate(entry["media"], start=1):
        mtype = (m.get("type") or "").lower()
        name_base = f"{tid}_{idx:02d}"

        if mtype == "photo":
            url = m.get("media_url_https") or ""
            if not url:
                continue
            info = m.get("original_info") or {}
            w, h = info.get("width") or 0, info.get("height") or 0
            items.append({
                "url": url + ("&" if "?" in url else "?") + "name=orig",
                "kind": "photo", "ext": ".jpg", "name": name_base + "_photo.jpg",
                "px": (w, h), "est_mb": 0.0,
                # 像素不足 320 的只可能是缩略图/表情
                "skip_reason": "图片过小" if (w and h and min(w, h) < MIN_PX) else "",
            })
        elif mtype in ("video", "animated_gif"):
            info = m.get("video_info") or {}
            best = pick_best_mp4(info.get("variants"))
            if not best:
                items.append({"url": "", "kind": "video", "ext": ".mp4",
                              "name": name_base + "_video.mp4", "px": (0, 0),
                              "est_mb": 0.0, "skip_reason": "无可用 mp4"})
                continue
            dur_ms = info.get("duration_millis") or 0
            est_mb = (best.get("bitrate") or 0) * (dur_ms / 1000.0) / 8 / 1024 / 1024
            items.append({
                "url": best["url"], "kind": "video", "ext": ".mp4",
                "name": name_base + "_video.mp4", "px": (0, 0),
                "est_mb": round(est_mb, 2),
                # 按码率×时长估算，超限先跳过，省得白下 30MB
                "skip_reason": f"预估过大 {est_mb:.1f}MB" if est_mb > max_mb else "",
            })
    return items


# ------------------------------------------------------------------ 上传

def api_ok():
    try:
        with urllib.request.urlopen(API + "/api/stats", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def upload(path, name, tags, title="", source=""):
    """multipart 流式上传，避免大文件一次性吃满内存"""
    boundary = "----XSCRAPE" + str(int(time.time() * 1000))

    def field(k, v):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()

    head = b"".join([
        field("title", title),
        field("tags", ",".join(tags)),
        field("source", source),
        # synchronous=1：CLI 需要同步拿到 item_id 与去重结果
        field("synchronous", "1"),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
         f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode(),
    ])
    tail = f"\r\n--{boundary}--\r\n".encode()
    total = len(head) + os.path.getsize(path) + len(tail)

    import http.client
    u = urllib.parse.urlparse(API)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=1800)
    try:
        conn.putrequest("POST", "/api/upload")
        conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        conn.putheader("Content-Length", str(total))
        conn.putheader("Connection", "close")
        conn.endheaders()
        conn.send(head)
        with open(path, "rb") as f:
            while True:
                ch = f.read(1024 * 512)
                if not ch:
                    break
                conn.send(ch)
        conn.send(tail)
        r = conn.getresponse()
        body = r.read()
        try:
            data = json.loads(body)
        except Exception:
            return {"error": f"HTTP {r.status}: {body[:200].decode('utf-8', 'replace')}"}
        if data.get("items"):
            return data["items"][0]
        return {"error": data.get("detail") or str(data)[:200]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ------------------------------------------------------------------ 校验

def verify_image(path):
    """用 Pillow 验真实像素，防 original_info 撒谎 / 文件损坏"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if min(w, h) < MIN_PX:
            return False, f"像素过小 {w}x{h}"
        if os.path.getsize(path) < MIN_IMG_BYTES:
            return False, f"体积过小 {os.path.getsize(path)}B"
        return True, f"{w}x{h}"
    except Exception as e:
        return False, f"图片校验失败 {type(e).__name__}"


# ------------------------------------------------------------------ 主流程

def scrape_account(account, st, args, stats, dry_run=False):
    url = f"https://x.com/{urllib.parse.quote(account)}"
    log(f"@{account} 抓取主页…")

    try:
        raw, ctype, final_url = http_get(url, timeout=args.timeout)
    except urllib.error.HTTPError as e:
        log(f"  ✗ HTTP {e.code}（代理/账号受限或风控）")
        stats["fail"] += 1
        return
    except Exception as e:
        log(f"  ✗ 抓取失败 {type(e).__name__}: {e}")
        stats["fail"] += 1
        return

    html = raw.decode("utf-8", "replace")
    if len(html) < 5000 or "media_entities2" not in html:
        log(f"  ✗ 页面异常（{len(html)}B，无 media_entities2）")
        stats["fail"] += 1
        return

    entries = parse_timeline(html)
    if not entries:
        log("  · 本页无带媒体的推文")
        stats["no_new"] += 1
        return
    stats["scanned"] += len(entries)

    seen = seen_set(st, account)
    fresh = [e for e in entries if e["tweet_id"] not in seen]
    log(f"  · 推文 {len(entries)} 条，新推文 {len(fresh)} 条，"
        f"待处理媒体 {sum(len(e['media']) for e in fresh)} 个")

    if not fresh:
        stats["no_new"] += 1
        if not dry_run:
            mark_seen(st, account, [])
            save_state(st)
        return

    handled = []       # 真正处理完的推文 ID（每条推文只记一次）
    for index, entry in enumerate(fresh):
        tid = entry["tweet_id"]
        # --limit N 的单位是**推文条数**，不是媒体数
        if args.limit > 0 and index >= args.limit:
            log(f"  · 已达本轮上限 {args.limit} 条推文，剩余留待下轮")
            break

        items = media_items(entry, max_mb=args.max_mb)
        if entry["is_retweet"]:
            log(f"  · {tid} 转发（原推 {entry['source_id']}）")
        if not items:
            # 没有可处理媒体（极罕见），标记为已见避免每轮重复扫
            handled.append(tid)
            continue
        all_ok = True
        for it in items:
            if it["skip_reason"]:
                log(f"    - {it['name']} 跳过：{it['skip_reason']}")
                stats["skip_small" if "小" in it["skip_reason"] else "skip_big"] += 1
                continue
            if not it["url"]:
                all_ok = False
                continue
            if dry_run:
                src = "转发" if entry["is_retweet"] else "原创"
                px = f" {it['px'][0]}x{it['px'][1]}" if it["kind"] == "photo" else ""
                est = f" ~{it['est_mb']}MB" if it["kind"] == "video" else ""
                log(f"    ↓ [dry] {it['name']} ({src}{px}{est})")
                continue
            ok = download_and_store(it, entry, account, args, stats)
            if not ok:
                all_ok = False

        # 只有整条推文的媒体都处理过（含被正常跳过的）才记入已见，
        # 否则下次还能补抓，避免像历史上那样 64 条被误标为已见
        if all_ok:
            handled.append(tid)
        else:
            log(f"  ! {tid} 有媒体未完成，留待下轮")

    if not dry_run and handled:
        mark_seen(st, account, handled)
        save_state(st)
    elif not dry_run:
        st["accounts"].setdefault(account, {"seen_tweets": [], "last_run": 0})
        st["accounts"][account]["last_run"] = int(time.time())
        save_state(st)


def download_and_store(it, entry, account, args, stats):
    """下载单个媒体并入库；返回是否成功（含「判重跳过」也算成功）"""
    tmpdir = tempfile.mkdtemp(prefix="xscrape-", dir="/tmp")
    dest = os.path.join(tmpdir, it["name"])
    try:
        data, ctype, _ = http_get(it["url"], timeout=args.timeout,
                                 referer="https://x.com/")
        size_mb = len(data) / 1024 / 1024
        if it["kind"] == "video" and size_mb > args.max_mb:
            log(f"    - {it['name']} 跳过：实下 {size_mb:.1f}MB 超限")
            stats["skip_big"] += 1
            return True
        with open(dest, "wb") as f:
            f.write(data)

        if it["kind"] == "photo":
            ok, info = verify_image(dest)
            if not ok:
                log(f"    - {it['name']} 跳过：{info}")
                stats["skip_small"] += 1
                return True
        else:
            info = f"{size_mb:.2f}MB"

        tags = list(args.tags)
        if it["kind"] == "video" and "X视频" not in tags:
            tags.append("X视频")
        title = f"@{account} X"

        if not getattr(args, "no_vision", False):
            vision_cfg = getattr(args, "vision_config", None) or vision_filter.load_config(DATA)
            if vision_cfg.get("enabled"):
                try:
                    vres = vision_filter.analyze_media(dest, it["kind"], vision_cfg)
                except Exception as e:
                    log(f"    ✗ 视觉识别失败 {it['name']}：{e}")
                    stats["fail"] += 1
                    return False
                if not vres["keep"]:
                    reason = vres.get("reason") or "不符合女性人像条件"
                    log(f"    - {it['name']} 跳过（视觉过滤）：{reason}")
                    stats["skip_vision"] = stats.get("skip_vision", 0) + 1
                    return True
                if vres.get("title"):
                    title = vres["title"]
                for vt in vres.get("tags") or []:
                    if vt not in tags:
                        tags.append(vt)

        rec = upload(dest, it["name"], tags, title=title,
                     source=f"https://x.com/{account}")
        if rec.get("error"):
            log(f"    ✗ 入库失败 {it['name']}：{rec['error']}")
            stats["fail"] += 1
            return False

        iid = rec.get("id") or "?"
        if rec.get("duplicate"):
            log(f"    · 内容重复 {iid}")
            stats["skip_dup"] += 1
        elif rec.get("near_duplicate_id"):
            log(f"    · 近似重复 {iid}（近 {rec['near_duplicate_id']}）")
            stats["skip_dup"] += 1
        else:
            log(f"      ✓ 入库 {iid} ({info})")
            stats["new"] += 1
            stats["bytes"] += len(data)
        return True
    except Exception as e:
        log(f"    ✗ {it['name']} 失败 {type(e).__name__}: {e}")
        stats["fail"] += 1
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def load_accounts(args):
    accts = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                accts.append(s.lstrip("@"))
    accts.extend(a.lstrip("@") for a in (args.accounts or []))
    # 去重保序
    out, seen = [], set()
    for a in accts:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", a):
            raise ValueError(f"无效 X 账号：{a!r}")
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def main():
    global log_fp
    p = argparse.ArgumentParser(description="抓取 X 账号最新图片/视频入库")
    p.add_argument("accounts", nargs="*", help="账号名（不含 @），可多个")
    p.add_argument("--file", help="账号白名单文件，一行一个，# 开头为注释")
    p.add_argument("--limit", type=int, default=4,
                   help="每账号每轮最多处理**推文条数**（默认 4）")
    p.add_argument("--batch", type=int, default=0,
                   help="每轮只处理 N 个账号，游标轮转（0=全部）")
    p.add_argument("--max-mb", type=float, default=30, help="单个文件上限 MB")
    p.add_argument("--tags", default="X抓取,人物", help="入库标签，逗号分隔")
    p.add_argument("--timeout", type=int, default=30, help="单请求超时秒")
    p.add_argument("--dry-run", action="store_true", help="只看会抓什么，不下载不入库")
    p.add_argument("--no-vision", action="store_true", help="跳过在线视觉识别过滤与元数据生成")
    p.add_argument("--quiet", action="store_true", help="不往 stderr 打日志")
    args = p.parse_args()
    if args.limit < 0 or args.batch < 0 or args.max_mb <= 0 or args.timeout <= 0:
        p.error("limit/batch 不能为负，max-mb/timeout 必须大于零")
    args.tags = [t.strip() for t in re.split(r"[,，]", args.tags) if t.strip()]

    try:
        accounts = load_accounts(args)
    except (OSError, ValueError) as e:
        p.error(str(e))
    if not accounts:
        log("没有账号可抓（检查 --file 或参数）")
        return 2

    log_fp = None
    if not args.dry_run:
        rotate_log()
        log_fp = open(LOG_PATH, "a", encoding="utf-8")

    log(f"=== 开始抓取 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", echo=not args.quiet)

    if not proxy_alive():
        log("✗ 代理不可用，终止（X 必须走住宅 IP）")
        return 3

    if not args.dry_run and not api_ok():
        log("✗ 图片库服务未响应（先跑 ensure.sh）")
        return 4

    args.vision_config = None
    if not args.dry_run and not args.no_vision:
        try:
            vcfg = vision_filter.load_config(DATA)
        except Exception as e:
            log(f"✗ 视觉识别配置加载失败：{e}")
            return 5
        if vcfg.get("enabled") and not vcfg.get("api_key"):
            log("✗ 已启用视觉识别但未配置 API Key（X_VISION_API_KEY 或 vision_config.json）")
            return 5
        args.vision_config = vcfg

    st = load_state()
    # 游标轮转：每轮只抓 batch 个，保证每个账号都会被轮到
    if args.batch and args.batch < len(accounts):
        cur = st.get("cursor", 0) % len(accounts)
        batch = [accounts[(cur + i) % len(accounts)] for i in range(args.batch)]
        st["cursor"] = (cur + args.batch) % len(accounts)
        if not args.dry_run:
            save_state(st)
        log(f"账号 {len(accounts)} 个｜本轮 {len(batch)} 个（游标 {cur}→{st['cursor']}）"
            f"｜上限 {args.max_mb:g}MB｜标签 {args.tags}")
        accounts = batch
    else:
        log(f"账号 {len(accounts)} 个｜上限 {args.max_mb:g}MB｜标签 {args.tags}")

    stats = {"accounts": 0, "scanned": 0, "new": 0, "skip_dup": 0,
             "skip_big": 0, "skip_small": 0, "skip_vision": 0, "fail": 0, "no_new": 0, "bytes": 0}
    for acct in accounts:
        stats["accounts"] += 1
        try:
            scrape_account(acct, st, args, stats, dry_run=args.dry_run)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"  ✗ @{acct} 未预期异常 {type(e).__name__}: {e}")
            stats["fail"] += 1

    stats["bytes"] = round(stats["bytes"] / 1024 / 1024, 2)
    log(f"完成：{json.dumps(stats, ensure_ascii=False)}", echo=not args.quiet)
    log(f"=== 结束 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", echo=not args.quiet)
    if log_fp:
        log_fp.close()
        log_fp = None
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
