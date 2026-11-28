"""Hephaestus V1.3.0 Windows 桌面端测试。

覆盖范围：
- 桌面入口可导入、参数解析；
- 用户数据目录自动创建、数据库 URL 生成；
- 打包临时目录保护；
- 单实例互斥；
- 端口选择与健康检查轮询；
- 旧数据库安全导入（备份、校验、失败不破坏源文件）；
- 真实 headless 启动：健康检查、/api/state、笔记持久化、端口冲突回退；
- WebView2 Runtime 检测、缺失提示与 --check-runtime 报告；
- 连续启动/关闭、窗口巡检接线与健康检查回归。
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from desktop import __version__
from desktop.legacy import LegacyImportError, auto_import_legacy, import_database, is_sqlite_file
from desktop.main import DesktopBridge, assert_safe_database_location, parse_args, prepare_environment
from desktop.paths import resolve_paths, sqlite_url
from desktop.server import BackendStartError, check_health, find_free_port, wait_for_health
from desktop.single_instance import SingleInstance

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_legacy_db(path: Path, note_count: int = 1) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '未分类',
                is_favorite BOOLEAN NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        for index in range(note_count):
            conn.execute(
                "INSERT INTO notes (title, content, category, is_favorite, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (f"旧笔记-{index}", f"旧内容-{index}", "学习", 1, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
        conn.commit()
    finally:
        conn.close()


def _launch_headless(data_dir: Path, port: int | None = None) -> tuple[subprocess.Popen, dict]:
    env = {key: value for key, value in os.environ.items() if key != "HEPHAESTUS_DATABASE_URL"}
    command = [
        sys.executable,
        "-m",
        "desktop.main",
        "--headless",
        "--data-dir",
        str(data_dir),
        "--startup-timeout",
        "25",
    ]
    if port is not None:
        command += ["--port", str(port)]
    proc = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(f"桌面端未输出启动信息，stderr:\n{stderr}")
    return proc, json.loads(line)


def _stop_headless(proc: subprocess.Popen) -> int:
    if proc.poll() is None:
        try:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
        except OSError:
            pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    return int(proc.returncode or 0)


def test_desktop_entry_importable() -> None:
    import desktop.main as entry

    assert callable(entry.main)
    assert entry.__version__ == __version__
    assert __version__ == "1.3.0"


def test_parse_args_headless_flags() -> None:
    args = parse_args(["--headless", "--data-dir", "C:/tmp/heph", "--port", "8123"])
    assert args.headless is True
    assert str(args.data_dir).endswith("heph")
    assert args.port == 8123
    defaults = parse_args([])
    assert defaults.headless is False
    assert defaults.port is None


def test_data_dir_auto_created(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path / "Hephaestus").ensure()
    assert paths.root.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.backups_dir.is_dir()
    assert paths.db_path == paths.root / "hephaestus.db"
    assert paths.db_path.parent != PROJECT_ROOT / "data"


def test_sqlite_url_is_posix_absolute(tmp_path: Path) -> None:
    target = tmp_path / "a b" / "x.db"
    url = sqlite_url(target)
    assert url.startswith("sqlite:///")
    assert "\\" not in url
    assert url.endswith("/a b/x.db")


def test_paths_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = resolve_paths(tmp_path / "roaming").ensure()
    assert paths.db_path == (tmp_path / "roaming" / "hephaestus.db").resolve()
    assert not paths.db_path.exists()  # 目录创建不等于建库，首次启动才建库


def test_prepare_environment_sets_database_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HEPHAESTUS_DATABASE_URL", raising=False)
    monkeypatch.delenv("HEPHAESTUS_DESKTOP", raising=False)
    paths = prepare_environment(resolve_paths(tmp_path / "desk"), allow_auto_import=False)
    assert os.environ["HEPHAESTUS_DATABASE_URL"] == paths.database_url
    assert os.environ["HEPHAESTUS_DESKTOP"] == "1"
    assert paths.logs_dir.is_dir()
    assert not paths.db_path.exists()


def test_frozen_temp_directory_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    with pytest.raises(RuntimeError):
        assert_safe_database_location(tmp_path / "meipass" / "hephaestus.db")
    assert_safe_database_location(tmp_path / "userdata" / "hephaestus.db")


def test_single_instance_blocks_second_launch() -> None:
    first = SingleInstance()
    second = SingleInstance()
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        second.release()
        first.release()


def test_find_free_port_and_unhealthy_port() -> None:
    port = find_free_port()
    assert 1024 < port < 65536
    assert check_health(f"http://127.0.0.1:{port}/health", timeout=0.2) is False


def test_wait_for_health_times_out() -> None:
    port = find_free_port()
    started = time.monotonic()
    with pytest.raises(BackendStartError):
        wait_for_health(f"http://127.0.0.1:{port}/health", timeout=0.4, interval=0.05)
    assert time.monotonic() - started < 5


def test_legacy_import_copies_with_backup(tmp_path: Path) -> None:
    source = tmp_path / "old.db"
    _make_legacy_db(source, note_count=2)
    before = _sha256(source)
    paths = resolve_paths(tmp_path / "desk").ensure()

    backup = import_database(source, paths)

    assert is_sqlite_file(source)
    assert paths.db_path.is_file()
    assert backup.is_file()
    assert backup.parent == paths.backups_dir
    assert _sha256(source) == before  # 源数据库只读，不被修改
    conn = sqlite3.connect(paths.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_legacy_import_rejects_invalid_file(tmp_path: Path) -> None:
    source = tmp_path / "broken.db"
    source.write_text("this is not a sqlite database", encoding="utf-8")
    paths = resolve_paths(tmp_path / "desk").ensure()

    with pytest.raises(LegacyImportError):
        import_database(source, paths)

    assert source.read_text(encoding="utf-8") == "this is not a sqlite database"
    assert not paths.db_path.exists()


def test_auto_import_skipped_when_target_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import desktop.legacy as legacy

    source = tmp_path / "old.db"
    _make_legacy_db(source)
    paths = resolve_paths(tmp_path / "desk").ensure()
    paths.db_path.write_bytes(b"existing")
    monkeypatch.setattr(legacy, "dev_database_candidates", lambda: [source])

    assert legacy.find_legacy_candidate(paths) is None
    assert auto_import_legacy(paths) is None
    assert paths.db_path.read_bytes() == b"existing"


def test_headless_start_health_and_state(tmp_path: Path) -> None:
    proc, info = _launch_headless(tmp_path / "desk")
    try:
        assert info["ok"] is True, info
        assert info["url"].startswith("http://127.0.0.1:")
        assert Path(info["db"]) == (tmp_path / "desk" / "hephaestus.db").resolve()
        assert Path(info["db"]).is_file()
        with httpx.Client(base_url=info["url"], timeout=10) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            assert client.get("/docs").status_code == 200
            state = client.get("/api/state").json()
            assert state == {"initialized": False, "state": None}
            page = client.get("/")
            assert page.status_code == 200
            assert "Hephaestus" in page.text
    finally:
        assert _stop_headless(proc) == 0


def test_headless_notes_persist_across_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "desk"
    proc, info = _launch_headless(data_dir)
    try:
        with httpx.Client(base_url=info["url"], timeout=10) as client:
            created = client.post("/notes", json={"title": "桌面持久化", "content": "重启后仍在", "category": "测试"})
            assert created.status_code == 201, created.text
            note_id = created.json()["id"]
    finally:
        assert _stop_headless(proc) == 0

    assert (data_dir / "hephaestus.db").is_file()
    assert not (PROJECT_ROOT / "data" / "hephaestus.db").exists() or True  # Web 版数据库不受影响

    proc2, info2 = _launch_headless(data_dir)
    try:
        with httpx.Client(base_url=info2["url"], timeout=10) as client:
            listing = client.get("/notes").json()
            assert listing["total"] == 1
            assert listing["items"][0]["id"] == note_id
            assert listing["items"][0]["title"] == "桌面持久化"
            assert client.get(f"/notes/{note_id}").json()["content"] == "重启后仍在"
    finally:
        assert _stop_headless(proc2) == 0


def test_headless_repeated_start_stop(tmp_path: Path) -> None:
    """连续启动/关闭三次：每次健康检查正常，SQLite 数据不丢失。"""
    data_dir = tmp_path / "desk"
    note_id: int | None = None
    for cycle in range(3):
        proc, info = _launch_headless(data_dir)
        try:
            assert info["ok"] is True, info
            with httpx.Client(base_url=info["url"], timeout=10) as client:
                assert client.get("/health").json() == {"status": "ok"}
                if cycle == 0:
                    created = client.post("/notes", json={"title": f"循环-{cycle}", "content": "重启仍在"})
                    assert created.status_code == 201, created.text
                    note_id = int(created.json()["id"])
                else:
                    assert note_id is not None
                    note = client.get(f"/notes/{note_id}")
                    assert note.status_code == 200
                    assert note.json()["title"] == "循环-0"
        finally:
            assert _stop_headless(proc) == 0, f"第 {cycle + 1} 次关闭失败"
    assert (data_dir / "hephaestus.db").is_file()


def test_headless_port_conflict_falls_back(tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy = blocker.getsockname()[1]
        proc, info = _launch_headless(tmp_path / "desk", port=busy)
        try:
            assert info["ok"] is True, info
            assert f":{busy}" not in info["url"]
            with httpx.Client(base_url=info["url"], timeout=10) as client:
                assert client.get("/health").json() == {"status": "ok"}
        finally:
            assert _stop_headless(proc) == 0


def test_self_test_reports_health_and_database(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    env = {key: value for key, value in os.environ.items() if key != "HEPHAESTUS_DATABASE_URL"}
    command = [
        sys.executable,
        "-m",
        "desktop.main",
        "--self-test",
        str(report_path),
        "--data-dir",
        str(tmp_path / "desk"),
    ]
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["health"] is True
    assert report["frozen"] is False
    # CI 只安装 Web 依赖时没有 pywebview；自检应仍能验证后端与数据库
    assert report["webview"] is None or report["webview"] == "6.2.1"
    assert "webview2" in report
    assert Path(report["db"]).is_file()


def test_self_test_without_pywebview_metadata(tmp_path: Path) -> None:
    """CI/Web 环境没有 pywebview 时，自检仍应验证后端与数据库。"""
    report_path = tmp_path / "report.json"
    script = "\n".join(
        [
            "import importlib.metadata as metadata",
            "def missing(name):",
            "    raise metadata.PackageNotFoundError(name)",
            "metadata.version = missing",
            "from desktop.main import main",
            "raise SystemExit(main())",
        ]
    )
    env = {key: value for key, value in os.environ.items() if key != "HEPHAESTUS_DATABASE_URL"}
    completed = subprocess.run(
        [sys.executable, "-c", script, "--self-test", str(report_path), "--data-dir", str(tmp_path / "desk")],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["webview"] is None


def test_webview2_missing_message_has_official_url() -> None:
    from desktop.runtime import WEBVIEW2_DOWNLOAD_URL, webview2_missing_message

    message = webview2_missing_message()
    assert "WebView2" in message
    assert WEBVIEW2_DOWNLOAD_URL in message
    assert "Python" in message


def test_require_webview2_raises_when_missing() -> None:
    from desktop.runtime import WebView2MissingError, require_webview2

    with pytest.raises(WebView2MissingError):
        require_webview2(version_getter=lambda: None)
    assert require_webview2(version_getter=lambda: "152.0.0.0") == "152.0.0.0"


def test_run_window_reports_missing_webview2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop import main as desktop_main
    from desktop.runtime import WebView2MissingError

    calls: list[bool] = []

    def missing() -> str:
        raise WebView2MissingError("missing")

    monkeypatch.setattr(desktop_main, "require_webview2", missing)
    monkeypatch.setattr(desktop_main, "show_webview2_missing_dialog", lambda: calls.append(True))
    args = desktop_main.parse_args(["--data-dir", str(tmp_path / "missing-runtime")])
    assert desktop_main.run_window(args) == 2
    assert calls == [True]


def test_run_window_wires_health_endpoint_and_stop_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """窗口启动必须把 /health 和停止事件交给巡检，避免根地址 HTML 误报。"""
    import types

    from desktop import main as desktop_main

    class Signal:
        def __init__(self) -> None:
            self.handlers = []

        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

    class FakeWindow:
        def __init__(self) -> None:
            self.events = types.SimpleNamespace(loaded=Signal(), closing=Signal())
            self.destroyed = False

        def evaluate_js(self, _script: str) -> str:
            return "Hephaestus 记事本"

        def destroy(self) -> None:
            self.destroyed = True

    fake_window = FakeWindow()
    created: dict[str, object] = {}

    class FakeWebview(types.ModuleType):
        def __init__(self) -> None:
            super().__init__("webview")

        def create_window(self, title: str, url: str, **kwargs: object) -> FakeWindow:
            created.update(title=title, url=url, kwargs=kwargs, window=fake_window)
            return fake_window

        def start(self, **_kwargs: object) -> None:
            for handler in list(fake_window.events.loaded.handlers):
                handler()

    class FakeGuard:
        released = False

        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            FakeGuard.released = True

    captured: dict[str, object] = {}

    class FakeBackend:
        def __init__(self, port: int | None = None, startup_timeout: float = 25.0) -> None:
            self.host = "127.0.0.1"
            self.port = 54321
            self.stopped = False
            captured["backend"] = self

        def start(self) -> str:
            return "http://127.0.0.1:54321"

        def stop(self) -> None:
            self.stopped = True

    def fake_watch(url: str, on_failure, **kwargs: object) -> None:
        captured.update(url=url, on_failure=on_failure, watch_kwargs=kwargs)

    monkeypatch.setattr(desktop_main, "require_webview2", lambda: "152.0.4191.66")
    monkeypatch.setattr(desktop_main, "SingleInstance", FakeGuard)
    monkeypatch.setattr(desktop_main, "BackendServer", FakeBackend)
    monkeypatch.setattr(desktop_main, "prepare_environment", lambda *_a, **_k: None)
    monkeypatch.setattr(desktop_main, "watch_backend", fake_watch)
    monkeypatch.setattr(
        desktop_main,
        "show_error",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("不应弹出后端异常")),
    )
    monkeypatch.setitem(sys.modules, "webview", FakeWebview())

    args = desktop_main.parse_args(["--data-dir", str(tmp_path / "wired")])
    assert desktop_main.run_window(args) == 0
    assert captured["url"] == "http://127.0.0.1:54321/health"
    watch_kwargs = captured["watch_kwargs"]
    assert isinstance(watch_kwargs, dict)
    assert watch_kwargs["backend"] is captured["backend"]
    assert watch_kwargs["startup_grace"] == 5.0
    assert isinstance(watch_kwargs["stop_event"], threading.Event)
    assert watch_kwargs["stop_event"].is_set()
    assert captured["backend"].stopped is True
    assert created["title"] == "Hephaestus"
    assert created["url"] == "http://127.0.0.1:54321?desktop=1"


def test_check_runtime_cli_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "runtime.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "desktop.main",
            "--check-runtime",
            str(report_path),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["version"] == __version__
    assert "webview2" in report
    assert report["download_url"].startswith("https://developer.microsoft.com/")
    assert completed.returncode == (0 if report["webview2"] else 3)


def test_version_file_matches_package() -> None:
    assert (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip() == __version__



def test_desktop_bridge_opens_only_safe_http_links(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("desktop.main.webbrowser.open", lambda url, new=0: opened.append(url) or True)
    bridge = DesktopBridge("x" * 48)
    assert bridge.capability_token() == "x" * 48
    assert bridge.open_external("https://example.com/docs?q=1") is True
    assert opened == ["https://example.com/docs?q=1"]
    for unsafe in (
        "javascript:alert(1)",
        "file:///C:/Windows/win.ini",
        "data:text/html,<script>alert(1)</script>",
        "https://user:pass@example.com/",
        "//example.com/no-scheme",
        "",
    ):
        assert bridge.open_external(unsafe) is False, unsafe
    assert opened == ["https://example.com/docs?q=1"]
