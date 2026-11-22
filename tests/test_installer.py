"""Hephaestus V1.2 安装包集成测试。

这些测试直接驱动 Inno Setup 生成的安装程序，覆盖：
- 首次静默安装、开始菜单快捷方式、程序文件完整性；
- 安装后启动真实 EXE（headless 模式）并写入笔记；
- 覆盖升级不覆盖用户数据；
- 卸载后数据库保留；
- 重装后能读取旧数据。

运行前提：已构建 dist/Hephaestus（onedir）与
dist/installer/Hephaestus-Setup-1.2.0.exe。缺少产物时整体跳过，
以便 CI 在没有 Windows 构建产物的环境下仍能运行其余测试。
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ONEDIR_EXE = PROJECT_ROOT / "dist" / "Hephaestus" / "Hephaestus.exe"
INSTALLER = PROJECT_ROOT / "dist" / "installer" / "Hephaestus-Setup-1.2.0.exe"
REAL_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "Hephaestus" / "hephaestus.db"
START_MENU_DIR = (
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
)

pytestmark = pytest.mark.skipif(
    not INSTALLER.is_file() or not ONEDIR_EXE.is_file(),
    reason="需要先构建 dist/Hephaestus 与 dist/installer/Hephaestus-Setup-1.2.0.exe",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _install(target: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            str(INSTALLER),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            f"/DIR={target}",
            "/TASKS=",
        ]
    )


def _uninstall(target: Path) -> subprocess.CompletedProcess[str]:
    # 覆盖安装后 Inno 可能生成 unins001.exe 等新名称，取编号最大的卸载程序。
    candidates = sorted(target.glob("unins*.exe"), key=lambda path: path.name)
    assert candidates, "安装目录缺少卸载程序"
    return _run([str(candidates[-1]), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_app(exe: Path, data_dir: Path) -> tuple[subprocess.Popen[str], dict[str, object]]:
    port = _free_port()
    process = subprocess.Popen(
        [
            str(exe),
            "--headless",
            "--data-dir",
            str(data_dir),
            "--port",
            str(port),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    lines: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        lines.put(process.stdout.readline())

    threading.Thread(target=reader, daemon=True).start()
    try:
        line = lines.get(timeout=90)
    except queue.Empty:  # pragma: no cover - 启动失败路径
        process.kill()
        raise AssertionError("打包后的 EXE 未在 90 秒内输出启动信息")
    assert line.strip(), "打包后的 EXE 未输出启动信息（可能窗口模式没有标准输出）"
    payload = json.loads(line)
    assert payload["ok"] is True, payload
    return process, payload


def _stop_app(process: subprocess.Popen[str]) -> None:
    assert process.stdin is not None
    process.stdin.write("stop\n")
    process.stdin.flush()
    assert process.wait(timeout=30) == 0


def _note_titles(base_url: str, keyword: str) -> list[str]:
    with httpx.Client(base_url=base_url, timeout=15) as client:
        response = client.get("/notes", params={"keyword": keyword})
        response.raise_for_status()
        return [item["title"] for item in response.json()["items"]]


def _assert_shortcut_removed() -> None:
    leftovers = list(START_MENU_DIR.rglob("Hephaestus.lnk")) if START_MENU_DIR.is_dir() else []
    assert leftovers == [], f"卸载后仍存在开始菜单快捷方式: {leftovers}"


def test_first_install_launch_and_shortcut(tmp_path: Path) -> None:
    target = tmp_path / "app"
    data_dir = tmp_path / "data"
    real_before = _sha256(REAL_DB) if REAL_DB.is_file() else None

    completed = _install(target)
    assert completed.returncode == 0, completed.stderr
    assert (target / "Hephaestus.exe").is_file()
    assert (target / "_internal" / "static" / "index.html").is_file()
    assert (target / "README.md").is_file()
    assert (target / "VERSION").read_text(encoding="utf-8").strip() == "1.2.0"

    shortcuts = list(START_MENU_DIR.rglob("Hephaestus.lnk"))
    assert shortcuts, "首次安装后没有创建开始菜单快捷方式"

    process, payload = _start_app(target / "Hephaestus.exe", data_dir)
    try:
        with httpx.Client(base_url=str(payload["url"]), timeout=15) as client:
            assert client.get("/health").json() == {"status": "ok"}
            created = client.post("/notes", json={"title": "首次安装验证", "content": "安装包启动成功"})
            assert created.status_code == 201, created.text
        assert (data_dir / "hephaestus.db").is_file()
    finally:
        _stop_app(process)

    if real_before is not None:
        assert _sha256(REAL_DB) == real_before, "安装或启动过程修改了真实用户数据库"

    completed = _uninstall(target)
    assert completed.returncode == 0, completed.stderr
    assert not (target / "Hephaestus.exe").exists()
    assert (data_dir / "hephaestus.db").is_file(), "卸载后临时用户数据库被删除"
    _assert_shortcut_removed()


def test_upgrade_uninstall_reinstall_keeps_data(tmp_path: Path) -> None:
    target = tmp_path / "app"
    data_dir = tmp_path / "data"
    real_before = _sha256(REAL_DB) if REAL_DB.is_file() else None

    completed = _install(target)
    assert completed.returncode == 0, completed.stderr
    process, payload = _start_app(target / "Hephaestus.exe", data_dir)
    try:
        with httpx.Client(base_url=str(payload["url"]), timeout=15) as client:
            created = client.post(
                "/notes",
                json={"title": "升级保留验证", "content": "升级、卸载、重装后仍应存在"},
            )
            assert created.status_code == 201, created.text
    finally:
        _stop_app(process)

    database = data_dir / "hephaestus.db"
    database_hash = _sha256(database)

    # 覆盖升级：同一 AppId、同一安装目录。
    completed = _install(target)
    assert completed.returncode == 0, completed.stderr
    assert _sha256(database) == database_hash, "升级安装修改了用户数据库"

    process, payload = _start_app(target / "Hephaestus.exe", data_dir)
    try:
        assert _note_titles(str(payload["url"]), "升级保留验证") == ["升级保留验证"]
    finally:
        _stop_app(process)

    completed = _uninstall(target)
    assert completed.returncode == 0, completed.stderr
    assert not (target / "Hephaestus.exe").exists()
    assert database.is_file(), "卸载删除了用户数据库"
    with sqlite3.connect(database) as connection:
        titles = [row[0] for row in connection.execute("select title from notes order by id")]
    assert "升级保留验证" in titles

    # 重装后读取旧数据。
    completed = _install(target)
    assert completed.returncode == 0, completed.stderr
    process, payload = _start_app(target / "Hephaestus.exe", data_dir)
    try:
        assert _note_titles(str(payload["url"]), "升级保留验证") == ["升级保留验证"]
    finally:
        _stop_app(process)

    if real_before is not None:
        assert _sha256(REAL_DB) == real_before, "安装/升级/卸载过程修改了真实用户数据库"

    assert _uninstall(target).returncode == 0
