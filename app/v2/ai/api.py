"""HTTP surface for AI provider configuration and use."""
from __future__ import annotations

import os

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.v2.ai.chat import ChatService
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
    ChatReply,
    ConversationCreate,
    ConversationDetail,
    ConversationPage,
    ConversationPatch,
    ConversationRead,
    MessagePage,
    RegenerateRequest,
    SendMessageRequest,
    StopGenerationRequest,
    StopGenerationResult,
)
from app.v2.dataport import (
    ConflictError,
    InvalidReferenceError,
    NotFoundError,
    SqlAlchemyDataPort,
)
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


def _data_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, NotFoundError):
        error = AIError("not_found", str(exc), status_code=404)
    elif isinstance(exc, ConflictError):
        error = AIError("conflict", str(exc), status_code=409)
    elif isinstance(exc, InvalidReferenceError):
        error = AIError("invalid_reference", str(exc), status_code=422)
    else:
        error = AIError("invalid_request", str(exc), status_code=422)
    return _error(error)


def get_chat_service(
    port: SqlAlchemyDataPort = Depends(get_port),
    providers: AIProviderService = Depends(get_ai_service),
    platform: str = Depends(get_client_platform),
    session: Session = Depends(get_v2_session),
) -> ChatService:
    bind = session.get_bind()
    factory = sessionmaker(bind=bind, expire_on_commit=False)
    return ChatService(port, providers, session_factory=factory, platform=platform)


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

# ---------- C2 conversations ----------


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_archived: bool = Query(default=False),
    service: ChatService = Depends(get_chat_service),
):
    try:
        return service.list_conversations(page, page_size, include_archived)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, service: ChatService = Depends(get_chat_service)):
    try:
        return service.create_conversation(payload)
    except AIError as exc:
        return _error(exc)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    service: ChatService = Depends(get_chat_service),
):
    try:
        conversation, messages = service.detail(conversation_id, page, page_size)
        return ConversationDetail(
            conversation=conversation,
            messages=messages.items,
            total=messages.total,
            page=messages.page,
            page_size=messages.page_size,
        )
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: str,
    payload: ConversationPatch,
    service: ChatService = Depends(get_chat_service),
):
    try:
        return service.update_conversation(conversation_id, payload)
    except AIError as exc:
        return _error(exc)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, service: ChatService = Depends(get_chat_service)):
    try:
        service.delete_conversation(conversation_id)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
def list_messages(
    conversation_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    service: ChatService = Depends(get_chat_service),
):
    try:
        return service.list_messages(conversation_id, page=page, page_size=page_size)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    service: ChatService = Depends(get_chat_service),
):
    try:
        if payload.stream:
            return StreamingResponse(
                service.stream_message(conversation_id, payload),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        return service.send_message(conversation_id, payload)
    except AIError as exc:
        return _error(exc)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/conversations/{conversation_id}/messages/{message_id}/regenerate")
def regenerate_message(
    conversation_id: str,
    message_id: str,
    payload: RegenerateRequest,
    service: ChatService = Depends(get_chat_service),
):
    if payload.message_id != message_id:
        return _error(AIError("invalid_request", "路径与消息 ID 不一致", status_code=422))
    try:
        if payload.stream:
            return StreamingResponse(
                service.stream_regenerate(conversation_id, payload),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        return service.regenerate(conversation_id, payload)
    except AIError as exc:
        return _error(exc)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post("/conversations/{conversation_id}/stop", response_model=StopGenerationResult)
def stop_generation(
    conversation_id: str,
    payload: StopGenerationRequest | None = Body(default=None),
    service: ChatService = Depends(get_chat_service),
):
    try:
        return service.stop(conversation_id, payload.message_id if payload else None)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/stop",
    response_model=StopGenerationResult,
)
def stop_message(
    conversation_id: str,
    message_id: str,
    service: ChatService = Depends(get_chat_service),
):
    try:
        return service.stop(conversation_id, message_id)
    except (NotFoundError, ConflictError, InvalidReferenceError) as exc:
        return _data_error(exc)
    except OperationalError as exc:
        raise _schema_missing(exc) from exc