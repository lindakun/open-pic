#!/usr/bin/env python3
"""技能学习沉淀（learn）——技能自我进化的读写工具。

命令：
  add      追加一条学习记录（去重：同签名则权重 +1、追加新证据）
  fail     快捷记一条"坑"（等价 add --kind 坑）
  recall   检索：关键词打分排序 + 兜底补齐，任务前加载
  stats    体检：类型/置信分布、高权重榜、一次性条目
  promote  标记"已提升至正文"（技能进化的收尾动作）
  prune    淘汰：长期未复现且低权重
  init     在新技能目录里建空的学习库（创建技能时用）

记录文件：<skill-dir>/references/LEARNINGS.md
条目格式（机器可解析，勿改分隔符）：
  ### L-<8位指纹> {kind}
  - 签名: ...            ← 去重键（归一化后比较）
  - 权重: 1              ← 复现/命中次数，越高越可信
  - 首次/最近: 2026-10-18
  - 场景: ...
  - 做法: ...
  - 证据: ...（命令 + 关键输出片段）
  - 标签: a,b
  - 置信: 高|中|低

用法：
  # 创建新技能时
  cp <skill-creator>/scripts/learn.py <新技能>/scripts/learn.py
  python3 <新技能>/scripts/learn.py init --topic "这个技能管什么"

  python3 learn.py add --kind 数据源 --symptom "HN 评论数" \
      --fix "item 接口 children 只含第一层，需递归展开" \
      --evidence 'hn_trend.py 顶层73 vs 全量642' --tags hn,评论 --conf 高

  python3 learn.py fail --symptom "页面抓取为空" --fix "换 agent-browser"

  python3 learn.py recall --query "评论 数量" --limit 5
  python3 learn.py recall --all
  python3 learn.py stats
  python3 learn.py prune --min-weight 1 --older-than 180   # 预览
  python3 learn.py prune --older-than 180 --apply
  python3 learn.py promote --id L-bd7f0130 --to "SKILL.md#坑"
"""
import argparse
import hashlib
import os
import re
import sys
from datetime import date

STORE = "LEARNINGS.md"
KINDS = ["数据源", "坑", "技巧", "判断", "口径"]
HEADER = """# 学习沉淀（自动维护，勿手改分隔符）

> 本文件由 `scripts/learn.py` 读写。每条记录都有 `权重`（被复现/命中次数）与 `证据`。
> 原则：**没有证据不记录；权重低的可淘汰；与正文冲突时以权重高者为先并回写 SKILL.md。**
"""

ENTRY_RE = re.compile(
    r"### (L-[0-9a-f]{8}) (?P<kind>[^\n]+)\n"
    r"- 签名: (?P<sig>[^\n]*)\n"
    r"- 权重: (?P<weight>\d+)\n"
    r"- 首次/最近: (?P<first>\S+) / (?P<last>\S+)\n"
    r"- 场景: (?P<scene>[^\n]*)\n"
    r"- 做法: (?P<fix>[^\n]*)\n"
    r"- 证据: (?P<evidence>[^\n]*)\n"
    r"- 标签: (?P<tags>[^\n]*)\n"
    r"- 置信: (?P<conf>[^\n]*)\n"
)

STOP = set("the a an of to in for on is are it and or".split())
STOPC = set("的 了 是 在 有 和 就 不 也 都 而 及 与 或 一个 这 那 么 之 其 对 于 再 次 出现".split())


def default_skill_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def store_path(args):
    return os.path.join(args.skill_dir, "references", args.store)


def normalize(sig):
    """归一化签名：去括号补充说明、去标点与停用词、单字，防同义写法重复入库。"""
    s = re.sub(r"[（(].*?[)）]", "", sig).lower()
    toks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", s)
    out = []
    for t in toks:
        if t in STOP:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", t):
            t = "".join(ch for ch in t if ch not in STOPC)
        if len(t) > 1:
            out.append(t)
    return " ".join(out)


def fingerprint(sig):
    return hashlib.sha1(normalize(sig).encode()).hexdigest()[:8]


def read_entries(path):
    if not os.path.exists(path):
        return []
    txt = open(path, encoding="utf-8").read()
    return [m.groupdict() | {"id": m.group(1)} for m in ENTRY_RE.finditer(txt)]


def write_entries(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entries.sort(key=lambda e: e["id"])
    entries.sort(key=lambda e: int(e["weight"]), reverse=True)
    body = [HEADER]
    for e in entries:
        body.append(
            f"### {e['id']} {e['kind']}\n"
            f"- 签名: {e['sig']}\n"
            f"- 权重: {e['weight']}\n"
            f"- 首次/最近: {e['first']} / {e['last']}\n"
            f"- 场景: {e['scene']}\n"
            f"- 做法: {e['fix']}\n"
            f"- 证据: {e['evidence']}\n"
            f"- 标签: {e['tags']}\n"
            f"- 置信: {e['conf']}\n")
    open(path, "w", encoding="utf-8").write("\n".join(body) + "\n")


def one_line(s, limit=300):
    return re.sub(r"\s+", " ", (s or "").strip())[:limit] or "-"


# ---------------------------------------------------------------- init
def cmd_init(args):
    path = store_path(args)
    if os.path.exists(path):
        print(f"已存在，不覆盖: {path}")
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head = HEADER
    if args.topic:
        head += f"\n主题：{args.topic}\n"
    open(path, "w", encoding="utf-8").write(head)
    print(f"已创建学习库: {path}")
    return 0


# ---------------------------------------------------------------- add / fail
def cmd_add(args, kind=None):
    kind = kind or args.kind
    sig = args.symphony or args.symptom
    today = date.today().isoformat()
    path = store_path(args)

    entries = read_entries(path)
    fp = "L-" + fingerprint(f"{kind}|{sig}")
    same = [e for e in entries if normalize(e["sig"]) == normalize(sig) or e["id"] == fp]
    # 同类优先（fail 与 add 记同一现象时归并到更贴切的那条，避免切换命令就派生新条目）
    same.sort(key=lambda e: e["kind"] != kind)
    for e in same[:1]:
            e["weight"] = str(int(e["weight"]) + 1)
            e["last"] = today
            if args.evidence and args.evidence not in e["evidence"]:
                e["evidence"] = one_line(f'{e["evidence"]} ｜ {args.evidence}', 600)
            if args.fix and len(args.fix) > len(e["fix"]):
                e["fix"] = one_line(args.fix, 400)
            merged = {t for t in (e["tags"] + "," + (args.tags or "")).split(",") if t.strip()}
            e["tags"] = ",".join(sorted(t.strip() for t in merged))
            write_entries(path, entries)
            print(f"命中已有记录 {fp}，权重 → {e['weight']}")
            return 0

    entries.append({
        "id": fp, "kind": kind, "sig": one_line(sig, 160), "weight": "1",
        "first": today, "last": today,
        "scene": one_line(args.symptom, 300),
        "fix": one_line(args.fix, 400),
        "evidence": one_line(args.evidence, 600),
        "tags": ",".join(t.strip() for t in (args.tags or "").split(",") if t.strip()),
        "conf": args.conf,
    })
    write_entries(path, entries)
    print(f"新增 {fp} [{kind}] {one_line(sig, 60)}")
    return 0


def cmd_fail(args):
    return cmd_add(args, kind="坑")


# ---------------------------------------------------------------- recall
def score(e, terms):
    hay = " ".join(e[k] for k in ("sig", "scene", "fix", "tags", "evidence")).lower()
    hit = sum(1 for t in terms if t in hay)
    return hit * 10 + int(e["weight"])


def ranked(entries, query, limit, floor=1):
    """关键词打分 + 兜底：命中不足 floor 条时用高权重记录补齐（标注"兜底"）。"""
    terms = [t.lower() for t in re.split(r"[\s,，]+", query) if t]
    scored = sorted(((score(e, terms), e) for e in entries), key=lambda x: -x[0])
    hit = [e for s, e in scored if s >= 10]
    out = [(False, e) for e in hit[:limit]]
    if len(out) < floor:
        chosen_ids = {e["id"] for _, e in out}
        for _, e in scored:
            if e["id"] in chosen_ids:
                continue
            out.append((True, e))
            if len(out) >= floor:
                break
    return out


def print_entry(e):
    print(f"[{e['id']}] {e['kind']} · 权重{e['weight']} · 置信{e['conf']} · 最近{e['last']}")
    print(f"  签名: {e['sig']}")
    print(f"  场景: {e['scene']}")
    print(f"  做法: {e['fix']}")
    print(f"  证据: {e['evidence']}")
    if e["tags"]:
        print(f"  标签: {e['tags']}")
    print()


def cmd_recall(args):
    path = store_path(args)
    entries = read_entries(path)
    if not entries:
        print("（暂无学习记录）")
        return 0
    if args.all:
        chosen = [(False, e) for e in entries]
    elif args.query:
        chosen = ranked(entries, args.query, args.limit, floor=args.floor)
    else:
        chosen = [(True, e) for e in sorted(entries, key=lambda e: -int(e["weight"]))[: args.limit]]
    print(f"# 召回 {len(chosen)} 条（库中 {len(entries)} 条）\n")
    for fallback, e in chosen:
        if fallback:
            print("（兜底推荐：与本次关键词无直接命中，但是高权重经验）")
        print_entry(e)
    return 0


def cmd_stats(args):
    entries = read_entries(store_path(args))
    from collections import Counter
    print(f"记录数 {len(entries)}")
    print("按类型:", dict(Counter(e["kind"] for e in entries)) or "-")
    print("按置信:", dict(Counter(e["conf"] for e in entries)) or "-")
    if entries:
        print("\n最高权重:")
        for e in sorted(entries, key=lambda e: -int(e["weight"]))[:5]:
            print(f"  {e['weight']}x {e['id']} {e['sig'][:60]}")
        pending = [e for e in entries
                   if int(e["weight"]) >= 3 and e["conf"] == "高" and "已提升" not in e["evidence"]]
        if pending:
            print("\n达提升条件但未回写正文（权重≥3 且置信=高）:")
            for e in pending:
                print(f"  {e['id']} {e['sig'][:60]}")
        print(f"\n仅命中 1 次（可考虑淘汰）: "
              f"{len([e for e in entries if int(e['weight']) <= 1])} 条")
    return 0


def cmd_promote(args):
    """把高权重经验标记为"已提升至正文"。"""
    path = store_path(args)
    entries = read_entries(path)
    target = next((e for e in entries if e["id"] == args.id), None)
    if not target:
        print(f"未找到 {args.id}", file=sys.stderr)
        return 1
    tag = f"→ 已提升至 {args.to}"
    if tag in target["evidence"]:
        print("该条已标记过。")
        return 0
    target["evidence"] = one_line(f'{target["evidence"]} {tag}', 700)
    write_entries(path, entries)
    print(f"{args.id} 已标记 {tag}")
    return 0


def cmd_prune(args):
    entries = read_entries(store_path(args))
    cutoff = None
    if args.older_than:
        cutoff = date.today().toordinal() - args.older_than
    keep, drop = [], []
    for e in entries:
        old = cutoff is not None and date.fromisoformat(e["last"]).toordinal() < cutoff
        if old and int(e["weight"]) <= args.min_weight:
            drop.append(e)
        else:
            keep.append(e)
    print(f"将删除 {len(drop)} 条，保留 {len(keep)} 条")
    for e in drop:
        print(f"  - {e['id']} w={e['weight']} {e['last']} {e['sig'][:50]}")
    if args.apply and drop:
        write_entries(store_path(args), keep)
        print("已写入。")
    elif drop:
        print("（预览模式，加 --apply 生效）")
    return 0


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="技能学习沉淀工具")
    p.add_argument("--skill-dir", default=default_skill_dir())
    p.add_argument("--store", default=STORE)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--symptom", required=True, help="场景 / 触发条件")
        sp.add_argument("--fix", required=True, help="做法 / 结论")
        sp.add_argument("--evidence", default="", help="证据：命令、输出片段、数字")
        sp.add_argument("--tags", default="")
        sp.add_argument("--conf", default="中", choices=["高", "中", "低"])

    i = sub.add_parser("init")
    i.add_argument("--topic", default="", help="这个技能管什么（写进文件头）")
    i.set_defaults(func=cmd_init)

    a = sub.add_parser("add")
    a.add_argument("--kind", default="技巧", choices=KINDS)
    a.add_argument("--symphony", default="", help="去重签名，缺省用 --symptom")
    add_common(a)
    a.set_defaults(func=cmd_add)

    f = sub.add_parser("fail")
    f.add_argument("--symphony", default="", help="去重签名，缺省用 --symptom")
    add_common(f)
    f.set_defaults(func=cmd_fail)

    r = sub.add_parser("recall")
    r.add_argument("--query", default="")
    r.add_argument("--all", action="store_true")
    r.add_argument("--limit", type=int, default=5)
    r.add_argument("--floor", type=int, default=2, help="命中不足时兜底补齐的条数")
    r.set_defaults(func=cmd_recall)

    s = sub.add_parser("stats")
    s.set_defaults(func=cmd_stats)

    pm = sub.add_parser("promote")
    pm.add_argument("--id", required=True)
    pm.add_argument("--to", required=True, help='正文位置，如 "SKILL.md#标准流程"')
    pm.set_defaults(func=cmd_promote)

    pr = sub.add_parser("prune")
    pr.add_argument("--min-weight", type=int, default=1)
    pr.add_argument("--older-than", type=int, default=180, help="天")
    pr.add_argument("--apply", action="store_true")
    pr.set_defaults(func=cmd_prune)

    args = p.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
