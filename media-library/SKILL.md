---
name: media-library
description: >
  open-pic 图片视频平台：通过定时自动抓取 X 账号图片与视频入库，向用户提供 Web 浏览，
  向管理员提供前台维护入口。也支持手工链接采集和本地文件上传。
  当用户要求检查定时抓取、维护图库，或提出"存到图片库"、"下载这个视频"、
  "帮我收一下这个链接"、"看看图片库"时使用。
  所有运行代码在 open-pic 仓库维护，提交并推送 GitHub 后才允许 NAS 拉取部署。
---

# 图片库（media-library）

本项目以**定时自动采集图片与视频**为主要数据来源：PicoClaw 定时触发 → 抓取、去重、入库 → 用户通过 `/app/` 浏览 → 管理员通过 `/admin/` 维护。手工链接采集和本地上传是补充能力。

## 代码来源与部署边界

- 本项目的采集脚本、服务端、用户前台、管理员前台、测试与部署脚本都必须在 `open-pic` Git 仓库维护；不得只在 NAS 技能目录、临时目录或会话里保留运行代码。
- NAS 上的本技能目录是部署副本，不是独立 Git 仓库；源码对应仓库内的 `media-library/`。
- 每次更新部署必须遵循：**本项目修改与测试 → Git 提交 → 推送 GitHub `origin/main` → NAS `/vol1/picoclaw/repos/open-pic` 执行 `git pull --ff-only origin main` → 同步部署副本 → 按需重启与验证**，完整流程以仓库根目录 `CLAUDE.md` 为准。
- 禁止跳过 GitHub 直接复制本地未提交代码到生产目录，也禁止只在 NAS 热改。部署前必须审查同步范围，`rsync --delete` 会删除仅存在于部署副本中的脚本。
- 数据目录 `/vol1/picoclaw/.picoclaw/workspace/media-library` 独立保存账号名单、断点、数据库与媒体；它不是代码目录。凭证、cookies、运行日志与真实媒体不要提交 Git。

## 定时自动采集（主流程）

当前 NAS 的 PicoClaw 任务按本地时区执行；定时配置保存在 `workspace/cron/jobs.json`，不是 Linux 用户 crontab，脚本自身不会安装或修改定时任务。

| 任务 | Cron 表达式 | 执行入口 |
|---|---|---|
| X 账号图片视频自动抓取 | `15 */2 * * *`，每两小时第 15 分钟 | `bash /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/x_scrape_cron.sh` |
| 存量后处理（去重与标注） | `45 */2 * * *`，每两小时第 45 分钟 | `bash /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/library_postprocess_cron.sh` |
| 图片库服务守护 | `0 * * * *`，每小时整点 | `bash /vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts/ensure.sh` |

`ensure.sh` 仅检查图片库并在不可用时拉起服务；**不能以保活成功代替自动采集验证**。`x_scrape_cron.sh` 默认通过 `setsid` / `nohup` 启动独立后台任务并立即返回，避免 PicoClaw 的 5 分钟命令时限中断采集；后台任务使用 `flock` 持锁到结束，先检查服务，再启动 `x_scrape.py`。保活进程不会继承采集锁；重复调度不会重叠采集。

- 名单来自数据目录的 `x_accounts.txt`，每行一个账号，可带 `@`，空行及 `#` 注释忽略；不把生产账号硬编码进脚本。
- 默认每次处理 **7 个账号、每账号至多 4 条推文**，`x_scrape_state.json` 保存轮转游标及各账号已见推文；失败或达到数量上限而未处理的推文不能误标为已见。
- 解析账号主页的原创与转发媒体；图片取 `name=orig` 原图，视频选择最高码率 MP4，视频默认按 30MB 上限做预估及下载后检查。
- 图片先检查原始像素，下载后再校验实际像素及体积：短边至少 320px，体积至少 20KB；不要套用手工 `ingest.py` 的 60KB 下限。
- 入库复用图片库的内容去重与近似图片提示；默认标签为 `X抓取,人物`，视频额外添加 `X视频`。
- 无需登录 X，依赖配置的 NAS 代理访问账号主页；页面通常只有最近约 4–5 条推文，不支持历史翻页，不能承诺抓全历史或两次轮询之间的所有更新。
- `x_scrape.log` 记录每轮结果，超过 5MB 保留末尾 2000 行；`x_scrape_runner.log` 只保留最近一轮后台进程输出，含退出码 `rc=0`（成功）或非零值（失败）。主程序抓取失败返回非零状态，损坏的状态文件报错退出，不清空已有断点；异步调度的返回码不是后台采集的最终结果。

```bash
S=/vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts

# 试运行：读取主页，不下载媒体、不入库、不推进断点，也不修改抓取日志
bash "$S/x_scrape_cron.sh" --dry-run --batch 1 --limit 1

# 投递一轮后台真实采集：会下载入库并更新断点
bash "$S/x_scrape_cron.sh"

# 人工同步诊断：等待本轮结束并返回实际退出码，勿用于有限时的 cron
bash "$S/x_scrape_cron.sh" --foreground
```

以上入口默认使用技能目录的 `venv/bin/python3`，不存在时才使用 `python3`；正常执行应使用 PicoClaw 的运行身份和环境。验证时检查实际 `x_scrape.log` 中的完成摘要、断点及素材变化，不能只看调度器显示的 `ok`；无新推文时新增数为零是正常结果。

## 手工采集（补充入口）

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

## 手工链接处理流程

1. `ingest.py` 传链接，带 `--tags`（从内容推断 1-3 个中文标签）
2. 看 stderr 里的 `✓ 新增 / ✓ 重复 / ✗ 失败`
3. 报告"入库 N 项"，附上界面地址

手工链接使用现有 `ingest.py`，定时账号采集使用现有 `x_scrape_cron.sh` / `x_scrape.py`；不要在 NAS 临时另写一套未纳入仓库的下载逻辑。

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
| `X_SCRAPE_PROXY` | `http://127.0.0.1:7890` | X 账号自动抓取使用的代理，与手工采集代理变量区分 |
| `X_SCRAPE_BATCH` | `7` | 定时入口每轮处理的账号数，`0` 表示全部 |
| `X_SCRAPE_LIMIT` | `4` | 定时入口每账号每轮的推文条数上限，`0` 表示本页全部；不是媒体数 |
| `X_SCRAPE_MAX_MB` | `30` | 定时入口的视频体积上限，目前不对图片应用此大小上限 |
| `X_SCRAPE_TAGS` | `X抓取,人物` | 定时入口的默认入库标签 |
| `X_VISION_ENABLED` | `1` | 是否开启 X 抓取视觉过滤与标题/标签生成（`0` 关闭） |
| `X_VISION_BASE_URL` | `https://sub.hhxxttxs.icu:8787` | OpenAI 兼容视觉接口地址 |
| `X_VISION_API_KEY` | 空 | 视觉接口密钥（也可写入数据目录 `vision_config.json`） |
| `X_VISION_MODEL` | `cloudflare-workers-ai/@cf/qwen/qwen3.8-27b` | 视觉模型 ID |
| `X_VISION_TIMEOUT` | `45` | 单次视觉识别请求超时秒数 |

`X_SCRAPE_BATCH/LIMIT/MAX_MB/TAGS` 由 shell 入口传给主程序；直接调用 `x_scrape.py` 时用对应命令行参数。主程序默认 `--batch 0`，与定时入口的默认 `7` 区分。`vision_config.json` 置于运行数据目录 `MEDIA_LIB_DIR` 下时，环境变量优先级高于文件配置。

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
├── files/       # 原文件，文件名 = <sha1前16位>.<ext>
├── thumbs/      # 多规格缩略图（<id>.jpg + <id>_{sm,md,lg}.webp）
├── previews/    # 视频 3 秒悬停动态 WebP 预览
├── play/        # 视频浏览器兼容播放副本（H.264 + AAC + faststart）
├── media.db     # SQLite 主库（WAL + FTS5 全文索引 + 画板 + 任务表）
├── index.json.migrated.bak  # 旧版索引自动迁移备份
├── x_accounts.txt          # 自动采集账号名单（运行配置，不硬编码到脚本）
├── x_scrape_state.json     # 轮转游标、已见推文与最近处理时间
├── x_scrape.lock           # 定时采集互斥锁
├── x_scrape.log            # 定时采集历史日志
├── x_scrape_runner.log     # 最近一轮后台输出及真实退出码
├── server.pid.lock         # 服务 PID 写入和清理的互斥锁
├── server.pid
└── server.log
```

- 缩略图：图片用 Pillow（EXIF 旋转校正、透明底填深色），视频用 ffmpeg 截 0.5s 帧并压制多规格 WebP
- 缩略图生成失败不影响入库，前端会 fallback 到原图

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/items?limit=&offset=&q=&tag=&kind=&sort=` | 多维组合检索与分页列表 |
| GET | `/api/stats` | 统计（总数/图/视频/字节/标签/平台分布/回收站） |
| GET | `/api/item/<id>` & `/api/item/<id>/similar` | 单条详情 & 视觉相似推荐 |
| PATCH | `/api/item/<id>` | 行内编辑标题、标签、备注 |
| POST | `/api/upload` | multipart：`file`/`title`/`tags`/`source` |
| POST | `/api/ingest-url` | Web 端异步抓取链接入库 |
| POST | `/api/delete` / `/api/restore` | 软删除（默认）与回收站恢复 |
| POST | `/api/items/batch` / `/api/items/download-zip` | 批量打标/画板/删除 & ZIP 打包下载 |
| GET/POST | `/api/collections` | 画板/专辑管理 |
| GET | `/api/jobs` & `/api/jobs/stream` | 后台任务队列与 SSE 实时推送 |
| GET | `/f/<id>.<ext>` | 原文件（支持 Range、ETag/304、`?play=1` 兼容流、`?dl=1` 下载） |
| GET | `/t/<id>_md.webp` / `/t/<id>.jpg` | 多规格 WebP / 兼容 JPEG 缩略图 |
| GET | `/p/<id>.webp` | 视频悬停动态预览 |
| GET | `/s/<id>` | 独立分享页（带 OpenGraph / Twitter Card 卡片） |
| GET | `/` | 站点入口，默认跳转用户前台 |
| GET | `/app/` | 用户前台：图片视频浏览、搜索、筛选与播放 |
| GET | `/admin/` | 管理员前台：素材维护、回收站、任务与统计 |

## 界面特性

- 无抖动 JS Masonry 瀑布流 + 等高网格 + 列表视图，暗黑/浅色双主题
- 左侧边栏：全部资产、回收站、统计与存储看板、画板/专辑、方向/平台/主色调筛选、热门标签云
- 全库后端检索（标题/标签/来源/OCR）、全屏拖拽与剪贴板贴图上传、URL 异步投递
- 专业灯箱：图片滚轮/双击缩放与拖拽平移、视频倍速/循环/画中画、右侧元数据编辑抽屉与相似图推荐

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

### 保活与抓取应分别验证

- 页面正常或 `ensure.sh` 成功，不代表 `x_scrape_cron.sh` 存在、可执行或已经完成采集；同时检查入口及主程序、实际抓取日志和状态文件。
- `--dry-run` 仍访问 X 主页，但不写入已见推文/轮转游标、不下载入库；它不能替代真实采集结果验证。
- 部署前核查服务运行用户、整点保活和正在执行的抓取，避免并发重启；若健康接口正常但 PID 状态异常，先核对实际进程，不要连续重启。
- 缺失或异常脚本必须回到本仓库修复、测试、提交、推送 GitHub，再由 NAS 拉取恢复；不要把清空账号名单或断点作为修复手段。

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
