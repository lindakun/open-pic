### 必须修改项

1. **路径冲突（V2-17）**：`server.py:407` 已占用 `/p/{preview_name}` 提供视频动态预览，资产分享页改用 `/p/{slug}-{shortId}` 会直接冲突，须更换路由前缀（如 `/a/`）。
2. **检索现状误判与 trigram 盲区（V2-07）**：`db.py:109` 虽建了 `items_fts`，但 `query_items`（`db.py:492`）实际未查 FTS 而是全字段 `LIKE`；且 SQLite `trigram` 不支持 `<3` 字符（中文单/双字词无法走索引），与“两字词准确率”验收矛盾，应改用预分词（如 jieba/2-gram）写入 FTS。
3. **瀑布流与缩略图口径冲突（V2-05/06/15）**：`app.js:142` 已是用 `aspect_ratio` 计算的绝对定位瀑布流，并非 `column-count`；`media_proc.py:17` 现有规格为 `360/720/1440`，V2-05 改为 `320/640/1280` 属降级且破坏存量兼容；V2-05 预生成 4 档 AVIF/WebP 与 V2-15 动态 `/img/` 重复建设，应合并。
4. **同步阻塞、OOM 与任务丢失风险（V2-05/08/13/19）**：`store_file`（`server.py:218`）同步生成缩略图，叠加 AVIF/OCR 会阻塞上传，必须下沉队列；`db.py:519/545` 色彩/相似检索全表拉取及 `server.py:615` `BytesIO` 全内存打包 ZIP 在万级资产下易超时/OOM；`TaskManager` 重启会丢失库内 `pending/running` 任务，需补启动恢复；`_physical_remove_items` 需联动清理新增缓存文件。

### 建议修改项

- **工作量与技术栈**：总计 117 人日偏失衡。V2-18（PWA）在局域网 NAS 场景收益低（4d 可砍）；无构建原生 JS 难以稳定承载虚拟滚动、多图对比、标签图谱与状态同步，建议至少拆分为原生 ES Module 或引入轻量构建，并补充 `/browse` 的后端路由返回；V2-08（CLIP ONNX + OCR）在无 GPU NAS 上内存与 CPU 占用过高且 10d 偏低估，建议移出首期。
- **写锁竞争**：`db.py:153` 全局 `_write_lock` 串行化写入，V2-19 高频埋点与异步任务并发下建议批量合并事务。

### 确认无问题项

- `aspect_ratio`、`palette_json`、`phash`、`ocr_text` 字段与 `TaskManager`+SSE 底座设计自洽，可直接复用；v1 CLI 与接口兼容约束明确。

### 结论

**有条件通过**。须先修正 `/p/` 路由冲突、FTS `trigram` 方案、V2-05/15 重复管线及同步阻塞/全表扫描隐患，并裁剪 V2-08/V2-18 后方可实施。
