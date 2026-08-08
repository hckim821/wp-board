"""`validation_service` — plan.md §2.5 의 V1~V14 를 규칙별로 검사한다.

DB 를 쓰지 않는다. 검증이 순수 함수라서 규칙 하나만 깨뜨린 입력을 손으로 만들어
"그 코드 하나만" 나오는지 확인할 수 있다.
"""

from __future__ import annotations

from dataclasses import replace

from app.services import validation_service as V
from app.services.validation_service import (
    MasterRef,
    MilestoneRef,
    PhaseRef,
    ValidationInput,
    ValidationRow,
    validate,
)

P1, P2 = 1, 2
M1, M2, M3 = 10, 11, 20
OWNER, DOC = 100, 200

PHASES = [
    PhaseRef(id=P1, name="Pre-Infrastructure Setup", seq_no=0),
    PhaseRef(id=P2, name="Initiation & Readiness", seq_no=1),
]
MILESTONES = [
    MilestoneRef(id=M1, phase_id=P1, name="환경 Gap", seq_no=1),
    MilestoneRef(id=M2, phase_id=P1, name="I/O 연결", seq_no=2),
    MilestoneRef(id=M3, phase_id=P2, name="Scope 정의", seq_no=1),
]
OWNERS = [MasterRef(id=OWNER, name="DSEP 인프라 담당자")]
DOCS = [MasterRef(id=DOC, name="Project Charter & R&R")]


def row(item_id: int, row_no: int, phase=P1, milestone=M1, **overrides) -> ValidationRow:
    base = ValidationRow(
        item_id=item_id,
        row_no=row_no,
        phase_id=phase,
        milestone_id=milestone,
        title="Key Action Item",
        deliverable="Deliverable",
        document_ids=[DOC],
        owner_ids=[OWNER],
    )
    return replace(base, **overrides)


def make_input(rows=None, **overrides) -> ValidationInput:
    """기본은 **모든 규칙을 통과하는** 보드다. 테스트마다 한 가지만 깨뜨린다."""
    if rows is None:
        rows = [row(1, 1, P1, M1), row(2, 2, P1, M2), row(3, 3, P2, M3)]
    data = ValidationInput(
        rows=rows,
        phases=list(PHASES),
        milestones=list(MILESTONES),
        owners=list(OWNERS),
        document_types=list(DOCS),
        phase_start_no=0,
    )
    return replace(data, **overrides)


def codes(result) -> set[str]:
    return {e.code for e in result.errors}


def warn_codes(result) -> set[str]:
    return {w.code for w in result.warnings}


# =============================================================================
# 기준선
# =============================================================================
def test_a_complete_board_passes_with_no_errors_or_warnings():
    result = validate(make_input())
    assert result.valid
    assert result.errors == []
    assert result.warnings == []


def test_all_rule_violations_are_reported_not_just_the_first():
    """그리드가 오류 셀을 한 번에 표시해야 하므로 첫 오류에서 멈추면 안 된다."""
    broken = row(1, 1, None, None, title="", deliverable="", document_ids=[], owner_ids=[])
    result = validate(make_input(rows=[broken]))
    assert {
        V.PHASE_REQUIRED,
        V.MILESTONE_REQUIRED,
        V.TITLE_REQUIRED,
        V.DELIVERABLE_REQUIRED,
        V.DOCUMENT_REQUIRED,
        V.OWNER_REQUIRED,
    } <= codes(result)


# =============================================================================
# V1 / V2 — Phase · Milestone 필수
# =============================================================================
def test_v1_phase_required():
    result = validate(make_input(rows=[row(1, 1, None, None)]))
    assert V.PHASE_REQUIRED in codes(result)
    issue = next(e for e in result.errors if e.code == V.PHASE_REQUIRED)
    assert (issue.item_id, issue.row_no, issue.field) == (1, 1, "phase_id")


def test_v2_milestone_required():
    result = validate(make_input(rows=[row(1, 1, P1, None)]))
    assert V.MILESTONE_REQUIRED in codes(result)


# =============================================================================
# V3 — Milestone 소속 불일치
# =============================================================================
def test_v3_milestone_belonging_to_another_phase():
    result = validate(make_input(rows=[row(1, 1, P2, M1)]))   # M1 은 P1 소속
    assert V.MILESTONE_PHASE_MISMATCH in codes(result)


def test_v3_passes_when_milestone_matches_its_phase():
    result = validate(make_input(rows=[row(1, 1, P1, M1)]))
    assert V.MILESTONE_PHASE_MISMATCH not in codes(result)


# =============================================================================
# V4 / V5 — 블록 연속성
# =============================================================================
def test_v4_phase_block_split_in_two():
    rows = [row(1, 1, P1, M1), row(2, 2, P2, M3), row(3, 3, P1, M1)]
    result = validate(make_input(rows=rows))
    assert V.PHASE_NOT_CONTIGUOUS in codes(result)
    issue = next(e for e in result.errors if e.code == V.PHASE_NOT_CONTIGUOUS)
    assert issue.row_no == 3          # 다시 나타난 지점을 가리켜야 한다


def test_v4_passes_for_contiguous_blocks():
    assert V.PHASE_NOT_CONTIGUOUS not in codes(validate(make_input()))


def test_v5_milestone_block_split_inside_a_phase():
    rows = [row(1, 1, P1, M1), row(2, 2, P1, M2), row(3, 3, P1, M1)]
    result = validate(make_input(rows=rows))
    assert V.MILESTONE_NOT_CONTIGUOUS in codes(result)
    assert V.PHASE_NOT_CONTIGUOUS not in codes(result)   # Phase 자체는 연속


def test_v5_same_milestone_in_two_phases_is_not_a_contiguity_error():
    """이건 V3 가 잡을 문제다. V5 는 '같은 (phase, milestone) 의 재등장'만 본다."""
    rows = [row(1, 1, P1, M1), row(2, 2, P2, M1)]
    result = validate(make_input(rows=rows))
    assert V.MILESTONE_NOT_CONTIGUOUS not in codes(result)
    assert V.MILESTONE_PHASE_MISMATCH in codes(result)


# =============================================================================
# V6 / V7 — 저장된 seq_no 의 빈틈
# =============================================================================
def test_v6_phase_seq_gap():
    gapped = [PhaseRef(id=P1, name="A", seq_no=0), PhaseRef(id=P2, name="B", seq_no=3)]
    result = validate(make_input(phases=gapped))
    assert V.PHASE_SEQ_GAP in codes(result)


def test_v6_respects_phase_start_no():
    shifted = [PhaseRef(id=P1, name="A", seq_no=1), PhaseRef(id=P2, name="B", seq_no=2)]
    result = validate(make_input(phases=shifted, phase_start_no=1))
    assert V.PHASE_SEQ_GAP not in codes(result)


def test_v6_flags_numbers_that_disagree_with_appearance_order():
    swapped = [PhaseRef(id=P1, name="A", seq_no=1), PhaseRef(id=P2, name="B", seq_no=0)]
    result = validate(make_input(phases=swapped))
    assert V.PHASE_SEQ_GAP in codes(result)


def test_v7_milestone_seq_gap_inside_a_phase():
    gapped = [
        MilestoneRef(id=M1, phase_id=P1, name="a", seq_no=1),
        MilestoneRef(id=M2, phase_id=P1, name="b", seq_no=5),
        MilestoneRef(id=M3, phase_id=P2, name="c", seq_no=1),
    ]
    result = validate(make_input(milestones=gapped))
    assert V.MILESTONE_SEQ_GAP in codes(result)


def test_v7_milestone_numbering_restarts_per_phase():
    """Phase 2 의 첫 Milestone 도 1 이어야 한다 (전역 일련번호가 아니다)."""
    continued = [
        MilestoneRef(id=M1, phase_id=P1, name="a", seq_no=1),
        MilestoneRef(id=M2, phase_id=P1, name="b", seq_no=2),
        MilestoneRef(id=M3, phase_id=P2, name="c", seq_no=3),
    ]
    result = validate(make_input(milestones=continued))
    assert V.MILESTONE_SEQ_GAP in codes(result)


# =============================================================================
# V8 ~ V11 — 행 필수값
# =============================================================================
def test_v8_document_required():
    result = validate(make_input(rows=[row(1, 1, document_ids=[])]))
    assert V.DOCUMENT_REQUIRED in codes(result)


def test_v9_owner_required():
    result = validate(make_input(rows=[row(1, 1, owner_ids=[])]))
    assert V.OWNER_REQUIRED in codes(result)
    issue = next(e for e in result.errors if e.code == V.OWNER_REQUIRED)
    assert issue.field == "owners"
    assert "1행" in issue.message


def test_v10_title_required():
    assert V.TITLE_REQUIRED in codes(validate(make_input(rows=[row(1, 1, title=None)])))


def test_v10_whitespace_only_title_counts_as_empty():
    assert V.TITLE_REQUIRED in codes(validate(make_input(rows=[row(1, 1, title="   ")])))


def test_v11_deliverable_required():
    assert V.DELIVERABLE_REQUIRED in codes(
        validate(make_input(rows=[row(1, 1, deliverable="")]))
    )


# =============================================================================
# V12 — 비활성 기준정보 참조
# =============================================================================
def test_v12_inactive_document_reference():
    inactive = [MasterRef(id=DOC, name="폐기된 문서", is_active=False)]
    result = validate(make_input(document_types=inactive))
    assert V.INACTIVE_REFERENCE in codes(result)


def test_v12_inactive_owner_reference():
    inactive = [MasterRef(id=OWNER, name="퇴직자", is_active=False)]
    result = validate(make_input(owners=inactive))
    issues = [e for e in result.errors if e.code == V.INACTIVE_REFERENCE]
    assert issues and all(i.field == "owners" for i in issues)


# =============================================================================
# V13 — 빈 버전
# =============================================================================
def test_v13_empty_version_cannot_be_published():
    result = validate(make_input(rows=[]))
    assert not result.valid
    assert codes(result) == {V.EMPTY_VERSION}


# =============================================================================
# V14 — 쓰이지 않는 기준정보 (warning)
# =============================================================================
def test_v14_orphan_phase_is_a_warning_not_an_error():
    rows = [row(1, 1, P1, M1), row(2, 2, P1, M2)]      # P2 를 아무도 안 씀
    result = validate(make_input(rows=rows))
    assert result.valid                                  # 발행을 막지 않는다
    assert V.ORPHAN_PHASE in warn_codes(result)
    assert V.ORPHAN_MILESTONE in warn_codes(result)      # M3 도 함께 뜬다


def test_v14_ignores_inactive_master_data():
    phases = [PHASES[0], PhaseRef(id=P2, name="보류", seq_no=1, is_active=False)]
    milestones = [
        MILESTONES[0],
        MILESTONES[1],
        MilestoneRef(id=M3, phase_id=P2, name="보류", seq_no=1, is_active=False),
    ]
    rows = [row(1, 1, P1, M1), row(2, 2, P1, M2)]
    result = validate(make_input(rows=rows, phases=phases, milestones=milestones))
    assert result.warnings == []


def test_v14_warning_carries_the_phase_id_for_the_ui():
    rows = [row(1, 1, P1, M1), row(2, 2, P1, M2)]
    result = validate(make_input(rows=rows))
    orphan = next(w for w in result.warnings if w.code == V.ORPHAN_PHASE)
    assert orphan.phase_id == P2
    assert orphan.level == "warning"


# =============================================================================
# 위치 정보 — V13 을 뺀 모든 오류가 셀을 짚을 수 있어야 한다 (plan.md §2.5)
# =============================================================================
def test_v6_points_at_the_first_row_of_the_offending_phase():
    gapped = [PhaseRef(id=P1, name="A", seq_no=0), PhaseRef(id=P2, name="B", seq_no=3)]
    result = validate(make_input(phases=gapped))
    issue = next(e for e in result.errors if e.code == V.PHASE_SEQ_GAP)
    assert issue.item_id == 3 and issue.row_no == 3      # P2 의 첫 행
    assert issue.field == "phase_id"
    assert issue.phase_id == P2


def test_v7_points_at_the_first_row_of_the_offending_milestone():
    gapped = [
        MilestoneRef(id=M1, phase_id=P1, name="a", seq_no=1),
        MilestoneRef(id=M2, phase_id=P1, name="b", seq_no=5),
        MilestoneRef(id=M3, phase_id=P2, name="c", seq_no=1),
    ]
    result = validate(make_input(milestones=gapped))
    issue = next(e for e in result.errors if e.code == V.MILESTONE_SEQ_GAP)
    assert issue.item_id == 2 and issue.row_no == 2      # M2 의 첫 행
    assert issue.field == "milestone_id"
    assert issue.milestone_id == M2


#: 코드별로 그 코드를 **실제로 발생시키는** 입력. 아래 테스트가 이 표가
#: 모듈 상수를 전부 덮는지 검사하므로, 새 코드를 추가하면 여기에 시나리오를
#: 넣기 전까지 테스트가 실패한다 — 닫히는 쪽으로 실패한다.
def _scenarios() -> dict[str, ValidationInput]:
    gapped_phases = [PhaseRef(id=P1, name="A", seq_no=0), PhaseRef(id=P2, name="B", seq_no=9)]
    gapped_ms = [
        MilestoneRef(id=M1, phase_id=P1, name="a", seq_no=1),
        MilestoneRef(id=M2, phase_id=P1, name="b", seq_no=7),
        MilestoneRef(id=M3, phase_id=P2, name="c", seq_no=1),
    ]
    only_p1 = [row(1, 1, P1, M1), row(2, 2, P1, M2)]

    return {
        V.PHASE_REQUIRED: make_input(rows=[row(1, 1, None, None)]),
        V.MILESTONE_REQUIRED: make_input(rows=[row(1, 1, P1, None)]),
        V.MILESTONE_PHASE_MISMATCH: make_input(rows=[row(1, 1, P2, M1)]),
        V.PHASE_NOT_CONTIGUOUS: make_input(
            rows=[row(1, 1, P1, M1), row(2, 2, P2, M3), row(3, 3, P1, M1)]
        ),
        V.MILESTONE_NOT_CONTIGUOUS: make_input(
            rows=[row(1, 1, P1, M1), row(2, 2, P1, M2), row(3, 3, P1, M1)]
        ),
        V.PHASE_SEQ_GAP: make_input(phases=gapped_phases),
        V.MILESTONE_SEQ_GAP: make_input(milestones=gapped_ms),
        V.DOCUMENT_REQUIRED: make_input(rows=[row(1, 1, document_ids=[])]),
        V.OWNER_REQUIRED: make_input(rows=[row(1, 1, owner_ids=[])]),
        V.TITLE_REQUIRED: make_input(rows=[row(1, 1, title="  ")]),
        V.DELIVERABLE_REQUIRED: make_input(rows=[row(1, 1, deliverable="")]),
        V.INACTIVE_REFERENCE: make_input(
            document_types=[MasterRef(id=DOC, name="폐기된 문서", is_active=False)]
        ),
        V.EMPTY_VERSION: make_input(rows=[]),
        V.ORPHAN_PHASE: make_input(rows=only_p1),
        V.ORPHAN_MILESTONE: make_input(rows=only_p1),
    }


def declared_codes() -> set[str]:
    """모듈이 선언한 오류/경고 코드 전부.

    상수 이름과 값이 같은 대문자 문자열만 고른다. 목록을 테스트에 손으로 적으면
    새 코드가 생겨도 조용히 통과하므로, **모듈에서 파생**시킨다.
    """
    return {
        name
        for name, value in vars(V).items()
        if name.isupper() and isinstance(value, str) and value == name
    }


#: 위치 정보를 요구하지 않는 코드 — 특정 행에 속하지 않는 것들.
LOCATION_EXEMPT = {V.EMPTY_VERSION, V.ORPHAN_PHASE, V.ORPHAN_MILESTONE}


def test_the_scenario_table_covers_every_declared_code():
    """새 코드를 추가하면 시나리오를 쓰기 전까지 여기서 막힌다."""
    missing = declared_codes() - set(_scenarios())
    assert missing == set(), f"시나리오가 없는 코드: {sorted(missing)}"

    unknown = set(_scenarios()) - declared_codes()
    assert unknown == set(), f"모듈에 없는 코드의 시나리오: {sorted(unknown)}"


def test_every_scenario_actually_produces_its_code():
    """시나리오가 의도한 코드를 정말 내는지 — 표가 썩지 않도록."""
    not_produced = []
    for code, data in _scenarios().items():
        result = validate(data)
        produced = {i.code for i in result.errors} | {i.code for i in result.warnings}
        if code not in produced:
            not_produced.append(code)
    assert not_produced == [], f"시나리오가 코드를 내지 못함: {sorted(not_produced)}"


def test_every_error_carries_a_cell_location():
    """그리드가 짚을 수 없는 오류는 사용자에게 무의미하다 (plan.md §2.5).

    면제는 특정 행에 속하지 않는 코드뿐이다.
    """
    offenders = []
    for code, data in _scenarios().items():
        if code in LOCATION_EXEMPT:
            continue
        for issue in validate(data).errors:
            if issue.code in LOCATION_EXEMPT:
                continue
            if issue.item_id is None or issue.row_no is None or issue.field is None:
                offenders.append(
                    f"{issue.code} (item_id={issue.item_id} row_no={issue.row_no} "
                    f"field={issue.field})"
                )
    assert offenders == [], f"위치 정보가 없는 오류: {sorted(set(offenders))}"


def test_warnings_identify_the_master_data_they_refer_to():
    """경고는 행이 아니라 기준정보를 가리킨다 — 그쪽 식별자는 있어야 한다."""
    for warning in validate(_scenarios()[V.ORPHAN_PHASE]).warnings:
        assert warning.phase_id is not None, warning
        if warning.code == V.ORPHAN_MILESTONE:
            assert warning.milestone_id is not None, warning
