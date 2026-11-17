#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite 数据库层（WAL 模式 + FTS5 全文检索 + 软删除 + 画板 + 异步任务）"""

import json
import os
import re
import secrets
import shutil
import sqlite3
import search_index
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    file TEXT NOT NULL,
    thumb TEXT,
    play_file TEXT,
    preview_file TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('image', 'video')),
    ext TEXT NOT NULL,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    source_platform TEXT NOT NULL DEFAULT 'local',
    author TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    aspect_ratio REAL NOT NULL DEFAULT 1.0,
    duration REAL NOT NULL DEFAULT 0.0,
    fps REAL NOT NULL DEFAULT 0.0,
    codec TEXT NOT NULL DEFAULT '',
    dominant_color TEXT NOT NULL DEFAULT '#1a1d24',
    palette_json TEXT NOT NULL DEFAULT '[]',
    exif_json TEXT NOT NULL DEFAULT '{}',
    phash TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    -- 授权与署名（REQ-V2-20 C-11）
    license TEXT NOT NULL DEFAULT '',
    license_url TEXT NOT NULL DEFAULT '',
    credit TEXT NOT NULL DEFAULT '',
    copyright_holder TEXT NOT NULL DEFAULT '',
    commercial_ok INTEGER NOT NULL DEFAULT 1,
    license_expires_at INTEGER DEFAULT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    downloads INTEGER NOT NULL DEFAULT 0,
    ts INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted_at INTEGER DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_ts ON items(ts DESC);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind);
CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deleted_at);
CREATE INDEX IF NOT EXISTS idx_items_phash ON items(phash);
CREATE INDEX IF NOT EXISTS idx_items_platform ON items(source_platform);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS item_tags (
    item_id TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    PRIMARY KEY (item_id, tag_id),
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag_id);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cover_item_id TEXT DEFAULT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    added_at INTEGER NOT NULL,
    PRIMARY KEY (collection_id, item_id),
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingest_jobs(status, created_at DESC);

-- 客户选片与批注（REQ-V2-20 C-14）
CREATE TABLE IF NOT EXISTS review_links (
    token TEXT PRIMARY KEY,
    collection_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    expires_at INTEGER DEFAULT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_review_links_col ON review_links(collection_id);

CREATE TABLE IF NOT EXISTS review_marks (
    token TEXT NOT NULL,
    item_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    note TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (token, item_id),
    FOREIGN KEY (token) REFERENCES review_links(token) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_review_marks_state ON review_marks(token, state);

-- 向量检索（REQ-V2-20 B-07 / B-08）：vec 为 float32 紧凑存储
CREATE TABLE IF NOT EXISTS item_embeddings (
    item_id TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    dim INTEGER NOT NULL DEFAULT 512,
    vec BLOB NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON item_embeddings(model_version);

-- AI 标签否决黑名单（B-07 验收 3：否决过的组合不再出现）
CREATE TABLE IF NOT EXISTS tag_rejections (
    item_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (item_id, tag)
);

-- 标签治理：别名与层级（REQ-V2-20 B-09）
CREATE TABLE IF NOT EXISTS tag_aliases (
    alias TEXT PRIMARY KEY,
    tag_id INTEGER NOT NULL,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

-- 个人工作区：喜欢（REQ-V2-20 C-15）
CREATE TABLE IF NOT EXISTS item_flags (
    item_id TEXT PRIMARY KEY,
    liked INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    item_id UNINDEXED,
    title,
    name,
    tags_text,
    source,
    notes,
    ocr_text,
    seg,
    tokenize='unicode61'
);
"""


def _hamming_hex(h1: str, h2: str) -> int:
    """计算两个十六进制感知哈希的汉明距离"""
    if not h1 or not h2 or len(h1) != len(h2):
        return 999
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except ValueError:
        return 999


def _hex_to_rgb(hx: str) -> Tuple[int, int, int]:
    hx = hx.lstrip("#")
    if len(hx) != 6:
        return (26, 29, 36)
    try:
        return (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16))
    except ValueError:
        return (26, 29, 36)


def _color_distance(c1: str, c2: str) -> float:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


class MediaDB:
    """线程安全的 SQLite 媒体库仓储"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._write_lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._write_lock, self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate_columns(conn)
            self._migrate_fts_seg(conn)
            conn.commit()

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        """为存量库补齐新增列。

        SQLite 的 ADD COLUMN 只支持常量默认值，正好满足本场景。
        逐列检查后再加，保证幂等（可重复启动）。
        """
        wanted = {
            "license": "TEXT NOT NULL DEFAULT ''",
            "license_url": "TEXT NOT NULL DEFAULT ''",
            "credit": "TEXT NOT NULL DEFAULT ''",
            "copyright_holder": "TEXT NOT NULL DEFAULT ''",
            "commercial_ok": "INTEGER NOT NULL DEFAULT 1",
            "license_expires_at": "INTEGER DEFAULT NULL",
            "status": "TEXT NOT NULL DEFAULT 'published'",
            "slug": "TEXT NOT NULL DEFAULT ''",
            "publish_at": "INTEGER DEFAULT NULL",
        }
        existing = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
        for col, decl in wanted.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE items ADD COLUMN {col} {decl}")

        # 标签层级（B-09）：tags 表补 parent_id，旧库一并升级
        tag_cols = {r[1] for r in conn.execute("PRAGMA table_info(tags)").fetchall()}
        if "parent_id" not in tag_cols:
            conn.execute("ALTER TABLE tags ADD COLUMN parent_id INTEGER DEFAULT NULL")

    def _migrate_fts_seg(self, conn: sqlite3.Connection) -> None:
        """迁移旧库的 FTS 表，补齐预分词列 seg（REQ-V2-20 B-06）。

        旧版本 items_fts 没有 seg 列，直接查会报错。
        FTS5 虚拟表不支持 ALTER TABLE ADD COLUMN，只能重建并回填。
        """
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items_fts)").fetchall()}
        if not cols or "seg" in cols:
            return

        conn.executescript(
            """
            DROP TABLE IF EXISTS items_fts;
            CREATE VIRTUAL TABLE items_fts USING fts5(
                item_id UNINDEXED, title, name, tags_text, source, notes, ocr_text, seg,
                tokenize='unicode61'
            );
            """
        )
        # 回填全部条目
        rows = conn.execute(
            "SELECT id, title, name, source, notes, ocr_text FROM items"
        ).fetchall()
        for row in rows:
            tag_rows = conn.execute(
                "SELECT t.name FROM tags t JOIN item_tags it ON t.id=it.tag_id WHERE it.item_id=?",
                (row["id"],),
            ).fetchall()
            tags_text = " ".join(r["name"] for r in tag_rows)
            seg_text = search_index.build_fts_text(
                row["title"], row["name"], tags_text, row["notes"], row["ocr_text"]
            )
            conn.execute(
                "INSERT INTO items_fts(item_id, title, name, tags_text, source, notes, ocr_text, seg)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    row["id"], row["title"], row["name"], tags_text,
                    row["source"], row["notes"], row["ocr_text"], seg_text,
                ),
            )

    # ---------- 迁移与同步 ----------

    def migrate_from_index_json(self, index_json_path: str) -> int:
        """如果数据库为空且存在 index.json，则无损迁移存量记录"""
        if not os.path.isfile(index_json_path):
            return 0
        with self.connect() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            if cnt > 0:
                return 0
        try:
            with open(index_json_path, "r", encoding="utf-8") as f:
                raw_items = json.load(f)
        except Exception:
            return 0
        if not isinstance(raw_items, list) or not raw_items:
            return 0

        migrated = 0
        for it in raw_items:
            iid = it.get("id")
            if not iid:
                continue
            rec = {
                "id": iid,
                "file": it.get("file", ""),
                "thumb": it.get("thumb"),
                "play_file": it.get("play_file"),
                "preview_file": it.get("preview_file"),
                "kind": it.get("kind", "image"),
                "ext": it.get("ext", ".jpg"),
                "name": it.get("name", iid),
                "title": it.get("title") or it.get("name") or iid,
                "source": it.get("source", ""),
                "source_platform": it.get("source_platform", self.detect_platform(it.get("source", ""))),
                "author": it.get("author", ""),
                "notes": it.get("notes", ""),
                "size": int(it.get("size", 0)),
                "width": int(it.get("width", 0)),
                "height": int(it.get("height", 0)),
                "aspect_ratio": float(it.get("aspect_ratio", 1.0)),
                "duration": float(it.get("duration", 0.0)),
                "fps": float(it.get("fps", 0.0)),
                "codec": it.get("codec", ""),
                "dominant_color": it.get("dominant_color", "#1a1d24"),
                "palette_json": json.dumps(it.get("palette", []), ensure_ascii=False),
                "exif_json": json.dumps(it.get("exif", {}), ensure_ascii=False),
                "phash": it.get("phash", ""),
                "ocr_text": it.get("ocr_text", ""),
                "ts": int(it.get("ts", time.time())),
                "tags": it.get("tags") or [],
            }
            if self.upsert_item(rec):
                migrated += 1

        # 备份原 index.json，保留历史依据
        bak = index_json_path + ".migrated.bak"
        if not os.path.exists(bak):
            try:
                shutil.copy2(index_json_path, bak)
            except Exception:
                pass
        return migrated

    @staticmethod
    def detect_platform(source: str) -> str:
        if not source:
            return "local"
        s = source.lower()
        for host, name in (
            ("x.com", "X"),
            ("twitter.com", "X"),
            ("bilibili.com", "B站"),
            ("b23.tv", "B站"),
            ("youtube.com", "YouTube"),
            ("youtu.be", "YouTube"),
            ("weibo.", "微博"),
            ("xiaohongshu.com", "小红书"),
            ("xhslink.com", "小红书"),
            ("douyin.com", "抖音"),
            ("tiktok.com", "TikTok"),
            ("instagram.com", "Instagram"),
            ("wallhaven.cc", "Wallhaven"),
            ("pinterest.", "Pinterest"),
            ("reddit.com", "Reddit"),
        ):
            if host in s:
                return name
        return "web" if s.startswith("http") else "local"

    # ---------- CRUD ----------

    def _sync_fts(self, conn: sqlite3.Connection, item_id: str):
        row = conn.execute(
            "SELECT id, title, name, source, notes, ocr_text FROM items WHERE id=?",
            (item_id,),
        ).fetchone()
        conn.execute("DELETE FROM items_fts WHERE item_id=?", (item_id,))
        if not row:
            return
        tag_rows = conn.execute(
            "SELECT t.name FROM tags t JOIN item_tags it ON t.id=it.tag_id WHERE it.item_id=?",
            (item_id,),
        ).fetchall()
        tags_text = " ".join(r["name"] for r in tag_rows)
        # 预分词：中文按 jieba（缺失时 2-gram）切分后写入 seg 列，
        # 使两字词也能被 FTS 索引命中（unicode61 会把中文切成单字）
        seg_text = search_index.build_fts_text(
            row["title"], row["name"], tags_text, row["notes"], row["ocr_text"]
        )
        conn.execute(
            "INSERT INTO items_fts(item_id, title, name, tags_text, source, notes, ocr_text, seg)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                row["id"],
                row["title"],
                row["name"],
                tags_text,
                row["source"],
                row["notes"],
                row["ocr_text"],
                seg_text,
            ),
        )

    def _set_tags_tx(self, conn: sqlite3.Connection, item_id: str, tags: List[str], source: str = "manual"):
        conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
        seen = set()
        for raw in tags:
            t = raw.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (t,))
            tid = conn.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()["id"]
            conn.execute(
                "INSERT OR IGNORE INTO item_tags(item_id, tag_id, source) VALUES (?,?,?)",
                (item_id, tid, source),
            )

    def upsert_item(self, rec: Dict[str, Any]) -> bool:
        """插入或更新条目，返回是否为新增"""
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            exists = conn.execute("SELECT id FROM items WHERE id=?", (rec["id"],)).fetchone()
            if exists:
                return False
            conn.execute(
                """
                INSERT INTO items(
                    id, file, thumb, play_file, preview_file, kind, ext, name, title,
                    source, source_platform, author, notes, size, width, height, aspect_ratio,
                    duration, fps, codec, dominant_color, palette_json, exif_json, phash, ocr_text,
                    license, license_url, credit, copyright_holder, commercial_ok, license_expires_at,
                    ts, updated_at, deleted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                """,
                (
                    rec["id"],
                    rec["file"],
                    rec.get("thumb"),
                    rec.get("play_file"),
                    rec.get("preview_file"),
                    rec["kind"],
                    rec["ext"],
                    rec["name"],
                    rec["title"],
                    rec.get("source", ""),
                    rec.get("source_platform") or self.detect_platform(rec.get("source", "")),
                    rec.get("author", ""),
                    rec.get("notes", ""),
                    int(rec.get("size", 0)),
                    int(rec.get("width", 0)),
                    int(rec.get("height", 0)),
                    float(rec.get("aspect_ratio", 1.0)),
                    float(rec.get("duration", 0.0)),
                    float(rec.get("fps", 0.0)),
                    rec.get("codec", ""),
                    rec.get("dominant_color", "#1a1d24"),
                    rec.get("palette_json") or json.dumps(rec.get("palette", []), ensure_ascii=False),
                    rec.get("exif_json") or json.dumps(rec.get("exif", {}), ensure_ascii=False),
                    rec.get("phash", ""),
                    rec.get("ocr_text", ""),
                    rec.get("license", ""),
                    rec.get("license_url", ""),
                    rec.get("credit", ""),
                    rec.get("copyright_holder", ""),
                    1 if rec.get("commercial_ok", True) else 0,
                    rec.get("license_expires_at"),
                    int(rec.get("ts", now)),
                    now,
                ),
            )
            self._set_tags_tx(conn, rec["id"], rec.get("tags") or [])
            self._sync_fts(conn, rec["id"])
            conn.commit()
            return True

    def update_media_fields(self, item_id: str, **fields) -> None:
        """异步处理完成后回写媒体字段（REQ-V2-20 D-16）。

        只允许白名单列，避免调用方拼错列名或写入不该改的字段。
        """
        allowed = {
            "width", "height", "aspect_ratio", "duration", "fps", "codec",
            "dominant_color", "palette_json", "exif_json", "phash", "thumb",
            "play_file", "preview_file",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [int(time.time()), item_id]
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE items SET {sets}, updated_at=? WHERE id=?", params)
            conn.commit()

    def update_license(self, item_id: str, **fields) -> Optional[Dict[str, Any]]:
        """更新授权与署名信息（REQ-V2-20 C-11）。"""
        allowed = {
            "license", "license_url", "credit", "copyright_holder",
            "commercial_ok", "license_expires_at", "status", "slug",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_item(item_id)
        if "commercial_ok" in updates:
            updates["commercial_ok"] = 1 if updates["commercial_ok"] else 0
        sets = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [int(time.time()), item_id]
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE items SET {sets}, updated_at=? WHERE id=?", params)
            conn.commit()
        return self.get_item(item_id)

    def _hydrate_rows(self, conn: sqlite3.Connection, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        tag_map: Dict[str, List[str]] = {i: [] for i in ids}
        for tr in conn.execute(
            f"""
            SELECT it.item_id, t.name
            FROM item_tags it JOIN tags t ON it.tag_id=t.id
            WHERE it.item_id IN ({placeholders})
            ORDER BY t.name
            """,
            ids,
        ):
            tag_map[tr["item_id"]].append(tr["name"])

        col_map: Dict[str, List[int]] = {i: [] for i in ids}
        for cr in conn.execute(
            f"SELECT item_id, collection_id FROM collection_items WHERE item_id IN ({placeholders})",
            ids,
        ):
            col_map[cr["item_id"]].append(cr["collection_id"])

        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = tag_map.get(r["id"], [])
            d["collections"] = col_map.get(r["id"], [])
            try:
                d["palette"] = json.loads(d.pop("palette_json", "[]") or "[]")
            except Exception:
                d["palette"] = []
            try:
                d["exif"] = json.loads(d.pop("exif_json", "{}") or "{}")
            except Exception:
                d["exif"] = {}
            out.append(d)
        return out

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return None
            return self._hydrate_rows(conn, [row])[0]

    def update_item(self, item_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {
            "title", "source", "source_platform", "author", "notes",
            "thumb", "play_file", "preview_file", "width", "height",
            "aspect_ratio", "duration", "fps", "codec", "dominant_color",
            "palette_json", "exif_json", "phash", "ocr_text",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "source" in updates and "source_platform" not in updates:
            updates["source_platform"] = self.detect_platform(updates["source"])
        with self._write_lock, self.connect() as conn:
            exists = conn.execute("SELECT id FROM items WHERE id=?", (item_id,)).fetchone()
            if not exists:
                return None
            if updates:
                updates["updated_at"] = int(time.time())
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE items SET {sets} WHERE id=?", (*updates.values(), item_id))
            if "tags" in fields and isinstance(fields["tags"], list):
                self._set_tags_tx(conn, item_id, fields["tags"])
            self._sync_fts(conn, item_id)
            conn.commit()
        return self.get_item(item_id)

    # 允许的状态流转（C-12 验收 1）：archived 不能直接回 published
    STATUS_TRANSITIONS = {
        "draft": {"published", "archived"},
        "published": {"draft", "archived"},
        "archived": {"draft"},
    }

    def set_status(self, item_id: str, status: str,
                   publish_at: Optional[int] = None) -> Tuple[bool, str]:
        """设置发布状态与定时发布时间（REQ-V2-20 C-12）。

        返回 (ok, message)；非法流转返回 False 与允许路径，由路由转 409。
        """
        if status not in ("draft", "published", "archived"):
            return False, "状态必须是 draft / published / archived"
        with self._write_lock, self.connect() as conn:
            row = conn.execute("SELECT status FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return False, "资源不存在"
            current = row["status"] or "published"
            if status != current:
                allowed = self.STATUS_TRANSITIONS.get(current, set())
                if status not in allowed:
                    return False, (
                        f"不允许从 {current} 直接流转到 {status}；"
                        f"允许的目标：{sorted(allowed) or '无'}"
                    )
            conn.execute(
                "UPDATE items SET status=?, publish_at=?, updated_at=? WHERE id=?",
                (status, publish_at, int(time.time()), item_id),
            )
            conn.commit()
            return True, "ok"

    def publish_due_items(self) -> int:
        """把到期的定时发布项落为 published（C-12：调度侧保障）。

        查询侧另有惰性兜底，两者互为补充，任一漏跑都不影响可见性。
        """
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE items SET status='published', updated_at=?"
                " WHERE status='draft' AND publish_at IS NOT NULL AND publish_at <= ?",
                (now, now),
            )
            conn.commit()
            return cur.rowcount or 0

    def increment_counter(self, item_id: str, col: str):
        if col not in ("views", "downloads"):
            return
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE items SET {col}={col}+1 WHERE id=?", (item_id,))
            conn.commit()

    def query_items(
        self,
        limit: int = 60,
        offset: int = 0,
        q: str = "",
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        kind: str = "",
        ext: str = "",
        orientation: str = "",
        platform: str = "",
        collection_id: Optional[int] = None,
        color: str = "",
        sort: str = "newest",
        deleted: bool = False,
        status: str = "",
        include_unpublished: bool = False,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        where = ["i.deleted_at IS NOT NULL" if deleted else "i.deleted_at IS NULL"]
        params: List[Any] = []

        # 标签别名映射（B-09）：一次查出，避免在循环里反复开连接
        alias_map: Dict[str, str] = {}
        if tags or exclude_tags:
            with self.connect() as _c:
                for r in _c.execute(
                    "SELECT a.alias, t.name FROM tag_aliases a JOIN tags t ON t.id=a.tag_id"
                ).fetchall():
                    alias_map[r["alias"]] = r["name"]

        # 发布状态（REQ-V2-20 C-12）：
        #   - 默认只出 published，且定时到期的 draft 视为已发布（惰性查询兜底）
        #   - 管理端可用 status= 显式查某一状态，或 include_unpublished 查全部
        if status:
            where.append("i.status = ?")
            params.append(status)
        elif not include_unpublished:
            where.append(
                "(i.status = 'published' OR (i.status = 'draft'"
                " AND i.publish_at IS NOT NULL AND i.publish_at <= ?))"
            )
            params.append(int(time.time()))

        if kind in ("image", "video"):
            where.append("i.kind = ?")
            params.append(kind)
        if ext:
            e = ext if ext.startswith(".") else "." + ext
            where.append("i.ext = ?")
            params.append(e.lower())
        if platform:
            where.append("i.source_platform = ?")
            params.append(platform)
        if orientation == "landscape":
            where.append("i.width > i.height AND i.width > 0")
        elif orientation == "portrait":
            where.append("i.height > i.width AND i.height > 0")
        elif orientation == "square":
            where.append("i.width > 0 AND ABS(i.aspect_ratio - 1.0) <= 0.12")

        if collection_id is not None:
            where.append("EXISTS (SELECT 1 FROM collection_items ci WHERE ci.item_id=i.id AND ci.collection_id=?)")
            params.append(collection_id)

        for t in (tags or []):
            t = t.strip()
            if not t:
                continue
            # 别名归一到主标签（B-09 验收 1：历史深链 ?tag=旧名 仍可用）
            t = alias_map.get(t, t)
            where.append(
                "EXISTS (SELECT 1 FROM item_tags it JOIN tags tg ON it.tag_id=tg.id WHERE it.item_id=i.id AND tg.name=?)"
            )
            params.append(t)

        for et in (exclude_tags or []):
            et = et.strip()
            if not et:
                continue
            et = alias_map.get(et, et)
            where.append(
                "NOT EXISTS (SELECT 1 FROM item_tags it JOIN tags tg ON it.tag_id=tg.id WHERE it.item_id=i.id AND tg.name=?)"
            )
            params.append(et)

        if q.strip():
            # 检索走 FTS5 索引（REQ-V2-20 B-06）：
            #   seg 列为预分词结果，中文两字词可命中；
            #   单字查询不构造 MATCH（几乎命中全库），改为标签精确 + 标题前缀。
            match_expr = search_index.build_match_query(q)
            if match_expr and not search_index.is_single_char_cjk(q):
                where.append("i.id IN (SELECT item_id FROM items_fts WHERE items_fts MATCH ?)")
                params.append(match_expr)
            else:
                # 单字/极短查询：走前缀匹配（可利用索引），避免 %kw% 全表扫。
                # 标签用前缀而非全等："城" 应能命中标签 "城市"。
                kw = q.strip()
                where.append(
                    "("
                    "i.title LIKE ? OR i.name LIKE ? "
                    "OR EXISTS (SELECT 1 FROM item_tags it JOIN tags tg ON it.tag_id=tg.id "
                    "WHERE it.item_id=i.id AND tg.name LIKE ?)"
                    ")"
                )
                params.extend([f"{kw}%", f"{kw}%", f"{kw}%"])

        where_sql = " AND ".join(where)
        order_map = {
            "newest": "i.ts DESC, i.rowid DESC",
            "oldest": "i.ts ASC, i.rowid ASC",
            "size": "i.size DESC",
            "pixels": "(i.width * i.height) DESC",
            "views": "i.views DESC, i.ts DESC",
            "random": "RANDOM()",
        }
        order_sql = order_map.get(sort, order_map["newest"])

        with self.connect() as conn:
            if color:
                # 色彩筛选：按色距过滤并排序
                rows = conn.execute(f"SELECT i.* FROM items i WHERE {where_sql}", params).fetchall()
                matched = []
                for r in rows:
                    dist = _color_distance(color, r["dominant_color"])
                    if dist <= 115:
                        matched.append((dist, r))
                matched.sort(key=lambda x: x[0])
                total = len(matched)
                sliced = [r for _, r in matched[offset:offset + limit]]
                return total, self._hydrate_rows(conn, sliced)

            total = conn.execute(f"SELECT COUNT(*) FROM items i WHERE {where_sql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT i.* FROM items i WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return total, self._hydrate_rows(conn, rows)

    def find_by_id_prefix(self, prefix: str, limit: int = 5) -> List[Dict[str, Any]]:
        """按 id 前缀查资产（REQ-V2-20 E-19 的 /a/ 语义路由）。

        id 是主键左前缀，可直接走索引范围扫描，不做全表 LIKE。
        """
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE id >= ? AND id < ? AND deleted_at IS NULL"
                " ORDER BY ts DESC LIMIT ?",
                (prefix, prefix + "\uffff", limit),
            ).fetchall()
            return self._hydrate_rows(conn, rows)

    def list_published_items(self) -> List[Dict[str, Any]]:
        """sitemap 用：只列 published 且未删除的资产（E-19）。"""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, title, name, slug, ts, updated_at, kind, width, height,"
                " author, license, license_url, copyright_holder, commercial_ok,"
                " duration, dominant_color, file"
                " FROM items WHERE deleted_at IS NULL AND status = 'published'"
                " ORDER BY ts DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def ensure_slug(self, item_id: str) -> str:
        """为资产补齐 slug（幂等）。空标题时返回空串，路径靠 shortId 保证唯一。"""
        with self._write_lock, self.connect() as conn:
            row = conn.execute("SELECT slug, title, name FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return ""
            if row["slug"]:
                return row["slug"]
            existing = {r[0] for r in conn.execute(
                "SELECT slug FROM items WHERE slug != ''").fetchall()}
            import export_seo
            slug = export_seo.build_slug(row["title"] or row["name"] or "", item_id, existing)
            conn.execute("UPDATE items SET slug=?, updated_at=? WHERE id=?",
                         (slug, int(time.time()), item_id))
            conn.commit()
            return slug

    def find_similar(self, item_id: str, limit: int = 12, max_dist: int = 14) -> List[Dict[str, Any]]:
        """基于 pHash 与主色调检索视觉相似资产"""
        with self.connect() as conn:
            target = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not target:
                return []
            ph = target["phash"]
            dc = target["dominant_color"]
            rows = conn.execute(
                "SELECT * FROM items WHERE id != ? AND deleted_at IS NULL",
                (item_id,),
            ).fetchall()
            scored = []
            for r in rows:
                if ph and r["phash"]:
                    hd = _hamming_hex(ph, r["phash"])
                    if hd <= max_dist:
                        scored.append((hd, _color_distance(dc, r["dominant_color"]), r))
                elif r["kind"] == target["kind"]:
                    cd = _color_distance(dc, r["dominant_color"])
                    if cd <= 55:
                        scored.append((20, cd, r))
            scored.sort(key=lambda x: (x[0], x[1]))
            return self._hydrate_rows(conn, [r for _, _, r in scored[:limit]])

    def find_near_duplicate(self, phash: str, max_dist: int = 4,
                            exclude_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """查找近似重复项。

        优化（REQ-V2-20 D-16）：先按 phash 前 2 个十六进制字符分桶，
        只比对同桶与相邻前缀的候选，避免万级资产下逐行算汉明距离。
        汉明距离 ≤4 意味着前 2 个 hex 字符（8 bit）通常至少共享若干位，
        因此用"前缀首字符相同"做粗筛，既安全又大幅减少候选。
        """
        if not phash:
            return None
        prefix = phash[:1]
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE phash != '' AND deleted_at IS NULL "
                "AND substr(phash,1,1)=?",
                (prefix,),
            ).fetchall()
            for r in rows:
                if exclude_id and r["id"] == exclude_id:
                    continue
                if _hamming_hex(phash, r["phash"]) <= max_dist:
                    return self._hydrate_rows(conn, [r])[0]
        return None

    # ---------- 批量与软删除 ----------

    def soft_delete(self, item_ids: List[str]) -> int:
        now = int(time.time())
        if not item_ids:
            return 0
        placeholders = ",".join("?" for _ in item_ids)
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                f"UPDATE items SET deleted_at=? WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                (now, *item_ids),
            )
            conn.commit()
            return cur.rowcount

    def restore_items(self, item_ids: List[str]) -> int:
        if not item_ids:
            return 0
        placeholders = ",".join("?" for _ in item_ids)
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                f"UPDATE items SET deleted_at=NULL WHERE id IN ({placeholders})",
                item_ids,
            )
            conn.commit()
            return cur.rowcount

    def permanent_delete(self, item_ids: List[str]) -> List[Dict[str, Any]]:
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        with self._write_lock, self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM items WHERE id IN ({placeholders})", item_ids).fetchall()
            removed = [dict(r) for r in rows]
            conn.execute(f"DELETE FROM items WHERE id IN ({placeholders})", item_ids)
            conn.execute(f"DELETE FROM items_fts WHERE item_id IN ({placeholders})", item_ids)
            conn.commit()
            return removed

    def batch_tags(self, item_ids: List[str], add_tags: Optional[List[str]] = None, remove_tags: Optional[List[str]] = None) -> int:
        if not item_ids:
            return 0
        with self._write_lock, self.connect() as conn:
            for iid in item_ids:
                for t in (add_tags or []):
                    t = t.strip()
                    if not t:
                        continue
                    conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (t,))
                    tid = conn.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()["id"]
                    conn.execute("INSERT OR IGNORE INTO item_tags(item_id, tag_id, source) VALUES (?,?,?)", (iid, tid, "manual"))
                for t in (remove_tags or []):
                    t = t.strip()
                    if not t:
                        continue
                    row = conn.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()
                    if row:
                        conn.execute("DELETE FROM item_tags WHERE item_id=? AND tag_id=?", (iid, row["id"]))
                self._sync_fts(conn, iid)
            conn.commit()
            return len(item_ids)

    # ---------- 画板（Collections） ----------

    def get_collection(self, cid: int) -> Optional[Dict[str, Any]]:
        """按 id 取单个合集（C-14 选片链接校验目标合集是否存在）。"""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
            return dict(row) if row else None

    def list_collections(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(ci.item_id) AS item_count,
                       COALESCE(c.cover_item_id, (
                           SELECT ci2.item_id FROM collection_items ci2
                           JOIN items i ON ci2.item_id=i.id
                           WHERE ci2.collection_id=c.id AND i.deleted_at IS NULL
                           ORDER BY ci2.added_at DESC LIMIT 1
                       )) AS resolved_cover
                FROM collections c
                LEFT JOIN collection_items ci ON c.id=ci.collection_id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def create_collection(self, name: str, description: str = "") -> Dict[str, Any]:
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO collections(name, description, created_at, updated_at) VALUES (?,?,?,?)",
                (name.strip(), description.strip(), now, now),
            )
            cid = cur.lastrowid
            conn.commit()
        return [c for c in self.list_collections() if c["id"] == cid][0]

    def update_collection(self, cid: int, name: Optional[str] = None, description: Optional[str] = None, cover_item_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        updates: Dict[str, Any] = {}
        if name is not None:
            updates["name"] = name.strip()
        if description is not None:
            updates["description"] = description.strip()
        if cover_item_id is not None:
            updates["cover_item_id"] = cover_item_id or None
        if not updates:
            return None
        updates["updated_at"] = int(time.time())
        sets = ", ".join(f"{k}=?" for k in updates)
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE collections SET {sets} WHERE id=?", (*updates.values(), cid))
            conn.commit()
        cols = [c for c in self.list_collections() if c["id"] == cid]
        return cols[0] if cols else None

    def delete_collection(self, cid: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM collections WHERE id=?", (cid,))
            conn.commit()
            return cur.rowcount > 0

    def add_to_collection(self, cid: int, item_ids: List[str]) -> int:
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            added = 0
            for iid in item_ids:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO collection_items(collection_id, item_id, added_at) VALUES (?,?,?)",
                    (cid, iid, now),
                )
                added += cur.rowcount
            conn.execute("UPDATE collections SET updated_at=? WHERE id=?", (now, cid))
            conn.commit()
            return added

    def remove_from_collection(self, cid: int, item_ids: List[str]) -> int:
        if not item_ids:
            return 0
        placeholders = ",".join("?" for _ in item_ids)
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                f"DELETE FROM collection_items WHERE collection_id=? AND item_id IN ({placeholders})",
                (cid, *item_ids),
            )
            conn.commit()
            return cur.rowcount

    # ---------- 统计与看板 ----------

    def get_stats(self) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN kind='image' THEN 1 ELSE 0 END), 0) AS images,
                    COALESCE(SUM(CASE WHEN kind='video' THEN 1 ELSE 0 END), 0) AS videos,
                    COALESCE(SUM(size), 0) AS bytes
                FROM items WHERE deleted_at IS NULL
                """
            ).fetchone()
            trash_count = conn.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NOT NULL").fetchone()[0]
            collections_count = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]

            tag_rows = conn.execute(
                """
                SELECT t.name, COUNT(it.item_id) AS cnt
                FROM tags t
                JOIN item_tags it ON t.id=it.tag_id
                JOIN items i ON it.item_id=i.id
                WHERE i.deleted_at IS NULL
                GROUP BY t.id
                ORDER BY cnt DESC, t.name ASC
                """
            ).fetchall()
            tags_dict = {r["name"]: r["cnt"] for r in tag_rows}
            tags_list = [{"name": r["name"], "count": r["cnt"]} for r in tag_rows]

            plat_rows = conn.execute(
                """
                SELECT source_platform, COUNT(*) AS cnt
                FROM items WHERE deleted_at IS NULL
                GROUP BY source_platform ORDER BY cnt DESC
                """
            ).fetchall()
            platforms = [{"name": r["source_platform"], "count": r["cnt"]} for r in plat_rows]

            return {
                "total": row["total"],
                "images": row["images"],
                "videos": row["videos"],
                "bytes": row["bytes"],
                "trash_count": trash_count,
                "collections_count": collections_count,
                "tags": tags_dict,
                "tags_list": tags_list,
                "platforms": platforms,
            }

    def get_facets(self, **filters) -> Dict[str, Any]:
        """分面统计（REQ-V2-20 B-10）。

        返回在当前筛选上下文下，各维度的可选值与计数，
        供前端渲染折叠式分面面板并置灰零结果项。

        做法：用与 query_items 相同的 where 条件跑聚合，
        每个维度额外排除自身的筛选条件，避免"选了 A 后 A 维度只剩 A"。
        """
        # 逐维度聚合：kind / ext / orientation / platform / tag
        with self.connect() as conn:
            def scalar(sql: str, params: List[Any]) -> int:
                row = conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0

            base = "FROM items i WHERE i.deleted_at IS NULL"
            result: Dict[str, Any] = {}

            # 类型
            rows = conn.execute(
                f"SELECT i.kind AS k, COUNT(*) AS c {base} GROUP BY i.kind ORDER BY c DESC"
            ).fetchall()
            result["kind"] = [{"value": r["k"], "count": r["c"]} for r in rows]

            # 格式
            rows = conn.execute(
                f"SELECT i.ext AS k, COUNT(*) AS c {base} GROUP BY i.ext ORDER BY c DESC"
            ).fetchall()
            result["ext"] = [{"value": r["k"], "count": r["c"]} for r in rows]

            # 方向（用 SQL 表达式直接分桶，避免逐行计算）
            rows = conn.execute(
                f"""
                SELECT
                    CASE
                        WHEN i.width = 0 OR i.height = 0 THEN 'unknown'
                        WHEN ABS(i.aspect_ratio - 1.0) <= 0.12 THEN 'square'
                        WHEN i.width > i.height THEN 'landscape'
                        ELSE 'portrait'
                    END AS k,
                    COUNT(*) AS c
                {base} GROUP BY k ORDER BY c DESC
                """
            ).fetchall()
            result["orientation"] = [
                {"value": r["k"], "count": r["c"]} for r in rows if r["k"] != "unknown"
            ]

            # 来源平台
            rows = conn.execute(
                f"SELECT i.source_platform AS k, COUNT(*) AS c {base} GROUP BY i.source_platform ORDER BY c DESC"
            ).fetchall()
            result["platform"] = [{"value": r["k"], "count": r["c"]} for r in rows]

            # 标签 Top 20（排除已删除资产）
            rows = conn.execute(
                """
                SELECT t.name AS k, COUNT(it.item_id) AS c
                FROM tags t
                JOIN item_tags it ON t.id = it.tag_id
                JOIN items i ON it.item_id = i.id
                WHERE i.deleted_at IS NULL
                GROUP BY t.id
                ORDER BY c DESC, t.name ASC
                LIMIT 20
                """
            ).fetchall()
            result["tag"] = [{"value": r["k"], "count": r["c"]} for r in rows]

            # 尺寸区间
            rows = conn.execute(
                f"""
                SELECT
                    CASE
                        WHEN MAX(i.width, i.height) >= 3840 THEN '4k'
                        WHEN MAX(i.width, i.height) >= 1920 THEN 'hd'
                        WHEN MAX(i.width, i.height) >= 1280 THEN 'sd'
                        WHEN MAX(i.width, i.height) > 0 THEN 'small'
                        ELSE 'unknown'
                    END AS k,
                    COUNT(*) AS c
                {base} GROUP BY k ORDER BY c DESC
                """
            ).fetchall()
            result["size_class"] = [
                {"value": r["k"], "count": r["c"]} for r in rows if r["k"] != "unknown"
            ]

            result["total"] = scalar(f"SELECT COUNT(*) {base}", [])
            return result

    def get_analytics(self) -> Dict[str, Any]:
        with self.connect() as conn:
            top_viewed = conn.execute(
                "SELECT id, title, kind, thumb, file, views, downloads FROM items WHERE deleted_at IS NULL ORDER BY views DESC LIMIT 10"
            ).fetchall()
            daily = conn.execute(
                """
                SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') AS day, COUNT(*) AS cnt
                FROM items WHERE deleted_at IS NULL AND ts >= ?
                GROUP BY day ORDER BY day ASC
                """,
                (int(time.time()) - 30 * 86400,),
            ).fetchall()
            return {
                "top_viewed": [dict(r) for r in top_viewed],
                "daily_ingest": [dict(r) for r in daily],
            }

    # ---------- 异步任务表 ----------

    # ---------- 客户选片与批注（C-14） ----------

    REVIEW_STATES = ("selected", "pending", "rejected")

    def create_review_link(self, collection_id: int, title: str = "",
                           message: str = "", expires_at: Optional[int] = None) -> Dict[str, Any]:
        """为合集生成选片链接（C-14）。token 仅作访问标识，不作鉴权。"""
        token = secrets.token_urlsafe(12)
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO review_links(token, collection_id, title, message, created_at, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (token, collection_id, title, message, now, expires_at),
            )
            conn.commit()
        return {
            "token": token, "collection_id": collection_id, "title": title,
            "message": message, "created_at": now, "expires_at": expires_at,
            "revoked": 0,
        }

    def get_review_link(self, token: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM review_links WHERE token=?", (token,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if d["revoked"]:
                return None
            if d["expires_at"] and d["expires_at"] < int(time.time()):
                return None
            return d

    def list_review_links(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT r.*, c.name AS collection_name FROM review_links r"
                " LEFT JOIN collections c ON c.id=r.collection_id"
                " ORDER BY r.created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def revoke_review_link(self, token: str) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("UPDATE review_links SET revoked=1 WHERE token=?", (token,))
            conn.commit()
            return cur.rowcount > 0

    def get_review_items(self, token: str) -> List[Dict[str, Any]]:
        """选片页数据：合集内资产 + 已有标记。"""
        link = self.get_review_link(token)
        if not link:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT i.*, m.state AS review_state, m.note AS review_note,"
                " m.reviewer AS review_reviewer, m.updated_at AS review_updated_at"
                " FROM collection_items ci"
                " JOIN items i ON i.id = ci.item_id"
                " LEFT JOIN review_marks m ON m.item_id=i.id AND m.token=?"
                " WHERE ci.collection_id=? AND i.deleted_at IS NULL"
                " ORDER BY ci.added_at ASC",
                (token, link["collection_id"]),
            ).fetchall()
            return self._hydrate_rows(conn, rows)

    def set_review_mark(self, token: str, item_id: str, state: str,
                        note: str = "", reviewer: str = "") -> Tuple[bool, str]:
        """写入选片标记与批注（C-14 验收 1：刷新后状态保留）。"""
        if state not in self.REVIEW_STATES:
            return False, "状态必须是 selected / pending / rejected"
        if not self.get_review_link(token):
            return False, "选片链接无效或已失效"
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM collection_items ci JOIN review_links r"
                " ON r.collection_id=ci.collection_id"
                " WHERE r.token=? AND ci.item_id=?",
                (token, item_id),
            ).fetchone()
            if not exists:
                return False, "该资产不在本次选片范围内"
            conn.execute(
                "INSERT INTO review_marks(token, item_id, state, note, reviewer, updated_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(token, item_id) DO UPDATE SET"
                " state=excluded.state, note=excluded.note,"
                " reviewer=excluded.reviewer, updated_at=excluded.updated_at",
                (token, item_id, state, note, reviewer, now),
            )
            conn.commit()
            return True, "ok"

    def review_summary(self, token: str) -> Dict[str, Any]:
        """库主侧批注汇总：按状态分组（C-14）。"""
        link = self.get_review_link(token)
        if not link:
            return {"ok": False, "states": [], "total": 0}
        states = {"selected": [], "pending": [], "rejected": [], "unmarked": []}
        for it in self.get_review_items(token):
            st = it.get("review_state") or "unmarked"
            states.setdefault(st, []).append({
                "id": it["id"],
                "title": it.get("title") or it.get("name"),
                "thumb": it.get("thumb"),
                "note": it.get("review_note") or "",
                "reviewer": it.get("review_reviewer") or "",
                "updated_at": it.get("review_updated_at"),
            })
        return {
            "ok": True,
            "link": link,
            "states": states,
            "total": sum(len(v) for v in states.values()),
        }

    # ---------- 标签治理（B-09） ----------

    def list_tag_admin(self, limit: int = 200) -> List[Dict[str, Any]]:
        """标签治理列表：频次、层级、别名（B-09）。"""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT t.id, t.name, t.parent_id, COUNT(it.item_id) AS count"
                " FROM tags t LEFT JOIN item_tags it ON it.tag_id=t.id"
                " GROUP BY t.id ORDER BY count DESC, t.name ASC LIMIT ?",
                (limit,),
            ).fetchall()
            aliases: Dict[int, List[str]] = {}
            for r in conn.execute("SELECT alias, tag_id FROM tag_aliases").fetchall():
                aliases.setdefault(r["tag_id"], []).append(r["alias"])
            return [
                {
                    "id": r["id"], "name": r["name"], "parent_id": r["parent_id"],
                    "count": r["count"], "aliases": aliases.get(r["id"], []),
                }
                for r in rows
            ]

    def merge_tags(self, source: str, target: str) -> Dict[str, Any]:
        """把 source 的全部资产并入 target 并删除 source（B-09 验收 1）。

        source 作为别名保留，历史深链 ?tag=source 仍可命中 target。
        """
        source, target = (source or "").strip(), (target or "").strip()
        if not source or not target or source == target:
            return {"ok": False, "message": "源与目标不能为空且不能相同"}
        with self._write_lock, self.connect() as conn:
            srow = conn.execute("SELECT id FROM tags WHERE name=?", (source,)).fetchone()
            trow = conn.execute("SELECT id FROM tags WHERE name=?", (target,)).fetchone()
            if not srow:
                return {"ok": False, "message": f"标签 {source} 不存在"}
            if not trow:
                return {"ok": False, "message": f"标签 {target} 不存在"}
            sid, tid = srow["id"], trow["id"]

            moved = conn.execute(
                "SELECT COUNT(*) FROM item_tags WHERE tag_id=?", (sid,)
            ).fetchone()[0]
            # 冲突组合先删（已同时拥有目标标签），再整体改挂
            conn.execute(
                "DELETE FROM item_tags WHERE tag_id=? AND item_id IN"
                " (SELECT item_id FROM item_tags WHERE tag_id=?)",
                (sid, tid),
            )
            conn.execute("UPDATE item_tags SET tag_id=? WHERE tag_id=?", (tid, sid))
            conn.execute("DELETE FROM tags WHERE id=?", (sid,))
            conn.execute(
                "INSERT INTO tag_aliases(alias, tag_id) VALUES (?,?)"
                " ON CONFLICT(alias) DO UPDATE SET tag_id=excluded.tag_id",
                (source, tid),
            )
            # 受影响资产的 FTS 需要重建标签文本
            ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT item_id FROM item_tags WHERE tag_id=?", (tid,)
            ).fetchall()]
            for iid in ids:
                self._sync_fts(conn, iid)
            conn.commit()
            return {"ok": True, "moved": moved, "target": target,
                    "affected": len(ids), "alias": source}

    def rename_tag(self, old: str, new: str) -> Dict[str, Any]:
        """重命名标签并同步 FTS（B-09 验收 2）。"""
        old, new = (old or "").strip(), (new or "").strip()
        if not old or not new:
            return {"ok": False, "message": "标签名不能为空"}
        with self._write_lock, self.connect() as conn:
            row = conn.execute("SELECT id FROM tags WHERE name=?", (old,)).fetchone()
            if not row:
                return {"ok": False, "message": f"标签 {old} 不存在"}
            dup = conn.execute("SELECT id FROM tags WHERE name=?", (new,)).fetchone()
            if dup:
                return {"ok": False, "message": f"标签 {new} 已存在，请用合并"}
            tid = row["id"]
            conn.execute("UPDATE tags SET name=? WHERE id=?", (new, tid))
            ids = [r[0] for r in conn.execute(
                "SELECT item_id FROM item_tags WHERE tag_id=?", (tid,)
            ).fetchall()]
            for iid in ids:
                self._sync_fts(conn, iid)
            conn.commit()
            return {"ok": True, "renamed": new, "affected": len(ids)}

    def resolve_tag_alias(self, name: str) -> str:
        """把别名归一到主标签名（B-09 验收 1）。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT t.name FROM tag_aliases a JOIN tags t ON t.id=a.tag_id"
                " WHERE a.alias=?", (name,),
            ).fetchone()
            return row["name"] if row else name

    # ---------- 向量与 AI 标签（B-07 / B-08） ----------

    def upsert_embedding(self, item_id: str, vec_bytes: bytes, model_version: str,
                         dim: int = 512, source_text: str = "") -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO item_embeddings(item_id, model_version, dim, vec, source_text, updated_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(item_id) DO UPDATE SET model_version=excluded.model_version,"
                " dim=excluded.dim, vec=excluded.vec, source_text=excluded.source_text,"
                " updated_at=excluded.updated_at",
                (item_id, model_version, dim, vec_bytes, source_text, int(time.time())),
            )
            conn.commit()

    def get_embedding(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM item_embeddings WHERE item_id=?", (item_id,)
            ).fetchone()
            return dict(row) if row else None

    def iter_embeddings(self, model_version: str = "") -> List[Dict[str, Any]]:
        """取出全部向量用于相似度比对。

        规模说明：512 维 float32 每条约 2KB，万级资产约 20MB，
        全量载入内存做点积是可接受的（比逐条 SQL 往返快得多）。
        超过此规模应换 ANN 索引，已在文档中标注为后续条件。
        """
        sql = (
            "SELECT e.item_id, e.vec, e.model_version FROM item_embeddings e"
            " JOIN items i ON i.id=e.item_id WHERE i.deleted_at IS NULL"
        )
        params: List[Any] = []
        if model_version:
            sql += " AND e.model_version=?"
            params.append(model_version)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def missing_embedding_ids(self, model_version: str = "", limit: int = 200) -> List[str]:
        """待补向量的资产（B-08 验收 5：配 Key 后一次性回填）。"""
        sql = (
            "SELECT i.id FROM items i LEFT JOIN item_embeddings e"
            " ON e.item_id=i.id AND e.model_version=?"
            " WHERE i.deleted_at IS NULL AND e.item_id IS NULL"
        )
        with self.connect() as conn:
            return [r[0] for r in conn.execute(
                sql + " LIMIT ?", (model_version, limit)
            ).fetchall()]

    def count_embeddings(self, model_version: str = "") -> int:
        sql = "SELECT COUNT(*) FROM item_embeddings"
        params: List[Any] = []
        if model_version:
            sql += " WHERE model_version=?"
            params.append(model_version)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def add_rejected_tags(self, item_id: str, tags: List[str]) -> int:
        """记录被否决的 AI 标签（B-07 验收 3）。"""
        if not tags:
            return 0
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            for t in tags:
                t = (t or "").strip()
                if not t:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO tag_rejections(item_id, tag, created_at)"
                    " VALUES (?,?,?)",
                    (item_id, t, now),
                )
            conn.commit()
        return len(tags)

    def rejected_tags(self, item_id: str) -> List[str]:
        with self.connect() as conn:
            return [r[0] for r in conn.execute(
                "SELECT tag FROM tag_rejections WHERE item_id=?", (item_id,)
            ).fetchall()]

    def set_tags_with_source(self, item_id: str, tags: List[str], source: str = "ai") -> int:
        """按来源写入标签（AI 标签用 source='ai'，UI 上以虚线区分）。"""
        tags = [t.strip() for t in tags if t and t.strip()]
        if not tags:
            return 0
        with self._write_lock, self.connect() as conn:
            for t in tags:
                conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (t,))
                tid = conn.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()["id"]
                conn.execute(
                    "INSERT OR IGNORE INTO item_tags(item_id, tag_id, source) VALUES (?,?,?)",
                    (item_id, tid, source),
                )
            self._sync_fts(conn, item_id)
            conn.commit()
        return len(tags)

    def keyword_search_ids(self, q: str, limit: int = 50) -> List[str]:
        """供 RRF 融合的关键词召回（复用 B-06 的检索路径）。"""
        total, items = self.query_items(limit=limit, q=q)
        return [i["id"] for i in items]

    # ---------- 个人工作区（C-15） ----------

    def set_liked(self, item_id: str, liked: bool) -> bool:
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO item_flags(item_id, liked, updated_at) VALUES (?,?,?)"
                " ON CONFLICT(item_id) DO UPDATE SET liked=excluded.liked,"
                " updated_at=excluded.updated_at",
                (item_id, 1 if liked else 0, int(time.time())),
            )
            conn.commit()
            return True

    def list_liked_ids(self) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT f.item_id FROM item_flags f JOIN items i ON i.id=f.item_id"
                " WHERE f.liked=1 AND i.deleted_at IS NULL ORDER BY f.updated_at DESC"
            ).fetchall()
            return [r[0] for r in rows]

    def create_job(self, job_type: str, payload: Dict[str, Any]) -> int:
        now = int(time.time())
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO ingest_jobs(job_type, payload, status, progress, message, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (job_type, json.dumps(payload, ensure_ascii=False), "pending", 0, "排队中", now, now),
            )
            conn.commit()
            return cur.lastrowid

    def update_job(self, job_id: int, status: Optional[str] = None, progress: Optional[int] = None, message: Optional[str] = None, result: Optional[Dict[str, Any]] = None):
        updates: Dict[str, Any] = {"updated_at": int(time.time())}
        if status is not None:
            updates["status"] = status
        if progress is not None:
            updates["progress"] = progress
        if message is not None:
            updates["message"] = message
        if result is not None:
            updates["result_json"] = json.dumps(result, ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in updates)
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE ingest_jobs SET {sets} WHERE id=?", (*updates.values(), job_id))
            conn.commit()

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ingest_jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload"] = json.loads(d["payload"])
                except Exception:
                    pass
                try:
                    d["result"] = json.loads(d.pop("result_json", "{}") or "{}")
                except Exception:
                    d["result"] = {}
                out.append(d)
            return out
