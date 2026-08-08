"""`renumber_service` — plan.md §2.2 / §2.3 의 불변식.

DB 를 전혀 쓰지 않는다. 재계산 로직이 순수 함수라서 가능한 일이고, 그래서
"삽입 / 드래그 이동 / 삭제 / Phase 경계 이동 / Phase 가 비는 경우" 를 조합으로
전수 검사할 수 있다.
"""

from __future__ import annotations

from app.services.renumber_service import (
    RowRef,
    find_contiguity_breaks,
    renumber,
)

# Phase 0 (milestone 10, 11) / Phase 1 (milestone 20) / Phase 2 (milestone 30)
BOARD = [
    RowRef(1, 100, 10),
    RowRef(2, 100, 10),
    RowRef(3, 100, 11),
    RowRef(4, 200, 20),
    RowRef(5, 200, 20),
    RowRef(6, 300, 30),
]


def phase_nos(rows: list[RowRef], start: int = 0) -> list[int | None]:
    return [r.phase_no for r in renumber(rows, start).rows]


def ms_display(rows: list[RowRef], start: int = 0) -> list[str | None]:
    return [r.milestone_display_no() for r in renumber(rows, start).rows]


def is_contiguous(rows: list[RowRef]) -> bool:
    """같은 Phase 가 한 덩어리로만 나타나고, Milestone 도 Phase 안에서 한 덩어리인가.

    **`find_contiguity_breaks` 와 독립된 판정기다.** 일부러 다른 방식으로 쓴다 —
    "각 키가 등장하는 인덱스들이 (회색 행을 걸러낸 좌표에서) 하나의 연속 구간인가"
    를 직접 본다. 같은 알고리즘을 두 번 쓰면 서로를 검증하지 못한다.

    미배정 행은 걸러낸다 (plan.md §0.2-1 투명성).
    """
    def one_run(keys: list) -> bool:
        positions: dict = {}
        for index, key in enumerate(keys):
            positions.setdefault(key, []).append(index)
        return all(
            span == list(range(span[0], span[-1] + 1)) for span in positions.values()
        )

    assigned = [r for r in rows if r.phase_id is not None]
    if not one_run([r.phase_id for r in assigned]):
        return False
    with_ms = [r for r in assigned if r.milestone_id is not None]
    return one_run([(r.phase_id, r.milestone_id) for r in with_ms])


# =============================================================================
# 번호 부여
# =============================================================================
def test_numbers_follow_first_appearance_order():
    assert phase_nos(BOARD) == [0, 0, 0, 1, 1, 2]


def test_phase_start_no_shifts_every_phase_number():
    assert phase_nos(BOARD, start=1) == [1, 1, 1, 2, 2, 3]


def test_milestone_number_restarts_inside_each_phase():
    assert ms_display(BOARD) == ["0.1", "0.1", "0.2", "1.1", "1.1", "2.1"]


def test_milestone_major_is_derived_not_stored():
    """Phase 시작번호를 바꾸면 Milestone 앞자리가 **따라 움직여야** 한다.

    앞자리를 따로 저장했다면 여기서 어긋난다.
    """
    assert ms_display(BOARD, start=5) == ["5.1", "5.1", "5.2", "6.1", "6.1", "7.1"]


def test_sort_order_is_dense_from_one():
    result = renumber(BOARD)
    assert [r.sort_order for r in result.rows] == [1, 2, 3, 4, 5, 6]


def test_master_seq_maps_are_returned_for_persistence():
    result = renumber(BOARD)
    assert result.phase_seq == {100: 0, 200: 1, 300: 2}
    assert result.milestone_seq == {10: 1, 11: 2, 20: 1, 30: 1}


# =============================================================================
# 경계 판정 (§2.3)
# =============================================================================
def test_phase_block_boundaries():
    rows = renumber(BOARD).rows
    assert [r.is_phase_block_start for r in rows] == [True, False, False, True, False, True]
    assert [r.is_phase_block_end for r in rows] == [False, False, True, False, True, True]


def test_milestone_boundaries_are_scoped_to_the_phase_block():
    rows = renumber(BOARD).rows
    assert [r.is_milestone_block_start for r in rows] == [True, False, True, True, False, True]
    assert [r.is_milestone_block_end for r in rows] == [False, True, True, False, True, True]


def test_new_phase_only_from_a_boundary_row():
    """블록 중간 행에서 새 Phase 를 만들면 기존 Phase 가 두 조각으로 쪼개진다."""
    rows = renumber(BOARD).rows
    assert [r.can_create_phase for r in rows] == [True, False, True, True, True, True]


def test_single_row_block_is_both_boundaries():
    rows = renumber(BOARD).rows
    last = rows[-1]  # Phase 2 는 행이 하나뿐
    assert last.is_phase_block_start and last.is_phase_block_end
    assert last.can_create_phase


# =============================================================================
# 미지정(NULL) 행 — 임시저장 경로
# =============================================================================
def test_unassigned_row_gets_no_number():
    rows = [RowRef(1, 100, 10), RowRef(2, None, None), RowRef(3, 200, 20)]
    result = renumber(rows)
    assert [r.phase_no for r in result.rows] == [0, None, 1]
    assert result.rows[1].milestone_display_no() is None


def test_unassigned_row_does_not_consume_a_phase_number():
    """미지정 행이 끼었다고 뒤 Phase 번호가 밀리면 안 된다."""
    with_gap = [RowRef(1, 100, 10), RowRef(2, None, None), RowRef(3, 200, 20)]
    without = [RowRef(1, 100, 10), RowRef(3, 200, 20)]
    assert renumber(with_gap).phase_seq == renumber(without).phase_seq


def test_milestone_without_phase_gets_no_number():
    rows = [RowRef(1, None, 10)]
    assert renumber(rows).rows[0].milestone_no is None


def test_empty_board():
    assert renumber([]).rows == []


# =============================================================================
# 행 추가 — 회색 행 (plan.md §0.2)
#
# 상속(`inherit_at`)은 삭제됐다. 신규 행은 어느 경로로 들어오든 미배정이고,
# 연속성은 상속이 아니라 **투명성**에서 나온다.
# =============================================================================
def test_a_new_gray_row_never_breaks_contiguity_wherever_it_lands():
    """어느 자리에 넣어도 연속이다 — 전수 (BOARD 길이 6 → 자리 7개)."""
    for index in range(len(BOARD) + 1):
        rows = BOARD[:index] + [RowRef(99, None, None)] + BOARD[index:]
        assert is_contiguous(rows), f"index={index}"
        assert find_contiguity_breaks(rows) == [], f"index={index}"


def test_a_gray_row_does_not_shift_any_existing_number():
    """회색 행은 번호를 소비하지 않는다 — 끼워 넣어도 기존 번호가 그대로다."""
    before = [r.phase_no for r in renumber(BOARD).rows]
    for index in range(len(BOARD) + 1):
        rows = BOARD[:index] + [RowRef(99, None, None)] + BOARD[index:]
        after = [r.phase_no for r in renumber(rows).rows if r.item_id != 99]
        assert after == before, f"index={index}"


# =============================================================================
# 삭제
# =============================================================================
def test_delete_renumbers_the_remaining_rows():
    remaining = [r for r in BOARD if r.item_id != 2]
    result = renumber(remaining)
    assert [r.sort_order for r in result.rows] == [1, 2, 3, 4, 5]
    assert [r.phase_no for r in result.rows] == [0, 0, 1, 1, 2]


def test_deleting_the_last_row_of_a_phase_drops_that_phase_number():
    remaining = [r for r in BOARD if r.item_id != 6]   # Phase 2 의 유일한 행
    result = renumber(remaining)
    assert result.phase_seq == {100: 0, 200: 1}


def test_deleting_a_milestone_block_pulls_later_milestones_up():
    remaining = [r for r in BOARD if r.item_id not in (1, 2)]  # milestone 10 이 사라짐
    result = renumber(remaining)
    assert result.milestone_seq[11] == 1


# =============================================================================
# 연속성 검사 — 소속을 명시적으로 받는 경로의 안전망
# =============================================================================
def test_a_well_formed_board_has_no_breaks():
    assert find_contiguity_breaks(BOARD) == []


def test_a_split_phase_block_is_detected():
    rows = [RowRef(1, 100, 10), RowRef(2, 200, 20), RowRef(3, 100, 10)]
    breaks = find_contiguity_breaks(rows)
    assert [(b.index, b.kind, b.ref_id) for b in breaks] == [
        (2, "phase", 100),
        (2, "milestone", 10),
    ]


def test_a_split_milestone_block_inside_one_phase_is_detected():
    rows = [RowRef(1, 100, 10), RowRef(2, 100, 11), RowRef(3, 100, 10)]
    breaks = find_contiguity_breaks(rows)
    assert [(b.index, b.kind) for b in breaks] == [(2, "milestone")]


def test_the_same_milestone_id_under_two_phases_is_not_a_contiguity_break():
    """그건 V3(MILESTONE_PHASE_MISMATCH)가 잡을 문제다."""
    rows = [RowRef(1, 100, 10), RowRef(2, 200, 10)]
    assert [b.kind for b in find_contiguity_breaks(rows)] == []


def test_unassigned_rows_are_not_contiguity_breaks():
    """미배정 행은 검사에 **투명**하다 (plan.md §0.2-1)."""
    rows = [RowRef(1, None, None), RowRef(2, 100, 10), RowRef(3, None, None)]
    assert find_contiguity_breaks(rows) == []


def test_a_gray_row_inside_a_block_is_not_a_break():
    """`P0 P0 [회색] P0` — §0.2 가 이름을 붙인 배치. 예전엔 여기서 422 였다."""
    rows = [RowRef(1, 100, 10), RowRef(2, 100, 10), RowRef(3, None, None), RowRef(4, 100, 10)]
    assert find_contiguity_breaks(rows) == []
    assert is_contiguous(rows)


def test_breaks_point_at_the_row_where_the_block_reappears():
    rows = [RowRef(1, 100, 10), RowRef(2, 100, 10), RowRef(3, 200, 20), RowRef(4, 100, 10)]
    assert find_contiguity_breaks(rows)[0].item_id == 4


# =============================================================================
# 회색(미배정) 행의 경계·생성 판정 — plan.md §0.2-4
#
# **경계인 것과 생성 가능한 것은 다르다.** 예전 규칙("미배정 행은 항상 경계이므로
# 항상 새 Phase 생성 가능")은 후자에서 틀렸다. 전수 동치 증명은
# `test_gray_row_exhaustive.py` 에 있고, 여기서는 대표 배치를 고정한다.
# =============================================================================
def test_an_unassigned_row_is_always_its_own_block():
    rows = [RowRef(1, None, None), RowRef(2, None, None), RowRef(3, None, None)]
    numbered = renumber(rows).rows
    assert all(r.is_phase_block_start and r.is_phase_block_end for r in numbered)
    # 배정된 이웃이 아예 없으므로 어디서 만들어도 쪼갤 블록이 없다.
    assert all(r.can_create_phase for r in numbered)


def test_a_gray_row_in_the_middle_of_one_block_cannot_create_a_phase():
    """**경계이지만 생성은 불가**. 만들면 P100 이 두 조각으로 쪼개진다."""
    rows = [RowRef(1, 100, 10), RowRef(2, None, None), RowRef(3, 100, 10)]
    gray = renumber(rows).rows[1]

    assert gray.is_phase_block_start and gray.is_phase_block_end
    assert gray.can_create_phase is False
    assert gray.can_create_milestone is False       # Phase 가 없으면 애초에 불가


def test_a_gray_row_between_two_different_blocks_can_create_a_phase():
    """§0.2-5 의 "사이에 추가" 가 열리는 자리."""
    rows = [RowRef(1, 100, 10), RowRef(2, None, None), RowRef(3, 200, 20)]
    assert renumber(rows).rows[1].can_create_phase is True


def test_a_gray_row_with_a_phase_but_no_milestone_follows_the_same_rule():
    """한 단계 아래에서도 같다 — Milestone 블록 한가운데면 불가."""
    inside = [RowRef(1, 100, 10), RowRef(2, 100, None), RowRef(3, 100, 10)]
    assert renumber(inside).rows[1].can_create_milestone is False

    seam = [RowRef(1, 100, 10), RowRef(2, 100, None), RowRef(3, 100, 11)]
    assert renumber(seam).rows[1].can_create_milestone is True


def test_boundary_flags_see_through_a_gray_row():
    """`P0 [회색] P0` 의 뒤쪽 P0 는 새 블록의 시작이 아니다.

    투명성이 경계 판정에도 적용되지 않으면, 그리드가 한 블록을 두 블록처럼 그리고
    §2.3 의 드롭다운 규칙도 어긋난다.
    """
    rows = renumber([RowRef(1, 100, 10), RowRef(2, None, None), RowRef(3, 100, 10)]).rows
    assert rows[0].is_phase_block_start is True
    assert rows[0].is_phase_block_end is False      # 회색 행 너머로 블록이 이어진다
    assert rows[2].is_phase_block_start is False
    assert rows[2].is_phase_block_end is True
