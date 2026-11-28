"""Real-browser verification for the V2 frontend DataPort (B2).

These tests drive the actual Hephaestus UI in a WebView2 window against
temporary SQLite databases. They are skipped when pywebview or the WebView2
runtime is unavailable, because there is no browser fallback in CI.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "ui_verify.py"
RECOVERY_HARNESS = ROOT / "tests" / "frontend" / "recovery_verify.py"
REAL_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "Hephaestus" / "hephaestus.db"


def _webview2_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from desktop.runtime import read_webview2_version

        return bool(read_webview2_version())
    except Exception:
        return False


HAS_WEBVIEW = importlib.util.find_spec("webview") is not None
pytestmark = pytest.mark.skipif(
    not (HAS_WEBVIEW and _webview2_available()),
    reason="需要 pywebview 与 WebView2 Runtime 才能执行真实界面验证",
)


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(mode: str, phase: str, root: Path) -> dict:
    before = _digest(REAL_DB)
    command = [
        sys.executable,
        str(HARNESS),
        "--mode",
        mode,
        "--phase",
        phase,
        "--root",
        str(root),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-4000:]
    result = json.loads(completed.stdout)
    assert result.get("error") is None, result.get("error")
    assert _digest(REAL_DB) == before, "测试不得修改用户的真实数据库"
    return result


def _run_recovery(root: Path) -> dict:
    before = _digest(REAL_DB)
    completed = subprocess.run(
        [sys.executable, str(RECOVERY_HARNESS), "--root", str(root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-4000:]
    result = json.loads(completed.stdout)
    assert result.get("error") is None, result.get("error")
    assert _digest(REAL_DB) == before, "测试不得修改用户的真实数据库"
    return result


def _snap(result: dict, name: str) -> dict:
    value = result["ui"].get(name)
    assert value is not None, f"缺少界面快照 {name}"
    return value


def _titles(snapshot: dict) -> list[str]:
    return [note.get("title") or "" for note in snapshot["notes"]]


def _assert_unique_ids(snapshot: dict) -> None:
    ids = [note["id"] for note in snapshot["notes"]]
    assert len(ids) == len(set(ids)), f"界面出现重复笔记: {ids}"


@pytest.fixture()
def ui_root():
    directory = Path(tempfile.mkdtemp(prefix="heph-b2-pytest-"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_legacy_mode_crud_refresh_and_reopen(ui_root: Path) -> None:
    result = _run("legacy", "main", ui_root)
    assert _snap(result, "initial")["mode"] == "legacy"
    assert len(_snap(result, "initial")["notes"]) == 3
    assert _snap(result, "after_restore")["label"] == "已保存"
    assert result["refresh_found"] is True
    assert _snap(result, "after_refresh")["label"] == "已保存"
    assert result["http"]["v2_status"][1]["data_mode"] == "legacy"
    v2_payload = result["http"]["v2_notes"][1]
    assert not v2_payload.get("items"), f"未迁移库不得写入 V2 数据: {v2_payload}"

    reopened = _run("legacy", "reopen", ui_root)
    assert reopened["reopen"]["found"] is True
    assert _snap(reopened, "initial")["mode"] == "legacy"
    assert len(_snap(reopened, "initial")["notes"]) == 4


def test_v2_crud_conflict_failure_retry_refresh_and_reopen(ui_root: Path) -> None:
    result = _run("v2", "main", ui_root)
    assert _snap(result, "initial")["mode"] == "v2_ready"
    assert len(_snap(result, "initial")["notes"]) == 3
    assert len(_snap(result, "after_create")["notes"]) == 4
    assert len(_snap(result, "after_duplicate_submit")["notes"]) == 4
    _assert_unique_ids(_snap(result, "after_duplicate_submit"))
    assert _snap(result, "after_edit")["label"] == "已保存"
    assert _snap(result, "after_favorite")["label"] == "已保存"
    assert _snap(result, "after_tag")["label"] == "已保存"
    assert _snap(result, "after_restore")["label"] == "已保存"

    assert result["conflict"]["modal_seen"] is True
    assert "检测到编辑冲突" in (result["conflict"]["modal_text"] or "")
    assert result["conflict"].get("choose_mine") is True

    failure = result["save_failure"]
    assert failure["started"] is True
    assert failure["failure_seen"] is True
    assert "无法连接本地服务" in failure["error"]
    assert failure["label"] == "保存失败，内容已保存在本地"
    assert failure["local_title"] is True

    assert _snap(result, "after_retry")["label"] == "已保存"
    assert len(_snap(result, "after_retry")["notes"]) == 4
    _assert_unique_ids(_snap(result, "after_retry"))
    assert "B2 断网本地保留" in _titles(_snap(result, "after_retry"))

    assert result["refresh_found"] is True
    refreshed = _snap(result, "after_refresh")
    assert refreshed["label"] == "已保存", refreshed["conflict"]
    assert len(refreshed["notes"]) == 4
    _assert_unique_ids(refreshed)
    assert "B2 断网本地保留" in _titles(refreshed)
    assert result["http"]["v2_status"][1]["data_mode"] == "v2_ready"

    reopened = _run("v2", "reopen", ui_root)
    assert reopened["reopen"]["found"] is True
    assert _snap(reopened, "initial")["label"] == "已保存"
    assert len(_snap(reopened, "initial")["notes"]) == 4
    _assert_unique_ids(_snap(reopened, "initial"))


def test_migration_pending_uses_legacy_only(ui_root: Path) -> None:
    result = _run("pending", "main", ui_root)
    assert _snap(result, "initial")["mode"] == "migration_pending"
    assert _snap(result, "initial")["modeLabel"] == "迁移待定 · 旧版兼容"
    assert len(_snap(result, "after_restore")["notes"]) == 4
    assert result["refresh_found"] is True
    assert _snap(result, "after_refresh")["label"] == "已保存"
    assert result["http"]["v2_notes"][1]["total"] == 0, "迁移待定库不得写入 V2 数据"
    assert result["http"]["legacy_note_present"] is True


def test_migration_failed_falls_back_to_legacy(ui_root: Path) -> None:
    result = _run("failed", "main", ui_root)
    assert _snap(result, "initial")["mode"] == "migration_failed"
    assert _snap(result, "initial")["modeLabel"] == "迁移失败 · 旧版兼容"
    assert len(_snap(result, "after_restore")["notes"]) == 4
    assert result["refresh_found"] is True
    assert _snap(result, "after_refresh")["label"] == "已保存"
    v2_payload = result["http"]["v2_notes"][1]
    assert all("B2 legacy 已编辑" not in (note.get("title") or "") for note in v2_payload.get("items", [])), "迁移失败后只能写回旧快照"
    assert result["http"]["legacy_note_present"] is True


def test_initialization_failure_edit_survives_recovery(ui_root: Path) -> None:
    result = _run_recovery(ui_root)
    assert result["initial_mode"] == "unknown"
    assert result["edited_note_local"] is True
    assert result["journal_written"]["reason"] == "init_failed"
    assert result["journal_written"]["notes"] == 1
    assert result["server_count_before_recovery"] == 2, "状态失败期间不得写服务器"
    assert result["recovered_mode"] == "v2_ready"
    assert result["note_present_after_reload"] is True
    assert result["server_title_after_recovery"] is True
    assert result["server_count_after_recovery"] == 3
    assert result["journal_after_sync"] is None
    assert result["note_present_after_second_reload"] is True
    assert result["final_label"] == "已保存"
