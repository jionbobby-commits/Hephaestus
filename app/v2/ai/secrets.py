"""Independent secret storage for AI provider keys.

The SQLite database only ever stores a random key_ref. Secret material lives in
the OS-protected store chosen here; tests inject InMemorySecretStore.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

SERVICE_NAME = "hephaestus-ai"


class SecretStoreError(Exception):
    pass


class SecretStore(Protocol):
    def has(self, ref: str) -> bool: ...

    def get(self, ref: str) -> str | None: ...

    def set(self, ref: str, secret: str) -> None: ...

    def delete(self, ref: str) -> None: ...


class InMemorySecretStore:
    """Test and headless fallback; never persisted."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data = dict(initial or {})
        self._lock = threading.Lock()

    def has(self, ref: str) -> bool:
        with self._lock:
            return bool(self._data.get(ref))

    def get(self, ref: str) -> str | None:
        with self._lock:
            return self._data.get(ref) or None

    def set(self, ref: str, secret: str) -> None:
        with self._lock:
            self._data[ref] = secret

    def delete(self, ref: str) -> None:
        with self._lock:
            self._data.pop(ref, None)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi_protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("当前平台没有可用的 DPAPI 密钥存储")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    in_blob, keep = _blob(data)
    out_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), "Hephaestus AI", None, None, None, 0x1, ctypes.byref(out_blob)
    )
    if not ok:
        raise SecretStoreError(f"DPAPI 加密失败（{ctypes.get_last_error()}）")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("当前平台没有可用的 DPAPI 密钥存储")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    in_blob, keep = _blob(data)
    out_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
    )
    if not ok:
        raise SecretStoreError("无法解密已保存的 API Key，可能由其他 Windows 用户创建")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _default_secret_path() -> Path:
    override = os.getenv("HEPHAESTUS_SECRET_DIR")
    if override:
        return Path(override).expanduser() / "ai-secrets.json"
    data_dir = os.getenv("HEPHAESTUS_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser() / "secrets" / "ai-secrets.json"
    if sys.platform == "win32":
        root = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "Hephaestus" / "secrets" / "ai-secrets.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Hephaestus" / "secrets" / "ai-secrets.json"
    root = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(root) / "Hephaestus" / "secrets" / "ai-secrets.json"


class FileSecretStore:
    """DPAPI-protected JSON file (Windows). Ciphertext only, atomic writes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_secret_path()
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("secret file root must be an object")
            secrets = raw.get("secrets", {})
            if not isinstance(secrets, dict):
                raise ValueError("secret file secrets must be an object")
            return {str(k): str(v) for k, v in secrets.items()}
        except (OSError, ValueError) as exc:
            raise SecretStoreError("密钥存储文件损坏，未读取明文") from exc

    def _write(self, secrets: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "secrets": secrets}, ensure_ascii=False)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
            ) as handle:
                temp_name = handle.name
                handle.write(payload)
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, self.path)
        except OSError as exc:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise SecretStoreError("无法写入密钥存储") from exc

    def has(self, ref: str) -> bool:
        with self._lock:
            return ref in self._read()

    def get(self, ref: str) -> str | None:
        with self._lock:
            encoded = self._read().get(ref)
        if not encoded:
            return None
        try:
            cipher = base64.b64decode(encoded.encode("ascii"), validate=True)
            return _dpapi_unprotect(cipher).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecretStoreError("密钥存储内容损坏") from exc

    def set(self, ref: str, secret: str) -> None:
        cipher = _dpapi_protect(secret.encode("utf-8"))
        encoded = base64.b64encode(cipher).decode("ascii")
        with self._lock:
            data = self._read()
            data[ref] = encoded
            self._write(data)

    def delete(self, ref: str) -> None:
        with self._lock:
            data = self._read()
            if ref in data:
                data.pop(ref, None)
                self._write(data)


class KeyringSecretStore:
    def __init__(self, service: str = SERVICE_NAME) -> None:
        try:
            import keyring  # type: ignore
        except Exception as exc:  # pragma: no cover - platform dependent
            raise SecretStoreError("keyring 不可用") from exc
        self._keyring = keyring
        self.service = service

    def has(self, ref: str) -> bool:
        return bool(self.get(ref))

    def get(self, ref: str) -> str | None:
        try:
            return self._keyring.get_password(self.service, ref)
        except Exception as exc:
            raise SecretStoreError("系统凭据库读取失败") from exc

    def set(self, ref: str, secret: str) -> None:
        try:
            self._keyring.set_password(self.service, ref, secret)
        except Exception as exc:
            raise SecretStoreError("系统凭据库写入失败") from exc

    def delete(self, ref: str) -> None:
        try:
            self._keyring.delete_password(self.service, ref)
        except Exception:
            pass


class SecretToolStore:
    """Linux Secret Service via secret-tool; secret travels over stdin only."""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self.binary = shutil.which("secret-tool") or ""
        self.service = service
        if not self.binary:
            raise SecretStoreError("secret-tool 不可用")

    def _run(self, args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.binary, *args],
                input=input_text,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError("secret-tool 调用失败") from exc

    def has(self, ref: str) -> bool:
        return self.get(ref) is not None

    def get(self, ref: str) -> str | None:
        result = self._run(["lookup", "service", self.service, "key", ref])
        if result.returncode == 3:
            return None
        if result.returncode != 0:
            raise SecretStoreError("系统密钥环读取失败")
        return result.stdout.rstrip("\n") or None

    def set(self, ref: str, secret: str) -> None:
        result = self._run(
            ["store", "--label=Hephaestus AI", "service", self.service, "key", ref],
            input_text=secret,
        )
        if result.returncode != 0:
            raise SecretStoreError("系统密钥环写入失败")

    def delete(self, ref: str) -> None:
        self._run(["clear", "service", self.service, "key", ref])


class MacKeychainStore:
    def __init__(self, service: str = SERVICE_NAME) -> None:
        self.binary = shutil.which("security") or ""
        self.service = service
        if not self.binary:
            raise SecretStoreError("macOS security 命令不可用")

    def has(self, ref: str) -> bool:
        return self.get(ref) is not None

    def get(self, ref: str) -> str | None:
        result = subprocess.run(
            [self.binary, "find-generic-password", "-s", self.service, "-a", ref, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.rstrip("\n") or None

    def set(self, ref: str, secret: str) -> None:
        result = subprocess.run(
            [self.binary, "add-generic-password", "-U", "-s", self.service, "-a", ref, "-w", secret],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise SecretStoreError("钥匙串写入失败")

    def delete(self, ref: str) -> None:
        subprocess.run(
            [self.binary, "delete-generic-password", "-s", self.service, "-a", ref],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )


def default_secret_store() -> SecretStore:
    backend = os.getenv("HEPHAESTUS_SECRET_BACKEND", "").strip().lower()
    if backend == "memory":
        return InMemorySecretStore()
    if backend in {"keyring", "secret-tool", "macos", "file"}:
        if backend == "keyring":
            return KeyringSecretStore()
        if backend == "secret-tool":
            return SecretToolStore()
        if backend == "macos":
            return MacKeychainStore()
        return FileSecretStore()
    try:
        import keyring  # noqa: F401

        return KeyringSecretStore()
    except Exception:
        pass
    if sys.platform == "win32":
        return FileSecretStore()
    if sys.platform == "darwin":
        try:
            return MacKeychainStore()
        except SecretStoreError:
            pass
    try:
        return SecretToolStore()
    except SecretStoreError as exc:
        raise SecretStoreError("没有可用的系统密钥存储，请设置 HEPHAESTUS_SECRET_BACKEND") from exc
