"""행 조작 API — plan.md §4.2 "행 조작".

모든 엔드포인트가 **재계산된 전체 행 목록**을 돌려준다. 프론트는 응답으로
통째로 교체하면 되므로 클라이언트/서버 상태가 어긋날 여지가 없다.

**위치 변경과 소속 변경은 분리되어 있다.**

| 엔드포인트 | 소속 | 연속성 |
|---|---|---|
| `reorder` | **절대 안 바뀐다** — 행이 자기 소속을 들고 자리만 옮긴다 | 블록 내부 순열이면 정의상 연속. 블록을 가로지르면 422 |
| `membership` | 요청이 지정 | 서버가 옮긴 뒤 검사, 위반 시 422 |

합치면 "안전한 경로" 가 선택 파라미터에 의존하게 되고, 호스트 프로젝트의 다른
클라이언트가 그걸 빠뜨리면 조용히 약한 경로로 떨어진다. 안전이 기본값이 아니라
옵트인이 되는 구조는 이 저장소가 피하려는 결함 그 자체다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.exceptions import WpAPIRoute
from ...deps import WpDeps
from ...schemas.item import (
    ItemInsertIn,
    ItemListOut,
    MembershipIn,
    MilestoneFromRowIn,
    PhaseFromRowIn,
    ReorderIn,
)
from ...services import item_service, version_service
from .apply import mount_board_apply


def build_router(deps: WpDeps) -> APIRouter:
    router = APIRouter(route_class=WpAPIRoute, tags=["items"])
    session_dep = Depends(deps.session)

    def _editable(session: Session, version_id: int):
        """쓰기 경로의 입구 — 버전 행을 **잠근 뒤** 상태를 확인한다.

        보드를 함께 돌려준다. `item_service` 는 `Version` 을 모르고 `Board` 만
        받으므로 (plan.md §0.1 — 템플릿·프로젝트가 같은 구현을 공유한다).
        """
        version = version_service.lock_editable_version(session, version_id)
        return version, version_service.board_of(session, version)

    def _recomputed(session: Session, version_id: int) -> ItemListOut:
        version = version_service.get_version(session, version_id)
        board = version_service.board_of(session, version)
        items = item_service.load_ordered_items(session, board)
        return ItemListOut(
            items=item_service.build_item_views(
                session, board, items
            )
        )

    @router.post("/versions/{version_id}/items", response_model=ItemListOut, status_code=201)
    def append_item(
        version_id: int,
        payload: ItemInsertIn | None = None,
        session: Session = session_dep,
    ):
        """목록 맨 끝에 빈 행을 추가한다.

        `insert-below` 는 기준 행을 요구하므로 **행이 0개인 버전**에는 첫 행을
        넣을 수 없다. 그 경우의 진입점이다.
        """
        _version, board = _editable(session, version_id)
        item_service.append_item(
            session, board, payload or ItemInsertIn()
        )
        session.commit()
        return _recomputed(session, version_id)

    @router.post("/versions/{version_id}/items/{item_id}/insert-below", response_model=ItemListOut)
    def insert_below(
        version_id: int,
        item_id: int,
        payload: ItemInsertIn | None = None,
        session: Session = session_dep,
    ):
        """기준 행 바로 아래에 행 추가 (phase/milestone 상속)."""
        _version, board = _editable(session, version_id)
        item_service.insert_below(
            session, board, item_id, payload or ItemInsertIn(),
        )
        session.commit()
        return _recomputed(session, version_id)

    @router.post("/versions/{version_id}/items/{item_id}/create-phase", response_model=ItemListOut)
    def create_phase_from_row(
        version_id: int, item_id: int, payload: PhaseFromRowIn, session: Session = session_dep
    ):
        """경계 행에서 새 Phase 생성 (§2.3) — 생성 + 배정 + 재계산이 한 트랜잭션.

        삽입 위치를 받지 않는다. 기준 행이 제자리를 지킨 채 소속만 바뀌므로
        앞/뒤는 그 행이 어느 경계에 있었는지에서 저절로 정해진다.
        블록 중간 행이면 422 (`PHASE_BOUNDARY_VIOLATION`).
        """
        _version, board = _editable(session, version_id)
        item_service.create_phase_from_row(session, board, item_id, payload.name)
        session.commit()
        return _recomputed(session, version_id)

    @router.post(
        "/versions/{version_id}/items/{item_id}/create-milestone", response_model=ItemListOut
    )
    def create_milestone_from_row(
        version_id: int, item_id: int, payload: MilestoneFromRowIn, session: Session = session_dep
    ):
        """경계 행에서 새 Milestone 생성. 소속 Phase 는 기준 행의 것.

        기준 행에 Phase 가 없으면 422 (`PHASE_REQUIRED`).
        """
        _version, board = _editable(session, version_id)
        item_service.create_milestone_from_row(session, board, item_id, payload.name)
        session.commit()
        return _recomputed(session, version_id)

    @router.post("/versions/{version_id}/items/reorder", response_model=ItemListOut)
    def reorder_items(version_id: int, payload: ReorderIn, session: Session = session_dep):
        """**위치만** 변경 (드래그) + 재계산.

        각 행은 자기 phase/milestone 을 그대로 유지한다. 드래그로 행의 분류가
        바뀌는 일은 없다 (§2.2). 블록을 가로지르는 순서는 422 로 거부한다.
        """
        _version, board = _editable(session, version_id)
        item_service.reorder(session, board, payload.item_ids)
        session.commit()
        return _recomputed(session, version_id)

    @router.patch("/versions/{version_id}/items/{item_id}/membership", response_model=ItemListOut)
    def change_membership(
        version_id: int, item_id: int, payload: MembershipIn, session: Session = session_dep
    ):
        """**소속만** 변경 (§2.3 셀 편집) + 이동 + 재계산.

        중간 행이어도 거부하지 않는다 — §2.3 이 정한 대로 **대상 블록 끝으로
        서버가 옮긴다.** 422 는 정말로 불가능한 요청에만 쓴다.
        """
        _version, board = _editable(session, version_id)
        item_service.change_membership(
            session, board, item_id, payload.phase_id, payload.milestone_id
        )
        session.commit()
        return _recomputed(session, version_id)

    @router.delete("/versions/{version_id}/items/{item_id}", response_model=ItemListOut)
    def delete_item(version_id: int, item_id: int, session: Session = session_dep):
        """행 삭제 + 재계산. 비게 된 Phase/Milestone 의 번호는 사라지고 뒤가 당겨진다."""
        _version, board = _editable(session, version_id)
        item_service.delete_item(session, board, item_id)
        session.commit()
        return _recomputed(session, version_id)

    # Phase/Milestone 관리 팝업의 원자적 적용 (§0.4). `resolve` 가 `_editable` 이므로
    # PUBLISHED/ARCHIVED 는 다른 쓰기 경로와 똑같이 409 로 막힌다 — 새 상태 관문을
    # 만들지 않는다.
    mount_board_apply(
        router,
        deps,
        prefix="/versions",
        param="version_id",
        resolve=lambda session, version_id: _editable(session, version_id)[1],
    )

    return router
