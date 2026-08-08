"""회색(미배정) 행 규칙의 **전수 증명** — plan.md §0.2.

§0.2 는 세 가지를 주장한다. 셋 다 작은 정의역에서 전수로 확인한다. 이 저장소에서
"구조적으로 안전하다" 는 추론은 세 번 틀렸고 (HANDOFF.md §5.1·§5.1c), 세 번 다
전수 탐색이 잡았다. 그래서 여기서도 추론하지 않고 센다.

1. **투명성** — `phase_id` 가 null 인 행은 연속성 판정에 보이지 않는다.
   `P0 P0 [회색] P0` 은 위반이 아니다.
2. **회색 행의 자유 이동** — 회색 행을 어디로 옮겨도 break 집합이 변하지 않는다.
   (§0.2-2 "회색 행은 어디로든 드래그 가능" 의 근거.)
3. **`can_create_phase` / `can_create_milestone` 의 정확성** — 플래그가 참인 것과
   "그 행에 새 Phase/Milestone 을 배정했을 때 결과가 연속인 것" 이 **동치**다.
   한쪽 방향(거짓 음성)만 확인하면 지나치게 보수적인 플래그도 통과하므로 양방향을 본다.

3번이 §0.2-4 가 정정한 지점이다. 이전 규칙은 "미배정 행은 항상 경계 → 항상 생성
가능" 이었는데, 한 블록 한가운데 놓인 회색 행에서 만들면 그 블록이 쪼개진다.
"""

from __future__ import annotations

from itertools import product

import pytest

from app.services.renumber_service import (
    RowRef,
    find_contiguity_breaks,
    renumber,
    reposition,
)

#: 회색 행을 뜻하는 표식. 보드 생성기에서 `None` 과 구별해 읽기 쉽게 쓴다.
GRAY = None


def boards_with_gray(n: int):
    """길이 `n` 의 **모든** (phase, milestone) 배정을 만든다 — 회색 포함.

    Phase 는 {None, 0, 1} 에서, Milestone 은 그 Phase 안에서 {None, 0, 1} 에서
    고른다. Phase 가 None 이면 Milestone 도 None 이다 (그 조합만 실재한다 —
    Phase 없이 Milestone 만 있는 행은 §0.2-6 에서 애초에 만들 수 없다).

    연속인 보드만 고르는 것이 아니라 **전부** 만든다. 조각난 보드도 임시저장으로
    실제로 만들어지므로 검사 대상이다.
    """
    cells = [(GRAY, GRAY)]
    for phase in (0, 1):
        for milestone in (GRAY, 0, 1):
            cells.append((phase, milestone))

    for combo in product(cells, repeat=n):
        yield [
            RowRef(item_id=i + 1, phase_id=p, milestone_id=m)
            for i, (p, m) in enumerate(combo)
        ]


def is_contiguous(rows: list[RowRef]) -> bool:
    return find_contiguity_breaks(rows) == []


def drop_gray(rows: list[RowRef]) -> list[RowRef]:
    return [r for r in rows if r.phase_id is not None]


# =============================================================================
# 1. 투명성
# =============================================================================
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_gray_rows_are_invisible_to_the_contiguity_check(n):
    """**전수 증명: 회색 행을 지운 보드와 판정이 같다.**

    투명성의 정의 그 자체를 확인한다. break 의 *유무*뿐 아니라 종류·대상까지
    같아야 한다 — 회색 행이 break 를 만들지도, 가리지도 않는다.
    """
    checked = 0
    for rows in boards_with_gray(n):
        checked += 1
        full = [(b.kind, b.ref_id) for b in find_contiguity_breaks(rows)]
        stripped = [(b.kind, b.ref_id) for b in find_contiguity_breaks(drop_gray(rows))]
        assert full == stripped, f"회색 행이 판정을 바꿨다: {_show(rows)}"

    assert checked > 0


def test_the_scenario_that_used_to_be_rejected():
    """§0.2 가 이름을 붙인 바로 그 배치 — `P0 P0 [회색] P0`.

    이전 구현은 여기서 `PHASE_NOT_CONTIGUOUS` 를 냈다. `prev` 추적에 null 이
    끼어들어 P0 가 "다시 등장" 한 것으로 보였기 때문이다. 그러면 두 P0 행 사이에
    새 행을 놓을 수조차 없다.
    """
    rows = [RowRef(1, 0, 0), RowRef(2, 0, 0), RowRef(3, GRAY, GRAY), RowRef(4, 0, 0)]
    assert find_contiguity_breaks(rows) == []


def test_a_gray_row_does_not_hide_a_real_break():
    """투명성이 눈가리개가 되면 안 된다 — 진짜 조각남은 그대로 잡혀야 한다.

    `P0/M0 · 회색 · P1/M1 · P0/M0` 은 두 층위 모두에서 갈라진다. Phase 가 다시
    등장하면 그 Phase 의 Milestone 도 함께 다시 등장하므로 둘 다 보고되는 것이 맞다.
    보고 위치는 **원본 리스트 인덱스**여야 한다 — 회색 행을 걸러낸 좌표를 그대로
    내보내면 그리드가 엉뚱한 행을 하이라이트한다.
    """
    rows = [RowRef(1, 0, 0), RowRef(2, GRAY, GRAY), RowRef(3, 1, 1), RowRef(4, 0, 0)]
    breaks = find_contiguity_breaks(rows)

    assert [b.kind for b in breaks] == ["phase", "milestone"]
    assert {b.index for b in breaks} == {3}
    assert {b.item_id for b in breaks} == {4}


def test_milestone_transparency_one_level_down():
    """`P0/M1, P0/(미배정), P0/M1` 도 위반이 아니다."""
    rows = [RowRef(1, 0, 0), RowRef(2, 0, GRAY), RowRef(3, 0, 0)]
    assert find_contiguity_breaks(rows) == []


# =============================================================================
# 2. 회색 행은 어디로든 옮길 수 있다
# =============================================================================
@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_moving_a_gray_row_anywhere_never_changes_contiguity(n):
    """**전수 증명: 회색 행의 위치는 판정에 영향이 없다.**

    모든 보드 × 모든 회색 행 × 그 행을 끼워 넣을 수 있는 모든 자리.
    이것이 §0.2-2("회색 행은 블록 제한의 예외")가 안전한 이유다 — 별도 가드가
    아니라 투명성에서 따라 나온다.
    """
    checked = 0
    for rows in boards_with_gray(n):
        before = [(b.kind, b.ref_id) for b in find_contiguity_breaks(rows)]
        for i, row in enumerate(rows):
            if row.phase_id is not None:
                continue
            rest = rows[:i] + rows[i + 1:]
            for j in range(len(rows)):
                moved = rest[:j] + [row] + rest[j:]
                checked += 1
                after = [(b.kind, b.ref_id) for b in find_contiguity_breaks(moved)]
                assert after == before, f"{_show(rows)} → {_show(moved)}"

    assert checked > 0


def test_a_gray_row_can_be_dragged_across_a_phase_boundary():
    """배정된 행이라면 422 가 될 이동도, 회색 행이면 통과한다."""
    rows = [RowRef(1, 0, 0), RowRef(2, 1, 1), RowRef(3, GRAY, GRAY)]
    assert is_contiguous(reposition(rows, [1, 3, 2]))     # P0 · 회색 · P1
    assert is_contiguous(reposition(rows, [3, 1, 2]))     # 회색 · P0 · P1


# =============================================================================
# 3. can_create_phase / can_create_milestone 은 정확하다 (동치)
# =============================================================================
NEW_PHASE = 99
NEW_MILESTONE = 99


def assign_phase(rows: list[RowRef], index: int) -> list[RowRef]:
    """그 행에 **새 Phase** 를 배정한 결과. 새 Phase 에는 Milestone 이 없다."""
    out = list(rows)
    out[index] = RowRef(rows[index].item_id, NEW_PHASE, None)
    return out


def assign_milestone(rows: list[RowRef], index: int) -> list[RowRef]:
    out = list(rows)
    out[index] = RowRef(rows[index].item_id, rows[index].phase_id, NEW_MILESTONE)
    return out


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_can_create_phase_is_exactly_the_set_of_safe_rows(n):
    """**전수 증명: `can_create_phase` ⟺ 새 Phase 배정 후에도 연속.**

    양방향이다.

    * 거짓 음성 — 플래그가 true 인데 결과가 조각나면 UI 가 사용자를 함정에 빠뜨린다.
    * 거짓 양성 — 플래그가 false 인데 결과가 멀쩡하면 **할 수 있는 일을 막는 것**이고,
      §0.2 가 열려던 "사이에 추가" 가 바로 그렇게 막혔었다.

    출발 보드가 이미 조각난 경우는 제외한다. 그때는 "결과가 연속인가" 라는 질문
    자체가 의미가 없다 — 무엇을 해도 조각나 있다.
    """
    checked = 0
    for rows in boards_with_gray(n):
        if not is_contiguous(rows):
            continue
        flags = [r.can_create_phase for r in renumber(rows).rows]
        for index in range(len(rows)):
            checked += 1
            safe = is_contiguous(assign_phase(rows, index))
            assert flags[index] == safe, (
                f"can_create_phase={flags[index]} 인데 실제로는 "
                f"{'연속' if safe else '조각남'}: {_show(rows)} @ {index}"
            )

    assert checked > 0


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_can_create_milestone_is_exactly_the_set_of_safe_rows(n):
    """**전수 증명: `can_create_milestone` ⟺ 새 Milestone 배정 후에도 연속.**

    Phase 가 없는 행은 항상 false 다 (§0.2-6 — 소속시킬 Phase 가 없다). 그 행은
    "배정해 보면 연속인가" 를 물을 수 없으므로 동치 검사에서 빼고 따로 확인한다.
    """
    checked = 0
    for rows in boards_with_gray(n):
        if not is_contiguous(rows):
            continue
        flags = [r.can_create_milestone for r in renumber(rows).rows]
        for index, row in enumerate(rows):
            if row.phase_id is None:
                assert flags[index] is False, f"Phase 없는 행에서 생성 허용: {_show(rows)}"
                continue
            checked += 1
            safe = is_contiguous(assign_milestone(rows, index))
            assert flags[index] == safe, (
                f"can_create_milestone={flags[index]} 인데 실제로는 "
                f"{'연속' if safe else '조각남'}: {_show(rows)} @ {index}"
            )

    assert checked > 0


def test_a_gray_row_inside_one_block_cannot_create_a_phase():
    """§0.2-4 가 정정한 바로 그 경우. 예전 규칙("미배정=항상 경계=항상 가능")은 여기서 틀렸다."""
    rows = [RowRef(1, 0, 0), RowRef(2, GRAY, GRAY), RowRef(3, 0, 0)]
    assert renumber(rows).rows[1].can_create_phase is False
    assert not is_contiguous(assign_phase(rows, 1))       # 막은 이유


def test_a_gray_row_between_two_blocks_can_create_a_phase():
    rows = [RowRef(1, 0, 0), RowRef(2, GRAY, GRAY), RowRef(3, 1, 1)]
    assert renumber(rows).rows[1].can_create_phase is True


def test_a_gray_row_at_either_end_can_create_a_phase():
    rows = [RowRef(1, GRAY, GRAY), RowRef(2, 0, 0), RowRef(3, GRAY, GRAY)]
    flags = [r.can_create_phase for r in renumber(rows).rows]
    assert flags == [True, True, True]


def test_consecutive_gray_rows_do_not_trap_each_other():
    """붙어 있는 회색 행끼리 서로를 가두면 안 된다 (감사 F8 의 원래 논지).

    투명성 덕분에 옆의 회색 행은 이웃 계산에 아예 참여하지 않는다.
    """
    rows = [RowRef(1, 0, 0), RowRef(2, GRAY, GRAY), RowRef(3, GRAY, GRAY), RowRef(4, 1, 1)]
    flags = [r.can_create_phase for r in renumber(rows).rows]
    assert flags[1] is True and flags[2] is True


# =============================================================================
# §0.2-5 — 두 블록 사이 회색 행에서 만든 Phase 는 저절로 가운데 번호를 받는다
# =============================================================================
def test_creating_a_phase_from_a_seam_row_numbers_it_in_between():
    """사용자 시나리오 그대로: P0 블록과 P1 블록 사이 회색 행 → 0, 1, 2.

    특별한 삽입 로직이 없다는 것이 요점이다. first-appearance 재계산이 순서만
    보고 번호를 매기므로, 가운데 자리에서 생긴 Phase 는 가운데 번호를 받는다.
    """
    before = [
        RowRef(1, 10, 100), RowRef(2, 10, 100),
        RowRef(3, GRAY, GRAY),
        RowRef(4, 20, 200), RowRef(5, 20, 200),
    ]
    assert [r.phase_no for r in renumber(before).rows] == [0, 0, None, 1, 1]
    assert renumber(before).rows[2].can_create_phase is True

    after = assign_phase(before, 2)                     # 회색 행에 새 Phase 배정
    assert is_contiguous(after)
    assert [r.phase_no for r in renumber(after).rows] == [0, 0, 1, 2, 2]


def _show(rows: list[RowRef]) -> str:
    return " ".join(
        "·" if r.phase_id is None else f"{r.phase_id}/{'-' if r.milestone_id is None else r.milestone_id}"
        for r in rows
    )
