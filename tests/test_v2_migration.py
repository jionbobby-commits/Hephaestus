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
    assert verified == {"ok": True, "checked_notes": 2, "checked_tags": 2, "mismatches": []}
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
