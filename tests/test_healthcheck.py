"""健康检查与后端生命周期回归测试（V1.2.1）。

真实故障回归：窗口巡检把服务根地址 http://127.0.0.1:PORT 当作健康接口，
首页返回的 200 HTML 被 JSON 解析失败后误判为“连续 3 次健康检查失败”。
本文件同时覆盖启动宽限、瞬时抖动确认、服务线程退出、超时/状态码/连接
失败分类，以及慢启动和关停时不误报。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from desktop.server import (
    BackendStartError,
    HealthResult,
    check_health,
    ensure_health_url,
    health_url,
    probe_health,
    wait_for_health,
    watch_backend,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _State:
    def __init__(self) -> None:
        self.mode = "ok"          # ok / html / error / flaky
        self.delay = 0.0
        self.hits = 0
        self.fail_until = 0


class _Handler(BaseHTTPRequestHandler):
    server: "_HealthServer"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        state = self.server.state
        if self.path == "/health":
            state.hits += 1
            if state.delay:
                time.sleep(state.delay)
            if state.mode == "error" or (state.mode == "flaky" and state.hits <= state.fail_until):
                self._send(500, b'{"detail":"boom"}', "application/json")
                return
            if state.mode == "html":
                self._send(200, b"<!DOCTYPE html><html><body>Hephaestus</body></html>", "text/html")
                return
            self._send(200, json.dumps({"status": "ok"}).encode(), "application/json")
            return
        # 服务根路径就是前端首页：200 + HTML，旧巡检正是在这里误判。
        self._send(200, b"<!DOCTYPE html><html><body>Hephaestus</body></html>", "text/html")

    def log_message(self, *_args: object) -> None:
        pass


class _HealthServer(ThreadingHTTPServer):
    daemon_threads = True
    state: _State


@pytest.fixture()
def service():
    server = _HealthServer(("127.0.0.1", 0), _Handler)
    server.state = _State()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _wait(callable_, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable_():
            return True
        time.sleep(0.01)
    return False


def test_ensure_health_url_accepts_base_and_full_url() -> None:
    assert ensure_health_url("http://127.0.0.1:50184") == "http://127.0.0.1:50184/health"
    assert ensure_health_url("http://127.0.0.1:50184/") == "http://127.0.0.1:50184/health"
    assert ensure_health_url("http://127.0.0.1:50184/health") == "http://127.0.0.1:50184/health"
    assert ensure_health_url("http://127.0.0.1:50184/health?x=1") == "http://127.0.0.1:50184/health?x=1"


def test_probe_health_base_url_uses_health_endpoint(service) -> None:
    """故障回归：根地址必须规范化为 /health，不得解析首页 HTML。"""
    _server, base = service
    result = probe_health(base)
    assert isinstance(result, HealthResult)
    assert result.ok is True
    assert result.kind == "ok"
    assert result.status_code == 200
    assert result.url == health_url("127.0.0.1", int(base.rsplit(":", 1)[1]))
    assert check_health(base) is True


def test_probe_health_html_payload_is_invalid_payload(service) -> None:
    server, base = service
    server.state.mode = "html"
    result = probe_health(base)
    assert result.ok is False
    assert result.kind == "invalid_payload"
    assert result.status_code == 200
    assert result.error_type in {"JSONDecodeError", "UnicodeDecodeError"}
    assert "DOCTYPE" in (result.body_preview or "")


def test_probe_health_http_error_reports_status(service) -> None:
    server, base = service
    server.state.mode = "error"
    result = probe_health(base)
    assert result.ok is False
    assert result.kind == "http_status"
    assert result.status_code == 500
    assert "500" in result.describe()


def test_probe_health_timeout_is_classified(service) -> None:
    server, base = service
    server.state.delay = 0.35
    result = probe_health(base, timeout=0.1)
    assert result.ok is False
    assert result.kind == "timeout"
    assert result.error_type
    assert result.elapsed_ms >= 50


def test_probe_health_connection_refused_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    import desktop.server as server_module

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise ConnectionRefusedError(10061, "由于目标计算机积极拒绝，无法连接")

    monkeypatch.setattr(server_module._DIRECT_OPENER, "open", refuse)
    result = probe_health("http://127.0.0.1:50184", timeout=0.4)
    assert result.ok is False
    assert result.kind == "connection"
    assert result.error_type == "ConnectionRefusedError"
    assert "kind=connection" in result.describe()
    assert "10061" in (result.error or "")


def test_probe_health_ignores_system_proxy(service, monkeypatch: pytest.MonkeyPatch) -> None:
    """回环健康检查必须直连，不能因系统代理配置被转发。"""
    _server, base = service
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    assert probe_health(base, timeout=0.8).ok is True


def test_watch_backend_base_url_does_not_false_alarm(service) -> None:
    _server, base = service
    failures: list[str] = []
    stop = threading.Event()
    thread = watch_backend(base, failures.append, interval=0.05, failures=2, stop_event=stop)
    time.sleep(0.4)
    stop.set()
    thread.join(timeout=2)
    assert failures == []
    assert not thread.is_alive()


def test_watch_backend_transient_failure_recovers(service) -> None:
    server, base = service
    server.state.mode = "flaky"
    server.state.fail_until = 1
    failures: list[str] = []
    stop = threading.Event()
    thread = watch_backend(base, failures.append, interval=0.05, failures=2, stop_event=stop)
    time.sleep(0.4)
    stop.set()
    thread.join(timeout=2)
    assert failures == []


def test_watch_backend_confirmed_outage_reports_reason(service) -> None:
    server, base = service
    server.state.mode = "error"
    reasons: list[str] = []
    alert = threading.Event()

    def on_failure(reason: str) -> None:
        reasons.append(reason)
        alert.set()

    thread = watch_backend(
        base,
        on_failure,
        interval=0.05,
        failures=2,
        probe_timeout=0.4,
        confirm_timeout=0.4,
    )
    assert alert.wait(timeout=3.0), "连续失败后应提示用户"
    thread.join(timeout=2)
    assert len(reasons) == 1
    reason = reasons[0]
    assert "连续 2 次健康检查失败" in reason
    assert "/health" in reason
    assert "http_status" in reason
    assert "500" in reason


def test_watch_backend_stop_prevents_alert(service) -> None:
    server, base = service
    server.state.mode = "error"
    failures: list[str] = []
    stop = threading.Event()
    thread = watch_backend(base, failures.append, interval=0.05, failures=1, stop_event=stop)
    stop.set()
    thread.join(timeout=2)
    assert failures == []
    assert not thread.is_alive()


def test_watch_backend_startup_grace_suppresses_alert(service) -> None:
    server, base = service
    server.state.mode = "error"
    failures: list[str] = []
    stop = threading.Event()
    thread = watch_backend(
        base,
        failures.append,
        interval=0.05,
        failures=1,
        stop_event=stop,
        startup_grace=5.0,
    )
    time.sleep(0.35)
    assert failures == [], "启动宽限期内不能误报"
    stop.set()
    thread.join(timeout=2)


def test_watch_backend_detects_dead_backend_thread(service) -> None:
    _server, base = service

    class DeadBackend:
        host = "127.0.0.1"
        port = int(base.rsplit(":", 1)[1])
        running = False

    reasons: list[str] = []
    alert = threading.Event()

    def on_failure(reason: str) -> None:
        reasons.append(reason)
        alert.set()

    thread = watch_backend(
        base,
        on_failure,
        interval=0.05,
        failures=3,
        backend=DeadBackend(),
        probe_timeout=0.4,
    )
    assert alert.wait(timeout=3.0)
    thread.join(timeout=2)
    assert reasons and "本地服务已退出（后端线程结束）" in reasons[0]
    assert "服务线程: 已退出" in reasons[0]


def test_wait_for_health_tolerates_slow_start() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    base = f"http://127.0.0.1:{port}"
    server_holder: dict[str, ThreadingHTTPServer] = {}

    def start_later() -> None:
        time.sleep(0.55)
        server = _HealthServer(("127.0.0.1", port), _Handler)
        server.state = _State()
        server_holder["server"] = server
        threading.Thread(target=server.serve_forever, daemon=True).start()

    threading.Thread(target=start_later, daemon=True).start()
    try:
        elapsed = wait_for_health(base, timeout=5.0, interval=0.05)
    finally:
        server = server_holder.get("server")
        if server is not None:
            server.shutdown()
            server.server_close()
    assert elapsed >= 0.45, "应当等到服务真正就绪，而不是第一次连接失败就放弃"


def test_wait_for_health_timeout_contains_url_and_detail(service) -> None:
    server, base = service
    server.state.delay = 2.0
    with pytest.raises(BackendStartError) as excinfo:
        wait_for_health(base, timeout=0.2, interval=0.05)
    message = str(excinfo.value)
    assert "未通过健康检查" in message
    assert "/health" in message
    assert "最后错误" in message
    assert "timeout" in message
    assert "请求超时" in message
