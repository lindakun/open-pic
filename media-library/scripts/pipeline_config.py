#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时抓取与存量后处理统一配置中心（pipeline_config.py）。

职责：
1. 管理运行数据目录（MEDIA_LIB_DIR）下的 pipeline_config.json，
   并向后兼容同步读写 vision_config.json 与 x_accounts.txt。
2. 提供参数结构化校验、API Key 脱敏、留空保留及原子写盘。
3. 提供 flock 非阻塞锁探测、游标进度读取/重置、待处理存量统计、
   日志尾部读取、代理连通性测试及脚本触发。
"""
import copy
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import vision_filter


class ConfigValidationError(ValueError):
    """配置参数或账号白名单校验失败（对应 HTTP 400）"""


class PipelineBusyError(RuntimeError):
    """目标任务正在运行中，持有互斥锁（对应 HTTP 409）"""


DEFAULT_CONFIG: Dict[str, Any] = {
    "scrape": {
        "batch": 14,
        "limit": 4,
        "max_mb": 30.0,
        "tags": ["X抓取", "人物"],
        "proxy": "http://127.0.0.1:7890",
        "timeout": 30,
        "min_px": 320,
        "min_img_kb": 20,
    },
    "postprocess": {
        "batch": 50,
        "phash_limit": 50,
        "max_dist": 4,
        "ai_tag": "AI已标注",
        "skip_dedup": False,
        "skip_vision": False,
    },
    "vision": {
        "enabled": True,
        "base_url": vision_filter.DEFAULT_BASE_URL,
        "api_key": "",
        "model": vision_filter.DEFAULT_MODEL,
        "timeout": vision_filter.DEFAULT_TIMEOUT,
        "prompt": vision_filter.DEFAULT_PROMPT,
    },
    "updated_at": 0,
}

LOG_FILES: Dict[str, str] = {
    "x_scrape": "x_scrape.log",
    "x_scrape_runner": "x_scrape_runner.log",
    "postprocess": "postprocess.log",
    "postprocess_runner": "postprocess_runner.log",
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _atomic_write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def mask_api_key(key: str) -> str:
    """对 API Key 做脱敏掩码显示，例如 sk-****1234"""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 6:
        return "****"
    prefix = k[:3] if k.startswith("sk-") else k[:2]
    return f"{prefix}****{k[-4:]}"


def parse_and_validate_accounts_text(text: str) -> List[str]:
    """解析并校验 x_accounts.txt 内容，返回去重保序的账号列表"""
    if not isinstance(text, str):
        raise ConfigValidationError("账号名单必须为文本字符串")
    out: List[str] = []
    seen = set()
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        s = raw_line.strip()
        if not s or s.startswith("#"):
            continue
        acct = s.lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", acct):
            raise ConfigValidationError(
                f"账号名单第 {lineno} 行格式非法（仅允许 1-15 位字母/数字/下划线）: {raw_line.strip()!r}"
            )
        low = acct.lower()
        if low not in seen:
            seen.add(low)
            out.append(acct)
    return out


def read_accounts_file(data_dir: str) -> Tuple[str, List[str]]:
    """读取 DATA/x_accounts.txt 原文与解析后的有效账号列表"""
    path = os.path.join(data_dir, "x_accounts.txt")
    if not os.path.exists(path):
        return "", []
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "", []
    accts: List[str] = []
    seen = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        a = s.lstrip("@")
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", a) and a.lower() not in seen:
            seen.add(a.lower())
            accts.append(a)
    return text, accts


def load_pipeline_config(data_dir: str) -> Dict[str, Any]:
    """加载完整运行配置（含明文 api_key，供内部脚本与服务使用）。

    向后兼容：若 pipeline_config.json 不存在或缺少 vision 节，
    自动回退合并 DATA/vision_config.json。
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not data_dir:
        return cfg

    p_path = os.path.join(data_dir, "pipeline_config.json")
    v_path = os.path.join(data_dir, "vision_config.json")

    raw_pipeline: Dict[str, Any] = {}
    if os.path.exists(p_path):
        try:
            with open(p_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw_pipeline = loaded
        except Exception:
            raw_pipeline = {}

    for section in ("scrape", "postprocess", "vision"):
        sec_data = raw_pipeline.get(section)
        if isinstance(sec_data, dict):
            for k, v in sec_data.items():
                if k in cfg[section] and v is not None:
                    cfg[section][k] = v

    if isinstance(raw_pipeline.get("updated_at"), (int, float)):
        cfg["updated_at"] = int(raw_pipeline["updated_at"])

    # 若 pipeline_config.json 中未包含 vision 节，回退读取 vision_config.json
    if "vision" not in raw_pipeline and os.path.exists(v_path):
        try:
            with open(v_path, "r", encoding="utf-8") as f:
                v_loaded = json.load(f)
            if isinstance(v_loaded, dict):
                for k, v in v_loaded.items():
                    if k in cfg["vision"] and v is not None:
                        cfg["vision"][k] = v
        except Exception:
            pass

    cfg["vision"]["base_url"] = str(cfg["vision"]["base_url"] or vision_filter.DEFAULT_BASE_URL).strip().rstrip("/")
    return cfg


def get_public_config(data_dir: str) -> Dict[str, Any]:
    """返回供管理端 API 展示的脱敏配置与账号白名单"""
    cfg = load_pipeline_config(data_dir)
    raw_key = str(cfg["vision"].get("api_key") or "").strip()
    vision_pub = {
        "enabled": bool(cfg["vision"].get("enabled", True)),
        "base_url": str(cfg["vision"].get("base_url") or vision_filter.DEFAULT_BASE_URL),
        "has_api_key": bool(raw_key),
        "api_key_masked": mask_api_key(raw_key),
        "model": str(cfg["vision"].get("model") or vision_filter.DEFAULT_MODEL),
        "timeout": int(cfg["vision"].get("timeout") or vision_filter.DEFAULT_TIMEOUT),
        "prompt": str(cfg["vision"].get("prompt") or vision_filter.DEFAULT_PROMPT),
    }
    accounts_text, accounts_list = read_accounts_file(data_dir)
    return {
        "scrape": cfg["scrape"],
        "postprocess": cfg["postprocess"],
        "vision": vision_pub,
        "defaults": {
            "vision_prompt": vision_filter.DEFAULT_PROMPT,
        },
        "accounts_text": accounts_text,
        "accounts_list": accounts_list,
        "accounts_count": len(accounts_list),
        "updated_at": cfg.get("updated_at", 0),
    }


def _validate_int(val: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(val, bool):
        raise ConfigValidationError(f"{name} 必须为整数")
    try:
        iv = int(val)
    except (TypeError, ValueError) as e:
        raise ConfigValidationError(f"{name} 必须为整数") from e
    if iv < lo or iv > hi:
        raise ConfigValidationError(f"{name} 必须在 {lo} ~ {hi} 之间（当前: {iv}）")
    return iv


def _validate_float(val: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(val, bool):
        raise ConfigValidationError(f"{name} 必须为数值")
    try:
        fv = float(val)
    except (TypeError, ValueError) as e:
        raise ConfigValidationError(f"{name} 必须为数值") from e
    if fv < lo or fv > hi:
        raise ConfigValidationError(f"{name} 必须在 {lo} ~ {hi} 之间（当前: {fv}）")
    return round(fv, 2)


def _validate_bool(val: Any, name: str) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    raise ConfigValidationError(f"{name} 必须为布尔值")


def validate_and_save_config(data_dir: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """校验并原子保存配置与账号名单，同步更新 vision_config.json"""
    if not isinstance(payload, dict):
        raise ConfigValidationError("请求体必须为 JSON 对象")

    cur = load_pipeline_config(data_dir)

    # 1. 先校验 accounts_text（若提供），确保任何校验失败都不半途改文件
    new_accounts_text: Optional[str] = None
    if "accounts_text" in payload and payload["accounts_text"] is not None:
        raw_text = payload["accounts_text"]
        parse_and_validate_accounts_text(raw_text)
        new_accounts_text = raw_text if raw_text.endswith("\n") or not raw_text else raw_text + "\n"

    # 2. 校验 scrape
    if "scrape" in payload and payload["scrape"] is not None:
        s_in = payload["scrape"]
        if not isinstance(s_in, dict):
            raise ConfigValidationError("scrape 必须为对象")
        s_cur = dict(cur["scrape"])
        if "batch" in s_in:
            s_cur["batch"] = _validate_int(s_in["batch"], "scrape.batch", 0, 500)
        if "limit" in s_in:
            s_cur["limit"] = _validate_int(s_in["limit"], "scrape.limit", 0, 50)
        if "max_mb" in s_in:
            s_cur["max_mb"] = _validate_float(s_in["max_mb"], "scrape.max_mb", 1.0, 2048.0)
        if "tags" in s_in:
            raw_tags = s_in["tags"]
            if isinstance(raw_tags, str):
                tag_list = [t.strip() for t in re.split(r"[,，\s]+", raw_tags) if t.strip()]
            elif isinstance(raw_tags, list):
                tag_list = [str(t or "").strip() for t in raw_tags if str(t or "").strip()]
            else:
                raise ConfigValidationError("scrape.tags 必须为字符串数组或逗号分隔字符串")
            if not tag_list:
                raise ConfigValidationError("scrape.tags 至少需要包含 1 个标签")
            for t in tag_list:
                if len(t) > 20 or re.search(r"[,，\s]", t):
                    raise ConfigValidationError(f"标签不合法或超过 20 字符: {t!r}")
            s_cur["tags"] = tag_list
        if "proxy" in s_in:
            proxy = str(s_in["proxy"] or "").strip()
            if proxy and not proxy.startswith(("http://", "https://", "socks5://")):
                raise ConfigValidationError("scrape.proxy 必须为空或以 http://, https://, socks5:// 开头")
            s_cur["proxy"] = proxy
        if "timeout" in s_in:
            s_cur["timeout"] = _validate_int(s_in["timeout"], "scrape.timeout", 5, 300)
        if "min_px" in s_in:
            s_cur["min_px"] = _validate_int(s_in["min_px"], "scrape.min_px", 64, 4096)
        if "min_img_kb" in s_in:
            s_cur["min_img_kb"] = _validate_int(s_in["min_img_kb"], "scrape.min_img_kb", 1, 10240)
        cur["scrape"] = s_cur

    # 3. 校验 postprocess
    if "postprocess" in payload and payload["postprocess"] is not None:
        p_in = payload["postprocess"]
        if not isinstance(p_in, dict):
            raise ConfigValidationError("postprocess 必须为对象")
        p_cur = dict(cur["postprocess"])
        if "batch" in p_in:
            p_cur["batch"] = _validate_int(p_in["batch"], "postprocess.batch", 0, 500)
        if "phash_limit" in p_in:
            p_cur["phash_limit"] = _validate_int(p_in["phash_limit"], "postprocess.phash_limit", 0, 5000)
        if "max_dist" in p_in:
            p_cur["max_dist"] = _validate_int(p_in["max_dist"], "postprocess.max_dist", 0, 16)
        if "ai_tag" in p_in:
            ai_tag = str(p_in["ai_tag"] or "").strip()
            if not ai_tag or len(ai_tag) > 20 or re.search(r"[,，\s]", ai_tag):
                raise ConfigValidationError("postprocess.ai_tag 必须为 1~20 字符且不含空白或逗号")
            p_cur["ai_tag"] = ai_tag
        if "skip_dedup" in p_in:
            p_cur["skip_dedup"] = _validate_bool(p_in["skip_dedup"], "postprocess.skip_dedup")
        if "skip_vision" in p_in:
            p_cur["skip_vision"] = _validate_bool(p_in["skip_vision"], "postprocess.skip_vision")
        cur["postprocess"] = p_cur

    # 4. 校验 vision
    if "vision" in payload and payload["vision"] is not None:
        v_in = payload["vision"]
        if not isinstance(v_in, dict):
            raise ConfigValidationError("vision 必须为对象")
        v_cur = dict(cur["vision"])
        if "enabled" in v_in:
            v_cur["enabled"] = _validate_bool(v_in["enabled"], "vision.enabled")
        if "base_url" in v_in:
            burl = str(v_in["base_url"] or "").strip().rstrip("/")
            if not burl.startswith(("http://", "https://")):
                raise ConfigValidationError("vision.base_url 必须以 http:// 或 https:// 开头")
            v_cur["base_url"] = burl
        if v_in.get("clear_api_key") is True:
            v_cur["api_key"] = ""
        elif "api_key" in v_in and v_in["api_key"] is not None:
            new_key = str(v_in["api_key"]).strip()
            if new_key:
                v_cur["api_key"] = new_key
        if "model" in v_in:
            model = str(v_in["model"] or "").strip()
            if not model:
                raise ConfigValidationError("vision.model 不能为空")
            v_cur["model"] = model
        if "timeout" in v_in:
            v_cur["timeout"] = _validate_int(v_in["timeout"], "vision.timeout", 5, 300)
        if "prompt" in v_in:
            prompt = str(v_in["prompt"] or "").strip()
            if not prompt or len(prompt) > 4000:
                raise ConfigValidationError("vision.prompt 不能为空且长度不超过 4000 字符")
            v_cur["prompt"] = prompt
        cur["vision"] = v_cur

    cur["updated_at"] = int(time.time())

    # 原子写入 pipeline_config.json 与 vision_config.json
    _atomic_write_json(os.path.join(data_dir, "pipeline_config.json"), cur)
    _atomic_write_json(os.path.join(data_dir, "vision_config.json"), cur["vision"])

    if new_accounts_text is not None:
        _atomic_write_text(os.path.join(data_dir, "x_accounts.txt"), new_accounts_text)

    return get_public_config(data_dir)


def is_lock_held(lock_path: str) -> bool:
    """非阻塞探测 flock 文件锁是否正被后台进程持有"""
    if not os.path.exists(lock_path):
        return False
    try:
        import fcntl
    except ImportError:
        return False
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return True
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def read_log_tail(data_dir: str, log_type: str = "x_scrape", lines: int = 120) -> Dict[str, Any]:
    """读取指定日志文件的尾部 N 行"""
    fname = LOG_FILES.get(log_type, "x_scrape.log")
    if log_type not in LOG_FILES:
        log_type = "x_scrape"
    lines = max(10, min(500, int(lines or 120)))
    fpath = os.path.join(data_dir, fname)
    if not os.path.isfile(fpath):
        return {
            "type": log_type,
            "path": fname,
            "content": "",
            "updated_at": 0,
        }
    try:
        stat = os.stat(fpath)
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = "".join(all_lines[-lines:])
        return {
            "type": log_type,
            "path": fname,
            "content": tail,
            "updated_at": int(stat.st_mtime),
        }
    except OSError:
        return {
            "type": log_type,
            "path": fname,
            "content": "",
            "updated_at": 0,
        }


def get_pipeline_status(
    data_dir: str,
    db: Any = None,
    log_type: str = "x_scrape",
    lines: int = 120,
) -> Dict[str, Any]:
    """汇总抓取/后处理锁状态、游标进度、存量待处理数与日志尾部"""
    cfg = load_pipeline_config(data_dir)
    _, accounts_list = read_accounts_file(data_dir)
    accounts_count = len(accounts_list)

    state_path = os.path.join(data_dir, "x_scrape_state.json")
    cursor = 0
    last_run_ts = 0
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st, dict):
                cursor = int(st.get("cursor") or 0)
                accts_meta = st.get("accounts")
                if isinstance(accts_meta, dict) and accts_meta:
                    last_run_ts = max(
                        (int(v.get("last_run") or 0) for v in accts_meta.values() if isinstance(v, dict)),
                        default=0,
                    )
        except Exception:
            pass

    next_account = ""
    if accounts_count > 0:
        next_account = accounts_list[cursor % accounts_count]

    missing_phash_count = 0
    untagged_vision_count = 0
    ai_tag = str(cfg["postprocess"].get("ai_tag") or "AI已标注").strip() or "AI已标注"
    if db is not None:
        try:
            with db.connect() as conn:
                r1 = conn.execute(
                    "SELECT COUNT(*) AS c FROM items WHERE deleted_at IS NULL AND (phash IS NULL OR phash='')"
                ).fetchone()
                missing_phash_count = int(r1["c"]) if r1 else 0
                r2 = conn.execute(
                    "SELECT COUNT(*) AS c FROM items "
                    "WHERE deleted_at IS NULL "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM item_tags it JOIN tags t ON t.id = it.tag_id "
                    "  WHERE it.item_id = items.id AND t.name = ?"
                    ")",
                    (ai_tag,),
                ).fetchone()
                untagged_vision_count = int(r2["c"]) if r2 else 0
        except Exception:
            pass

    return {
        "scrape": {
            "running": is_lock_held(os.path.join(data_dir, "x_scrape.lock")),
            "cursor": cursor,
            "accounts_count": accounts_count,
            "next_account": next_account,
            "last_run_ts": last_run_ts,
        },
        "postprocess": {
            "running": is_lock_held(os.path.join(data_dir, "postprocess.lock")),
            "missing_phash_count": missing_phash_count,
            "untagged_vision_count": untagged_vision_count,
        },
        "log": read_log_tail(data_dir, log_type=log_type, lines=lines),
    }


def reset_scrape_cursor(data_dir: str) -> Dict[str, Any]:
    """将 x_scrape_state.json 的轮转游标重置为 0，保留 seen_tweets 断点"""
    if is_lock_held(os.path.join(data_dir, "x_scrape.lock")):
        raise PipelineBusyError("定时抓取正在运行中，无法重置游标")

    state_path = os.path.join(data_dir, "x_scrape_state.json")
    st: Dict[str, Any] = {"accounts": {}, "cursor": 0}
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                st = loaded
        except Exception:
            pass
    st.setdefault("accounts", {})
    st["cursor"] = 0
    _atomic_write_json(state_path, st)
    return {"ok": True, "cursor": 0, "message": "轮转游标已重置为 0"}


def test_proxy_connectivity(proxy: str, timeout: int = 10) -> Dict[str, Any]:
    """测试代理访问 https://x.com/robots.txt 连通性与耗时"""
    proxy = (proxy or "").strip()
    if proxy and not proxy.startswith(("http://", "https://", "socks5://")):
        raise ConfigValidationError("代理地址格式非法")

    t0 = time.monotonic()
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request("https://x.com/robots.txt", headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=timeout) as resp:
            elapsed_ms = int(round((time.monotonic() - t0) * 1000))
            return {
                "ok": resp.status == 200,
                "status": resp.status,
                "elapsed_ms": elapsed_ms,
                "error": "",
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = int(round((time.monotonic() - t0) * 1000))
        return {
            "ok": False,
            "status": e.code,
            "elapsed_ms": elapsed_ms,
            "error": f"HTTP {e.code}: {e.reason}",
        }
    except Exception as e:
        elapsed_ms = int(round((time.monotonic() - t0) * 1000))
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": f"{type(e).__name__}: {e}",
        }


def trigger_pipeline_action(
    data_dir: str,
    scripts_dir: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行运维动作：重置游标、测试代理、后台触发或试运行"""
    payload = payload or {}
    if action == "reset_cursor":
        return reset_scrape_cursor(data_dir)

    if action == "test_proxy":
        proxy = payload.get("proxy")
        if proxy is None:
            cfg = load_pipeline_config(data_dir)
            proxy = cfg["scrape"].get("proxy", "")
        return test_proxy_connectivity(str(proxy or ""))

    env = {**os.environ, "MEDIA_LIB_DIR": data_dir}

    if action == "run_scrape":
        if is_lock_held(os.path.join(data_dir, "x_scrape.lock")):
            raise PipelineBusyError("X 定时抓取正在运行中，请勿重复触发")
        script = os.path.join(scripts_dir, "x_scrape_cron.sh")
        r = subprocess.run(["bash", script], env=env, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"启动抓取失败 (rc={r.returncode})")
        return {"ok": True, "message": "已投递后台抓取任务"}

    if action == "run_postprocess":
        if is_lock_held(os.path.join(data_dir, "postprocess.lock")):
            raise PipelineBusyError("存量后处理正在运行中，请勿重复触发")
        script = os.path.join(scripts_dir, "library_postprocess_cron.sh")
        r = subprocess.run(["bash", script], env=env, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"启动后处理失败 (rc={r.returncode})")
        return {"ok": True, "message": "已投递后台存量后处理任务"}

    if action == "dry_run_scrape":
        if is_lock_held(os.path.join(data_dir, "x_scrape.lock")):
            raise PipelineBusyError("X 定时抓取正在运行中，请稍后再试")
        script = os.path.join(scripts_dir, "x_scrape_cron.sh")
        r = subprocess.run(
            ["bash", script, "--dry-run", "--batch", "2", "--limit", "2"],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = "\n".join(x for x in (r.stdout.strip(), r.stderr.strip()) if x)
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "output": out or "（无输出）",
            "message": "抓取试运行完成" if r.returncode == 0 else f"抓取试运行退出码 {r.returncode}",
        }

    if action == "dry_run_postprocess":
        if is_lock_held(os.path.join(data_dir, "postprocess.lock")):
            raise PipelineBusyError("存量后处理正在运行中，请稍后再试")
        script = os.path.join(scripts_dir, "library_postprocess_cron.sh")
        r = subprocess.run(
            ["bash", script, "--dry-run"],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = "\n".join(x for x in (r.stdout.strip(), r.stderr.strip()) if x)
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "output": out or "（无输出）",
            "message": "后处理试运行完成" if r.returncode == 0 else f"后处理试运行退出码 {r.returncode}",
        }

    raise ConfigValidationError(f"不支持的运维动作: {action!r}")
