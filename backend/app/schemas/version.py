from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.base import VersionStatus
from .item import ItemOut


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    version_number: int
    status: VersionStatus
    source_version_id: int | None = None
    #: 발행 시점에 고정된 표시 번호 시작값 (plan.md §2.4). DRAFT 는 `null` 이며
    #: 그동안은 템플릿의 현재 값을 따른다.
    phase_start_no: int | None = None
    notes: str | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None
    created_by: str | None = None
    published_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: DRAFT 만 편집 가능. 프론트가 읽기전용 모드를 켜는 근거.
    is_editable: bool = False


class VersionDetailOut(BaseModel):
    """그리드 로드용 — 버전 + 재계산된 전체 행."""

    version: VersionOut
    items: list[ItemOut] = Field(default_factory=list)


class DraftCreateIn(BaseModel):
    """draft 발행. 현재 PUBLISHED 를 deep copy 한다 (없으면 빈 v1)."""

    created_by: str | None = None
    notes: str | None = None


class PublishIn(BaseModel):
    published_by: str | None = None
    notes: str | None = None
