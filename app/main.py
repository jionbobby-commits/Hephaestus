from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import create_db, get_db
from app.models import FrontendState, Note
from app.schemas import FrontendStatePayload, NoteCreate, NoteList, NoteRead, NoteUpdate

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db()
    yield


app = FastAPI(title="Hephaestus", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
DbSession = Annotated[Session, Depends(get_db)]


@app.get("/")
def read_root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, db: DbSession):
    note = Note(**payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@app.get("/notes", response_model=NoteList)
def list_notes(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    q: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=30),
    favorite: bool | None = None,
):
    filters = []
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        filters.append(or_(Note.title.ilike(keyword), Note.content.ilike(keyword)))
    if category:
        filters.append(Note.category == category)
    if favorite is not None:
        filters.append(Note.is_favorite.is_(favorite))

    total = db.scalar(select(func.count()).select_from(Note).where(*filters)) or 0
    statement = (
        select(Note)
        .where(*filters)
        .order_by(Note.updated_at.desc(), Note.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = db.scalars(statement).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/notes/{note_id}", response_model=NoteRead)
def get_note(note_id: int, db: DbSession):
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


@app.put("/notes/{note_id}", response_model=NoteRead)
def update_note(note_id: int, payload: NoteUpdate, db: DbSession):
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    for key, value in payload.model_dump().items():
        setattr(note, key, value)
    db.commit()
    db.refresh(note)
    return note


@app.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: DbSession):
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    db.delete(note)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/state")
def get_frontend_state(db: DbSession):
    saved = db.get(FrontendState, 1)
    return {
        "initialized": saved is not None,
        "state": saved.payload if saved is not None else None,
    }


@app.put("/api/state")
def save_frontend_state(payload: FrontendStatePayload, db: DbSession):
    state = payload.model_dump(mode="json")
    if len(state["notes"]) > 10000 or len(state["tags"]) > 1000:
        raise HTTPException(status_code=413, detail="笔记或标签数量超过限制")

    saved = db.get(FrontendState, 1)
    if saved is None:
        saved = FrontendState(id=1, payload=state)
        db.add(saved)
    else:
        saved.payload = state
    db.commit()
    return {"saved": True, "note_count": len(state["notes"])}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
