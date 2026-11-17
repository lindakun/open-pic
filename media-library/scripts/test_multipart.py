#!/usr/bin/env python3
"""流式 multipart 解析器离线测试（不起服务）"""
import os, sys, hashlib, tempfile
sys.path.insert(0, "/vol1/picoclaw/.picoclaw/workspace/skills/media-library/scripts")
import server as S

def build(fields, files, boundary):
    out = b""
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n").encode()
        out += v.encode() + b"\r\n"
    for name, fname, data in files:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out

def run_case(label, fields, files, boundary="----MLIBTEST"):
    body = build(fields, files, boundary)
    tmpdir = tempfile.mkdtemp(prefix="mlibtest-")
    raw = os.path.join(tmpdir, "raw.bin")
    open(raw, "wb").write(body)
    f, r = S.parse_multipart_to_disk(raw, boundary, tmpdir, chunk_size=4096)
    ok = True
    # 字段
    if f != fields:
        print(f"  ✗ {label}: fields {f} != {fields}"); ok = False
    # 文件
    if len(r) != len(files):
        print(f"  ✗ {label}: 文件数 {len(r)} != {len(files)}"); ok = False
    else:
        for (path, fname), (_, efname, edata) in zip(r, files):
            got = open(path, "rb").read()
            if got != edata:
                print(f"  ✗ {label}: {fname} 内容不符 ({len(got)} vs {len(edata)})"); ok = False
            if fname != efname:
                print(f"  ✗ {label}: 文件名 {fname} != {efname}"); ok = False
    if ok:
        print(f"  ✓ {label}")
    import shutil as sh
    sh.rmtree(tmpdir, ignore_errors=True)
    return ok

cases = []
cases.append(run_case("纯文字字段", {"title": "标题", "tags": "人物,X"}, []))
cases.append(run_case("单小文件", {"title": "t"},
                      [("file", "a.jpg", b"A" * 500)]))
# 含 CRLF 与分隔符前缀的二进制（考验滑窗边界）
tricky = b"\r\n--" + b"x" * 50 + b"\r\n--not-a-boundary" + b"\r\n" * 3
cases.append(run_case("含类分隔符二进制", {"title": "t"},
                      [("file", "b.mp4", tricky)]))
big = os.urandom(3 * 1024 * 1024)
cases.append(run_case("3MB 随机二进制", {"tags": "x"},
                      [("file", "c.mp4", big)]))
cases.append(run_case("多文件", {"title": "multi"},
                      [("file", "d1.jpg", b"D1" * 100), ("file", "d2.jpg", b"D2" * 200)]))
cases.append(run_case("中文文件名", {"title": "中文"},
                      [("file", "测试图.jpg", b"Z" * 300)]))

print("全部通过" if all(cases) else "有失败")
sys.exit(0 if all(cases) else 1)
