"""대시보드 — `dash_label` 컬럼과 전체 현황 API (plan.md §0.5).

두 가지를 검사한다.

1. **`dash_label` 이 모든 경로를 통과하는가.** 저장·조회는 물론이고 **deep copy
   두 경로**(템플릿 draft 생성 / 프로젝트 생성)에서 값이 살아남아야 한다. 복제
   함수는 필드를 하나씩 손으로 옮겨 적는 코드라, 컬럼을 늘릴 때 빠뜨리기 가장
   쉬운 자리다. 빠뜨리면 오류 없이 **조용히 NULL** 이 된다.
2. **`GET /projects/overview` 의 형태와 파생값.** 특히 `phase_seq` 가 저장값이
   아니라 그리드와 같은 재계산기에서 나온 표시 번호라는 것, 그리고 이 조회가
   아무것도 쓰지 않는다는 것.
"""

from __future__ import annotations

import pytest

from app.models import Item, ItemStatus, Project, ProjectDocument, ProjectItem, ProjectPhase
from app.services import version_service

pytestmark = pytest.mark.db

API = "/api/v1"


# =============================================================================
# 픽스처
# =============================================================================
@pytest.fixture
def published(db, board):
    """발행본 v1 — `[P0/M01, P0/M01, P0/M02, P1/M11]`, 각 행에 dash_label."""
    layout = [(board.p0, board.m01), (board.p0, board.m01), (board.p0, board.m02), (board.p1, board.m11)]
    for order, (phase, milestone) in enumerate(layout, start=1):
        db.add(
            Item(
                version_id=board.published.id,
                sort_order=order,
                phase_id=phase.id,
                milestone_id=milestone.id,
                title=f"행 {order}",
                deliverable=f"산출물 {order}",
                dash_label=f"라벨{order}",
            )
        )
    db.commit()
    return board


def make_project(client, board, *, name="테스트 프로젝트", maker_id=7):
    response = client.post(
        f"{API}/projects", json={"maker_id": maker_id, "name": name, "template_id": board.wp.id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def project_items(client, project_id):
    response = client.get(f"{API}/projects/{project_id}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def version_items(client, version_id):
    response = client.get(f"{API}/versions/{version_id}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def overview(client):
    """설비사 섹션을 가로질러 **프로젝트만** 평평하게 돌려준다.

    이 파일의 관심사는 프로젝트 단위의 파생값(집계·`phase_seq`·문서)이라,
    §0.6-3 이 들여온 설비사 그룹핑은 여기서 벗겨 낸다. 그룹핑 자체와 표시
    규칙은 `test_api_makers.py` 가 본다.
    """
    response = client.get(f"{API}/projects/overview")
    assert response.status_code == 200, response.text
    return [p for maker in response.json()["makers"] for p in maker["projects"]]


class FakeResolver:
    """호스트 설비사 조회 대역."""

    def __init__(self, names: dict[int, str]):
        self.names = names
        self.calls: list[list[int]] = []

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        self.calls.append(list(maker_ids))
        return {i: self.names[i] for i in maker_ids if i in self.names}

    def exists(self, maker_id: int) -> bool:
        return True


# =============================================================================
# deep copy — 두 경로 모두 복사한다
# =============================================================================
def test_draft_creation_copies_the_dash_label(db, client, published):
    """경로 1: 템플릿 PUBLISHED → 새 DRAFT."""
    draft = version_service.create_draft(db, published.wp.id)
    db.commit()

    labels = [r["dash_label"] for r in version_items(client, draft.id)]
    assert labels == ["라벨1", "라벨2", "라벨3", "라벨4"]


def test_project_creation_copies_the_dash_label(client, published):
    """경로 2: 템플릿 발행본 → 프로젝트 스냅샷."""
    created = make_project(client, published)
    assert [r["dash_label"] for r in created["items"]] == ["라벨1", "라벨2", "라벨3", "라벨4"]


def test_a_copied_dash_label_is_a_snapshot_not_a_link(db, client, published):
    """프로젝트의 라벨을 고쳐도 템플릿은 그대로다 (§0.1 — 전파 없음)."""
    created = make_project(client, published)
    project_id = created["project"]["id"]

    rows = created["items"]
    response = client.put(
        f"{API}/projects/{project_id}/items",
        json={
            "items": [
                {
                    "id": r["id"],
                    "phase_id": r["phase_id"],
                    "milestone_id": r["milestone_id"],
                    "title": r["title"],
                    "dash_label": "프로젝트에서 고침" if i == 0 else r["dash_label"],
                }
                for i, r in enumerate(rows)
            ]
        },
    )
    assert response.status_code == 200, response.text

    assert project_items(client, project_id)[0]["dash_label"] == "프로젝트에서 고침"
    db.expire_all()
    origin = db.query(Item).filter_by(sort_order=1, version_id=published.published.id).one()
    assert origin.dash_label == "라벨1"


# =============================================================================
# 저장 왕복
# =============================================================================
def test_a_project_save_round_trips_the_dash_label(client, published):
    created = make_project(client, published)
    project_id = created["project"]["id"]

    response = client.put(
        f"{API}/projects/{project_id}/items",
        json={"items": [{"id": r["id"], "dash_label": f"새 라벨{i}"} for i, r in enumerate(created["items"])]},
    )
    assert response.status_code == 200, response.text
    assert [r["dash_label"] for r in response.json()["items"]] == ["새 라벨0", "새 라벨1", "새 라벨2", "새 라벨3"]
    assert [r["dash_label"] for r in project_items(client, project_id)] == [
        "새 라벨0", "새 라벨1", "새 라벨2", "새 라벨3",
    ]


def test_a_template_temp_save_round_trips_the_dash_label(db, client, published):
    draft = version_service.create_draft(db, published.wp.id)
    db.commit()
    rows = version_items(client, draft.id)

    response = client.put(
        f"{API}/versions/{draft.id}/items",
        json={"items": [{"id": r["id"], "dash_label": "임시저장 라벨"} for r in rows]},
    )
    assert response.status_code == 200, response.text
    assert all(r["dash_label"] == "임시저장 라벨" for r in version_items(client, draft.id))


def test_a_save_can_clear_the_dash_label(client, published):
    """`null` 을 보내면 지워진다. 라벨 없음이 정상 상태이므로 되돌릴 길이 있어야 한다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]

    response = client.put(
        f"{API}/projects/{project_id}/items",
        json={"items": [{"id": r["id"], "dash_label": None} for r in created["items"]]},
    )
    assert response.status_code == 200, response.text
    assert all(r["dash_label"] is None for r in response.json()["items"])


def test_a_dash_label_longer_than_the_column_is_rejected(client, published):
    """컬럼이 VARCHAR(60) 이다. 넘치면 DB 가 자르기 전에 422 로 막는다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]

    response = client.put(
        f"{API}/projects/{project_id}/items",
        json={"items": [{"id": created["items"][0]["id"], "dash_label": "가" * 61}]},
    )
    assert response.status_code == 422, response.text


# =============================================================================
# 행 추가 경로
# =============================================================================
def test_append_and_insert_carry_the_dash_label(client, published):
    created = make_project(client, published)
    project_id = created["project"]["id"]
    anchor = created["items"][0]["id"]

    appended = client.post(
        f"{API}/projects/{project_id}/items", json={"dash_label": "끝에 붙인 행"}
    )
    assert appended.status_code == 201, appended.text
    assert appended.json()["items"][-1]["dash_label"] == "끝에 붙인 행"

    inserted = client.post(
        f"{API}/projects/{project_id}/items/{anchor}/insert-below",
        json={"dash_label": "사이에 넣은 행"},
    )
    assert inserted.status_code == 200, inserted.text
    assert inserted.json()["items"][1]["dash_label"] == "사이에 넣은 행"


def test_a_plain_gray_row_is_born_without_a_dash_label(client, published):
    """§0.2 의 회색 행. 라벨은 사용자가 나중에 채운다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]

    response = client.post(f"{API}/projects/{project_id}/items")
    assert response.status_code == 201, response.text
    row = response.json()["items"][-1]
    assert row["phase_id"] is None and row["dash_label"] is None


def test_the_structure_popup_blank_row_has_no_dash_label(client, published):
    """§0.4 의 관리 팝업이 새 Phase 를 지탱하려고 만드는 빈 행도 라벨이 없다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]
    phases = client.get(f"{API}/projects/{project_id}/phases").json()

    response = client.post(
        f"{API}/projects/{project_id}/phases/apply",
        json={
            "phases": [{"id": p["id"], "name": p["name"]} for p in phases]
            + [{"id": None, "name": "새 단계"}],
            "deleted_ids": [],
        },
    )
    assert response.status_code == 200, response.text
    blank = response.json()["items"][-1]
    assert blank["dash_label"] is None


# =============================================================================
# GET /projects/overview — 형태
# =============================================================================
def test_overview_is_not_shadowed_by_the_project_id_route(db, client):
    """`/projects/{project_id}` 보다 먼저 등록되어야 한다.

    순서가 뒤집히면 "overview" 가 정수 경로 파라미터로 잡혀 **422** 가 난다.
    라우트 등록 순서에만 의존하는 성질이라 테스트 없이는 조용히 깨진다.
    """
    response = client.get(f"{API}/projects/overview")
    assert response.status_code == 200, response.text
    assert response.json() == {"makers": []}


def test_overview_reports_counts_and_a_minimap_row_per_item(client, published):
    created = make_project(client, published)
    project_id = created["project"]["id"]

    rows = overview(client)
    assert len(rows) == 1
    entry = rows[0]

    assert entry["id"] == project_id
    assert entry["name"] == "테스트 프로젝트"
    assert entry["maker_id"] == 7
    # 다섯 상태 키가 0 이어도 전부 나온다 — 집계 칩이 "완료 0" 을 그려야 한다.
    assert entry["counts"] == {
        "NOT_STARTED": 4, "IN_PROGRESS": 0, "DONE": 0, "HOLD": 0, "NA": 0,
    }
    assert [i["no"] for i in entry["items"]] == [1, 2, 3, 4]
    assert [i["dash_label"] for i in entry["items"]] == ["라벨1", "라벨2", "라벨3", "라벨4"]
    assert set(entry["items"][0]) == {
        "no", "status", "phase_seq", "milestone_seq", "dash_label",
        "title", "deliverable", "owners",
    }


def test_overview_counts_follow_the_item_statuses(db, client, published):
    created = make_project(client, published)
    project_id = created["project"]["id"]

    rows = db.query(ProjectItem).filter_by(project_id=project_id).order_by(ProjectItem.sort_order).all()
    rows[0].status = ItemStatus.DONE
    rows[1].status = ItemStatus.IN_PROGRESS
    rows[2].status = ItemStatus.HOLD
    rows[3].status = ItemStatus.NA
    db.commit()

    entry = overview(client)[0]
    assert entry["counts"] == {
        "NOT_STARTED": 0, "IN_PROGRESS": 1, "DONE": 1, "HOLD": 1, "NA": 1,
    }
    assert [i["status"] for i in entry["items"]] == ["DONE", "IN_PROGRESS", "HOLD", "NA"]


def test_overview_items_follow_sort_order(db, client, published):
    """미니맵은 보드와 같은 순서로 그려져야 한다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]
    ids = [r["id"] for r in created["items"]]

    response = client.post(
        f"{API}/projects/{project_id}/items/reorder",
        json={"item_ids": [ids[1], ids[0], ids[2], ids[3]]},
    )
    assert response.status_code == 200, response.text

    entry = overview(client)[0]
    assert [i["dash_label"] for i in entry["items"]] == ["라벨2", "라벨1", "라벨3", "라벨4"]
    assert [i["no"] for i in entry["items"]] == [1, 2, 3, 4]


# =============================================================================
# phase_seq 는 저장값이 아니라 파생값이다
# =============================================================================
def test_overview_phase_seq_matches_the_grid_numbering(client, published):
    created = make_project(client, published)
    grid = created["items"]
    entry = overview(client)[0]

    assert [i["phase_seq"] for i in entry["items"]] == [r["phase_no"] for r in grid]
    assert [i["milestone_seq"] for i in entry["items"]] == [r["milestone_no"] for r in grid]
    assert [i["phase_seq"] for i in entry["items"]] == [0, 0, 0, 1]
    assert [i["milestone_seq"] for i in entry["items"]] == [1, 1, 2, 1]


def test_overview_phase_seq_ignores_the_stored_master_seq_no(db, client, published):
    """기준정보의 `seq_no` 를 직접 읽으면 안 된다 — 번호는 **행 순서**에서 나온다.

    `wp_project_phases.seq_no` 를 엉뚱한 값으로 흐트러뜨려도 표시 번호는
    첫 등장 순서(0, 1)를 지켜야 한다. seq_no 를 읽어 쓰는 구현이었다면 여기서
    깨진다.
    """
    created = make_project(client, published)
    project_id = created["project"]["id"]

    for phase in db.query(ProjectPhase).filter_by(project_id=project_id).all():
        phase.seq_no = 99
    db.commit()

    entry = overview(client)[0]
    assert [i["phase_seq"] for i in entry["items"]] == [0, 0, 0, 1]


def test_overview_honours_the_projects_phase_start_no(db, client, published):
    """표시 시작 번호는 프로젝트가 생성 시점에 스냅샷한 값이다 (§0.1)."""
    created = make_project(client, published)
    project = db.query(Project).filter_by(id=created["project"]["id"]).one()
    project.phase_start_no = 5
    db.commit()

    assert [i["phase_seq"] for i in overview(client)[0]["items"]] == [5, 5, 5, 6]


def test_overview_leaves_gray_rows_unnumbered(client, published):
    """미배정 행은 `phase_seq` / `milestone_seq` 가 둘 다 null 이고, 뒤 번호를 밀지 않는다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]

    appended = client.post(f"{API}/projects/{project_id}/items")
    assert appended.status_code == 201, appended.text

    cells = overview(client)[0]["items"]
    assert len(cells) == 5
    assert cells[-1]["phase_seq"] is None
    assert cells[-1]["milestone_seq"] is None
    assert cells[-1]["dash_label"] is None
    # 회색 행이 끼어도 앞 행들의 번호는 그대로다.
    assert [i["phase_seq"] for i in cells] == [0, 0, 0, 1, None]


# =============================================================================
# 팝오버가 쓰는 필드 — title · deliverable · owners (plan.md §0.5-3 개편)
#
# 전체 현황의 hover 팝오버가 프로젝트 대시보드 카드와 **같은 포맷**
# (담당 · 상태 · action item · deliverable)이어야 한다. 그 넷 중 셋이 미니맵
# 응답에 없어서 추가된 필드들이다.
# =============================================================================
def test_overview_items_carry_the_title_and_deliverable(client, published):
    created = make_project(client, published)
    cells = overview(client)[0]["items"]

    assert [i["title"] for i in cells] == ["행 1", "행 2", "행 3", "행 4"]
    assert [i["deliverable"] for i in cells] == ["산출물 1", "산출물 2", "산출물 3", "산출물 4"]
    # 그리드 응답과 같은 값이어야 한다 — 두 화면이 다른 문구를 보이면 안 된다.
    assert [i["title"] for i in cells] == [r["title"] for r in created["items"]]


def test_overview_items_carry_owner_names_in_order(db, client, published):
    """Owner 는 **이름 배열**이다 (id 가 아니라).

    프로젝트 Owner 는 로컬 사본이라 id 가 템플릿과 다르고, 이 화면에서 그 id 로
    할 수 있는 일이 없다. 순서는 `sort_order` 를 따른다.
    """
    from app.models import ProjectItemOwner, ProjectOwner

    created = make_project(client, published)
    project_id = created["project"]["id"]

    owners = {
        o.name: o
        for o in db.query(ProjectOwner).filter_by(project_id=project_id).all()
    }
    first = db.query(ProjectItem).filter_by(project_id=project_id, sort_order=1).one()
    first.owners = [
        ProjectItemOwner(owner_id=owners["사내 개발부서"].id, sort_order=1),
        ProjectItemOwner(owner_id=owners["DSEP 인프라 담당자"].id, sort_order=2),
    ]
    db.commit()

    cells = overview(client)[0]["items"]
    assert cells[0]["owners"] == ["사내 개발부서", "DSEP 인프라 담당자"]
    assert cells[1]["owners"] == []


def test_owner_names_survive_the_deep_copy_into_the_overview(db, client, published):
    """템플릿 행의 Owner → 프로젝트 로컬 사본 → 전체 현황까지 이어지는지."""
    from app.models import ItemOwner

    template_row = db.query(Item).filter_by(
        version_id=published.published.id, sort_order=1
    ).one()
    template_row.owners = [ItemOwner(owner_id=published.o1.id, sort_order=1)]
    db.commit()

    make_project(client, published)
    assert overview(client)[0]["items"][0]["owners"] == ["DSEP 인프라 담당자"]


def test_a_gray_row_reports_null_text_and_no_owners(client, published):
    """§0.2 의 회색 행은 아무것도 없이 태어난다 — 팝오버가 빈 값을 견뎌야 한다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]

    appended = client.post(f"{API}/projects/{project_id}/items")
    assert appended.status_code == 201, appended.text

    last = overview(client)[0]["items"][-1]
    assert last["title"] is None
    assert last["deliverable"] is None
    assert last["dash_label"] is None
    assert last["owners"] == []


def test_the_server_does_not_apply_the_label_fallback(client, published):
    """폴백(`dash_label` → `deliverable` → title)은 **화면이** 적용한다.

    서버가 미리 채우면 "라벨이 비어 있다" 는 사실이 응답에서 사라지고, 그리드의
    편집 컬럼이 무엇을 저장해야 할지 알 수 없게 된다 (§0.5-1 과 같은 이유).
    """
    created = make_project(client, published)
    project_id = created["project"]["id"]

    response = client.put(
        f"{API}/projects/{project_id}/items",
        json={"items": [{"id": r["id"], "title": r["title"], "deliverable": r["deliverable"]}
                        for r in created["items"]]},
    )
    assert response.status_code == 200, response.text

    first = overview(client)[0]["items"][0]
    assert first["dash_label"] is None          # deliverable 로 채워지지 않았다
    assert first["deliverable"] == "산출물 1"


# =============================================================================
# overview 의 문서 구획 (plan.md §0.5-3b / §0.5-4)
# =============================================================================
def test_overview_lists_the_documents_a_project_uses(client, published):
    """저장된 행이 없어도 활성 전역 문서가 전부 나온다 — 기본값이 사용=1 이다."""
    make_project(client, published)
    documents = overview(client)[0]["documents"]

    assert [d["no"] for d in documents] == [1, 2]
    assert all(d["doc_status"] == "NOT_WRITTEN" for d in documents)
    assert all(d["link_url"] is None for d in documents)
    assert set(documents[0]) == {"id", "no", "name", "doc_status", "link_url"}


def test_overview_excludes_documents_the_project_does_not_use(client, published):
    """`is_used=0` 은 ④ 구획에서 빠진다 — 그 구획에 자리를 차지할 이유가 없다."""
    project_id = make_project(client, published)["project"]["id"]
    rows = client.get(f"{API}/projects/{project_id}/documents").json()["documents"]

    response = client.put(
        f"{API}/projects/{project_id}/documents",
        json={"documents": [
            {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": False},
            {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": True},
        ]},
    )
    assert response.status_code == 200, response.text

    # 1번을 껐으므로 남은 문서가 **1번**이 된다 — 번호에 구멍이 남지 않는다.
    assert [d["no"] for d in overview(client)[0]["documents"]] == [1]


def test_overview_document_numbers_are_always_contiguous(client, published):
    """전체 현황은 사용 문서만 담으므로 `no` 에 구멍이 없다 (§0.5.10)."""
    project_id = make_project(client, published)["project"]["id"]
    rows = client.get(f"{API}/projects/{project_id}/documents").json()["documents"]

    client.put(
        f"{API}/projects/{project_id}/documents",
        json={"documents": [
            {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": False},
            {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": True},
        ]},
    )

    numbers = [d["no"] for d in overview(client)[0]["documents"]]
    assert numbers == list(range(1, len(numbers) + 1))


def test_overview_carries_the_link_and_status(client, published):
    project_id = make_project(client, published)["project"]["id"]
    rows = client.get(f"{API}/projects/{project_id}/documents").json()["documents"]

    client.put(
        f"{API}/projects/{project_id}/documents",
        json={"documents": [
            {"id": rows[0]["id"], "name": rows[0]["name"], "doc_status": "DONE",
             "link_url": "https://drive.example.com/charter"},
            {"id": rows[1]["id"], "name": rows[1]["name"]},
        ]},
    )

    first = overview(client)[0]["documents"][0]
    assert first["doc_status"] == "DONE"
    assert first["link_url"] == "https://drive.example.com/charter"


def test_overview_skips_documents_the_project_stopped_using(db, client, published):
    """§0.5.10 — 전역 비활성 개념이 사라졌다. 프로젝트가 사용 해제한 것만 빠진다."""
    created = make_project(client, published)
    project_id = created["project"]["id"]
    second = db.query(ProjectDocument).filter_by(project_id=project_id, sort_order=2).one()
    second.is_used = 0
    db.commit()

    assert [d["no"] for d in overview(client)[0]["documents"]] == [1]


def test_overview_document_settings_do_not_leak_between_projects(client, published):
    a = make_project(client, published, name="A")["project"]["id"]
    make_project(client, published, name="B")

    rows = client.get(f"{API}/projects/{a}/documents").json()["documents"]
    client.put(
        f"{API}/projects/{a}/documents",
        json={"documents": [
            {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": False},
            {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": True},
        ]},
    )

    entries = {p["name"]: p for p in overview(client)}
    assert [d["no"] for d in entries["A"]["documents"]] == [1]
    assert [d["no"] for d in entries["B"]["documents"]] == [1, 2]


# =============================================================================
# 범위 — active 프로젝트만, 설비사 이름은 포트 경유
# =============================================================================
def test_overview_lists_only_active_projects(client, published):
    keep = make_project(client, published, name="살아있는 프로젝트")["project"]["id"]
    drop = make_project(client, published, name="비활성 프로젝트")["project"]["id"]

    assert client.delete(f"{API}/projects/{drop}").status_code == 200
    assert [p["id"] for p in overview(client)] == [keep]


def test_overview_without_a_resolver_returns_a_null_maker_name(client, published):
    """resolver 미주입은 **정상 상태**다 (INTEGRATION.md §2.2)."""
    make_project(client, published)
    assert overview(client)[0]["maker_name"] is None


def test_overview_with_a_resolver_fills_the_maker_name_in_one_call(make_client, db, board, published):
    client = make_client()
    make_project(client, published, name="A", maker_id=1)
    make_project(client, published, name="B", maker_id=2)
    make_project(client, published, name="C", maker_id=1)

    resolver = FakeResolver({1: "설비사 가", 2: "설비사 나"})
    body = make_client(maker_resolver=resolver).get(f"{API}/projects/overview").json()

    sections = {m["maker_id"]: m for m in body["makers"]}
    assert [m["name"] for m in body["makers"]] == ["설비사 가", "설비사 나"]
    assert [p["name"] for p in sections[1]["projects"]] == ["A", "C"]
    # 카드의 maker_name 은 섹션 이름과 같은 값이어야 한다 (두 곳이 갈리면 안 된다).
    assert all(p["maker_name"] == "설비사 가" for p in sections[1]["projects"])
    # 프로젝트 3건이지만 조회는 1회, id 는 중복 제거 — 설비사 테이블 JOIN 이 아니다.
    # (이 `FakeResolver` 는 `list_makers` 가 없어 이름 해석 경로로 떨어진다.)
    assert resolver.calls == [[1, 2]]


def test_overview_survives_a_dangling_maker_id(make_client, published):
    client = make_client()
    make_project(client, published, maker_id=424242)

    resolver = FakeResolver({1: "설비사 가"})
    makers = make_client(maker_resolver=resolver).get(f"{API}/projects/overview").json()["makers"]
    assert len(makers) == 1
    assert makers[0]["maker_id"] == 424242 and makers[0]["name"] is None
    assert makers[0]["projects"][0]["maker_name"] is None


# =============================================================================
# 읽기 전용
# =============================================================================
def test_overview_writes_nothing(db, client, published):
    """관망 화면을 여는 것만으로 데이터가 바뀌면 안 된다.

    실수하기 쉬운 자리다: 프로젝트 보드는 `sync_master_seq=True` 라, 그리드
    경로(`build_item_views` → `renumber_and_persist`)를 무심코 재사용했다면
    조회가 곧 기준정보 쓰기가 된다. 그래서 흐트러진 `seq_no` 가 조회 뒤에도
    **그대로 흐트러져 있어야** 한다.
    """
    created = make_project(client, published)
    project_id = created["project"]["id"]

    for phase in db.query(ProjectPhase).filter_by(project_id=project_id).all():
        phase.seq_no = 99
    items = db.query(ProjectItem).filter_by(project_id=project_id).order_by(ProjectItem.id).all()
    for item in items:
        item.sort_order = item.sort_order + 100
    db.commit()

    before_phases = {p.id: p.seq_no for p in db.query(ProjectPhase).filter_by(project_id=project_id)}
    before_items = {i.id: i.sort_order for i in db.query(ProjectItem).filter_by(project_id=project_id)}

    overview(client)

    db.expire_all()
    after_phases = {p.id: p.seq_no for p in db.query(ProjectPhase).filter_by(project_id=project_id)}
    after_items = {i.id: i.sort_order for i in db.query(ProjectItem).filter_by(project_id=project_id)}
    assert after_phases == before_phases
    assert after_items == before_items


def test_overview_is_not_a_mutating_route(client):
    """라우트 표에서 직접 확인한다 — GET 하나뿐이어야 한다."""
    schema = client.app.openapi()
    assert set(schema["paths"]["/api/v1/projects/overview"]) == {"get"}
