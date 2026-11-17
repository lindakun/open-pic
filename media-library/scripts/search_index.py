#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文检索分词与查询构造（REQ-V2-20 B-06）

问题背景：
  现有 items_fts 使用 unicode61 tokenizer，中文被切成单字，
  查询时又完全没走 FTS（实际是六路 LIKE 全表扫）。
  SQLite 自带的 trigram tokenizer 要求 ≥3 字符，两字词仍然无法命中。

方案：
  1. 入库时对标题/备注/OCR 做 jieba 预分词（不可用时退化为 2-gram），
     结果写入独立的 FTS 列，保证两字词可被索引命中
  2. 查询时对关键词同样分词，用 MATCH 走索引
  3. 单字查询退化为标签精确匹配 + 标题前缀匹配，不做 %kw% 全表扫
"""

import re
from typing import List, Optional

# 中文连续片段
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
# 英数片段
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

# jieba 为可选依赖：缺失时用 2-gram 兜底，功能不降级
try:
    import jieba  # type: ignore

    jieba.setLogLevel(60)  # 关闭加载日志，避免污染服务输出

    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


def has_jieba() -> bool:
    return _HAS_JIEBA


def _cjk_bigrams(text: str) -> List[str]:
    """把中文串切成 2-gram，保证两字词可索引。

    "城市夜景" -> ["城市", "市夜", "夜景"]
    """
    out: List[str] = []
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            out.append(run)
            continue
        for i in range(len(run) - 1):
            out.append(run[i : i + 2])
    return out


def tokenize(text: str) -> List[str]:
    """把文本切成检索词元，供写入 FTS 与查询共用。

    中文：优先 jieba 分词，缺失时用 2-gram；
    英文与数字：整词小写；
    去重并保持稳定顺序。
    """
    if not text:
        return []

    t = text.strip()
    out: List[str] = []

    # 中文部分
    if _HAS_JIEBA:
        for seg in jieba.cut_for_search(t):
            seg = seg.strip()
            if not seg:
                continue
            if _CJK_RE.fullmatch(seg) or re.fullmatch(r"[\w\u4e00-\u9fff]+", seg):
                out.append(seg)
            elif _WORD_RE.fullmatch(seg):
                out.append(seg.lower())
    else:
        out.extend(_cjk_bigrams(t))

    # 英数部分（两种情况都要补，jieba 不一定切出英文词）
    for w in _WORD_RE.findall(t):
        out.append(w.lower())

    # 去重保序
    seen = set()
    result: List[str] = []
    for tok in out:
        if tok and tok not in seen:
            seen.add(tok)
            result.append(tok)
    return result


def build_fts_text(*parts: Optional[str]) -> str:
    """把多个字段的分词结果拼成 FTS 索引列内容。"""
    tokens: List[str] = []
    for p in parts:
        if p:
            tokens.extend(tokenize(p))
    return " ".join(tokens)


def _escape_fts(term: str) -> str:
    """FTS5 查询串中的特殊字符需要转义，用双引号包裹整个词。"""
    return '"' + term.replace('"', '""') + '"'


def build_match_query(query: str, operator: str = "AND") -> Optional[str]:
    """构造 FTS5 MATCH 表达式。

    多词元之间默认 AND（更精确），调用方可在结果过少时用 OR 重试。
    返回 None 表示该查询不适合走 FTS（如单字），由调用方走兜底路径。
    """
    tokens = tokenize(query)
    if not tokens:
        return None
    # 单字查询走 FTS 价值很低（几乎命中全部），交由调用方兜底
    if all(len(t) < 2 and _CJK_RE.fullmatch(t) for t in tokens):
        return None
    return f" {operator} ".join(_escape_fts(t) for t in tokens)


def is_single_char_cjk(query: str) -> bool:
    """是否为单个汉字查询（需走标签/前缀兜底，避免全表扫）。"""
    q = query.strip()
    return len(q) == 1 and bool(_CJK_RE.fullmatch(q))
