"""행 조작 API — plan.md §4.2 / §4.3.

HTTP 를 통과시켜, 응답 계약(재계산된 전체 행 + 경계 플래그)과 불변성 가드를
함께 확인한다.
"""

from __future__ import annotations

import pytest

from app.models import Item, ItemDocument, ItemOwner, VersionStatus
from app.services import version_service

pytestmark = pytest.mark.db

API = "/api/v1"


def add_item(db, version, sort_order, phase, milestone, *, docs=(), owners=()):
    item = Item(
        version_id=version.id,
        sort_order=sort_order,
        phase_id=phase.id,
        milestone_id=milestone.id,
        title=f"행 {sort_order}",
        deliverable=f"산출물 {sort_order}",
    )
    item.documents = [ItemDocument(template_document_id=d.id, sort_order=i) for i, d in enumerate(docs, 1)]
    item.owners = [ItemOwner(owner_id=o.id, sort_order=i) for i, o in enumerate(owners, 1)]
    db.add(item)
    db.flush()
    return item


@pytest.fixture
def draft(db, board):
    """행 4개짜리 DRAFT: [P0/M01, P0/M01, P0/M02, P1/M11]."""
    b = board
    layout = [(b.p0, b.m01), (b.p0, b.m01), (b.p0, b.m02), (b.p1, b.m11)]
    for order, (phase, milestone) in enumerate(layout, start=1):
        add_item(db, b.published, order, phase, milestone, docs=[b.d1], owners=[b.o1])
    db.commit()

    version = version_service.create_draft(db, b.wp.id)
    db.commit()
    b.draft = version
    return b


@pytest.fixture
def three_block_draft(db, board):
    """Phase 1 이 **Milestone 블록 3개**인 DRAFT — plan.md §0.3 재배치 규칙 검증용.

    `a1 a2 | b1(1.1) c1(1.2) c2(1.2) d1(1.3) d2(1.3)`

    기본 `draft` 픽스처로는 이 규칙을 검사할 수 없다. 거기서는 P1 의 Milestone 이
    `m11` 하나뿐이라 **마일스톤 블록 끝과 Phase 블록 끝이 같은 자리**이고, 따라서
    phase 단위로만 재배치하는 구현도 똑같이 통과한다. 대상 마일스톤이 자기 Phase 의
    **마지막이 아닌** 배치가 있어야 두 구현이 갈라진다.
    """
    from app.models import Milestone

    b = board
    m12 = Milestone(template_id=b.wp.id, phase_id=b.p1.id, name="설계", seq_no=2)
    m13 = Milestone(template_id=b.wp.id, phase_id=b.p1.id, name="구현", seq_no=3)
    db.add_all([m12, m13])
    db.flush()

    layout = [
        (b.p0, b.m01, "a1"), (b.p0, b.m01, "a2"),
        (b.p1, b.m11, "b1"),
        (b.p1, m12, "c1"), (b.p1, m12, "c2"),
        (b.p1, m13, "d1"), (b.p1, m13, "d2"),
    ]
    for order, (phase, milestone, title) in enumerate(layout, start=1):
        item = add_item(db, b.published, order, phase, milestone)
        item.title = title
    db.commit()

    b.m12, b.m13 = m12, m13
    b.draft = version_service.create_draft(db, b.wp.id)
    db.commit()
    return b


def items_of(client, version_id):
    response = client.get(f"{API}/versions/{version_id}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


# =============================================================================
# 조회 응답 계약
# =============================================================================
def test_version_detail_carries_numbering_and_boundary_flags(client, draft):
    rows = items_of(client, draft.draft.id)

    assert [r["row_no"] for r in rows] == [1, 2, 3, 4]
    assert [r["phase_no"] for r in rows] == [0, 0, 0, 1]
    assert [r["milestone_no"] for r in rows] == [1, 1, 2, 1]
    assert rows[0]["phase_display"] == "Phase 0. Pre-Infrastructure Setup"
    assert rows[2]["milestone_no_display"] == "0.2"
    assert rows[2]["milestone_display"] == "0.2 I/O 연결"
    assert [r["is_phase_block_start"] for r in rows] == [True, False, False, True]
    assert [r["can_create_phase"] for r in rows] == [True, False, True, True]


def test_version_detail_includes_the_n_to_m_links(client, draft):
    row = items_of(client, draft.draft.id)[0]
    assert row["documents"] == [{"id": draft.d1.id, "no": 1, "name": "Project Charter & R&R"}]
    assert row["owners"] == [{"id": draft.o1.id, "name": "DSEP 인프라 담당자"}]


# =============================================================================
# 행 추가
# =============================================================================
def test_insert_below_creates_a_gray_row(client, draft):
    """plan.md §0.2: 신규 행은 **미배정**이다. 상속하지 않는다.

    상속 규칙은 드래그가 블록 내부로 제한된 뒤 새 행을 기존 블록 안에 가두어,
    기존 Phase 사이에 항목을 넣을 방법을 없앴다.
    """
    rows = items_of(client, draft.draft.id)
    anchor = rows[2]                                  # P0 / M02

    response = client.post(f"{API}/versions/{draft.draft.id}/items/{anchor['id']}/insert-below")
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert len(new_rows) == 5
    inserted = new_rows[3]
    assert inserted["phase_id"] is None
    assert inserted["milestone_id"] is None
    assert inserted["phase_no"] is None
    assert inserted["origin"] == "ADDED"
    assert [r["row_no"] for r in new_rows] == [1, 2, 3, 4, 5]


def test_a_gray_row_between_two_blocks_offers_phase_creation(client, draft):
    """§0.2-4/5 의 사용자 시나리오 — P0 블록과 P1 블록 사이에 행을 넣는다.

    보드는 `[P0/M01, P0/M01, P0/M02, P1/M11]` 이므로 3행 아래가 곧 경계다.
    거기 생긴 회색 행에서 새 Phase 를 만들면 번호가 **사이에** 들어간다.
    """
    rows = items_of(client, draft.draft.id)
    seam = rows[2]                                    # P0 블록의 마지막 행

    inserted = client.post(
        f"{API}/versions/{draft.draft.id}/items/{seam['id']}/insert-below"
    ).json()["items"][3]
    assert inserted["can_create_phase"] is True

    created = client.post(
        f"{API}/versions/{draft.draft.id}/items/{inserted['id']}/create-phase",
        json={"name": "사이 단계"},
    )
    assert created.status_code == 200, created.text
    assert [r["phase_no"] for r in created.json()["items"]] == [0, 0, 0, 1, 2]


def test_a_gray_row_inside_a_block_refuses_phase_creation(client, draft):
    """같은 블록 한가운데 회색 행에서는 만들 수 없다 — 그 블록이 쪼개지므로."""
    rows = items_of(client, draft.draft.id)
    anchor = rows[0]                                  # P0/M01 블록의 첫 행 (뒤에 같은 블록이 더 있다)

    inserted = client.post(
        f"{API}/versions/{draft.draft.id}/items/{anchor['id']}/insert-below"
    ).json()["items"][1]
    assert inserted["can_create_phase"] is False

    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/{inserted['id']}/create-phase",
        json={"name": "쪼개는 단계"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PHASE_BOUNDARY_VIOLATION"


def test_a_gray_row_is_not_a_contiguity_break(client, draft):
    """회색 행이 블록 한가운데 있어도 저장·조회가 정상이다 (§0.2-1 투명성)."""
    rows = items_of(client, draft.draft.id)
    client.post(f"{API}/versions/{draft.draft.id}/items/{rows[0]['id']}/insert-below")

    after = items_of(client, draft.draft.id)
    assert [r["phase_no"] for r in after] == [0, None, 0, 0, 1]


def test_insert_below_returns_the_whole_recomputed_list(client, draft):
    rows = items_of(client, draft.draft.id)
    response = client.post(f"{API}/versions/{draft.draft.id}/items/{rows[0]['id']}/insert-below")
    payload = response.json()["items"]
    # 마지막 Phase 1 행의 번호가 그대로여야 한다 (앞에 행이 늘어도 Phase 번호는 불변)
    assert payload[-1]["phase_no"] == 1
    assert payload[-1]["row_no"] == 5


def test_insert_below_rejects_an_unknown_anchor(client, draft):
    response = client.post(f"{API}/versions/{draft.draft.id}/items/999999/insert-below")
    assert response.status_code == 404


# =============================================================================
# 드래그 — 위치만 (plan.md §4.2)
# =============================================================================
def reorder(client, version_id, item_ids):
    return client.post(
        f"{API}/versions/{version_id}/items/reorder", json={"item_ids": item_ids}
    )


def membership(client, version_id, item_id, phase_id=None, milestone_id=None):
    return client.patch(
        f"{API}/versions/{version_id}/items/{item_id}/membership",
        json={"phase_id": phase_id, "milestone_id": milestone_id},
    )


def test_reorder_takes_positions_only(client, draft):
    """소속 필드도 `moved_item_id` 도 스키마가 받지 않는다 — 오용이 불가능하다.

    보드는 `[P0/M01, P0/M01, P0/M02, P1/M11]` 이므로 드래그로 자리를 바꿀 수 있는
    것은 첫 두 행뿐이다 (같은 Milestone 블록). 결과의 소속은 그대로다.
    """
    rows = items_of(client, draft.draft.id)
    order = [rows[1]["id"], rows[0]["id"], rows[2]["id"], rows[3]["id"]]

    response = reorder(client, draft.draft.id, order)
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert [r["id"] for r in new_rows] == order
    assert [(r["phase_id"], r["milestone_id"]) for r in new_rows] == [
        (draft.p0.id, draft.m01.id),
        (draft.p0.id, draft.m01.id),
        (draft.p0.id, draft.m02.id),
        (draft.p1.id, draft.m11.id),
    ]
    assert [r["phase_no"] for r in new_rows] == [0, 0, 0, 1]


def test_a_drag_never_reassigns_the_dragged_rows_phase(client, draft):
    """**§2.2 가 고친 버그 그 자체.**

    P1 행을 P0 블록 가운데로 끌면 예전에는 그 행의 Phase 가 **아무 경고 없이**
    P0 로 바뀌었고 (그래서 P1 자체가 사라졌고), 응답은 200 이었다. 지금은
    소속을 건드리지 않으므로 P0 가 두 조각이 되고 422 로 거부된다.
    """
    rows = items_of(client, draft.draft.id)
    before = items_of(client, draft.draft.id)
    order = [rows[0]["id"], rows[3]["id"], rows[1]["id"], rows[2]["id"]]

    response = reorder(client, draft.draft.id, order)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PHASE_NOT_CONTIGUOUS"
    assert items_of(client, draft.draft.id) == before      # 아무것도 저장되지 않았다


def test_moving_a_row_to_the_top_keeps_its_phase_and_renumbers_instead(client, draft):
    """P1 행을 맨 위로 옮기면 **그 행의 Phase 가 아니라 번호가 바뀐다.**

    예전에는 새 뒷행(P0)에서 소속을 물려받아 P1 이 보드에서 사라졌다. 지금은
    소속을 그대로 들고 가므로 결과는 `P1, P0, P0, P0` — 여전히 연속이라 200 이고,
    표시 번호만 최초 등장 순서에 따라 `0, 1, 1, 1` 로 다시 매겨진다.
    """
    rows = items_of(client, draft.draft.id)
    order = [rows[3]["id"], rows[0]["id"], rows[1]["id"], rows[2]["id"]]

    response = reorder(client, draft.draft.id, order)
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert new_rows[0]["phase_id"] == draft.p1.id      # 소속은 그대로
    assert new_rows[0]["phase_no"] == 0                # 번호만 바뀐다
    assert [r["phase_id"] for r in new_rows[1:]] == [draft.p0.id] * 3
    assert [r["phase_no"] for r in new_rows] == [0, 1, 1, 1]


def contiguous_runs(rows):
    blocks = [r["phase_id"] for r in rows]
    return [k for i, k in enumerate(blocks) if i == 0 or blocks[i - 1] != k]


def test_every_permutation_of_the_board_behaves_as_the_pure_function_says(client, draft):
    """4행 보드의 **24개 순열 전부**를 HTTP 로 돈다 (표본 아님).

    순수 함수 수준의 전수 증명은 `test_reorder_exhaustive.py` 가 n≤6 까지
    수행한다. 여기서 확인하는 것은 **HTTP 를 통과해도 결론이 같은지** 다.

    * 연속을 유지하는 순열 → 200, 그리고 모든 행의 소속이 그대로
    * 조각나는 순열 → 422, 그리고 보드가 요청 전과 완전히 동일
    """
    from itertools import permutations

    from app.services.renumber_service import RowRef, find_contiguity_breaks, reposition

    rows = items_of(client, draft.draft.id)
    ids = [r["id"] for r in rows]
    original = list(rows)
    refs = [RowRef(r["id"], r["phase_id"], r["milestone_id"]) for r in rows]
    membership = {r["id"]: (r["phase_id"], r["milestone_id"]) for r in rows}

    accepted = refused = 0
    for order in permutations(ids):
        expected_ok = find_contiguity_breaks(reposition(refs, list(order))) == []
        response = reorder(client, draft.draft.id, list(order))

        if expected_ok:
            accepted += 1
            assert response.status_code == 200, f"{order}: {response.text}"
            new_rows = response.json()["items"]
            assert [r["id"] for r in new_rows] == list(order)
            assert {r["id"]: (r["phase_id"], r["milestone_id"]) for r in new_rows} == membership
            runs = contiguous_runs(new_rows)
            assert len(runs) == len(set(runs)), f"non-contiguous for {order}"
            reorder(client, draft.draft.id, ids)          # 다음 케이스를 위해 되돌린다
        else:
            refused += 1
            assert response.status_code == 422, f"{order}: {response.text}"
            assert items_of(client, draft.draft.id) == original

    assert accepted + refused == 24
    assert accepted and refused, f"accepted={accepted} refused={refused}"


def _fragmenting_board(db, board):
    """Phase 가 셋(`A, B, C, C`)인 DRAFT 를 만든다.

    기본 픽스처(Phase 둘)보다 조각나는 순열이 많고 형태도 다양해서, 거부 경로를
    한 가지 모양에만 기대지 않게 해 준다.
    """
    from app.models import Item, Milestone, Phase
    from app.services import version_service

    p2 = Phase(template_id=board.wp.id, name="세 번째 단계", seq_no=2)
    db.add(p2)
    db.flush()
    m21 = Milestone(template_id=board.wp.id, phase_id=p2.id, name="세-1", seq_no=1)
    m22 = Milestone(template_id=board.wp.id, phase_id=p2.id, name="세-2", seq_no=2)
    db.add_all([m21, m22])
    db.flush()

    layout = [(board.p0, board.m01), (board.p1, board.m11), (p2, m21), (p2, m22)]
    for order, (phase, milestone) in enumerate(layout, start=1):
        db.add(Item(version_id=board.published.id, sort_order=order, phase_id=phase.id,
                    milestone_id=milestone.id, title="t", deliverable="d"))
    db.commit()

    draft = version_service.create_draft(db, board.wp.id)
    db.commit()
    return draft


def test_an_unknown_extra_field_does_not_resurrect_the_old_behaviour(client, draft):
    """`moved_item_id` 는 계약에서 사라졌다. 보내도 아무 일도 일어나지 않는다.

    구버전 클라이언트가 그 필드를 계속 실어 보낼 수 있는데, 그것이 옛 경로를
    되살려서는 안 된다. 조각나는 순서는 필드가 있든 없든 똑같이 422 다.
    """
    rows = items_of(client, draft.draft.id)
    ids = [r["id"] for r in rows]
    before = items_of(client, draft.draft.id)

    crossing = [ids[0], ids[3], ids[1], ids[2]]
    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/reorder",
        json={"item_ids": crossing, "moved_item_id": ids[3]},
    )

    assert response.status_code == 422, response.text
    assert items_of(client, draft.draft.id) == before


def test_a_fragmenting_permutation_is_refused_and_nothing_is_saved(db, client, board):
    """조각나는 순열을 직접 찾아서, 거부와 **무저장**을 함께 확인한다."""
    from itertools import permutations

    from app.services import item_service
    from app.services.renumber_service import find_contiguity_breaks, reposition

    draft = _fragmenting_board(db, board)
    refs = item_service.to_row_refs(item_service.load_ordered_items(db, version_service.board_of(db, draft)))
    ids = [r.item_id for r in refs]

    victim = next(
        (list(o) for o in permutations(ids)
         if find_contiguity_breaks(reposition(refs, list(o)))),
        None,
    )
    assert victim is not None, "이 보드 형태에 조각나는 순열이 없다"

    before = items_of(client, draft.id)
    response = reorder(client, draft.id, victim)

    assert response.status_code == 422, response.text
    body = response.json()["detail"]
    assert body["code"] in {"PHASE_NOT_CONTIGUOUS", "MILESTONE_NOT_CONTIGUOUS"}
    assert body["breaks"], "어느 행에서 갈라졌는지 알려주어야 한다"
    assert items_of(client, draft.id) == before


def test_reorder_rejects_an_incomplete_list(client, draft):
    rows = items_of(client, draft.draft.id)
    assert reorder(client, draft.draft.id, [rows[0]["id"], rows[1]["id"]]).status_code == 400


def test_reorder_keeps_the_only_rows_membership(db, client, draft):
    """행이 하나뿐인 보드에서도 소속이 그대로여야 한다 (감사 F7)."""
    rows = items_of(client, draft.draft.id)
    for row in rows[1:]:
        client.delete(f"{API}/versions/{draft.draft.id}/items/{row['id']}")

    only = items_of(client, draft.draft.id)
    assert len(only) == 1
    before = (only[0]["phase_id"], only[0]["milestone_id"])

    after = reorder(client, draft.draft.id, [only[0]["id"]]).json()["items"][0]
    assert (after["phase_id"], after["milestone_id"]) == before


# =============================================================================
# 셀 편집 — 소속만 (§2.3)
# =============================================================================
def test_membership_change_relocates_a_middle_row_to_the_target_block_end(client, draft):
    """§2.3: 중간 행이 다른 Phase 를 고르면 **대상 블록 끝으로 이동**한다.

    422 가 아니다 — 목적지 계산이야말로 §2.3 이 서버에 두려는 판단이다.
    """
    rows = items_of(client, draft.draft.id)
    middle = rows[1]
    assert middle["can_create_phase"] is False        # 블록 중간이 맞다

    response = membership(client, draft.draft.id, middle["id"], draft.p1.id, draft.m11.id)
    assert response.status_code == 200, response.text

    new_rows = response.json()["items"]
    assert new_rows[-1]["id"] == middle["id"]          # P1 블록 끝으로 갔다
    assert new_rows[-1]["phase_id"] == draft.p1.id
    assert [r["phase_no"] for r in new_rows] == [0, 0, 1, 1]


def test_membership_change_on_a_boundary_row_merges_into_the_adjacent_block(client, draft):
    rows = items_of(client, draft.draft.id)
    boundary = rows[2]                                 # P0 블록의 마지막 행

    new_rows = membership(
        client, draft.draft.id, boundary["id"], draft.p1.id, draft.m11.id
    ).json()["items"]
    assert new_rows[-1]["id"] == boundary["id"]
    assert new_rows[-1]["phase_id"] == draft.p1.id


def test_membership_change_keeps_the_board_contiguous(client, draft):
    rows = items_of(client, draft.draft.id)
    membership(client, draft.draft.id, rows[0]["id"], draft.p1.id, draft.m11.id)

    blocks = [r["phase_id"] for r in items_of(client, draft.draft.id)]
    runs = [k for i, k in enumerate(blocks) if i == 0 or blocks[i - 1] != k]
    assert len(runs) == len(set(runs))


def test_membership_change_rejects_master_data_from_another_template(db, client, draft):
    from app.models import Phase, Template

    other = Template(code="OTHER-R", name="다른 템플릿")
    db.add(other)
    db.flush()
    foreign = Phase(template_id=other.id, name="남의 Phase", seq_no=0)
    db.add(foreign)
    db.commit()

    rows = items_of(client, draft.draft.id)
    assert membership(client, draft.draft.id, rows[0]["id"], foreign.id).status_code == 400


def test_membership_change_can_clear_the_assignment(client, draft):
    """임시저장과 마찬가지로 미지정 상태는 정상이다."""
    rows = items_of(client, draft.draft.id)
    result = membership(client, draft.draft.id, rows[0]["id"], None, None)
    assert result.status_code == 200
    cleared = next(r for r in result.json()["items"] if r["id"] == rows[0]["id"])
    assert cleared["phase_id"] is None and cleared["phase_no"] is None


# =============================================================================
# §0.3 — 재배치는 **마일스톤 블록** 끝 단위다
# =============================================================================
def titles(rows) -> list[str]:
    return [r["title"] for r in rows]


def test_assigning_a_milestone_lands_at_that_milestone_block_end_not_the_phase_end(
    client, three_block_draft
):
    """**§0.3 의 핵심 규칙.** 1.2 를 고르면 1.2 블록 끝이지, Phase 블록 끝이 아니다.

    `a1 a2 | b1(1.1) c1(1.2) c2(1.2) d1(1.3) d2(1.3)` 에서 회색 행에 `{P1, 1.2}` 를
    지정하면 **c2 뒤·d1 앞**에 놓여야 한다. Phase 단위로만 재배치하는 구현은 d2 뒤에
    놓으므로 여기서 갈라진다.
    """
    b = three_block_draft
    rows = items_of(client, b.draft.id)

    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[1]['id']}/insert-below"
    ).json()["items"][2]
    assert gray["phase_id"] is None

    response = membership(client, b.draft.id, gray["id"], b.p1.id, b.m12.id)
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert titles(new_rows) == ["a1", "a2", "b1", "c1", "c2", None, "d1", "d2"], (
        "회색 행이 1.2 블록 끝이 아니라 다른 자리에 놓였다"
    )
    landed = new_rows[5]
    assert landed["id"] == gray["id"]
    assert (landed["phase_id"], landed["milestone_id"]) == (b.p1.id, b.m12.id)
    # 번호가 뒤섞이지 않는다 — 사용자에게 보고된 증상이 그것이었다.
    assert [r["milestone_no_display"] for r in new_rows] == [
        "0.1", "0.1", "1.1", "1.2", "1.2", "1.2", "1.3", "1.3"
    ]


def test_the_two_step_phase_then_milestone_flow_lands_in_the_same_place(
    client, three_block_draft
):
    """§0.3 의 2단계 흐름 — phase 먼저, 그 다음 milestone.

    1단계 뒤에는 행이 **Phase 블록 끝**(d2 뒤)에 있고, 2단계에서 **1.2 블록 끝**으로
    당겨져야 한다. 한 번에 지정한 경우와 최종 위치가 같아야 한다.
    """
    b = three_block_draft
    rows = items_of(client, b.draft.id)

    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[1]['id']}/insert-below"
    ).json()["items"][2]

    step1 = membership(client, b.draft.id, gray["id"], b.p1.id, None)
    assert step1.status_code == 200, step1.text
    # milestone 미지정이면 Phase 블록 끝 — 여기서는 d2 뒤가 맞다.
    assert titles(step1.json()["items"]) == ["a1", "a2", "b1", "c1", "c2", "d1", "d2", None]

    step2 = membership(client, b.draft.id, gray["id"], b.p1.id, b.m12.id)
    assert step2.status_code == 200, step2.text
    assert titles(step2.json()["items"]) == ["a1", "a2", "b1", "c1", "c2", None, "d1", "d2"]


def test_assigning_the_first_milestone_block_lands_before_the_later_blocks(
    client, three_block_draft
):
    """1.1 을 고르면 b1 바로 뒤다 — 뒤 블록(1.2/1.3)을 건너뛰지 않는다."""
    b = three_block_draft
    rows = items_of(client, b.draft.id)

    gray = client.post(
        f"{API}/versions/{b.draft.id}/items/{rows[1]['id']}/insert-below"
    ).json()["items"][2]

    new_rows = membership(client, b.draft.id, gray["id"], b.p1.id, b.m11.id).json()["items"]
    assert titles(new_rows) == ["a1", "a2", "b1", None, "c1", "c2", "d1", "d2"]


# =============================================================================
# §0.3 — `{null, null}` 은 **제자리에서** 미배정으로 전환한다
# =============================================================================
def test_clearing_an_assigned_mid_block_row_keeps_it_in_place(client, three_block_draft):
    """§0.3 의 유일한 재분류 경로. 행이 움직이면 안 된다.

    `c1` 은 1.2 블록의 **한가운데**(앞에 b1, 뒤에 c2)다. null 은 연속성에 투명하므로
    제자리에 두어도 보드가 조각나지 않는다 — 그래서 옮길 이유가 없다. 옮기는 구현은
    사용자가 "행이 멋대로 움직인다" 고 느끼는 바로 그 동작이고, §0.3 이 막으려는 것이다.
    """
    b = three_block_draft
    rows = items_of(client, b.draft.id)
    target = rows[3]                                   # c1 — 1.2 블록의 첫 행
    assert target["title"] == "c1"

    response = membership(client, b.draft.id, target["id"], None, None)
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    # 위치가 그대로다 (index 3).
    assert titles(new_rows) == ["a1", "a2", "b1", "c1", "c2", "d1", "d2"]
    assert new_rows[3]["id"] == target["id"]

    cleared = new_rows[3]
    assert cleared["phase_id"] is None and cleared["milestone_id"] is None
    assert cleared["phase_no"] is None and cleared["milestone_no_display"] is None

    # 나머지 행의 번호는 흔들리지 않는다 — 회색 행이 투명하기 때문이다.
    assert [r["milestone_no_display"] for r in new_rows] == [
        "0.1", "0.1", "1.1", None, "1.2", "1.3", "1.3"
    ]


def test_clearing_a_row_strictly_inside_a_milestone_block_does_not_split_it(
    client, three_block_draft
):
    """블록을 둘로 가르는 자리에서 비워도 422 가 아니다 — null 은 투명하다.

    `c1`, `c2` 사이에 회색 행이 생기는 형태가 되지만, 1.2 블록은 여전히 한 덩어리로
    취급된다. 이것이 §0.3 이 "제자리 전환은 안전하다" 고 말하는 근거다.
    """
    b = three_block_draft
    rows = items_of(client, b.draft.id)

    # 1.2 블록을 3행으로 늘린다. **c2 바로 뒤**에 넣어야 한다 — 목록 끝에 붙이면
    # 그 저장 자체로 1.2 가 두 조각이 되고(임시저장은 무검증), 이어지는 비우기가
    # 정당하게 422 로 거부된다. 그러면 검사하려던 것과 다른 것을 보게 된다.
    payload = [
        {"id": r["id"], "phase_id": r["phase_id"], "milestone_id": r["milestone_id"],
         "title": r["title"]}
        for r in rows
    ]
    payload.insert(5, {"phase_id": b.p1.id, "milestone_id": b.m12.id, "title": "c3"})
    saved = client.put(f"{API}/versions/{b.draft.id}/items", json={"items": payload})
    assert saved.status_code == 200, saved.text
    assert titles(saved.json()["items"]) == ["a1", "a2", "b1", "c1", "c2", "c3", "d1", "d2"]

    middle = next(r for r in items_of(client, b.draft.id) if r["title"] == "c2")

    response = membership(client, b.draft.id, middle["id"], None, None)
    assert response.status_code == 200, response.text

    after = response.json()["items"]
    # 제자리에 남고, 회색이 되고, 1.2 블록은 조각나지 않은 것으로 취급된다.
    assert titles(after) == ["a1", "a2", "b1", "c1", "c2", "c3", "d1", "d2"]
    cleared = after[4]
    assert cleared["id"] == middle["id"]
    assert cleared["phase_id"] is None and cleared["milestone_id"] is None
    assert [r["milestone_no_display"] for r in after] == [
        "0.1", "0.1", "1.1", "1.2", None, "1.2", "1.3", "1.3"
    ]


# =============================================================================
# 빈 버전에 첫 행 만들기
# =============================================================================
def test_append_creates_the_first_row_of_an_empty_version(client, draft):
    client.put(f"{API}/versions/{draft.draft.id}/items", json={"items": []})
    assert items_of(client, draft.draft.id) == []

    response = client.post(f"{API}/versions/{draft.draft.id}/items")
    assert response.status_code == 201, response.text

    created = response.json()["items"]
    assert len(created) == 1
    assert created[0]["phase_id"] is None          # 상속할 앞행이 없다
    assert created[0]["milestone_id"] is None
    assert created[0]["origin"] == "ADDED"
    assert created[0]["row_no"] == 1


def test_append_puts_the_row_at_the_end(client, draft):
    before = items_of(client, draft.draft.id)
    created = client.post(f"{API}/versions/{draft.draft.id}/items").json()["items"]

    assert len(created) == len(before) + 1
    assert created[-1]["origin"] == "ADDED"
    assert [r["id"] for r in created[:-1]] == [r["id"] for r in before]
    # 앞 행들의 번호는 그대로여야 한다
    assert [r["phase_no"] for r in created[:-1]] == [r["phase_no"] for r in before]


def test_append_is_blocked_on_a_published_version(client, draft):
    assert client.post(f"{API}/versions/{draft.published.id}/items").status_code == 409


# =============================================================================
# 기준 행에서 Phase / Milestone 생성 (§2.3)
# =============================================================================
def test_create_phase_from_the_bottom_edge_lands_after_the_block(client, draft):
    rows = items_of(client, draft.draft.id)
    anchor = rows[2]                                   # P0 블록의 마지막 행
    assert anchor["can_create_phase"] is True

    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/{anchor['id']}/create-phase",
        json={"name": "신규 단계"},
    )
    assert response.status_code == 200, response.text
    new_rows = response.json()["items"]

    assert [r["phase_no"] for r in new_rows] == [0, 0, 1, 2]
    assert new_rows[2]["phase_name"] == "신규 단계"
    assert new_rows[2]["milestone_id"] is None         # 새 Phase 에는 Milestone 이 없다
    assert new_rows[3]["phase_no"] == 2                # 기존 P1 이 뒤로 밀렸다


def test_create_phase_from_the_top_edge_lands_before_the_block(client, draft):
    rows = items_of(client, draft.draft.id)
    anchor = rows[0]                                   # P0 블록의 첫 행

    new_rows = client.post(
        f"{API}/versions/{draft.draft.id}/items/{anchor['id']}/create-phase",
        json={"name": "선행 단계"},
    ).json()["items"]

    assert new_rows[0]["phase_name"] == "선행 단계"
    assert new_rows[0]["phase_no"] == 0
    assert new_rows[1]["phase_no"] == 1                # 기존 P0 이 뒤로 밀렸다


def test_create_phase_is_rejected_from_a_middle_row(client, draft):
    rows = items_of(client, draft.draft.id)
    middle = rows[1]
    assert middle["can_create_phase"] is False

    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/{middle['id']}/create-phase",
        json={"name": "쪼개는 단계"},
    )
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["code"] == "PHASE_BOUNDARY_VIOLATION"
    assert body["item_id"] == middle["id"]
    assert body["field"] == "phase_id"

    assert items_of(client, draft.draft.id) == rows     # 아무것도 바뀌지 않았다


def test_create_phase_rejects_a_duplicate_name(client, draft):
    rows = items_of(client, draft.draft.id)
    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/{rows[0]['id']}/create-phase",
        json={"name": "Initiation & Readiness"},
    )
    assert response.status_code == 400


def test_create_milestone_from_a_boundary_row(client, draft):
    rows = items_of(client, draft.draft.id)
    anchor = rows[2]                                   # P0/M02, 블록 크기 1

    new_rows = client.post(
        f"{API}/versions/{draft.draft.id}/items/{anchor['id']}/create-milestone",
        json={"name": "신규 마일스톤"},
    ).json()["items"]

    assert new_rows[2]["milestone_name"] == "신규 마일스톤"
    assert new_rows[2]["phase_id"] == draft.p0.id      # Phase 는 그대로
    assert new_rows[2]["milestone_no_display"] == "0.2"


def test_create_milestone_is_rejected_from_a_middle_row(client, draft):
    """Milestone 블록의 **한가운데 배정된 행**에서는 새 Milestone 을 만들 수 없다.

    행 추가로는 이 배치를 만들 수 없다 — 신규 행은 회색이라 블록을 늘리지 않기
    때문이다 (§0.2). 그래서 임시저장으로 3행짜리 M01 블록을 직접 깐다.
    """
    rows = items_of(client, draft.draft.id)
    saved = client.put(
        f"{API}/versions/{draft.draft.id}/items",
        json={"items": [
            {"id": rows[0]["id"], "phase_id": draft.p0.id, "milestone_id": draft.m01.id},
            {"id": rows[1]["id"], "phase_id": draft.p0.id, "milestone_id": draft.m01.id},
            {"id": rows[2]["id"], "phase_id": draft.p0.id, "milestone_id": draft.m01.id},
            {"id": rows[3]["id"], "phase_id": draft.p1.id, "milestone_id": draft.m11.id},
        ]},
    )
    assert saved.status_code == 200, saved.text

    board = items_of(client, draft.draft.id)
    assert board[1]["can_create_milestone"] is False    # M01 블록의 한가운데

    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/{board[1]['id']}/create-milestone",
        json={"name": "쪼개는 마일스톤"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MILESTONE_BOUNDARY_VIOLATION"


def test_create_milestone_requires_the_anchor_to_have_a_phase(client, draft):
    client.put(f"{API}/versions/{draft.draft.id}/items", json={"items": []})
    created = client.post(f"{API}/versions/{draft.draft.id}/items").json()["items"]

    response = client.post(
        f"{API}/versions/{draft.draft.id}/items/{created[0]['id']}/create-milestone",
        json={"name": "Phase 없는 마일스톤"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PHASE_REQUIRED"


def test_creating_a_phase_is_blocked_on_a_published_version(client, draft):
    rows = items_of(client, draft.published.id)
    response = client.post(
        f"{API}/versions/{draft.published.id}/items/{rows[0]['id']}/create-phase",
        json={"name": "x"},
    )
    assert response.status_code == 409


# =============================================================================
# 삭제
# =============================================================================
def test_delete_renumbers_the_rest(client, draft):
    rows = items_of(client, draft.draft.id)
    response = client.delete(f"{API}/versions/{draft.draft.id}/items/{rows[1]['id']}")
    assert response.status_code == 200

    remaining = response.json()["items"]
    assert [r["row_no"] for r in remaining] == [1, 2, 3]
    assert [r["phase_no"] for r in remaining] == [0, 0, 1]


def test_deleting_the_last_row_of_a_phase_removes_its_number(client, draft):
    rows = items_of(client, draft.draft.id)
    response = client.delete(f"{API}/versions/{draft.draft.id}/items/{rows[3]['id']}")
    remaining = response.json()["items"]
    assert {r["phase_no"] for r in remaining} == {0}


# =============================================================================
# 임시저장 — 검증 없음, 참조 무결성만
# =============================================================================
def test_temp_save_rejects_sort_order_that_disagrees_with_array_position(client, draft):
    """순서의 정본은 배열 위치다. `sort_order` 는 주장일 뿐이고 불일치는 400."""
    rows = items_of(client, draft.draft.id)
    payload = {"items": [
        {"id": rows[0]["id"], "sort_order": 5},
        {"id": rows[1]["id"], "sort_order": 2},
    ]}
    assert client.put(f"{API}/versions/{draft.draft.id}/items", json=payload).status_code == 400


def test_temp_save_accepts_sort_order_that_agrees(client, draft):
    rows = items_of(client, draft.draft.id)
    payload = {"items": [
        {"id": rows[0]["id"], "sort_order": 1},
        {"id": rows[1]["id"], "sort_order": 2},
    ]}
    assert client.put(f"{API}/versions/{draft.draft.id}/items", json=payload).status_code == 200


def test_temp_save_accepts_rows_with_nothing_filled_in(client, draft):
    rows = items_of(client, draft.draft.id)
    payload = {"items": [{"id": rows[0]["id"]}, {"id": rows[1]["id"], "title": "  "}]}

    response = client.put(f"{API}/versions/{draft.draft.id}/items", json=payload)
    assert response.status_code == 200, response.text

    saved = response.json()["items"]
    assert len(saved) == 2                       # 목록에 없는 행은 삭제된다
    assert saved[0]["phase_id"] is None          # Phase 미지정도 그대로 저장
    assert saved[0]["phase_no"] is None
    assert saved[0]["documents"] == []


def test_temp_save_can_create_rows_on_an_empty_draft(client, draft):
    client.put(f"{API}/versions/{draft.draft.id}/items", json={"items": []})
    assert items_of(client, draft.draft.id) == []

    response = client.put(
        f"{API}/versions/{draft.draft.id}/items",
        json={"items": [{"phase_id": draft.p0.id, "milestone_id": draft.m01.id, "title": "첫 행"}]},
    )
    assert response.status_code == 200
    created = response.json()["items"]
    assert len(created) == 1 and created[0]["title"] == "첫 행"
    assert created[0]["origin"] == "ADDED"


def test_temp_save_still_rejects_a_dangling_reference(client, draft):
    response = client.put(
        f"{API}/versions/{draft.draft.id}/items", json={"items": [{"phase_id": 999999}]}
    )
    assert response.status_code == 400


def test_temp_save_rejects_master_data_from_another_template(db, client, draft, board):
    """기준정보는 WP 스코프다. 다른 WP 의 Phase 를 끌어다 쓸 수 없다."""
    from app.models import Phase, Template

    other = Template(code="OTHER", name="다른 템플릿")
    db.add(other)
    db.flush()
    foreign = Phase(template_id=other.id, name="남의 Phase", seq_no=0)
    db.add(foreign)
    db.commit()

    response = client.put(
        f"{API}/versions/{draft.draft.id}/items", json={"items": [{"phase_id": foreign.id}]}
    )
    assert response.status_code == 400


# =============================================================================
# 불변성 — PUBLISHED / ARCHIVED 는 쓰기 금지
# =============================================================================
def mutating_item_routes(client) -> set[tuple[str, str]]:
    """행을 바꾸는 엔드포인트를 **라우트 표에서 직접 뽑는다.**

    목록을 손으로 적으면 새 엔드포인트가 추가돼도 테스트는 조용히 통과한다.
    OpenAPI 에서 뽑으면 새로 생긴 쓰기 경로가 아래 시나리오에 등록되지 않는 한
    테스트가 **실패한다** — 닫히는 쪽으로 실패한다.

    `/items` 아래만 보면 안 된다. §0.4 의 `phases/apply` 는 URL 이 `/phases` 로
    시작하지만 **행을 만들고 지우는** 연산이라, 빠뜨리면 PUBLISHED 버전을
    고칠 수 있는 경로가 생긴다. §0.5.10 의 `documents/apply` 도 같다 — 문서를
    지우면 항목 링크가 캐스케이드로 사라지므로 그 역시 행을 바꾸는 연산이다.
    `/validate` · `/publish` 는 `/versions/{id}` 바로 아래에 있어 접두만으로는
    걸러지지 않으므로 세 묶음을 명시적으로 고른다.
    """
    schema = client.app.openapi()
    base = "/api/v1/versions/{version_id}"
    groups = (f"{base}/items", f"{base}/phases", f"{base}/documents")
    return {
        (method.upper(), path)
        for path, ops in schema["paths"].items()
        if path.startswith(groups)
        for method in ops
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    }


def build_write_request(client, call, version_id, rows, draft):
    """(METHOD, path) → 그 엔드포인트를 실제로 호출한다."""
    method, path = call
    first = rows[0]["id"]
    if path.endswith("/phases/apply"):
        return client.post(
            f"{API}/versions/{version_id}/phases/apply",
            json={"phases": [{"id": draft.p0.id, "name": "그대로"}], "deleted_ids": []},
        )
    if path.endswith("/documents/apply"):
        return client.post(
            f"{API}/versions/{version_id}/documents/apply",
            json={"documents": [{"id": draft.d1.id, "name": "그대로"},
                                {"id": draft.d2.id, "name": "그대로2"}],
                  "deleted_ids": []},
        )
    if path.endswith("/milestones/apply"):
        return client.post(
            f"{API}/versions/{version_id}/phases/{draft.p0.id}/milestones/apply",
            json={"milestones": [{"id": draft.m01.id, "name": "그대로"}], "deleted_ids": []},
        )
    if path.endswith("/items") and method == "POST":
        return client.post(f"{API}/versions/{version_id}/items")
    if path.endswith("/items") and method == "PUT":
        return client.put(f"{API}/versions/{version_id}/items", json={"items": []})
    if path.endswith("/reorder"):
        return reorder(client, version_id, [r["id"] for r in reversed(rows)])
    if path.endswith("/insert-below"):
        return client.post(f"{API}/versions/{version_id}/items/{first}/insert-below")
    if path.endswith("/create-phase"):
        return client.post(
            f"{API}/versions/{version_id}/items/{first}/create-phase", json={"name": "새 단계"}
        )
    if path.endswith("/create-milestone"):
        return client.post(
            f"{API}/versions/{version_id}/items/{first}/create-milestone", json={"name": "새 마일스톤"}
        )
    if path.endswith("/membership"):
        return membership(client, version_id, first, draft.p1.id, draft.m11.id)
    if method == "DELETE":
        return client.delete(f"{API}/versions/{version_id}/items/{first}")
    raise AssertionError(f"등록되지 않은 쓰기 경로: {method} {path}")


def test_the_write_path_list_covers_every_mutating_endpoint(client, draft):
    """시나리오가 실제 라우트를 전부 덮는지 먼저 확인한다.

    함정 하나: 임시저장은 `PUT .../items`, 빈 행 추가는 `POST .../items` 로
    **경로가 같고 메서드만 다르다.** 경로만 세면 덮인 것처럼 읽힌다.
    """
    discovered = mutating_item_routes(client)
    assert len(discovered) == 11, sorted(discovered)

    rows = items_of(client, draft.draft.id)
    for call in discovered:
        # 등록되지 않은 경로면 build_write_request 가 AssertionError 를 던진다
        build_write_request(client, call, draft.draft.id, rows, draft)


def test_published_versions_reject_every_write_path(client, draft):
    """**열 개 전부** 409. 하나라도 빠지면 불변성에 구멍이 난다."""
    published_id = draft.published.id
    rows = items_of(client, published_id)
    before = items_of(client, published_id)

    for call in sorted(mutating_item_routes(client)):
        response = build_write_request(client, call, published_id, rows, draft)
        assert response.status_code == 409, f"{call} -> {response.status_code} {response.text}"
        assert response.json()["detail"]["code"] == "CONFLICT", call

    assert items_of(client, published_id) == before


def test_archived_versions_reject_every_write_path(db, client, draft):
    """ARCHIVED 도 마찬가지다 — PUBLISHED 만 막고 끝나면 안 된다."""
    from app.models import VersionStatus

    published = db.get(type(draft.published), draft.published.id)
    published.status = VersionStatus.ARCHIVED
    db.commit()

    rows = items_of(client, published.id)
    for call in sorted(mutating_item_routes(client)):
        response = build_write_request(client, call, published.id, rows, draft)
        assert response.status_code == 409, f"{call} -> {response.status_code}"


def test_a_published_version_is_marked_read_only(client, draft):
    response = client.get(f"{API}/versions/{draft.published.id}")
    assert response.json()["version"]["is_editable"] is False
    assert response.json()["version"]["status"] == "PUBLISHED"


# =============================================================================
# 검증 / 발행 엔드포인트
# =============================================================================
def test_validate_endpoint_reports_cell_locations(client, draft):
    rows = items_of(client, draft.draft.id)
    client.put(
        f"{API}/versions/{draft.draft.id}/items",
        json={"items": [{"id": rows[0]["id"], "phase_id": draft.p0.id,
                         "milestone_id": draft.m01.id, "title": "제목", "deliverable": "산출물"}]},
    )

    result = client.post(f"{API}/versions/{draft.draft.id}/validate").json()
    assert result["valid"] is False
    by_code = {e["code"]: e for e in result["errors"]}
    assert "DOCUMENT_REQUIRED" in by_code and "OWNER_REQUIRED" in by_code
    assert by_code["OWNER_REQUIRED"]["row_no"] == 1
    # 값이 없는 위치 필드는 응답에서 빠진다
    assert "milestone_id" not in by_code["OWNER_REQUIRED"]


def test_validate_does_not_change_the_version(client, draft):
    client.post(f"{API}/versions/{draft.draft.id}/validate")
    assert client.get(f"{API}/versions/{draft.draft.id}").json()["version"]["status"] == "DRAFT"


def test_publish_returns_422_with_the_full_error_payload(client, draft):
    rows = items_of(client, draft.draft.id)
    client.put(
        f"{API}/versions/{draft.draft.id}/items",
        json={"items": [{"id": rows[0]["id"], "title": "제목"}]},
    )

    response = client.post(f"{API}/versions/{draft.draft.id}/publish")
    assert response.status_code == 422
    # §2.5 형식이 `detail` 바로 아래에 평평하게 담긴다 (`detail.detail` 아님).
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_FAILED"
    assert detail["valid"] is False
    assert {"PHASE_REQUIRED", "MILESTONE_REQUIRED"} <= {e["code"] for e in detail["errors"]}
    assert "warnings" in detail

    assert client.get(f"{API}/versions/{draft.draft.id}").json()["version"]["status"] == "DRAFT"


def test_publish_succeeds_and_archives_the_previous_version(db, client, draft):
    response = client.post(
        f"{API}/versions/{draft.draft.id}/publish", json={"published_by": "tester"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"]["status"] == "PUBLISHED"

    db.expire_all()
    assert db.get(type(draft.published), draft.published.id).status == VersionStatus.ARCHIVED


def test_discarding_a_draft_leaves_the_published_version_alone(client, draft):
    assert client.delete(f"{API}/versions/{draft.draft.id}").status_code == 204
    assert client.get(f"{API}/versions/{draft.draft.id}").status_code == 404
    assert len(items_of(client, draft.published.id)) == 4


def test_a_published_version_cannot_be_discarded(client, draft):
    assert client.delete(f"{API}/versions/{draft.published.id}").status_code == 409
