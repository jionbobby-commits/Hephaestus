from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FrontendState
from app.schemas import FrontendStatePayload

router = APIRouter(prefix="/api/state", tags=["前端状态"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
def get_frontend_state(db: DbSession):
    saved = db.get(FrontendState, 1)
    return {"initialized": saved is not None, "state": saved.payload if saved is not None else None}


@router.put("")
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
