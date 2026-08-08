"""행(Item) 관련 스키마 — plan.md §4.3.

응답에 `is_*_block_start/end` 와 `can_create_*` 를 **서버가 계산해서** 담는다.
§2.3 의 경계 규칙이 셀 에디터마다 재구현되지 않도록, 판단은 서버 한 곳에만 둔다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ..models.base import ItemOrigin, ItemStatus


class DocumentRef(BaseModel):
    """행에 연결된 문서. **원문자 코드는 없다** (plan.md §0.5.10).

    `no` 는 **파생된 표시 번호**다 (§0.5.10 팝업 정밀화) — 저장된 `sort_order` 가
    아니라 **사용 중인 문서만 세어** 매긴 1..N 이다. 프로젝트에서 꺼진 문서는 이
    목록에 아예 실리지 않으므로 여기 `no` 는 언제나 정수다.

    예전의 `code`(①②)는 전역 문서 모델과 함께 폐기됐다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    no: int
    name: str


class OwnerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ItemOut(BaseModel):
    id: int
    sort_order: int
    #: 화면의 `No` 컬럼. 현재는 `sort_order` 와 같지만, 표시용과 저장용을 분리해
    #: 두면 나중에 "번호 없는 행" 같은 요구가 와도 응답 계약이 흔들리지 않는다.
    row_no: int

    phase_id: int | None = None
    phase_no: int | None = None
    phase_name: str | None = None
    phase_display: str | None = None

    milestone_id: int | None = None
    milestone_no: int | None = None
    milestone_name: str | None = None
    #: `0.1` — 앞자리는 소속 Phase 에서 파생한 값이다.
    milestone_no_display: str | None = None
    #: `0.1 DSEP 환경 Gap 및 자원 구성`
    milestone_display: str | None = None

    is_phase_block_start: bool
    is_phase_block_end: bool
    is_milestone_block_start: bool
    is_milestone_block_end: bool
    can_create_phase: bool
    can_create_milestone: bool

    title: str | None = None
    deliverable: str | None = None
    #: 대시보드 카드에 실리는 요약 단어 (plan.md §0.5-1). `null` 이 정상이며,
    #: 폴백(deliverable → title 앞부분)은 서버가 아니라 카드가 정한다 — 서버가
    #: 채워 내려주면 "라벨이 비어 있다" 는 사실이 응답에서 사라져 그리드의
    #: 편집 컬럼이 무엇을 저장해야 할지 알 수 없게 된다.
    dash_label: str | None = None
    gate_code: str | None = None
    documents: list[DocumentRef] = Field(default_factory=list)
    owners: list[OwnerRef] = Field(default_factory=list)
    status: ItemStatus = ItemStatus.NOT_STARTED
    completion_date: date | None = None
    origin: ItemOrigin = ItemOrigin.INHERITED


class ItemSaveIn(BaseModel):
    """임시저장(bulk replace)의 행 1건.

    `sort_order` 를 보내면 **그 값이 순서의 정본**이고, 배열 순서는 무시한다.
    전부 생략하면 배열 순서를 쓴다. 섞어 보내면 400 이다.

    왜 굳이 둘 다 받는가: 클라이언트가 `sort_order` 를 실어 보내는데 서버가
    배열 순서만 보면, 갱신되지 않은 낡은 `sort_order` 가 조용히 무시되거나
    반대로 직전 reorder 를 되돌려 버린다. 어느 쪽이 정본인지 애매한 상태를
    남기지 않으려고 명시적으로 정한다.

    `id` 가 `null` 이면 신규 행으로 만든다.
    """

    id: int | None = None
    sort_order: int | None = None
    phase_id: int | None = None
    milestone_id: int | None = None
    title: str | None = None
    deliverable: str | None = None
    dash_label: str | None = Field(default=None, max_length=60)
    gate_code: str | None = None
    status: ItemStatus = ItemStatus.NOT_STARTED
    completion_date: date | None = None
    document_ids: list[int] = Field(default_factory=list)
    owner_ids: list[int] = Field(default_factory=list)


class ItemsSaveIn(BaseModel):
    """임시저장 — 전량 교체. 목록에 없는 기존 행은 삭제된다."""

    items: list[ItemSaveIn] = Field(default_factory=list)


class ItemInsertIn(BaseModel):
    """행 추가.

    `phase_id` / `milestone_id` 를 받지 않는 것은 의도다. 신규 행은 기준 행의
    phase/milestone 을 **그대로 상속**해야 블록 연속성이 자동으로 보장된다
    (plan.md §2.2).
    """

    title: str | None = None
    deliverable: str | None = None
    dash_label: str | None = Field(default=None, max_length=60)
    gate_code: str | None = None
    status: ItemStatus = ItemStatus.NOT_STARTED
    completion_date: date | None = None
    document_ids: list[int] = Field(default_factory=list)
    owner_ids: list[int] = Field(default_factory=list)


class ReorderIn(BaseModel):
    """**위치만** 변경한다 (드래그) — plan.md §4.2.

    `item_ids` 는 그 버전의 전체 행을 새 순서로 빠짐없이 한 번씩 담는다.
    **이 필드가 전부다.**

    소속(phase/milestone)을 받지 않을 뿐 아니라, 서버가 다시 유도하지도 않는다.
    각 행은 자기 소속을 그대로 들고 자리만 바꾼다 (§2.2). 그래서 어느 행이
    끌렸는지 서버가 알 필요가 없고, `moved_item_id` 도 더 이상 받지 않는다 —
    아무것도 재유도하지 않는 연산에서 그 값은 의미가 없다.

    소속 변경은 `membership` 엔드포인트로 분리되어 있다. 두 연산을 합치면
    "안전한 경로" 가 선택 파라미터에 의존하게 되고, 그 파라미터를 빠뜨린
    클라이언트가 조용히 약한 경로로 떨어진다.
    """

    item_ids: list[int]


class MembershipIn(BaseModel):
    """**소속만** 변경한다 (§2.3 셀 편집).

    서버가 행을 대상 블록 끝으로 옮긴다. 위치를 클라이언트가 계산하지 않는다 —
    그 판단이야말로 §2.3 이 서버에 두려는 것이다.
    """

    phase_id: int | None = None
    milestone_id: int | None = None


class PhaseFromRowIn(BaseModel):
    """기준 행에서 새 Phase 를 만든다 (§2.3).

    기준 행은 **경로**로 받는다 (`/items/{iid}/create-phase`).

    **삽입 위치를 받지 않는 것이 핵심이다.** 기준 행은 목록에서 제자리를 지키고
    `phase_id` 만 바뀌므로, 새 Phase 가 기존 블록 앞에 생기는지 뒤에 생기는지는
    기준 행이 어느 경계에 있었는지에서 자동으로 따라 나온다. 위치를 따로 받으면
    §2.3 규칙에 정본이 둘 생긴다.

    기준 행이 블록 중간이면(`can_create_phase == false`) 422 로 거부한다.
    """

    name: str = Field(min_length=1, max_length=200)


class MilestoneFromRowIn(BaseModel):
    """기준 행에서 새 Milestone 을 만든다. 소속 Phase 는 기준 행의 것을 쓴다.

    기준 행에 `phase_id` 가 없으면 422 (`PHASE_REQUIRED`).
    """

    name: str = Field(min_length=1, max_length=255)


class ItemListOut(BaseModel):
    """행 조작 API 의 공통 응답 — **재계산된 전체 행 목록**.

    부분 갱신 대신 전체를 돌려주므로 프론트는 그대로 교체하면 되고,
    클라이언트/서버 상태가 어긋날 여지가 없다 (plan.md §4.2 설계 원칙).
    """

    items: list[ItemOut]
