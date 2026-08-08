"""문서 스키마 — plan.md §0.5.10.

두 계층이 **같은 모양**을 쓴다. 다른 것은 프로젝트 쪽에만 사용여부·링크·작성
상태가 더 있다는 점뿐이다 — 문서 자체(이름·순서)는 같은 개념이다.

`no` 는 `sort_order` 이며 표시 번호다. 원문자 코드(①②)는 전역 문서 모델과 함께
폐기됐다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models.base import ProjectDocStatus
from .item import ItemOut


class TemplateDocumentOut(BaseModel):
    id: int
    no: int
    name: str
    is_active: bool = True


class TemplateDocumentListOut(BaseModel):
    documents: list[TemplateDocumentOut] = Field(default_factory=list)
    #: 삭제 캐스케이드로 항목 링크가 바뀌므로 **재계산된 행 목록**을 함께 준다
    #: (§0.5.10). 저장 뒤 그리드가 따로 다시 읽지 않아도 되게 하려는 것이다.
    items: list[ItemOut] = Field(default_factory=list)


class DocumentApplyEntry(BaseModel):
    """`id` 가 `null` 이면 신규. **`no` 를 받지 않는다** — 배열 위치가 정본이다."""

    id: int | None = None
    name: str = Field(max_length=200)


class DocumentApplyIn(BaseModel):
    """팝업 표의 최종 상태. `phases/apply` 와 같은 형태다.

    `documents` + `deleted_ids` 가 기존 전체 집합과 정확히 일치해야 한다 —
    화면이 보지 못한 문서를 조용히 남기거나 지우지 않기 위해서다.
    """

    documents: list[DocumentApplyEntry] = Field(default_factory=list)
    deleted_ids: list[int] = Field(default_factory=list)
