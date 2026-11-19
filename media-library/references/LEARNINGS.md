# 学习沉淀（自动维护，勿手改分隔符）

> 本文件由 `scripts/learn.py` 读写。每条记录都有 `权重`（被复现/命中次数）与 `证据`。
> 原则：**没有证据不记录；权重低的可淘汰；与正文冲突时以权重高者为先并回写 SKILL.md。**

### L-16e69cb1 坑
- 签名: ensure.sh 返回成功但几十秒后服务 000 失联
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: ensure.sh 返回成功但几十秒后服务 000 失联
- 做法: 从 picoclaw exec 拉起的进程会随命令结束被回收；必须 setsid nohup ... < /dev/null & 再 disown
- 证据: 23:41 与 23:42 两次 拉起成功 pid=xxx，随后 curl stats 返回 000，server.log 无新日志
- 标签: 进程,setsid,守护
- 置信: 高

### L-37870287 坑
- 签名: 跟进详情页时把 /tag/96819 /wallpaper/fav/xxx 当内容页，白跑几十个请求
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 跟进详情页时把 /tag/96819 /wallpaper/fav/xxx 当内容页，白跑几十个请求
- 做法: DETAIL_HINT 只认明确的短 ID 内容页模式（/w/xxxx、/status/123、纯数字ID）；SKIP_HINT 排掉 /tag/ /category/ /user/ /page/ /wallpaper/fav
- 证据: 早期宽泛正则 /w/|/p/|/photo|/detail|\d{4,} 命中 tag 页，2 分钟没结果
- 标签: 爬取,详情页,正则
- 置信: 高

### L-3cca2777 坑
- 签名: B站/YouTube 等外网视频直连超时
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: B站/YouTube 等外网视频直连超时
- 做法: yt-dlp 必须加 --proxy http://127.0.0.1:7890（mihomo）；已在 download_with_ytdlp 里默认加，可用 MEDIA_LIB_PROXY 覆盖
- 证据: 直连 B站 simulate 超时；加代理后 1s 拿到标题
- 标签: 代理,bilibili,mihomo
- 置信: 高

### L-5bcc9053 坑
- 签名: server.py 收到 SIGTERM 后端口已停但进程不退出，--stop 超时报'停止尚未完成'，且旧 PID 记录让 ensure.sh 以'已在运行'拒绝拉起，服务持续离线
- 权重: 1
- 首次/最近: 2026-11-19 / 2026-11-19
- 场景: server.py 收到 SIGTERM 后端口已停但进程不退出，--stop 超时报'停止尚未完成'，且旧 PID 记录让 ensure.sh 以'已在运行'拒绝拉起，服务持续离线
- 做法: uvicorn.run 增加 timeout_graceful_shutdown=5（SIGTERM 后最多等 5s 强制退出，落在 --stop 的 10s 检测窗口内）；残留实例用 pkill -9 -f 'server[.]py --port 18100' 清理后 rm server.pid 再 ensure.sh
- 证据: 17:50 SIGTERM 后 18:08 进程仍在且 /healthz offline；本地验证：持有 SSE 连接时 SIGTERM 后 5s 退出；pkill 模式用 server[.]py 防止误杀命令自身
- 标签: 进程,信号,SSE,优雅退出,stop
- 置信: 高

### L-767205a1 坑
- 签名: YouTube 下载报 Sign in to confirm you're not a bot
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: YouTube 下载报 Sign in to confirm you're not a bot
- 做法: 需导出 cookies.txt，用 --cookies 传入（环境变量 MEDIA_LIB_YTDLP_COOKIES）
- 证据: yt-dlp aqz-KE-bpKQ 直连与走代理 7890 均报 bot 校验
- 标签: youtube,yt-dlp,cookies
- 置信: 高

### L-8695bf5b 坑
- 签名: cron job 用 command 模式仍然每小时往微信推一条消息
- 权重: 1
- 首次/最近: 2026-11-11 / 2026-11-11
- 场景: cron job 用 command 模式仍然每小时往微信推一条消息
- 做法: command 模式并非静默：pkg/tools/cron.go ExecuteJob 执行完仍会 PublishOutbound 到 payload.channel。真要静默必须把 payload.channel 改成内部通道 cli（pkg/channels/manager.go dispatchLoop 对 IsInternalChannel 直接 continue 丢弃），to 填 direct。改完需 POST /reload
- 证据: 图片库守护 job 原 payload.kind=agent_turn/channel=weixin，每小时推一条巡检提示
- 标签: cron,静默,微信,通知
- 置信: 高

### L-9eaf95d6 坑
- 签名: 服务所有接口卡死/超时(code=000)
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 服务所有接口卡死/超时(code=000)
- 做法: 缩略图生成(ffmpeg/Pillow)必须在索引锁外做；放进 _lock 内会让 /api/stats 也阻塞
- 证据: store_file 原版把 make_thumb 放在 with _lock 内，传大视频时 curl api/stats 超时 10s 返回 000
- 标签: 并发,锁,性能
- 置信: 高

### L-c92e7e49 坑
- 签名: 空目录名 {scripts,references} 出现在技能目录
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 空目录名 {scripts,references} 出现在技能目录
- 做法: mkdir -p 时没用 brace expansion（bash 默认支持但工具 exec 逐条发命令时可能不走 bash）；建目录要写成两条独立 mkdir
- 证据: skills/media-library 下出现字面量目录 {scripts,references}
- 标签: 环境,坑
- 置信: 中

### L-cf87d8bf 坑
- 签名: X/Twitter 纯图片推文，yt-dlp 报 No video could be found in this tweet，ingest.py 直接判失败
- 权重: 1
- 首次/最近: 2026-11-17 / 2026-11-17
- 场景: X/Twitter 纯图片推文，yt-dlp 报 No video could be found in this tweet，ingest.py 直接判失败
- 做法: 别放弃：走 syndication API 拿图。GET https://cdn.syndication.twimg.com/tweet-result?id=<推文ID>&token=4 （经代理）→ json.mediaDetails[].media_url_https，去重后逐个加 ?name=orig 下载原图（orig 比 large 大 30-50%，实测 480KB vs 329KB）。脚本已固化为 scripts/tw_photos.py <推文ID...>，再用 ingest.py 传本地文件入库。
- 证据: 11 条里 5 条失败全是纯图片推文；2122294026401681413 拿到 20 张、2122377450730783191 拿到 20 张
- 标签: twitter,图片,ys-dlp,fallback
- 置信: 高

### L-e08d8ddd 技巧
- 签名: 无扩展名的图片 CDN 链接（如 picsum.photos/900/1200）被当成网页解析
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 无扩展名的图片 CDN 链接（如 picsum.photos/900/1200）被当成网页解析
- 做法: 先发 Range: bytes=0-2047 探测 Content-Type，是 image/* video/* 就直接下载；不要靠 URL 后缀判断
- 证据: picsum.photos 无后缀，旧逻辑走 extract_from_html 拿到 0 候选
- 标签: cdn,直链,探测
- 置信: 高

### L-f1969c38 技巧
- 签名: 列表页/相册页只能抓到 300x200 缩略图
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 列表页/相册页只能抓到 300x200 缩略图
- 做法: 三层护栏：文件名噪音过滤 + probe_size 读 Content-Range 跳小于60KB + Pillow 查真实像素小于320px丢弃；必要时跟进详情页取 og:image 原图
- 证据: wallhaven 搜索页 24 张全是 /small/ 300x200，跟进 /w/xxxx 详情页后拿到 7008x4672 原图
- 标签: 缩略图,质量,列表页
- 置信: 高

### L-f9702128 技巧
- 签名: 20MB 视频 multipart 上传报 Remote end closed connection
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 20MB 视频 multipart 上传报 Remote end closed connection
- 做法: 客户端用 http.client 手工流式 send 分块；服务端先把 body 流式落盘再喂 BytesFeedParser，不要一次性 read(n) 进内存
- 证据: 旧版 upload() 一次性读全文件 + 服务端 read(n)，20MB mp4 上传失败
- 标签: 上传,大文件,内存
- 置信: 高

### L-fcd02ac2 坑
- 签名: 索引有记录但磁盘上文件不存在（孤儿记录）
- 权重: 1
- 首次/最近: 2026-11-10 / 2026-11-10
- 场景: 索引有记录但磁盘上文件不存在（孤儿记录）
- 做法: 并发上传同内容时，竞争失败分支曾 os.remove(dest) 删掉对方文件；改为 _id_lock(item_id) 按 ID 串行化，并在 server.py --repair 里剔除孤儿+补缩略图
- 证据: defa5c3c8bf2911f 在 index.json 有 4937KB 记录，files/ 下无对应文件
- 标签: 并发,锁,一致性,孤儿
- 置信: 高

