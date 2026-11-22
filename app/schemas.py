from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(default="", max_length=10000)
    category: str = Field(default="未分类", max_length=30)

    @field_validator("title")
    @classmethod
    def check_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空白")
        return value

    @field_validator("category")
    @classmethod
    def check_category(cls, value: str) -> str:
        return value.strip() or "未分类"


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, max_length=30)
    is_favorite: bool | None = None

    @field_validator("title")
    @classmethod
    def check_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空白")
        return value

    @field_validator("category")
    @classmethod
    def check_category(cls, value: str | None) -> str | None:
        return value.strip() or "未分类" if value is not None else None

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的字段")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("更新字段不能为 null")
        return self


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class NoteRead(BaseModel):
    id: int
    title: str
    content: str
    category: str
    is_favorite: bool
    created_at: datetime
    updated_at: datetime


class NoteList(BaseModel):
    items: list[NoteRead]
    total: int
    page: int
    page_size: int


class FrontendStatePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    notes: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    ui: dict[str, Any] = Field(default_factory=dict)
