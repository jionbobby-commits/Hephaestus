"""Read-only detection of the active data mode (B2).

This module never creates tables, never migrates and never writes. It answers
one question for the frontend: can /api/v2 be used safely, or must the legacy
/api/state path remain authoritative?

States:
* legacy             - no V2 schema; /api/state is authoritative.
* migration_pending  - V2 tables exist but migration is incomplete.
* v2_ready           - V2 schema and migration marker are present.
* migration_failed   - an explicit failure marker exists; use legacy fallback.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.v2.contracts import utc_now_iso

REQUIRED_V2_TABLES = {
    "v2_notes",
    "v2_tags",
    "v2_note_tags",
    "v2_attachments",
    "v2_note_attachments",
    "v2_settings",
    "v2_ai_providers",
    "v2_schema_migrations",
    "v2_import_meta",
}
MIGRATION_VERSION = 1


def _legacy_status(session: Session, tables: set[str]) -> dict[str, Any]:
    status: dict[str, Any] = {
        "available": "frontend_state" in tables,
        "initialized": False,
        "note_count": 0,
        "tag_count": 0,
        "error": None,
    }
    if not status["available"]:
        return status
    try:
        row = session.execute(
            text("SELECT payload FROM frontend_state WHERE id=1")
        ).first()
        if not row or not row[0]:
            return status
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            raise ValueError("frontend_state payload 不是对象")
        notes = payload.get("notes")
        tags = payload.get("tags")
        if not isinstance(notes, list) or not isinstance(tags, list):
            raise ValueError("frontend_state 缺少 notes/tags 数组")
        status.update(initialized=True, note_count=len(notes), tag_count=len(tags))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        status["error"] = str(exc)
    return status


def _v2_status(session: Session, tables: set[str]) -> dict[str, Any]:
    status: dict[str, Any] = {
        "available": any(name.startswith("v2_") for name in tables),
        "schema_ready": REQUIRED_V2_TABLES.issubset(tables),
        "migration_version": None,
        "migrated_at": None,
        "note_count": None,
        "tag_count": None,
        "explicit_status": None,
        "error": None,
    }
    if not status["schema_ready"]:
        return status
    try:
        marker = session.execute(
            text("SELECT version, applied_at FROM v2_schema_migrations WHERE version=:version"),
            {"version": MIGRATION_VERSION},
        ).first()
        if marker:
            status["migration_version"] = int(marker[0])
            status["migrated_at"] = str(marker[1])
        if "v2_import_meta" in tables:
            rows = session.execute(
                text("SELECT key, value FROM v2_import_meta")
            ).all()
            meta = {str(row[0]): str(row[1]) for row in rows}
            status["explicit_status"] = meta.get("migration_status")
            status["migrated_at"] = status["migrated_at"] or meta.get("frontend_state_migrated_at")
        if "v2_notes" in tables:
            status["note_count"] = int(session.execute(text("SELECT count(*) FROM v2_notes")).scalar() or 0)
        if "v2_tags" in tables:
            status["tag_count"] = int(session.execute(text("SELECT count(*) FROM v2_tags")).scalar() or 0)
    except Exception as exc:  # diagnose, never break the legacy fallback
        status["error"] = str(exc)
    return status


def detect_data_mode(session: Session) -> dict[str, Any]:
    bind = session.get_bind()
    tables = set(inspect(bind).get_table_names())
    legacy = _legacy_status(session, tables)
    v2 = _v2_status(session, tables)
    if v2["explicit_status"] == "failed":
        mode, reason = "migration_failed", "迁移失败标记存在，使用旧 /api/state"
    elif v2["explicit_status"] == "pending":
        mode, reason = "migration_pending", "迁移进行中，使用旧 /api/state"
    elif not v2["available"]:
        mode, reason = "legacy", "未发现 V2 表，使用旧 /api/state"
    elif not v2["schema_ready"]:
        mode, reason = "migration_pending", "V2 表不完整，使用旧 /api/state"
    elif v2["migration_version"] is None:
        mode, reason = "migration_pending", "缺少 V2 迁移标记，使用旧 /api/state"
    elif v2["error"]:
        mode, reason = "migration_failed", "V2 状态读取失败，使用旧 /api/state"
    else:
        mode, reason = "v2_ready", "V2 数据已就绪"
    return {
        "data_mode": mode,
        "contract_version": "2.0",
        "schema_version": 1,
        "legacy": legacy,
        "v2": v2,
        "fallback": mode != "v2_ready",
        "reason": reason,
        "checked_at": utc_now_iso(),
    }
