"""Temporary SQLite fixtures for the B2 real-UI verification.

Never points at the user's database. Every helper writes into the caller's
temporary directory only.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import FrontendState
from app.v2.db import create_v2_db, create_v2_engine
from app.v2.migrate import migrate_database, sqlite_url
from app.v2.models import ImportMetaV2


def payload() -> dict[str, Any]:
    now = int(time.time() * 1000)
    return {
        "notes": [
            {
                "id": "note-a",
                "title": "本地优先测试",
                "html": "<p>旧数据保留，不能被迁移失败清空。</p>",
                "tags": ["tag-work"],
                "fav": True,
                "trashed": False,
                "created": now - 86_400_000,
                "updated": now - 3_600_000,
                "category": "工作",
            },
            {
                "id": "note-b",
                "title": "旧快照笔记",
                "html": "<p>legacy snapshot</p>",
                "tags": ["tag-life"],
                "fav": False,
                "trashed": False,
                "created": now - 172_800_000,
                "updated": now - 7_200_000,
                "category": "生活",
            },
            {
                "id": "note-trash",
                "title": "回收站旧笔记",
                "html": "<p>trashed</p>",
                "tags": [],
                "fav": False,
                "trashed": True,
                "created": now - 259_200_000,
                "updated": now - 100_000_000,
                "category": "其他",
            },
        ],
        "tags": [
            {"id": "tag-work", "name": "工作", "color": "#7c83e6"},
            {"id": "tag-life", "name": "生活", "color": "#f2c230"},
        ],
        "ui": {"theme": "dark", "layout": "list", "sort": "updated"},
    }


def build_legacy(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    engine = create_engine(sqlite_url(target))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(FrontendState(id=1, payload=payload()))
            session.commit()
    finally:
        engine.dispose()
    return target


def build_v2(path: str | Path) -> Path:
    target = Path(path)
    source = target.with_name(target.stem + "-source.db")
    if target.exists():
        target.unlink()
    build_legacy(source)
    migrate_database(source, target, backup_dir=target.parent / "backups")
    return target


def build_pending(path: str | Path) -> Path:
    target = build_legacy(path)
    engine = create_v2_engine(sqlite_url(target))
    create_v2_db(engine)
    engine.dispose()
    return target


def build_failed(path: str | Path) -> Path:
    target = build_v2(path)
    engine = create_v2_engine(sqlite_url(target))
    try:
        with Session(engine) as session:
            session.merge(ImportMetaV2(key="migration_status", value="failed"))
            session.commit()
    finally:
        engine.dispose()
    return target
