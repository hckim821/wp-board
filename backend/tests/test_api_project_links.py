"""프로젝트 주요 링크 — plan.md §0.5.5.

**전량 교체**라는 것이 이 엔드포인트의 성격을 거의 다 정한다. 배열 순서가 곧
`sort_order` 이고, 목록에서 빠진 링크는 삭제되며, 재정렬·수정·추가·삭제가 한 번의
저장에 섞여 들어온다. 그래서 검사도 그 네 가지가 **한 요청 안에서** 동시에 맞게
처리되는지에 몰려 있다.

문서 설정(`test_api_project_documents.py`)과 헷갈리지 말 것 — 그쪽은 전역 마스터에
매인 부분 업서트다.
"""

from __future__ import annotations

import pytest

from app.models import Item, Project, ProjectLink

pytestmark = pytest.mark.db

API = "/api/v1"


@pytest.fixture
def published(db, board):
    for order in (1, 2):
        db.add(
            Item(
                version_id=board.published.id,
                sort_order=order,
                phase_id=board.p0.id,
                milestone_id=board.m01.id,
                title=f"행 {order}",
            )
        )
    db.commit()
    return board


@pytest.fixture
def project(client, published):
    response = client.post(
        f"{API}/projects",
        json={"maker_id": 7, "name": "링크 테스트 프로젝트", "template_id": published.wp.id},
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]["id"]


def links_of(client, project_id):
    response = client.get(f"{API}/projects/{project_id}/links")
    assert response.status_code == 200, response.text
    return response.json()["links"]


def save(client, project_id, links):
    return client.put(f"{API}/projects/{project_id}/links", json={"links": links})


def seed(client, project_id, count=3):
    """`count` 개를 저장하고 응답(= id 가 붙은 목록)을 돌려준다."""
    response = save(client, project_id, [
        {"id": None, "description": f"설명 {i}", "url": f"https://example.com/{i}"}
        for i in range(1, count + 1)
    ])
    assert response.status_code == 200, response.text
    return response.json()["links"]


# =============================================================================
# 왕복 — 순서 보존
# =============================================================================
def test_a_new_project_has_no_links(client, project):
    """문서 설정과 달리 기본 목록이 없다 — 있는 행이 전부다."""
    assert links_of(client, project) == []


def test_saving_assigns_ids_and_sort_order_from_the_array_position(client, project):
    rows = seed(client, project)

    assert [r["sort_order"] for r in rows] == [1, 2, 3]
    assert [r["description"] for r in rows] == ["설명 1", "설명 2", "설명 3"]
    assert all(isinstance(r["id"], int) for r in rows)
    assert links_of(client, project) == rows


def test_the_response_shape(client, project):
    row = seed(client, project, count=1)[0]
    assert set(row) == {"id", "description", "url", "sort_order"}


def test_sort_order_is_ignored_if_sent(client, project):
    """`sort_order` 는 입력 스키마에 없다 — 보내도 배열 위치가 이긴다.

    순서의 정본이 둘이면 낡은 번호가 직전 재정렬을 조용히 되돌린다.
    """
    response = save(client, project, [
        {"id": None, "description": "두번째여야 함", "url": "https://a", "sort_order": 99},
        {"id": None, "description": "첫번째여야 함", "url": "https://b", "sort_order": 1},
    ])
    assert response.status_code == 200, response.text
    assert [r["description"] for r in response.json()["links"]] == [
        "두번째여야 함", "첫번째여야 함",
    ]
    assert [r["sort_order"] for r in response.json()["links"]] == [1, 2]


def test_editing_a_description_and_url_in_place(client, project):
    rows = seed(client, project, count=2)

    response = save(client, project, [
        {"id": rows[0]["id"], "description": "고친 설명", "url": "https://changed.example.com"},
        {"id": rows[1]["id"], "description": rows[1]["description"], "url": rows[1]["url"]},
    ])
    assert response.status_code == 200, response.text

    after = links_of(client, project)
    assert after[0]["id"] == rows[0]["id"]          # 같은 행을 고친 것이다
    assert after[0]["description"] == "고친 설명"
    assert after[0]["url"] == "https://changed.example.com"


# =============================================================================
# 재정렬 (관리형 row drag 가 만드는 요청)
# =============================================================================
def test_reordering_keeps_the_ids_and_renumbers(client, project):
    rows = seed(client, project)

    response = save(client, project, [
        {"id": rows[2]["id"], "description": rows[2]["description"], "url": rows[2]["url"]},
        {"id": rows[0]["id"], "description": rows[0]["description"], "url": rows[0]["url"]},
        {"id": rows[1]["id"], "description": rows[1]["description"], "url": rows[1]["url"]},
    ])
    assert response.status_code == 200, response.text

    after = links_of(client, project)
    assert [r["id"] for r in after] == [rows[2]["id"], rows[0]["id"], rows[1]["id"]]
    assert [r["sort_order"] for r in after] == [1, 2, 3]
    assert [r["description"] for r in after] == ["설명 3", "설명 1", "설명 2"]


def test_reorder_add_edit_and_delete_in_one_save(db, client, project):
    """네 연산이 한 요청에 섞여 들어오는 것이 이 화면의 정상 사용이다."""
    rows = seed(client, project)

    response = save(client, project, [
        {"id": rows[1]["id"], "description": "이동+수정", "url": rows[1]["url"]},
        {"id": None, "description": "신규", "url": "https://new.example.com"},
        {"id": rows[0]["id"], "description": rows[0]["description"], "url": rows[0]["url"]},
        # rows[2] 는 빠졌다 → 삭제
    ])
    assert response.status_code == 200, response.text

    after = links_of(client, project)
    assert [r["description"] for r in after] == ["이동+수정", "신규", "설명 1"]
    assert [r["sort_order"] for r in after] == [1, 2, 3]
    assert db.query(ProjectLink).filter_by(project_id=project).count() == 3


# =============================================================================
# 삭제 — 목록에서 빠지면 지워진다
# =============================================================================
def test_a_missing_id_deletes_that_link(db, client, project):
    rows = seed(client, project)

    response = save(client, project, [
        {"id": rows[0]["id"], "description": rows[0]["description"], "url": rows[0]["url"]}
    ])
    assert response.status_code == 200, response.text

    assert [r["id"] for r in links_of(client, project)] == [rows[0]["id"]]
    assert db.query(ProjectLink).filter_by(project_id=project).count() == 1


def test_an_empty_list_clears_every_link(db, client, project):
    seed(client, project)

    response = save(client, project, [])
    assert response.status_code == 200, response.text
    assert response.json()["links"] == []
    assert db.query(ProjectLink).filter_by(project_id=project).count() == 0


def test_deleting_a_project_row_cascades(db, client, project):
    seed(client, project)

    db.expire_all()
    db.delete(db.get(Project, project))
    db.commit()

    assert db.query(ProjectLink).filter_by(project_id=project).count() == 0


# =============================================================================
# URL 검증 — 422 + 필드 위치
# =============================================================================
@pytest.mark.parametrize(
    "url",
    [
        "example.com/page",          # 스킴 없음
        "www.example.com",
        "ftp://example.com",
        "file:///C:/secret.txt",
        "javascript:alert(1)",
        "/relative/path",
        "",
        "   ",
        "https://",                  # 스킴만 있고 주소가 없다
        "http://   ",
    ],
)
def test_a_non_http_url_is_422(client, project, url):
    response = save(client, project, [{"id": None, "description": "설명", "url": url}])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "LINK_URL_INVALID"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com/path?q=1#frag",
        "HTTPS://EXAMPLE.COM",       # 스킴 대소문자는 가리지 않는다
        "https://confluence.internal/display/EDM/page",
    ],
)
def test_an_http_url_is_accepted(client, project, url):
    response = save(client, project, [{"id": None, "description": "설명", "url": url}])
    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["url"] == url.strip()


def test_the_error_points_at_the_offending_row_and_field(client, project):
    """그리드가 문제의 셀을 짚으려면 위치가 필요하다 (§2.5 와 같은 규약)."""
    response = save(client, project, [
        {"id": None, "description": "정상", "url": "https://ok.example.com"},
        {"id": None, "description": "정상", "url": "https://ok2.example.com"},
        {"id": None, "description": "정상", "url": "틀린 주소"},
    ])
    assert response.status_code == 422, response.text

    detail = response.json()["detail"]
    assert detail["index"] == 2 and detail["row_no"] == 3
    assert detail["field"] == "url"


def test_a_url_is_trimmed_before_saving(client, project):
    response = save(client, project, [
        {"id": None, "description": "설명", "url": "  https://example.com  "}
    ])
    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["url"] == "https://example.com"


# =============================================================================
# 설명 검증
# =============================================================================
@pytest.mark.parametrize("description", ["", "   ", "\t\n"])
def test_a_blank_description_is_422(client, project, description):
    response = save(client, project, [
        {"id": None, "description": description, "url": "https://example.com"}
    ])
    assert response.status_code == 422, response.text
    body = response.json()["detail"]
    assert body["code"] == "LINK_DESCRIPTION_REQUIRED"
    assert body["field"] == "description" and body["row_no"] == 1


def test_a_description_is_trimmed_before_saving(client, project):
    response = save(client, project, [
        {"id": None, "description": "  다듬힌 설명  ", "url": "https://example.com"}
    ])
    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["description"] == "다듬힌 설명"


def test_an_overlong_description_is_rejected(client, project):
    response = save(client, project, [
        {"id": None, "description": "가" * 201, "url": "https://example.com"}
    ])
    assert response.status_code == 422, response.text


def test_an_overlong_url_is_rejected(client, project):
    response = save(client, project, [
        {"id": None, "description": "설명", "url": "https://example.com/" + "x" * 1000}
    ])
    assert response.status_code == 422, response.text


# =============================================================================
# 검증이 먼저, 쓰기는 나중
# =============================================================================
def test_a_rejected_save_changes_nothing(db, client, project):
    """유효한 항목이 섞여 있어도, 재정렬·삭제가 섞여 있어도 저장되지 않는다."""
    rows = seed(client, project)

    response = save(client, project, [
        {"id": rows[2]["id"], "description": "옮기려 했음", "url": rows[2]["url"]},
        {"id": None, "description": "설명", "url": "틀린 주소"},
    ])
    assert response.status_code == 422

    db.expire_all()
    after = links_of(client, project)
    assert [r["id"] for r in after] == [r["id"] for r in rows]
    assert [r["description"] for r in after] == ["설명 1", "설명 2", "설명 3"]
    assert db.query(ProjectLink).filter_by(project_id=project).count() == 3


# =============================================================================
# 스코프 — 남의 프로젝트 링크는 만질 수 없다
# =============================================================================
def test_another_projects_link_id_is_422(db, client, published, project):
    other = client.post(
        f"{API}/projects",
        json={"maker_id": 8, "name": "다른 프로젝트", "template_id": published.wp.id},
    ).json()["project"]["id"]
    stolen = seed(client, other, count=1)[0]

    response = save(client, project, [
        {"id": stolen["id"], "description": "훔친 링크", "url": "https://example.com"}
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "LINK_OUT_OF_SCOPE"

    # 남의 링크는 그대로 있어야 한다.
    db.expire_all()
    assert links_of(client, other)[0]["description"] == "설명 1"


def test_an_unknown_link_id_is_422(client, project):
    response = save(client, project, [
        {"id": 999999, "description": "설명", "url": "https://example.com"}
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "LINK_OUT_OF_SCOPE"


def test_the_same_link_twice_is_422(client, project):
    rows = seed(client, project, count=1)
    response = save(client, project, [
        {"id": rows[0]["id"], "description": "하나", "url": "https://a.example.com"},
        {"id": rows[0]["id"], "description": "둘", "url": "https://b.example.com"},
    ])
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "LINK_DUPLICATED"


def test_links_are_scoped_to_one_project(client, published, project):
    other = client.post(
        f"{API}/projects",
        json={"maker_id": 8, "name": "다른 프로젝트", "template_id": published.wp.id},
    ).json()["project"]["id"]

    seed(client, project, count=2)
    assert links_of(client, other) == []

    seed(client, other, count=1)
    assert len(links_of(client, project)) == 2


def test_an_unknown_project_is_404(client):
    assert client.get(f"{API}/projects/999999/links").status_code == 404
    assert client.put(f"{API}/projects/999999/links", json={"links": []}).status_code == 404


# =============================================================================
# 다른 화면과 섞이지 않는다
# =============================================================================
def test_links_are_not_the_document_settings(client, project):
    """§0.5.5 와 §0.5-4 는 별개다 — 한쪽을 저장해도 다른 쪽이 바뀌지 않는다."""
    seed(client, project, count=2)

    documents = client.get(f"{API}/projects/{project}/documents").json()["documents"]
    assert len(documents) == 2                      # board 픽스처의 전역 문서 ①②
    assert all(d["link_url"] is None for d in documents)
    assert len(links_of(client, project)) == 2


def test_links_do_not_leak_into_the_overview_item_payload(client, project):
    """미니맵 셀은 축약형이다 — 링크가 거기 실리면 응답이 부풀어 오른다."""
    seed(client, project)
    makers = client.get(f"{API}/projects/overview").json()["makers"]
    entry = makers[0]["projects"][0]
    assert "links" not in entry
