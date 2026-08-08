"""기준정보 CRUD — plan.md §2.6.

**삭제 정책이 이 모듈의 핵심이다.** 사용 중인 기준정보는 hard delete 하지 않는다.
사용처가 있으면 `is_active=false` 로 비활성화만 하고, 사용 건수를 함께 돌려준다.
사용처가 없을 때만 실제로 지운다. 스키마의 `ON DELETE RESTRICT` 가 마지막
방어선이지만, 사용자에게는 여기서 만든 친절한 응답이 먼저 닿는다.

스코프는 두 종류다 (plan.md §0.1).

* **전역** — `DocumentType`. 두 계층이 같은 행을 공유하며 복제하지 않는다.
* **보드 스코프** — `Phase` / `Milestone` / `Owner`. 템플릿에는 템플릿 set 이,
  프로젝트에는 생성 시 복제된 **로컬 사본**이 있다. 두 경우의 CRUD 는 테이블만
  다르고 규칙이 같으므로 `Board` 를 받아 한 벌로 처리한다.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.exceptions import BadRequestError, ConflictError, NotFoundError
from ..schemas.master import DeleteResultOut
from .board import Board


def _count(session: Session, stmt) -> int:
    return int(session.scalar(stmt) or 0)


def _deleted(entity_id: int) -> DeleteResultOut:
    return DeleteResultOut(
        id=entity_id, deleted=True, deactivated=False, usage_count=0, message="삭제했습니다."
    )


def _deactivated(entity_id: int, usage: int) -> DeleteResultOut:
    return DeleteResultOut(
        id=entity_id,
        deleted=False,
        deactivated=True,
        usage_count=usage,
        message=f"{usage}건에서 사용 중이라 삭제하지 않고 비활성화했습니다.",
    )


# =============================================================================
# 보드 스코프: Owner / Phase / Milestone — 템플릿과 프로젝트가 공유한다
# =============================================================================
#
# 어느 테이블을 볼지는 `board.spec` 이, 어느 행을 볼지는 `board.master_scope_id`
# 가 정한다. 두 계층의 CRUD 가 한 벌이므로 삭제 정책(사용 중이면 비활성화)이
# 양쪽에서 자동으로 같아진다 — 두 벌이면 한쪽만 고쳐지고 조용히 갈라진다.
#
def _scoped(board: Board, model: type):
    return board.spec.master_scope(model) == board.master_scope_id


def _owned_by(board: Board, entity) -> bool:
    return getattr(entity, board.spec.master_scope_attr) == board.master_scope_id


# ----------------------------------------------------------------------- Owner
def list_owners(session: Session, board: Board) -> list:
    owner = board.spec.owner_cls
    return list(
        session.scalars(
            select(owner).where(_scoped(board, owner)).order_by(owner.sort_order, owner.id)
        )
    )


def _get_owner(session: Session, board: Board, owner_id: int):
    entity = session.get(board.spec.owner_cls, owner_id)
    if entity is None or not _owned_by(board, entity):
        raise NotFoundError(
            f"Owner {owner_id} 을(를) 이 {board.spec.scope_label}에서 찾을 수 없습니다."
        )
    return entity


def create_owner(session: Session, board: Board, data):
    entity = board.spec.owner_cls(
        **{board.spec.master_scope_attr: board.master_scope_id},
        name=data.name,
        sort_order=data.sort_order,
    )
    session.add(entity)
    session.flush()
    return entity


def update_owner(session: Session, board: Board, owner_id: int, data):
    entity = _get_owner(session, board, owner_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    session.flush()
    return entity


def delete_owner(session: Session, board: Board, owner_id: int) -> DeleteResultOut:
    entity = _get_owner(session, board, owner_id)
    link = board.spec.item_owner_cls
    usage = _count(
        session, select(func.count()).select_from(link).where(link.owner_id == owner_id)
    )
    if usage:
        entity.is_active = 0
        session.flush()
        return _deactivated(owner_id, usage)
    session.delete(entity)
    session.flush()
    return _deleted(owner_id)


# ----------------------------------------------------------------------- Phase
def list_phases(session: Session, board: Board) -> list:
    phase = board.spec.phase_cls
    return list(
        session.scalars(
            select(phase).where(_scoped(board, phase)).order_by(phase.seq_no, phase.id)
        )
    )


def _get_phase(session: Session, board: Board, phase_id: int):
    entity = session.get(board.spec.phase_cls, phase_id)
    if entity is None or not _owned_by(board, entity):
        raise NotFoundError(
            f"Phase {phase_id} 을(를) 이 {board.spec.scope_label}에서 찾을 수 없습니다."
        )
    return entity


def create_phase(session: Session, board: Board, data):
    phase = board.spec.phase_cls
    seq_no = data.seq_no
    if seq_no is None:
        seq_no = _count(session, select(func.max(phase.seq_no)).where(_scoped(board, phase))) + 1
    entity = phase(
        **{board.spec.master_scope_attr: board.master_scope_id}, name=data.name, seq_no=seq_no
    )
    session.add(entity)
    session.flush()
    return entity


def update_phase(session: Session, board: Board, phase_id: int, data):
    entity = _get_phase(session, board, phase_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    session.flush()
    return entity


def delete_phase(session: Session, board: Board, phase_id: int) -> DeleteResultOut:
    entity = _get_phase(session, board, phase_id)
    item, milestone = board.spec.item_cls, board.spec.milestone_cls
    # 하위 Milestone 도 사용처로 친다. Phase 를 지우면 CASCADE 로 Milestone 이
    # 함께 사라지는데, 그 Milestone 을 쓰는 행이 있으면 안 되기 때문이다.
    usage = _count(
        session, select(func.count()).select_from(item).where(item.phase_id == phase_id)
    ) + _count(
        session,
        select(func.count())
        .select_from(item)
        .join(milestone, milestone.id == item.milestone_id)
        .where(milestone.phase_id == phase_id),
    )
    if usage:
        entity.is_active = 0
        session.flush()
        return _deactivated(phase_id, usage)
    session.delete(entity)
    session.flush()
    return _deleted(phase_id)


# ------------------------------------------------------------------- Milestone
def list_milestones(session: Session, board: Board, phase_id: int | None = None) -> list:
    milestone = board.spec.milestone_cls
    stmt = select(milestone).where(_scoped(board, milestone))
    if phase_id is not None:
        stmt = stmt.where(milestone.phase_id == phase_id)
    return list(session.scalars(stmt.order_by(milestone.phase_id, milestone.seq_no, milestone.id)))


def _get_milestone(session: Session, board: Board, milestone_id: int):
    entity = session.get(board.spec.milestone_cls, milestone_id)
    if entity is None or not _owned_by(board, entity):
        raise NotFoundError(
            f"Milestone {milestone_id} 을(를) 이 {board.spec.scope_label}에서 찾을 수 없습니다."
        )
    return entity


def create_milestone(session: Session, board: Board, data):
    _get_phase(session, board, data.phase_id)      # 소속 Phase 가 같은 보드인지 확인
    milestone = board.spec.milestone_cls
    seq_no = data.seq_no
    if seq_no is None:
        seq_no = (
            _count(
                session,
                select(func.max(milestone.seq_no)).where(milestone.phase_id == data.phase_id),
            )
            + 1
        )
    entity = milestone(
        **{board.spec.master_scope_attr: board.master_scope_id},
        phase_id=data.phase_id,
        name=data.name,
        seq_no=seq_no,
    )
    session.add(entity)
    session.flush()
    return entity


def milestone_usage_count(session: Session, board: Board, milestone_id: int) -> int:
    item = board.spec.item_cls
    return _count(
        session, select(func.count()).select_from(item).where(item.milestone_id == milestone_id)
    )


def update_milestone(session: Session, board: Board, milestone_id: int, data):
    """이름 수정은 허용하되, **사용 중인 Milestone 의 소속 Phase 변경은 거부한다.**

    plan.md §2.4 의 원칙: 발행된 버전의 유효성은 변경 가능한 기준정보에 의존해서는
    안 된다. 이름 수정 같은 표시용 변경은 전파되어도 좋지만, 소속 Phase 를 바꾸면
    이미 발행된 버전이 `MILESTONE_PHASE_MISMATCH` 로 조용히 무효가 된다 —
    사용자는 기준정보 화면만 만졌는데 과거 버전이 깨지는 셈이다.

    프로젝트에는 발행된 버전이 없지만 규칙은 그대로 둔다. 사용 중인 Milestone 의
    Phase 를 바꾸면 그 자리에서 보드가 조각나므로(§2.2 연속성), 막아야 할 이유는
    계층과 무관하게 성립한다.
    """
    entity = _get_milestone(session, board, milestone_id)
    patch = data.model_dump(exclude_unset=True)

    new_phase_id = patch.get("phase_id")
    if new_phase_id is not None and new_phase_id != entity.phase_id:
        _get_phase(session, board, new_phase_id)
        usage = milestone_usage_count(session, board, milestone_id)
        if usage:
            raise ConflictError(
                f"{usage}개 행이 사용 중인 Milestone 의 소속 Phase 는 변경할 수 없습니다. "
                "발행된 버전이 무효가 됩니다.",
                detail={"milestone_id": milestone_id, "usage_count": usage, "field": "phase_id"},
            )

    for key, value in patch.items():
        setattr(entity, key, value)
    session.flush()
    return entity


def delete_milestone(session: Session, board: Board, milestone_id: int) -> DeleteResultOut:
    entity = _get_milestone(session, board, milestone_id)
    usage = milestone_usage_count(session, board, milestone_id)
    if usage:
        entity.is_active = 0
        session.flush()
        return _deactivated(milestone_id, usage)
    session.delete(entity)
    session.flush()
    return _deleted(milestone_id)


# =============================================================================
# 표시 문자열 조합 (번호 + 이름) — 프론트가 조합 로직을 갖지 않도록 서버가 만든다
# =============================================================================
def phase_display(phase) -> str:
    return f"Phase {phase.seq_no}. {phase.name}"


def milestone_no_display(milestone, phase) -> str:
    major = phase.seq_no if phase is not None else "?"
    return f"{major}.{milestone.seq_no}"


def milestone_display(milestone, phase) -> str:
    return f"{milestone_no_display(milestone, phase)} {milestone.name}"
