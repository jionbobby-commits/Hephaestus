from __future__ import annotations

import json
import re
from pathlib import Path

from app.v2.contracts import (
    AIProviderConfigRead,
    AppSettings,
    NotePage,
    NoteRead,
    TagRead,
)

FIXTURE = Path(__file__).resolve().parents[1] / "contracts" / "v2" / "contract_fixture.json"
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_shared_fixture_is_valid_for_python_contract():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["contract_version"] == "2.0"
    tag = TagRead.model_validate(data["tag"])
    note = NoteRead.model_validate(data["note"])
    settings = AppSettings.model_validate(data["settings"])
    provider = AIProviderConfigRead.model_validate(data["provider"])
    page = NotePage.model_validate(data["page"])

    assert tag.id == "tag_contract"
    assert note.tags[0].id == tag.id
    assert note.is_favorite is True and note.is_trashed is False
    assert note.revision == 3
    assert settings.theme == "dark" and settings.locale == "zh-CN"
    assert provider.has_key is False
    assert page.total == 0 and page.page_size == 20

    assert ISO_RE.match(note.created_at) and ISO_RE.match(note.updated_at)
    assert ISO_RE.match(tag.created_at) and ISO_RE.match(provider.created_at)

    dumped = note.model_dump()
    assert set(dumped) == {
        "id", "title", "content_html", "content_text", "category", "tags",
        "attachments", "is_favorite", "is_trashed", "favorited_at", "trashed_at",
        "created_at", "updated_at", "revision",
    }
    assert "key_ref" not in provider.model_dump()
    assert json.loads(note.model_dump_json())["id"] == note.id
