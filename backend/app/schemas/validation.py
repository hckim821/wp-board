"""검증 응답 — plan.md §2.5 의 형식 그대로.

`item_id` / `row_no` / `field` 위치 정보를 담아 그리드가 해당 셀을 바로
하이라이트할 수 있게 한다. 값이 없는 위치 필드는 응답에서 생략된다
(`response_model_exclude_none=True`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ValidationIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    level: str
    message: str
    item_id: int | None = None
    row_no: int | None = None
    field: str | None = None
    phase_id: int | None = None
    milestone_id: int | None = None


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    valid: bool
    errors: list[ValidationIssueOut] = Field(default_factory=list)
    warnings: list[ValidationIssueOut] = Field(default_factory=list)
