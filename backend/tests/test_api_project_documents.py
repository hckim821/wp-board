"""문서 모델 — plan.md §0.5.10 (포맷 종속 + 프로젝트 복제).

전역 문서가 폐기되고 문서가 Phase/Milestone/Owner 와 같은 스코프 규칙 위로 옮겨졌다.
그래서 검사도 세 갈래다.

1. **스코프** — 템플릿이 소유하고, 프로젝트는 생성 시 복제하며, 이후 서로 무관하다.
2. **관리** — 템플릿은 `apply`(집합 일치), 프로젝트는 전량 교체. 둘 다 원자적.
3. **삭제 캐스케이드** — 문서를 지우면 항목 링크가 함께 사라지고, 응답에 재계산된
   행 목록이 실려 온다.
"""

from __future__ import annotations

import pytest

from app.models import (
    Item,
    ItemDocument,
    Project,
    ProjectDocument,
    ProjectItemDocument,
    TemplateDocument,
)
from app.services import version_service

pytestmark = pytest.mark.db

API = "/api/v1"


@pytest.fixture
def published(db, board):
    """행 2개 — 1번 행이 문서 1을, 2번 행이 문서 1·2를 쓴다."""
    for order, docs in ((1, [board.d1]), (2, [board.d1, board.d2])):
        item = Item(
            version_id=board.published.id, sort_order=order,
            phase_id=board.p0.id, milestone_id=board.m01.id,
            title=f"행 {order}", deliverable=f"산출물 {order}",
        )
        item.documents = [
            ItemDocument(template_document_id=d.id, sort_order=i)
            for i, d in enumerate(docs, start=1)
        ]
        db.add(item)
    db.commit()
    return board


@pytest.fixture
def draft(db, published):
    version = version_service.create_draft(db, published.wp.id)
    db.commit()
    published.draft = version
    return published


@pytest.fixture
def project(client, published):
    response = client.post(
        f"{API}/projects",
        json={"maker_id": 7, "name": "문서 테스트 프로젝트", "template_id": published.wp.id},
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]["id"]


def template_docs(client, version_id):
    response = client.get(f"{API}/versions/{version_id}/documents")
    assert response.status_code == 200, response.text
    return response.json()["documents"]


def apply_docs(client, version_id, documents, deleted_ids=()):
    return client.post(
        f"{API}/versions/{version_id}/documents/apply",
        json={"documents": documents, "deleted_ids": list(deleted_ids)},
    )


def project_docs(client, project_id):
    response = client.get(f"{API}/projects/{project_id}/documents")
    assert response.status_code == 200, response.text
    return response.json()["documents"]


def save_docs(client, project_id, documents, deleted_ids=()):
    return client.put(
        f"{API}/projects/{project_id}/documents",
        json={"documents": documents, "deleted_ids": list(deleted_ids)},
    )


def items_of(client, project_id):
    return client.get(f"{API}/projects/{project_id}").json()["items"]


# =============================================================================
# 스코프 — 템플릿 소유, 프로젝트 복제
# =============================================================================
def test_documents_belong_to_the_template_not_the_globe(client, published):
    rows = template_docs(client, published.published.id)

    assert [d["no"] for d in rows] == [1, 2]
    assert [d["name"] for d in rows] == [
        "Project Charter & R&R", "DSEP Readiness & I/O Spec"
    ]
    assert "code" not in rows[0], "원문자 코드는 §0.5.10 에서 폐기됐다"


def test_a_second_template_has_its_own_documents(db, client, published):
    """전역이 아니라는 것의 핵심 — 템플릿마다 자기 문서를 갖는다."""
    from app.models import Template, Version
    from app.models.base import VersionStatus

    other = Template(code="OTHER", name="다른 템플릿", phase_start_no=0)
    db.add(other)
    db.flush()
    version = Version(template_id=other.id, version_number=1,
                      status=VersionStatus.PUBLISHED, phase_start_no=0)
    db.add(version)
    db.add(TemplateDocument(template_id=other.id, name="남의 문서", sort_order=1))
    db.commit()

    assert [d["name"] for d in template_docs(client, version.id)] == ["남의 문서"]
    assert len(template_docs(client, published.published.id)) == 2


def test_project_creation_copies_the_template_documents(db, client, published):
    project_id = client.post(
        f"{API}/projects",
        json={"maker_id": 7, "name": "복제", "template_id": published.wp.id},
    ).json()["project"]["id"]

    copies = db.query(ProjectDocument).filter_by(project_id=project_id).all()
    assert [c.sort_order for c in copies] == [1, 2]
    assert [c.name for c in copies] == [
        "Project Charter & R&R", "DSEP Readiness & I/O Spec"
    ]
    # **사본이다** — 템플릿 문서와 id 가 다르다.
    assert {c.id for c in copies}.isdisjoint({published.d1.id, published.d2.id})
    # 초기값: 사용=1 · 작성전 · 링크 없음.
    assert all(c.is_used and c.link_url is None for c in copies)
    assert all(c.doc_status.value == "NOT_WRITTEN" for c in copies)


def test_the_copied_item_links_point_at_the_project_copies(db, client, published, project):
    copies = {c.id for c in db.query(ProjectDocument).filter_by(project_id=project).all()}
    links = (
        db.query(ProjectItemDocument)
        .join(ProjectDocument, ProjectDocument.id == ProjectItemDocument.project_document_id)
        .filter(ProjectDocument.project_id == project)
        .all()
    )
    assert len(links) == 3                       # 행1 → 1건, 행2 → 2건
    assert all(link.project_document_id in copies for link in links)


def test_editing_a_project_document_does_not_touch_the_template(db, client, published, project):
    rows = project_docs(client, project)
    assert save_docs(client, project, [
        {"id": rows[0]["id"], "name": "프로젝트에서 고침"},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
    ]).status_code == 200

    db.expire_all()
    assert db.get(TemplateDocument, published.d1.id).name == "Project Charter & R&R"


def test_a_draft_does_not_duplicate_the_template_documents(db, client, draft):
    """문서는 Phase/Milestone 처럼 **템플릿**에 매인다 — 버전마다 늘지 않는다."""
    assert db.query(TemplateDocument).filter_by(template_id=draft.wp.id).count() == 2
    assert [d["no"] for d in template_docs(client, draft.draft.id)] == [1, 2]


# =============================================================================
# 템플릿 apply
# =============================================================================
def test_apply_adds_renames_and_reorders(client, draft):
    rows = template_docs(client, draft.draft.id)

    response = apply_docs(client, draft.draft.id, [
        {"id": rows[1]["id"], "name": "두번째가 첫번째로"},
        {"id": rows[0]["id"], "name": "이름 변경"},
        {"id": None, "name": "신규 문서"},
    ])
    assert response.status_code == 200, response.text

    after = response.json()["documents"]
    assert [d["no"] for d in after] == [1, 2, 3]
    assert [d["name"] for d in after] == ["두번째가 첫번째로", "이름 변경", "신규 문서"]
    assert after[0]["id"] == rows[1]["id"]       # 같은 행이 위로 갔다


def test_apply_deletes_and_cascades_the_item_links(db, client, draft):
    rows = template_docs(client, draft.draft.id)
    before = client.get(f"{API}/versions/{draft.draft.id}").json()["items"]
    assert [len(i["documents"]) for i in before] == [1, 2]

    response = apply_docs(
        client, draft.draft.id,
        [{"id": rows[1]["id"], "name": rows[1]["name"]}],
        deleted_ids=[rows[0]["id"]],
    )
    assert response.status_code == 200, response.text

    # 응답에 **재계산된 행 목록**이 실려 온다 (§0.5.10).
    items = response.json()["items"]
    assert [len(i["documents"]) for i in items] == [0, 1]
    assert [d["no"] for d in response.json()["documents"]] == [1]


def test_apply_deactivates_instead_of_deleting_when_another_version_uses_it(db, client, draft):
    """§0.4 정밀화 1 동형 — 발행본이 쓰는 문서는 지우지 않고 비활성화한다."""
    rows = template_docs(client, draft.draft.id)
    target = rows[0]["id"]

    response = apply_docs(
        client, draft.draft.id,
        [{"id": rows[1]["id"], "name": rows[1]["name"]}],
        deleted_ids=[target],
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    survivor = db.get(TemplateDocument, target)
    assert survivor is not None, "PUBLISHED 가 쓰는 문서를 하드 삭제했다"
    assert survivor.is_active == 0
    # 비활성 문서는 목록에서 빠진다.
    assert target not in [d["id"] for d in response.json()["documents"]]


def test_apply_hard_deletes_a_document_no_other_version_uses(db, client, draft):
    rows = template_docs(client, draft.draft.id)
    created = apply_docs(client, draft.draft.id, [
        {"id": rows[0]["id"], "name": rows[0]["name"]},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
        {"id": None, "name": "아무도 안 쓰는 문서"},
    ]).json()["documents"]
    orphan = created[-1]["id"]

    apply_docs(client, draft.draft.id, [
        {"id": rows[0]["id"], "name": rows[0]["name"]},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
    ], deleted_ids=[orphan])

    db.expire_all()
    assert db.get(TemplateDocument, orphan) is None


def test_apply_requires_the_set_to_match(client, draft):
    """`phases/apply` 와 같은 집합 일치 규칙 — 빠뜨린 문서가 있으면 422."""
    rows = template_docs(client, draft.draft.id)
    response = apply_docs(client, draft.draft.id, [{"id": rows[0]["id"], "name": "하나만"}])

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_SET_MISMATCH"


@pytest.mark.parametrize("name", ["", "   "])
def test_apply_rejects_an_empty_name(client, draft, name):
    rows = template_docs(client, draft.draft.id)
    response = apply_docs(client, draft.draft.id, [
        {"id": rows[0]["id"], "name": name},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_EMPTY_NAME"


def test_apply_rejects_duplicate_names(client, draft):
    rows = template_docs(client, draft.draft.id)
    response = apply_docs(client, draft.draft.id, [
        {"id": rows[0]["id"], "name": "같은 이름"},
        {"id": rows[1]["id"], "name": "같은 이름"},
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_DUPLICATE_NAME"


def test_apply_rejects_a_document_from_another_template(db, client, draft):
    from app.models import Template

    other = Template(code="X", name="다른 템플릿")
    db.add(other)
    db.flush()
    foreign = TemplateDocument(template_id=other.id, name="남의 문서", sort_order=1)
    db.add(foreign)
    db.commit()

    rows = template_docs(client, draft.draft.id)
    response = apply_docs(client, draft.draft.id, [
        {"id": rows[0]["id"], "name": rows[0]["name"]},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
        {"id": foreign.id, "name": "훔친 문서"},
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_OUT_OF_SCOPE"


def test_apply_is_blocked_on_a_published_version(client, published):
    rows = template_docs(client, published.published.id)
    response = apply_docs(client, published.published.id, [
        {"id": rows[0]["id"], "name": "고치려 함"},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
    ])
    assert response.status_code == 409, response.text


def test_a_rejected_apply_changes_nothing(db, client, draft):
    rows = template_docs(client, draft.draft.id)
    apply_docs(client, draft.draft.id, [
        {"id": rows[0]["id"], "name": ""},
        {"id": rows[1]["id"], "name": "바뀌면 안 됨"},
    ])

    db.expire_all()
    assert [d["name"] for d in template_docs(client, draft.draft.id)] == [
        "Project Charter & R&R", "DSEP Readiness & I/O Spec"
    ]


# =============================================================================
# 프로젝트 저장 (전량 교체)
# =============================================================================
def test_project_documents_round_trip(client, project):
    rows = project_docs(client, project)

    response = save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": True,
         "doc_status": "WRITING", "link_url": "https://drive.example.com/x"},
        {"id": rows[1]["id"], "name": "이름 변경", "is_used": False},
    ])
    assert response.status_code == 200, response.text

    after = project_docs(client, project)
    # 2번을 껐으므로 번호는 **사용 문서만** 센다 (§0.5.10 팝업 정밀화).
    assert [d["no"] for d in after] == [1, None]
    assert after[0]["doc_status"] == "WRITING"
    assert after[0]["link_url"] == "https://drive.example.com/x"
    assert after[1]["name"] == "이름 변경" and after[1]["is_used"] is False


# =============================================================================
# 표시 번호 = 사용 문서만 세는 파생값 (§0.5.10 팝업 정밀화)
# =============================================================================
def test_the_display_number_counts_only_used_documents(client, project):
    """꺼진 문서가 번호를 차지하면 목록이 `1, 3` 처럼 구멍 난 채로 읽힌다."""
    rows = project_docs(client, project)
    save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": False},
        {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": True},
        {"id": None, "name": "세번째", "is_used": True},
    ])

    after = project_docs(client, project)
    # 저장 순서는 그대로, 번호만 사용 문서를 훑으며 1..N.
    assert [d["name"] for d in after] == [
        "Project Charter & R&R", "DSEP Readiness & I/O Spec", "세번째"
    ]
    assert [d["no"] for d in after] == [None, 1, 2]


def test_turning_a_document_back_on_restores_a_contiguous_sequence(client, project):
    rows = project_docs(client, project)
    save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": False},
        {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": True},
    ])
    assert [d["no"] for d in project_docs(client, project)] == [None, 1]

    save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": True},
        {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": True},
    ])
    assert [d["no"] for d in project_docs(client, project)] == [1, 2]


def test_an_unused_document_is_dropped_from_the_row_payload(client, project):
    """그리드 셀은 꺼진 문서를 보여주지 않는다 — 번호가 없으니 실을 수도 없다."""
    rows = project_docs(client, project)
    before = items_of(client, project)
    assert [len(i["documents"]) for i in before] == [1, 2]

    save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"], "is_used": True},
        {"id": rows[1]["id"], "name": rows[1]["name"], "is_used": False},
    ])

    after = items_of(client, project)
    assert [len(i["documents"]) for i in after] == [1, 1]
    assert all(d["no"] == 1 for i in after for d in i["documents"])


def test_the_template_tier_numbers_every_document(client, draft):
    """템플릿에는 `is_used` 가 없다 — 전부 1..N 그대로."""
    assert [d["no"] for d in template_docs(client, draft.draft.id)] == [1, 2]


def test_a_project_can_add_its_own_document(client, project):
    """사용자 확정 ② — 프로젝트 로컬 행 추가를 허용한다."""
    rows = project_docs(client, project)
    response = save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"]},
        {"id": rows[1]["id"], "name": rows[1]["name"]},
        {"id": None, "name": "이 프로젝트에만 있는 문서"},
    ])
    assert response.status_code == 200, response.text

    after = project_docs(client, project)
    assert [d["no"] for d in after] == [1, 2, 3]
    assert after[2]["name"] == "이 프로젝트에만 있는 문서"


def test_reordering_renumbers_from_the_array_position(client, project):
    rows = project_docs(client, project)
    save_docs(client, project, [
        {"id": rows[1]["id"], "name": rows[1]["name"]},
        {"id": rows[0]["id"], "name": rows[0]["name"]},
    ])

    after = project_docs(client, project)
    assert [d["id"] for d in after] == [rows[1]["id"], rows[0]["id"]]
    assert [d["no"] for d in after] == [1, 2]


def test_deleting_a_project_document_cascades_the_item_links(db, client, project):
    rows = project_docs(client, project)
    before = items_of(client, project)
    assert [len(i["documents"]) for i in before] == [1, 2]

    response = save_docs(
        client, project,
        [{"id": rows[1]["id"], "name": rows[1]["name"]}],
        deleted_ids=[rows[0]["id"]],
    )
    assert response.status_code == 200, response.text

    # 응답이 재계산된 행 목록을 함께 준다.
    assert [len(i["documents"]) for i in response.json()["items"]] == [0, 1]
    db.expire_all()
    assert db.get(ProjectDocument, rows[0]["id"]) is None


def test_save_rejects_an_empty_name_with_a_cell_location(client, project):
    rows = project_docs(client, project)
    response = save_docs(client, project, [
        {"id": rows[0]["id"], "name": rows[0]["name"]},
        {"id": rows[1]["id"], "name": "  "},
    ])
    assert response.status_code == 422, response.text
    body = response.json()["detail"]
    assert body["code"] == "DOCUMENT_EMPTY_NAME"
    assert body["row_no"] == 2 and body["field"] == "name"


def test_save_rejects_another_projects_document(client, published, project):
    other = client.post(
        f"{API}/projects",
        json={"maker_id": 8, "name": "다른 프로젝트", "template_id": published.wp.id},
    ).json()["project"]["id"]
    stolen = project_docs(client, other)[0]["id"]

    response = save_docs(client, project, [{"id": stolen, "name": "훔친 문서"}])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_OUT_OF_SCOPE"


def test_save_rejects_the_same_document_twice(client, project):
    rows = project_docs(client, project)
    response = save_docs(client, project, [
        {"id": rows[0]["id"], "name": "하나"},
        {"id": rows[0]["id"], "name": "둘"},
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_DUPLICATED"


def test_save_rejects_saving_and_deleting_the_same_document(client, project):
    rows = project_docs(client, project)
    response = save_docs(
        client, project,
        [{"id": rows[0]["id"], "name": rows[0]["name"]}],
        deleted_ids=[rows[0]["id"]],
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DOCUMENT_DELETE_CONFLICT"


def test_a_rejected_save_changes_nothing(db, client, project):
    rows = project_docs(client, project)
    save_docs(client, project, [
        {"id": rows[0]["id"], "name": "바뀌면 안 됨"},
        {"id": rows[1]["id"], "name": ""},
    ])

    db.expire_all()
    assert [d["name"] for d in project_docs(client, project)] == [
        "Project Charter & R&R", "DSEP Readiness & I/O Spec"
    ]


def test_an_empty_save_clears_every_document(db, client, project):
    rows = project_docs(client, project)
    response = save_docs(client, project, [], deleted_ids=[r["id"] for r in rows])
    assert response.status_code == 200, response.text

    assert project_docs(client, project) == []
    assert all(len(i["documents"]) == 0 for i in response.json()["items"])


def test_documents_go_away_with_the_project(db, client, project):
    db.expire_all()
    db.delete(db.get(Project, project))
    db.commit()
    assert db.query(ProjectDocument).filter_by(project_id=project).count() == 0


def test_unknown_ids_are_404(client):
    assert client.get(f"{API}/projects/999999/documents").status_code == 404
    assert client.get(f"{API}/versions/999999/documents").status_code == 404
