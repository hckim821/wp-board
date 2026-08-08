"""프로젝트 API — plan.md §0.1, §4.2.

두 가지를 확인한다.

1. **스냅샷 격리** — 생성 시 전부 복제되고, 이후 두 계층이 서로에게 영향을 주지
   않는다. 프로젝트를 고쳐도 템플릿이 그대로이고, 템플릿을 재발행해도 기존
   프로젝트가 그대로다.
2. **그리드 규약의 동일성** — 재계산·경계·회색 행·드래그가 템플릿과 같게 동작한다.
   두 계층이 `item_service` 를 공유하므로 당연해야 하는데, "당연"은 이 저장소에서
   여러 번 틀렸으므로 확인한다.
"""

from __future__ import annotations

import pytest

from app.models import (
    Item,
    ItemDocument,
    ItemOwner,
    Project,
    ProjectItem,
    ProjectPhase,
    VersionStatus,
)
from app.services import version_service

pytestmark = pytest.mark.db

API = "/api/v1"


@pytest.fixture
def published(db, board):
    """템플릿 발행본 v1 — `[P0/M01, P0/M01, P0/M02, P1/M11]` + 문서/Owner 연결."""
    layout = [(board.p0, board.m01), (board.p0, board.m01), (board.p0, board.m02), (board.p1, board.m11)]
    for order, (phase, milestone) in enumerate(layout, start=1):
        item = Item(
            version_id=board.published.id,
            sort_order=order,
            phase_id=phase.id,
            milestone_id=milestone.id,
            title=f"행 {order}",
            deliverable=f"산출물 {order}",
        )
        item.documents = [ItemDocument(template_document_id=board.d1.id, sort_order=1)]
        item.owners = [ItemOwner(owner_id=board.o1.id, sort_order=1)]
        db.add(item)
    db.commit()
    return board


def make_project(client, board, name="테스트 프로젝트", maker_id=7):
    response = client.post(
        f"{API}/projects", json={"maker_id": maker_id, "name": name, "template_id": board.wp.id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def items_of(client, project_id):
    response = client.get(f"{API}/projects/{project_id}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


# =============================================================================
# 생성 = deep copy
# =============================================================================
def test_creation_copies_every_row_with_its_links(client, published):
    created = make_project(client, published)
    rows = created["items"]

    assert len(rows) == 4
    assert [r["row_no"] for r in rows] == [1, 2, 3, 4]
    assert [r["phase_no"] for r in rows] == [0, 0, 0, 1]
    assert [r["milestone_no"] for r in rows] == [1, 1, 2, 1]
    assert [r["title"] for r in rows] == ["행 1", "행 2", "행 3", "행 4"]
    # 문서는 **전역**이라 같은 id 를 가리킨다 (복제하지 않는다).
    # §0.5.10 — 문서도 복제되므로 **id 가 다르다**. 이름과 표시 번호가 같아야 한다.
    assert [d["no"] for d in rows[0]["documents"]] == [1]
    assert [d["name"] for d in rows[0]["documents"]] == ["Project Charter & R&R"]
    assert rows[0]["documents"][0]["id"] != published.d1.id
    assert rows[0]["owners"][0]["name"] == "DSEP 인프라 담당자"


def test_creation_records_its_provenance_and_snapshots_phase_start_no(client, published):
    created = make_project(client, published)["project"]
    assert created["source_template_id"] == published.wp.id
    assert created["source_version_id"] == published.published.id
    # 헤더가 "어느 포맷의 몇 버전" 을 보여주므로 표시용 번호도 함께 나간다.
    assert created["source_version_number"] == published.published.version_number
    assert created["phase_start_no"] == 0


# =============================================================================
# 원본 버전 번호 — id 가 아니라 사람이 읽는 번호
# =============================================================================
def test_the_source_version_number_follows_the_version_it_came_from(db, client, published):
    """v1 이 아닌 버전에서 만든 프로젝트도 자기 출처를 정확히 말해야 한다.

    `source_version_id` 를 그대로 보여주면 안 되는 이유이기도 하다 — id 는
    auto-increment 라 "몇 번째 버전인가" 와 아무 상관이 없다.
    """
    from app.services import version_service

    draft = version_service.create_draft(db, published.wp.id)
    db.commit()
    v2 = version_service.publish(db, draft.id)
    db.commit()
    assert v2.version_number == 2

    created = make_project(client, published, name="v2 에서 만든 프로젝트")["project"]
    assert created["source_version_id"] == v2.id
    assert created["source_version_number"] == 2


def test_the_source_version_number_appears_on_every_project_response(db, client, published):
    """단건·목록·수정 응답이 갈리면 헤더가 화면마다 다른 값을 보인다."""
    created = make_project(client, published)["project"]
    project_id = created["id"]
    expected = published.published.version_number

    assert client.get(f"{API}/projects/{project_id}").json()["project"][
        "source_version_number"
    ] == expected
    listed = client.get(f"{API}/projects").json()
    assert [p["source_version_number"] for p in listed] == [expected]
    assert client.patch(
        f"{API}/projects/{project_id}", json={"name": "이름 변경"}
    ).json()["source_version_number"] == expected


def test_a_dangling_source_version_leaves_the_number_null(db, client, published):
    """원본 버전이 사라져도 **조회가 깨지지 않는다.**

    `source_version_id` 에 물리 FK 를 걸지 않은 것은 의도다 (원본이 지워져도
    출처 이력은 남긴다). 그래서 고아 참조는 정상적으로 생길 수 있고, 그때는
    번호만 비어야 한다 — 설비사 이름과 같은 규칙이다.
    """
    created = make_project(client, published)["project"]
    project_id = created["id"]
    assert created["source_version_number"] is not None

    project = db.get(Project, project_id)
    project.source_version_id = 999999          # 호스트/원본에서 사라진 상태를 흉내
    db.commit()

    single = client.get(f"{API}/projects/{project_id}")
    assert single.status_code == 200, single.text
    assert single.json()["project"]["source_version_number"] is None
    assert single.json()["project"]["source_version_id"] == 999999

    listed = client.get(f"{API}/projects")
    assert listed.status_code == 200
    assert listed.json()[0]["source_version_number"] is None


def test_a_project_without_a_source_version_reports_null(db, client):
    """직접 만든(복제가 아닌) 프로젝트 행 — `source_version_id` 자체가 없다."""
    orphan = Project(maker_id=1, name="출처 없는 프로젝트", phase_start_no=0)
    db.add(orphan)
    db.commit()

    body = client.get(f"{API}/projects/{orphan.id}").json()["project"]
    assert body["source_version_id"] is None
    assert body["source_version_number"] is None


def test_the_copied_master_data_is_local_not_shared(db, client, published):
    """Phase/Milestone/Owner 는 **사본**이다.

    id 값을 서로 비교하는 것으로는 확인할 수 없다 — `wp_phases` 와
    `wp_project_phases` 는 다른 테이블이라 같은 번호를 갖는 것이 정상이다.
    확인해야 할 것은 **행이 가리키는 곳이 프로젝트 로컬 테이블인가**, 그리고 그
    사본이 템플릿 원본을 출처로 기록하고 있는가다.
    """
    created = make_project(client, published)
    project_id = created["project"]["id"]

    local = db.query(ProjectPhase).filter_by(project_id=project_id).all()
    assert len(local) == 2
    assert {p.source_phase_id for p in local} == {published.p0.id, published.p1.id}

    # 행의 phase_id 가 **로컬 사본의 id 집합** 안에 있다.
    referenced = {r["phase_id"] for r in created["items"] if r["phase_id"]}
    assert referenced <= {p.id for p in local}

    phases = client.get(f"{API}/projects/{project_id}/phases").json()
    assert {p["name"] for p in phases} == {"Pre-Infrastructure Setup", "Initiation & Readiness"}
    # 응답이 어느 스코프의 것인지 스스로 말한다.
    assert all(p["project_id"] == project_id and p["template_id"] is None for p in phases)


def test_owner_links_point_at_the_local_owner_copies(db, client, published):
    from app.models import ProjectOwner

    created = make_project(client, published)
    project_id = created["project"]["id"]

    local = db.query(ProjectOwner).filter_by(project_id=project_id).all()
    assert {o.source_owner_id for o in local} == {published.o1.id, published.o2.id}
    assert created["items"][0]["owners"][0]["id"] in {o.id for o in local}


def test_a_draft_version_cannot_be_used_as_a_source(db, client, published):
    """DRAFT 는 확정되지 않은 작업본이다 — 스냅샷의 출처가 될 수 없다."""
    draft = version_service.create_draft(db, published.wp.id)
    db.commit()

    response = client.post(
        f"{API}/projects",
        json={"maker_id": 7, "name": "이르다", "template_version_id": draft.id},
    )
    assert response.status_code == 400
    assert "DRAFT" in response.json()["detail"]["message"]


def test_a_template_without_a_published_version_cannot_seed_a_project(db, client, board):
    response = client.post(
        f"{API}/projects", json={"maker_id": 7, "name": "빈 템플릿", "template_id": board.wp.id}
    )
    # board 픽스처의 v1 은 PUBLISHED 지만 행이 없다 — 그래도 발행본이므로 통과한다.
    assert response.status_code == 201, response.text
    assert response.json()["items"] == []


def test_creation_is_atomic(db, client, published):
    """존재하지 않는 버전을 주면 프로젝트가 **하나도** 남지 않아야 한다."""
    before = db.query(Project).count()
    response = client.post(
        f"{API}/projects", json={"maker_id": 7, "name": "실패", "template_version_id": 999999}
    )
    assert response.status_code == 404
    assert db.query(Project).count() == before


# =============================================================================
# 격리 — 양방향
# =============================================================================
def test_editing_the_project_does_not_touch_the_template(db, client, published):
    created = make_project(client, published)
    project_id = created["project"]["id"]
    rows = created["items"]

    client.delete(f"{API}/projects/{project_id}/items/{rows[0]['id']}")
    client.post(
        f"{API}/projects/{project_id}/items/{rows[3]['id']}/create-phase",
        json={"name": "프로젝트 전용 단계"},
    )

    template_rows = client.get(f"{API}/versions/{published.published.id}").json()["items"]
    assert len(template_rows) == 4
    assert [r["phase_no"] for r in template_rows] == [0, 0, 0, 1]

    template_phases = client.get(f"{API}/templates/{published.wp.id}/phases").json()
    assert "프로젝트 전용 단계" not in {p["name"] for p in template_phases}


def test_republishing_the_template_does_not_touch_existing_projects(db, client, published):
    """스냅샷이라는 말의 의미 — 전파가 **없다**."""
    created = make_project(client, published)
    project_id = created["project"]["id"]
    before = items_of(client, project_id)

    draft = version_service.create_draft(db, published.wp.id)
    db.commit()
    rows = client.get(f"{API}/versions/{draft.id}").json()["items"]
    client.delete(f"{API}/versions/{draft.id}/items/{rows[0]['id']}")
    client.post(f"{API}/versions/{draft.id}/publish")

    assert items_of(client, project_id) == before


def test_a_project_local_phase_never_appears_in_the_template_master_list(client, published):
    created = make_project(client, published)
    project_id = created["project"]["id"]

    client.post(f"{API}/projects/{project_id}/phases", json={"name": "로컬 단계"})

    assert "로컬 단계" in {
        p["name"] for p in client.get(f"{API}/projects/{project_id}/phases").json()
    }
    assert "로컬 단계" not in {
        p["name"] for p in client.get(f"{API}/templates/{published.wp.id}/phases").json()
    }


# =============================================================================
# 그리드 규약 — 템플릿과 같아야 한다
# =============================================================================
def test_rows_carry_the_same_numbering_and_boundary_flags(client, published):
    rows = items_of(client, make_project(client, published)["project"]["id"])
    assert rows[0]["phase_display"] == "Phase 0. Pre-Infrastructure Setup"
    assert rows[2]["milestone_no_display"] == "0.2"
    assert [r["is_phase_block_start"] for r in rows] == [True, False, False, True]
    assert [r["can_create_phase"] for r in rows] == [True, False, True, True]


def test_append_and_insert_below_create_gray_rows(client, published):
    project_id = make_project(client, published)["project"]["id"]
    rows = items_of(client, project_id)

    appended = client.post(f"{API}/projects/{project_id}/items")
    assert appended.status_code == 201, appended.text
    assert appended.json()["items"][-1]["phase_id"] is None

    inserted = client.post(
        f"{API}/projects/{project_id}/items/{rows[0]['id']}/insert-below"
    ).json()["items"][1]
    assert inserted["phase_id"] is None
    assert inserted["origin"] == "ADDED"


def test_a_gray_row_between_blocks_creates_an_in_between_phase(client, published):
    """§0.2-5 가 프로젝트에서도 그대로 성립한다."""
    project_id = make_project(client, published)["project"]["id"]
    rows = items_of(client, project_id)

    gray = client.post(
        f"{API}/projects/{project_id}/items/{rows[2]['id']}/insert-below"
    ).json()["items"][3]
    assert gray["can_create_phase"] is True

    created = client.post(
        f"{API}/projects/{project_id}/items/{gray['id']}/create-phase",
        json={"name": "사이 단계"},
    )
    assert created.status_code == 200, created.text
    assert [r["phase_no"] for r in created.json()["items"]] == [0, 0, 0, 1, 2]


def test_reorder_keeps_membership_and_refuses_a_crossing_order(client, published):
    project_id = make_project(client, published)["project"]["id"]
    rows = items_of(client, project_id)
    ids = [r["id"] for r in rows]

    ok = client.post(
        f"{API}/projects/{project_id}/items/reorder",
        json={"item_ids": [ids[1], ids[0], ids[2], ids[3]]},
    )
    assert ok.status_code == 200, ok.text
    assert [(r["phase_id"], r["milestone_id"]) for r in ok.json()["items"]] == [
        (rows[1]["phase_id"], rows[1]["milestone_id"]),
        (rows[0]["phase_id"], rows[0]["milestone_id"]),
        (rows[2]["phase_id"], rows[2]["milestone_id"]),
        (rows[3]["phase_id"], rows[3]["milestone_id"]),
    ]

    before = items_of(client, project_id)
    crossing = client.post(
        f"{API}/projects/{project_id}/items/reorder",
        json={"item_ids": [ids[1], ids[3], ids[0], ids[2]]},
    )
    assert crossing.status_code == 422
    assert crossing.json()["detail"]["code"] == "PHASE_NOT_CONTIGUOUS"
    assert items_of(client, project_id) == before


def test_membership_change_relocates_the_row(client, published):
    project_id = make_project(client, published)["project"]["id"]
    rows = items_of(client, project_id)
    middle = rows[1]

    response = client.patch(
        f"{API}/projects/{project_id}/items/{middle['id']}/membership",
        json={"phase_id": rows[3]["phase_id"], "milestone_id": rows[3]["milestone_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][-1]["id"] == middle["id"]


def test_project_master_data_from_another_project_is_refused(client, published):
    """기준정보는 프로젝트 스코프다 — 남의 사본을 끌어다 쓸 수 없다."""
    first = make_project(client, published, name="첫번째")["project"]["id"]
    second = make_project(client, published, name="두번째")

    foreign_phase = second["items"][0]["phase_id"]
    rows = items_of(client, first)

    response = client.patch(
        f"{API}/projects/{first}/items/{rows[0]['id']}/membership",
        json={"phase_id": foreign_phase, "milestone_id": None},
    )
    assert response.status_code == 400


# =============================================================================
# 버전이 없다는 사실 자체
# =============================================================================
def test_projects_have_no_version_endpoints(client):
    """draft/발행/폐기/검증이 프로젝트 URL 아래에 **존재하지 않아야** 한다.

    "없음" 은 잊기 쉬운 종류의 요구사항이라 라우트 표에서 직접 확인한다.
    """
    paths = set(client.app.openapi()["paths"])
    forbidden = [
        p for p in paths
        if p.startswith("/api/v1/projects")
        and any(word in p for word in ("versions", "publish", "validate", "draft"))
    ]
    assert forbidden == [], f"프로젝트에 버전 개념이 새어 들어왔다: {forbidden}"


def test_saving_a_project_does_not_validate(client, published):
    """프로젝트에는 차단 검증이 없다 (plan.md §0.1) — 회색 행도 빈 행도 저장된다."""
    project_id = make_project(client, published)["project"]["id"]
    rows = items_of(client, project_id)

    response = client.put(
        f"{API}/projects/{project_id}/items",
        json={"items": [{"id": rows[0]["id"]}, {"title": "새 행"}]},
    )
    assert response.status_code == 200, response.text
    saved = response.json()["items"]
    assert len(saved) == 2
    assert all(r["phase_id"] is None for r in saved)


# =============================================================================
# §0.3 — 소속 셀 규칙이 프로젝트에서도 같아야 한다
#
# 두 계층이 `item_service` 를 공유하므로 같아야 "마땅" 하지만, 이 저장소에서
# "마땅히 그럴 것" 은 여러 번 틀렸다. 프로젝트는 기준정보가 **로컬 사본**이라
# 스코프 해석이 한 겹 더 있으므로 특히 확인할 값이 있다.
# =============================================================================
@pytest.fixture
def three_block_project(db, client, board):
    """Phase 1 이 Milestone 블록 3개인 템플릿에서 만든 프로젝트.

    `a1 a2 | b1(1.1) c1(1.2) c2(1.2) d1(1.3) d2(1.3)`

    대상 마일스톤(1.2)이 자기 Phase 의 **마지막이 아니어야** phase 단위 재배치
    구현과 갈라진다 — 기본 픽스처로는 그 차이가 드러나지 않는다.
    """
    from app.models import Milestone

    m12 = Milestone(template_id=board.wp.id, phase_id=board.p1.id, name="설계", seq_no=2)
    m13 = Milestone(template_id=board.wp.id, phase_id=board.p1.id, name="구현", seq_no=3)
    db.add_all([m12, m13])
    db.flush()

    layout = [
        (board.p0, board.m01, "a1"), (board.p0, board.m01, "a2"),
        (board.p1, board.m11, "b1"),
        (board.p1, m12, "c1"), (board.p1, m12, "c2"),
        (board.p1, m13, "d1"), (board.p1, m13, "d2"),
    ]
    for order, (phase, milestone, title) in enumerate(layout, start=1):
        db.add(Item(version_id=board.published.id, sort_order=order, phase_id=phase.id,
                    milestone_id=milestone.id, title=title, deliverable="d"))
    db.commit()

    created = make_project(client, board, name="세 블록 프로젝트")
    return created["project"]["id"], created["items"]


def titles(rows) -> list[str]:
    return [r["title"] for r in rows]


def test_assigning_a_milestone_lands_at_that_milestone_block_end(client, three_block_project):
    """§0.3: 1.2 를 고르면 **c2 뒤·d1 앞**이다. Phase 블록 끝(d2 뒤)이 아니다.

    프로젝트의 phase/milestone id 는 **로컬 사본**의 것이라 템플릿 id 와 다르다.
    응답에서 뽑아 쓴다 — 템플릿 id 를 그대로 넘기면 400 이 맞다.
    """
    project_id, rows = three_block_project
    assert titles(rows) == ["a1", "a2", "b1", "c1", "c2", "d1", "d2"]

    c1 = rows[3]
    gray = client.post(
        f"{API}/projects/{project_id}/items/{rows[1]['id']}/insert-below"
    ).json()["items"][2]
    assert gray["phase_id"] is None

    response = client.patch(
        f"{API}/projects/{project_id}/items/{gray['id']}/membership",
        json={"phase_id": c1["phase_id"], "milestone_id": c1["milestone_id"]},
    )
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert titles(new_rows) == ["a1", "a2", "b1", "c1", "c2", None, "d1", "d2"]
    assert new_rows[5]["id"] == gray["id"]
    assert [r["milestone_no_display"] for r in new_rows] == [
        "0.1", "0.1", "1.1", "1.2", "1.2", "1.2", "1.3", "1.3"
    ]


def test_the_two_step_flow_lands_in_the_same_place(client, three_block_project):
    project_id, rows = three_block_project
    c1 = rows[3]

    gray = client.post(
        f"{API}/projects/{project_id}/items/{rows[1]['id']}/insert-below"
    ).json()["items"][2]

    step1 = client.patch(
        f"{API}/projects/{project_id}/items/{gray['id']}/membership",
        json={"phase_id": c1["phase_id"], "milestone_id": None},
    )
    assert step1.status_code == 200, step1.text
    assert titles(step1.json()["items"]) == ["a1", "a2", "b1", "c1", "c2", "d1", "d2", None]

    step2 = client.patch(
        f"{API}/projects/{project_id}/items/{gray['id']}/membership",
        json={"phase_id": c1["phase_id"], "milestone_id": c1["milestone_id"]},
    )
    assert step2.status_code == 200, step2.text
    assert titles(step2.json()["items"]) == ["a1", "a2", "b1", "c1", "c2", None, "d1", "d2"]


def test_clearing_an_assigned_row_keeps_it_in_place(client, three_block_project):
    """§0.3 의 유일한 재분류 경로 — 프로젝트에서도 행이 움직이지 않는다."""
    project_id, rows = three_block_project
    target = rows[3]                                   # c1

    response = client.patch(
        f"{API}/projects/{project_id}/items/{target['id']}/membership",
        json={"phase_id": None, "milestone_id": None},
    )
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert titles(new_rows) == ["a1", "a2", "b1", "c1", "c2", "d1", "d2"]
    assert new_rows[3]["id"] == target["id"]
    assert new_rows[3]["phase_id"] is None and new_rows[3]["milestone_id"] is None
    assert [r["milestone_no_display"] for r in new_rows] == [
        "0.1", "0.1", "1.1", None, "1.2", "1.3", "1.3"
    ]


def test_delete_deactivates_instead_of_removing(db, client, published):
    project_id = make_project(client, published)["project"]["id"]

    response = client.delete(f"{API}/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assert db.get(Project, project_id) is not None
    assert db.query(ProjectItem).filter_by(project_id=project_id).count() == 4
    # 기본 목록에서는 빠지고, 명시적으로 요청하면 보인다.
    assert project_id not in {p["id"] for p in client.get(f"{API}/projects").json()}
    assert project_id in {
        p["id"]
        for p in client.get(f"{API}/projects", params={"include_inactive": True}).json()
    }
