"""V2 engine/session setup.

Deliberately does not create V2 tables at application import/startup. The
B1 migration drill and the future explicit migration command own table
creation, so opening the current app cannot alter the real user database.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from app.database import DATABASE_URL
from app.v2.models import V2Base

_engine: Engine | None = None


def configure_sqlite(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def create_v2_engine(url: str | None = None) -> Engine:
    engine = create_engine(
        url or DATABASE_URL,
        connect_args={"check_same_thread": False} if (url or DATABASE_URL).startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    configure_sqlite(engine)
    return engine


def get_v2_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_v2_engine()
    return _engine


def create_v2_db(engine: Engine | None = None) -> None:
    V2Base.metadata.create_all(bind=engine or get_v2_engine())


def get_v2_session() -> Iterator[Session]:
    with Session(get_v2_engine(), expire_on_commit=False) as session:
        yield session
