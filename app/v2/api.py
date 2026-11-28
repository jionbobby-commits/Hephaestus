"""Versioned /api/v2 read/write surface for the B1 data layer.

The legacy /api/state and /notes routers stay registered and unchanged.
V2 tables are not created at startup; a missing schema surfaces as 503 until
the explicit migration command has been run.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.v2.ai.api import router as ai_router
from app.v2.contracts import (
    AppSettings,
    AppSettingsPatch,
    AttachmentRead,
    FavoriteRequest,
    NoteCreate,
    NotePage,
    NotePatch,
    NoteRead,
    TagCreate,
    TagRead,
    TagUpdate,
    utc_now_iso,
)
from app.v2.dataport import ConflictError, InvalidReferenceError, NotFoundError, SqlAlchemyDataPort
from app.v2.db import get_v2_session
from app.v2.status import detect_data_mode

router = APIRouter(prefix="/api/v2", tags=["V2 数据"])


def get_port(session: Session = Depends(get_v2_session)) -> SqlAlchemyDataPort:
    return SqlAlchemyDataPort(session)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _invalid(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _schema_missing(exc: OperationalError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="V2 数据库尚未迁移；请先运行显式迁移命令，旧 /api/state 不受影响",
    )


@router.get("/meta")
def meta():
    return {"contract_version": "2.0", "schema_version": 1, "server_time": utc_now_iso()}


@router.get("/status")
def data_status(session: Session = Depends(get_v2_session)):
    """Read-only mode detection used by the frontend DataPort.

    The endpoint never creates tables or migrates. If the database itself
    cannot be inspected, return 503; the frontend then stops writing instead
    of guessing a mode, which would risk two write sources.
    """
    try:
        return detect_data_mode(session)
    except Exception as exc:  # noqa: BLE001 - diagnostic path must fail closed
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"无法读取数据状态，前端已停止写入：{exc}",
        ) from exc


@router.get("/notes", response_model=NotePage)
def list_notes(
    q: str | None = Query(default=None, max_length=200),
    tag_id: str | None = Query(default=None, max_length=64),
    favorite: bool | None = Query(default=None),
    trashed: bool | None = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="updated", pattern="^(updated|created|title)$"),
    port: SqlAlchemyDataPort = Depends(get_port),
):
    try:
        return port.list_notes(query=q, tag_id=tag_id, favorite=favorite, trashed=trashed, page=page, page_size=page_size, sort=sort)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.create_note(payload)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ConflictError as exc:
        raise _conflict(exc) from exc
    except (InvalidReferenceError, ValueError) as exc:
        raise _invalid(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.get("/notes/{note_id}", response_model=NoteRead)
def get_note(note_id: str, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.get_note(note_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.patch("/notes/{note_id}", response_model=NoteRead)
def update_note(note_id: str, payload: NotePatch, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.update_note(note_id, payload)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ConflictError as exc:
        raise _conflict(exc) from exc
    except (InvalidReferenceError, ValueError) as exc:
        raise _invalid(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.patch("/notes/{note_id}/favorite", response_model=NoteRead)
def set_favorite(note_id: str, payload: FavoriteRequest, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.set_favorite(note_id, payload.favorite)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/notes/{note_id}/restore", response_model=NoteRead)
def restore_note(note_id: str, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.restore_note(note_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: str,
    permanent: bool = Query(default=False),
    port: SqlAlchemyDataPort = Depends(get_port),
):
    try:
        port.delete_note(note_id, permanent=permanent)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notes/{note_id}/attachments", response_model=list[AttachmentRead])
def list_attachments(note_id: str, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.list_attachments(note_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.get("/tags", response_model=list[TagRead])
def list_tags(port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.list_tags()
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/tags", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.create_tag(payload)
    except ConflictError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.patch("/tags/{tag_id}", response_model=TagRead)
def update_tag(tag_id: str, payload: TagUpdate, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.update_tag(tag_id, payload)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ConflictError as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: str, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        port.delete_tag(tag_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except OperationalError as exc:
        raise _schema_missing(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/settings", response_model=AppSettings)
def get_settings(port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.get_settings()
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.patch("/settings", response_model=AppSettings)
def update_settings(payload: AppSettingsPatch, port: SqlAlchemyDataPort = Depends(get_port)):
    try:
        return port.update_settings(payload)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


# AI config/chat routes live in a child router so the public prefix stays /api/v2/ai.
router.include_router(ai_router)
