from __future__ import annotations

import re

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.v2.contracts import (
    AIProviderConfigCreate,
    AppSettingsPatch,
    NoteCreate,
    NotePatch,
    TagCreate,
    utc_now_iso,
)
from app.v2.dataport import ConflictError, InvalidReferenceError, NotFoundError, SqlAlchemyDataPort
from app.v2.db import configure_sqlite, create_v2_db
from app.v2.models import AttachmentV2, NoteV2

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture()
def port():
    engine = create_engine("sqlite://")
    configure_sqlite(engine)
    create_v2_db(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield SqlAlchemyDataPort(session)
    engine.dispose()


def test_create_list_update_note_contract(port: SqlAlchemyDataPort):
    tag = port.create_tag(TagCreate(name="设计", color="#48be80"))
    note = port.create_note(NoteCreate(
        title="第一条笔记",
        content_html="<p>你好 <b>世界</b></p>",
        category="开发",
        tags=[tag.id],
    ))
    assert note.title == "第一条笔记"
    assert note.content_text == "你好 世界"
    assert [t.id for t in note.tags] == [tag.id]
    assert note.revision == 1
    assert ISO_RE.match(note.created_at) and ISO_RE.match(note.updated_at)
    assert note.created_at.endswith("Z")

    page = port.list_notes(query="世界")
    assert page.total == 1 and page.items[0].id == note.id
    assert port.list_notes(tag_id=tag.id).total == 1
    assert port.list_notes(favorite=True).total == 0

    updated = port.update_note(note.id, NotePatch(title="改过的标题", revision=1))
    assert updated.title == "改过的标题" and updated.revision == 2
    with pytest.raises(ConflictError):
        port.update_note(note.id, NotePatch(title="冲突", revision=1))
    with pytest.raises(ValidationError):
        NotePatch()


def test_unknown_tag_is_rejected(port: SqlAlchemyDataPort):
    with pytest.raises(InvalidReferenceError):
        port.create_note(NoteCreate(title="x", tags=["missing"]))


def test_favorite_trash_restore_and_permanent_delete(port: SqlAlchemyDataPort):
    note = port.create_note(NoteCreate(title="收藏测试"))
    fav = port.set_favorite(note.id, True)
    assert fav.is_favorite is True and fav.favorited_at is not None
    assert port.list_notes(favorite=True).total == 1

    trashed = port.trash_note(note.id)
    assert trashed.is_trashed is True and trashed.trashed_at is not None
    assert port.list_notes(trashed=False).total == 0
    assert port.list_notes(trashed=True).total == 1
    assert port.list_notes(trashed=None).total == 1

    restored = port.restore_note(note.id)
    assert restored.is_trashed is False and restored.trashed_at is None
    port.delete_note(note.id, permanent=True)
    with pytest.raises(NotFoundError):
        port.get_note(note.id)


def test_delete_tag_keeps_notes(port: SqlAlchemyDataPort):
    tag = port.create_tag(TagCreate(name="临时"))
    note = port.create_note(NoteCreate(title="保留", tags=[tag.id]))
    port.delete_tag(tag.id)
    kept = port.get_note(note.id)
    assert kept.tags == []
    with pytest.raises(NotFoundError):
        port.delete_tag(tag.id)


def test_settings_and_ai_provider_do_not_store_secrets(port: SqlAlchemyDataPort):
    defaults = port.get_settings()
    assert defaults.locale == "zh-CN"
    changed = port.update_settings(AppSettingsPatch(theme="dark", locale="en"))
    assert changed.theme == "dark" and changed.locale == "en"

    without_key = port.create_ai_provider(AIProviderConfigCreate(
        kind="ollama", label="本地 Ollama", base_url="http://127.0.0.1:11434", model="qwen3",
    ))
    assert without_key.has_key is False
    with_key = port.create_ai_provider(AIProviderConfigCreate(
        kind="openai", label="OpenAI", base_url="https://api.openai.com/v1", model="gpt-5", key_ref="keyring:openai",
    ))
    assert with_key.has_key is True
    dumped = with_key.model_dump()
    assert "key_ref" not in dumped and "api_key" not in dumped
    with pytest.raises(ValidationError):
        AIProviderConfigCreate(kind="openai", label="x", base_url="https://x", model="m", api_key="secret")

    port.delete_ai_provider(with_key.id)
    assert len(port.list_ai_providers()) == 1


def test_attachment_link_is_shared_and_never_double_deleted(port: SqlAlchemyDataPort):
    first = port.create_note(NoteCreate(title="附件一"))
    second = port.create_note(NoteCreate(title="附件二"))
    now = utc_now_iso()
    attachment = AttachmentV2(
        id="att_shared", original_name="a.png", mime="image/png", size=3,
        sha256="a" * 64, kind="image", stored_name="files/att_shared.png", created_at=now,
    )
    first_row = port.session.get(NoteV2, first.id)
    second_row = port.session.get(NoteV2, second.id)
    first_row.attachments.append(attachment)
    second_row.attachments.append(attachment)
    port.session.commit()

    assert len(port.list_attachments(first.id)) == 1
    port.delete_note(first.id, permanent=True)
    assert len(port.list_attachments(second.id)) == 1
    assert port.session.get(AttachmentV2, "att_shared") is not None
    port.delete_note(second.id, permanent=True)
    assert port.session.get(AttachmentV2, "att_shared") is not None
