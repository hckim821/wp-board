"""Phase/Milestone 관리 팝업의 원자적 적용 — plan.md §0.4.

요청은 **팝업 표의 최종 상태**다. 부분 변경(diff)을 보내지 않는다.

* `phases` / `milestones` — 위→아래가 곧 보드의 블록 순서다. 기존 항목은 `id` 와
  (수정된) 이름을, 신규 항목은 `id: null` 과 이름을 담는다.
* `deleted_ids` — **명시적** 삭제 목록. 남길 것과 지울 것을 둘 다 적게 하는 것이
  요점이다. 목록에서 빠진 id 를 "삭제 의사" 로 해석하면, 화면이 낡은 상태에서
  보낸 요청 하나가 조용히 행을 지워 버린다. 그래서 `목록 + deleted_ids` 의 합집합이
  서버가 아는 집합과 **정확히** 같지 않으면 422 로 거부한다.
* `anchor_item_id` — 회색 행에서 시작한 생성 흐름. 신규가 정확히 1개일 때만.

번호를 요청에 담지 않는 것에 주의. 번호는 first-appearance 재계산(§2.2)이
블록 순서에서 파생하므로, 요청이 정하는 것은 **순서**뿐이다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .item import ItemOut
from .master import MilestoneOut, PhaseOut


class ApplyEntry(BaseModel):
    """표의 한 행. `id` 가 없으면 신규다.

    빈 이름은 `Field(min_length=...)` 로 막지 않는다. 공백만 있는 이름(`"  "`)이
    통과해 버리고, 무엇보다 오류 본문이 FastAPI 의 형식 오류 모양이라 이 모듈의
    `{code, message, ...}` 규약과 달라지기 때문이다. 판정은 서비스가 한다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str


class PhasesApplyIn(BaseModel):
    phases: list[ApplyEntry] = Field(default_factory=list)
    deleted_ids: list[int] = Field(default_factory=list)
    anchor_item_id: int | None = None


class MilestonesApplyIn(BaseModel):
    """대상 Phase 는 URL 로 온다 — 본문에 담지 않는다."""

    milestones: list[ApplyEntry] = Field(default_factory=list)
    deleted_ids: list[int] = Field(default_factory=list)
    anchor_item_id: int | None = None


class BoardOut(BaseModel):
    """apply 의 응답 — **전체 보드**.

    행 조작 엔드포인트의 `ItemListOut` 을 그대로 품고 기준정보 두 목록을 더한다.
    apply 는 기준정보 자체를 만들고 지우므로, 행만 돌려주면 팝업이 방금 생긴
    Phase 의 id 를 알 길이 없어 곧바로 두 번째 요청을 하게 된다. 한 번의 응답으로
    화면 전체가 교체되도록 함께 싣는다 (plan.md §0.4).
    """

    items: list[ItemOut]
    phases: list[PhaseOut]
    milestones: list[MilestoneOut]
