#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用隔离数据和模拟信号验证 PID 生命周期及并发互斥。"""

import io
import os
import sys
import threading
import json
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import server as S


_REAL_HEALTH_STATUS = S._health_status
_REAL_IS_SERVER_PROCESS = S._is_server_process
_REAL_LISTENING_SERVER_PID = S._listening_server_pid
PORT = 18199
OLD_PID = 61001
NEW_PID = 61002
LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux", reason="requires real Linux flock semantics"
)


@pytest.fixture(autouse=True)
def isolated_process(tmp_path, monkeypatch):
    # Copy the module facade: mocking kill/getpid/listdir must not affect pytest
    # or unrelated modules through the shared stdlib os module.
    monkeypatch.setattr(S, "os", SimpleNamespace(**vars(os)))
    monkeypatch.setattr(S, "time", SimpleNamespace(sleep=Mock()))
    monkeypatch.setenv("MEDIA_LIB_DIR", str(tmp_path))
    monkeypatch.setattr(S, "DATA", str(tmp_path))
    for name, child in {
        "FILES": "files", "THUMBS": "thumbs", "PREVIEWS": "previews",
        "PLAY_DIR": "play", "IMG_CACHE_DIR": "imgcache",
        "INDEX_JSON": "index.json", "DB_PATH": "media.db",
        "PIDFILE": "server.pid",
    }.items():
        monkeypatch.setattr(S, name, str(tmp_path / child))
    monkeypatch.setattr(S.os, "kill", Mock(side_effect=AssertionError("real signals forbidden")))
    if hasattr(S.os, "killpg"):
        monkeypatch.setattr(S.os, "killpg", Mock(side_effect=AssertionError("real signals forbidden")))
    monkeypatch.setattr(S, "build_opener", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(S, "create_app", Mock(side_effect=AssertionError("real app forbidden")))
    monkeypatch.setattr(S.uvicorn, "run", Mock(side_effect=AssertionError("real server forbidden")))
    monkeypatch.setattr(S, "_health_status", Mock(return_value={}))
    monkeypatch.setattr(S, "_listening_server_pid", Mock(return_value=None))
    monkeypatch.setattr(S, "_is_server_process", Mock(return_value=False))
    return tmp_path / "server.pid"


def test_read_pid_rejects_missing_invalid_and_unreadable_records(isolated_process, monkeypatch):
    pidfile = isolated_process
    assert S._read_pid() is None
    for contents, expected in [("", None), ("garbage", None), ("0", None),
                               ("-12", None), ("12.5", None), (" 61001\n", OLD_PID)]:
        pidfile.write_text(contents, encoding="utf-8")
        assert S._read_pid() == expected, contents
    monkeypatch.setattr(S, "open", Mock(side_effect=PermissionError("PID unreadable")), raising=False)
    assert S._read_pid() is None


def test_cleanup_only_removes_own_pid(isolated_process):
    pidfile = isolated_process
    S._remove_own_pid(OLD_PID)  # Missing records are harmless.
    for contents in (str(NEW_PID), "invalid"):
        pidfile.write_text(contents, encoding="utf-8")
        S._remove_own_pid(OLD_PID)
        assert pidfile.read_text(encoding="utf-8") == contents
    pidfile.write_text(str(OLD_PID), encoding="utf-8")
    S._remove_own_pid(OLD_PID)
    assert not pidfile.exists()
    S._remove_own_pid(OLD_PID)  # Cleanup is idempotent and releases its lock.


def test_start_initialization_failure_cleans_own_pid(isolated_process, monkeypatch):
    monkeypatch.setattr(S.os, "getpid", lambda: OLD_PID)

    def fail_initialization(*, port):
        assert port == PORT
        assert S._read_pid() == OLD_PID
        raise RuntimeError("initialization failed")

    monkeypatch.setattr(S, "create_app", fail_initialization)
    with pytest.raises(RuntimeError, match="initialization failed"):
        S.cmd_start(PORT, "127.0.0.1")
    assert not isolated_process.exists()
    S.uvicorn.run.assert_not_called()


def test_start_shutdown_preserves_replacement_pid(isolated_process, monkeypatch):
    monkeypatch.setattr(S.os, "getpid", lambda: OLD_PID)
    app = object()
    monkeypatch.setattr(S, "create_app", Mock(return_value=app))

    def replacement_started(application, **kwargs):
        assert application is app
        assert kwargs["port"] == PORT
        assert S._read_pid() == OLD_PID
        isolated_process.write_text(str(NEW_PID), encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(S.uvicorn, "run", replacement_started)
    assert S.cmd_start(PORT, "127.0.0.1") == 0
    assert S._read_pid() == NEW_PID


def test_start_existing_service_never_restarts_or_overwrites_pid(isolated_process, capsys):
    # Cover health PID, legacy health without PID (/proc listener), recorded PID
    # during initialization, and a healthy service whose owner is inaccessible.
    for health, listener, identified in [
        ({"ok": True, "pid": OLD_PID}, None, True),
        ({"ok": True}, OLD_PID, False),
        ({}, None, True),
        ({"ok": True}, None, False),
    ]:
        isolated_process.write_text(str(OLD_PID), encoding="utf-8")
        S._health_status.return_value = health
        S._listening_server_pid.return_value = listener
        S._is_server_process.return_value = identified
        assert S.cmd_start(PORT, "127.0.0.1") == 0
        assert S._read_pid() == OLD_PID
        assert "已在运行" in capsys.readouterr().out
    S.create_app.assert_not_called()
    S.uvicorn.run.assert_not_called()
    S.os.kill.assert_not_called()


def test_status_healthy_without_readable_pid_never_probes_with_kill(
    isolated_process, monkeypatch, capsys
):
    S._health_status.return_value = {"ok": True, "pid": OLD_PID}
    S._is_server_process.side_effect = lambda pid, port: (pid, port) == (OLD_PID, PORT)
    assert not isolated_process.exists()
    assert S.cmd_status(PORT) == 0
    assert f"运行中 pid={OLD_PID}" in capsys.readouterr().out

    isolated_process.write_text(str(OLD_PID), encoding="utf-8")
    monkeypatch.setattr(S, "open", Mock(side_effect=PermissionError("PID unreadable")), raising=False)
    assert S.cmd_status(PORT) == 0
    assert "健康检查正常" in capsys.readouterr().out

    # Older health endpoints may not publish a PID at all.
    S._health_status.return_value = {"ok": True}
    assert S.cmd_status(PORT) == 0
    output = capsys.readouterr().out
    assert "运行中" in output and "未知" in output and "未运行" not in output
    S.os.kill.assert_not_called()


def test_status_unhealthy_distinguishes_starting_from_absent(isolated_process, capsys):
    isolated_process.write_text(str(OLD_PID), encoding="utf-8")
    S._is_server_process.return_value = True
    assert S.cmd_status(PORT) != 0
    assert "进程存在但服务未就绪" in capsys.readouterr().out
    S._is_server_process.return_value = False
    assert S.cmd_status(PORT) != 0
    assert "未运行" in capsys.readouterr().out
    S.os.kill.assert_not_called()
    assert S._read_pid() == OLD_PID


def test_stop_permission_denied_preserves_pid(isolated_process, monkeypatch, capsys):
    isolated_process.write_text(str(OLD_PID), encoding="utf-8")
    S._is_server_process.return_value = True
    kill = Mock(side_effect=PermissionError("not owner"))
    monkeypatch.setattr(S.os, "kill", kill)
    assert S.cmd_stop(PORT) != 0
    kill.assert_called_once_with(OLD_PID, S.signal.SIGTERM)
    assert S._read_pid() == OLD_PID
    assert "无权停止" in capsys.readouterr().out
    S.time.sleep.assert_not_called()


def test_stop_timeout_preserves_pid_without_forced_signal(isolated_process, monkeypatch, capsys):
    isolated_process.write_text(str(OLD_PID), encoding="utf-8")
    S._is_server_process.return_value = True
    kill = Mock()
    monkeypatch.setattr(S.os, "kill", kill)
    assert S.cmd_stop(PORT) != 0
    kill.assert_called_once_with(OLD_PID, S.signal.SIGTERM)
    assert S.time.sleep.called  # Waiting is mocked; this test never sleeps.
    assert S._read_pid() == OLD_PID
    assert "停止尚未完成" in capsys.readouterr().out


def test_stop_never_signals_reused_or_unverifiable_pid(isolated_process):
    isolated_process.write_text(str(OLD_PID), encoding="utf-8")
    assert S.cmd_stop(PORT) == 0  # PID now belongs to an unrelated program.
    S._is_server_process.assert_called_with(OLD_PID, PORT)
    S._health_status.return_value = {"ok": True, "pid": OLD_PID}
    assert S.cmd_stop(PORT) != 0  # Healthy but identity cannot be verified.
    S.os.kill.assert_not_called()
    assert S._read_pid() == OLD_PID


def test_stop_concurrent_replacement_survives_cleanup(isolated_process, monkeypatch):
    isolated_process.write_text(str(OLD_PID), encoding="utf-8")
    S._is_server_process.return_value = True

    def replace_while_stopping(pid, sig):
        assert (pid, sig) == (OLD_PID, S.signal.SIGTERM)
        isolated_process.write_text(str(NEW_PID), encoding="utf-8")

    kill = Mock(side_effect=replace_while_stopping)
    monkeypatch.setattr(S.os, "kill", kill)
    assert S.cmd_stop(PORT) == 0
    kill.assert_called_once_with(OLD_PID, S.signal.SIGTERM)
    assert S._read_pid() == NEW_PID


def test_stop_completed_or_already_exited_cleans_own_record(isolated_process, monkeypatch):
    for already_exited in (False, True):
        isolated_process.write_text(str(OLD_PID), encoding="utf-8")
        S._is_server_process.side_effect = [True, False]
        kill = Mock(side_effect=ProcessLookupError() if already_exited else None)
        monkeypatch.setattr(S.os, "kill", kill)
        assert S.cmd_stop(PORT) == 0
        kill.assert_called_once_with(OLD_PID, S.signal.SIGTERM)
        assert not isolated_process.exists()


def test_linux_process_identity_requires_actual_script_and_matching_port(monkeypatch):
    # Simulate /proc rather than reading any process on the machine running pytest.
    monkeypatch.setattr(S, "sys", SimpleNamespace(platform="linux"))
    script = os.path.realpath(S.__file__)
    cases = [
        (["python3", script, "--port", str(PORT)], PORT, True),
        (["python3", script], 18100, True),
        (["python3", script], PORT, False),
        (["python3", script, "--port", "18100"], PORT, False),
        (["python3", "/different/library/server.py", "--port", str(PORT)], PORT, False),
        (["python3", "/tmp/other.py"], PORT, False),
        (["python3", script, "--port"], PORT, False),
        (["python3", script, "--port", "invalid"], PORT, False),
        ([], PORT, False),
    ]
    for flag in ("--stop", "--status", "--repair"):
        cases.append((["python3", script, "--port", str(PORT), flag], PORT, False))
    # argparse accepts --port=VALUE; a script name merely passed as another
    # program's argument must not establish server identity.
    cases.extend([
        (["python3", script, f"--port={PORT}"], PORT, True),
        (["python3", "/tmp/other.py", script, "--port", str(PORT)], PORT, False),
    ])
    mismatches = []
    for argv, port, expected in cases:
        data = b"\0".join(os.fsencode(arg) for arg in argv) + b"\0"
        mocked_open = Mock(side_effect=lambda *args, data=data, **kwargs: io.BytesIO(data))
        monkeypatch.setattr(S, "open", mocked_open, raising=False)
        actual = _REAL_IS_SERVER_PROCESS(OLD_PID, port)
        mocked_open.assert_called_once_with(f"/proc/{OLD_PID}/cmdline", "rb")
        if actual != expected:
            mismatches.append((argv, port, expected, actual))
    for error in (FileNotFoundError(), PermissionError()):
        monkeypatch.setattr(S, "open", Mock(side_effect=error), raising=False)
        assert _REAL_IS_SERVER_PROCESS(OLD_PID, PORT) is False
    assert not mismatches, mismatches


def test_nonlinux_identity_uses_health_pid_for_requested_port(monkeypatch):
    monkeypatch.setattr(S, "sys", SimpleNamespace(platform="win32"))
    S._health_status.side_effect = lambda port: {"ok": True, "pid": OLD_PID} if port == PORT else {}
    assert _REAL_IS_SERVER_PROCESS(OLD_PID, PORT) is True
    assert _REAL_IS_SERVER_PROCESS(NEW_PID, PORT) is False
    assert _REAL_IS_SERVER_PROCESS(OLD_PID, PORT + 1) is False
    assert _REAL_LISTENING_SERVER_PID(PORT) is None
    S.os.kill.assert_not_called()


def test_linux_listener_matches_socket_inode_identity_and_port(monkeypatch):
    monkeypatch.setattr(S, "sys", SimpleNamespace(platform="linux"))

    def row(port, state, inode):
        return f"0: 0100007F:{port:04X} 00000000:0000 {state} 0:0 0:0 0 0 0 {inode}\n"

    tcp = "header\n" + row(PORT + 1, "0A", "10") + row(PORT, "01", "11")
    tcp6 = "header\n" + row(PORT, "0A", "12")

    def proc_open(path, *args, **kwargs):
        assert path in ("/proc/net/tcp", "/proc/net/tcp6")
        return io.StringIO(tcp if path.endswith("/tcp") else tcp6)

    def proc_listdir(path):
        if path == "/proc":
            return ["self", "101", "102", "103", "104", str(OLD_PID)]
        if path == "/proc/101/fd":
            raise PermissionError("other owner")
        if path == "/proc/102/fd":
            raise FileNotFoundError("exited")
        if path == "/proc/103/fd":
            return ["1"]
        assert path == f"/proc/{OLD_PID}/fd"
        return ["raced", "1", "2"]

    def proc_readlink(path):
        if path.endswith("/raced"):
            raise FileNotFoundError("closed fd")
        return "socket:[12]" if path.endswith("/2") else "socket:[10]"

    monkeypatch.setattr(S, "open", proc_open, raising=False)
    monkeypatch.setattr(S.os, "listdir", proc_listdir)
    monkeypatch.setattr(S.os, "readlink", proc_readlink)
    S._is_server_process.side_effect = lambda pid, port: pid != 104 and port == PORT
    assert _REAL_LISTENING_SERVER_PID(PORT) == OLD_PID
    assert _REAL_LISTENING_SERVER_PID(PORT + 2) is None
    assert all(call.args[1] == PORT for call in S._is_server_process.call_args_list)
    # A missing table (e.g. IPv6 disabled) is not fatal.
    monkeypatch.setattr(S, "open", Mock(side_effect=FileNotFoundError()), raising=False)
    assert _REAL_LISTENING_SERVER_PID(PORT) is None


def test_health_probe_ignores_proxies_and_rejects_invalid_responses(monkeypatch):
    for body, expected in [
        (b'{"ok":true,"pid":61001}', {"ok": True, "pid": OLD_PID}),
        (b'{"ok":false}', {}), (b'{"ok":1}', {}),
        (b'[]', {}), (b'null', {}), (b'not json', {}),
    ]:
        opener = Mock()
        opener.open.return_value = io.BytesIO(body)
        factory = Mock(return_value=opener)
        monkeypatch.setattr(S, "build_opener", factory)
        assert _REAL_HEALTH_STATUS(PORT) == expected
        assert factory.call_args.args[0].proxies == {}
        opener.open.assert_called_once_with(f"http://127.0.0.1:{PORT}/healthz", timeout=2)
    opener.open.side_effect = OSError("connection refused")
    assert _REAL_HEALTH_STATUS(PORT) == {}


@LINUX_ONLY
def test_linux_concurrent_starts_serialize_pid_claim(isolated_process, monkeypatch):
    # Independent opens in different threads contend on real flock locks. Events
    # force the second starter to arrive while the first is checking its claim.
    real_guard = S._pid_guard
    real_server_pid = S._server_pid
    checking = threading.Event()
    second_attempted = threading.Event()
    second_checked = threading.Event()
    release_check = threading.Event()
    running = threading.Event()
    release_run = threading.Event()
    errors, results, runs = [], [], []
    monkeypatch.setattr(S.os, "getpid", lambda: OLD_PID if threading.current_thread().name == "starter-one" else NEW_PID)
    S._is_server_process.side_effect = lambda pid, port: pid in (OLD_PID, NEW_PID) and port == PORT

    @contextmanager
    def observed_guard():
        if threading.current_thread().name == "starter-two":
            second_attempted.set()
        with real_guard():
            yield

    def checked_pid(port):
        if S.os.getpid() == OLD_PID:
            checking.set()
            assert release_check.wait(5), "first check not released"
        else:
            second_checked.set()
        return real_server_pid(port)

    def fake_run(app, **kwargs):
        runs.append(S.os.getpid())
        running.set()
        assert release_run.wait(5), "fake server not released"

    def start():
        try:
            results.append(S.cmd_start(PORT, "127.0.0.1"))
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(S, "_pid_guard", observed_guard)
    monkeypatch.setattr(S, "_server_pid", checked_pid)
    monkeypatch.setattr(S, "create_app", Mock(return_value=object()))
    monkeypatch.setattr(S.uvicorn, "run", fake_run)
    first = threading.Thread(target=start, name="starter-one", daemon=True)
    second = threading.Thread(target=start, name="starter-two", daemon=True)
    first.start()
    try:
        assert checking.wait(5)
        second.start()
        assert second_attempted.wait(5)
        assert not second_checked.wait(0.1), "second starter bypassed PID lock"
        release_check.set()
        assert running.wait(5)
        second.join(5)
        assert not second.is_alive()
        assert S._read_pid() == OLD_PID
        assert runs == [OLD_PID]
    finally:
        release_check.set()
        release_run.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors, errors
    assert results == [0, 0]
    assert not isolated_process.exists()


@LINUX_ONLY
def test_linux_cleanup_waits_for_new_pid_writer(isolated_process, monkeypatch):
    real_guard = S._pid_guard
    attempted, finished = threading.Event(), threading.Event()
    errors = []
    isolated_process.write_text(str(OLD_PID), encoding="utf-8")

    @contextmanager
    def observed_guard():
        attempted.set()
        with real_guard():
            yield

    def cleanup():
        try:
            S._remove_own_pid(OLD_PID)
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    monkeypatch.setattr(S, "_pid_guard", observed_guard)
    worker = threading.Thread(target=cleanup, daemon=True)
    try:
        with real_guard():
            worker.start()
            assert attempted.wait(5)
            assert not finished.wait(0.1), "cleanup bypassed PID writer's lock"
            isolated_process.write_text(str(NEW_PID), encoding="utf-8")
    finally:
        if worker.ident is not None:
            worker.join(5)
    assert not worker.is_alive()
    assert not errors, errors
    assert finished.is_set()
    assert S._read_pid() == NEW_PID


@LINUX_ONLY
def test_real_service_missing_pid_status_duplicate_start_and_stop(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "MEDIA_LIB_DIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-B", S.__file__, f"--port={port}"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (tmp_path / "process.log").open("w") as output:
        process = subprocess.Popen(command + ["--host", "127.0.0.1"], env=env, stdout=output, stderr=output)
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=0.5) as response:
                        health = json.load(response)
                    break
                except OSError:
                    assert time.monotonic() < deadline and process.poll() is None
                    time.sleep(0.05)
            assert health["pid"] == process.pid
            pidfile = tmp_path / "server.pid"
            pidfile.unlink()
            for option in (["--status"], ["--host", "127.0.0.1"]):
                result = subprocess.run(command + option, env=env, capture_output=True, text=True, timeout=10)
                assert result.returncode == 0, result.stderr
                assert str(process.pid) in result.stdout
            result = subprocess.run(command + ["--stop"], env=env, capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stdout + result.stderr
            process.wait(timeout=10)
            assert not pidfile.exists()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
