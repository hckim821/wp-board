from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TemplateOut(BaseModel):
    """WP 템플릿 — **중앙 기준 데이터** (plan.md §0.1).

    `maker_id` / `maker_name` 이 없다. 템플릿은 설비사에 매이지 않는다 — 설비사별
    인스턴스는 `Project` 이고, 호스트 설비사 참조는 그쪽에만 있다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    phase_start_no: int = 0
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TemplateCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    phase_start_no: int = 0


class TemplateUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    phase_start_no: int | None = None
    is_active: bool | None = None
