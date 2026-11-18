from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import NoteCreate, NoteList, NoteRead, NoteUpdate

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Hephaestus", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 第一阶段按学习手册要求使用内存存储；服务重启后数据会清空。
notes: list[dict] = []
next_id = 1

# 兼容现有前端完整数据结构（富文本、标签、收藏、回收站和界面设置）。
# 前端通过该接口同步整个本地优先状态；正式 REST CRUD 接口仍保留在 /notes。
frontend_state: dict | None = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def find_note(note_id: int) -> dict:
    for note in notes:
        if note["id"] == note_id:
            return note
    raise HTTPException(status_code=404, detail="笔记不存在")


@app.get("/")
def read_root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate):
    global next_id
    timestamp = now()
    note = {
        "id": next_id,
        **payload.model_dump(),
        "is_favorite": False,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    notes.append(note)
    next_id += 1
    return note


@app.get("/notes", response_model=NoteList)
def list_notes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    ordered = sorted(notes, key=lambda item: item["updated_at"], reverse=True)
    start = (page - 1) * page_size
    return {
        "items": ordered[start:start + page_size],
        "total": len(ordered),
        "page": page,
        "page_size": page_size,
    }


@app.get("/notes/{note_id}", response_model=NoteRead)
def get_note(note_id: int):
    return find_note(note_id)


@app.put("/notes/{note_id}", response_model=NoteRead)
def update_note(note_id: int, payload: NoteUpdate):
    note = find_note(note_id)
    note.update(payload.model_dump())
    note["updated_at"] = now()
    return note


@app.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int):
    note = find_note(note_id)
    notes.remove(note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/state")
def get_frontend_state():
    return {"initialized": frontend_state is not None, "state": frontend_state}


@app.put("/api/state")
def save_frontend_state(payload: dict):
    global frontend_state
    if not isinstance(payload.get("notes"), list) or not isinstance(payload.get("tags"), list):
        raise HTTPException(status_code=422, detail="state 必须包含 notes 和 tags 数组")
    frontend_state = payload
    return {"saved": True, "note_count": len(frontend_state["notes"])}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
