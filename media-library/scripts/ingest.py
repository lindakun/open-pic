#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片库 CLI —— 下载链接内容并上传到本地图片服务

用法：
  python3 ingest.py <url> [<url> ...] [选项]

选项：
  --tags 标签1,标签2     给本次入库打标签
  --title 标题           自定义标题（仅单文件时生效）
  --source 来源          默认自动填原始 URL
  --limit N              每个链接最多取 N 个文件（默认 30）
  --no-start             不自动拉起服务

支持的链接：
  - 直接图片 URL（jpg/png/gif/webp/avif/heic）
  - 直接视频 URL（mp4/webm/mov/m4v）
  - 网页（会解析 og:image / <img> / <video> 等）
  - YouTube / B站 / 微博 / Twitter(X) / 抖音 等（走 yt-dlp）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(BASE)
WORKSPACE = os.path.dirname(os.path.dirname(SKILL_DIR))
API = os.environ.get("MEDIA_LIB_API", "http://127.0.0.1:18100")
YTDLP = os.environ.get("YTDLP_BIN", "/vol1/picoclaw/bin/yt-dlp")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic"}
VID_EXT = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}

# 小于这个体积的图片基本是列表缩略图/图标，不值得入库（60KB）
MIN_BYTES = 60 * 1024

VIDEO_HOSTS = (
    "youtube.com", "youtu.be", "bilibili.com", "b23.tv", "twitter.com", "x.com",
    "weibo.com", "weibo.cn", "douyin.com", "v.douyin.com", "tiktok.com",
    "instagram.com", "vimeo.com", "dailymotion.com", "ixigua.com", "kuaishou.com",
    "xiaohongshu.com", "xhslink.com", "facebook.com", "reddit.com",
)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- 服务健康 ----------

def api_ok():
    try:
        with urllib.request.urlopen(API + "/api/stats", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_server():
    if api_ok():
        return True
    srv = os.path.join(BASE, "server.py")
    log("服务未运行，尝试拉起…")
    # setsid 让服务脱离当前会话，否则父进程退出后会被一起回收
    kw = {}
    if hasattr(os, "setsid"):
        kw["preexec_fn"] = os.setsid
    subprocess.Popen([sys.executable, srv, "--port",
                      str(urllib.parse.urlparse(API).port or 18100)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True, **kw)
    for _ in range(40):
        time.sleep(0.25)
        if api_ok():
            return True
    return False


# ---------- HTTP 工具 ----------

def fetch_bytes(url, referer=None, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,video/*,*/*;q=0.8",
        **({"Referer": referer} if referer else {}),
    })
    proxy = os.environ.get("MEDIA_LIB_PROXY", "")
    if proxy:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        with op.open(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except Exception:
        # 直连失败时兜底走本机代理（yt-dlp 用的同一个）
        proxy = os.environ.get("MEDIA_LIB_PROXY_FALLBACK", "http://127.0.0.1:7890")
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        with op.open(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")


def guess_ext(url, ctype):
    if url.startswith("file://"):
        url = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    url_path = urllib.parse.urlparse(url).path if "://" in url else url
    ext = os.path.splitext(url_path)[1].lower()
    if ext in IMG_EXT or ext in VID_EXT:
        return ext
    m = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "image/avif": ".avif", "image/bmp": ".bmp",
        "image/heic": ".heic", "video/mp4": ".mp4", "video/webm": ".webm",
        "video/quicktime": ".mov",
    }
    for k, v in m.items():
        if ctype.startswith(k):
            return v
    return ""


# ---------- 网页解析 ----------

def is_media_url(url, ctype=""):
    ext = guess_ext(url, ctype)
    return ext in IMG_EXT or ext in VID_EXT


# 噪音文件名关键词（logo、图标、占位图等，抓下来没意义）
NOISE_NAME = re.compile(
    r"(logo|icon|favicon|avatar|sprite|placeholder|blank|spacer|loading|"
    r"twitter[-_]?card|facebook[-_]?card|share[-_]?(img|image)|"
    r"default[-_]?(img|image|thumb)|watermark|badge|captcha|qrcode)",
    re.I)


def extract_from_html(url):
    """从网页里抽取媒体直链

    返回 [(url, 预估面积)]，按面积降序（大图优先）。
    会过滤掉 logo/图标/占位图等噪音。
    """
    try:
        html, _ = fetch_bytes(url, timeout=45)
    except Exception as e:
        log(f"  取页面失败: {e}")
        return []
    text = html.decode("utf-8", "replace")

    cands = {}  # url -> area

    def add(u, w=0, h=0, is_og=False):
        u = (u or "").strip().replace("&amp;", "&")
        if not u or u.startswith("data:") or u.startswith("blob:"):
            return
        u = urllib.parse.urljoin(url, u)
        if not is_media_url(u):
            return
        name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(u).path))
        # 文件名噪音过滤，og 图也一样过滤（twitter-card/logo 这类抓下来没意义）
        if NOISE_NAME.search(name):
            return
        # 尺寸过滤：有明确尺寸且太小就不算
        if w and h and (w < 200 or h < 200):
            return
        area = (w or 0) * (h or 0)
        if is_og:
            area = max(area, 1)  # og 图给个基础分，但不高于带尺寸的大图
        cands[u] = max(cands.get(u, 0), area)

    # og / twitter meta（只在没有更好候选时才用，所以只给低分）
    for m in re.finditer(
            r'<meta[^>]+(?:property|name)=["\'](?:og:image|og:video|twitter:image|twitter:player:stream)["\'][^>]+content=["\']([^"\']+)',
            text, re.I):
        add(m.group(1), is_og=True)
    for m in re.finditer(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|og:video|twitter:image)["\']',
            text, re.I):
        add(m.group(1), is_og=True)

    # <img> 带 width/height 属性
    for m in re.finditer(r"<img\b[^>]*>", text, re.I):
        tag = m.group(0)
        src = re.search(r'\bsrc=["\']([^"\']+)', tag, re.I)
        if not src:
            continue
        w = re.search(r'\bwidth=["\']?(\d+)', tag, re.I)
        h = re.search(r'\bheight=["\']?(\d+)', tag, re.I)
        add(src.group(1),
            int(w.group(1)) if w else 0,
            int(h.group(1)) if h else 0)

    # srcset 里最大的那张
    for m in re.finditer(r'\bsrcset=["\']([^"\']+)', text, re.I):
        best, best_w = None, 0
        for item in m.group(1).split(","):
            parts = item.strip().split()
            if not parts:
                continue
            ww = 0
            if len(parts) > 1 and parts[-1].endswith("w"):
                try:
                    ww = int(parts[-1][:-1])
                except ValueError:
                    ww = 0
            if ww >= best_w:
                best, best_w = parts[0], ww
        if best:
            add(best, best_w, int(best_w * 0.75) if best_w else 0)

    # <source> / <video>
    for m in re.finditer(r'<source[^>]+src=["\']([^"\']+)', text, re.I):
        add(m.group(1), is_og=True)  # 视频优先保留
    for m in re.finditer(r'<video[^>]+src=["\']([^"\']+)', text, re.I):
        add(m.group(1), is_og=True)

    # 常见 JSON 字段里的原图/大图
    for m in re.finditer(
            r'"(?:original|origin|large|full|url|src)"\s*:\s*'
            r'"(https?:\\?/\\?/[^"]+?\.(?:jpg|jpeg|png|gif|webp|avif|mp4)[^"]*)"',
            text, re.I):
        add(m.group(1).replace("\\/", "/"), 0, 0)

    items = sorted(cands.items(), key=lambda kv: -kv[1])
    # 若存在带真实尺寸的候选，就丢掉纯 og 兜底项（area==1 的都是 og/meta 来的）
    if any(a > 1 for _, a in items):
        items = [(u, a) for u, a in items if a > 1]

    # 缩略图 URL 升级：先探测一次，确认这类升级在本站真的存在
    # （不同站点的缩略图路径规则不同，盲目换路径会全是 404）
    upgraded = []
    rule_ok = {}  # rule_idx -> True/False/None(未测)
    for u, a in items:
        for idx, (pat, rep) in enumerate(UPGRADE_RULES):
            if not re.search(pat, u, re.I):
                continue
            nu = re.sub(pat, rep, u, flags=re.I)
            if nu == u or not is_media_url(nu) or nu in cands:
                continue
            if rule_ok.get(idx) is None:
                rule_ok[idx] = probe_exists(nu)
                log(f"  升级规则 {pat} -> {rep}: {'可用' if rule_ok[idx] else '不可用'}")
            if rule_ok[idx]:
                upgraded.append((nu, max(a, 2)))
    return upgraded + [(u, a) for u, a in items]


def is_video_site(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(h in host for h in VIDEO_HOSTS)


# ---------- 下载 ----------

# 缩略图 URL 升级规则：命中就用同名大图替换
UPGRADE_RULES = [
    (r"/small/", "/full/"),
    (r"/thumbs?/", "/"),
    (r"/thumb/", "/"),
    (r"[-_]thumb(?=\.)", ""),
    (r"[-_]\d{2,4}x\d{2,4}(?=\.)", ""),      # -300x200.jpg
    (r"/(?:small|medium|thumb)(?=/)", ""),
]


def upgrade_url(u):
    out = []
    for pat, rep in UPGRADE_RULES:
        nu = re.sub(pat, rep, u, flags=re.I)
        if nu != u and is_media_url(nu):
            out.append(nu)
    return out


def probe_size(url):
    """探测远端文件大小（用 Range: 0-0 读 Content-Range），不解body

    返回 (可访问, 字节数)。字节数 0 表示未知。
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    try:
        proxy = os.environ.get("MEDIA_LIB_PROXY", "")
        if proxy:
            op = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            r = op.open(req, timeout=12)
        else:
            r = urllib.request.urlopen(req, timeout=12)
        with r:
            ct = r.headers.get("Content-Type", "")
            cr = r.headers.get("Content-Range", "")
            cl = r.headers.get("Content-Length", "0")
            st = r.status
        if st not in (200, 206):
            return False, 0
        if not (ct.startswith("image/") or ct.startswith("video/")):
            return False, 0
        total = 0
        if "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except ValueError:
                total = 0
        if not total:
            try:
                total = int(cl)
            except ValueError:
                total = 0
        return True, total
    except Exception:
        return False, 0


def probe_exists(url):
    """轻量探测 URL 是否可下载（只取 1 字节）"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    try:
        proxy = os.environ.get("MEDIA_LIB_PROXY", "")
        if proxy:
            op = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            r = op.open(req, timeout=12)
        else:
            r = urllib.request.urlopen(req, timeout=12)
        with r:
            ct = r.headers.get("Content-Type", "")
            st = r.status
        return st in (200, 206) and (ct.startswith("image/") or ct.startswith("video/"))
    except Exception:
        return False


# 详情页识别：只认明确的"短 ID 内容页"模式，宁可漏也不乱跟
DETAIL_HINT = re.compile(
    r"(/w/[a-z0-9]{4,10}$"            # wallhaven /w/og7865
    r"|/p/[a-z0-9]{4,20}$"            # 通用 /p/xxx
    r"|/status/\d{6,}"                # twitter /status/123
    r"|/photo/[a-z0-9/_-]{4,}$"       # unsplash/pexels
    r"|/item/[a-z0-9_-]{4,}$"
    r"|/post/[a-z0-9_-]{4,}$"
    r"|/article/[a-z0-9_-]{4,}"
    r"|/archives/\d{4,}"
    r"|/\d{6,}$)",                    # 纯数字 ID 页
    re.I)

# 明确不是内容页的路径，先排掉
SKIP_HINT = re.compile(
    r"(/tag/|/tags/|/category/|/categories/|/user/|/users/|/author/|"
    r"/wallpaper/fav|/wallpaper/tags|/wallpaper/similar|"
    r"/login|/signin|/register|/signup|/about|/contact|/privacy|/terms|"
    r"/help|/faq|/search|/page/|/feed|/rss|"
    r"javascript:|mailto:|tel:|^#$|\.(css|js|zip|pdf)$)",
    re.I)


def find_detail_links(url, max_n=10):
    """列表页 → 详情页。

    相册/搜索结果页往往只给 300px 缩略图，真正的大图在详情页的 og:image 里。
    这里从页面里挑出"看起来像详情页"的同域链接。
    """
    try:
        html, _ = fetch_bytes(url, timeout=45)
    except Exception as e:
        log(f"  取页面失败: {e}")
        return []
    text = html.decode("utf-8", "replace")
    host = urllib.parse.urlparse(url).netloc
    base_path = urllib.parse.urlparse(url).path.rstrip("/")

    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]+href=["\']([^"\'#][^"\']*)', text, re.I):
        u = urllib.parse.urljoin(url, m.group(1).strip().replace("&amp;", "&"))
        p = urllib.parse.urlparse(u)
        if p.netloc != host:
            continue
        if u in seen or SKIP_HINT.search(u):
            continue
        if not DETAIL_HINT.search(p.path + ("?" + p.query if p.query else "")):
            continue
        if is_media_url(u):
            continue  # 直链媒体不算详情页
        seen.add(u)
        out.append(u)
        if len(out) >= max_n:
            break
    return out


def is_too_small(path, ext, min_px=320):
    """下载后按真实像素判断：太小的是图标/列表缩略图，不要

    320 这个阈值是实测定的：常见 CMS 缩略图上限是 300px 宽（WordPress
    -300x200、wallhaven /small/ 300x200），低于它基本是列表页产物。
    """
    if ext not in IMG_EXT:
        return False
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if w < min_px or h < min_px:
            log(f"  跳过（尺寸过小 {w}x{h}）")
            return True
    except Exception:
        pass
    return False


def download_direct(url, referer=None):
    """直链下载到临时文件，返回 (path, name) 或 None"""
    try:
        data, ctype = fetch_bytes(url, referer=referer)
    except Exception as e:
        log(f"  下载失败 {url[:90]}: {e}")
        return None
    if len(data) < 1024:
        log(f"  跳过（过小 {len(data)}B）: {url[:90]}")
        return None
    ext = guess_ext(url, ctype)
    if not ext:
        log(f"  跳过（类型未知 {ctype}）: {url[:90]}")
        return None
    # 用 URL 里的文件名，没有就按时间戳生成
    base = os.path.basename(urllib.parse.urlparse(url).path)
    base = urllib.parse.unquote(base)
    if not base or os.path.splitext(base)[1].lower() not in (IMG_EXT | VID_EXT):
        base = f"media-{int(time.time() * 1000)}"
    name = os.path.splitext(base)[0] + ext
    fd, p = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if is_too_small(p, ext):
        try:
            os.remove(p)
        except Exception:
            pass
        return None
    return p, name


def download_tweet_photos(url, max_items=10):
    """X/Twitter 纯图片推文的兜底：syndication API 拿 mediaDetails 原图

    yt-dlp 对纯图片推文会硬失败（No video could be found in this tweet）。
    该接口免登录，取到的图加 ?name=orig 才是原图（比 ?name=large 大约 30-50%）。
    """
    m = re.search(r"(?:twitter\.com|x\.com)/[^/]+/status(?:es)?/(\d+)", url)
    if not m:
        return []
    tid = m.group(1)
    api = f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=4"
    try:
        raw, _ct = fetch_bytes(api)
        data = json.loads(raw)
    except Exception as e:
        log(f"  syndication API 失败: {e}")
        return []
    urls, seen = [], set()
    for md in data.get("mediaDetails") or []:
        if md.get("type") != "photo":
            continue
        u = md.get("media_url_https")
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    if not urls:
        return []
    log(f"  syndication 拿到 {len(urls)} 张图")
    out = []
    for u in urls[:max_items]:
        try:
            data, ctype = fetch_bytes(u + "?name=orig")
        except Exception:
            data, ctype = b"", ""
        if len(data) < 1024:
            continue
        ext = guess_ext(u, ctype) or ".jpg"
        fd, p = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if is_too_small(p, ext):
            try:
                os.remove(p)
            except Exception:
                pass
            continue
        out.append(p)
    return out


def download_with_ytdlp(url, max_items=10):
    """用 yt-dlp 拉视频或图片集，返回临时文件列表"""
    outdir = tempfile.mkdtemp(prefix="mlib-y-")
    cmd = [YTDLP, "--no-warnings", "--yes-playlist",
           "--merge-output-format", "mp4",
           "-o", os.path.join(outdir, "%(autonumber)s-%(id).40s.%(ext)s"),
           "--playlist-end", str(max_items),
           "--no-progress", "-q"]
    proxy = os.environ.get("MEDIA_LIB_PROXY", "http://127.0.0.1:7890")
    if proxy:
        cmd += ["--proxy", proxy]
    ck = os.environ.get("MEDIA_LIB_YTDLP_COOKIES")
    if ck and os.path.isfile(ck):
        cmd += ["--cookies", ck]
    # 优先要能播放的 mp4
    cmd += ["-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"]
    cmd += [url]
    try:
        r = subprocess.run(cmd, timeout=600, capture_output=True, text=True)
        if r.returncode != 0 and not os.listdir(outdir):
            log(f"  yt-dlp 失败: {(r.stderr or '')[-300:]}")
            # 再试一次：纯图片/无格式约束
            cmd2 = [YTDLP, "--no-warnings", "--no-progress", "-q",
                    "-o", os.path.join(outdir, "%(autonumber)s-%(id).40s.%(ext)s"),
                    "--playlist-end", str(max_items)]
            if proxy:
                cmd2 += ["--proxy", proxy]
            cmd2 += [url]
            r2 = subprocess.run(cmd2, timeout=600, capture_output=True, text=True)
            if r2.returncode != 0:
                log(f"  yt-dlp 重试也失败: {(r2.stderr or '')[-300:]}")
    except subprocess.TimeoutExpired:
        log("  yt-dlp 超时")
    return [os.path.join(outdir, f) for f in sorted(os.listdir(outdir))]


# ---------- 上传 ----------

def upload(path, name, title="", tags=None, source=""):
    """multipart 上传（流式读文件，避免大文件一次性吃满内存）"""
    boundary = "----MLIB" + str(int(time.time() * 1000))
    tags = tags or []

    def field(k, v):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()

    head = b"".join([
        field("title", title), field("tags", ",".join(tags)), field("source", source),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
         f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode(),
    ])
    tail = f"\r\n--{boundary}--\r\n".encode()
    fsize = os.path.getsize(path)
    total = len(head) + fsize + len(tail)

    req = urllib.request.Request(
        API + "/api/upload", data=None, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Content-Length": str(total)})

    # http.client 手工流式发送
    import http.client
    u = urllib.parse.urlparse(API)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=1800)
    try:
        conn.putrequest("POST", "/api/upload")
        conn.putheader("Content-Type", req.headers["Content-type"])
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
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP {r.status}: {body[:200].decode('utf-8','replace')}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------- 主流程 ----------

def probe_is_media(url):
    """探测 URL 的实际 Content-Type，判断是否直链媒体（只读 2KB）"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-2047"})
    try:
        proxy = os.environ.get("MEDIA_LIB_PROXY", "")
        if proxy:
            op = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            r = op.open(req, timeout=25)
        else:
            r = urllib.request.urlopen(req, timeout=25)
        with r:
            ct = r.headers.get("Content-Type", "")
            final = r.geturl()
        if ct.startswith("image/") or ct.startswith("video/"):
            return True, final, ct
        return False, final, ct
    except Exception as e:
        log(f"  探测失败: {e}")
        return False, url, ""


def process_url(url, args):
    log(f"\n=== {url}")
    got = []  # (path, name)

    # 本地文件（绝对路径或 file://）
    local = None
    if url.startswith("file://"):
        local = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    elif os.path.isabs(url) and os.path.isfile(url):
        local = url
    if local:
        if not os.path.isfile(local):
            log("  ✗ 本地文件不存在")
            return []
        ext = os.path.splitext(local)[1].lower()
        if ext not in IMG_EXT and ext not in VID_EXT:
            log(f"  ✗ 不支持的类型 {ext}")
            return []
        # 复制到临时目录，避免服务端入库时的 move 动到用户原文件
        tmpcopy = os.path.join(tempfile.gettempdir(),
                               f"mlib-local-{int(time.time()*1000)}{ext}")
        try:
            with open(local, "rb") as a, open(tmpcopy, "wb") as b:
                while True:
                    ch = a.read(1024 * 512)
                    if not ch:
                        break
                    b.write(ch)
        except Exception as e:
            log(f"  ✗ 读取本地文件失败: {e}")
            return []
        got.append((tmpcopy, os.path.basename(local)))
    elif is_video_site(url):
        log("  识别为视频站，用 yt-dlp")
        for p in download_with_ytdlp(url, args.limit)[:args.limit]:
            got.append((p, os.path.basename(p)))
        if not got:
            # X 纯图片推文 yt-dlp 会硬失败，走 syndication API 兜底
            for p in download_tweet_photos(url, args.limit):
                got.append((p, os.path.basename(p)))
    else:
        # 先探测是否直链媒体（无扩展名的图片 CDN 很常见）
        is_media, final_url, ct = probe_is_media(url)
        if is_media:
            log(f"  直链媒体 ({ct})")
            r = download_direct(final_url)
            if r:
                got.append(r)
        else:
            log("  解析网页媒体…")
            cands = extract_from_html(url)
            log(f"  发现 {len(cands)} 个候选")
            if not cands:
                log("  无候选，尝试 yt-dlp")
                for p in download_with_ytdlp(url, args.limit)[:args.limit]:
                    got.append((p, os.path.basename(p)))
            else:
                # 按候选顺序尝试。先用 Range 探测体积，跳过明显是缩略图的
                # （列表页常见 300x200 缩略图只有 10-30KB，正文图通常 >60KB）
                ok_base = set()
                for link, _area in cands:
                    if len(got) >= args.limit:
                        break
                    base = re.sub(r".*?/(full|small|th|lg)/", "", link)
                    if base in ok_base:
                        continue
                    reachable, nbytes = probe_size(link)
                    if not reachable:
                        continue
                    if nbytes and nbytes < MIN_BYTES:
                        continue  # 缩略图，不浪费时间下载
                    r = download_direct(link, referer=url)
                    if r:
                        got.append(r)
                        ok_base.add(base)

                # 依然不够（列表页只给缩略图）→ 进详情页捞 og:image 大图
                if len(got) < args.limit:
                    log(f"  仅 {len(got)} 张可用，尝试跟进详情页")
                    for durl in find_detail_links(url, max_n=args.limit * 2):
                        if len(got) >= args.limit:
                            break
                        log(f"  详情页 {durl}")
                        for dl, _a in extract_from_html(durl)[:3]:
                            if len(got) >= args.limit:
                                break
                            r = download_direct(dl, referer=durl)
                            if r:
                                got.append(r)

    if not got:
        log("  ✗ 没拿到任何文件")
        return []

    out = []
    for i, (p, name) in enumerate(got[:args.limit]):
        title = args.title if (args.title and len(got) == 1) else ""
        if not title and len(got) > 1:
            title = os.path.splitext(name)[0]
        res = upload(p, name, title=title, tags=args.tags, source=url)
        # 只清理我们自己的临时文件，绝不动用户的原文件
        if p.startswith(tempfile.gettempdir()):
            try:
                os.remove(p)
            except Exception:
                pass
        if res.get("error"):
            log(f"  ✗ 上传失败 {name}: {res['error'][:160]}")
        else:
            for it in res.get("items", []):
                flag = "重复" if it.get("duplicate") else "新增"
                log(f"  ✓ {flag}: {it['id']} {it['name']}")
                out.append(it)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--tags", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--no-start", action="store_true")
    a = ap.parse_args()
    a.tags = [t.strip() for t in re.split(r"[,，\s]+", a.tags) if t.strip()]

    if not a.no_start and not ensure_server():
        log("错误：图片服务无法启动")
        return 2

    added = []
    for u in a.urls:
        added.extend(process_url(u, a))

    print(json.dumps({
        "ok": True,
        "count": len(added),
        "items": [{"id": i["id"], "name": i["name"], "kind": i["kind"],
                   "url": f"{API}/f/{i['file']}",
                   "thumb": f"{API}/t/{i['id']}.jpg" if i.get("thumb") else None}
                  for i in added],
    }, ensure_ascii=False, indent=2))
    return 0 if added else 1


if __name__ == "__main__":
    sys.exit(main())
