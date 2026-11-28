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
    ChatReply,
    ConversationCreate,
    ConversationPage,
    ConversationPatch,
    ConversationRead,
    MessagePage,
    MessageRead,
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
    ConversationV2,
    MessageV2,
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


    # ---------- C2 conversations and messages ----------

    def _conversation(self, conversation_id: str) -> ConversationV2:
        row = self.session.get(ConversationV2, conversation_id)
        if row is None:
            raise NotFoundError(f"对话不存在: {conversation_id}")
        return row

    def _message(self, message_id: str) -> MessageV2:
        row = self.session.get(MessageV2, message_id)
        if row is None:
            raise NotFoundError(f"消息不存在: {message_id}")
        return row

    @staticmethod
    def _conversation_extra(row: ConversationV2) -> dict[str, Any]:
        try:
            value = json.loads(row.extra_json or "{}")
        except (TypeError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _message_count(self, conversation_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(MessageV2).where(
                    MessageV2.conversation_id == conversation_id
                )
            )
            or 0
        )

    def conversation_public(self, row: ConversationV2, *, message_count: int | None = None) -> ConversationRead:
        extra = self._conversation_extra(row)
        prompt = extra.get("system_prompt")
        return ConversationRead(
            id=row.id,
            title=row.title,
            provider_id=row.provider_id,
            model=row.model or "",
            system_prompt=str(prompt) if isinstance(prompt, str) and prompt else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
            archived_at=row.archived_at,
            revision=row.revision,
            message_count=self._message_count(row.id) if message_count is None else message_count,
        )

    @staticmethod
    def _message_public(row: MessageV2) -> MessageRead:
        return MessageRead(
            id=row.id,
            conversation_id=row.conversation_id,
            role=row.role,  # type: ignore[arg-type]
            content=row.content or "",
            status=row.status,  # type: ignore[arg-type]
            sequence=row.sequence,
            client_id=row.client_id,
            error_code=row.error_code,
            created_at=row.created_at,
            updated_at=row.updated_at,
            revision=row.revision,
        )

    def list_conversations(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        include_archived: bool = False,
    ) -> ConversationPage:
        stmt = select(ConversationV2)
        count_stmt = select(func.count()).select_from(ConversationV2)
        if not include_archived:
            stmt = stmt.where(ConversationV2.archived_at.is_(None))
            count_stmt = count_stmt.where(ConversationV2.archived_at.is_(None))
        total = int(self.session.scalar(count_stmt) or 0)
        rows = list(
            self.session.scalars(
                stmt.order_by(ConversationV2.updated_at.desc(), ConversationV2.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return ConversationPage(
            items=[self.conversation_public(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_conversation(self, conversation_id: str) -> ConversationRead:
        return self.conversation_public(self._conversation(conversation_id))

    def create_conversation(self, payload: ConversationCreate, *, model: str) -> ConversationRead:
        now = utc_now_iso()
        extra: dict[str, Any] = {}
        if payload.system_prompt:
            extra["system_prompt"] = payload.system_prompt
        row = ConversationV2(
            id=_new_id(),
            title=payload.title.strip() or "新对话",
            provider_id=payload.provider_id,
            model=model,
            created_at=now,
            updated_at=now,
            archived_at=None,
            revision=1,
            extra_json=json.dumps(extra, ensure_ascii=False),
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self.conversation_public(row)

    def update_conversation(self, conversation_id: str, payload: ConversationPatch) -> ConversationRead:
        row = self._conversation(conversation_id)
        if payload.revision is not None and payload.revision != row.revision:
            raise ConflictError("对话已被其他操作修改，请刷新后重试")
        fields = payload.model_fields_set
        if "title" in fields and payload.title is not None:
            row.title = payload.title.strip()
        if "provider_id" in fields and payload.provider_id is not None:
            row.provider_id = payload.provider_id
        if "model" in fields and payload.model is not None:
            row.model = payload.model
        if "archived" in fields and payload.archived is not None:
            row.archived_at = utc_now_iso() if payload.archived else None
        if "system_prompt" in fields:
            extra = self._conversation_extra(row)
            if payload.system_prompt:
                extra["system_prompt"] = payload.system_prompt
            else:
                extra.pop("system_prompt", None)
            row.extra_json = json.dumps(extra, ensure_ascii=False)
        row.revision += 1
        row.updated_at = utc_now_iso()
        self.session.commit()
        self.session.refresh(row)
        return self.conversation_public(row)

    def delete_conversation(self, conversation_id: str) -> None:
        row = self._conversation(conversation_id)
        self.session.execute(delete(MessageV2).where(MessageV2.conversation_id == conversation_id))
        self.session.delete(row)
        self.session.commit()

    def list_messages(
        self,
        conversation_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> MessagePage:
        self._conversation(conversation_id)
        total = int(
            self.session.scalar(
                select(func.count()).select_from(MessageV2).where(
                    MessageV2.conversation_id == conversation_id
                )
            )
            or 0
        )
        rows = list(
            self.session.scalars(
                select(MessageV2)
                .where(MessageV2.conversation_id == conversation_id)
                .order_by(MessageV2.sequence.asc(), MessageV2.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return MessagePage(
            items=[self._message_public(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_message(self, message_id: str) -> MessageRead:
        return self._message_public(self._message(message_id))

    def find_message_by_client_id(self, conversation_id: str, client_id: str) -> MessageRead | None:
        row = self.session.scalar(
            select(MessageV2).where(
                MessageV2.conversation_id == conversation_id,
                MessageV2.client_id == client_id,
            )
        )
        return self._message_public(row) if row is not None else None

    def next_message(self, conversation_id: str, sequence: int) -> MessageRead | None:
        row = self.session.scalar(
            select(MessageV2)
            .where(
                MessageV2.conversation_id == conversation_id,
                MessageV2.sequence == sequence,
            )
            .limit(1)
        )
        return self._message_public(row) if row is not None else None

    def append_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        status: str = "complete",
        client_id: str | None = None,
    ) -> MessageRead:
        conversation = self._conversation(conversation_id)
        if client_id:
            existing = self.find_message_by_client_id(conversation_id, client_id)
            if existing is not None:
                return existing
        now = utc_now_iso()
        current_max = self.session.scalar(
            select(func.max(MessageV2.sequence)).where(
                MessageV2.conversation_id == conversation_id
            )
        )
        row = MessageV2(
            id=_new_id(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=status,
            sequence=int(current_max or 0) + 1,
            client_id=client_id,
            error_code=None,
            created_at=now,
            updated_at=now,
            revision=1,
        )
        self.session.add(row)
        conversation.updated_at = now
        self.session.commit()
        self.session.refresh(row)
        return self._message_public(row)

    def update_message(
        self,
        message_id: str,
        *,
        content: str | object = _UNSET,
        status: str | object = _UNSET,
        error_code: str | None | object = _UNSET,
    ) -> MessageRead:
        row = self._message(message_id)
        if content is not _UNSET:
            row.content = str(content)
        if status is not _UNSET:
            row.status = str(status)
        if error_code is not _UNSET:
            row.error_code = error_code  # type: ignore[assignment]
        row.revision += 1
        row.updated_at = utc_now_iso()
        self.session.commit()
        self.session.refresh(row)
        return self._message_public(row)

    def recover_stale_messages(
        self, conversation_id: str, *, older_than_seconds: int = 120
    ) -> int:
        """Mark abandoned pending/streaming placeholders after a crash.

        Live streams touch updated_at on every delta, so only genuinely stale
        rows are converted. Without this a process crash would leave an
        assistant bubble "streaming" forever.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=max(1, older_than_seconds))
        ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        rows = list(
            self.session.scalars(
                select(MessageV2).where(
                    MessageV2.conversation_id == conversation_id,
                    MessageV2.status.in_(("pending", "streaming")),
                    MessageV2.updated_at < cutoff,
                )
            ).all()
        )
        if not rows:
            return 0
        now = utc_now_iso()
        for row in rows:
            row.status = "error"
            row.error_code = "generation_interrupted"
            row.updated_at = now
            row.revision += 1
        self.session.commit()
        return len(rows)

    def context_messages(
        self,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        limit: int = 30,
        char_budget: int = 24_000,
    ) -> list[MessageRead]:
        """Newest-first bounded history, returned oldest-first for the model."""
        stmt = select(MessageV2).where(MessageV2.conversation_id == conversation_id)
        if before_sequence is not None:
            stmt = stmt.where(MessageV2.sequence < before_sequence)
        stmt = stmt.where(
            MessageV2.role.in_(("user", "assistant")),
            MessageV2.status.in_(("complete", "stopped")),
            MessageV2.content != "",
        )
        rows = list(
            self.session.scalars(
                stmt.order_by(MessageV2.sequence.desc()).limit(max(1, limit))
            ).all()
        )
        selected: list[MessageRead] = []
        used = 0
        for row in rows:
            item = self._message_public(row)
            cost = len(item.content)
            if used + cost > char_budget:
                if selected:
                    break
                # Keep the newest turn (usually the message just sent) but never
                # exceed the hard context budget, even when a long system prompt
                # leaves very little room.
                item = item.model_copy(update={"content": item.content[:char_budget]})
                cost = len(item.content)
            selected.append(item)
            used += cost
        selected.reverse()
        return selected

    def last_user_before(self, conversation_id: str, sequence: int) -> MessageRead | None:
        row = self.session.scalar(
            select(MessageV2)
            .where(
                MessageV2.conversation_id == conversation_id,
                MessageV2.sequence < sequence,
                MessageV2.role == "user",
                MessageV2.status == "complete",
            )
            .order_by(MessageV2.sequence.desc())
        )
        return self._message_public(row) if row is not None else None


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