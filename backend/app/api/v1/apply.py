"""Phase/Milestone 관리 팝업의 적용 엔드포인트 — plan.md §0.4.

```
POST /versions/{version_id}/phases/apply
POST /versions/{version_id}/phases/{phase_id}/milestones/apply
POST /projects/{project_id}/phases/apply
POST /projects/{project_id}/phases/{phase_id}/milestones/apply
```

네 개가 **한 구현**이다. `mount_scoped_master()` 와 같은 이유다 — 두 계층의
그리드 규칙이 같으므로 두 벌을 두면 한쪽만 고쳐지고 조용히 갈라진다. 계층 차이는
`resolve` 콜백이 흡수한다: 템플릿 쪽은 버전을 잠그고 DRAFT 인지 확인한 뒤 보드를
주고(PUBLISHED/ARCHIVED 는 거기서 409), 프로젝트 쪽은 존재 확인만 한다.

응답은 **전체 보드**다 (`BoardOut`). 행 조작 엔드포인트가 행 목록을 통째로
돌려주는 것과 같은 이유이며, apply 는 기준정보까지 만들고 지우므로 그 두 목록도
함께 싣는다 — 그러지 않으면 팝업이 방금 만든 Phase 의 id 를 알기 위해 곧바로
두 번째 요청을 하게 된다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...deps import WpDeps
from ...schemas.apply import BoardOut, MilestonesApplyIn, PhasesApplyIn
from ...services import apply_service, item_service, master_service
from ...services.board import Board
from .master import _milestone_out, _phase_out, _route


def board_out(session: Session, deps: WpDeps, board: Board) -> BoardOut:
    """행 + 기준정보 두 목록. 번호·경계 플래그는 `item_service` 가 붙인다."""
    items = item_service.load_ordered_items(session, board)
    phases = master_service.list_phases(session, board)
    by_id = {p.id: p for p in phases}
    return BoardOut(
        items=item_service.build_item_views(
            session, board, items
        ),
        phases=[_phase_out(p) for p in phases],
        milestones=[
            _milestone_out(m, by_id.get(m.phase_id))
            for m in master_service.list_milestones(session, board)
        ],
    )


def mount_board_apply(router: APIRouter, deps: WpDeps, *, prefix: str, param: str, resolve) -> None:
    """apply 2종을 `router` 에 단다.

    Args:
        prefix: `/versions` 또는 `/projects`.
        param: 경로 파라미터 이름. 핸들러는 `scope_id` 로 쓰고 등록 직전에
            `__signature__` 를 갈아 끼운다 (`master._route`).
        resolve: `(session, scope_id) -> Board`. **쓰기 관문이 여기 있다** —
            템플릿 쪽은 이 콜백이 버전을 잠그고 DRAFT 를 확인한다.
    """
    session_dep = Depends(deps.session)
    base = f"{prefix}/{{{param}}}"

    @_route(router.post, param)(
        f"{base}/phases/apply", response_model=BoardOut, name=f"{param}_apply_phases"
    )
    def apply_phases(scope_id: int, payload: PhasesApplyIn, session: Session = session_dep):
        """Phase 팝업의 최종 상태를 원자적으로 반영한다.

        표의 위→아래가 곧 블록 순서이고, 번호는 재계산(§2.2)이 파생한다.
        """
        board = resolve(session, scope_id)
        apply_service.apply_phases(session, board, payload)
        session.commit()
        return board_out(session, deps, board)

    @_route(router.post, param)(
        f"{base}/phases/{{phase_id}}/milestones/apply",
        response_model=BoardOut,
        name=f"{param}_apply_milestones",
    )
    def apply_milestones(
        scope_id: int, phase_id: int, payload: MilestonesApplyIn, session: Session = session_dep
    ):
        """해당 Phase 안의 Milestone 팝업을 원자적으로 반영한다."""
        board = resolve(session, scope_id)
        apply_service.apply_milestones(session, board, phase_id, payload)
        session.commit()
        return board_out(session, deps, board)
