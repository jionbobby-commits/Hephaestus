from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Note
from app.schemas import NoteCreate, NoteUpdate


def create_note(db: Session, payload: NoteCreate) -> Note:
    note = Note(**payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def list_notes(db: Session, *, page: int = 1, page_size: int = 10, keyword: str | None = None, category: str | None = None, favorite: bool | None = None) -> dict:
    filters = []
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(or_(Note.title.ilike(pattern), Note.content.ilike(pattern)))
    if category:
        filters.append(Note.category == category)
    if favorite is not None:
        filters.append(Note.is_favorite.is_(favorite))
    total = db.scalar(select(func.count()).select_from(Note).where(*filters)) or 0
    statement = select(Note).where(*filters).order_by(Note.updated_at.desc(), Note.id.desc()).offset((page - 1) * page_size).limit(page_size)
    return {"items": db.scalars(statement).all(), "total": total, "page": page, "page_size": page_size}


def get_note_or_404(db: Session, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


def update_note(db: Session, note_id: int, payload: NoteUpdate) -> Note:
    note = get_note_or_404(db, note_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, key, value)
    db.commit()
    db.refresh(note)
    return note


def set_favorite(db: Session, note_id: int, is_favorite: bool) -> Note:
    note = get_note_or_404(db, note_id)
    note.is_favorite = is_favorite
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note_id: int) -> None:
    note = get_note_or_404(db, note_id)
    db.delete(note)
    db.commit()
