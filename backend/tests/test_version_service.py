"""버전 상태 기계 / deep copy — plan.md §2.4.

실제 MariaDB 위에서 돈다 (`db/schema.sql` 원본 적용).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.exceptions import ConflictError, PublishValidationError
from app.models import Item, ItemDocument, ItemOwner, Phase, Version, VersionStatus
from app.schemas.item import ItemSaveIn
from app.services import item_service, version_service

pytestmark = pytest.mark.db


def add_item(db, version, sort_order, phase, milestone, *, docs=(), owners=(), title="행", deliv="산출물"):
    item = Item(
        version_id=version.id,
        sort_order=sort_order,
        phase_id=phase.id if phase else None,
        milestone_id=milestone.id if milestone else None,
        title=title,
        deliverable=deliv,
    )
    item.documents = [ItemDocument(template_document_id=d.id, sort_order=i) for i, d in enumerate(docs, 1)]
    item.owners = [ItemOwner(owner_id=o.id, sort_order=i) for i, o in enumerate(owners, 1)]
    db.add(item)
    db.flush()
    return item


@pytest.fixture
def filled(db, board):
    """PUBLISHED v1 에 3행을 채운다. Phase/Milestone/Owner/문서를 모두 쓴다."""
    b = board
    rows = [
        add_item(db, b.published, 1, b.p0, b.m01, docs=[b.d1], owners=[b.o1]),
        add_item(db, b.published, 2, b.p0, b.m02, docs=[b.d1, b.d2], owners=[b.o1, b.o2]),
        add_item(db, b.published, 3, b.p1, b.m11, docs=[b.d2], owners=[b.o2]),
    ]
    db.commit()
    b.items = rows
    return b


# =============================================================================
# draft 발행 = deep copy
# =============================================================================
def test_draft_deep_copies_rows_and_their_n_to_m_links(db, filled):
    draft = version_service.create_draft(db, filled.wp.id, created_by="tester")
    db.commit()

    copies = item_service.load_ordered_items(db, version_service.board_of(db, draft))
    assert len(copies) == 3
    assert [c.title for c in copies] == ["행", "행", "행"]
    assert [len(c.documents) for c in copies] == [1, 2, 1]
    assert [len(c.owners) for c in copies] == [1, 2, 1]
    # 링크의 순서(sort_order)까지 보존되어야 한다.
    assert [d.template_document_id for d in copies[1].documents] == [filled.d1.id, filled.d2.id]


def test_draft_records_its_provenance(db, filled):
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    assert draft.version_number == 2
    assert draft.status == VersionStatus.DRAFT
    assert draft.source_version_id == filled.published.id

    copies = item_service.load_ordered_items(db, version_service.board_of(db, draft))
    assert [c.source_item_id for c in copies] == [i.id for i in filled.items]


def test_editing_the_draft_leaves_the_published_version_untouched(db, filled):
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    item_service.delete_item(db, version_service.board_of(db, draft), item_service.load_ordered_items(db, version_service.board_of(db, draft))[0].id)
    db.commit()

    original = item_service.load_ordered_items(db, version_service.board_of(db, filled.published))
    assert len(original) == 3
    assert [i.sort_order for i in original] == [1, 2, 3]


def test_draft_does_not_duplicate_template_scoped_master_data(db, filled):
    """Phase/Milestone/Owner 는 버전이 아니라 WP 에 매인다 — 복사 대상이 아니다.

    복사했다면 `UQ(template_id, name)` 에 걸려 터졌을 것이다.
    """
    before = db.query(Phase).filter(Phase.template_id == filled.wp.id).count()
    version_service.create_draft(db, filled.wp.id)
    db.commit()
    after = db.query(Phase).filter(Phase.template_id == filled.wp.id).count()
    assert before == after == 2


def test_at_most_one_draft_per_template(db, filled):
    version_service.create_draft(db, filled.wp.id)
    db.commit()
    with pytest.raises(ConflictError):
        version_service.create_draft(db, filled.wp.id)


def test_draft_without_a_published_version_starts_empty_at_v1(db, board):
    db.delete(board.published)
    db.commit()

    draft = version_service.create_draft(db, board.wp.id)
    db.commit()

    assert draft.version_number == 1
    assert draft.source_version_id is None
    assert item_service.load_ordered_items(db, version_service.board_of(db, draft)) == []


# =============================================================================
# 버전별 번호의 독립성 — 설계의 핵심 주장
# =============================================================================
def test_published_numbering_survives_a_reordering_draft(db, filled):
    """DRAFT 에서 Phase 순서를 뒤집어도 PUBLISHED 의 표시 번호는 그대로여야 한다.

    표시 번호를 기준정보의 `seq_no` 에서 읽었다면 여기서 깨진다.
    두 버전이 같은 `wp_phases` 행을 공유하기 때문이다.
    """
    published_before = item_service.build_item_views(
        db, version_service.board_of(db, filled.published), item_service.load_ordered_items(db, version_service.board_of(db, filled.published)))
    assert [v.phase_no for v in published_before] == [0, 0, 1]

    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    # DRAFT 에서 Phase 블록 순서를 뒤집는다 → 기준정보 seq_no 가 뒤집힌다.
    # UI 드래그로는 이렇게 만들 수 없다 — 드래그는 자기 Phase·Milestone 블록
    # 안에서만 순서를 바꾸므로 블록 자체를 옮기지 못한다 (§2.2).
    # 그래서 임시저장(전량 교체) 경로를 쓴다.
    rows = item_service.load_ordered_items(db, version_service.board_of(db, draft))
    item_service.bulk_replace(db, version_service.board_of(db, draft), [
        ItemSaveIn(id=rows[2].id, phase_id=filled.p1.id, milestone_id=filled.m11.id),
        ItemSaveIn(id=rows[0].id, phase_id=filled.p0.id, milestone_id=filled.m01.id),
        ItemSaveIn(id=rows[1].id, phase_id=filled.p0.id, milestone_id=filled.m02.id),
    ])
    db.commit()

    db.refresh(filled.p0)
    db.refresh(filled.p1)
    assert (filled.p1.seq_no, filled.p0.seq_no) == (0, 1)   # 기준정보는 뒤집혔고

    published_after = item_service.build_item_views(
        db, version_service.board_of(db, filled.published), item_service.load_ordered_items(db, version_service.board_of(db, filled.published)))
    assert [v.phase_no for v in published_after] == [0, 0, 1]   # PUBLISHED 는 그대로


def test_reading_a_published_version_does_not_write_master_data(db, filled):
    db.refresh(filled.p0)
    before = filled.p0.seq_no
    filled.p0.seq_no = 9
    db.commit()

    items = item_service.load_ordered_items(db, version_service.board_of(db, filled.published))
    item_service.renumber_and_persist(db, version_service.board_of(db, filled.published), items)
    db.commit()

    db.refresh(filled.p0)
    assert filled.p0.seq_no == 9 != before   # PUBLISHED 재계산은 기준정보를 건드리지 않는다


# =============================================================================
# 발행
# =============================================================================
def test_publish_promotes_the_draft_and_archives_the_previous(db, filled):
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    version_service.publish(db, draft.id, published_by="tester")
    db.commit()

    db.refresh(draft)
    db.refresh(filled.published)
    assert draft.status == VersionStatus.PUBLISHED
    assert draft.published_at is not None
    assert draft.published_by == "tester"
    assert filled.published.status == VersionStatus.ARCHIVED
    assert filled.published.archived_at is not None


def test_publish_fails_validation_and_changes_nothing(db, filled):
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    broken = item_service.load_ordered_items(db, version_service.board_of(db, draft))[0]
    broken.owners = []
    db.commit()

    with pytest.raises(PublishValidationError) as exc:
        version_service.publish(db, draft.id)

    payload = exc.value.to_payload()
    assert payload["valid"] is False
    assert any(e["code"] == "OWNER_REQUIRED" for e in payload["errors"])
    # 위치 정보가 담겨 그리드가 셀을 바로 짚을 수 있어야 한다.
    issue = next(e for e in payload["errors"] if e["code"] == "OWNER_REQUIRED")
    assert issue["item_id"] == broken.id and issue["field"] == "owners"

    db.rollback()
    db.refresh(draft)
    assert draft.status == VersionStatus.DRAFT


def test_publish_rejects_an_empty_version(db, board):
    db.delete(board.published)
    db.commit()
    draft = version_service.create_draft(db, board.wp.id)
    db.commit()

    with pytest.raises(PublishValidationError) as exc:
        version_service.publish(db, draft.id)
    assert exc.value.detail["errors"][0]["code"] == "EMPTY_VERSION"


def test_publish_is_blocked_for_a_non_draft_version(db, filled):
    with pytest.raises(ConflictError):
        version_service.publish(db, filled.published.id)


def test_validate_and_publish_evaluate_the_same_state(db, filled):
    """미리보기와 발행이 갈리면 안 된다 (plan.md §2.5 필수 요건 1).

    이전 구현은 발행만 먼저 재계산해서, `/validate` 가 `PHASE_SEQ_GAP` 을
    보여준 보드가 발행은 성공했다. 사용자가 대응할 수 없는 모순이다.
    """
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    filled.p0.seq_no = 41
    filled.p1.seq_no = 42
    db.commit()

    preview = version_service.validate_version(db, draft)
    preview_codes = {e.code for e in preview.errors}

    if preview.valid:
        version_service.publish(db, draft.id)
        db.commit()
    else:
        with pytest.raises(PublishValidationError) as exc:
            version_service.publish(db, draft.id)
        assert {e["code"] for e in exc.value.to_payload()["errors"]} == preview_codes
        db.rollback()


def test_publish_normalizes_numbering_once_validation_passes(db, filled):
    """검증을 통과하면 저장 전에 번호를 정규화한다."""
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    version_service.publish(db, draft.id)
    db.commit()

    db.refresh(filled.p0)
    db.refresh(filled.p1)
    assert (filled.p0.seq_no, filled.p1.seq_no) == (0, 1)


def test_publish_snapshots_phase_start_no_onto_the_version(db, filled):
    """발행 버전은 표시 파라미터를 스스로 들고 있어야 한다 (plan.md §2.4).

    이후 WP 의 `phase_start_no` 를 바꿔도 발행된 버전의 번호는 흔들리지 않는다.
    """
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()
    version_service.publish(db, draft.id)
    db.commit()

    db.refresh(draft)
    assert draft.phase_start_no == 0

    filled.wp.phase_start_no = 7          # 기준정보 쪽을 바꿔도
    db.commit()

    views = item_service.build_item_views(
        db, version_service.board_of(db, draft), item_service.load_ordered_items(db, version_service.board_of(db, draft))
    )
    assert [v.phase_no for v in views] == [0, 0, 1]   # 발행 버전은 그대로


# =============================================================================
# 폐기
# =============================================================================
def test_discard_removes_a_draft_and_its_rows(db, filled):
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()
    draft_id = draft.id

    version_service.discard(db, draft.id)
    db.commit()

    assert db.get(Version, draft_id) is None
    assert db.get(Version, draft_id) is None
    assert len(item_service.load_ordered_items(db, version_service.board_of(db, filled.published))) == 3


def test_discard_refuses_a_published_version(db, filled):
    with pytest.raises(ConflictError):
        version_service.discard(db, filled.published.id)


def test_discard_rewinds_master_numbering_touched_by_the_draft(db, filled):
    """폐기한 DRAFT 가 기준정보에 남긴 번호 흔적을 되돌린다.

    되돌리지 않으면, 손대지도 않은 PUBLISHED 버전을 검증할 때 V6 가 헛되이
    PHASE_SEQ_GAP 을 낸다. 실제로 그 상태를 만들어 본 뒤 잡은 결함이다.
    """
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    # DRAFT 에서 새 Phase 를 만들면 기존 Phase 번호가 밀린다
    rows = item_service.load_ordered_items(db, version_service.board_of(db, draft))
    item_service.create_phase_from_row(db, version_service.board_of(db, draft), rows[1].id, "임시 단계")
    db.commit()

    db.refresh(filled.p1)
    assert filled.p1.seq_no == 2                      # 0,1 → 새 Phase 가 1을 차지

    version_service.discard(db, draft.id)
    db.commit()

    db.refresh(filled.p0)
    db.refresh(filled.p1)
    assert (filled.p0.seq_no, filled.p1.seq_no) == (0, 1)

    result = version_service.validate_version(db, filled.published)
    assert not [e for e in result.errors if e.code == "PHASE_SEQ_GAP"]


# =============================================================================
# F1 — 상태 검사는 잠금 하에서 (plan.md §2.4)
# =============================================================================
def test_write_paths_reread_status_instead_of_trusting_a_stale_object(db, filled, session_factory):
    """다른 세션이 상태를 바꾼 뒤에는 낡은 객체로 쓰기가 통과하면 안 된다.

    예전 구현은 `session.get()` 으로 읽은 상태를 그대로 믿었다. 검사와 쓰기
    사이에 발행이 끼어들면 방금 발행된 버전을 임시저장이 덮어썼다.
    """
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()
    draft_id = draft.id

    stale = db.get(Version, draft_id)
    assert stale.status == VersionStatus.DRAFT          # 이 세션이 아는 상태

    with session_factory() as other:                     # 다른 요청이 먼저 발행
        other.execute(
            text("UPDATE wp_versions SET status='PUBLISHED' WHERE id=:i"), {"i": draft_id}
        )
        other.commit()

    # **여기서 rollback 하지 않는다.** rollback 은 identity map 을 만료시켜
    # `populate_existing` 없이도 재조회가 신선해진다 — 즉 고치기 전 코드로도
    # 테스트가 통과해 회귀를 못 잡는다. 실제 `publish()`/`discard()` 창에는
    # rollback 이 없으므로, 낡은 객체가 identity map 에 살아 있는 상태 그대로
    # 잠금 후 재조회를 확인해야 한다.
    with pytest.raises(ConflictError):
        version_service.lock_editable_version(db, draft_id)


def test_discard_of_a_published_version_is_refused_by_id(db, filled):
    """폐기도 id 로 받아 잠금 뒤 상태를 다시 읽는다."""
    with pytest.raises(ConflictError):
        version_service.discard(db, filled.published.id)


# =============================================================================
# F4 — 쓰이지 않는 Phase 도 고유한 seq_no 를 받는다
# =============================================================================
def test_unused_phases_keep_distinct_seq_no(db, filled):
    """사용 중인 것에만 번호를 쓰면 나머지가 예전 값을 들고 있어 겹친다."""
    draft = version_service.create_draft(db, filled.wp.id)
    db.commit()

    # DRAFT 에서 Phase 1 행을 모두 지워 P1 을 미사용으로 만든다
    for row in item_service.load_ordered_items(db, version_service.board_of(db, draft)):
        if row.phase_id == filled.p1.id:
            item_service.delete_item(db, version_service.board_of(db, draft), row.id)
    db.commit()

    db.refresh(filled.p0)
    db.refresh(filled.p1)
    seqs = [filled.p0.seq_no, filled.p1.seq_no]
    assert len(set(seqs)) == len(seqs), f"seq_no 중복: {seqs}"
    assert filled.p0.seq_no == 0
