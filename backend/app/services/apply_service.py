"""Phase/Milestone 관리 팝업의 원자적 적용 — plan.md §0.4.

## 이 모듈이 하는 일과, 일부러 하지 않는 일

**하는 일은 블록 재배열 하나다.** 팝업 표의 위→아래 순서를 받아 보드의 Phase
블록(또는 한 Phase 안의 Milestone 블록)을 그 순서로 늘어놓고, 이름 변경·생성·
삭제를 반영한 뒤 `item_service.renumber_and_persist()` 를 부른다.

**번호를 계산하지 않는다.** `seq_no` 도 표시 번호도 이 모듈에는 등장하지 않는다.
first-appearance 재계산(§2.2)이 블록 순서에서 번호를 파생하므로, 순서를 바꾸는
것만으로 "Phase 0 과 1 사이에 새 Phase 를 끼우면 기존 1 이 2 가 되고 하위 행·
마일스톤 번호가 전부 따라 바뀐다" 가 저절로 성립한다. 번호를 직접 끼워 넣는
로직을 두면 정본이 둘이 되고, 둘은 반드시 갈라진다.

## 연속성이 구조적으로 보장되는 이유

재배열의 단위가 **블록**이다. 한 Phase 의 행들은 언제나 한 덩어리로 함께 움직이고
따로 떨어지는 경로가 없으므로, 결과는 정의상 연속이다 (`reorder` 와 달리 임의
순열을 받지 않는다). 그래도 마지막에 `find_contiguity_breaks` 로 단언한다 —
"구조적으로 안전하다" 는 주장은 이 저장소에서 이미 한 번 거짓으로 드러났다
(HANDOFF §5.1).

## 회색(미배정) 행의 부착 — §0.4

미배정 행은 자기 블록이 없으므로 재배열의 단위가 될 수 없다. 그래서 **직전 배정
행의 블록에 붙어 함께 움직인다.** 보드 최상단의 선행 회색 행들은 붙을 블록이
없으므로 최상단에 남는다. Milestone 재배열도 한 단계 아래에서 똑같다 —
milestone 이 null 인 행(회색 행 포함)은 직전 milestone 블록에 붙는다.

블록이 삭제되면 거기 붙어 있던 회색 행은 **지우지 않는다.** 회색 행은 그 Phase 에
속하지 않으므로 캐스케이드 대상이 아니고, 팝업이 사용자에게 보여준 "하위 항목 N개"
에도 포함되지 않는다. 현재 순서에서 가장 가까운 **앞쪽 생존 블록**에 다시 붙이고,
그런 블록이 없으면 최상단 그룹으로 보낸다.

## 기준정보 실체의 삭제 — 하드 삭제와 비활성화

§0.4 는 Phase/Milestone 을 "보드 구조의 일부" 로 보고 캐스케이드 삭제를 허용한다.
그런데 **템플릿 계층에서 Phase 는 버전이 아니라 템플릿에 매인다** — 같은 Phase 를
PUBLISHED 버전이 계속 쓰고 있을 수 있고, 그것을 물리적으로 지우면 손대지도 않은
발행본이 깨진다. 그래서 행을 지운 뒤 `master_service.delete_phase()` 의 기존
정책을 그대로 태운다: **다른 곳에서 안 쓰면 하드 삭제, 쓰고 있으면 비활성화.**
어느 쪽이든 이 보드에서는 사라지므로 사용자가 보는 결과는 같다.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.exceptions import UnprocessableEntityError
from ..models.base import ItemOrigin, ItemStatus
from ..schemas.apply import ApplyEntry, MilestonesApplyIn, PhasesApplyIn
from . import master_service
from .board import Board
from .item_service import load_ordered_items, renumber_and_persist, to_row_refs
from .renumber_service import find_contiguity_breaks

# --- 오류 코드 ---------------------------------------------------------------
SET_MISMATCH = "APPLY_SET_MISMATCH"
DUPLICATE_ID = "APPLY_DUPLICATE_ID"
OUT_OF_SCOPE = "APPLY_OUT_OF_SCOPE"
EMPTY_NAME = "APPLY_EMPTY_NAME"
DUPLICATE_NAME = "APPLY_DUPLICATE_NAME"
ANCHOR_INVALID = "APPLY_ANCHOR_INVALID"
BOARD_NOT_CONTIGUOUS = "APPLY_BOARD_NOT_CONTIGUOUS"

#: 이름 교환(A↔B)을 UQ 위반 없이 통과시키기 위한 중간 이름의 접두.
_TEMP_PREFIX = " wp-apply-"


def _reject(code: str, message: str, **detail) -> None:
    raise UnprocessableEntityError(message, code=code, detail=detail or None)


# =============================================================================
# 블록 분해
# =============================================================================
def _split_blocks(rows: list, key: Callable) -> tuple[list, dict[int, list], list[int]]:
    """`(선행 미배정 행, key → 블록, 최초 등장 순서)`.

    블록에는 그 key 를 가진 행과, **그 뒤에 붙은 미배정 행**이 함께 들어간다
    (§0.4 — 미배정 행은 직전 배정 행에 부착된다). Phase 층위와 Milestone 층위가
    같은 규칙이라 한 함수로 처리한다.
    """
    leading: list = []
    blocks: dict[int, list] = {}
    order: list[int] = []
    current: int | None = None

    for row in rows:
        value = key(row)
        if value is None:
            (leading if current is None else blocks[current]).append(row)
            continue
        if value not in blocks:
            blocks[value] = []
            order.append(value)
        blocks[value].append(row)
        current = value
    return leading, blocks, order


def _phase_of(row):
    return row.phase_id


def _milestone_of(row):
    return row.milestone_id


def _orphan_targets(
    order: list[int], deleted: set[int], blocks: dict[int, list], key: Callable
) -> dict[int | None, list]:
    """삭제되는 블록에 붙어 있던 미배정 행을 어느 블록으로 옮길지 정한다.

    현재 순서에서 **가장 가까운 앞쪽 생존 블록**의 꼬리에 붙인다. 없으면 `None`
    (최상단 그룹). 앞쪽을 택하는 이유는 사용자가 보던 자리에서 가장 덜 움직이기
    때문이다 — 뒤쪽으로 보내면 삭제와 무관한 행이 화면에서 위로 튀어 오른다.
    """
    targets: dict[int | None, list] = {}
    for index, block_key in enumerate(order):
        if block_key not in deleted:
            continue
        survivors = [row for row in blocks[block_key] if key(row) is None]
        if not survivors:
            continue
        target = next(
            (order[j] for j in range(index - 1, -1, -1) if order[j] not in deleted), None
        )
        targets.setdefault(target, []).extend(survivors)
    return targets


# =============================================================================
# 요청 검증 — 전부 422 다
# =============================================================================
def _validate_entries(
    entries: list[ApplyEntry],
    deleted_ids: list[int],
    existing: list[int],
    in_scope: set[int],
    *,
    label: str,
    scope_label: str,
) -> None:
    """§0.4 의 서버 검증. 순서가 있다 — 먼저 걸리는 것이 더 구체적인 오류다."""
    for position, entry in enumerate(entries, start=1):
        if not entry.name or not entry.name.strip():
            _reject(EMPTY_NAME, f"{position}번째 {label} 이름이 비어 있습니다.", position=position)

    referenced = [e.id for e in entries if e.id is not None] + list(deleted_ids)
    seen: set[int] = set()
    for entity_id in referenced:
        if entity_id in seen:
            _reject(
                DUPLICATE_ID,
                f"{label} id {entity_id} 가 요청에 두 번 이상 나옵니다. "
                "목록과 deleted_ids 를 통틀어 한 번씩만 나와야 합니다.",
                id=entity_id,
            )
        seen.add(entity_id)

    outside = sorted(i for i in referenced if i not in in_scope)
    if outside:
        _reject(
            OUT_OF_SCOPE,
            f"{scope_label}의 {label} 가 아닙니다: {outside}. "
            "다른 템플릿·프로젝트·Phase 의 기준정보는 참조할 수 없습니다.",
            ids=outside,
        )

    expected = set(existing)
    missing = sorted(expected - seen)
    unknown = sorted(seen - expected)
    if missing or unknown:
        _reject(
            SET_MISMATCH,
            f"요청의 {label} 집합이 현재 보드와 다릅니다. "
            f"빠진 id={missing}, 보드에 없는 id={unknown}. "
            "목록과 deleted_ids 의 합집합이 현재 집합과 정확히 같아야 합니다.",
            missing=missing,
            unknown=unknown,
            expected=sorted(expected),
        )


def _resolve_anchor(
    items: list, entries: list[ApplyEntry], anchor_item_id: int | None, *, label: str
):
    """앵커 규칙 (§0.4). 반환값은 `(앵커 행 | None, 신규 엔트리 수)`."""
    new_count = sum(1 for e in entries if e.id is None)
    if anchor_item_id is None:
        return None, new_count

    if new_count != 1:
        _reject(
            ANCHOR_INVALID,
            f"anchor_item_id 는 신규 {label} 가 정확히 1개일 때만 쓸 수 있습니다. "
            f"(신규 {new_count}개)",
            item_id=anchor_item_id,
            new_count=new_count,
        )
    anchor = next((it for it in items if it.id == anchor_item_id), None)
    if anchor is None:
        _reject(
            ANCHOR_INVALID,
            f"이 보드에 없는 anchor_item_id 입니다: {anchor_item_id}",
            item_id=anchor_item_id,
        )
    return anchor, new_count


def _check_names(
    session: Session, model, scope_clause, entries: list[ApplyEntry], kept_ids: set[int]
) -> None:
    """최종 이름이 유일한지 본다 — UQ 위반이 500 으로 새어 나가지 않도록.

    검사 대상은 두 묶음이다.

    1. 요청 안에서의 중복.
    2. **보드 밖에 남아 있는 같은 스코프의 기준정보.** 템플릿의 Phase 는 template
       스코프라 다른 버전만 쓰는 것이 남아 있을 수 있고, 비활성으로 물러난 것도
       이름을 계속 점유한다.

    삭제를 **먼저** 수행한 뒤에 부르는 것이 전제다. 그래야 방금 지운 이름을
    재사용하는 요청이 자기 자신 때문에 거부되지 않는다.
    """
    seen: set[str] = set()
    for entry in entries:
        name = entry.name.strip()
        if name in seen:
            _reject(DUPLICATE_NAME, f"이름이 중복됩니다: {name}", name=name)
        seen.add(name)

    for entity in session.scalars(select(model).where(scope_clause)):
        if entity.id in kept_ids:
            continue
        if entity.name in seen:
            _reject(
                DUPLICATE_NAME,
                f"이미 존재하는 이름입니다: {entity.name}",
                name=entity.name,
                id=entity.id,
            )


def _rename(session: Session, pairs: list[tuple[object, str]]) -> None:
    """이름을 두 번에 나눠 쓴다 — A↔B 교환이 UQ 에 걸리지 않도록.

    MariaDB 는 UNIQUE 를 문장 단위로 검사하므로 한 번에 쓰면 교환 중간 상태가
    충돌한다. 먼저 전부 임시 이름으로 밀어 두고 flush 한 뒤 최종 이름을 쓴다.
    """
    changed = [(entity, name) for entity, name in pairs if entity.name != name]
    if not changed:
        return
    for entity, _ in changed:
        entity.name = f"{_TEMP_PREFIX}{entity.id}"
    session.flush()
    for entity, name in changed:
        entity.name = name
    session.flush()


def _blank_row(board: Board, *, phase_id: int | None, milestone_id: int | None):
    """새 블록을 지탱할 빈 행 (§0.4 — 행 없는 Phase 는 존재할 수 없다)."""
    spec = board.spec
    return spec.item_cls(
        **{spec.item_scope_attr: board.scope_id},
        sort_order=0,
        phase_id=phase_id,
        milestone_id=milestone_id,
        status=ItemStatus.NOT_STARTED,
        origin=ItemOrigin.ADDED,
    )


def _assert_contiguous(items: list, *, when: str) -> None:
    breaks = find_contiguity_breaks(to_row_refs(items))
    if breaks:
        _reject(
            BOARD_NOT_CONTIGUOUS,
            f"{when} 보드의 Phase/Milestone 블록이 연속되지 않습니다.",
            breaks=[
                {"row_no": b.index + 1, "item_id": b.item_id, "kind": b.kind, "ref_id": b.ref_id}
                for b in breaks
            ],
        )


def _finish(session: Session, board: Board, ordered: list) -> list:
    session.flush()
    _assert_contiguous(ordered, when="적용 결과")
    renumber_and_persist(session, board, ordered)
    return ordered


# =============================================================================
# Phase 적용
# =============================================================================
def apply_phases(session: Session, board: Board, payload: PhasesApplyIn) -> list:
    """팝업 표의 최종 상태를 보드에 반영한다 (plan.md §0.4).

    한 트랜잭션이다 — 어느 단계에서 거부되든 호출부가 커밋하지 않으므로 보드는
    요청 전 상태 그대로다.
    """
    spec = board.spec
    entries = payload.phases
    items = load_ordered_items(session, board)
    _assert_contiguous(items, when="적용 전")
    leading, blocks, order = _split_blocks(items, _phase_of)

    in_scope = {
        p.id
        for p in session.scalars(
            select(spec.phase_cls).where(spec.master_scope(spec.phase_cls) == board.master_scope_id)
        )
    }
    _validate_entries(
        entries, payload.deleted_ids, order, in_scope,
        label="Phase", scope_label=f"이 {spec.scope_label}",
    )
    anchor, _new_count = _resolve_anchor(items, entries, payload.anchor_item_id, label="Phase")
    if anchor is not None and anchor.phase_id is not None:
        _reject(
            ANCHOR_INVALID,
            "새 Phase 의 첫 행이 될 수 있는 것은 미배정(회색) 행뿐입니다. "
            "배정된 행은 먼저 '미배정으로 전환' 해야 합니다.",
            item_id=anchor.id,
            field="phase_id",
        )

    # --- 삭제 (캐스케이드) ---------------------------------------------------
    deleted = set(payload.deleted_ids)
    orphans = _orphan_targets(order, deleted, blocks, _phase_of)
    removed_rows: set[int] = set()
    for phase_id in payload.deleted_ids:
        removed_rows |= _delete_phase_rows(session, board, items, phase_id)
        result = master_service.delete_phase(session, board, phase_id)
        if not result.deleted:
            # 다른 버전이 쓰고 있어 비활성화만 된 경우. 하위 Milestone 도 함께
            # 내린다 — 그러지 않으면 사라진 Phase 아래의 Milestone 이 기준정보
            # 화면에 살아남아 선택 가능한 것처럼 보이고, V14 도 계속 경고한다.
            for milestone in session.scalars(
                select(spec.milestone_cls).where(spec.milestone_cls.phase_id == phase_id)
            ):
                milestone.is_active = 0
            session.flush()

    # --- 이름: 검증 → 변경 → 생성 --------------------------------------------
    kept = {e.id for e in entries if e.id is not None}
    _check_names(
        session,
        spec.phase_cls,
        spec.master_scope(spec.phase_cls) == board.master_scope_id,
        entries,
        kept,
    )
    existing_entities = {
        p.id: p
        for p in session.scalars(select(spec.phase_cls).where(spec.phase_cls.id.in_(kept or {0})))
    }
    _rename(session, [(existing_entities[e.id], e.name.strip()) for e in entries if e.id is not None])

    created: dict[int, object] = {}
    for position, entry in enumerate(entries):
        if entry.id is not None:
            continue
        phase = spec.phase_cls(
            **{spec.master_scope_attr: board.master_scope_id}, name=entry.name.strip(), seq_no=0
        )
        session.add(phase)
        created[position] = phase
    if created:
        session.flush()

    # --- 블록 재배열 ---------------------------------------------------------
    final: dict[int, list] = {}
    for phase_id in order:
        if phase_id in deleted:
            continue
        rows = [row for row in blocks[phase_id] if row.id not in removed_rows]
        final[phase_id] = rows + orphans.get(phase_id, [])
    top = list(leading) + orphans.get(None, [])

    if anchor is not None:
        top = [row for row in top if row is not anchor]
        for phase_id in list(final):
            final[phase_id] = [row for row in final[phase_id] if row is not anchor]

    for position, entry in enumerate(entries):
        if entry.id is not None:
            continue
        phase = created[position]
        if anchor is not None:
            # 앵커가 있으면 신규는 정확히 1개다 (`_resolve_anchor` 가 보장).
            anchor.phase_id = phase.id
            anchor.milestone_id = None
            final[phase.id] = [anchor]
        else:
            row = _blank_row(board, phase_id=phase.id, milestone_id=None)
            session.add(row)
            final[phase.id] = [row]
    session.flush()

    ordered = list(top)
    for position, entry in enumerate(entries):
        ordered.extend(final[entry.id if entry.id is not None else created[position].id])
    return _finish(session, board, ordered)


def _delete_phase_rows(session: Session, board: Board, items: list, phase_id: int) -> set[int]:
    """그 Phase 의 행을 전부 지운다 — 하위 Milestone 을 쓰는 행까지 포함한다.

    정상 데이터에서는 두 집합이 같지만, `milestone` 만 그 Phase 소속이고
    `phase_id` 는 다른 행이 남아 있으면 Milestone 삭제가 FK RESTRICT 에 걸린다.
    """
    spec = board.spec
    milestone_ids = set(
        session.scalars(
            select(spec.milestone_cls.id).where(spec.milestone_cls.phase_id == phase_id)
        )
    )
    removed: set[int] = set()
    for item in items:
        if item.id in removed:
            continue
        if item.phase_id == phase_id or (
            item.milestone_id is not None and item.milestone_id in milestone_ids
        ):
            session.delete(item)
            removed.add(item.id)
    session.flush()
    return removed


# =============================================================================
# Milestone 적용 — 한 Phase 안에서
# =============================================================================
def apply_milestones(
    session: Session, board: Board, phase_id: int, payload: MilestonesApplyIn
) -> list:
    """한 Phase 블록 안의 Milestone 순서·이름·생성·삭제를 반영한다 (§0.4).

    Phase 블록의 **바깥은 건드리지 않는다.** 다른 Phase 의 블록은 순서도 내용도
    그대로 다시 이어 붙인다.
    """
    spec = board.spec
    entries = payload.milestones
    items = load_ordered_items(session, board)
    _assert_contiguous(items, when="적용 전")
    leading, blocks, order = _split_blocks(items, _phase_of)

    phase = session.get(spec.phase_cls, phase_id)
    if phase is None or getattr(phase, spec.master_scope_attr) != board.master_scope_id:
        _reject(OUT_OF_SCOPE, f"이 {spec.scope_label}의 Phase 가 아닙니다: {phase_id}", ids=[phase_id])
    if phase_id not in blocks:
        _reject(
            SET_MISMATCH,
            f"Phase {phase_id} 에 속한 행이 보드에 없습니다. "
            "행이 없는 Phase 에는 Milestone 을 배치할 수 없습니다.",
            missing=[],
            unknown=[],
            expected=[],
        )

    ms_leading, ms_blocks, ms_order = _split_blocks(blocks[phase_id], _milestone_of)

    in_scope = {
        m.id
        for m in session.scalars(
            select(spec.milestone_cls).where(spec.milestone_cls.phase_id == phase_id)
        )
    }
    _validate_entries(
        entries, payload.deleted_ids, ms_order, in_scope,
        label="Milestone", scope_label="이 Phase",
    )
    anchor, _new_count = _resolve_anchor(items, entries, payload.anchor_item_id, label="Milestone")
    if anchor is not None and (
        anchor.milestone_id is not None or anchor.phase_id not in (None, phase_id)
    ):
        # Milestone 층위의 "미배정" 은 `milestone_id is None` 이다. 회색 행(phase 도
        # 없음)과 §0.3 의 "phase 만 배정된 행" 둘 다 여기서 새 Milestone 을 만들 수
        # 있어야 한다 — 후자가 Milestone 셀 에디터가 열리는 유일한 상태이기 때문이다.
        _reject(
            ANCHOR_INVALID,
            "새 Milestone 의 첫 행이 될 수 있는 것은 이 Phase 의 Milestone 미배정 행 "
            "또는 미배정(회색) 행뿐입니다.",
            item_id=anchor.id,
            field="milestone_id",
        )

    # --- 삭제 (캐스케이드) ---------------------------------------------------
    deleted = set(payload.deleted_ids)
    orphans = _orphan_targets(ms_order, deleted, ms_blocks, _milestone_of)
    removed_rows: set[int] = set()
    for milestone_id in payload.deleted_ids:
        for item in items:
            if item.milestone_id == milestone_id and item.id not in removed_rows:
                session.delete(item)
                removed_rows.add(item.id)
        session.flush()
        master_service.delete_milestone(session, board, milestone_id)

    # --- 이름: 검증 → 변경 → 생성 --------------------------------------------
    kept = {e.id for e in entries if e.id is not None}
    _check_names(session, spec.milestone_cls, spec.milestone_cls.phase_id == phase_id, entries, kept)
    existing_entities = {
        m.id: m
        for m in session.scalars(
            select(spec.milestone_cls).where(spec.milestone_cls.id.in_(kept or {0}))
        )
    }
    _rename(session, [(existing_entities[e.id], e.name.strip()) for e in entries if e.id is not None])

    created: dict[int, object] = {}
    for position, entry in enumerate(entries):
        if entry.id is not None:
            continue
        milestone = spec.milestone_cls(
            **{spec.master_scope_attr: board.master_scope_id},
            phase_id=phase_id,
            name=entry.name.strip(),
            seq_no=0,
        )
        session.add(milestone)
        created[position] = milestone
    if created:
        session.flush()

    # --- Phase 블록 내부 재배열 ----------------------------------------------
    final: dict[int, list] = {}
    for milestone_id in ms_order:
        if milestone_id in deleted:
            continue
        rows = [row for row in ms_blocks[milestone_id] if row.id not in removed_rows]
        final[milestone_id] = rows + orphans.get(milestone_id, [])
    block_top = list(ms_leading) + orphans.get(None, [])

    # 앵커는 이 Phase 블록 밖(다른 블록에 붙은 회색 행, 최상단 회색 행)에 있을 수
    # 있다. 어디에 있든 떼어 낸 뒤 새 Milestone 의 첫 행으로 삼는다.
    if anchor is not None:
        block_top = [row for row in block_top if row is not anchor]
        for milestone_id in list(final):
            final[milestone_id] = [row for row in final[milestone_id] if row is not anchor]
        leading = [row for row in leading if row is not anchor]
        for other_id in blocks:
            if other_id != phase_id:
                blocks[other_id] = [row for row in blocks[other_id] if row is not anchor]

    for position, entry in enumerate(entries):
        if entry.id is not None:
            continue
        milestone = created[position]
        if anchor is not None:
            anchor.phase_id = phase_id
            anchor.milestone_id = milestone.id
            final[milestone.id] = [anchor]
        else:
            row = _blank_row(board, phase_id=phase_id, milestone_id=milestone.id)
            session.add(row)
            final[milestone.id] = [row]
    session.flush()

    rearranged = list(block_top)
    for position, entry in enumerate(entries):
        rearranged.extend(final[entry.id if entry.id is not None else created[position].id])

    ordered = list(leading)
    for other_id in order:
        if other_id == phase_id:
            ordered.extend(rearranged)
        else:
            ordered.extend(row for row in blocks[other_id] if row.id not in removed_rows)
    return _finish(session, board, ordered)
