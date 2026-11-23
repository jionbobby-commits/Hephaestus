"""Physical V2 schema (B1.1/B1.2).

All tables are v2_-prefixed. Legacy notes/frontend_state remain untouched so
the V1 API and /api/state can keep serving old clients during migration.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class V2Base(DeclarativeBase):
    pass


v2_note_tags = Table(
    "v2_note_tags",
    V2Base.metadata,
    Column("note_id", String(64), ForeignKey("v2_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String(64), ForeignKey("v2_tags.id", ondelete="CASCADE"), primary_key=True),
)


v2_note_attachments = Table(
    "v2_note_attachments",
    V2Base.metadata,
    Column("note_id", String(64), ForeignKey("v2_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("attachment_id", String(64), ForeignKey("v2_attachments.id", ondelete="CASCADE"), primary_key=True),
)


class NoteV2(V2Base):
    __tablename__ = "v2_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    favorited_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trashed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extra_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    tags: Mapped[list["TagV2"]] = relationship(
        secondary=v2_note_tags, lazy="selectin", order_by="TagV2.created_at",
    )
    attachments: Mapped[list["AttachmentV2"]] = relationship(
        secondary=v2_note_attachments, lazy="selectin", order_by="AttachmentV2.created_at",
    )


class TagV2(V2Base):
    __tablename__ = "v2_tags"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#8b8f94")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AttachmentV2(V2Base):
    __tablename__ = "v2_attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AppSettingV2(V2Base):
    __tablename__ = "v2_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AIProviderConfigV2(V2Base):
    __tablename__ = "v2_ai_providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    extra_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class SchemaMigrationV2(V2Base):
    __tablename__ = "v2_schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[str] = mapped_column(String(40), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)


class ImportMetaV2(V2Base):
    __tablename__ = "v2_import_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
