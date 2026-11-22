"""Hephaestus V1.2 Windows 桌面端入口。

启动流程：
1. 检测 Microsoft WebView2 Runtime，缺失时给出中文安装指引并退出；
2. 准备用户数据目录（%LOCALAPPDATA%\\Hephaestus）并设置数据库环境变量；
3. 单实例互斥量检查，避免重复启动多个后端；
4. 在后台线程启动 FastAPI（仅 127.0.0.1，随机可用端口）；
5. 轮询 /health 直到就绪（超时则提示错误）；
6. 使用 pywebview 打开独立窗口加载原有前端页面；
7. 关闭窗口时先留出前端状态写入时间，再优雅停止本地服务。
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from desktop import __version__
from desktop.dialogs import show_error, show_info
from desktop.legacy import LegacyImportError, auto_import_legacy, import_database
from desktop.paths import AppPaths, resolve_paths
from desktop.server import BackendServer, BackendStartError, watch_backend
from desktop.single_instance import SingleInstance
from desktop import server as server_module
from desktop.runtime import (
    WEBVIEW2_DOWNLOAD_URL,
    WebView2MissingError,
    read_webview2_version,
    require_webview2,
    show_webview2_missing_dialog,
)

LOGGER = logging.getLogger("hephaestus.desktop")


def emit_line(text: str) -> None:
    """向标准输出写一行；窗口模式（console=False）下 stdout 为 None 时退回日志。"""
    stream = sys.stdout if sys.stdout is not None else getattr(sys, "__stdout__", None)
    if stream is not None:
        try:
            stream.write(text + "\n")
            stream.flush()
            return
        except (OSError, ValueError):
            pass
    LOGGER.info(text)


def emit_json(payload: dict) -> None:
    emit_line(json.dumps(payload, ensure_ascii=False))


def setup_logging(log_file: Path) -> None:
    """只配置桌面端相关 logger，不影响宿主（例如 pytest）的日志配置。"""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    for name in ("hephaestus", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.handlers[:] = [file_handler, console]
        logger.propagate = False


def assert_safe_database_location(db_path: Path) -> None:
    """禁止把数据库写进 PyInstaller 临时目录或只读的程序目录。"""
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        temp_root = Path(meipass).resolve()
        try:
            db_path.resolve().relative_to(temp_root)
        except ValueError:
            pass
        else:
            raise RuntimeError(f"数据库路径位于打包临时目录，已中止启动: {db_path}")


def prepare_environment(
    paths: AppPaths,
    import_db: Path | None = None,
    allow_auto_import: bool = True,
) -> AppPaths:
    paths.ensure()
    assert_safe_database_location(paths.db_path)
    os.environ["HEPHAESTUS_DATABASE_URL"] = paths.database_url
    os.environ["HEPHAESTUS_DESKTOP"] = "1"
    if import_db is not None:
        backup = import_database(import_db, paths)
        LOGGER.info("已导入指定数据库: source=%s target=%s backup=%s", import_db, paths.db_path, backup)
    elif allow_auto_import:
        try:
            auto_import_legacy(paths)
        except LegacyImportError as exc:
            LOGGER.warning("旧数据库自动导入已跳过: %s", exc)
    LOGGER.info("用户数据目录: %s", paths.root)
    LOGGER.info("数据库文件: %s", paths.db_path)
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="Hephaestus", description="Hephaestus 本地笔记桌面版")
    parser.add_argument("--data-dir", type=Path, default=None, help="覆盖用户数据目录（默认 %%LOCALAPPDATA%%\\Hephaestus）")
    parser.add_argument("--port", type=int, default=None, help="指定后端端口（默认自动选择空闲端口）")
    parser.add_argument("--import-db", type=Path, default=None, help="启动前把指定 SQLite 数据库复制到用户数据目录")
    parser.add_argument("--startup-timeout", type=float, default=25.0, help="等待健康检查的超时秒数")
    parser.add_argument("--headless", action="store_true", help="仅启动本地后端，不打开窗口（自动化测试/排查用）")
    parser.add_argument(
        "--check-runtime",
        nargs="?",
        const="",
        default=None,
        metavar="REPORT",
        help="检查 WebView2 Runtime 并输出 JSON；可把报告写入指定文件（不启动窗口）",
    )
    parser.add_argument("--self-test", type=Path, default=None, metavar="REPORT", help="启动后端并自检，把 JSON 报告写入指定文件后退出（打包验证用）")
    parser.add_argument("--version", action="store_true", help="输出版本号后退出")
    return parser.parse_args(argv)


def run_check_runtime(report_path: str | None = None) -> int:
    """输出 WebView2 Runtime 检测结果，供安装程序和故障排查使用。"""
    version = read_webview2_version()
    payload = {
        "ok": bool(version),
        "version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "webview2": version,
        "download_url": WEBVIEW2_DOWNLOAD_URL,
    }
    if report_path:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_json(payload)
    return 0 if version else 3


def run_headless(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.data_dir)
    if not args.version:
        setup_logging(paths.log_file)
        prepare_environment(paths, import_db=args.import_db)
    backend = BackendServer(port=args.port, startup_timeout=args.startup_timeout)
    try:
        url = backend.start()
    except BackendStartError as exc:
        LOGGER.error("后端启动失败: %s", exc)
        emit_json({"ok": False, "error": str(exc), "db": str(paths.db_path)})
        return 1
    emit_json({"ok": True, "url": url, "db": str(paths.db_path), "log": str(paths.log_file)})
    try:
        for line in sys.stdin:
            if line.strip().lower() in {"stop", "quit", "exit"}:
                break
    except KeyboardInterrupt:  # pragma: no cover - 交互式退出
        pass
    finally:
        backend.stop()
    return 0


def run_self_test(args: argparse.Namespace) -> int:
    """打包后的可执行文件自检：真实启动后端、检查健康接口与数据库文件。"""
    import importlib.metadata as metadata

    paths = resolve_paths(args.data_dir)
    setup_logging(paths.log_file)
    report: dict[str, object] = {
        "ok": False,
        "frozen": bool(getattr(sys, "frozen", False)),
        "db": str(paths.db_path),
        "log": str(paths.log_file),
        "url": None,
        "health": False,
        "webview": None,
        "webview2": read_webview2_version(),
        "error": None,
    }
    backend = BackendServer(port=args.port, startup_timeout=args.startup_timeout)
    try:
        prepare_environment(paths, import_db=args.import_db)
        url = backend.start()
        report["url"] = url
        report["health"] = server_module.check_health(server_module.health_url(backend.host, backend.port))
        report["webview"] = metadata.version("pywebview")
        report["ok"] = bool(report["health"]) and paths.db_path.is_file()
    except Exception as exc:  # noqa: BLE001 - 自检需要把所有失败写入报告
        report["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("self-test 失败")
    finally:
        backend.stop()

    target = Path(args.self_test)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info("self-test 结果: %s", report)
    return 0 if report["ok"] else 1


def run_window(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.data_dir)
    setup_logging(paths.log_file)
    try:
        webview2_version = require_webview2()
    except WebView2MissingError:
        LOGGER.error("未检测到 Microsoft WebView2 Runtime，无法打开窗口")
        show_webview2_missing_dialog()
        return 2
    LOGGER.info("WebView2 Runtime 版本: %s", webview2_version)

    import webview  # 仅在窗口模式导入；此时已确认运行时可用的概率最高

    guard = SingleInstance()
    if not guard.acquire():
        LOGGER.info("检测到已有实例，放弃重复启动")
        show_info("Hephaestus", "Hephaestus 已在运行。\n请切换到已打开的窗口。")
        return 0

    backend = BackendServer(port=args.port, startup_timeout=args.startup_timeout)
    window = None
    try:
        prepare_environment(paths, import_db=args.import_db)
        try:
            url = backend.start()
        except BackendStartError as exc:
            LOGGER.exception("本地服务启动失败")
            show_error(
                "Hephaestus 启动失败",
                f"本地服务未能启动。\n\n{exc}\n\n日志文件：{paths.log_file}",
            )
            return 1

        window = webview.create_window(
            "Hephaestus",
            url,
            width=1280,
            height=820,
            min_size=(960, 600),
            resizable=True,
            background_color="#0f1115",
        )

        def on_loaded() -> None:
            try:
                title = window.evaluate_js("document.title")
            except Exception:  # noqa: BLE001 - 仅用于日志
                title = "?"
            LOGGER.info("桌面窗口已连接本地服务: url=%s document.title=%s", url, title)

        closing_state = {"flushing": False}

        def flush_state_and_close() -> None:
            """在工作线程里触发前端 pagehide 并等待写入完成，避免阻塞 WinForms 消息循环。"""
            try:
                window.evaluate_js("window.dispatchEvent(new Event('pagehide'))")
            except Exception:  # noqa: BLE001 - 窗口可能已经被用户关闭
                LOGGER.debug("关闭前触发 pagehide 失败", exc_info=True)
            # 前端 store.save() 有 350ms 防抖，这里留出足够时间让最后一次写入落到后端。
            time.sleep(0.9)
            LOGGER.info("前端状态写入等待结束，销毁窗口")
            try:
                window.destroy()
            except Exception:  # noqa: BLE001 - 窗口可能已经销毁
                LOGGER.debug("销毁窗口失败", exc_info=True)

        def on_closing() -> bool:
            if closing_state["flushing"]:
                return True
            closing_state["flushing"] = True
            LOGGER.info("收到窗口关闭事件，等待前端状态写入后停止本地服务")
            threading.Thread(
                target=flush_state_and_close,
                name="hephaestus-close",
                daemon=True,
            ).start()
            # 先取消本次关闭，等后台线程完成状态写入后再主动销毁窗口，
            # 否则在 WinForms 的 UI 线程里调用 evaluate_js 会与 WebView2 消息循环互相等待。
            return False

        window.events.loaded += on_loaded
        window.events.closing += on_closing
        watch_backend(url, lambda reason: show_error("Hephaestus 后端异常", f"{reason}\n\n日志文件：{paths.log_file}"))
        LOGGER.info("打开桌面窗口: %s", url)
        webview.start(debug=False, private_mode=False)
        LOGGER.info("窗口已关闭")
        return 0
    except Exception as exc:  # noqa: BLE001 - 任何 UI 初始化失败都要给出明确提示
        LOGGER.exception("桌面窗口启动失败")
        show_error(
            "Hephaestus 启动失败",
            f"无法打开桌面窗口：{exc}\n\n请确认已安装 Microsoft Edge WebView2 Runtime。\n日志文件：{paths.log_file}",
        )
        return 1
    finally:
        backend.stop()
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass
        guard.release()


def main(argv: list[str] | None = None) -> int:
    if getattr(sys, "frozen", False):
        multiprocessing.freeze_support()
    args = parse_args(argv)
    if args.version:
        print(f"Hephaestus {__version__}")
        return 0
    if args.check_runtime is not None:
        return run_check_runtime(args.check_runtime or None)
    if args.self_test is not None:
        return run_self_test(args)
    if args.headless:
        return run_headless(args)
    return run_window(args)


if __name__ == "__main__":
    sys.exit(main())
