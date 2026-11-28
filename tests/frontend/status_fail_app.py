"""Test-only ASGI wrapper: serve the real app but fail /api/v2/status.

Used to verify that an initialization failure (page already served, status
endpoint broken) journals edits and merges them after recovery. Never used by
production code.
"""
from __future__ import annotations

from starlette.responses import JSONResponse

from app.main import app as fastapi_app


class StatusFailApp:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/api/v2/status":
            response = JSONResponse({"detail": "injected status failure for B2 test"}, status_code=503)
            await response(scope, receive, send)
            return
        await self.inner(scope, receive, send)


app = StatusFailApp(fastapi_app)
