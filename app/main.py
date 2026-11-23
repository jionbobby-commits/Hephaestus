from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import create_db
from app.release import VERSION, release_info
from app.routers import notes, state
from app.v2.api import router as v2_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db()
    yield


app = FastAPI(title="Hephaestus", version=VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(notes.router)
app.include_router(state.router)
app.include_router(v2_router)


@app.get("/", include_in_schema=False)
def read_root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["系统"])
def health():
    return {"status": "ok"}


@app.get("/api/release", tags=["系统"])
def release():
    return release_info()


@app.get("/download/windows", include_in_schema=False)
def download_windows():
    return RedirectResponse(release_info()["download_url"], status_code=307)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
