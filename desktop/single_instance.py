"""单实例保护：避免同时启动多个桌面进程/后端实例。"""

from __future__ import annotations

import ctypes
import socket
import sys

MUTEX_NAME = "Hephaestus-Desktop-V1.1"
LOCK_PORT = 51231
ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Windows 命名互斥量实现，其它平台退化为本地端口占用检测。"""

    def __init__(self, name: str = MUTEX_NAME, lock_port: int = LOCK_PORT) -> None:
        self.name = name
        self.lock_port = lock_port
        self.acquired = False
        self._handle: int | None = None
        self._socket: socket.socket | None = None

    def acquire(self) -> bool:
        if self.acquired:
            return True
        if sys.platform == "win32":
            return self._acquire_windows()
        return self._acquire_socket()

    def _acquire_windows(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

        handle = kernel32.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(f"CreateMutexW 失败: {error}")
        if error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        self.acquired = True
        return True

    def _acquire_socket(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", self.lock_port))
            sock.listen(1)
        except OSError:
            sock.close()
            return False
        self._socket = sock
        self.acquired = True
        return True

    def release(self) -> None:
        if self._handle is not None:
            ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        if not self.acquire():
            raise RuntimeError("Hephaestus 已在运行")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
