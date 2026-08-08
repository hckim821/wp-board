"""`db/migrate.py` 의 엑셀 파싱 — 원본 데이터의 함정들.

DB 를 쓰지 않는다. 원본 파일만 읽는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATE_PATH = REPO_ROOT / "db" / "migrate.py"
EXCEL_PATH = REPO_ROOT / "docs" / "Work Package.xlsx"


def load_migrate():
    """`db/` 는 패키지가 아니므로 경로로 직접 로드한다."""
    spec = importlib.util.spec_from_file_location("wp_migrate", MIGRATE_PATH)
    module = importlib.util.module_from_spec(spec)
    # @dataclass 가 실행 중에 sys.modules 를 되짚으므로 exec 전에 등록해야 한다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migrate = load_migrate()


@pytest.fixture(scope="module")
def book():
    if not EXCEL_PATH.exists():
        pytest.skip(f"원본 엑셀이 없습니다: {EXCEL_PATH}")
    return migrate.parse_workbook(EXCEL_PATH)


# =============================================================================
# 다중값 컬럼 — 구분자의 함정
# =============================================================================
def test_related_documents_split_on_the_circled_marker_not_the_slash():
    """`관련 문서` 는 명목상 `/` 구분이지만 **문서명 자체에 `/` 가 들어간다.**

    `② DSEP Readiness & I/O Spec` 의 `I/O` 를 구분자로 오인하면 파싱이 깨진다.
    실제로 순진하게 `split('/')` 로 구현했다가 이 셀에서 터졌다.
    """
    cell = "① Project Charter & R&R / ② DSEP Readiness & I/O Spec"
    # §0.5.10 — 파서는 이제 **표시 번호**를 돌려준다 (①=1). 원문자 표기는 원본
    # 엑셀 최초 임포트를 위해 계속 받아 준다.
    assert migrate.parse_documents(cell) == [1, 2]


def test_a_single_document_containing_a_slash():
    assert migrate.parse_documents("② DSEP Readiness & I/O Spec") == [2]


def test_owner_splits_on_plus():
    assert migrate.parse_owners("DSEP 인프라 담당자+사내 IT·보안") == [
        "DSEP 인프라 담당자",
        "사내 IT·보안",
    ]


def test_owner_keeps_parenthesised_names_intact():
    """`공동(구매·법무·보안)` 은 한 명이다. 가운뎃점은 구분자가 아니다."""
    assert migrate.parse_owners("공동(구매·법무·보안)") == ["공동(구매·법무·보안)"]


def test_document_cell_without_a_marker_is_rejected():
    with pytest.raises(ValueError):
        migrate.parse_documents("마커 없는 문서명")


def test_numeric_notation_is_accepted_for_round_trip():
    """§0.5.10 ③ — 내보내기는 숫자로 쓴다. 그것을 되읽을 수 있어야 한다."""
    assert migrate.parse_documents("1 / 3") == [1, 3]
    assert migrate.parse_documents("2") == [2]
    assert migrate.parse_documents("") == []


# =============================================================================
# 번호를 이름에서 분리 (요구사항 1)
# =============================================================================
def test_phase_number_is_separated_from_the_name(book):
    first = book.rows[0]
    assert first.phase_seq == 0
    assert first.phase_name == "Pre-Infrastructure Setup"     # `Phase 0. ` 이 빠졌다


def test_milestone_keeps_only_the_minor_number(book):
    first = book.rows[0]
    assert first.milestone_seq == 1                            # `0.1` 의 뒷자리만
    assert first.milestone_name == "DSEP 환경 Gap 및 자원 구성"


def test_milestone_major_always_matches_its_phase():
    """앞자리를 저장하지 않아도 되는 근거 — 원본에서 둘이 항상 일치한다.

    파서는 어긋난 행을 만나면 거부한다. 35행 전체가 파싱을 통과했다는 사실이
    곧 "앞자리는 Phase 에서 파생해도 안전하다" 는 근거다.
    """
    assert migrate.PHASE_RE.match("Phase 2. Development") .group(1) == "2"
    assert migrate.MILESTONE_RE.match("2.4 Interim Review").groups() == ("2", "4", "Interim Review")


# =============================================================================
# 원본 전체 형상 (plan.md §1.1 과 대조)
# =============================================================================
def test_row_and_document_counts(book):
    assert len(book.rows) == 35
    assert len(book.doc_types) == 5
    assert [d.code for d in book.doc_types] == ["①", "②", "③", "④", "⑤"]


def test_phase_and_milestone_shape(book):
    phases = {r.phase_seq: r.phase_name for r in book.rows}
    assert sorted(phases) == [0, 1, 2, 3]

    milestones = {(r.phase_seq, r.milestone_seq) for r in book.rows}
    assert len(milestones) == 13

    per_phase = {p: sum(1 for r in book.rows if r.phase_seq == p) for p in phases}
    assert per_phase == {0: 4, 1: 10, 2: 11, 3: 10}


def test_the_n_to_m_links_that_justify_the_join_tables(book):
    """다중값이 실제로 존재해야 N:M 정규화가 정당화된다."""
    multi_doc = [r.no for r in book.rows if len(r.doc_numbers) > 1]
    multi_owner = [r.no for r in book.rows if len(r.owner_names) > 1]
    assert multi_doc == [6, 14]
    assert len(multi_owner) == 10
    assert sum(len(r.doc_numbers) for r in book.rows) == 37
    assert sum(len(r.owner_names) for r in book.rows) == 45


def test_owner_master_is_deduplicated_across_rows(book):
    names: list[str] = []
    for row in book.rows:
        for name in row.owner_names:
            if name not in names:
                names.append(name)
    assert len(names) == 8
    assert "공동(구매·법무·보안)" in names


def test_the_source_board_is_already_contiguous(book):
    """원본이 블록 연속성을 만족하기 때문에 그대로 번호를 매길 수 있다."""
    assert migrate.check_consistency(book) == []


# =============================================================================
# 대시보드 라벨 (plan.md §0.5-1) — 엑셀이 아니라 상수에서 온다
# =============================================================================
def test_every_row_gets_a_dash_label(book):
    """라벨은 `docs/dashboard.jpg` 의 문구이고 행 No 로 붙는다.

    엑셀에서 읽지 않는 값이라, 엑셀 행 수가 바뀌면 라벨이 밀리거나 비게 된다.
    35행 전체가 라벨을 갖는지 여기서 고정한다.
    """
    assert len(migrate.DASH_LABELS) == 35
    assert [r.dash_label for r in book.rows] == [migrate.DASH_LABELS[r.no] for r in book.rows]
    assert all(r.dash_label for r in book.rows)


def test_dash_labels_fit_the_column():
    assert max(len(v) for v in migrate.DASH_LABELS.values()) <= migrate.DASH_LABEL_MAX


def test_consistency_catches_a_row_without_a_dash_label(book, monkeypatch):
    """건강한 경우에만 확인한 검사기는 쓸모가 없다 — 아픈 경우로 확인한다."""
    trimmed = {k: v for k, v in migrate.DASH_LABELS.items() if k != 7}
    monkeypatch.setattr(migrate, "DASH_LABELS", trimmed)

    problems = migrate.check_consistency(book)
    assert any("라벨이 없는 행" in p and "7" in p for p in problems)


def test_seed_sql_carries_the_dash_labels(book, tmp_path):
    """`--emit-sql` 산출물에도 라벨이 실려야 한다 — 시드가 적재 경로와 같아야 한다."""
    out = tmp_path / "seed.sql"
    migrate.emit_seed_sql(book, out)
    sql = out.read_text(encoding="utf-8")

    assert "dash_label" in sql
    assert f"'{migrate.DASH_LABELS[1]}'" in sql
    assert f"'{migrate.DASH_LABELS[35]}'" in sql
