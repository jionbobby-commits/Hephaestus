"""本地 FastAPI 服务管理：仅监听 127.0.0.1，随机可用端口 + 健康检查轮询。"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import uvicorn

LOGGER = logging.getLogger("hephaestus.desktop.server")

DEFAULT_HOST = "127.0.0.1"

# 健康检查必须直连本机回环地址。如果使用系统代理，代理切换、TUN 模式或
# 代理软件退出都会让 127.0.0.1 的请求被错误转发，造成“服务明明正常却
# 连续健康检查失败”的误报。ProxyHandler({}) 明确禁用所有代理。
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_KIND_LABELS = {
    "ok": "正常",
    "timeout": "请求超时",
    "connection": "连接失败或端口未监听",
    "http_status": "接口返回异常 HTTP 状态码",
    "invalid_payload": "接口返回内容不是预期的健康检查 JSON",
    "unexpected": "未预期的健康检查异常",
}


class BackendStartError(RuntimeError):
    """后端未能在限定时间内启动。"""


@dataclass(frozen=True)
class HealthResult:
    """一次健康检查的完整结果，便于日志和错误提示区分失败类型。"""

    ok: bool
    url: str
    kind: str
    status_code: int | None = None
    elapsed_ms: float = 0.0
    error_type: str | None = None
    error: str | None = None
    body_preview: str | None = None
    traceback_text: str | None = None

    @property
    def label(self) -> str:
        return _KIND_LABELS.get(self.kind, self.kind)

    def describe(self) -> str:
        parts = [f"url={self.url}", f"kind={self.kind}（{self.label}）", f"elapsed={self.elapsed_ms:.0f}ms"]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.error_type:
            parts.append(f"error={self.error_type}: {self.error}")
        if self.body_preview:
            parts.append(f"body={self.body_preview!r}")
        return " ".join(parts)


def find_free_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def ensure_health_url(url: str) -> str:
    """把服务根地址规范化为 /health，避免把首页 HTML 当成健康响应。

    历史问题：窗口巡检曾直接传入 http://127.0.0.1:PORT，请求落在首页 /
    上并返回 200 HTML，JSON 解析失败后被误判为服务异常。这里统一修正，
    同时保留已经传入完整 /health 地址的调用方式。
    """
    parts = urlsplit(url)
    path = parts.path
    if path in ("", "/"):
        path = "/health"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _body_preview(body: bytes) -> str:
    text = body[:180].decode("utf-8", "replace")
    return " ".join(text.split())


def probe_health(url: str, timeout: float = 1.5) -> HealthResult:
    """请求健康接口并返回结构化结果，不抛异常，不吞掉失败原因。"""
    target = ensure_health_url(url)
    started = time.monotonic()
    request = urllib.request.Request(
        target,
        headers={"Connection": "close", "Accept": "application/json"},
        method="GET",
    )
    try:
        with _DIRECT_OPENER.open(request, timeout=timeout) as response:
            body = response.read(4096)
            elapsed = (time.monotonic() - started) * 1000
            status = int(getattr(response, "status", 0) or 0)
            if status != 200:
                return HealthResult(
                    ok=False,
                    url=target,
                    kind="http_status",
                    status_code=status,
                    elapsed_ms=elapsed,
                    error_type="HTTPStatus",
                    error=f"HTTP {status}",
                    body_preview=_body_preview(body),
                )
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return HealthResult(
                    ok=False,
                    url=target,
                    kind="invalid_payload",
                    status_code=status,
                    elapsed_ms=elapsed,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    body_preview=_body_preview(body),
                )
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                return HealthResult(
                    ok=False,
                    url=target,
                    kind="invalid_payload",
                    status_code=status,
                    elapsed_ms=elapsed,
                    error_type="UnexpectedPayload",
                    error=f"payload={payload!r}",
                    body_preview=_body_preview(body),
                )
            return HealthResult(ok=True, url=target, kind="ok", status_code=status, elapsed_ms=elapsed)
    except urllib.error.HTTPError as exc:
        elapsed = (time.monotonic() - started) * 1000
        try:
            body = exc.read(1024)
        except Exception:  # noqa: BLE001 - 读取错误响应体失败时不影响状态码判断
            body = b""
        return HealthResult(
            ok=False,
            url=target,
            kind="http_status",
            status_code=exc.code,
            elapsed_ms=elapsed,
            error_type=type(exc).__name__,
            error=str(exc),
            body_preview=_body_preview(body),
        )
    except (socket.timeout, TimeoutError) as exc:
        elapsed = (time.monotonic() - started) * 1000
        return HealthResult(
            ok=False,
            url=target,
            kind="timeout",
            elapsed_ms=elapsed,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback_text=traceback.format_exc(),
        )
    except urllib.error.URLError as exc:
        elapsed = (time.monotonic() - started) * 1000
        reason = exc.reason
        kind = "timeout" if isinstance(reason, (socket.timeout, TimeoutError)) else "connection"
        return HealthResult(
            ok=False,
            url=target,
            kind=kind,
            elapsed_ms=elapsed,
            error_type=type(reason).__name__ if reason is not None else type(exc).__name__,
            error=str(reason if reason is not None else exc),
            traceback_text=traceback.format_exc(),
        )
    except (ConnectionError, http.client.RemoteDisconnected, http.client.HTTPException) as exc:
        elapsed = (time.monotonic() - started) * 1000
        return HealthResult(
            ok=False,
            url=target,
            kind="connection",
            elapsed_ms=elapsed,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback_text=traceback.format_exc(),
        )
    except Exception as exc:  # noqa: BLE001 - 任何异常都要记录类型和堆栈，不能静默
        elapsed = (time.monotonic() - started) * 1000
        return HealthResult(
            ok=False,
            url=target,
            kind="unexpected",
            elapsed_ms=elapsed,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback_text=traceback.format_exc(),
        )


def check_health(url: str, timeout: float = 1.5) -> bool:
    """兼容旧调用：返回布尔值；详细失败原因通过 probe_health 获取。"""
    return probe_health(url, timeout=timeout).ok


def wait_for_health(
    url: str,
    timeout: float = 20.0,
    interval: float = 0.1,
    abort: Callable[[], bool] | None = None,
) -> float:
    """轮询健康检查接口，成功返回耗时；超时或后端提前退出时抛错。"""
    target = ensure_health_url(url)
    started = time.monotonic()
    deadline = started + timeout
    last: HealthResult | None = None
    while time.monotonic() < deadline:
        last = probe_health(target)
        if last.ok:
            return time.monotonic() - started
        LOGGER.debug("等待本地服务健康检查: %s", last.describe())
        if abort is not None and abort():
            detail = last.describe() if last is not None else "没有任何健康检查响应"
            raise BackendStartError(f"本地服务在启动过程中退出，健康检查失败: {detail}")
        time.sleep(interval)
    detail = last.describe() if last is not None else "没有任何健康检查响应"
    raise BackendStartError(
        f"本地服务在 {timeout:.1f} 秒内未通过健康检查: {target}（最后错误: {detail}）"
    )


class BackendServer:
    """在后台线程中运行 uvicorn，并提供确定性的启动/停止接口。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int | None = None,
        startup_timeout: float = 25.0,
        attempts: int = 3,
    ) -> None:
        self.host = host
        self.requested_port = port
        self.startup_timeout = startup_timeout
        self.attempts = max(1, attempts)
        self.port: int = 0
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> str:
        return health_url(self.host, self.port)

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive() and not self._stop_event.is_set())

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def start(self) -> str:
        if self.running:
            return self.url
        # 延迟导入：调用方必须先设置 HEPHAESTUS_DATABASE_URL 等环境变量。
        from app.main import app as fastapi_app

        self._stop_event.clear()
        self._server = None
        self._thread = None
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            port = self.requested_port if attempt == 1 and self.requested_port else find_free_port(self.host)
            config = uvicorn.Config(
                app=fastapi_app,
                host=self.host,
                port=port,
                log_config=None,      # 保留桌面端自己的日志配置
                log_level="warning",
                access_log=False,     # 不记录请求路径，避免搜索关键词等进入日志
                lifespan="on",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, name="hephaestus-backend", daemon=True)
            thread.start()
            try:
                elapsed = wait_for_health(
                    health_url(self.host, port),
                    timeout=self.startup_timeout,
                    abort=lambda: (
                        not thread.is_alive()
                        or bool(server.should_exit)
                        or self._stop_event.is_set()
                    ),
                )
            except BackendStartError as exc:
                last_error = exc
                LOGGER.warning("后端第 %d 次启动尝试失败（port=%s）: %s", attempt, port, exc)
                server.should_exit = True
                thread.join(timeout=5.0)
                continue
            if not thread.is_alive() or server.should_exit:
                last_error = BackendStartError(
                    f"健康检查通过但后端线程已退出（port={port}, thread_alive={thread.is_alive()}, "
                    f"should_exit={server.should_exit}）"
                )
                LOGGER.warning("后端第 %d 次启动尝试在健康检查后退出（port=%s）", attempt, port)
                server.should_exit = True
                thread.join(timeout=5.0)
                continue
            self._server = server
            self._thread = thread
            self.port = port
            LOGGER.info("本地服务已启动: %s（健康检查 %.0f ms）", self.url, elapsed * 1000)
            return self.url
        raise BackendStartError(f"本地服务启动失败（已尝试 {self.attempts} 次）: {last_error}")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        server, thread = self._server, self._thread
        if server is None:
            return
        LOGGER.info("正在停止本地服务: %s", self.url)
        server.should_exit = True
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                LOGGER.warning("本地服务未在 %.1f 秒内完全停止", timeout)
        self._server = None
        self._thread = None

    def __enter__(self) -> "BackendServer":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def _sleep_interruptible(seconds: float, stop_event: threading.Event) -> bool:
    """可被停止事件打断的 sleep；返回 False 表示应停止巡检。"""
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if stop_event.is_set():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.2, remaining))


def watch_backend(
    url: str,
    on_failure: Callable[[str], None],
    interval: float = 3.0,
    failures: int = 3,
    *,
    backend: BackendServer | None = None,
    stop_event: threading.Event | None = None,
    startup_grace: float = 0.0,
    probe_timeout: float = 1.5,
    confirm_timeout: float = 3.0,
) -> threading.Thread:
    """后台巡检：连续健康检查失败且确认服务确实不可用时才提示用户。

    - url 可以是服务根地址或完整 /health 地址，内部统一规范化；
    - 传入 backend 时同时检查后端线程是否存活；
    - stop_event 用于窗口关闭/服务停止时立即退出，避免关窗时误报；
    - startup_grace 内只记录日志，不弹窗，覆盖窗口初始化较慢的机器；
    - 达到失败阈值后先用更长超时确认一次，区分瞬时抖动和真实故障。
    """

    stop = stop_event if stop_event is not None else threading.Event()
    try:
        target = health_url(backend.host, backend.port) if backend is not None and backend.port else ensure_health_url(url)
    except Exception as exc:  # noqa: BLE001 - 配置错误也要给出明确日志
        LOGGER.error("健康巡检地址无效: %r (%s: %s)", url, type(exc).__name__, exc)
        target = url

    def _service_state() -> str:
        if backend is None:
            return "未跟踪（仅按 HTTP 检查判断）"
        return "运行中" if backend.running else "已退出"

    def _report(reason: str) -> None:
        if stop.is_set():
            LOGGER.info("健康巡检已停止，忽略失败提示")
            return
        try:
            on_failure(reason)
        except Exception:  # noqa: BLE001 - 提示失败不能影响主线程
            LOGGER.exception("健康巡检失败提示回调异常")

    def _loop() -> None:
        started = time.monotonic()
        grace_until = started + max(0.0, startup_grace)
        strikes = 0
        LOGGER.info(
            "启动本地服务健康巡检: %s（interval=%.1fs, failures=%d, grace=%.1fs）",
            target,
            interval,
            max(1, failures),
            max(0.0, startup_grace),
        )
        while True:
            if not _sleep_interruptible(interval, stop):
                LOGGER.info("本地服务健康巡检结束（服务已停止）")
                return
            if stop.is_set():
                LOGGER.info("本地服务健康巡检结束（服务已停止）")
                return

            in_grace = time.monotonic() < grace_until
            if backend is not None and not backend.running and not in_grace:
                last = probe_health(target, timeout=probe_timeout)
                detail = last.describe() if not last.ok else "HTTP 健康检查仍成功，但后端线程已退出"
                reason = (
                    "本地服务已退出（后端线程结束）\n"
                    f"地址: {target}\n"
                    f"服务线程: {_service_state()}\n"
                    f"最后检查: {detail}"
                )
                LOGGER.error("%s", reason)
                _report(reason)
                return

            result = probe_health(target, timeout=probe_timeout)
            if result.ok:
                if strikes:
                    LOGGER.info("本地服务健康检查已恢复（此前连续失败 %d 次）: %s", strikes, target)
                strikes = 0
                continue

            if in_grace:
                LOGGER.warning(
                    "启动宽限期内健康检查失败（暂不提示用户）: %s；服务线程=%s",
                    result.describe(),
                    _service_state(),
                )
                continue

            strikes += 1
            LOGGER.warning(
                "本地服务健康检查失败（%d/%d）: %s；服务线程=%s",
                strikes,
                max(1, failures),
                result.describe(),
                _service_state(),
            )
            if result.traceback_text and result.kind == "unexpected":
                LOGGER.warning("健康检查异常堆栈:\n%s", result.traceback_text)

            if strikes < max(1, failures):
                continue
            if stop.is_set():
                return

            # 达到阈值后做一次更长超时的确认检查，避免把瞬时抖动当成故障。
            LOGGER.warning("连续失败达到阈值，执行确认健康检查: %s", target)
            confirmation = probe_health(target, timeout=max(confirm_timeout, probe_timeout))
            if confirmation.ok:
                LOGGER.warning("确认健康检查成功，判定为瞬时抖动，不提示用户: %s", target)
                strikes = 0
                continue
            if backend is not None and not backend.running:
                reason = (
                    "本地服务已退出（后端线程结束）\n"
                    f"地址: {target}\n"
                    f"服务线程: {_service_state()}\n"
                    f"最后错误: {confirmation.describe()}"
                )
            else:
                reason = (
                    f"本地服务连续 {strikes} 次健康检查失败，确认检查仍失败\n"
                    f"地址: {target}\n"
                    f"失败类型: {confirmation.kind}（{confirmation.label}）\n"
                    f"服务线程: {_service_state()}\n"
                    f"最后错误: {confirmation.describe()}"
                )
            LOGGER.error("%s", reason)
            if confirmation.traceback_text and confirmation.kind in {"unexpected", "timeout", "connection"}:
                LOGGER.error("确认检查异常堆栈:\n%s", confirmation.traceback_text)
            if stop.is_set():
                return
            _report(reason)
            return

    thread = threading.Thread(target=_loop, name="hephaestus-watchdog", daemon=True)
    thread.start()
    return thread
