"""기준정보 스키마.

삭제 정책 (plan.md §2.6): 사용 중인 기준정보는 **hard delete 금지**.
`DELETE` 는 사용 건수를 함께 반환하고, 사용처가 있으면 비활성화만 수행한다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models.base import ItemStatus


# --- 전역: Document Type ------------------------------------------------------
class OwnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    #: 스코프 — **둘 중 하나만 채워진다** (plan.md §0.1).
    #: 템플릿 기준정보면 `template_id`, 프로젝트 로컬 사본이면 `project_id`.
    #: 두 계층이 같은 응답 모델을 쓰므로 어느 쪽 것인지 응답만 보고 알 수 있어야 한다.
    template_id: int | None = None
    project_id: int | None = None
    name: str
    sort_order: int = 0
    is_active: bool = True


class OwnerCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class OwnerUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    is_active: bool | None = None


# --- 보드 스코프: Phase ---------------------------------------------------------
class PhaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    #: 스코프 — **둘 중 하나만 채워진다** (plan.md §0.1).
    #: 템플릿 기준정보면 `template_id`, 프로젝트 로컬 사본이면 `project_id`.
    #: 두 계층이 같은 응답 모델을 쓰므로 어느 쪽 것인지 응답만 보고 알 수 있어야 한다.
    template_id: int | None = None
    project_id: int | None = None
    #: 번호를 뺀 순수 이름
    name: str
    seq_no: int = 0
    is_active: bool = True
    #: `Phase 0. Pre-Infrastructure Setup` — 조합해서 내려준다.
    display: str | None = None


class PhaseCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    seq_no: int | None = None


class PhaseUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    seq_no: int | None = None
    is_active: bool | None = None


# --- 보드 스코프: Milestone -----------------------------------------------------
class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    #: 스코프 — **둘 중 하나만 채워진다** (plan.md §0.1).
    #: 템플릿 기준정보면 `template_id`, 프로젝트 로컬 사본이면 `project_id`.
    #: 두 계층이 같은 응답 모델을 쓰므로 어느 쪽 것인지 응답만 보고 알 수 있어야 한다.
    template_id: int | None = None
    project_id: int | None = None
    phase_id: int
    name: str
    #: 표시번호의 **뒷자리만**. 앞자리는 소속 Phase 에서 파생한다.
    seq_no: int = 0
    is_active: bool = True
    #: `0.1` — 소속 Phase 의 seq_no 와 조합한 값
    no_display: str | None = None
    #: `0.1 DSEP 환경 Gap 및 자원 구성`
    display: str | None = None


class MilestoneCreateIn(BaseModel):
    phase_id: int
    name: str = Field(min_length=1, max_length=255)
    seq_no: int | None = None


class MilestoneUpdateIn(BaseModel):
    phase_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    seq_no: int | None = None
    is_active: bool | None = None


# --- 삭제 응답 ---------------------------------------------------------------
class DeleteResultOut(BaseModel):
    """삭제 시도 결과.

    `deleted=False` 면 사용 중이라 비활성화만 했다는 뜻이고, `usage_count` 가
    그 근거다 (plan.md §2.6).
    """

    id: int
    deleted: bool
    deactivated: bool
    usage_count: int
    message: str
