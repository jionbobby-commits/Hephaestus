from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NoteBase(BaseModel):
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
        value = value.strip()
        return value or "未分类"


class NoteCreate(NoteBase):
    pass


class NoteUpdate(NoteBase):
    is_favorite: bool = False


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
