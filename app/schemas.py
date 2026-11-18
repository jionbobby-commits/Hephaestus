from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class NoteBase(BaseModel):
    title: str = Field(max_length=100)
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
    pass


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
