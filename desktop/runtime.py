"""WebView2 Runtime 检测与缺失提示（V1.2）。

Hephaestus 的窗口依赖 Microsoft Edge WebView2 Runtime。普通 Windows 10/11
通常已随 Edge 浏览器安装，但精简系统或长期未更新的镜像可能缺失。这里在
打开窗口之前主动检测，缺失时给出中文说明和微软官方下载地址，而不是抛出
底层异常或静默退出。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from collections.abc import Callable

LOGGER = logging.getLogger("hephaestus.desktop")

# Microsoft 官方登记的 WebView2 Runtime 客户端 GUID。
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_CLIENT_KEY = rf"Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"

# 官方说明页与 Evergreen 在线安装器（由 Microsoft 托管，不在本项目中打包）。
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
WEBVIEW2_BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

MESSAGE_TITLE = "Hephaestus - 缺少 WebView2 Runtime"


class WebView2MissingError(RuntimeError):
    """当前系统没有可用的 WebView2 Runtime。"""


def read_webview2_version() -> str | None:
    """读取已安装的 WebView2 Runtime 版本；未安装时返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows 平台
        return None

    # 64 位系统上 Inno/Edge 会写入 WOW6432Node；不同安装方式也可能写 64 位视图或 HKCU。
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{WEBVIEW2_CLIENT_KEY}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{WEBVIEW2_CLIENT_KEY}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\{WEBVIEW2_CLIENT_KEY}"),
    ]
    for hive, subkey in locations:
        for access in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, subkey, 0, access) as key:
                    value, _ = winreg.QueryValueEx(key, "pv")
            except OSError:
                continue
            version = str(value).strip()
            if version and version not in {"0.0.0.0", "0.0.0"}:
                return version
    return None


def webview2_missing_message() -> str:
    """返回给最终用户看的中文说明（包含微软官方安装指引）。"""
    return (
        "Hephaestus 使用 Windows 的 WebView2 组件显示界面，"
        "但当前系统未检测到 Microsoft WebView2 Runtime。\n\n"
        "请按以下步骤安装（不需要安装 Python）：\n"
        f"1. 打开微软官方下载页面：\n   {WEBVIEW2_DOWNLOAD_URL}\n"
        "2. 下载并运行“Evergreen Standalone Installer”（x64）。\n"
        "3. 安装完成后重新打开 Hephaestus。\n\n"
        "如果电脑无法联网，请联系管理员部署 WebView2 Runtime。"
    )


def open_webview2_download_page() -> bool:
    """用默认浏览器打开微软官方下载页。"""
    try:
        if sys.platform == "win32":
            os.startfile(WEBVIEW2_DOWNLOAD_URL)  # type: ignore[attr-defined]
        else:  # pragma: no cover - 非 Windows 平台
            import webbrowser

            webbrowser.open(WEBVIEW2_DOWNLOAD_URL)
        return True
    except OSError:
        LOGGER.warning("无法自动打开浏览器，请手动访问 %s", WEBVIEW2_DOWNLOAD_URL)
        return False


def show_webview2_missing_dialog(message: str | None = None) -> None:
    """弹出中文错误框，并询问是否打开官方下载页；失败时退回标准错误输出。"""
    text = message or webview2_missing_message()
    if sys.platform == "win32":
        try:
            mb_yesno = 0x00000004
            mb_iconerror = 0x00000010
            idyes = 6
            answer = ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                None,
                text + "\n\n是否现在打开微软官方下载页面？",
                MESSAGE_TITLE,
                mb_yesno | mb_iconerror,
            )
            if answer == idyes:
                open_webview2_download_page()
            return
        except Exception:  # noqa: BLE001 - 提示失败也要继续走 stderr 兜底
            LOGGER.exception("显示 WebView2 缺失提示失败")
    print(f"[ERROR] {MESSAGE_TITLE}: {text}", file=sys.stderr, flush=True)


def require_webview2(version_getter: Callable[[], str | None] = read_webview2_version) -> str:
    """确认 WebView2 可用并返回版本号，否则抛出 WebView2MissingError。"""
    version = version_getter()
    if not version:
        raise WebView2MissingError(webview2_missing_message())
    return version
