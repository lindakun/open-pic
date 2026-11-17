---
name: media-library
description: >
  个人图片/视频库。当用户发来链接（图片、视频、推文、网页、B站/YouTube 等）要求
  "存起来 / 存到图片库 / 传到服务器 / 下载下来" 时使用。会把链接里的图片或视频
  下载到本地图片服务并按标签归档，用户可通过瀑布流 Web 界面浏览。
  也支持直接入库本地文件。触发语："把这个存图库"、"下载这个视频"、"传到图片服务器"、
  "帮我收一下这个链接"、"看看图片库"。
---

# 图片库（media-library）

本地图片/视频库 + 瀑布流 Web 界面。
用户丢一个链接过来 → 下载 → 入库 → 网页瀑布流浏览。

## 快速上手

```bash
S=/vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts

# 一个或多个链接（自动判断是图片/网页/视频站）
python3 $S/ingest.py "https://x.com/xxx/status/123" --tags 人物,壁纸

# 本地文件
python3 $S/ingest.py /path/to/a.jpg --tags 素材

# 服务管理
python3 $S/server.py --status
python3 $S/server.py --port 18100      # 前台启动
python3 $S/server.py --stop
```

**访问地址**：`http://192.168.31.188:18100/`（局域网内任意设备）

## 核心流程（收到链接时照做）

1. `ingest.py` 传链接，带 `--tags`（从内容推断 1-3 个中文标签）
2. 看 stderr 里的 `✓ 新增 / ✓ 重复 / ✗ 失败`
3. 报告"入库 N 项"，附上界面地址

不要自己去写下载逻辑，全部走 `ingest.py`。

## ingest.py 行为

| 链接类型 | 处理方式 |
|---|---|
| 本地路径 / `file://` | 直接入库（复制，不动原文件） |
| 直链图片/视频（含无扩展名 CDN） | Range 探测 Content-Type，通过则下载 |
| 普通网页 | 抽 `og:image`/`og:video`/`<img>`/`<video>`/`<source>`/JSON 内图片字段 |
| 列表/相册页（只给缩略图） | 自动跟进详情页捞 og:image 原图 |
| 视频站（B站/YouTube/微博/X/抖音/小红书…） | 走 `yt-dlp` |

### 图片质量护栏（三层，防抓一堆缩略图）

1. **文件名噪音过滤**：`logo|icon|favicon|avatar|sprite|placeholder|twitter-card|share-img|watermark|captcha|qrcode` 直接丢
2. **尺寸升级**：命中 `UPGRADE_RULES`（`/small/→/full/`、`/thumb/→/`、`-300x200→空` 等）时，
   先 `probe_exists()` 验证规则在本站真有效，再优先尝试升级 URL
3. **体积/像素双重判定**：`probe_size()` 读 `Content-Range` 得到远端字节数，
   `< 60KB` 视为缩略图跳过；下载后再用 Pillow 查真实像素，`< 320px` 丢弃

> 阈值依据：常见 CMS 缩略图上限 300px 宽（WordPress `-300x200`、wallhaven `/small/` 就是 300×200）。

### 列表页 → 详情页

列表页往往只有 300px 缩略图（wallhaven 搜索页就是）。规则：

- `DETAIL_HINT`：`/w/xxxx`、`/p/xxx`、`/status/123`、`/photo/xxx`、`/item/xxx`、`/archives/1234`、纯数字 ID 页
- `SKIP_HINT`：`/tag/`、`/category/`、`/user/`、`/page/`、`/wallpaper/fav` 等一律不跟

**故意保守**：宁可漏抓也不乱跟（早期版本把 `/tag/96819` 当详情页，白跑几十个请求）。

### 去重与清理

- 内容 sha1 前 16 位做 ID，同一文件重复上传返回原记录，不重复占盘
- 单个链接最终成功入库数受 `--limit` 限制（不是候选数限制）
- 只清理自己创建的 `/tmp` 临时文件，**绝不动用户原文件**

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `MEDIA_LIB_API` | `http://127.0.0.1:18100` | 服务地址 |
| `MEDIA_LIB_DIR` | `<workspace>/media-library` | 数据目录 |
| `MEDIA_LIB_PROXY` | 空 | 强制走代理下载网页/图片 |
| `MEDIA_LIB_PROXY_FALLBACK` | `http://127.0.0.1:7890` | 直连失败时兜底代理 |
| `MEDIA_LIB_YTDLP_COOKIES` | 空 | yt-dlp cookies 文件路径 |
| `YTDLP_BIN` | `/vol1/picoclaw/bin/yt-dlp` | yt-dlp 路径 |

## 已知限制（踩过的坑）

- **YouTube 需要 cookies**：`Sign in to confirm you're not a bot`。
  解：导出 cookies.txt 放到 `MEDIA_LIB_YTDLP_COOKIES` 指向的位置。
- **B站/YouTube 必须走代理**：`yt-dlp` 已默认加 `--proxy http://127.0.0.1:7890`（mihomo）。
  若 mihomo 未运行则外网视频全挂。
- **B站大视频慢**：默认 `bv*+ba` 分离流再 merge，1 分钟以上视频要等。用 `--limit N` 控制批量。
- **微博/小红书** 常要登录态，无 cookies 时抽取会拿到占位图。
- **X 纯图片推文 yt-dlp 会硬失败**：直接报 `No video could be found in this tweet`。
  已内置自动兜底：`download_tweet_photos()` 走
  `cdn.syndication.twimg.com/tweet-result?id=<推文ID>&token=4`（免登录、经代理），
  取 `mediaDetails[].media_url_https`，去重后加 `?name=orig` 下原图。
  **务必用 `?name=orig`**：实测同一张 480KB vs `?name=large` 的 329KB。
  日志里出现 `syndication 拿到 N 张图` 就是走了这条路。**不用手动操作。**

## 数据位置

```
/vol1/picoclaw/.picoclaw/workspace/media-library/
├── files/      # 原文件，文件名 = <sha1前16位>.<ext>
├── thumbs/     # 缩略图 640px JPEG
├── index.json  # 元数据索引（原子写入）
├── server.pid
└── server.log
```

- 缩略图：图片用 Pillow（EXIF 旋转校正、透明底填深色），视频用 ffmpeg 截 0.5s 帧
- 缩略图生成失败不影响入库，前端会 fallback 到原图

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/items?limit=&offset=&tag=&kind=` | 列表（时间倒序） |
| GET | `/api/stats` | 统计（总数/图/视频/字节/标签分布） |
| GET | `/api/item/<id>` | 单条详情 |
| POST | `/api/upload` | multipart：`file`/`title`/`tags`/`source` |
| POST | `/api/delete` | `{"id": "..."}` |
| GET | `/f/<id>.<ext>` | 原文件（支持 Range，视频可拖动） |
| GET | `/f/<id>.<ext>?dl=1` | 强制下载 |
| GET | `/t/<id>.jpg` | 缩略图 |
| GET | `/` | 瀑布流界面 |

## 界面特性

- 瀑布流（CSS multi-column，自适应 5/4/3/2 列）
- 无限滚动 + 图片懒加载
- 顶部筛选：全部 / 图片 / 视频，标题标签搜索（前端过滤已加载部分）
- 点开大图：左右键切换、Esc 关闭、下载 / 原图 / 来源链接
- 视频支持 Range 请求，可拖动进度条

## 故障排查

```bash
S=/vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts
D=/vol1/picoclaw/.picoclaw/workspace/media-library

# 服务没起来
python3 $S/server.py --status
tail -30 $D/server.log

# 拉起 / 幂等保活
bash $S/ensure.sh

# 一致性自检（剔除孤儿记录 + 补缩略图）
python3 $S/server.py --repair

# 端口被占
ss -lntp | grep 18100

# 手工测接口
curl -s http://127.0.0.1:18100/api/stats
```

### ⚠️ 服务必须用 setsid 拉起

从 picoclaw 的 exec 里启动时，**如果不用 setsid，进程会随命令结束被回收**——
表现为"`ensure.sh` 返回 0、`stats` 也 200，但几十秒后再 curl 就 000"。
`ensure.sh` 已经用 `setsid nohup ... < /dev/null &` + `disown`，别再改成裸 `nohup ... &`。

### ⚠️ 锁的粒度

- **索引锁（`_lock`）内绝不能跑 ffmpeg/Pillow**：一次慢缩略图会把 `/api/stats` 也阻塞，
  整个服务看起来"死掉"（curl 10s 超时返回 000）。缩略图必须在锁外生成。
- 同一内容 ID 的并发上传用 `_id_lock(item_id)` 串行化。
  **早期版本在竞争失败分支里 `os.remove(dest)`，会把对方刚写好的文件删掉** →
  索引有记录、磁盘没文件（孤儿）。已修复，`--repair` 可清理历史孤儿。

### 检测孤儿记录

```bash
python3 $S/server.py --repair     # 自动剔孤儿 + 补缩略图
```

## 学习

```bash
python3 $S/learn.py recall "yt-dlp"
python3 $S/learn.py add "B站用 -f bv*+ba 会 merge，慢但画质好" --tags bilibili
python3 $S/learn.py list
```
