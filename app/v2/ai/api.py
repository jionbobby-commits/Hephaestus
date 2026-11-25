"""HTTP surface for AI provider configuration and use."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.v2.ai.errors import AIError
from app.v2.ai.secrets import SecretStore, default_secret_store
from app.v2.ai.service import AIProviderService
from app.v2.ai.transport import HttpTransport, default_transport
from app.v2.contracts import (
    AIChatRequest,
    AIChatResult,
    AIConnectionTest,
    AIModelList,
    AIProviderConfigCreate,
    AIProviderConfigRead,
    AIProviderConfigUpdate,
)
from app.v2.dataport import SqlAlchemyDataPort
from app.v2.db import get_v2_session

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def get_port(session: Session = Depends(get_v2_session)) -> SqlAlchemyDataPort:
    return SqlAlchemyDataPort(session)


def get_ai_secret_store() -> SecretStore:
    return default_secret_store()


def get_ai_transport() -> HttpTransport:
    return default_transport()


def get_client_platform(
    x_hephaestus_platform: str = Header(default="web", alias="X-Hephaestus-Platform"),
) -> str:
    platform = (x_hephaestus_platform or "web").strip().lower()
    if platform not in {"desktop", "web", "mobile"}:
        raise HTTPException(status_code=422, detail="X-Hephaestus-Platform 只能是 desktop、web 或 mobile")
    return platform


def require_local_client(request: Request) -> None:
    """AI config and chat stay on the local machine unless explicitly opted out."""
    if os.getenv("HEPHAESTUS_AI_ALLOW_REMOTE", "").lower() in {"1", "true", "yes"}:
        return
    host = request.client.host if request.client else ""
    if host in _LOCAL_HOSTS or host.startswith("127."):
        return
    raise HTTPException(status_code=403, detail="AI 配置接口仅允许本机访问")


def get_ai_service(
    port: SqlAlchemyDataPort = Depends(get_port),
    secret_store: SecretStore = Depends(get_ai_secret_store),
    transport: HttpTransport = Depends(get_ai_transport),
    platform: str = Depends(get_client_platform),
) -> AIProviderService:
    return AIProviderService(port, secret_store=secret_store, transport=transport, platform=platform)


def _error(exc: AIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(exc.to_response()))


def _schema_missing(exc: OperationalError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="V2 数据库尚未迁移；请先运行显式迁移命令，旧 /api/state 不受影响",
    )


router = APIRouter(prefix="/ai", tags=["V2 AI"], dependencies=[Depends(require_local_client)])


@router.get("/providers", response_model=list[AIProviderConfigRead])
def list_ai_providers(service: AIProviderService = Depends(get_ai_service)):
    try:
        return service.list_providers()
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/providers", response_model=AIProviderConfigRead, status_code=status.HTTP_201_CREATED)
def create_ai_provider(payload: AIProviderConfigCreate, service: AIProviderService = Depends(get_ai_service)):
    try:
        return service.create_provider(payload)
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.patch("/providers/{provider_id}", response_model=AIProviderConfigRead)
def update_ai_provider(
    provider_id: str,
    payload: AIProviderConfigUpdate,
    service: AIProviderService = Depends(get_ai_service),
):
    try:
        return service.update_provider(provider_id, payload)
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_provider(provider_id: str, service: AIProviderService = Depends(get_ai_service)):
    try:
        service.delete_provider(provider_id)
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/providers/{provider_id}/models", response_model=AIModelList)
def list_ai_models(provider_id: str, service: AIProviderService = Depends(get_ai_service)):
    try:
        return service.list_models(provider_id)
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/providers/{provider_id}/test", response_model=AIConnectionTest)
def test_ai_provider(provider_id: str, service: AIProviderService = Depends(get_ai_service)):
    try:
        return service.test_connection(provider_id)
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/chat", response_model=AIChatResult)
def chat(payload: AIChatRequest, service: AIProviderService = Depends(get_ai_service)):
    try:
        return service.chat(payload)
    except AIError as exc:
        return _error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc
