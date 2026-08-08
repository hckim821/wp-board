"""발행 검증 — plan.md §2.5 의 V1~V14.

**순수 함수다.** DB 를 모르므로 규칙 하나하나를 DB 없이 테스트할 수 있다.
DB 에서 입력을 모아 오는 일은 `version_service.build_validation_input()` 이 한다.

두 저장 경로의 계약이 다르다는 점이 이 모듈의 존재 이유다.

* **임시저장** — 검증 없음. 필수값 누락도, Phase 미지정도 그대로 저장한다.
  (참조 무결성만 API 레이어가 400 으로 막는다.)
* **발행** — 아래 전체 규칙. 실패하면 상태를 바꾸지 않고 오류 목록을 돌려준다.

응답에는 그리드가 셀을 바로 하이라이트할 수 있도록 `item_id` / `row_no` /
`field` 위치 정보를 담는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- 오류 코드 ---------------------------------------------------------------
PHASE_REQUIRED = "PHASE_REQUIRED"                        # V1
MILESTONE_REQUIRED = "MILESTONE_REQUIRED"                # V2
MILESTONE_PHASE_MISMATCH = "MILESTONE_PHASE_MISMATCH"    # V3
PHASE_NOT_CONTIGUOUS = "PHASE_NOT_CONTIGUOUS"            # V4
MILESTONE_NOT_CONTIGUOUS = "MILESTONE_NOT_CONTIGUOUS"    # V5
PHASE_SEQ_GAP = "PHASE_SEQ_GAP"                          # V6
MILESTONE_SEQ_GAP = "MILESTONE_SEQ_GAP"                  # V7
DOCUMENT_REQUIRED = "DOCUMENT_REQUIRED"                  # V8
OWNER_REQUIRED = "OWNER_REQUIRED"                        # V9
TITLE_REQUIRED = "TITLE_REQUIRED"                        # V10
DELIVERABLE_REQUIRED = "DELIVERABLE_REQUIRED"            # V11
INACTIVE_REFERENCE = "INACTIVE_REFERENCE"                # V12
EMPTY_VERSION = "EMPTY_VERSION"                          # V13
ORPHAN_PHASE = "ORPHAN_PHASE"                            # V14 (warning)
#: V14 의 확장. 규칙표에는 Phase 만 있으나, 쓰이지 않는 Milestone 도 같은 성격의
#: 잔여 기준정보이므로 별도 코드로 경고한다. warning 이라 발행을 막지 않는다.
ORPHAN_MILESTONE = "ORPHAN_MILESTONE"


# =============================================================================
# 입출력 자료구조
# =============================================================================
@dataclass(frozen=True)
class ValidationRow:
    item_id: int
    row_no: int
    phase_id: int | None
    milestone_id: int | None
    title: str | None
    deliverable: str | None
    document_ids: list[int]
    owner_ids: list[int]


@dataclass(frozen=True)
class PhaseRef:
    id: int
    name: str
    seq_no: int
    is_active: bool = True


@dataclass(frozen=True)
class MilestoneRef:
    id: int
    phase_id: int
    name: str
    seq_no: int
    is_active: bool = True


@dataclass(frozen=True)
class MasterRef:
    """Owner / DocumentType 공통 — 활성 여부 판정에만 쓴다."""

    id: int
    name: str
    is_active: bool = True


@dataclass(frozen=True)
class ValidationInput:
    rows: list[ValidationRow]
    phases: list[PhaseRef]
    milestones: list[MilestoneRef]
    owners: list[MasterRef]
    document_types: list[MasterRef]
    phase_start_no: int = 0


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    level: str
    message: str
    item_id: int | None = None
    row_no: int | None = None
    field: str | None = None
    phase_id: int | None = None
    milestone_id: int | None = None


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)


def _err(code: str, message: str, **loc) -> ValidationIssue:
    return ValidationIssue(code=code, level="error", message=message, **loc)


def _warn(code: str, message: str, **loc) -> ValidationIssue:
    return ValidationIssue(code=code, level="warning", message=message, **loc)


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


# =============================================================================
# 검증
# =============================================================================
def validate(data: ValidationInput) -> ValidationResult:
    """V1~V14 를 모두 수행한다. 첫 오류에서 멈추지 않는다.

    그리드가 오류 셀을 한 번에 전부 표시해야 하므로, 규칙을 통과하지 못한
    행을 모아서 돌려준다.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    rows = data.rows

    phase_by_id = {p.id: p for p in data.phases}
    ms_by_id = {m.id: m for m in data.milestones}
    owner_by_id = {o.id: o for o in data.owners}
    doc_by_id = {d.id: d for d in data.document_types}

    # --- V13: 행 0개인 버전 발행 금지 ----------------------------------------
    if not rows:
        errors.append(_err(EMPTY_VERSION, "행이 하나도 없는 버전은 발행할 수 없습니다."))
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    # --- 행 단위 규칙 (V1, V2, V3, V8~V12) -----------------------------------
    for row in rows:
        n = row.row_no
        if row.phase_id is None:
            errors.append(_err(PHASE_REQUIRED, f"{n}행: Phase가 지정되지 않았습니다.",
                               item_id=row.item_id, row_no=n, field="phase_id"))
        if row.milestone_id is None:
            errors.append(_err(MILESTONE_REQUIRED, f"{n}행: Milestone이 지정되지 않았습니다.",
                               item_id=row.item_id, row_no=n, field="milestone_id"))

        # V3 — Milestone 의 소속 Phase 와 행의 Phase 가 어긋나면 표시번호를 만들 수 없다.
        if row.milestone_id is not None and row.phase_id is not None:
            ms = ms_by_id.get(row.milestone_id)
            if ms is not None and ms.phase_id != row.phase_id:
                errors.append(_err(
                    MILESTONE_PHASE_MISMATCH,
                    f"{n}행: Milestone '{ms.name}'은(는) 이 행의 Phase에 속하지 않습니다.",
                    item_id=row.item_id, row_no=n, field="milestone_id",
                    phase_id=row.phase_id, milestone_id=row.milestone_id))

        if not row.document_ids:
            errors.append(_err(DOCUMENT_REQUIRED, f"{n}행: 관련 문서가 지정되지 않았습니다.",
                               item_id=row.item_id, row_no=n, field="documents"))
        if not row.owner_ids:
            errors.append(_err(OWNER_REQUIRED, f"{n}행: Owner가 지정되지 않았습니다.",
                               item_id=row.item_id, row_no=n, field="owners"))
        if _blank(row.title):
            errors.append(_err(TITLE_REQUIRED, f"{n}행: Key Action Item이 비어 있습니다.",
                               item_id=row.item_id, row_no=n, field="title"))
        if _blank(row.deliverable):
            errors.append(_err(DELIVERABLE_REQUIRED, f"{n}행: Deliverable이 비어 있습니다.",
                               item_id=row.item_id, row_no=n, field="deliverable"))

        # V12 — 비활성 기준정보 참조
        for doc_id in row.document_ids:
            doc = doc_by_id.get(doc_id)
            if doc is not None and not doc.is_active:
                errors.append(_err(
                    INACTIVE_REFERENCE,
                    f"{n}행: 비활성 문서 '{doc.name}'을(를) 참조하고 있습니다.",
                    item_id=row.item_id, row_no=n, field="documents"))
        for owner_id in row.owner_ids:
            owner = owner_by_id.get(owner_id)
            if owner is not None and not owner.is_active:
                errors.append(_err(
                    INACTIVE_REFERENCE,
                    f"{n}행: 비활성 Owner '{owner.name}'을(를) 참조하고 있습니다.",
                    item_id=row.item_id, row_no=n, field="owners"))

    # --- V4: Phase 블록 연속성 ------------------------------------------------
    # 같은 Phase 가 두 번째 "덩어리"로 다시 나타나면 연속성이 깨진 것이다.
    seen_phase: set[int] = set()
    prev_phase: int | None = None
    first_run = True
    for row in rows:
        if first_run or row.phase_id != prev_phase:
            if row.phase_id is not None and row.phase_id in seen_phase:
                name = phase_by_id[row.phase_id].name if row.phase_id in phase_by_id else row.phase_id
                errors.append(_err(
                    PHASE_NOT_CONTIGUOUS,
                    f"Phase '{name}' 블록이 연속되지 않습니다. ({row.row_no}행)",
                    item_id=row.item_id, row_no=row.row_no, field="phase_id",
                    phase_id=row.phase_id))
            if row.phase_id is not None:
                seen_phase.add(row.phase_id)
            prev_phase = row.phase_id
            first_run = False

    # --- V5: Milestone 블록 연속성 (Phase 내부) --------------------------------
    seen_ms: set[tuple[int | None, int]] = set()
    prev_key: tuple[int | None, int | None] | None = None
    for row in rows:
        key = (row.phase_id, row.milestone_id)
        if key != prev_key:
            if row.milestone_id is not None and (row.phase_id, row.milestone_id) in seen_ms:
                name = ms_by_id[row.milestone_id].name if row.milestone_id in ms_by_id else row.milestone_id
                errors.append(_err(
                    MILESTONE_NOT_CONTIGUOUS,
                    f"Milestone '{name}' 블록이 연속되지 않습니다. ({row.row_no}행)",
                    item_id=row.item_id, row_no=row.row_no, field="milestone_id",
                    phase_id=row.phase_id, milestone_id=row.milestone_id))
            if row.milestone_id is not None:
                seen_ms.add((row.phase_id, row.milestone_id))
            prev_key = key

    # --- V6/V7: 기준정보에 저장된 seq_no 의 빈틈 -------------------------------
    #
    # 조회 시 표시번호는 행 순서에서 파생하므로 언제나 촘촘하다. 그럼에도 이
    # 규칙이 필요한 이유는 기준정보 CRUD 화면에서 `seq_no` 를 직접 손댈 수 있기
    # 때문이다. 여기서는 **저장된 seq_no** 가 최초 등장 순서와 일치하고 빈틈이
    # 없는지를 본다. (발행은 저장 직전에 재계산을 수행하므로 정상 흐름에서는
    # 통과하고, 이 규칙은 기준정보가 어긋났을 때의 안전망으로 동작한다.)
    used_phase_order: list[int] = []
    for row in rows:
        if row.phase_id is not None and row.phase_id not in used_phase_order:
            used_phase_order.append(row.phase_id)

    # 위치 정보는 그 Phase 의 **첫 행**을 가리킨다 — 셀을 짚을 수 없는 오류는
    # 사용자에게 무의미하기 때문이다 (plan.md §2.5 필수 요건 2).
    first_row_of_phase = {}
    for row in rows:
        if row.phase_id is not None and row.phase_id not in first_row_of_phase:
            first_row_of_phase[row.phase_id] = row

    expected = list(range(data.phase_start_no, data.phase_start_no + len(used_phase_order)))
    actual = [phase_by_id[p].seq_no for p in used_phase_order if p in phase_by_id]
    if len(actual) == len(expected) and actual != expected:
        culprit = next(
            (p for p, want in zip(used_phase_order, expected)
             if p in phase_by_id and phase_by_id[p].seq_no != want),
            used_phase_order[0] if used_phase_order else None,
        )
        anchor = first_row_of_phase.get(culprit)
        errors.append(_err(
            PHASE_SEQ_GAP,
            f"Phase 번호가 {data.phase_start_no}부터 빈틈없이 이어지지 않습니다. "
            f"(저장값 {actual} / 기대값 {expected})",
            item_id=anchor.item_id if anchor else None,
            row_no=anchor.row_no if anchor else None,
            field="phase_id",
            phase_id=culprit))

    used_ms_by_phase: dict[int, list[int]] = {}
    for row in rows:
        if row.phase_id is None or row.milestone_id is None:
            continue
        bucket = used_ms_by_phase.setdefault(row.phase_id, [])
        if row.milestone_id not in bucket:
            bucket.append(row.milestone_id)
    first_row_of_ms = {}
    for row in rows:
        if row.milestone_id is not None and row.milestone_id not in first_row_of_ms:
            first_row_of_ms[row.milestone_id] = row

    for phase_id, ms_ids in used_ms_by_phase.items():
        expected_ms = list(range(1, len(ms_ids) + 1))
        actual_ms = [ms_by_id[m].seq_no for m in ms_ids if m in ms_by_id]
        if len(actual_ms) == len(expected_ms) and actual_ms != expected_ms:
            pname = phase_by_id[phase_id].name if phase_id in phase_by_id else phase_id
            culprit = next(
                (m for m, want in zip(ms_ids, expected_ms)
                 if m in ms_by_id and ms_by_id[m].seq_no != want),
                ms_ids[0],
            )
            anchor = first_row_of_ms.get(culprit)
            errors.append(_err(
                MILESTONE_SEQ_GAP,
                f"Phase '{pname}'의 Milestone 번호가 1부터 빈틈없이 이어지지 않습니다. "
                f"(저장값 {actual_ms} / 기대값 {expected_ms})",
                item_id=anchor.item_id if anchor else None,
                row_no=anchor.row_no if anchor else None,
                field="milestone_id", phase_id=phase_id, milestone_id=culprit))

    # --- V14: 사용되지 않는 기준정보 (warning) ---------------------------------
    used_phases = {r.phase_id for r in rows if r.phase_id is not None}
    for phase in data.phases:
        if phase.is_active and phase.id not in used_phases:
            warnings.append(_warn(
                ORPHAN_PHASE, f"Phase '{phase.name}'에 속한 항목이 없습니다.",
                phase_id=phase.id))

    used_ms = {r.milestone_id for r in rows if r.milestone_id is not None}
    for ms in data.milestones:
        if ms.is_active and ms.id not in used_ms:
            warnings.append(_warn(
                ORPHAN_MILESTONE, f"Milestone '{ms.name}'에 속한 항목이 없습니다.",
                phase_id=ms.phase_id, milestone_id=ms.id))

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
