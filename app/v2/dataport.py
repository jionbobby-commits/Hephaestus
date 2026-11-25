"""Python DataPort for the V2 desktop/web backend (B1.3).

The UI and API must call this port instead of issuing SQL directly. The mobile
TypeScript port implements the same method semantics and contract fixtures.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.v2.contracts import (
    AIProviderConfigCreate,
    AIProviderConfigRead,
    AIProviderConfigUpdate,
    AIProviderParams,
    AppSettings,
    AppSettingsPatch,
    AttachmentRead,
    NoteCreate,
    NotePage,
    NotePatch,
    NoteRead,
    TagCreate,
    TagRead,
    TagUpdate,
    epoch_ms_to_iso,
    html_to_text,
    note_to_public,
    utc_now_iso,
)
from app.v2.models import (
    AIProviderConfigV2,
    AppSettingV2,
    AttachmentV2,
    NoteV2,
    TagV2,
    v2_note_attachments,
    v2_note_tags,
)


class DataPortError(Exception):
    """Base class for domain errors mapped by the API layer."""


class NotFoundError(DataPortError):
    pass


class ConflictError(DataPortError):
    pass


class InvalidReferenceError(DataPortError):
    pass


_UNSET = object()


def _new_id() -> str:
    return uuid.uuid4().hex


def _tag_public(tag: TagV2) -> TagRead:
    return TagRead(id=tag.id, name=tag.name, color=tag.color, created_at=tag.created_at, updated_at=tag.updated_at)


def _attachment_public(attachment: AttachmentV2) -> AttachmentRead:
    return AttachmentRead(
        id=attachment.id,
        original_name=attachment.original_name,
        mime=attachment.mime,
        size=attachment.size,
        sha256=attachment.sha256,
        kind=attachment.kind,
        created_at=attachment.created_at,
    )


class SqlAlchemyDataPort:
    def __init__(self, session: Session):
        self.session = session

    # ---------- notes ----------

    def _note(self, note_id: str) -> NoteV2:
        note = self.session.scalar(
            select(NoteV2)
            .options(selectinload(NoteV2.tags), selectinload(NoteV2.attachments))
            .where(NoteV2.id == note_id)
        )
        if note is None:
            raise NotFoundError(f"笔记不存在: {note_id}")
        return note

    def _tags_by_ids(self, tag_ids: list[str]) -> list[TagV2]:
        ids = list(dict.fromkeys(tag_ids))
        if not ids:
            return []
        tags = self.session.scalars(select(TagV2).where(TagV2.id.in_(ids))).all()
        found = {t.id for t in tags}
        missing = [tag_id for tag_id in ids if tag_id not in found]
        if missing:
            raise InvalidReferenceError("标签不存在: " + ", ".join(missing))
        by_id = {t.id: t for t in tags}
        return [by_id[tag_id] for tag_id in ids]

    def _base_query(self, query: str | None, tag_id: str | None, favorite: bool | None, trashed: bool | None):
        stmt = select(NoteV2)
        if query:
            needle = f"%{query.strip()}%"
            stmt = stmt.where(NoteV2.title.ilike(needle) | NoteV2.content_text.ilike(needle))
        if tag_id:
            stmt = stmt.where(NoteV2.tags.any(TagV2.id == tag_id))
        if favorite is not None:
            stmt = stmt.where(NoteV2.is_favorite.is_(favorite))
        if trashed is not None:
            stmt = stmt.where(NoteV2.is_trashed.is_(trashed))
        return stmt

    def list_notes(
        self,
        *,
        query: str | None = None,
        tag_id: str | None = None,
        favorite: bool | None = None,
        trashed: bool | None = False,
        page: int = 1,
        page_size: int = 20,
        sort: str = "updated",
    ) -> NotePage:
        page = max(1, int(page))
        page_size = min(100, max(1, int(page_size)))
        stmt = self._base_query(query, tag_id, favorite, trashed)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self.session.scalar(count_stmt) or 0)
        order = {
            "updated": (NoteV2.updated_at.desc(), NoteV2.id.desc()),
            "created": (NoteV2.created_at.desc(), NoteV2.id.desc()),
            "title": (func.lower(NoteV2.title).asc(), NoteV2.id.asc()),
        }.get(sort, (NoteV2.updated_at.desc(), NoteV2.id.desc()))
        notes = self.session.scalars(
            stmt.options(selectinload(NoteV2.tags), selectinload(NoteV2.attachments))
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return NotePage(
            items=[note_to_public(n) for n in notes],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_note(self, note_id: str) -> NoteRead:
        return note_to_public(self._note(note_id))

    def create_note(self, payload: NoteCreate) -> NoteRead:
        title = payload.title.strip()
        if not title:
            raise ValueError("标题不能为空")
        tags = self._tags_by_ids(payload.tags)
        now = utc_now_iso()
        note = NoteV2(
            id=_new_id(),
            title=title,
            content_html=payload.content_html,
            content_text=payload.content_text or html_to_text(payload.content_html),
            category=(payload.category.strip() or None) if payload.category else None,
            is_favorite=False,
            favorited_at=None,
            is_trashed=False,
            trashed_at=None,
            created_at=now,
            updated_at=now,
            revision=1,
            tags=tags,
        )
        self.session.add(note)
        self.session.commit()
        return note_to_public(self._note(note.id))

    def update_note(self, note_id: str, payload: NotePatch) -> NoteRead:
        note = self._note(note_id)
        if payload.revision is not None and payload.revision != note.revision:
            raise ConflictError(f"笔记已被修改: 当前 revision={note.revision}")
        fields = payload.model_fields_set
        if "title" in fields:
            title = (payload.title or "").strip()
            if not title:
                raise ValueError("标题不能为空")
            note.title = title
        if "content_html" in fields:
            note.content_html = payload.content_html or ""
            if "content_text" not in fields:
                note.content_text = html_to_text(note.content_html)
        if "content_text" in fields:
            note.content_text = payload.content_text or ""
        if "category" in fields:
            note.category = (payload.category.strip() or None) if payload.category else None
        if "tags" in fields and payload.tags is not None:
            note.tags = self._tags_by_ids(payload.tags)
        if "is_favorite" in fields and payload.is_favorite is not None:
            self._set_favorite(note, payload.is_favorite, touch=False)
        note.revision += 1
        note.updated_at = utc_now_iso()
        self.session.commit()
        return note_to_public(self._note(note.id))

    def _set_favorite(self, note: NoteV2, favorite: bool, *, touch: bool = True) -> None:
        note.is_favorite = favorite
        note.favorited_at = utc_now_iso() if favorite else None
        if touch:
            note.revision += 1
            note.updated_at = utc_now_iso()

    def set_favorite(self, note_id: str, favorite: bool) -> NoteRead:
        note = self._note(note_id)
        self._set_favorite(note, favorite)
        self.session.commit()
        return note_to_public(self._note(note_id))

    def trash_note(self, note_id: str) -> NoteRead:
        note = self._note(note_id)
        if not note.is_trashed:
            note.is_trashed = True
            note.trashed_at = utc_now_iso()
            note.revision += 1
            note.updated_at = utc_now_iso()
            self.session.commit()
        return note_to_public(self._note(note_id))

    def restore_note(self, note_id: str) -> NoteRead:
        note = self._note(note_id)
        if note.is_trashed:
            note.is_trashed = False
            note.trashed_at = None
            note.revision += 1
            note.updated_at = utc_now_iso()
            self.session.commit()
        return note_to_public(self._note(note_id))

    def delete_note(self, note_id: str, *, permanent: bool = False) -> None:
        note = self._note(note_id)
        if not permanent:
            self.trash_note(note_id)
            return
        # ORM many-to-many handling removes only this note's link rows. Shared
        # attachment metadata and files must survive for other notes.
        self.session.delete(note)
        self.session.commit()

    # ---------- tags ----------

    def list_tags(self) -> list[TagRead]:
        tags = self.session.scalars(select(TagV2).order_by(TagV2.created_at, TagV2.id)).all()
        return [_tag_public(t) for t in tags]

    def create_tag(self, payload: TagCreate) -> TagRead:
        name = payload.name.strip()
        if not name:
            raise ValueError("标签名不能为空")
        if self.session.scalar(select(TagV2).where(TagV2.name == name)) is not None:
            raise ConflictError(f"标签已存在: {name}")
        now = utc_now_iso()
        tag = TagV2(id=_new_id(), name=name, color=payload.color, created_at=now, updated_at=now)
        self.session.add(tag)
        self.session.commit()
        return _tag_public(tag)

    def update_tag(self, tag_id: str, payload: TagUpdate) -> TagRead:
        tag = self.session.get(TagV2, tag_id)
        if tag is None:
            raise NotFoundError(f"标签不存在: {tag_id}")
        if "name" in payload.model_fields_set and payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise ValueError("标签名不能为空")
            duplicate = self.session.scalar(select(TagV2).where(TagV2.name == name, TagV2.id != tag_id))
            if duplicate is not None:
                raise ConflictError(f"标签已存在: {name}")
            tag.name = name
        if "color" in payload.model_fields_set and payload.color is not None:
            tag.color = payload.color
        tag.updated_at = utc_now_iso()
        self.session.commit()
        return _tag_public(tag)

    def delete_tag(self, tag_id: str) -> None:
        tag = self.session.get(TagV2, tag_id)
        if tag is None:
            raise NotFoundError(f"标签不存在: {tag_id}")
        self.session.execute(delete(v2_note_tags).where(v2_note_tags.c.tag_id == tag_id))
        self.session.delete(tag)
        self.session.commit()

    # ---------- settings ----------

    def get_settings(self) -> AppSettings:
        values: dict[str, Any] = {}
        for row in self.session.scalars(select(AppSettingV2)).all():
            try:
                values[row.key] = json.loads(row.value_json)
            except json.JSONDecodeError:
                continue
        return AppSettings.model_validate(values)

    def update_settings(self, payload: AppSettingsPatch) -> AppSettings:
        changes = payload.model_dump(exclude_unset=True)
        now = utc_now_iso()
        for key, value in changes.items():
            row = self.session.get(AppSettingV2, key)
            if row is None:
                row = AppSettingV2(key=key, value_json="", updated_at=now)
                self.session.add(row)
            row.value_json = json.dumps(value, ensure_ascii=False)
            row.updated_at = now
        self.session.commit()
        return self.get_settings()

    # ---------- AI provider configs (no secret here) ----------

    @staticmethod
    def _provider_extra(row: AIProviderConfigV2) -> dict[str, Any]:
        try:
            value = json.loads(row.extra_json or "{}")
        except (TypeError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _provider_meta(cls, row: AIProviderConfigV2) -> tuple[dict[str, Any], bool, bool, AIProviderParams]:
        extra = cls._provider_extra(row)
        raw_params = extra.get("params", {})
        try:
            params = AIProviderParams.model_validate(raw_params if isinstance(raw_params, dict) else {})
        except Exception:
            params = AIProviderParams()
        return extra, bool(extra.get("enabled", True)), bool(extra.get("is_default", False)), params

    @classmethod
    def provider_public(cls, row: AIProviderConfigV2, *, has_key: bool | None = None) -> AIProviderConfigRead:
        _extra, enabled, is_default, params = cls._provider_meta(row)
        return AIProviderConfigRead(
            id=row.id,
            kind=row.kind,
            label=row.label,
            base_url=row.base_url,
            model=row.model,
            enabled=enabled,
            is_default=is_default,
            params=params,
            has_key=bool(row.key_ref) if has_key is None else has_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def list_ai_provider_rows(self) -> list[AIProviderConfigV2]:
        return list(self.session.scalars(select(AIProviderConfigV2).order_by(AIProviderConfigV2.created_at)).all())

    def get_ai_provider_row(self, provider_id: str) -> AIProviderConfigV2:
        row = self.session.get(AIProviderConfigV2, provider_id)
        if row is None:
            raise NotFoundError(f"AI 配置不存在: {provider_id}")
        return row

    def list_ai_providers(self) -> list[AIProviderConfigRead]:
        return [self.provider_public(row) for row in self.list_ai_provider_rows()]

    def create_ai_provider(self, payload: AIProviderConfigCreate, *, key_ref: str | None = None) -> AIProviderConfigRead:
        now = utc_now_iso()
        extra = {
            "enabled": payload.enabled,
            "is_default": payload.is_default,
            "params": payload.params.model_dump(),
        }
        # key_ref is deprecated in the public contract; read storage directly so
        # old direct-DataPort callers keep working without emitting warnings.
        legacy_ref = payload.__dict__.get("key_ref")
        effective_ref = key_ref if key_ref is not None else legacy_ref
        row = AIProviderConfigV2(
            id=_new_id(),
            kind=payload.kind,
            label=payload.label,
            base_url=payload.base_url,
            model=payload.model,
            key_ref=effective_ref,
            created_at=now,
            updated_at=now,
            extra_json=json.dumps(extra, ensure_ascii=False),
        )
        self.session.add(row)
        self.session.commit()
        return self.provider_public(row, has_key=bool(effective_ref))

    def update_ai_provider(
        self,
        provider_id: str,
        payload: AIProviderConfigUpdate,
        *,
        key_ref: str | None | object = _UNSET,
        has_key: bool | None = None,
    ) -> AIProviderConfigRead:
        row = self.get_ai_provider_row(provider_id)
        fields = payload.model_fields_set
        for name in ("kind", "label", "base_url", "model"):
            if name in fields:
                setattr(row, name, getattr(payload, name))
        extra = self._provider_extra(row)
        if "enabled" in fields:
            extra["enabled"] = bool(payload.enabled)
        if "is_default" in fields:
            extra["is_default"] = bool(payload.is_default)
        if "params" in fields and payload.params is not None:
            extra["params"] = payload.params.model_dump()
        if key_ref is not _UNSET:
            row.key_ref = key_ref  # type: ignore[assignment]
        row.extra_json = json.dumps(extra, ensure_ascii=False)
        row.updated_at = utc_now_iso()
        self.session.commit()
        return self.provider_public(row, has_key=has_key)

    def set_ai_defaults(self, default_id: str | None) -> None:
        """Make exactly one provider the default and mirror its model in settings.

        Unknown extra_json keys and secrets are preserved. A disabled provider
        can never remain the default.
        """
        rows = self.list_ai_provider_rows()
        chosen: AIProviderConfigV2 | None = None
        for row in rows:
            extra = self._provider_extra(row)
            enabled = bool(extra.get("enabled", True))
            is_default = row.id == default_id and enabled
            extra["is_default"] = is_default
            row.extra_json = json.dumps(extra, ensure_ascii=False)
            if is_default:
                chosen = row
        settings = self.session.get(AppSettingV2, "default_model")
        value = chosen.model if chosen is not None else None
        if settings is None:
            settings = AppSettingV2(key="default_model", value_json="", updated_at=utc_now_iso())
            self.session.add(settings)
        settings.value_json = json.dumps(value, ensure_ascii=False)
        settings.updated_at = utc_now_iso()
        self.session.commit()

    def delete_ai_provider(self, provider_id: str) -> None:
        row = self.get_ai_provider_row(provider_id)
        self.session.delete(row)
        self.session.commit()

    # ---------- attachments (metadata only in B1) ----------

    def list_attachments(self, note_id: str) -> list[AttachmentRead]:
        self._note(note_id)
        rows = self.session.scalars(
            select(AttachmentV2)
            .join(v2_note_attachments, v2_note_attachments.c.attachment_id == AttachmentV2.id)
            .where(v2_note_attachments.c.note_id == note_id)
            .order_by(AttachmentV2.created_at, AttachmentV2.id)
        ).all()
        return [_attachment_public(a) for a in rows]
