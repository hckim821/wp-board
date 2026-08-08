"""`reorder` 의 불변식을 **전수 증명**한다 — 표본이 아니다.

## 무엇이 증명 대상인가

plan.md §2.2 가 드래그를 자기 Phase·Milestone 블록 안으로 제한하면서, `reorder`
의 계약이 한 줄로 줄었다: **행은 자기 소속을 들고 다니며, 순서만 바뀐다.**

그래서 지금 하중을 받는 명제는 이것이다.

1. **소속 불변** — 어떤 보드, 어떤 순열에도 각 행의 `(phase_id, milestone_id)`
   가 그대로다. 이것이 깨지면 사용자가 요청하지 않은 Phase 재배정이 일어난다.
2. **블록 내부 순열은 항상 연속** — UI 가 만드는 유일한 요청은 절대 거부되지
   않는다.
3. **블록을 가로지르는 순열은 거부** — 그리고 **아무것도 저장되지 않는다.**

## 왜 전수인가

이 자리에서 이미 세 번 틀렸다 (HANDOFF.md §5.1·§5.1c). 세 번 다 "구조적으로
안전하다" 는 추론이 작은 정의역 전수 탐색에 잡혔다. 그래서 여기서는 추론하지
않고 n ≤ 6 의 **모든 연속 보드 배치 × 모든 순열**을 돈다. 표본이 아니다.

## 이전 판이 측정하던 것

이전 판은 소속 **재유도**(`apply_position_change`, LIS `detect_moved_ids`)의
조각남 확률을 쟀다 — 임의 순열 n=6 에서 12.86%, `moved_item_id` 오보 시 ~1%.
그 실패 모드는 재유도가 있어서 존재했다. 재유도가 사라졌으므로 확률도 사라진
것이 아니라 **사건 자체가 정의되지 않는다.** 그 시절의 반례는
`test_the_historical_counterexample_no_longer_reassigns_anything` 에 회귀
테스트로 남겨 두었다 — 조용히 사라지지 않도록.
"""

from __future__ import annotations

from itertools import permutations

import pytest

from app.services.renumber_service import (
    RowRef,
    find_contiguity_breaks,
    reposition,
)


def contiguous_boards(n: int) -> list[list[tuple[int, int]]]:
    """길이 `n` 의 연속 보드 배치를 전부 만든다.

    Phase 블록으로 나누고(compositions of n), 각 블록을 다시 Milestone 블록으로
    나눈다. Phase/Milestone id 는 서로 구별되기만 하면 되므로 0,1,2… 를 쓴다.
    """
    def compositions(total: int) -> list[list[int]]:
        if total == 0:
            return [[]]
        out = []
        for first in range(1, total + 1):
            for rest in compositions(total - first):
                out.append([first] + rest)
        return out

    boards: list[list[tuple[int, int]]] = []
    for phase_sizes in compositions(n):
        # 각 Phase 블록 안에서의 Milestone 분할을 곱집합으로 조합
        per_phase = [compositions(size) for size in phase_sizes]

        def build(depth: int, acc: list[tuple[int, int]], ms_counter: int):
            if depth == len(phase_sizes):
                boards.append(list(acc))
                return
            for ms_sizes in per_phase[depth]:
                rows: list[tuple[int, int]] = []
                counter = ms_counter
                for size in ms_sizes:
                    rows += [(depth, counter)] * size
                    counter += 1
                build(depth + 1, acc + rows, counter)

        build(0, [], 0)
    return boards


def as_rows(board: list[tuple[int, int]]) -> list[RowRef]:
    return [RowRef(item_id=i + 1, phase_id=p, milestone_id=m) for i, (p, m) in enumerate(board)]


def is_contiguous(rows: list[RowRef]) -> bool:
    return find_contiguity_breaks(rows) == []


def membership_of(rows: list[RowRef]) -> dict[int, tuple[int | None, int | None]]:
    return {r.item_id: (r.phase_id, r.milestone_id) for r in rows}


def block_internal_permutations(board: list[tuple[int, int]]):
    """**UI 가 만들 수 있는 모든 순서** — 각 Milestone 블록 내부의 순열.

    드래그는 자기 Phase·Milestone 블록 밖으로 나가지 못하므로, 보드 전체의
    순서는 "각 블록을 그 자리에서 독립적으로 섞은 것" 의 곱집합이다.
    """
    blocks: list[list[int]] = []
    for index, key in enumerate(board):
        if index == 0 or board[index - 1] != key:
            blocks.append([])
        blocks[-1].append(index + 1)

    def walk(depth: int, acc: list[int]):
        if depth == len(blocks):
            yield list(acc)
            return
        for shuffled in permutations(blocks[depth]):
            yield from walk(depth + 1, acc + list(shuffled))

    yield from walk(0, [])


# =============================================================================
# 전수 조사의 전제
# =============================================================================
def test_the_board_generator_produces_only_contiguous_boards():
    for n in range(1, 6):
        boards = contiguous_boards(n)
        assert boards, f"n={n} 에서 보드가 생성되지 않았다"
        for board in boards:
            assert is_contiguous(as_rows(board)), f"생성기가 비연속 보드를 만들었다: {board}"


def test_board_generator_counts_match_the_closed_form():
    """빠뜨린 배치가 없는지 조합론으로 교차 확인한다.

    n 행을 k 개 Phase 블록으로 나누는 경우가 C(n-1, k-1) 이고, 각 경우의
    Milestone 분할이 2^(n-k) 이므로 총합은 sum_k C(n-1,k-1) * 2^(n-k).
    """
    from math import comb

    for n in range(1, 7):
        expected = sum(comb(n - 1, k - 1) * 2 ** (n - k) for k in range(1, n + 1))
        assert len(contiguous_boards(n)) == expected, f"n={n}"


def test_block_internal_permutation_generator_covers_exactly_the_blocks():
    """생성기가 **블록 내부 순열만** 만드는지 확인한다.

    이 전제가 틀리면 아래 "항상 성공" 주장이 무의미해진다 — 실제로는 더 좁은
    (혹은 더 넓은) 집합을 돌게 되기 때문이다.
    """
    from math import factorial

    for n in range(1, 6):
        for board in contiguous_boards(n):
            rows = as_rows(board)
            orders = list(block_internal_permutations(board))

            sizes: list[int] = []
            for index, key in enumerate(board):
                if index == 0 or board[index - 1] != key:
                    sizes.append(0)
                sizes[-1] += 1
            expected = 1
            for size in sizes:
                expected *= factorial(size)
            assert len(orders) == expected, f"board={board}"

            # 어떤 순서든 각 자리의 소속은 원본과 같아야 한다 (= 블록 밖으로 안 나갔다)
            original = [(r.phase_id, r.milestone_id) for r in rows]
            for order in orders:
                moved = [(rows[i - 1].phase_id, rows[i - 1].milestone_id) for i in order]
                assert moved == original, f"블록 밖으로 나간 순서 {order} board={board}"


# =============================================================================
# 1. 소속 불변 — 지금 하중을 받는 명제
# =============================================================================
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_reorder_never_changes_any_rows_membership(n):
    """**전수 증명: 어떤 순열에도 소속은 바뀌지 않는다.**

    n ≤ 6 의 모든 연속 보드 배치 × **모든 순열** (블록 내부든 아니든)을 돌며,
    각 행의 `(phase_id, milestone_id)` 가 재배치 전후로 동일한지 본다.

    거부될 순열까지 포함하는 것이 중요하다. 거부는 서비스 계층의 판단이고,
    이 순수 함수는 **무엇을 받든** 소속을 건드리지 않아야 한다.
    """
    checked = 0
    for board in contiguous_boards(n):
        rows = as_rows(board)
        ids = [r.item_id for r in rows]
        before = membership_of(rows)

        for order in permutations(ids):
            result = reposition(rows, list(order))
            checked += 1
            assert [r.item_id for r in result] == list(order), f"순서가 요청과 다르다 {order}"
            assert membership_of(result) == before, f"소속이 바뀌었다 board={board} order={order}"

    assert checked > 0


def test_reorder_preserves_membership_even_on_a_board_that_is_already_fragmented():
    """조각난 보드를 받아도 소속을 "고쳐" 주지 않는다.

    예전 구현은 여기서 상속을 걸어 보드를 그럴듯하게 만들었다. 그 고침이 곧
    사용자가 요청하지 않은 재배정이었다. 조각난 보드는 임시저장(§2.5)으로
    실제로 만들어질 수 있으므로 도달 불가능한 입력이 아니다.
    """
    rows = [RowRef(1, 0, 0), RowRef(2, 1, 1), RowRef(3, 0, 0)]     # P0 가 두 조각
    result = reposition(rows, [3, 2, 1])

    assert membership_of(result) == membership_of(rows)
    assert not is_contiguous(result)          # 고쳐 주지 않는다 — 서비스가 422 로 거부한다


def test_a_single_row_board_keeps_its_membership():
    """이웃이 없는 행도 예외가 아니다. 예전엔 여기서 소속이 지워졌다 (감사 F7)."""
    rows = [RowRef(item_id=1, phase_id=7, milestone_id=9)]
    assert reposition(rows, [1]) == rows


def test_an_identity_reorder_changes_nothing():
    for n in range(1, 6):
        for board in contiguous_boards(n):
            rows = as_rows(board)
            result = reposition(rows, [r.item_id for r in rows])
            assert result == rows, f"항등 재배치가 보드를 바꿨다: {board}"


# =============================================================================
# 2. 블록 내부 순열 — UI 가 만드는 유일한 요청
# =============================================================================
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_every_block_internal_permutation_stays_contiguous(n):
    """**전수 증명: UI 가 만들 수 있는 순서는 하나도 거부되지 않는다.**

    n ≤ 6 의 모든 연속 보드 배치 × 각 보드의 **모든 블록 내부 순열**.
    """
    checked = 0
    for board in contiguous_boards(n):
        rows = as_rows(board)
        for order in block_internal_permutations(board):
            result = reposition(rows, order)
            checked += 1
            assert is_contiguous(result), f"board={board} order={order}"

    assert checked > 0


# =============================================================================
# 3. 블록을 가로지르는 순열 — 거부되고, 아무것도 저장되지 않는다
# =============================================================================
def crossing_permutations(board: list[tuple[int, int]]):
    """블록을 가로지르는 순열 중 **실제로 조각나는 것**만 고른다.

    가로지른다고 반드시 조각나는 것은 아니다. 예를 들어 인접한 두 블록을 통째로
    맞바꾸면 각 블록은 붙어 있는 채라 연속이다. 그런 순열은 통과하는 것이 맞고,
    거부 대상이 아니다.
    """
    rows = as_rows(board)
    ids = [r.item_id for r in rows]
    for order in permutations(ids):
        if not is_contiguous(reposition(rows, list(order))):
            yield list(order)


@pytest.mark.parametrize("n", [3, 4, 5])
def test_fragmenting_permutations_exist_and_are_all_detected(n):
    """조각나는 순열이 존재한다는 사실을 **양성 사실로** 고정한다.

    UI 는 이런 순서를 만들 수 없지만 호스트의 다른 클라이언트는 만들 수 있다.
    이 반례가 사라지는 날이 오면 여기가 먼저 깨지면서 "이제 `reorder` 의
    연속성 검사를 제거해도 된다" 고 알려준다.
    """
    found = 0
    for board in contiguous_boards(n):
        for order in crossing_permutations(board):
            found += 1
            # 검사가 실제로 잡는지 (crossing_permutations 자체가 검사로 골랐으므로
            # 여기서는 소속 불변까지 함께 성립하는지를 본다)
            rows = as_rows(board)
            result = reposition(rows, order)
            assert membership_of(result) == membership_of(rows)

    assert found > 0, (
        f"n={n} 에서 조각나는 순열이 하나도 없다면 reorder 의 연속성 검사를 "
        "제거할 수 있다 — 다만 그 판단은 이 테스트를 고치면서 명시적으로 하라."
    )


def test_the_service_rejects_a_crossing_order_and_saves_nothing(db, board):
    """422 로 끝나는 것으로 부족하다 — **보드가 요청 전과 완전히 같아야** 한다."""
    from app.core.exceptions import UnprocessableEntityError
    from app.models import Item
    from app.services import item_service, version_service

    layout = [(board.p0, board.m01), (board.p1, board.m11),
              (board.p0, board.m02), (board.p0, board.m02)]
    for order, (phase, milestone) in enumerate(layout, start=1):
        db.add(Item(version_id=board.published.id, sort_order=order,
                    phase_id=phase.id, milestone_id=milestone.id, title="t", deliverable="d"))
    db.commit()

    draft = version_service.create_draft(db, board.wp.id)
    db.commit()
    rows = item_service.load_ordered_items(db, version_service.board_of(db, draft))
    ids = [r.id for r in rows]

    def snapshot():
        return [
            (i.id, i.sort_order, i.phase_id, i.milestone_id)
            for i in item_service.load_ordered_items(db, version_service.board_of(db, draft))
        ]

    before = snapshot()
    # P0 블록 사이로 P1 행을 끼워 넣는다 — 블록을 가로지른다
    crossing = [ids[0], ids[2], ids[1], ids[3]]
    assert not is_contiguous(reposition(item_service.to_row_refs(rows), crossing))

    with pytest.raises(UnprocessableEntityError):
        item_service.reorder(db, version_service.board_of(db, draft), crossing)
    db.rollback()

    assert snapshot() == before


# =============================================================================
# 회귀 — 예전 설계가 남긴 반례
# =============================================================================
def test_the_historical_counterexample_no_longer_reassigns_anything():
    """`[A,A,A,B]` 를 `(A1,A2,B,A3)` 로 — 재유도 시절의 대표 반례.

    이 순서는 A 블록 사이에 B 행을 끼워 넣는다. 예전에는 서버가 소속을 재유도해
    B 행을 조용히 A 로 바꿔 놓거나(§2.2 가 지적한 결함), 재상속을 놓쳐 `A,A,B,A`
    로 조각냈다. 지금은 **소속을 그대로 두고**, 조각난 결과를 서비스가 422 로
    거부한다.
    """
    rows = [RowRef(1, 0, 0), RowRef(2, 0, 0), RowRef(3, 0, 0), RowRef(4, 1, 1)]
    result = reposition(rows, [1, 2, 4, 3])

    assert membership_of(result) == membership_of(rows)       # 아무것도 재배정되지 않았다
    assert not is_contiguous(result)                          # 그러므로 422 대상이다


def test_the_phase_boundary_drag_that_used_to_silently_reassign():
    """§2.2 가 기록한 재현 절차 그대로.

    `행1(P0) 행2(P0) │ 행3(P1) 행4(P1) 행5(P1)` 에서 행1 을 P1 블록 가운데로.
    예전 결과: 행1 의 Phase 가 **경고 없이** P1 로 바뀌고 breaks 는 비어 있었다.
    """
    rows = [RowRef(1, 0, 0), RowRef(2, 0, 0), RowRef(3, 1, 1), RowRef(4, 1, 1), RowRef(5, 1, 1)]
    result = reposition(rows, [2, 3, 1, 4, 5])

    assert membership_of(result)[1] == (0, 0), "행1 의 소속이 바뀌었다 — 바로 그 버그다"
    assert not is_contiguous(result), "P0 가 두 조각 — 서비스가 422 로 거부한다"
