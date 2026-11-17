#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索内核测试（REQ-V2-20 B-06）

验收要点：
  1. 中文两字词能命中（改造前 FTS 表建了但查询根本不走它）
  2. 单字查询不产生全表扫描，仍能按标签/前缀命中
  3. 多词之间是 AND 关系
  4. 标签、来源、备注均在检索范围内
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import search_index  # noqa: E402


class TestTokenizer:
    def test_chinese_two_char_word_is_indexed(self):
        tokens = search_index.tokenize("城市夜景")
        # 应包含两字词元，而不是被切成单字
        assert "城市" in tokens
        assert "夜景" in tokens

    def test_english_is_lowercased(self):
        tokens = search_index.tokenize("City LIGHTS")
        assert "city" in tokens
        assert "lights" in tokens

    def test_mixed_language(self):
        tokens = search_index.tokenize("东京 Tokyo 夜景")
        assert "东京" in tokens
        assert "tokyo" in tokens
        assert "夜景" in tokens

    def test_empty_input(self):
        assert search_index.tokenize("") == []
        assert search_index.tokenize("   ") == []

    def test_tokens_are_deduplicated(self):
        tokens = search_index.tokenize("城市 城市")
        assert tokens.count("城市") == 1

    def test_match_query_uses_and(self):
        expr = search_index.build_match_query("城市 夜景")
        assert expr is not None
        assert " AND " in expr

    def test_match_query_can_use_or(self):
        expr = search_index.build_match_query("城市 夜景", operator="OR")
        assert expr is not None
        assert " OR " in expr

    def test_single_char_cjk_returns_none(self):
        """单字不构造 MATCH：会命中几乎全库，应走前缀/标签兜底。"""
        assert search_index.build_match_query("城") is None
        assert search_index.is_single_char_cjk("城") is True
        assert search_index.is_single_char_cjk("城市") is False

    def test_build_fts_text_joins_fields(self):
        text = search_index.build_fts_text("城市", "夜景", None, "备注")
        assert "城市" in text
        assert "夜景" in text
        assert "备注" in text


@pytest.fixture()
def db(tmp_path):
    """独立数据目录的数据库实例。"""
    from db import MediaDB

    os.environ["MEDIA_LIB_DIR"] = str(tmp_path)
    instance = MediaDB(str(tmp_path / "media.db"))
    yield instance


def _insert(db, item_id, title, tags=(), notes="", source=""):
    rec = {
        "id": item_id,
        "file": f"{item_id}.jpg",
        "thumb": f"{item_id}.jpg",
        "kind": "image",
        "ext": ".jpg",
        "name": f"{item_id}.jpg",
        "title": title,
        "tags": list(tags),
        "source": source,
        "notes": notes,
        "size": 1024,
        "width": 1200,
        "height": 800,
        "aspect_ratio": 1.5,
        "ts": 1700000000,
        "updated_at": 1700000000,
    }
    db.upsert_item(rec)


class TestSearch:
    def test_chinese_two_char_word_hits(self, db):
        _insert(db, "aaa111", "城市夜景天际线")
        _insert(db, "bbb222", "山间清晨")

        total, items = db.query_items(q="城市")
        assert total == 1
        assert items[0]["id"] == "aaa111"

    def test_search_across_title_and_notes(self, db):
        _insert(db, "ccc333", "无名", notes="拍摄于东京塔下")
        total, items = db.query_items(q="东京")
        assert total == 1
        assert items[0]["id"] == "ccc333"

    def test_search_matches_tags(self, db):
        _insert(db, "ddd444", "随便的标题", tags=["赛博朋克"])
        total, items = db.query_items(q="赛博朋克")
        assert total == 1
        assert items[0]["id"] == "ddd444"

    def test_multi_word_is_and(self, db):
        _insert(db, "eee555", "城市夜景")
        _insert(db, "fff666", "城市清晨")
        total, _ = db.query_items(q="城市 夜景")
        assert total == 1

    def test_single_char_matches_by_tag(self, db):
        _insert(db, "ggg777", "无关标题", tags=["城市"])
        total, items = db.query_items(q="城")
        # 单字走标签精确匹配与前缀匹配，应能命中标签
        assert total >= 1
        assert any(i["id"] == "ggg777" for i in items)

    def test_no_match_returns_empty(self, db):
        _insert(db, "hhh888", "城市夜景")
        total, items = db.query_items(q="完全不存在的关键词组合")
        assert total == 0
        assert items == []

    def test_search_respects_soft_delete(self, db):
        _insert(db, "iii999", "城市夜景")
        db.soft_delete(["iii999"])
        total, _ = db.query_items(q="城市")
        assert total == 0
