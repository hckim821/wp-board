"""행 조작 + 응답 조립 — **두 계층이 함께 쓴다.**

이 모듈이 지키는 약속

1. **서버가 순서의 최종 권한이다.** 삽입/이동/삭제 후에는 반드시
   `renumber_service.renumber()` 를 돌리고, 재계산된 **전체 행 목록**을 돌려준다.
   프론트는 응답으로 통째로 교체하면 되므로 상태가 어긋날 수 없다.
2. **표시 번호는 그 보드의 행 순서에서 파생한다.** 기준정보의 `seq_no` 를 읽어
   쓰지 않는다. 그래야 DRAFT 를 편집해도 PUBLISHED 버전의 번호가 흔들리지 않는다.
3. **소속은 절대 추측하지 않는다.** 행 추가는 회색 행을 만들고(§0.2), 드래그는
   소속을 들고 다니며(§2.2), 소속 변경은 `change_membership` 만 한다.

## 계층 중립 (plan.md §0.1)

함수들은 `Version` 도 `Project` 도 알지 못하고 `Board` 만 받는다 (`board.py`).
템플릿 버전과 프로젝트는 저장 위치만 다르고 그리드 규칙이 같으므로, 구현을 한 벌만
둔다. 두 벌이면 규칙이 조용히 갈라진다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.exceptions import BadRequestError, NotFoundError, UnprocessableEntityError
from ..models.base import ItemOrigin
from ..schemas.item import DocumentRef, ItemInsertIn, ItemOut, ItemSaveIn, OwnerRef
from .board import Board
from .document_numbering import display_numbers
from .renumber_service import (
    RenumberResult,
    RowRef,
    find_contiguity_breaks,
    renumber,
    reposition,
)


# =============================================================================
# 조회
# =============================================================================
def load_ordered_items(session: Session, board: Board) -> list:
    spec = board.spec
    stmt = (
        select(spec.item_cls)
        .where(spec.item_scope() == board.scope_id)
        .order_by(spec.item_cls.sort_order, spec.item_cls.id)
        .options(
            selectinload(spec.item_cls.documents), selectinload(spec.item_cls.owners)
        )
    )
    return list(session.scalars(stmt))


def to_row_refs(items: list) -> list[RowRef]:
    return [RowRef(item_id=i.id, phase_id=i.phase_id, milestone_id=i.milestone_id) for i in items]


def _masters(session: Session, board: Board) -> tuple[dict, dict, dict, dict]:
    """이 보드의 기준정보를 id → 엔티티로 모은다.

    §0.5.10 이후로 **문서도 여기 포함된다.** 예전에는 전역이라 주입된 리포지토리로
    따로 읽었는데, 포맷 종속이 되면서 Phase/Owner 와 같은 자리로 들어왔다.
    """
    spec = board.spec
    phases = {
        p.id: p
        for p in session.scalars(
            select(spec.phase_cls).where(spec.master_scope(spec.phase_cls) == board.master_scope_id)
        )
    }
    milestones = {
        m.id: m
        for m in session.scalars(
            select(spec.milestone_cls).where(
                spec.master_scope(spec.milestone_cls) == board.master_scope_id
            )
        )
    }
    owners = {
        o.id: o
        for o in session.scalars(
            select(spec.owner_cls).where(spec.master_scope(spec.owner_cls) == board.master_scope_id)
        )
    }
    # **정렬해서 읽는다** — 표시 번호가 이 순서를 훑으며 매겨진다 (§0.5.10).
    ordered_documents = list(
        session.scalars(
            select(spec.document_cls)
            .where(spec.master_scope(spec.document_cls) == board.master_scope_id)
            .order_by(spec.document_cls.sort_order, spec.document_cls.id)
        )
    )
    return phases, milestones, owners, ordered_documents


def build_item_views(session: Session, board: Board, items: list) -> list[ItemOut]:
    """행 목록을 API 응답 형태로 조립한다 (번호 · 경계 플래그 포함)."""
    phases, milestones, owners, ordered_documents = _masters(session, board)
    documents = {d.id: d for d in ordered_documents}
    # 표시 번호는 파생값이다. 프로젝트에서 꺼진 문서는 `None` 이 되고, 그 링크는
    # 아래에서 응답에 실리지 않는다 — 화면 어디에도 나오지 않는 문서이기 때문이다.
    numbers = display_numbers(ordered_documents)

    result = renumber(to_row_refs(items), phase_start_no=board.phase_start_no)

    views: list[ItemOut] = []
    for item, row in zip(items, result.rows):
        phase = phases.get(item.phase_id) if item.phase_id else None
        ms = milestones.get(item.milestone_id) if item.milestone_id else None

        phase_display = None
        if phase is not None and row.phase_no is not None:
            phase_display = f"Phase {row.phase_no}. {phase.name}"

        no_display = row.milestone_display_no()
        ms_display = f"{no_display} {ms.name}" if (ms is not None and no_display) else None

        views.append(
            ItemOut(
                id=item.id,
                sort_order=row.sort_order,
                row_no=row.sort_order,
                phase_id=item.phase_id,
                phase_no=row.phase_no,
                phase_name=phase.name if phase else None,
                phase_display=phase_display,
                milestone_id=item.milestone_id,
                milestone_no=row.milestone_no,
                milestone_name=ms.name if ms else None,
                milestone_no_display=no_display,
                milestone_display=ms_display,
                is_phase_block_start=row.is_phase_block_start,
                is_phase_block_end=row.is_phase_block_end,
                is_milestone_block_start=row.is_milestone_block_start,
                is_milestone_block_end=row.is_milestone_block_end,
                can_create_phase=row.can_create_phase,
                can_create_milestone=row.can_create_milestone,
                title=item.title,
                deliverable=item.deliverable,
                dash_label=item.dash_label,
                gate_code=item.gate_code,
                documents=[
                    DocumentRef(
                        id=getattr(d, board.spec.item_document_attr),
                        no=numbers[getattr(d, board.spec.item_document_attr)],
                        name=documents[getattr(d, board.spec.item_document_attr)].name,
                    )
                    for d in item.documents
                    if numbers.get(getattr(d, board.spec.item_document_attr)) is not None
                ],
                owners=[
                    OwnerRef(id=o.owner_id, name=owners[o.owner_id].name)
                    for o in item.owners
                    if o.owner_id in owners
                ],
                status=item.status,
                completion_date=item.completion_date,
                origin=item.origin,
            )
        )
    return views


# =============================================================================
# 재계산 반영
# =============================================================================
def renumber_and_persist(session: Session, board: Board, items: list) -> RenumberResult:
    """`items` 의 **리스트 순서**를 정본으로 삼아 번호를 다시 매긴다.

    기준정보의 `seq_no` 갱신 여부는 `board.sync_master_seq` 가 정한다. 템플릿은
    DRAFT 일 때만 갱신한다 — PUBLISHED/ARCHIVED 를 읽는 것만으로 기준정보가 바뀌면
    안 되기 때문이다. 프로젝트는 편집 가능한 상태가 하나뿐이라 항상 갱신한다.
    """
    result = renumber(to_row_refs(items), phase_start_no=board.phase_start_no)

    for item, row in zip(items, result.rows):
        if item.sort_order != row.sort_order:
            item.sort_order = row.sort_order

    if board.sync_master_seq:
        apply_master_seq(session, board, result)

    session.flush()
    return result


def apply_master_seq(session: Session, board: Board, result: RenumberResult) -> None:
    """재계산 결과를 기준정보의 `seq_no` 에 반영한다.

    **이 보드가 쓰지 않는 Phase/Milestone 에도 번호를 준다.** 사용 중인 것에만
    쓰면 나머지는 예전 값을 그대로 들고 있어 번호가 겹친다 (실제로 기준정보
    화면에 `P0=0, P2=0, P1=1, P3=1` 이 나왔다). 쓰이는 것들을 먼저 촘촘히 채우고,
    쓰이지 않는 것들은 그 뒤로 밀어 유일성을 유지한다.
    """
    spec = board.spec
    phases = list(
        session.scalars(
            select(spec.phase_cls)
            .where(spec.master_scope(spec.phase_cls) == board.master_scope_id)
            .order_by(spec.phase_cls.seq_no, spec.phase_cls.id)
        )
    )
    next_seq = max(result.phase_seq.values(), default=-1) + 1
    for phase in phases:
        seq = result.phase_seq.get(phase.id)
        if seq is None:                      # 이 보드가 쓰지 않는 Phase
            seq = next_seq
            next_seq += 1
        if phase.seq_no != seq:
            phase.seq_no = seq

    milestones = list(
        session.scalars(
            select(spec.milestone_cls)
            .where(spec.master_scope(spec.milestone_cls) == board.master_scope_id)
            .order_by(spec.milestone_cls.phase_id, spec.milestone_cls.seq_no, spec.milestone_cls.id)
        )
    )
    next_by_phase: dict[int, int] = {}
    for phase_id in {m.phase_id for m in milestones}:
        used = [result.milestone_seq[m.id] for m in milestones
                if m.phase_id == phase_id and m.id in result.milestone_seq]
        next_by_phase[phase_id] = max(used, default=0) + 1
    for ms in milestones:
        seq = result.milestone_seq.get(ms.id)
        if seq is None:
            seq = next_by_phase[ms.phase_id]
            next_by_phase[ms.phase_id] += 1
        if ms.seq_no != seq:
            ms.seq_no = seq


def resync_master_numbering(session: Session, board: Board) -> None:
    """기준정보 `seq_no` 를 이 보드의 행 순서에 다시 맞춘다.

    DRAFT 를 편집하면 기준정보의 `seq_no` 가 그 DRAFT 기준으로 갱신되는데,
    DRAFT 를 폐기하면 그 흔적이 남는다. 버전별 표시 번호는 각자의 행 순서에서
    파생하므로 화면 번호는 멀쩡하지만, **기준정보 자체에는 빈틈이 남아**
    V6/V7 이 남아 있는 PUBLISHED 버전을 두고 헛되이 오류를 낸다.
    폐기 후 남은 버전 기준으로 되돌려 그 상황을 막는다.

    (템플릿 계층 전용 상황이다. 프로젝트에는 폐기가 없다.)
    """
    items = load_ordered_items(session, board)
    result = renumber(to_row_refs(items), phase_start_no=board.phase_start_no)
    apply_master_seq(session, board, result)
    session.flush()


# =============================================================================
# 참조 무결성 (임시저장도 이것만은 통과시키지 않는다 — plan.md §2.5)
# =============================================================================
def _check_references(
    session: Session,
    board: Board,
    *,
    phase_ids: set[int],
    milestone_ids: set[int],
    owner_ids: set[int],
    document_ids: set[int],
) -> None:
    spec = board.spec
    scope = board.master_scope_id

    def _missing(model: type, ids: set[int]) -> set[int]:
        found = set(
            session.scalars(
                select(model.id).where(
                    model.id.in_(ids), spec.master_scope(model) == scope
                )
            )
        )
        return ids - found

    if phase_ids:
        missing = _missing(spec.phase_cls, phase_ids)
        if missing:
            # 다른 보드의 Phase 를 참조하는 경우도 여기서 걸린다. 기준정보는 보드
            # 스코프이므로 스코프를 넘는 참조는 존재하지 않는 것과 같다.
            raise BadRequestError(f"이 {spec.scope_label}에 없는 phase_id: {sorted(missing)}")

    if milestone_ids:
        missing = _missing(spec.milestone_cls, milestone_ids)
        if missing:
            raise BadRequestError(f"이 {spec.scope_label}에 없는 milestone_id: {sorted(missing)}")

    if owner_ids:
        missing = _missing(spec.owner_cls, owner_ids)
        if missing:
            raise BadRequestError(f"이 {spec.scope_label}에 없는 owner_id: {sorted(missing)}")

    if document_ids:
        # 문서도 보드 스코프다 (§0.5.10) — 남의 템플릿/프로젝트 문서를 링크할 수 없다.
        missing = _missing(spec.document_cls, document_ids)
        if missing:
            raise BadRequestError(f"이 {spec.scope_label}에 없는 document_id: {sorted(missing)}")


def _set_links(board: Board, item, document_ids: list[int], owner_ids: list[int]) -> None:
    """N:M 연결을 통째로 교체한다. 순서는 입력 순서를 그대로 보존한다."""
    seen_docs: list[int] = []
    for d in document_ids:
        if d not in seen_docs:
            seen_docs.append(d)
    seen_owners: list[int] = []
    for o in owner_ids:
        if o not in seen_owners:
            seen_owners.append(o)

    spec = board.spec
    item.documents = [
        spec.item_document_cls(**{spec.item_document_attr: d}, sort_order=i)
        for i, d in enumerate(seen_docs, start=1)
    ]
    item.owners = [
        spec.item_owner_cls(owner_id=o, sort_order=i)
        for i, o in enumerate(seen_owners, start=1)
    ]


def _new_item(board: Board, **kwargs):
    """이 보드의 행 하나를 만든다. 스코프 컬럼 이름이 계층마다 다르므로 여기서 붙인다."""
    return board.spec.item_cls(**{board.spec.item_scope_attr: board.scope_id}, **kwargs)


# =============================================================================
# 쓰기 연산
# =============================================================================
def assert_order_agrees(entries: list, label: str) -> None:
    """**배열 순서가 항상 정본이다.** `sort_order` 는 주장(assertion)으로만 취급한다.

    보내도 되지만, 배열 위치와 다르면 400 이다. 둘 중 하나를 이기게 하는 규칙은
    결국 정본이 둘이라는 뜻이고, 낡은 `sort_order` 가 조용히 직전 reorder 를
    되돌려도 아무도 눈치채지 못한다. 불일치를 소리내어 거부하는 편이 낫다.
    """
    for index, entry in enumerate(entries, start=1):
        declared = getattr(entry, "sort_order", None)
        if declared is not None and declared != index:
            raise BadRequestError(
                f"{label}: sort_order 가 배열 위치와 다릅니다 "
                f"(배열 {index}번째인데 sort_order={declared}). "
                "순서의 정본은 배열 위치입니다 — sort_order 는 생략해도 됩니다.",
                detail={"position": index, "sort_order": declared},
            )


def bulk_replace(
    session: Session,
    board: Board,
    payload: list[ItemSaveIn],
) -> list:
    """직접 저장 — 전량 교체. **검증하지 않는다.**

    필수값 누락도, Phase 미지정도 그대로 저장한다. 목록에 없는 기존 행은 삭제된다.

    순서의 정본은 **배열 위치**다. `sort_order` 를 실어 보내면 배열 위치와
    일치하는지만 확인하고, 다르면 400 (`assert_order_agrees`).

    템플릿에서는 "임시저장" 이고 발행 때 V1~V14 가 잡는다. 프로젝트에서는 발행이
    없으므로 이것이 **유일한** 저장 경로이며, 그래서 참조 무결성만 본다
    (plan.md §0.1 — 프로젝트에는 차단 검증이 없다).
    """
    assert_order_agrees(payload, "저장")
    existing = {i.id: i for i in load_ordered_items(session, board)}

    referenced_ids = {p.id for p in payload if p.id is not None}
    unknown = referenced_ids - set(existing)
    if unknown:
        raise BadRequestError(f"이 {board.spec.scope_label}에 없는 item_id: {sorted(unknown)}")

    _check_references(
        session,
        board,
        phase_ids={p.phase_id for p in payload if p.phase_id is not None},
        milestone_ids={p.milestone_id for p in payload if p.milestone_id is not None},
        owner_ids={o for p in payload for o in p.owner_ids},
        document_ids={d for p in payload for d in p.document_ids},
    )

    for item_id, item in existing.items():
        if item_id not in referenced_ids:
            session.delete(item)

    ordered: list = []
    for index, row in enumerate(payload, start=1):
        if row.id is not None:
            item = existing[row.id]
        else:
            item = _new_item(board, sort_order=index, origin=ItemOrigin.ADDED)
            session.add(item)
        item.sort_order = index
        item.phase_id = row.phase_id
        item.milestone_id = row.milestone_id
        item.title = row.title
        item.deliverable = row.deliverable
        item.dash_label = row.dash_label
        item.gate_code = row.gate_code
        item.status = row.status
        item.completion_date = row.completion_date
        _set_links(board, item, row.document_ids, row.owner_ids)
        ordered.append(item)

    session.flush()
    renumber_and_persist(session, board, ordered)
    return ordered


def insert_below(
    session: Session,
    board: Board,
    anchor_item_id: int,
    payload: ItemInsertIn,
) -> list:
    """기준 행 **바로 아래**에 신규 행을 넣는다. 신규 행은 **회색(미배정)** 이다.

    plan.md §0.2. 예전에는 기준 행의 phase/milestone 을 상속했는데, 드래그가 블록
    내부로 제한된 뒤로는 그 규칙이 **새 행을 기존 블록 안에 가둬** 기존 Phase 사이에
    항목을 넣을 방법을 없앴다. 미배정 행은 연속성 검사에 투명하므로 어디에 놓아도
    안전하고, 사용자가 셀 에디터로 소속을 정하거나 그 자리에서 새 Phase 를 만든다.
    """
    items = load_ordered_items(session, board)
    index = next((i for i, it in enumerate(items) if it.id == anchor_item_id), None)
    if index is None:
        raise NotFoundError(f"이 {board.spec.scope_label}에 없는 item_id: {anchor_item_id}")

    _check_references(
        session,
        board,
        phase_ids=set(),
        milestone_ids=set(),
        owner_ids=set(payload.owner_ids),
        document_ids=set(payload.document_ids),
    )

    new_item = _new_item(
        board,
        sort_order=index + 2,
        phase_id=None,
        milestone_id=None,
        title=payload.title,
        deliverable=payload.deliverable,
        dash_label=payload.dash_label,
        gate_code=payload.gate_code,
        status=payload.status,
        completion_date=payload.completion_date,
        origin=ItemOrigin.ADDED,
    )
    session.add(new_item)
    _set_links(board, new_item, payload.document_ids, payload.owner_ids)
    session.flush()

    items.insert(index + 1, new_item)
    renumber_and_persist(session, board, items)
    return items


def append_item(
    session: Session, board: Board, payload: ItemInsertIn
) -> list:
    """목록 맨 끝에 회색 행을 붙인다.

    `insert-below` 는 기준 행이 있어야 하므로, **행이 0개인 보드**에는 첫 행을
    만들 방법이 없다 (새 템플릿의 첫 DRAFT 가 실제로 그렇다). 이 연산이 그 구멍을
    메운다. 소속은 §0.2 에 따라 비워 둔다 — `insert-below` 와 같은 규칙이다.
    """
    _check_references(
        session,
        board,
        phase_ids=set(),
        milestone_ids=set(),
        owner_ids=set(payload.owner_ids),
        document_ids=set(payload.document_ids),
    )

    items = load_ordered_items(session, board)
    new_item = _new_item(
        board,
        sort_order=len(items) + 1,
        phase_id=None,
        milestone_id=None,
        title=payload.title,
        deliverable=payload.deliverable,
        dash_label=payload.dash_label,
        gate_code=payload.gate_code,
        status=payload.status,
        completion_date=payload.completion_date,
        origin=ItemOrigin.ADDED,
    )
    session.add(new_item)
    _set_links(board, new_item, payload.document_ids, payload.owner_ids)
    session.flush()

    items.append(new_item)
    renumber_and_persist(session, board, items)
    return items


def reorder(session: Session, board: Board, item_ids: list[int]) -> list:
    """**위치만** 변경한다 (드래그). 소속은 요청에서 받지도, 서버가 다시 유도하지도 않는다.

    각 행은 **자기 `phase_id`/`milestone_id` 를 그대로 들고** 자리만 바꾼다
    (plan.md §2.2). 그래서 드래그로는 행의 분류가 바뀌지 않는다.

    ## 연속성

    UI 는 자기 Phase·Milestone 블록 **내부**의 순열만 만든다. 같은 소속의 행들이
    서로 자리를 바꾸는 것뿐이므로 결과는 정의상 연속이다. **회색 행은 예외로
    어디로든 옮길 수 있는데**, 그것도 가드가 필요 없다 — 회색 행은 연속성 판정에
    투명해서 위치가 판정에 영향을 주지 않는다 (plan.md §0.2-2, 전수 증명:
    `tests/test_gray_row_exhaustive.py`).

    그렇다고 검사를 뺄 수는 없다. 호스트의 다른 클라이언트는 UI 없이 임의 순서를
    보낼 수 있고, 블록을 가로지르는 순열은 보드를 조각낸다. 예전에는 서버가 소속을
    재유도해 그런 순서를 "고쳐" 주었는데, 그 고침이 곧 **사용자가 요청하지 않은
    Phase 재배정**이었다. 이제는 고치지 않고 422 로 거부한다 — 아무것도 저장하지
    않으므로 보드는 요청 전 상태 그대로다.
    """
    items = load_ordered_items(session, board)
    by_id = {i.id: i for i in items}

    if len(set(item_ids)) != len(item_ids):
        raise BadRequestError("reorder 목록에 중복된 item_id 가 있습니다.")
    if len(item_ids) != len(items) or set(item_ids) != set(by_id):
        raise BadRequestError(
            f"reorder 목록은 이 {board.spec.scope_label}의 전체 행을 정확히 한 번씩 포함해야 합니다."
        )

    refs = reposition(to_row_refs(items), item_ids)

    breaks = find_contiguity_breaks(refs)
    if breaks:
        kind = "Phase" if breaks[0].kind == "phase" else "Milestone"
        raise UnprocessableEntityError(
            f"{kind} 블록이 연속되지 않습니다. "
            "드래그는 행이 속한 Phase·Milestone 블록 **안에서만** 순서를 바꿉니다 — "
            "블록을 가로지르는 순서는 저장하지 않습니다. "
            "소속을 바꾸려면 PATCH .../items/{iid}/membership 을 쓰세요.",
            code="PHASE_NOT_CONTIGUOUS" if breaks[0].kind == "phase" else "MILESTONE_NOT_CONTIGUOUS",
            detail={
                "breaks": [
                    {"row_no": b.index + 1, "item_id": b.item_id, "kind": b.kind, "ref_id": b.ref_id}
                    for b in breaks
                ],
            },
        )

    # 소속은 손대지 않는다. 순서만 바뀌므로 `renumber_and_persist` 가 sort_order 를
    # 다시 매기는 것으로 충분하다.
    ordered = [by_id[ref.item_id] for ref in refs]
    renumber_and_persist(session, board, ordered)
    return ordered


def change_membership(
    session: Session,
    board: Board,
    item_id: int,
    phase_id: int | None,
    milestone_id: int | None,
) -> list:
    """**소속만** 변경한다 (§2.3 셀 편집). 서버가 행을 옮긴다.

    §2.3 은 중간 행이 다른 Phase 를 고르면 "대상 Phase 블록 끝으로 행이
    이동됩니다" 라고 정한다. 그 목적지 계산이야말로 클라이언트에서 떼어내려는
    판단이므로, **중간 행이라고 422 를 내지 않는다** — 서버가 옮긴다.

    422 는 정말로 불가능한 요청에만 쓴다. 대상 Phase 블록 끝에 붙이는 이동은
    구조적으로 연속성을 지키지만, 만일을 대비해 마지막에 검사한다.
    """
    items = load_ordered_items(session, board)
    index = next((i for i, it in enumerate(items) if it.id == item_id), None)
    if index is None:
        raise NotFoundError(f"이 {board.spec.scope_label}에 없는 item_id: {item_id}")

    # 문서/Owner 는 건드리지 않는 연산이라 문서 리포지토리가 필요 없다.
    _check_references(
        session,
        board,
        phase_ids={phase_id} if phase_id is not None else set(),
        milestone_ids={milestone_id} if milestone_id is not None else set(),
        owner_ids=set(),
        document_ids=set(),
    )

    target = items[index]
    rest = items[:index] + items[index + 1 :]

    # 목적지: 대상 Milestone 블록의 끝 → 없으면 대상 Phase 블록의 끝 →
    # 그것도 없으면 (보드에 그 Phase 가 아직 없으므로) 원래 자리를 지킨다.
    destination = None
    if milestone_id is not None:
        matches = [i for i, it in enumerate(rest)
                   if it.phase_id == phase_id and it.milestone_id == milestone_id]
        if matches:
            destination = matches[-1] + 1
    if destination is None and phase_id is not None:
        matches = [i for i, it in enumerate(rest) if it.phase_id == phase_id]
        if matches:
            destination = matches[-1] + 1
    if destination is None:
        destination = min(index, len(rest))

    target.phase_id = phase_id
    target.milestone_id = milestone_id
    ordered = rest[:destination] + [target] + rest[destination:]

    refs = [RowRef(i.id, i.phase_id, i.milestone_id) for i in ordered]
    breaks = find_contiguity_breaks(refs)
    if breaks:
        kind = "Phase" if breaks[0].kind == "phase" else "Milestone"
        raise UnprocessableEntityError(
            f"{kind} 블록이 연속되지 않습니다. 같은 Phase/Milestone 의 행들은 붙어 있어야 합니다.",
            code="PHASE_NOT_CONTIGUOUS" if breaks[0].kind == "phase" else "MILESTONE_NOT_CONTIGUOUS",
            # 사용자가 실제로 편집한 행을 가리킨다. 조각남이 "드러나는" 위치가
            # 아니라 원인이 된 위치라야 그리드가 쓸모 있게 하이라이트한다.
            detail={
                "item_id": item_id,
                "row_no": destination + 1,
                "field": "phase_id" if breaks[0].kind == "phase" else "milestone_id",
                "breaks": [
                    {"row_no": b.index + 1, "item_id": b.item_id, "kind": b.kind, "ref_id": b.ref_id}
                    for b in breaks
                ],
            },
        )

    session.flush()
    renumber_and_persist(session, board, ordered)
    return ordered


def _anchor_numbering(session: Session, board: Board, anchor_item_id: int):
    """기준 행과, 그 행에 대한 서버 계산 경계 플래그를 함께 돌려준다."""
    items = load_ordered_items(session, board)
    index = next((i for i, it in enumerate(items) if it.id == anchor_item_id), None)
    if index is None:
        raise NotFoundError(f"이 {board.spec.scope_label}에 없는 item_id: {anchor_item_id}")

    result = renumber(to_row_refs(items), phase_start_no=board.phase_start_no)
    return items, index, result.rows[index]


def create_phase_from_row(
    session: Session, board: Board, anchor_item_id: int, name: str
) -> list:
    """기준 행에서 새 Phase 를 만들고, 그 행을 새 Phase 로 옮긴다 (§2.3 / §0.2).

    **삽입 위치를 인자로 받지 않는다.** 기준 행이 목록에서 제자리를 지킨 채
    소속만 바뀌므로, 새 Phase 가 기존 블록 앞에 생길지 뒤에 생길지는 기준 행이
    어디에 있었는지에서 저절로 정해진다. 위치를 따로 받으면 §2.3 규칙에 정본이
    둘 생긴다.

    **회색 행이 이 연산의 주 무대다** (§0.2-5). 두 블록 사이의 회색 행에서 만들면
    first-appearance 재계산이 저절로 그 **사이 번호**를 부여한다 — "사이에 추가"에
    필요한 특별한 삽입 로직은 없다.

    거부 조건은 `can_create_phase` 하나이고, 그것은 "새 Phase 를 배정해도 보드가
    연속인가" 와 **동치**다 (전수 증명: `tests/test_gray_row_exhaustive.py`).
    """
    items, index, numbering = _anchor_numbering(session, board, anchor_item_id)

    if not numbering.can_create_phase:
        raise UnprocessableEntityError(
            f"{index + 1}행에서 새 Phase 를 만들면 기존 Phase 블록이 두 조각으로 쪼개집니다. "
            "블록의 경계 행이나, 서로 다른 블록 사이의 미배정 행에서만 가능합니다.",
            code="PHASE_BOUNDARY_VIOLATION",
            detail={"item_id": anchor_item_id, "row_no": index + 1, "field": "phase_id"},
        )

    spec = board.spec
    duplicate = session.scalar(
        select(spec.phase_cls).where(
            spec.master_scope(spec.phase_cls) == board.master_scope_id,
            spec.phase_cls.name == name,
        )
    )
    if duplicate is not None:
        raise BadRequestError(f"이미 존재하는 Phase 이름입니다: {name}")

    phase = spec.phase_cls(
        **{spec.master_scope_attr: board.master_scope_id}, name=name, seq_no=0
    )
    session.add(phase)
    session.flush()

    anchor = items[index]
    anchor.phase_id = phase.id
    # 새 Phase 에는 아직 Milestone 이 없다.
    anchor.milestone_id = None
    session.flush()

    renumber_and_persist(session, board, items)
    return items


def create_milestone_from_row(
    session: Session, board: Board, anchor_item_id: int, name: str
) -> list:
    """기준 행에서 새 Milestone 을 만든다. 소속 Phase 는 기준 행의 것을 쓴다."""
    items, index, numbering = _anchor_numbering(session, board, anchor_item_id)
    anchor = items[index]

    if anchor.phase_id is None:
        raise UnprocessableEntityError(
            f"{index + 1}행에 Phase 가 지정되어 있지 않아 Milestone 을 만들 수 없습니다.",
            code="PHASE_REQUIRED",
            detail={"item_id": anchor_item_id, "row_no": index + 1, "field": "phase_id"},
        )
    if not numbering.can_create_milestone:
        raise UnprocessableEntityError(
            f"{index + 1}행에서 새 Milestone 을 만들면 기존 Milestone 블록이 쪼개집니다. "
            "블록의 경계 행이나, 서로 다른 블록 사이의 미배정 행에서만 가능합니다.",
            code="MILESTONE_BOUNDARY_VIOLATION",
            detail={"item_id": anchor_item_id, "row_no": index + 1, "field": "milestone_id"},
        )

    spec = board.spec
    duplicate = session.scalar(
        select(spec.milestone_cls).where(
            spec.milestone_cls.phase_id == anchor.phase_id, spec.milestone_cls.name == name
        )
    )
    if duplicate is not None:
        raise BadRequestError(f"이 Phase 에 이미 존재하는 Milestone 이름입니다: {name}")

    milestone = spec.milestone_cls(
        **{spec.master_scope_attr: board.master_scope_id},
        phase_id=anchor.phase_id,
        name=name,
        seq_no=0,
    )
    session.add(milestone)
    session.flush()

    anchor.milestone_id = milestone.id
    session.flush()

    renumber_and_persist(session, board, items)
    return items


def delete_item(session: Session, board: Board, item_id: int) -> list:
    """행 삭제 후 재계산.

    빈 Phase/Milestone 은 번호 부여 대상에서 빠질 뿐, 기준정보 자체는 보존한다
    (plan.md §2.2).
    """
    items = load_ordered_items(session, board)
    target = next((i for i in items if i.id == item_id), None)
    if target is None:
        raise NotFoundError(f"이 {board.spec.scope_label}에 없는 item_id: {item_id}")

    items.remove(target)
    session.delete(target)
    session.flush()

    renumber_and_persist(session, board, items)
    return items
