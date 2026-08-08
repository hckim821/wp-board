"""기준정보 API — plan.md §2.6.

특히 **삭제 정책**: 사용 중이면 지우지 않고 비활성화하며, 사용 건수를 함께
돌려준다.
"""

from __future__ import annotations

import pytest

from app.models import Item, ItemDocument, ItemOwner

pytestmark = pytest.mark.db

API = "/api/v1"


@pytest.fixture
def used(db, board):
    """기준정보를 실제로 쓰는 행 1건을 만들어 '사용 중' 상태로 만든다."""
    item = Item(
        version_id=board.published.id,
        sort_order=1,
        phase_id=board.p0.id,
        milestone_id=board.m01.id,
        title="행",
        deliverable="산출물",
    )
    item.documents = [ItemDocument(template_document_id=board.d1.id, sort_order=1)]
    item.owners = [ItemOwner(owner_id=board.o1.id, sort_order=1)]
    db.add(item)
    db.commit()
    return board


# =============================================================================
# 전역 Document Type 테스트는 **삭제됐다** (plan.md §0.5.10).
#
# 전역 문서 모델 자체가 폐기되고 문서가 템플릿 소유로 바뀌면서, `/master/
# document-types` CRUD·삭제 정책·`usage_count` 가 함께 사라졌다. 대체 검사는
# `test_api_documents.py` 에 있다 (템플릿 apply / 프로젝트 전량 교체).
# =============================================================================
# =============================================================================
# WP 스코프: Owner
# =============================================================================
def test_owners_are_scoped_to_their_template(client, board, db):
    from app.models import Template

    other = Template(code="OTHER", name="다른 템플릿")
    db.add(other)
    db.commit()

    assert len(client.get(f"{API}/templates/{board.wp.id}/owners").json()) == 2
    assert client.get(f"{API}/templates/{other.id}/owners").json() == []
    # 다른 WP 의 Owner 를 그 WP 경로로 만지면 404
    assert client.put(
        f"{API}/templates/{other.id}/owners/{board.o1.id}", json={"name": "x"}
    ).status_code == 404


def test_owner_crud(client, board):
    created = client.post(
        f"{API}/templates/{board.wp.id}/owners", json={"name": "사내 IT·보안", "sort_order": 3}
    )
    assert created.status_code == 201
    owner_id = created.json()["id"]

    renamed = client.put(
        f"{API}/templates/{board.wp.id}/owners/{owner_id}", json={"name": "보안"}
    )
    assert renamed.json()["name"] == "보안"

    assert client.delete(
        f"{API}/templates/{board.wp.id}/owners/{owner_id}"
    ).json()["deleted"] is True


def test_an_owner_in_use_is_deactivated(client, used):
    body = client.delete(f"{API}/templates/{used.wp.id}/owners/{used.o1.id}").json()
    assert (body["deleted"], body["deactivated"], body["usage_count"]) == (False, True, 1)


# =============================================================================
# WP 스코프: Phase / Milestone
# =============================================================================
def test_phase_display_is_composed_by_the_server(client, board):
    rows = client.get(f"{API}/templates/{board.wp.id}/phases").json()
    assert rows[0]["display"] == "Phase 0. Pre-Infrastructure Setup"
    assert rows[0]["name"] == "Pre-Infrastructure Setup"      # 이름에 번호가 없다


def test_milestone_major_number_comes_from_its_phase(client, board):
    rows = client.get(f"{API}/templates/{board.wp.id}/milestones").json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[board.m01.id]["no_display"] == "0.1"
    assert by_id[board.m11.id]["no_display"] == "1.1"
    assert by_id[board.m11.id]["display"] == "1.1 Scope 정의"
    assert by_id[board.m11.id]["seq_no"] == 1                 # 뒷자리만 저장


def test_renumbering_a_phase_moves_its_milestones_display_numbers(client, board):
    client.put(f"{API}/templates/{board.wp.id}/phases/{board.p1.id}", json={"seq_no": 4})
    rows = client.get(f"{API}/templates/{board.wp.id}/milestones").json()
    assert next(r for r in rows if r["id"] == board.m11.id)["no_display"] == "4.1"


def test_milestones_can_be_filtered_by_phase(client, board):
    rows = client.get(
        f"{API}/templates/{board.wp.id}/milestones", params={"phase_id": board.p0.id}
    ).json()
    assert {r["id"] for r in rows} == {board.m01.id, board.m02.id}


def test_creating_a_milestone_requires_a_phase_from_the_same_template(client, board, db):
    from app.models import Phase, Template

    other = Template(code="OTHER2", name="다른 템플릿")
    db.add(other)
    db.flush()
    foreign = Phase(template_id=other.id, name="남의 Phase", seq_no=0)
    db.add(foreign)
    db.commit()

    response = client.post(
        f"{API}/templates/{board.wp.id}/milestones",
        json={"phase_id": foreign.id, "name": "끼워넣기"},
    )
    assert response.status_code == 404


def test_a_phase_whose_milestone_is_in_use_is_deactivated(client, used):
    body = client.delete(f"{API}/templates/{used.wp.id}/phases/{used.p0.id}").json()
    assert body["deleted"] is False and body["usage_count"] >= 1


def test_an_unused_phase_is_deleted_with_its_milestones(client, used):
    body = client.delete(f"{API}/templates/{used.wp.id}/phases/{used.p1.id}").json()
    assert body["deleted"] is True

    remaining = client.get(f"{API}/templates/{used.wp.id}/milestones").json()
    assert used.m11.id not in {r["id"] for r in remaining}


def test_a_milestone_in_use_is_deactivated(client, used):
    body = client.delete(
        f"{API}/templates/{used.wp.id}/milestones/{used.m01.id}"
    ).json()
    assert (body["deleted"], body["usage_count"]) == (False, 1)


# =============================================================================
# F3 — 사용 중인 Milestone 의 소속 Phase 변경 금지 (plan.md §2.4)
# =============================================================================
def test_renaming_a_milestone_in_use_is_allowed(client, used):
    """표시용 변경은 과거 버전에 전파되어도 좋다 (오타 수정)."""
    response = client.put(
        f"{API}/templates/{used.wp.id}/milestones/{used.m01.id}", json={"name": "이름 수정"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "이름 수정"


def test_reparenting_a_milestone_in_use_is_refused(client, used):
    """구조를 바꾸는 변경은 발행된 버전에 닿으면 안 된다.

    소속 Phase 를 바꾸면 이미 발행된 버전이 `MILESTONE_PHASE_MISMATCH` 로
    조용히 무효가 된다 — 사용자는 기준정보 화면만 만졌는데.
    """
    response = client.put(
        f"{API}/templates/{used.wp.id}/milestones/{used.m01.id}",
        json={"phase_id": used.p1.id},
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["usage_count"] == 1
    assert body["field"] == "phase_id"


def test_reparenting_an_unused_milestone_is_allowed(client, used):
    response = client.put(
        f"{API}/templates/{used.wp.id}/milestones/{used.m11.id}",
        json={"phase_id": used.p0.id},
    )
    assert response.status_code == 200
    assert response.json()["phase_id"] == used.p0.id


def test_a_published_version_stays_valid_after_master_edits(db, client, used):
    """기준정보 화면을 만진 뒤에도 발행 버전은 계속 유효해야 한다."""
    from app.services import version_service

    client.put(
        f"{API}/templates/{used.wp.id}/milestones/{used.m01.id}", json={"name": "새 이름"}
    )
    client.put(
        f"{API}/templates/{used.wp.id}/milestones/{used.m01.id}",
        json={"phase_id": used.p1.id},
    )

    db.expire_all()
    result = version_service.validate_version(db, used.published)
    assert "MILESTONE_PHASE_MISMATCH" not in {e.code for e in result.errors}
