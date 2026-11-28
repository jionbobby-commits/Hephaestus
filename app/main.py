from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import create_db
from app.release import VERSION, release_info
from app.routers import notes, state
from app.v2.ai.capability import ensure_capability_token
from app.v2.ai.middleware import AISecurityMiddleware
from app.v2.ai.validation import validation_exception_handler
from app.v2.api import router as v2_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # C2.1: the token lives only in memory. Desktop sets it before importing
    # this module; web deployments must provision it explicitly.
    ensure_capability_token()
    create_db()
    yield


app = FastAPI(title="Hephaestus", version=VERSION, lifespan=lifespan)
# Never echo api_key/key_ref values back in FastAPI's 422 diagnostics.
app.add_exception_handler(RequestValidationError, validation_exception_handler)


_AI_ERROR_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "invalid_request",
    429: "too_many_requests",
    503: "service_unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def ai_http_exception_handler(request, exc: StarletteHTTPException):
    """Keep dependency/framework errors on AI routes in the same envelope."""
    if not request.url.path.startswith("/api/v2/ai"):
        return await default_http_exception_handler(request, exc)
    message = exc.detail if isinstance(exc.detail, str) else "请求失败"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": _AI_ERROR_CODES.get(exc.status_code, "http_error"),
                "message": message,
                "provider_id": None,
                "retryable": exc.status_code in {429, 503},
                "details": {},
            }
        },
        headers=getattr(exc, "headers", None),
    )
# Local-only boundary for AI routes: Host/Origin validation and a body cap.
app.add_middleware(AISecurityMiddleware)
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