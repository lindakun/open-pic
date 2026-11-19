# 图库存量后处理（去重 + 视觉标题/标签补齐）设计

**日期**：2026-11-19
**状态**：待评审
**关联模块**：新增 `media-library/scripts/library_postprocess.py`、`media-library/scripts/library_postprocess_cron.sh`；复用 `db.py`、`media_proc.py`、`vision_filter.py`；微调 `x_scrape.py`

## 1. 背景与目标

当前图库存在约 318 条存量素材（216 张图片、102 条视频），存在以下历史遗留问题：
1. **标题与标签缺失**：大量 X 存量素材标题统一为 `@account X`，部分本地入库素材标题为随机编号串，缺少细分场景/穿搭/风格标签。
2. **近似重复未清理**：全库已存在多对汉明距离 ≤ 4 的近似重复图片（如同一张图同时存在高清原图与压缩图）；同时 102 条存量视频的 `phash` 全部为空，无法进行视觉去重。
3. **防止重复调用 API**：存量视觉补齐必须幂等且有明确标记，避免定时任务重复处理同一批素材造成 API 费用浪费。

本次新增独立的定时后处理模块，先完成低成本的**程序化去重**，再分批对未标注的存量素材调用视觉模型（`qwen3.8-27b`）**补齐中文标题与标签并清理非目标素材**。

## 2. 整体流程

```text
library_postprocess_cron.sh (setsid + flock 互斥)
   │
   ▼
Phase 1: 视频/图片指纹补齐与全库近似去重（纯本地计算，零 API 费用）
   ├─ 为 phash 为空的活跃图片/视频计算 dHash 并回填 media.db
   ├─ 按 kind 分组，Union-Find 聚类汉明距离 <= 4（视频附加时长差 <= 1.5s）
   └─ 每组保留 (像素最高 → 体积最大 → 最早入库)，合并副本标签后软删除副本
   │
   ▼
Phase 2: 存量视觉补齐与过滤（分批调用 vision_filter，每批默认 15 条）
   ├─ 查询 deleted_at IS NULL 且不含标签 "AI已标注" 的活跃素材
   ├─ 调用 vision_filter.analyze_media()（图片缩放 / 视频三联抽帧）
   ├─ API 异常 ──▶ 记录失败，不打 "AI已标注"，留待下轮重试
   ├─ keep == false ──▶ 打上 "AI已标注" 后软删除进回收站
   └─ keep == true  ──▶ 更新生成标题 + 合并去重标签 + "AI已标注"
```

> **执行顺序原则**：必须先执行 Phase 1 去重，再执行 Phase 2 视觉识别，避免对即将被淘汰的重复副本浪费视觉 API 调用。

## 3. 核心设计细节

### 3.1 防重复调用标记（`AI已标注`）
- 标记标签统一为 `AI已标注`（可通过环境变量 `X_POSTPROCESS_TAG` 配置）。
- **存量后处理**：仅查询不含 `AI已标注` 标签的活跃素材（`NOT EXISTS (SELECT 1 FROM item_tags it JOIN tags t ON t.id=it.tag_id WHERE it.item_id=i.id AND t.name=?)`）。处理完成（无论 `keep=true` 还是 `keep=false` 软删除）均打上 `AI已标注`；API 异常时不打标签以便下轮重试。
- **新抓取协同（`x_scrape.py`）**：`x_scrape.py` 在启用视觉识别且成功通过时，入库标签自动附带 `AI已标注`，使新入库素材直接跳过后处理 Phase 2，避免二次调用。

### 3.2 视频指纹补齐与近似去重
- **视频 dHash 计算**：使用 `ffmpeg` 抽取视频 50% 位置帧（时长未知或过短时降级抽首帧），再用 `media_proc._compute_dhash_pil()` 计算 16 位十六进制 `dHash` 写入 `items.phash`。
- **精确聚类去重**：
  - 图片：全量活跃图片比对 64-bit dHash 汉明距离，`<= 4` 判为近似重复（可通过 `--max-dist` 调整）。
  - 视频：全量活跃视频比对 64-bit dHash 汉明距离 `<= 4` **且** `abs(duration_a - duration_b) <= 1.5` 秒（防止不同视频仅中帧相似被误合并）。
  - 使用并查集（Union-Find）将传递相似的项聚为一组，每组按 `(-(width * height), -size, ts, id)` 选出最优保留项。
  - 将组内其余副本的标签去重合并到保留项后，调用 `db.soft_delete(dup_ids)` 将副本移入回收站。

### 3.3 并发与数据库安全
- 复用 `db.MediaDB(DATA/media.db)`（SQLite WAL 模式 + `_write_lock` + 30s 超时），`db.update_item()` 会自动同步 `items_fts` 全文检索索引，无需重启 `server.py`。
- `library_postprocess_cron.sh` 采用与 `x_scrape_cron.sh` 一致的 `setsid nohup` + `flock -n` 互斥锁机制（锁文件 `DATA/postprocess.lock`），避免定时任务重叠或被 5 分钟命令时限中断。
- 试运行模式（`--dry-run`）：同步执行，仅打印将回填、去重和待标注的候选清单，**不修改数据库、不软删除、不调用视觉 API**。

### 3.4 定时任务调度建议
- 推荐调度：`45 */2 * * *`（每两小时第 45 分钟执行，与 `15 */2 * * *` 的 X 抓取任务错开 30 分钟，避免高峰并发）。
- 每批视觉处理默认 `--batch 15`：存量全部消化后，日常无待处理素材时 Phase 2 查询为空，零 API 开销直接退出。

## 4. 验收计划

1. **单元测试（`media-library/scripts/test_library_postprocess.py`）**：
   - 视频 `phash` 缺失回填测试（mock `ffmpeg`）。
   - 图片与视频近似去重聚类测试：验证像素最高保留、标签合并、副本软删除，以及时长差异 > 1.5s 的视频不被误删。
   - Phase 2 视觉补齐测试：`keep=true` 更新标题并打上 `AI已标注`；`keep=false` 打上 `AI已标注` 并软删除；API 异常不打标不删除；已带 `AI已标注` 的素材不再触发 API 调用。
   - `--dry-run` 不修改数据库也不调用视觉 API。
2. **线上部署与验收**：
   - NAS 同步代码后先跑 `--dry-run`，确认待去重对数与待标注数量符合预期。
   - 手动触发一轮小批量真实执行（`--batch 5`），验证日志输出、去重进回收站及 `/app/` 标题标签更新效果。
   - 注册 PicoClaw 定时任务（`45 */2 * * *`）并 reload 生效。
