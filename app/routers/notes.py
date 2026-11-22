from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import FavoriteUpdate, NoteCreate, NoteList, NoteRead, NoteUpdate
from app.services import notes as note_service

router = APIRouter(prefix="/notes", tags=["笔记"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, db: DbSession):
    return note_service.create_note(db, payload)


@router.get("", response_model=NoteList)
def list_notes(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=100),
    q: str | None = Query(default=None, max_length=100, description="兼容旧版前端搜索参数"),
    category: str | None = Query(default=None, max_length=30),
    favorite: bool | None = None,
):
    return note_service.list_notes(db, page=page, page_size=page_size, keyword=keyword if keyword is not None else q, category=category, favorite=favorite)


@router.get("/favorites", response_model=NoteList)
def list_favorites(db: DbSession, page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100)):
    return note_service.list_notes(db, page=page, page_size=page_size, favorite=True)


@router.get("/{note_id}", response_model=NoteRead)
def get_note(note_id: int, db: DbSession):
    return note_service.get_note_or_404(db, note_id)


@router.patch("/{note_id}", response_model=NoteRead)
def patch_note(note_id: int, payload: NoteUpdate, db: DbSession):
    return note_service.update_note(db, note_id, payload)


@router.put("/{note_id}", response_model=NoteRead, deprecated=True)
def replace_note_compat(note_id: int, payload: NoteUpdate, db: DbSession):
    return note_service.update_note(db, note_id, payload)


@router.patch("/{note_id}/favorite", response_model=NoteRead)
def update_favorite(note_id: int, payload: FavoriteUpdate, db: DbSession):
    return note_service.set_favorite(db, note_id, payload.is_favorite)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: DbSession):
    note_service.delete_note(db, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
