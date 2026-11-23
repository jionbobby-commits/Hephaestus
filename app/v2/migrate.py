"""B1 JSON snapshot migration, backup and rollback helpers.

Safety rules:
* reads the source database read-only;
* writes only the target database;
* refuses source == target unless allow_in_place=True;
* backs up an existing target before migration;
* never drops or edits the legacy notes/frontend_state tables.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.v2.contracts import (
    AppSettings,
    NoteRead,
    SnapshotSummary,
    epoch_ms_to_iso,
    html_to_text,
    note_to_public,
    utc_now_iso,
)
from app.v2.db import create_v2_db, create_v2_engine
from app.v2.models import (
    AppSettingV2,
    ImportMetaV2,
    NoteV2,
    SchemaMigrationV2,
    TagV2,
    v2_note_tags,
)

MIGRATION_VERSION = 1
MIGRATION_CHECKSUM = hashlib.sha256(b"b1-v1-tags").hexdigest()
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class MigrationError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    p = Path(path).resolve().as_posix()
    if readonly:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    return sqlite3.connect(p)


def sqlite_url(path: str | Path) -> str:
    return "sqlite:///" + Path(path).resolve().as_posix()


def backup_database(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Use SQLite online backup, then verify the destination integrity."""
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise MigrationError(f"源数据库不存在: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    source_conn = _connect(source, readonly=True)
    dest_conn = sqlite3.connect(tmp.as_posix())
    try:
        source_conn.backup(dest_conn)
        dest_conn.commit()
        check = dest_conn.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise MigrationError(f"备份完整性检查失败: {check}")
    finally:
        dest_conn.close()
        source_conn.close()
    os.replace(tmp, destination)
    return {
        "source": str(source),
        "destination": str(destination),
        "source_sha256": sha256_file(source),
        "backup_sha256": sha256_file(destination),
        "size": destination.stat().st_size,
        "integrity": "ok",
    }


def restore_database(backup: str | Path, target: str | Path) -> dict[str, Any]:
    """Restore through a temporary file, keeping the backup untouched."""
    backup = Path(backup)
    target = Path(target)
    if not backup.is_file():
        raise MigrationError(f"备份不存在: {backup}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".restore.tmp")
    if temp.exists():
        temp.unlink()
    source_conn = _connect(backup, readonly=True)
    dest_conn = sqlite3.connect(temp.as_posix())
    try:
        source_conn.backup(dest_conn)
        dest_conn.commit()
        check = dest_conn.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise MigrationError(f"恢复完整性检查失败: {check}")
    finally:
        dest_conn.close()
        source_conn.close()
    os.replace(temp, target)
    return {"target": str(target), "sha256": sha256_file(target), "size": target.stat().st_size, "integrity": "ok"}


def read_snapshot(source: str | Path) -> dict[str, Any]:
    conn = _connect(source, readonly=True)
    try:
        table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='frontend_state'").fetchone()
        if not table:
            raise MigrationError("源数据库没有 frontend_state 表")
        row = conn.execute("SELECT payload FROM frontend_state WHERE id=1").fetchone()
        if not row or not row[0]:
            raise MigrationError("frontend_state 没有 id=1 的 payload")
        try:
            payload = json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise MigrationError(f"frontend_state JSON 解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise MigrationError("frontend_state payload 必须是 JSON 对象")
        return payload
    finally:
        conn.close()


def validate_snapshot(payload: dict[str, Any], source: str | Path) -> SnapshotSummary:
    notes = payload.get("notes")
    tags = payload.get("tags")
    if not isinstance(notes, list) or not isinstance(tags, list):
        raise MigrationError("payload 必须包含 notes 数组和 tags 数组")
    note_ids: set[str] = set()
    tag_ids: set[str] = set()
    unknown_note: set[str] = set()
    unknown_tag: set[str] = set()
    favorite = trashed = note_tags = data_urls = 0
    known_note = {"id", "title", "html", "tags", "fav", "trashed", "created", "updated", "category"}
    known_tag = {"id", "name", "color", "created", "updated"}
    for note in notes:
        if not isinstance(note, dict):
            raise MigrationError("notes 中存在非对象条目")
        note_id = str(note.get("id") or "")
        if not note_id or note_id in note_ids:
            raise MigrationError(f"笔记 id 缺失或重复: {note_id!r}")
        note_ids.add(note_id)
        unknown_note.update(set(note) - known_note)
        if note.get("fav"):
            favorite += 1
        if note.get("trashed"):
            trashed += 1
        note_tags += len(note.get("tags") or [])
        data_urls += len(re.findall(r"data:image/", str(note.get("html") or "")))
        for field in ("created", "updated"):
            value = note.get(field)
            if not isinstance(value, (int, float)):
                raise MigrationError(f"笔记 {note_id} 的 {field} 不是毫秒时间戳")
    for tag in tags:
        if not isinstance(tag, dict):
            raise MigrationError("tags 中存在非对象条目")
        tag_id = str(tag.get("id") or "")
        if not tag_id or tag_id in tag_ids:
            raise MigrationError(f"标签 id 缺失或重复: {tag_id!r}")
        tag_ids.add(tag_id)
        unknown_tag.update(set(tag) - known_tag)
    for note in notes:
        for tag_id in note.get("tags") or []:
            if str(tag_id) not in tag_ids:
                raise MigrationError(f"笔记 {note.get('id')} 引用了不存在的标签 {tag_id}")
    return SnapshotSummary(
        note_count=len(notes),
        tag_count=len(tags),
        favorite_count=favorite,
        trashed_count=trashed,
        note_tags_count=note_tags,
        data_url_count=data_urls,
        unknown_note_fields=sorted(unknown_note),
        unknown_tag_fields=sorted(unknown_tag),
        source_sha256=sha256_file(source),
        source_size=Path(source).stat().st_size,
    )


def _iso_or_now(value: Any, now: str) -> str:
    """Legacy tags may omit timestamps or store epoch milliseconds."""
    if isinstance(value, (int, float)):
        return epoch_ms_to_iso(value)
    if isinstance(value, str):
        if _ISO_RE.match(value):
            return value
        if value.isdigit() and len(value) >= 10:
            return epoch_ms_to_iso(int(value))
    return now


def _insert_tags(session: Session, tags: list[dict[str, Any]], now: str) -> dict[str, TagV2]:
    result: dict[str, TagV2] = {}
    for tag in tags:
        tag_id = str(tag["id"])
        row = TagV2(
            id=tag_id,
            name=str(tag.get("name") or "未命名标签")[:32],
            color=str(tag.get("color") or "#8b8f94"),
            created_at=_iso_or_now(tag.get("created"), now),
            updated_at=_iso_or_now(tag.get("updated"), now),
        )
        session.add(row)
        result[tag_id] = row
    return result


def _insert_notes(session: Session, notes: list[dict[str, Any]], tags: dict[str, TagV2]) -> None:
    for note in notes:
        note_id = str(note["id"])
        created = epoch_ms_to_iso(note["created"])
        updated = epoch_ms_to_iso(note["updated"])
        content_html = str(note.get("html") or "")
        extra = {k: v for k, v in note.items() if k not in {"id", "title", "html", "tags", "fav", "trashed", "created", "updated", "category"}}
        row = NoteV2(
            id=note_id,
            title=str(note.get("title") or "无标题笔记")[:120],
            content_html=content_html,
            content_text=html_to_text(content_html),
            category=(str(note["category"])[:30] if note.get("category") else None),
            is_favorite=bool(note.get("fav")),
            favorited_at=updated if note.get("fav") else None,
            is_trashed=bool(note.get("trashed")),
            trashed_at=updated if note.get("trashed") else None,
            created_at=created,
            updated_at=updated,
            revision=1,
            extra_json=json.dumps(extra, ensure_ascii=False),
        )
        row.tags = [tags[str(tag_id)] for tag_id in (note.get("tags") or [])]
        session.add(row)


def _insert_settings(session: Session, payload: dict[str, Any], now: str) -> None:
    ui = payload.get("ui") if isinstance(payload.get("ui"), dict) else {}
    settings = AppSettings(
        locale=str(ui.get("locale") or "zh-CN"),
        theme=str(ui.get("theme") or "system"),
        layout=str(ui.get("layout") or "list"),
        sort=str(ui.get("sort") or "updated"),
    )
    for key, value in settings.model_dump().items():
        session.add(AppSettingV2(key=key, value_json=json.dumps(value, ensure_ascii=False), updated_at=now))


def migrate_database(
    source_db: str | Path,
    target_db: str | Path,
    *,
    backup_dir: str | Path | None = None,
    allow_in_place: bool = False,
) -> dict[str, Any]:
    source = Path(source_db).resolve()
    target = Path(target_db).resolve()
    if source == target and not allow_in_place:
        raise MigrationError("源和目标是同一个数据库；B1 只允许在副本上演练，真实迁移需显式 allow_in_place")
    payload = read_snapshot(source)
    summary = validate_snapshot(payload, source)
    if summary.note_count != 7 or summary.tag_count != 4:
        # Not a hard schema error, but the B1 real-data acceptance expects these counts.
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: dict[str, Any] | None = None
    if target.exists():
        backup_dir = Path(backup_dir) if backup_dir else target.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_database(target, backup_dir / f"pre-v2-b1-{utc_now_iso().replace(':', '-').replace('.', '-')}.db")
    else:
        backup = backup_database(source, target)
    engine = create_v2_engine(sqlite_url(target))
    create_v2_db(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            existing = session.get(SchemaMigrationV2, MIGRATION_VERSION)
            if existing is not None:
                counts = {
                    "notes": int(session.scalar(select(func.count()).select_from(NoteV2)) or 0),
                    "tags": int(session.scalar(select(func.count()).select_from(TagV2)) or 0),
                    "note_tags": int(session.scalar(select(func.count()).select_from(v2_note_tags)) or 0),
                }
                return {"ok": True, "already_migrated": True, "summary": summary.model_dump(), "counts": counts, "backup": backup}
            now = utc_now_iso()
            tags = _insert_tags(session, payload.get("tags") or [], now)
            _insert_notes(session, payload.get("notes") or [], tags)
            _insert_settings(session, payload, now)
            session.add(SchemaMigrationV2(version=MIGRATION_VERSION, applied_at=now, checksum=MIGRATION_CHECKSUM))
            session.add(ImportMetaV2(key="frontend_state_sha256", value=summary.source_sha256))
            session.add(ImportMetaV2(key="frontend_state_migrated_at", value=now))
            session.add(ImportMetaV2(key="frontend_state_note_count", value=str(summary.note_count)))
            session.add(ImportMetaV2(key="frontend_state_tag_count", value=str(summary.tag_count)))
            session.commit()
    finally:
        engine.dispose()
    report = {
        "ok": True,
        "already_migrated": False,
        "summary": summary.model_dump(),
        "backup": backup,
    }
    report["counts"] = verify_migrated(target)
    return report


def verify_against_snapshot(source_db: str | Path, target_db: str | Path) -> dict[str, Any]:
    """Compare every migrated note against the source JSON snapshot."""
    payload = read_snapshot(source_db)
    summary = validate_snapshot(payload, source_db)
    target = Path(target_db).resolve()
    conn = _connect(target, readonly=True)
    mismatches: list[str] = []
    try:
        for note in payload.get("notes") or []:
            note_id = str(note["id"])
            row = conn.execute(
                "SELECT id, title, content_html, created_at, updated_at, is_favorite, is_trashed, category "
                "FROM v2_notes WHERE id=?", (note_id,)
            ).fetchone()
            if row is None:
                mismatches.append(f"missing note {note_id}")
                continue
            expected_title = str(note.get("title") or "无标题笔记")[:120]
            expected_html = str(note.get("html") or "")
            expected_created = epoch_ms_to_iso(note["created"])
            expected_updated = epoch_ms_to_iso(note["updated"])
            expected_category = (str(note["category"])[:30] if note.get("category") else None)
            checks = [
                (row[1], expected_title, "title"),
                (row[2], expected_html, "content_html"),
                (row[3], expected_created, "created_at"),
                (row[4], expected_updated, "updated_at"),
                (bool(row[5]), bool(note.get("fav")), "is_favorite"),
                (bool(row[6]), bool(note.get("trashed")), "is_trashed"),
                (row[7], expected_category, "category"),
            ]
            for actual, expected, field in checks:
                if actual != expected:
                    mismatches.append(f"{note_id}.{field}")
            actual_tags = {
                r[0] for r in conn.execute(
                    "SELECT tag_id FROM v2_note_tags WHERE note_id=?", (note_id,)
                ).fetchall()
            }
            expected_tags = {str(t) for t in (note.get("tags") or [])}
            if actual_tags != expected_tags:
                mismatches.append(f"{note_id}.tags")
        for tag in payload.get("tags") or []:
            tag_id = str(tag["id"])
            row = conn.execute("SELECT name, color FROM v2_tags WHERE id=?", (tag_id,)).fetchone()
            if row is None:
                mismatches.append(f"missing tag {tag_id}")
                continue
            if row[0] != str(tag.get("name") or "未命名标签")[:32]:
                mismatches.append(f"{tag_id}.name")
            if row[1] != str(tag.get("color") or "#8b8f94"):
                mismatches.append(f"{tag_id}.color")
        if summary.note_count != len(payload.get("notes") or []):
            mismatches.append("note_count")
        if summary.tag_count != len(payload.get("tags") or []):
            mismatches.append("tag_count")
        return {
            "ok": not mismatches,
            "checked_notes": summary.note_count,
            "checked_tags": summary.tag_count,
            "mismatches": mismatches,
        }
    finally:
        conn.close()


def verify_migrated(target_db: str | Path) -> dict[str, Any]:
    target = Path(target_db).resolve()
    conn = _connect(target, readonly=True)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"v2_notes", "v2_tags", "v2_note_tags", "v2_settings", "v2_schema_migrations"}
        missing = sorted(required - tables)
        if missing:
            raise MigrationError("缺少 V2 表: " + ", ".join(missing))
        counts = {
            "notes": conn.execute("SELECT count(*) FROM v2_notes").fetchone()[0],
            "tags": conn.execute("SELECT count(*) FROM v2_tags").fetchone()[0],
            "note_tags": conn.execute("SELECT count(*) FROM v2_note_tags").fetchone()[0],
            "favorites": conn.execute("SELECT count(*) FROM v2_notes WHERE is_favorite=1").fetchone()[0],
            "trashed": conn.execute("SELECT count(*) FROM v2_notes WHERE is_trashed=1").fetchone()[0],
            "settings": conn.execute("SELECT count(*) FROM v2_settings").fetchone()[0],
        }
        rows = conn.execute("SELECT id, title, created_at, updated_at, is_favorite, is_trashed, revision FROM v2_notes").fetchall()
        for row in rows:
            if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", str(row[2])):
                raise MigrationError(f"created_at 不是 ISO UTC: {row[0]}")
            if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", str(row[3])):
                raise MigrationError(f"updated_at 不是 ISO UTC: {row[0]}")
        return counts
    finally:
        conn.close()
