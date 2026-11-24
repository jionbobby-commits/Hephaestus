from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.v2.migrate import (
    MigrationError,
    backup_database,
    migrate_database,
    read_snapshot,
    restore_database,
    sha256_file,
    verify_against_snapshot,
    verify_migrated,
)


def _payload(tags=None):
    return {
        "notes": [
            {"id": "n1", "title": "第一条", "html": "<p>正文 <b>内容</b></p>", "tags": ["t1"], "fav": True, "trashed": False, "created": 1700000000000, "updated": 1700000001000},
            {"id": "n2", "title": "第二条", "html": "", "tags": [], "fav": False, "trashed": True, "created": 1700000002000, "updated": 1700000003000},
        ],
        "tags": tags if tags is not None else [
            {"id": "t1", "name": "设计", "color": "#48be80"},
            {"id": "t2", "name": "阅读", "color": "#f5a524"},
        ],
        "ui": {"theme": "dark", "layout": "list", "sort": "updated"},
    }


def _legacy_db(path: Path, payload: dict) -> Path:
    conn = sqlite3.connect(path.as_posix())
    conn.execute("CREATE TABLE frontend_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    conn.execute("INSERT INTO frontend_state (id, payload) VALUES (1, ?)", (json.dumps(payload, ensure_ascii=False),))
    conn.commit()
    conn.close()
    return path


def test_migrate_copy_verify_and_idempotent(tmp_path: Path):
    source = _legacy_db(tmp_path / "legacy.db", _payload())
    target = tmp_path / "target.db"
    backup_database(source, target)
    original_hash = sha256_file(source)

    report = migrate_database(source, target)
    assert report["ok"] is True and report["already_migrated"] is False
    assert report["summary"]["note_count"] == 2
    assert report["summary"]["tag_count"] == 2
    assert report["summary"]["favorite_count"] == 1
    assert report["summary"]["trashed_count"] == 1
    assert report["counts"] == {"notes": 2, "tags": 2, "note_tags": 1, "favorites": 1, "trashed": 1, "settings": 8}

    verified = verify_against_snapshot(source, target)
    assert verified == {
        "ok": True,
        "checked_notes": 2,
        "checked_tags": 2,
        "checked_note_tags": 1,
        "checked_settings": 8,
        "frontend_state_preserved": True,
        "legacy_notes_count_preserved": True,
        "mismatches": [],
    }
    assert sha256_file(source) == original_hash

    again = migrate_database(source, target)
    assert again["already_migrated"] is True
    assert again["counts"]["notes"] == 2 and again["counts"]["tags"] == 2


def test_backup_and_restore_preserve_legacy_snapshot(tmp_path: Path):
    source = _legacy_db(tmp_path / "legacy.db", _payload())
    backup = tmp_path / "backup.db"
    backup_database(source, backup)

    target = tmp_path / "target.db"
    backup_database(source, target)
    migrate_database(source, target)
    assert verify_migrated(target)["notes"] == 2

    restored = tmp_path / "restored.db"
    restore_database(backup, restored)
    assert read_snapshot(restored)["notes"][0]["id"] == "n1"
    conn = sqlite3.connect(restored.as_posix())
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "frontend_state" in tables
    assert "v2_notes" not in tables


def test_refuses_in_place_without_explicit_flag(tmp_path: Path):
    source = _legacy_db(tmp_path / "legacy.db", _payload())
    with pytest.raises(MigrationError, match="同一个数据库"):
        migrate_database(source, source)


def test_invalid_snapshot_does_not_touch_target(tmp_path: Path):
    bad = _payload(tags=[{"id": "t1", "name": "设计", "color": "#48be80"}])
    bad["notes"][0]["tags"] = ["t1", "t2"]
    source = _legacy_db(tmp_path / "legacy.db", bad)
    target = tmp_path / "target.db"
    backup_database(source, target)
    before = sha256_file(target)
    with pytest.raises(MigrationError, match="不存在的标签"):
        migrate_database(source, target)
    assert sha256_file(target) == before
    assert read_snapshot(target)["notes"][0]["id"] == "n1"


def test_unknown_note_fields_and_ui_extras_are_preserved(tmp_path: Path):
    payload = _payload()
    payload["notes"][0]["future_note_field"] = {"schema": 9, "value": "保留"}
    payload["ui"]["density"] = "compact"
    source = _legacy_db(tmp_path / "legacy.db", payload)
    target = tmp_path / "target.db"
    backup_database(source, target)
    migrate_database(source, target)

    verified = verify_against_snapshot(source, target)
    assert verified["ok"] is True
    assert verified["mismatches"] == []
    conn = sqlite3.connect(target.as_posix())
    try:
        extra = json.loads(conn.execute("SELECT extra_json FROM v2_notes WHERE id='n1'").fetchone()[0])
        density = conn.execute("SELECT value_json FROM v2_settings WHERE key='density'").fetchone()[0]
    finally:
        conn.close()
    assert extra == {"future_note_field": {"schema": 9, "value": "保留"}}
    assert json.loads(density) == "compact"

    conn = sqlite3.connect(target.as_posix())
    try:
        conn.execute("UPDATE v2_notes SET extra_json='{}' WHERE id='n1'")
        conn.commit()
    finally:
        conn.close()
    tampered = verify_against_snapshot(source, target)
    assert tampered["ok"] is False
    assert "n1.extra_json" in tampered["mismatches"]


def test_unknown_tag_fields_fail_closed(tmp_path: Path):
    payload = _payload()
    payload["tags"][0]["future_tag_field"] = "must-not-be-dropped"
    source = _legacy_db(tmp_path / "legacy.db", payload)
    target = tmp_path / "target.db"
    backup_database(source, target)
    before = sha256_file(target)
    with pytest.raises(MigrationError, match="未知字段"):
        migrate_database(source, target)
    assert sha256_file(target) == before
    assert read_snapshot(target)["tags"][0]["name"] == "设计"


def test_invalid_ui_value_rolls_back_and_backup_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = _payload()
    payload["ui"]["theme"] = "neon"
    source = _legacy_db(tmp_path / "legacy.db", payload)
    backup = tmp_path / "backup.db"
    backup_database(source, backup)
    target = tmp_path / "target.db"
    restore_database(backup, target)
    with pytest.raises(Exception):
        migrate_database(source, target)

    conn = sqlite3.connect(target.as_posix())
    try:
        notes = conn.execute("SELECT count(*) FROM v2_notes").fetchone()[0]
        markers = conn.execute("SELECT count(*) FROM v2_schema_migrations").fetchone()[0]
    finally:
        conn.close()
    assert notes == 0 and markers == 0

    restored = tmp_path / "restored_after_failure.db"
    restore_database(backup, restored)
    assert sha256_file(restored) == sha256_file(backup)
    assert read_snapshot(restored)["ui"]["theme"] == "neon"


def test_mid_transaction_failure_leaves_no_rows_and_restore_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = _payload()
    source = _legacy_db(tmp_path / "legacy.db", payload)
    target = tmp_path / "target.db"
    backup_database(source, target)
    backup = tmp_path / "pre_migration.db"
    backup_database(source, backup)
    source_hash = sha256_file(source)

    def boom(session, payload, now):
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr("app.v2.migrate._insert_settings", boom)
    with pytest.raises(RuntimeError, match="injected"):
        migrate_database(source, target)
    assert sha256_file(source) == source_hash

    conn = sqlite3.connect(target.as_posix())
    try:
        assert conn.execute("SELECT count(*) FROM v2_notes").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM v2_tags").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM v2_schema_migrations").fetchone()[0] == 0
    finally:
        conn.close()

    restore_database(backup, target)
    assert sha256_file(target) == sha256_file(backup)
    assert read_snapshot(target) == payload
    conn = sqlite3.connect(target.as_posix())
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "v2_notes" not in tables
