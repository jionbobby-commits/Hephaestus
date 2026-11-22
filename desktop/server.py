"""本地 FastAPI 服务管理：仅监听 127.0.0.1，随机可用端口 + 健康检查轮询。"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.request
from typing import Callable

import uvicorn

LOGGER = logging.getLogger("hephaestus.desktop.server")

DEFAULT_HOST = "127.0.0.1"


class BackendStartError(RuntimeError):
    """后端未能在限定时间内启动。"""


def find_free_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def check_health(url: str, timeout: float = 1.5) -> bool:
    try:
        request = urllib.request.Request(url, headers={"Connection": "close"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except Exception:  # noqa: BLE001 - 健康检查失败原因很多，统一视为未就绪
        return False


def wait_for_health(
    url: str,
    timeout: float = 20.0,
    interval: float = 0.1,
    abort: Callable[[], bool] | None = None,
) -> float:
    """轮询健康检查接口，成功返回耗时；超时或后端提前退出时抛错。"""
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        if check_health(url):
            return time.monotonic() - started
        if abort is not None and abort():
            raise BackendStartError("本地服务在启动过程中退出，健康检查失败")
        time.sleep(interval)
    raise BackendStartError(f"本地服务在 {timeout:.1f} 秒内未通过健康检查: {url}")


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

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> str:
        if self.running:
            return self.url
        # 延迟导入：调用方必须先设置 HEPHAESTUS_DATABASE_URL 等环境变量。
        from app.main import app as fastapi_app

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
                wait_for_health(
                    health_url(self.host, port),
                    timeout=self.startup_timeout,
                    abort=lambda: not thread.is_alive(),
                )
            except BackendStartError as exc:
                last_error = exc
                LOGGER.warning("后端第 %d 次启动尝试失败（port=%s）: %s", attempt, port, exc)
                server.should_exit = True
                thread.join(timeout=5.0)
                continue
            self._server = server
            self._thread = thread
            self.port = port
            LOGGER.info("本地服务已启动: %s", self.url)
            return self.url
        raise BackendStartError(f"本地服务启动失败（已尝试 {self.attempts} 次）: {last_error}")

    def stop(self, timeout: float = 10.0) -> None:
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


def watch_backend(url: str, on_failure: Callable[[str], None], interval: float = 3.0, failures: int = 3) -> threading.Thread:
    """后台巡检：连续多次健康检查失败时提示用户。"""

    def _loop() -> None:
        strikes = 0
        while True:
            time.sleep(interval)
            if check_health(url):
                strikes = 0
                continue
            strikes += 1
            if strikes >= failures:
                on_failure(f"本地服务连续 {strikes} 次健康检查失败: {url}")
                return

    thread = threading.Thread(target=_loop, name="hephaestus-watchdog", daemon=True)
    thread.start()
    return thread
