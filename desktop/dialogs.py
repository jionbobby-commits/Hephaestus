"""最小化的原生提示框（失败时退化为控制台输出）。"""

from __future__ import annotations

import ctypes
import sys

MB_ICONERROR = 0x00000010
MB_ICONINFORMATION = 0x00000040


def _message_box(title: str, text: str, flags: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
        return True
    except Exception:
        return False


def show_error(title: str, text: str) -> None:
    if not _message_box(title, text, MB_ICONERROR):
        print(f"[ERROR] {title}: {text}", file=sys.stderr, flush=True)


def show_info(title: str, text: str) -> None:
    if not _message_box(title, text, MB_ICONINFORMATION):
        print(f"[INFO] {title}: {text}", file=sys.stderr, flush=True)
