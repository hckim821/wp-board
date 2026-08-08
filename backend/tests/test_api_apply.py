"""Phase/Milestone 관리 팝업의 원자적 적용 — plan.md §0.4.

여기서 확인하는 것은 세 가지다.

1. **인덱싱** — 표의 순서가 곧 번호다. 0 과 1 사이에 새 Phase 를 끼우면 기존 1 은
   2 가 되고 하위 행·마일스톤 표시 번호가 전부 따라 바뀐다. 번호를 직접 만지는
   코드가 없다는 것이 이 규칙의 근거이므로, 파생이 실제로 일어나는지 본다.
2. **회색 행의 부착** — 미배정 행은 직전 배정 행과 한 몸으로 움직이고, 최상단의
   선행 회색 행은 최상단에 남는다.
3. **거부** — 422 목록 전부. 집합 불일치·중복·스코프 밖·교차 계층·빈 이름·
   앵커 규칙·비 DRAFT. 그리고 **아무것도 반영되지 않았다**는 원자성.

두 계층이 같은 구현을 쓰므로 프로젝트 쪽도 같은 값을 내야 한다 (`test_project_*`).
"""

from __future__ import annotations

import itertools

import pytest

from app.models import Item, ItemDocument, ItemOwner, Milestone, Phase, Template
from app.services import version_service

pytestmark = pytest.mark.db

API = "/api/v1"


# =============================================================================
# 픽스처
# =============================================================================
def add_item(db, version, sort_order, phase, milestone, *, title=None, docs=(), owners=()):
    item = Item(
        version_id=version.id,
        sort_order=sort_order,
        phase_id=phase.id if phase else None,
        milestone_id=milestone.id if milestone else None,
        title=title or f"행 {sort_order}",
        deliverable=f"산출물 {sort_order}",
    )
    item.documents = [ItemDocument(template_document_id=d.id, sort_order=i) for i, d in enumerate(docs, 1)]
    item.owners = [ItemOwner(owner_id=o.id, sort_order=i) for i, o in enumerate(owners, 1)]
    db.add(item)
    db.flush()
    return item


@pytest.fixture
def three_phases(db, board):
    """Phase 0/1/2 각각 행 2개, 마일스톤 1개씩인 DRAFT.

    `p2` 와 `m21` 은 기본 `board` 픽스처에 없으므로 여기서 만든다.
    """
    b = board
    p2 = Phase(template_id=b.wp.id, name="Evaluation", seq_no=2)
    db.add(p2)
    db.flush()
    m21 = Milestone(template_id=b.wp.id, phase_id=p2.id, name="평가 설계", seq_no=1)
    db.add(m21)
    db.flush()

    layout = [
        (b.p0, b.m01, "a1"), (b.p0, b.m01, "a2"),
        (b.p1, b.m11, "b1"), (b.p1, b.m11, "b2"),
        (p2, m21, "c1"), (p2, m21, "c2"),
    ]
    for order, (phase, milestone, title) in enumerate(layout, start=1):
        add_item(db, b.published, order, phase, milestone, title=title)
    db.commit()

    b.p2, b.m21 = p2, m21
    b.draft = version_service.create_draft(db, b.wp.id)
    db.commit()
    return b


def board_of(client, version_id):
    response = client.get(f"{API}/versions/{version_id}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def apply_phases(client, version_id, phases, deleted_ids=(), anchor_item_id=None):
    return client.post(
        f"{API}/versions/{version_id}/phases/apply",
        json={
            "phases": phases,
            "deleted_ids": list(deleted_ids),
            "anchor_item_id": anchor_item_id,
        },
    )


def apply_milestones(client, version_id, phase_id, milestones, deleted_ids=(), anchor_item_id=None):
    return client.post(
        f"{API}/versions/{version_id}/phases/{phase_id}/milestones/apply",
        json={
            "milestones": milestones,
            "deleted_ids": list(deleted_ids),
            "anchor_item_id": anchor_item_id,
        },
    )


def keep(entity, name=None):
    return {"id": entity.id, "name": name or entity.name}


def titles(rows):
    return [r["title"] for r in rows]


def row_exists(db, model, entity_id) -> bool:
    """DB 를 **다시 읽어** 확인한다.

    테스트 세션은 요청 세션과 별개라 identity map 에 낡은 객체가 남아 있다.
    `db.get()` 은 그것을 그대로 돌려주므로 삭제 여부를 확인할 수 없다.
    """
    from sqlalchemy import func, select

    db.rollback()
    return bool(db.scalar(select(func.count()).select_from(model).where(model.id == entity_id)))


# =============================================================================
# 인덱싱 — 순서가 곧 번호다
# =============================================================================
def test_reordering_phases_reindexes_rows_and_milestones(client, three_phases):
    """P0 P1 P2 → P2 P0 P1. 번호는 요청이 아니라 **순서**에서 나온다."""
    b = three_phases
    response = apply_phases(client, b.draft.id, [keep(b.p2), keep(b.p0), keep(b.p1)])
    assert response.status_code == 200, response.text
    rows = response.json()["items"]

    assert titles(rows) == ["c1", "c2", "a1", "a2", "b1", "b2"]
    assert [r["phase_no"] for r in rows] == [0, 0, 1, 1, 2, 2]
    assert [r["row_no"] for r in rows] == [1, 2, 3, 4, 5, 6]
    # 마일스톤 표시번호의 앞자리는 소속 Phase 에서 파생한다 — 저장값이 아니다.
    assert [r["milestone_no_display"] for r in rows] == ["0.1", "0.1", "1.1", "1.1", "2.1", "2.1"]


def test_inserting_a_phase_between_0_and_1_pushes_the_rest_down(client, three_phases):
    """§0.4 의 대표 시나리오. 기존 1 → 2, 2 → 3 이 되어야 한다."""
    b = three_phases
    response = apply_phases(
        client, b.draft.id, [keep(b.p0), {"id": None, "name": "새 단계"}, keep(b.p1), keep(b.p2)]
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    rows = payload["items"]

    assert [r["phase_no"] for r in rows] == [0, 0, 1, 2, 2, 3, 3]
    assert titles(rows) == ["a1", "a2", None, "b1", "b2", "c1", "c2"]

    # 신규 Phase 를 지탱하는 빈 행이 함께 생겼다 (§0.4 — 행 없는 Phase 는 없다).
    created = rows[2]
    assert created["origin"] == "ADDED"
    assert created["status"] == "NOT_STARTED"
    assert created["phase_name"] == "새 단계"
    assert created["milestone_id"] is None

    # 기준정보 목록도 같은 응답에 실린다 — 팝업이 새 id 를 곧바로 알 수 있어야 한다.
    assert [p["name"] for p in payload["phases"]][:4] == [
        "Pre-Infrastructure Setup", "새 단계", "Initiation & Readiness", "Evaluation"
    ]
    assert [p["seq_no"] for p in payload["phases"]][:4] == [0, 1, 2, 3]


def test_renaming_is_applied_without_touching_order(client, three_phases):
    b = three_phases
    response = apply_phases(
        client, b.draft.id, [keep(b.p0, "이름 변경"), keep(b.p1), keep(b.p2)]
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert rows[0]["phase_display"] == "Phase 0. 이름 변경"
    assert titles(rows) == ["a1", "a2", "b1", "b2", "c1", "c2"]


def test_two_phases_can_swap_names(client, three_phases):
    """A↔B 교환. UQ(template_id, name) 때문에 한 번에 쓰면 깨진다."""
    b = three_phases
    response = apply_phases(
        client,
        b.draft.id,
        [keep(b.p0, b.p1.name), keep(b.p1, b.p0.name), keep(b.p2)],
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert rows[0]["phase_name"] == "Initiation & Readiness"
    assert rows[2]["phase_name"] == "Pre-Infrastructure Setup"


def test_the_anchor_row_becomes_the_first_row_of_the_new_phase(client, three_phases):
    """앵커가 있으면 빈 행을 만들지 않고 그 회색 행을 옮겨 배정한다."""
    b = three_phases
    rows = board_of(client, b.draft.id)
    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[5]['id']}/insert-below"
    ).json()["items"][6]
    assert gray["phase_id"] is None

    response = apply_phases(
        client,
        b.draft.id,
        [keep(b.p0), {"id": None, "name": "사이 단계"}, keep(b.p1), keep(b.p2)],
        anchor_item_id=gray["id"],
    )
    assert response.status_code == 200, response.text
    result = response.json()["items"]

    assert len(result) == 7                      # 빈 행이 추가로 생기지 않았다
    assert result[2]["id"] == gray["id"]
    assert result[2]["phase_name"] == "사이 단계"
    assert [r["phase_no"] for r in result] == [0, 0, 1, 2, 2, 3, 3]


# =============================================================================
# 회색 행의 부착 — §0.4
# =============================================================================
def test_a_gray_row_travels_with_the_block_above_it(client, three_phases):
    """`P0 P0 [회색] P1 P1 P2 P2` 에서 P0 블록을 끝으로 보내면 회색 행도 따라간다."""
    b = three_phases
    rows = board_of(client, b.draft.id)
    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[1]['id']}/insert-below"
    ).json()["items"][2]

    response = apply_phases(client, b.draft.id, [keep(b.p1), keep(b.p2), keep(b.p0)])
    assert response.status_code == 200, response.text
    result = response.json()["items"]

    assert titles(result) == ["b1", "b2", "c1", "c2", "a1", "a2", None]
    assert result[-1]["id"] == gray["id"]
    assert result[-1]["phase_id"] is None
    assert [r["phase_no"] for r in result] == [0, 0, 1, 1, 2, 2, None]


def test_leading_gray_rows_stay_at_the_top(client, three_phases):
    """최상단의 선행 회색 행은 붙을 블록이 없으므로 최상단에 남는다 (§0.4)."""
    b = three_phases
    appended = client.post(f"{API}/versions/{b.draft.id}/items").json()["items"]
    gray_id = appended[-1]["id"]
    moved = client.post(
        f"{API}/versions/{b.draft.id}/items/reorder",
        json={"item_ids": [gray_id] + [r["id"] for r in appended[:-1]]},
    )
    assert moved.status_code == 200, moved.text

    response = apply_phases(client, b.draft.id, [keep(b.p2), keep(b.p1), keep(b.p0)])
    assert response.status_code == 200, response.text
    result = response.json()["items"]

    assert result[0]["id"] == gray_id
    assert result[0]["phase_id"] is None
    assert titles(result) == [None, "c1", "c2", "b1", "b2", "a1", "a2"]


def test_deleting_a_block_keeps_its_attached_gray_row(client, three_phases):
    """회색 행은 그 Phase 에 속하지 않으므로 캐스케이드 대상이 아니다."""
    b = three_phases
    rows = board_of(client, b.draft.id)
    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[3]['id']}/insert-below"
    ).json()["items"][4]                                   # P1 블록 끝에 붙은 회색 행

    response = apply_phases(client, b.draft.id, [keep(b.p0), keep(b.p2)], deleted_ids=[b.p1.id])
    assert response.status_code == 200, response.text
    result = response.json()["items"]

    # P1 의 두 행만 사라지고 회색 행은 앞쪽 생존 블록(P0)에 다시 붙는다.
    assert titles(result) == ["a1", "a2", None, "c1", "c2"]
    assert result[2]["id"] == gray["id"]
    assert [r["row_no"] for r in result] == [1, 2, 3, 4, 5]


# =============================================================================
# 캐스케이드 삭제
# =============================================================================
def test_deleting_a_phase_removes_its_rows_and_milestones(db, client, three_phases):
    b = three_phases
    response = apply_phases(client, b.draft.id, [keep(b.p0), keep(b.p2)], deleted_ids=[b.p1.id])
    assert response.status_code == 200, response.text
    payload = response.json()

    assert titles(payload["items"]) == ["a1", "a2", "c1", "c2"]
    assert [r["row_no"] for r in payload["items"]] == [1, 2, 3, 4]
    assert [r["phase_no"] for r in payload["items"]] == [0, 0, 1, 1]

    # 기준정보에서도 사라졌다 — 이 Phase 는 PUBLISHED 도 쓰고 있으므로
    # 물리 삭제 대신 비활성화된다 (아래 전용 테스트 참고).
    assert b.p1.id not in [p["id"] for p in payload["phases"] if p["is_active"]]
    assert b.m11.id not in [m["id"] for m in payload["milestones"] if m["is_active"]]


def test_a_phase_used_by_no_other_version_is_hard_deleted(db, client, board):
    """다른 버전이 안 쓰면 실제로 지운다 (`master_service` 의 기존 정책)."""
    b = board
    b.draft = version_service.create_draft(db, b.wp.id)      # PUBLISHED 가 비어 있다
    db.commit()
    add_item(db, b.draft, 1, b.p0, b.m01, title="x")
    add_item(db, b.draft, 2, b.p1, b.m11, title="y")
    db.commit()

    response = apply_phases(client, b.draft.id, [keep(b.p1)], deleted_ids=[b.p0.id])
    assert response.status_code == 200, response.text
    assert row_exists(db, Phase, b.p0.id) is False
    assert row_exists(db, Milestone, b.m01.id) is False


def test_deleting_a_milestone_removes_only_its_rows(client, three_phases, db):
    b = three_phases
    m02_rows = [
        add_item(db, b.draft, 99, b.p0, b.m02, title="a3"),
    ]
    db.commit()
    # a3 를 P0 블록 끝(a1 a2 뒤)으로 옮긴다.
    rows = board_of(client, b.draft.id)
    order = [r["id"] for r in rows if r["title"] != "a3"]
    order.insert(2, m02_rows[0].id)
    assert client.post(
        f"{API}/versions/{b.draft.id}/items/reorder", json={"item_ids": order}
    ).status_code == 200

    response = apply_milestones(client, b.draft.id, b.p0.id, [keep(b.m01)], deleted_ids=[b.m02.id])
    assert response.status_code == 200, response.text
    result = response.json()["items"]
    assert titles(result) == ["a1", "a2", "b1", "b2", "c1", "c2"]
    assert [r["row_no"] for r in result] == [1, 2, 3, 4, 5, 6]


# =============================================================================
# Milestone 적용
# =============================================================================
@pytest.fixture
def two_milestones(db, three_phases):
    """P0 안에 마일스톤 2개: `a1(0.1) a2(0.1) a3(0.2) a4(0.2)`."""
    b = three_phases
    rows = list(
        db.query(Item).filter(Item.version_id == b.draft.id).order_by(Item.sort_order).all()
    )
    extra = [
        add_item(db, b.draft, 0, b.p0, b.m02, title="a3"),
        add_item(db, b.draft, 0, b.p0, b.m02, title="a4"),
    ]
    order = [rows[0], rows[1], *extra, *rows[2:]]
    for index, item in enumerate(order, start=1):
        item.sort_order = index
    db.commit()
    return b


def test_reordering_milestones_reindexes_only_inside_the_phase(client, two_milestones):
    b = two_milestones
    response = apply_milestones(client, b.draft.id, b.p0.id, [keep(b.m02), keep(b.m01)])
    assert response.status_code == 200, response.text
    rows = response.json()["items"]

    assert titles(rows) == ["a3", "a4", "a1", "a2", "b1", "b2", "c1", "c2"]
    assert [r["milestone_no_display"] for r in rows] == [
        "0.1", "0.1", "0.2", "0.2", "1.1", "1.1", "2.1", "2.1"
    ]
    # 다른 Phase 의 블록은 순서도 번호도 그대로다.
    assert [r["phase_no"] for r in rows] == [0, 0, 0, 0, 1, 1, 2, 2]


def test_creating_a_milestone_adds_an_empty_row_in_that_phase(client, two_milestones):
    b = two_milestones
    response = apply_milestones(
        client, b.draft.id, b.p0.id, [keep(b.m01), {"id": None, "name": "신규 MS"}, keep(b.m02)]
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]

    assert titles(rows) == ["a1", "a2", None, "a3", "a4", "b1", "b2", "c1", "c2"]
    created = rows[2]
    assert created["phase_id"] == b.p0.id
    assert created["milestone_name"] == "신규 MS"
    assert created["milestone_no_display"] == "0.2"
    assert created["origin"] == "ADDED"
    assert rows[3]["milestone_no_display"] == "0.3"


def test_a_gray_row_can_anchor_a_new_milestone(client, two_milestones):
    b = two_milestones
    rows = board_of(client, b.draft.id)
    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[-1]['id']}/insert-below"
    ).json()["items"][-1]

    response = apply_milestones(
        client,
        b.draft.id,
        b.p0.id,
        [keep(b.m01), keep(b.m02), {"id": None, "name": "앵커 MS"}],
        anchor_item_id=gray["id"],
    )
    assert response.status_code == 200, response.text
    result = response.json()["items"]

    assert result[4]["id"] == gray["id"]
    assert result[4]["phase_id"] == b.p0.id
    assert result[4]["milestone_no_display"] == "0.3"
    assert len(result) == len(rows) + 1          # 회색 행 1개만 늘었다


def test_a_phase_assigned_row_can_anchor_a_new_milestone(client, two_milestones):
    """§0.3 — Milestone 셀 에디터가 열리는 유일한 상태가 "phase 만 배정" 이다."""
    b = two_milestones
    rows = board_of(client, b.draft.id)
    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[3]['id']}/insert-below"
    ).json()["items"][4]
    assigned = client.patch(
        f"{API}/versions/{b.draft.id}/items/{gray['id']}/membership",
        json={"phase_id": b.p0.id, "milestone_id": None},
    )
    assert assigned.status_code == 200, assigned.text

    response = apply_milestones(
        client,
        b.draft.id,
        b.p0.id,
        [keep(b.m01), keep(b.m02), {"id": None, "name": "앵커 MS"}],
        anchor_item_id=gray["id"],
    )
    assert response.status_code == 200, response.text
    result = response.json()["items"]
    assert result[4]["id"] == gray["id"]
    assert result[4]["milestone_name"] == "앵커 MS"


# =============================================================================
# 422 — 거부되는 요청 전부. 그리고 아무것도 반영되지 않는다.
# =============================================================================
def _unchanged(client, version_id, before):
    assert board_of(client, version_id) == before


def test_a_missing_id_is_rejected_as_a_set_mismatch(client, three_phases):
    b = three_phases
    before = board_of(client, b.draft.id)

    response = apply_phases(client, b.draft.id, [keep(b.p0), keep(b.p1)])
    assert response.status_code == 422, response.text
    body = response.json()["detail"]
    assert body["code"] == "APPLY_SET_MISMATCH"
    assert body["missing"] == [b.p2.id]
    _unchanged(client, b.draft.id, before)


def test_deleting_without_listing_the_rest_is_rejected(client, three_phases):
    b = three_phases
    before = board_of(client, b.draft.id)
    response = apply_phases(client, b.draft.id, [keep(b.p0)], deleted_ids=[b.p1.id])
    assert response.status_code == 422
    assert response.json()["detail"]["missing"] == [b.p2.id]
    _unchanged(client, b.draft.id, before)


def test_a_duplicate_id_is_rejected(client, three_phases):
    b = three_phases
    before = board_of(client, b.draft.id)
    response = apply_phases(
        client, b.draft.id, [keep(b.p0), keep(b.p1), keep(b.p1), keep(b.p2)]
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APPLY_DUPLICATE_ID"
    _unchanged(client, b.draft.id, before)


def test_an_id_in_both_the_list_and_deleted_ids_is_rejected(client, three_phases):
    b = three_phases
    response = apply_phases(
        client, b.draft.id, [keep(b.p0), keep(b.p1), keep(b.p2)], deleted_ids=[b.p2.id]
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APPLY_DUPLICATE_ID"


def test_a_phase_from_another_template_is_rejected(db, client, three_phases):
    """기준정보는 보드 스코프다 — 남의 것은 참조할 수 없다."""
    b = three_phases
    other = Template(code="OTHER", name="다른 템플릿")
    db.add(other)
    db.flush()
    foreign = Phase(template_id=other.id, name="남의 Phase", seq_no=0)
    db.add(foreign)
    db.commit()

    before = board_of(client, b.draft.id)
    response = apply_phases(
        client, b.draft.id, [keep(b.p0), keep(b.p1), keep(b.p2), keep(foreign)]
    )
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["code"] == "APPLY_OUT_OF_SCOPE"
    assert body["ids"] == [foreign.id]
    _unchanged(client, b.draft.id, before)


def test_a_template_phase_cannot_be_applied_to_a_project(client, project):
    """교차 계층 — 템플릿의 Phase id 를 프로젝트 apply 에 쓸 수 없다.

    프로젝트의 기준정보는 생성 시 복제된 **로컬 사본**이라 id 가 다르다.
    """
    b = project
    project_id = b.project["project"]["id"]
    local_phases = {r["phase_id"] for r in b.project["items"]}
    assert b.p0.id not in local_phases

    response = client.post(
        f"{API}/projects/{project_id}/phases/apply",
        json={"phases": [{"id": b.p0.id, "name": "템플릿 Phase"}], "deleted_ids": []},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "APPLY_OUT_OF_SCOPE"


def test_an_empty_name_is_rejected(client, three_phases):
    b = three_phases
    for blank in ("", "   "):
        response = apply_phases(
            client, b.draft.id, [keep(b.p0), keep(b.p1), {"id": b.p2.id, "name": blank}]
        )
        assert response.status_code == 422, blank
        assert response.json()["detail"]["code"] == "APPLY_EMPTY_NAME"


def test_a_duplicate_name_is_rejected(client, three_phases):
    b = three_phases
    response = apply_phases(
        client, b.draft.id, [keep(b.p0), keep(b.p1, b.p0.name), keep(b.p2)]
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APPLY_DUPLICATE_NAME"


def test_an_anchor_must_be_a_gray_row(client, three_phases):
    b = three_phases
    rows = board_of(client, b.draft.id)
    before = list(rows)

    response = apply_phases(
        client,
        b.draft.id,
        [keep(b.p0), {"id": None, "name": "신규"}, keep(b.p1), keep(b.p2)],
        anchor_item_id=rows[0]["id"],                    # 배정된 행
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "APPLY_ANCHOR_INVALID"
    _unchanged(client, b.draft.id, before)


def test_an_anchor_requires_exactly_one_new_entry(client, three_phases):
    b = three_phases
    rows = board_of(client, b.draft.id)
    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[-1]['id']}/insert-below"
    ).json()["items"][-1]

    for entries in (
        [keep(b.p0), keep(b.p1), keep(b.p2)],                                   # 신규 0개
        [keep(b.p0), {"id": None, "name": "A"}, {"id": None, "name": "B"},
         keep(b.p1), keep(b.p2)],                                               # 신규 2개
    ):
        response = apply_phases(client, b.draft.id, entries, anchor_item_id=gray["id"])
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "APPLY_ANCHOR_INVALID"


def test_an_unknown_anchor_is_rejected(client, three_phases):
    b = three_phases
    response = apply_phases(
        client,
        b.draft.id,
        [keep(b.p0), {"id": None, "name": "신규"}, keep(b.p1), keep(b.p2)],
        anchor_item_id=999999,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APPLY_ANCHOR_INVALID"


def test_a_milestone_from_another_phase_is_rejected(client, three_phases):
    b = three_phases
    response = apply_milestones(client, b.draft.id, b.p0.id, [keep(b.m01), keep(b.m11)])
    assert response.status_code == 422, response.text
    body = response.json()["detail"]
    assert body["code"] == "APPLY_OUT_OF_SCOPE"
    assert body["ids"] == [b.m11.id]


def test_milestones_apply_needs_a_phase_that_is_on_the_board(db, client, three_phases):
    b = three_phases
    unused = Phase(template_id=b.wp.id, name="행 없는 Phase", seq_no=9)
    db.add(unused)
    db.commit()

    response = apply_milestones(client, b.draft.id, unused.id, [])
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APPLY_SET_MISMATCH"


def test_published_and_archived_versions_reject_apply(db, client, three_phases):
    """비 DRAFT 는 기존 쓰기 차단 계층이 잡는다 — 새 관문을 만들지 않았다."""
    from app.models import VersionStatus

    b = three_phases
    for status in (VersionStatus.PUBLISHED, VersionStatus.ARCHIVED):
        version = db.get(type(b.published), b.published.id)
        version.status = status
        db.commit()

        response = apply_phases(client, b.published.id, [keep(b.p0), keep(b.p1), keep(b.p2)])
        assert response.status_code == 409, f"{status} -> {response.status_code} {response.text}"
        assert response.json()["detail"]["code"] == "CONFLICT"

        response = apply_milestones(client, b.published.id, b.p0.id, [keep(b.m01)])
        assert response.status_code == 409, status


# =============================================================================
# 연속성 — 블록 단위 재배열이므로 구조적으로 0이어야 한다
# =============================================================================
def _assert_contiguous(rows):
    """응답 행 목록에 조각난 블록이 없는지 직접 확인한다."""
    from app.services.renumber_service import RowRef, find_contiguity_breaks

    refs = [RowRef(r["id"], r["phase_id"], r["milestone_id"]) for r in rows]
    breaks = find_contiguity_breaks(refs)
    assert breaks == [], breaks


def test_every_phase_permutation_keeps_the_board_contiguous(client, three_phases):
    """**전수**다. 부하가 걸린 주장은 표본으로 확인하지 않는다 (HANDOFF §6.2).

    보드에 회색 행을 하나 섞어 둔다 — 회색 행이 블록에 부착되어 함께 움직이는
    경로가 순열마다 실제로 밟힌다.
    """
    b = three_phases
    rows = board_of(client, b.draft.id)
    client.post(f"{API}/versions/{b.draft.id}/items/{rows[3]['id']}/insert-below")

    phases = [b.p0, b.p1, b.p2]
    for order in itertools.permutations(phases):
        response = apply_phases(client, b.draft.id, [keep(p) for p in order])
        assert response.status_code == 200, f"{[p.name for p in order]} -> {response.text}"
        result = response.json()["items"]

        _assert_contiguous(result)
        assert [r["row_no"] for r in result] == list(range(1, len(result) + 1))

        # 번호는 요청 순서에서 파생한다 — 저장된 seq_no 를 읽는 것이 아니다.
        seen: list[int] = []
        for row in result:
            if row["phase_id"] is not None and row["phase_id"] not in seen:
                seen.append(row["phase_id"])
        assert seen == [p.id for p in order]
        assert [r["phase_no"] for r in result if r["phase_id"] is not None] == [
            seen.index(r["phase_id"]) for r in result if r["phase_id"] is not None
        ]


def test_every_milestone_permutation_keeps_the_board_contiguous(client, two_milestones):
    b = two_milestones
    for order in itertools.permutations([b.m01, b.m02]):
        response = apply_milestones(client, b.draft.id, b.p0.id, [keep(m) for m in order])
        assert response.status_code == 200, response.text
        result = response.json()["items"]
        _assert_contiguous(result)
        assert [r["row_no"] for r in result] == list(range(1, len(result) + 1))


# =============================================================================
# 프로젝트 계층 — 같은 구현이므로 같은 결과라야 한다
# =============================================================================
@pytest.fixture
def project(db, client, three_phases):
    b = three_phases
    for item in db.query(Item).filter(Item.version_id == b.published.id).all():
        item.documents = [ItemDocument(template_document_id=b.d1.id, sort_order=1)]
        item.owners = [ItemOwner(owner_id=b.o1.id, sort_order=1)]
    db.commit()

    created = client.post(
        f"{API}/projects", json={"maker_id": 7, "name": "적용 검사", "template_id": b.wp.id}
    )
    assert created.status_code == 201, created.text
    b.project = created.json()
    return b


def local_phase_ids(rows) -> list[int]:
    """행 순서상 최초 등장 순서로 본 프로젝트 로컬 Phase id."""
    seen: list[int] = []
    for row in rows:
        if row["phase_id"] is not None and row["phase_id"] not in seen:
            seen.append(row["phase_id"])
    return seen


def test_project_phase_apply_behaves_like_the_template(client, project):
    b = project
    project_id = b.project["project"]["id"]
    p0, p1, p2 = local_phase_ids(b.project["items"])

    response = client.post(
        f"{API}/projects/{project_id}/phases/apply",
        json={
            "phases": [{"id": p2, "name": "C"}, {"id": p0, "name": "A"}, {"id": p1, "name": "B"}],
            "deleted_ids": [],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["items"]
    assert titles(result) == ["c1", "c2", "a1", "a2", "b1", "b2"]
    assert [r["phase_no"] for r in result] == [0, 0, 1, 1, 2, 2]
    assert [r["phase_name"] for r in result] == ["C", "C", "A", "A", "B", "B"]
    _assert_contiguous(result)


def test_project_apply_does_not_touch_the_template(client, project, db):
    """프로젝트 편집은 중앙 기준 데이터에 전파되지 않는다 (plan.md §0.1)."""
    b = project
    project_id = b.project["project"]["id"]
    p0, p1, p2 = local_phase_ids(b.project["items"])

    response = client.post(
        f"{API}/projects/{project_id}/phases/apply",
        json={
            "phases": [{"id": p0, "name": "프로젝트에서만 바뀐 이름"}],
            "deleted_ids": [p1, p2],
        },
    )
    assert response.status_code == 200, response.text
    assert titles(response.json()["items"]) == ["a1", "a2"]

    db.rollback()
    assert db.get(Phase, b.p0.id).name == "Pre-Infrastructure Setup"
    assert row_exists(db, Phase, b.p1.id) is True
    assert row_exists(db, Milestone, b.m11.id) is True
    # 템플릿 DRAFT 의 행도 그대로다.
    assert db.query(Item).filter(Item.version_id == b.draft.id).count() == 6
