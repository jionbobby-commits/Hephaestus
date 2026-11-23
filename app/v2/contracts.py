"""Hephaestus V2 data contracts (B1.1).

These models are the single source of truth for JSON exchanged by the
desktop Python backend, the web frontend and the mobile TypeScript DataPort.
Physical table names live in app/v2/models.py; they are deliberately v2_-prefixed
so the legacy tables and /api/state keep working during migration.
"""
from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Locale = Literal["zh-CN", "en", "ja", "es", "fr", "ru", "ar", "fa", "he", "tr"]
Theme = Literal["light", "dark", "system"]
Layout = Literal["list", "grid"]
Sort = Literal["updated", "created", "title"]

NoteId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
IsoUtc = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms_to_iso(value: int | float) -> str:
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def html_to_text(value: str) -> str:
    """Best-effort plain text for search/accessibility; HTML remains authoritative."""
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


class TagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=32)
    color: HexColor = "#8b8f94"


class TagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=32)
    color: HexColor | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "TagUpdate":
        if not self.model_fields_set:
            raise ValueError("至少需要修改一个字段")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name 不能为 null")
        return self


class TagRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NoteId
    name: str
    color: str
    created_at: IsoUtc
    updated_at: IsoUtc


class AttachmentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NoteId
    original_name: str
    mime: str
    size: int = Field(ge=0)
    sha256: str
    kind: Literal["image", "audio", "document", "other"]
    created_at: IsoUtc


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    content_html: str = Field(default="", max_length=1_000_000)
    content_text: str = Field(default="", max_length=1_000_000)
    category: str | None = Field(default=None, max_length=30)
    tags: list[NoteId] = Field(default_factory=list, max_length=100)


class NotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    content_html: str | None = Field(default=None, max_length=1_000_000)
    content_text: str | None = Field(default=None, max_length=1_000_000)
    category: str | None = Field(default=None, max_length=30)
    tags: list[NoteId] | None = Field(default=None, max_length=100)
    is_favorite: bool | None = None
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "NotePatch":
        if not self.model_fields_set:
            raise ValueError("至少需要修改一个字段")
        for name in ("title", "content_html", "content_text"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为 null")
        return self


class NoteRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NoteId
    title: str
    content_html: str
    content_text: str
    category: str | None = None
    tags: list[TagRead]
    attachments: list[AttachmentRead]
    is_favorite: bool
    is_trashed: bool
    favorited_at: IsoUtc | None = None
    trashed_at: IsoUtc | None = None
    created_at: IsoUtc
    updated_at: IsoUtc
    revision: int


class NotePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[NoteRead]
    total: int
    page: int
    page_size: int


class FavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favorite: bool


class AppSettings(BaseModel):
    """Public settings object. Extra keys are preserved for forward compatibility."""
    model_config = ConfigDict(extra="allow")
    locale: Locale = "zh-CN"
    theme: Theme = "system"
    layout: Layout = "list"
    sort: Sort = "updated"
    assistant_name: str = Field(default="赫淮斯托斯", min_length=1, max_length=32)
    assistant_style: Literal["professional", "concise", "friendly", "academic", "creative", "custom"] = "friendly"
    response_length: Literal["short", "medium", "long"] = "medium"
    default_model: str | None = Field(default=None, max_length=200)


class AppSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    locale: Locale | None = None
    theme: Theme | None = None
    layout: Layout | None = None
    sort: Sort | None = None
    assistant_name: str | None = Field(default=None, min_length=1, max_length=32)
    assistant_style: Literal["professional", "concise", "friendly", "academic", "creative", "custom"] | None = None
    response_length: Literal["short", "medium", "long"] | None = None
    default_model: str | None = Field(default=None, max_length=200)


AIProviderKind = Literal["ollama", "openai", "anthropic", "gemini", "deepseek", "qwen", "custom"]


class AIProviderConfigCreate(BaseModel):
    """Configuration only; the secret is stored in OS keyring under key_ref."""
    model_config = ConfigDict(extra="forbid")
    kind: AIProviderKind
    label: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    key_ref: str | None = Field(default=None, min_length=1, max_length=255)


class AIProviderConfigRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NoteId
    kind: AIProviderKind
    label: str
    base_url: str
    model: str
    has_key: bool
    created_at: IsoUtc
    updated_at: IsoUtc


class SnapshotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note_count: int
    tag_count: int
    favorite_count: int
    trashed_count: int
    note_tags_count: int
    data_url_count: int
    unknown_note_fields: list[str]
    unknown_tag_fields: list[str]
    source_sha256: str
    source_size: int


def note_to_public(note: Any) -> NoteRead:
    """Map a SQLAlchemy NoteV2 row to its public JSON contract."""
    return NoteRead(
        id=note.id,
        title=note.title,
        content_html=note.content_html or "",
        content_text=note.content_text or "",
        category=note.category,
        tags=[TagRead.model_validate({
            "id": t.id, "name": t.name, "color": t.color,
            "created_at": t.created_at, "updated_at": t.updated_at,
        }) for t in note.tags],
        attachments=[AttachmentRead.model_validate({
            "id": a.id, "original_name": a.original_name, "mime": a.mime,
            "size": a.size, "sha256": a.sha256, "kind": a.kind,
            "created_at": a.created_at,
        }) for a in note.attachments],
        is_favorite=bool(note.is_favorite),
        is_trashed=bool(note.is_trashed),
        favorited_at=note.favorited_at,
        trashed_at=note.trashed_at,
        created_at=note.created_at,
        updated_at=note.updated_at,
        revision=note.revision,
    )
