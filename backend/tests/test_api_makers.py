"""설비사 설정과 전체 현황 그룹핑 — plan.md §0.6.

무게중심은 **표시 규칙**이다 (§0.6-1). 설정 행이 있으면 그 값, 없으면 "active
프로젝트가 있으면 표시". 세 분기(행=1 / 행=0 / 무행)와 프로젝트 유무의 조합을
전부 확인한다 — 조합 하나가 틀리면 사용자에게는 "체크했는데 안 나온다" 로 보이고,
그건 설정 화면이 고장 난 것처럼 읽힌다.
"""

from __future__ import annotations

import pytest

from app.models import Item, MakerSetting, Phase, Template, Version, VersionStatus

pytestmark = pytest.mark.db

API = "/api/v1"


class FakeResolver:
    """호스트 구현 대역. `list_makers` 까지 갖춘 최신 포트."""

    def __init__(self, names: dict[int, str]):
        self.names = names
        self.list_calls = 0

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        return {i: self.names[i] for i in maker_ids if i in self.names}

    def exists(self, maker_id: int) -> bool:
        return maker_id in self.names

    def list_makers(self) -> list[tuple[int, str]]:
        self.list_calls += 1
        return sorted(self.names.items())


class LegacyResolver:
    """`list_makers` 가 **없는** 구현 — §0.6 이전 계약에 맞춘 호스트."""

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        return {i: f"구형 {i}" for i in maker_ids}

    def exists(self, maker_id: int) -> bool:
        return True


class BrokenResolver:
    def resolve(self, maker_ids):
        raise RuntimeError("호스트 장애")

    def exists(self, maker_id):
        raise RuntimeError("호스트 장애")

    def list_makers(self):
        raise RuntimeError("호스트 장애")


@pytest.fixture
def template(db):
    """프로젝트를 만들 수 있는 최소 템플릿 — 발행본 + 행 1개."""
    entity = Template(code="T", name="템플릿", phase_start_no=0)
    db.add(entity)
    db.flush()
    phase = Phase(template_id=entity.id, name="P0", seq_no=0)
    db.add(phase)
    db.flush()
    version = Version(
        template_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED, phase_start_no=0
    )
    db.add(version)
    db.flush()
    db.add(Item(version_id=version.id, sort_order=1, phase_id=phase.id, title="행"))
    db.commit()
    return entity


def make_project(client, template, *, maker_id, name="프로젝트"):
    response = client.post(
        f"{API}/projects", json={"maker_id": maker_id, "name": name, "template_id": template.id}
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]["id"]


def makers_of(client):
    response = client.get(f"{API}/makers")
    assert response.status_code == 200, response.text
    return {m["maker_id"]: m for m in response.json()["makers"]}


def overview_of(client):
    response = client.get(f"{API}/projects/overview")
    assert response.status_code == 200, response.text
    return response.json()["makers"]


# =============================================================================
# 표시 규칙 (§0.6-1) — 3분기 × 프로젝트 유무
# =============================================================================
def test_without_a_setting_visibility_follows_whether_projects_exist(db, make_client, template):
    """무설정 기본값. 설치 직후 전체 현황이 비지 않게 하는 규칙이다."""
    client = make_client(maker_resolver=FakeResolver({1: "가", 2: "나"}))
    make_project(client, template, maker_id=1)

    rows = makers_of(client)
    assert rows[1]["explicit"] is False and rows[1]["has_projects"] is True
    assert rows[1]["show_in_overview"] is True
    assert rows[2]["explicit"] is False and rows[2]["has_projects"] is False
    assert rows[2]["show_in_overview"] is False

    assert [m["maker_id"] for m in overview_of(client)] == [1]


def test_an_explicit_check_shows_a_maker_with_no_projects(make_client, template):
    """체크한 설비사는 프로젝트 0개여도 섹션이 나온다 — 거기에 추가해야 하니까."""
    client = make_client(maker_resolver=FakeResolver({1: "가", 2: "나"}))

    assert client.put(
        f"{API}/makers/settings", json={"settings": [{"maker_id": 2, "show_in_overview": True}]}
    ).status_code == 200

    rows = makers_of(client)
    assert rows[2]["explicit"] is True and rows[2]["has_projects"] is False
    assert rows[2]["show_in_overview"] is True

    sections = overview_of(client)
    assert [m["maker_id"] for m in sections] == [2]
    assert sections[0]["projects"] == []


def test_an_explicit_uncheck_hides_a_maker_that_has_projects(make_client, template):
    """반대 방향. 프로젝트가 있어도 체크를 풀면 숨는다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    make_project(client, template, maker_id=1)

    assert client.put(
        f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": False}]}
    ).status_code == 200

    rows = makers_of(client)
    assert rows[1]["explicit"] is True and rows[1]["has_projects"] is True
    assert rows[1]["show_in_overview"] is False
    assert overview_of(client) == []


def test_deactivating_the_last_project_turns_an_unset_maker_off(make_client, template):
    """무설정의 유효값은 **파생값**이라 프로젝트가 사라지면 따라 꺼진다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    project_id = make_project(client, template, maker_id=1)

    assert makers_of(client)[1]["show_in_overview"] is True
    assert client.delete(f"{API}/projects/{project_id}").status_code == 200

    rows = makers_of(client)
    assert rows[1]["has_projects"] is False and rows[1]["show_in_overview"] is False
    assert overview_of(client) == []


def test_an_explicit_check_survives_losing_every_project(make_client, template):
    """명시 설정은 파생값과 달리 프로젝트 유무에 흔들리지 않는다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    project_id = make_project(client, template, maker_id=1)
    client.put(f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": True}]})

    client.delete(f"{API}/projects/{project_id}")

    assert makers_of(client)[1]["show_in_overview"] is True
    assert [m["maker_id"] for m in overview_of(client)] == [1]


# =============================================================================
# 업서트
# =============================================================================
def test_settings_are_created_then_updated_in_place(db, make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))

    client.put(f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": True}]})
    client.put(f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": False}]})

    assert db.query(MakerSetting).filter_by(maker_id=1).count() == 1
    assert makers_of(client)[1]["show_in_overview"] is False


def test_a_partial_save_leaves_other_makers_alone(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가", 2: "나", 3: "다"}))
    client.put(
        f"{API}/makers/settings",
        json={"settings": [
            {"maker_id": 1, "show_in_overview": True},
            {"maker_id": 2, "show_in_overview": True},
        ]},
    )

    client.put(f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": False}]})

    rows = makers_of(client)
    assert rows[1]["show_in_overview"] is False
    assert rows[2]["show_in_overview"] is True and rows[2]["explicit"] is True
    assert rows[3]["explicit"] is False


def test_the_save_response_is_the_refreshed_table(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가", 2: "나"}))
    response = client.put(
        f"{API}/makers/settings", json={"settings": [{"maker_id": 2, "show_in_overview": True}]}
    )
    assert response.status_code == 200, response.text

    rows = {m["maker_id"]: m for m in response.json()["makers"]}
    assert rows[2]["show_in_overview"] is True and rows[2]["explicit"] is True


def test_an_empty_save_changes_nothing(db, make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    assert client.put(f"{API}/makers/settings", json={"settings": []}).status_code == 200
    assert db.query(MakerSetting).count() == 0


def test_the_same_maker_twice_is_422(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    response = client.put(
        f"{API}/makers/settings",
        json={"settings": [
            {"maker_id": 1, "show_in_overview": True},
            {"maker_id": 1, "show_in_overview": False},
        ]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "MAKER_DUPLICATED"


def test_a_setting_for_an_unknown_maker_is_accepted(db, make_client, template):
    """존재 검증을 하지 않는 것은 의도다 — resolver 미주입 설치에서도 설정이
    가능해야 하기 때문이다. 고아 설정은 이름 없는 빈 섹션이 될 뿐이다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    response = client.put(
        f"{API}/makers/settings", json={"settings": [{"maker_id": 4242, "show_in_overview": True}]}
    )
    assert response.status_code == 200, response.text

    rows = makers_of(client)
    assert rows[4242]["name"] is None and rows[4242]["show_in_overview"] is True
    assert [m["maker_id"] for m in overview_of(client)] == [4242]


# =============================================================================
# resolver 유무
# =============================================================================
def test_the_maker_list_comes_from_the_resolver(make_client, template):
    """프로젝트가 하나도 없어도 설비사 전체가 표에 나와야 설정을 할 수 있다."""
    resolver = FakeResolver({1: "가", 2: "나", 3: "다"})
    client = make_client(maker_resolver=resolver)

    rows = makers_of(client)
    assert sorted(rows) == [1, 2, 3]
    assert rows[1]["name"] == "가"
    assert resolver.list_calls == 1


def test_without_a_resolver_the_table_falls_back_to_ids_in_use(client, template):
    """resolver 미주입은 정상 상태 — 전체 목록은 못 얻지만 쓰이는 id 는 안다."""
    make_project(client, template, maker_id=9)

    rows = makers_of(client)
    assert sorted(rows) == [9]
    assert rows[9]["name"] is None and rows[9]["show_in_overview"] is True

    sections = overview_of(client)
    assert [m["maker_id"] for m in sections] == [9]
    assert sections[0]["name"] is None


def test_without_a_resolver_and_without_projects_the_table_is_empty(db, client):
    assert makers_of(client) == {}
    assert overview_of(client) == []


def test_a_resolver_without_list_makers_does_not_break_the_screen(make_client, template):
    """§0.6 이전 계약에 맞춘 호스트 구현이 살아 있을 수 있다.

    `list_makers` 가 없다고 설정 화면이 500 을 내면 안 된다 — 전체 목록만 포기하고
    쓰이는 id 로 폴백한다. 이름은 `resolve()` 로 여전히 채워진다.
    """
    client = make_client(maker_resolver=LegacyResolver())
    make_project(client, template, maker_id=5)

    rows = makers_of(client)
    assert sorted(rows) == [5]
    assert rows[5]["name"] == "구형 5"
    assert [m["maker_id"] for m in overview_of(client)] == [5]


def test_a_failing_resolver_does_not_break_the_screen(make_client, client, template):
    """프로젝트를 만든 뒤 호스트 조회가 고장 난 상황 — 이름만 비고 화면은 산다."""
    make_project(client, template, maker_id=6)

    broken = make_client(maker_resolver=BrokenResolver())
    rows = makers_of(broken)
    assert sorted(rows) == [6]
    assert rows[6]["name"] is None
    assert [m["maker_id"] for m in overview_of(broken)] == [6]


def test_a_dangling_maker_id_keeps_its_projects_visible(make_client, client, template):
    """호스트에서 사라진 설비사라도 자기 프로젝트를 잃지 않는다 (§2.2).

    resolver 없는 클라이언트로 만든다 — resolver 가 있으면 `exists()` 가 생성
    자체를 막으므로(그것도 맞는 동작이다) 고아는 "나중에 호스트에서 사라진"
    경우로만 생긴다.
    """
    make_project(client, template, maker_id=1, name="정상 프로젝트")
    make_project(client, template, maker_id=777, name="고아 프로젝트")

    reader = make_client(maker_resolver=FakeResolver({1: "가"}))
    sections = {m["maker_id"]: m for m in overview_of(reader)}
    assert sorted(sections) == [1, 777]
    assert sections[1]["name"] == "가"
    assert sections[777]["name"] is None
    assert [p["name"] for p in sections[777]["projects"]] == ["고아 프로젝트"]


# =============================================================================
# 전체 현황 그룹핑 (§0.6-3)
# =============================================================================
def test_overview_groups_projects_under_their_maker(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가", 2: "나"}))
    make_project(client, template, maker_id=1, name="A")
    make_project(client, template, maker_id=2, name="B")
    make_project(client, template, maker_id=1, name="C")

    sections = {m["maker_id"]: m for m in overview_of(client)}
    assert sorted(sections) == [1, 2]
    assert [p["name"] for p in sections[1]["projects"]] == ["A", "C"]
    assert [p["name"] for p in sections[2]["projects"]] == ["B"]
    assert sections[1]["name"] == "가"


def test_the_project_shape_inside_a_section_is_unchanged(make_client, template):
    """§0.5-3 의 프로젝트 형태는 그대로다 — documents 포함."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    make_project(client, template, maker_id=1)

    project = overview_of(client)[0]["projects"][0]
    assert set(project) == {
        "id", "name", "maker_id", "maker_name", "counts", "items", "documents",
    }
    assert project["maker_name"] == "가"
    assert set(project["counts"]) == {"NOT_STARTED", "IN_PROGRESS", "DONE", "HOLD", "NA"}
    assert [i["no"] for i in project["items"]] == [1]


def test_overview_omits_inactive_projects_but_keeps_the_section(make_client, template):
    """프로젝트가 비활성화돼도 **명시적으로 켠** 설비사의 섹션은 남는다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    keep = make_project(client, template, maker_id=1, name="살아있음")
    drop = make_project(client, template, maker_id=1, name="비활성")
    client.put(f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": True}]})

    client.delete(f"{API}/projects/{drop}")

    sections = overview_of(client)
    assert [p["id"] for p in sections[0]["projects"]] == [keep]


def test_the_top_level_key_is_makers_not_projects(client):
    """§0.6-3 개편의 계약 자체. 예전 평면 배열로 되돌아가면 여기서 깨진다."""
    body = client.get(f"{API}/projects/overview").json()
    assert set(body) == {"makers"}


# =============================================================================
# 프로젝트명 수정 (§0.6-3)
# =============================================================================
def test_rename_changes_only_the_name(db, client, template):
    project_id = make_project(client, template, maker_id=1, name="옛 이름")
    before = client.get(f"{API}/projects/{project_id}").json()["project"]

    response = client.patch(f"{API}/projects/{project_id}", json={"name": "새 이름"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "새 이름"

    after = client.get(f"{API}/projects/{project_id}").json()["project"]
    assert after["phase_start_no"] == before["phase_start_no"]
    assert after["is_active"] == before["is_active"]
    assert after["source_version_id"] == before["source_version_id"]


def test_rename_shows_up_in_the_overview(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    project_id = make_project(client, template, maker_id=1, name="옛 이름")

    client.patch(f"{API}/projects/{project_id}", json={"name": "새 이름"})
    assert overview_of(client)[0]["projects"][0]["name"] == "새 이름"


def test_an_empty_rename_is_422(client, template):
    project_id = make_project(client, template, maker_id=1)
    assert client.patch(f"{API}/projects/{project_id}", json={"name": ""}).status_code == 422


def test_a_whitespace_only_rename_is_422(client, template):
    """`min_length=1` 만으로는 통과한다 — 저장되면 이름 없는 프로젝트가 된다."""
    project_id = make_project(client, template, maker_id=1)
    assert client.patch(f"{API}/projects/{project_id}", json={"name": "   "}).status_code == 422


def test_rename_trims_surrounding_whitespace(client, template):
    project_id = make_project(client, template, maker_id=1)
    response = client.patch(f"{API}/projects/{project_id}", json={"name": "  다듬힌 이름  "})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "다듬힌 이름"


def test_renaming_an_unknown_project_is_404(client):
    assert client.patch(f"{API}/projects/999999", json={"name": "x"}).status_code == 404


# =============================================================================
# 프로젝트 사용 여부 스위치 — 설비사 관리 화면
#
# 스위치는 `wp_projects.is_active` 를 쓴다. off 는 **전체 현황에서 감추기**이지
# 삭제가 아니며, 이 API 에는 실제 삭제 경로가 없다 (관리자용
# `db/delete_project.py` 뿐). 그래서 "꺼도 살아 있다" 와 "꺼도 다시 켤 수 있다" 를
# 둘 다 못박는다 — 후자가 무너지면 off 가 되돌릴 수 없는 조작이 된다.
# =============================================================================
def test_the_maker_row_lists_its_projects_including_the_switched_off_ones(make_client, template):
    """`has_projects` 는 활성 기준, `projects` 는 전부. 둘은 다른 질문의 답이다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    on = make_project(client, template, maker_id=1, name="켜짐")
    off = make_project(client, template, maker_id=1, name="꺼짐")

    assert client.put(
        f"{API}/makers/settings", json={"settings": [], "projects": [{"id": off, "is_active": False}]}
    ).status_code == 200

    row = makers_of(client)[1]
    assert [(p["id"], p["is_active"]) for p in row["projects"]] == [(on, True), (off, False)]
    assert row["has_projects"] is True


def test_switching_a_project_off_hides_it_from_the_overview_but_keeps_the_row(
    db, make_client, template
):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    keep = make_project(client, template, maker_id=1, name="유지")
    hide = make_project(client, template, maker_id=1, name="숨김")

    client.put(
        f"{API}/makers/settings", json={"settings": [], "projects": [{"id": hide, "is_active": False}]}
    )

    assert [p["id"] for p in overview_of(client)[0]["projects"]] == [keep]
    # 행도 항목도 그대로 살아 있다 — 감춘 것이지 지운 것이 아니다.
    detail = client.get(f"{API}/projects/{hide}")
    assert detail.status_code == 200
    assert detail.json()["project"]["is_active"] is False
    assert len(detail.json()["items"]) == 1


def test_switching_it_back_on_restores_it_unchanged(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    project_id = make_project(client, template, maker_id=1, name="왕복")

    client.put(
        f"{API}/makers/settings",
        json={"settings": [], "projects": [{"id": project_id, "is_active": False}]},
    )
    assert overview_of(client) == []

    client.put(
        f"{API}/makers/settings",
        json={"settings": [], "projects": [{"id": project_id, "is_active": True}]},
    )
    section = overview_of(client)[0]
    assert [(p["id"], p["name"]) for p in section["projects"]] == [(project_id, "왕복")]


def test_a_maker_whose_every_project_is_off_stays_in_the_table(client, template):
    """off 를 **되돌릴 수 있게** 하는 불변식.

    resolver 없이 만든다 — 그래야 설비사 목록의 유일한 출처가 "프로젝트가 쓰는
    maker_id" 가 되고, 그 목록이 활성만 세면 이 설비사가 통째로 사라진다.
    사라지면 스위치를 다시 켤 화면이 없어져 off 가 편도가 된다.
    """
    project_id = make_project(client, template, maker_id=9, name="유일")
    client.put(
        f"{API}/makers/settings",
        json={"settings": [], "projects": [{"id": project_id, "is_active": False}]},
    )

    row = makers_of(client)[9]
    assert row["has_projects"] is False and row["show_in_overview"] is False
    assert [(p["id"], p["is_active"]) for p in row["projects"]] == [(project_id, False)]
    # 그래도 전체 현황에는 안 나온다 — 표시 규칙은 여전히 활성 기준이다.
    assert overview_of(client) == []


def test_the_delete_endpoint_and_the_switch_are_the_same_column(client, template):
    """`DELETE /projects/{id}` 도 비활성화다. 두 경로가 갈리면 화면이 어긋난다."""
    project_id = make_project(client, template, maker_id=1)
    client.delete(f"{API}/projects/{project_id}")

    assert makers_of(client)[1]["projects"][0]["is_active"] is False


def test_an_unknown_project_id_is_422(make_client, template):
    """설비사 id 와 달리 프로젝트 id 는 우리 것이라 모른다고 넘길 이유가 없다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    response = client.put(
        f"{API}/makers/settings", json={"settings": [], "projects": [{"id": 999999, "is_active": False}]}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_the_same_project_twice_is_422(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    project_id = make_project(client, template, maker_id=1)
    response = client.put(
        f"{API}/makers/settings",
        json={"settings": [], "projects": [
            {"id": project_id, "is_active": False},
            {"id": project_id, "is_active": True},
        ]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PROJECT_DUPLICATED"


def test_a_rejected_project_takes_the_maker_settings_down_with_it(db, make_client, template):
    """**한 트랜잭션**이다. 화면의 저장 버튼 하나가 절반만 반영되면 안 된다."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    response = client.put(
        f"{API}/makers/settings",
        json={
            "settings": [{"maker_id": 1, "show_in_overview": True}],
            "projects": [{"id": 999999, "is_active": False}],
        },
    )
    assert response.status_code == 422, response.text
    assert db.query(MakerSetting).count() == 0


def test_an_omitted_projects_list_leaves_projects_alone(make_client, template):
    """빈 배열은 "건드리지 말라" 이지 "전부 끄라" 가 아니다 (§0.6 부분 목록 규칙)."""
    client = make_client(maker_resolver=FakeResolver({1: "가"}))
    project_id = make_project(client, template, maker_id=1)

    assert client.put(
        f"{API}/makers/settings", json={"settings": [{"maker_id": 1, "show_in_overview": True}]}
    ).status_code == 200

    assert makers_of(client)[1]["projects"] == [
        {"id": project_id, "name": "프로젝트", "is_active": True}
    ]


def test_switching_projects_does_not_touch_another_maker(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "가", 2: "나"}))
    mine = make_project(client, template, maker_id=1, name="내 것")
    theirs = make_project(client, template, maker_id=2, name="남의 것")

    client.put(
        f"{API}/makers/settings", json={"settings": [], "projects": [{"id": mine, "is_active": False}]}
    )

    rows = makers_of(client)
    assert rows[1]["projects"][0]["is_active"] is False
    assert rows[2]["projects"][0]["is_active"] is True
    assert [p["id"] for p in overview_of(client)[0]["projects"]] == [theirs]
