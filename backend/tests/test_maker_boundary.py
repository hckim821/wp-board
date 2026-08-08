"""설비사(Maker) 경계 — INTEGRATION.md §2.2, plan.md §0.1.

계약의 핵심은 "**미주입이 정상 상태**" 라는 것이다. resolver 가 없어도, 호스트에
없는 `maker_id` 를 갖고 있어도, resolver 구현이 터져도 **조회는 성공해야 한다.**

§0 이후 이 경계의 위치가 바뀌었다. 예전에는 `wp_work_packages.maker_id` 였는데,
템플릿이 중앙 기준 데이터가 되면서 **`wp_projects.maker_id` 한 곳으로 옮겨졌다.**
템플릿에는 설비사 개념이 아예 없다 — 그 사실 자체를 아래에서 검사한다.
"""

from __future__ import annotations

import pytest

from app.models import Item, Phase, Template, Version, VersionStatus

pytestmark = pytest.mark.db

API = "/api/v1"


class FakeResolver:
    """호스트 구현 대역. 아는 id 만 이름을 돌려준다."""

    def __init__(self, names: dict[int, str]):
        self.names = names
        self.resolve_calls: list[list[int]] = []

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        self.resolve_calls.append(list(maker_ids))
        return {i: self.names[i] for i in maker_ids if i in self.names}

    def exists(self, maker_id: int) -> bool:
        return maker_id in self.names


class BrokenResolver:
    def resolve(self, maker_ids):
        raise RuntimeError("호스트 설비사 조회 실패")

    def exists(self, maker_id):
        raise RuntimeError("호스트 설비사 조회 실패")


@pytest.fixture
def template(db):
    """프로젝트를 만들 수 있는 최소 템플릿 — 발행본 1개 + 행 1개."""
    entity = Template(code="T", name="템플릿", phase_start_no=0)
    db.add(entity)
    db.flush()

    phase = Phase(template_id=entity.id, name="P0", seq_no=0)
    db.add(phase)
    db.flush()

    version = Version(
        template_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        phase_start_no=0,
    )
    db.add(version)
    db.flush()
    db.add(Item(version_id=version.id, sort_order=1, phase_id=phase.id, title="t"))
    db.commit()
    return entity


@pytest.fixture
def projects(db, client, template):
    """설비사 1 이 둘, 설비사 2 가 하나 (1:N)."""
    for maker_id, name in ((1, "설비사1 프로젝트"), (2, "설비사2 프로젝트"), (1, "설비사1 두번째")):
        response = client.post(
            f"{API}/projects",
            json={"maker_id": maker_id, "name": name, "template_id": template.id},
        )
        assert response.status_code == 201, response.text


# =============================================================================
# resolver 미주입 — 정상 상태
# =============================================================================
def test_without_a_resolver_the_response_omits_the_name_and_still_works(client, projects):
    rows = client.get(f"{API}/projects").json()
    assert len(rows) == 3
    assert all(r["maker_name"] is None for r in rows)
    assert {r["maker_id"] for r in rows} == {1, 2}


def test_without_a_resolver_creation_is_not_blocked(client, template):
    """존재 검증은 resolver 가 있을 때만 한다. 없으면 통과시킨다."""
    response = client.post(
        f"{API}/projects",
        json={"maker_id": 424242, "name": "새 프로젝트", "template_id": template.id},
    )
    assert response.status_code == 201, response.text
    assert response.json()["project"]["maker_name"] is None


# =============================================================================
# resolver 주입
# =============================================================================
def test_an_injected_resolver_supplies_the_names(make_client, db, template, projects):
    resolver = FakeResolver({1: "설비사 A", 2: "설비사 B"})
    rows = make_client(maker_resolver=resolver).get(f"{API}/projects").json()
    assert {r["maker_id"]: r["maker_name"] for r in rows} == {1: "설비사 A", 2: "설비사 B"}


def test_the_resolver_is_asked_once_with_deduplicated_ids(make_client, projects):
    resolver = FakeResolver({1: "설비사 A", 2: "설비사 B"})
    make_client(maker_resolver=resolver).get(f"{API}/projects")
    assert resolver.resolve_calls == [[1, 2]]   # 프로젝트 3건이지만 조회 1회, id 중복 제거


def test_a_dangling_maker_id_does_not_break_the_read(make_client, projects):
    """물리 FK 가 없으므로 고아 참조는 생길 수 있다. 이름만 비우고 넘어간다."""
    resolver = FakeResolver({1: "설비사 A"})        # 2 는 호스트에 없음
    rows = make_client(maker_resolver=resolver).get(f"{API}/projects").json()
    assert len(rows) == 3
    assert {r["maker_id"]: r["maker_name"] for r in rows} == {1: "설비사 A", 2: None}


def test_a_failing_resolver_does_not_break_the_read(make_client, projects):
    """설비사 이름은 부가 정보다. 호스트 구현 장애가 프로젝트 조회를 막으면 안 된다."""
    response = make_client(maker_resolver=BrokenResolver()).get(f"{API}/projects")
    assert response.status_code == 200
    assert all(r["maker_name"] is None for r in response.json())


def test_an_injected_resolver_validates_the_maker_on_create(make_client, template):
    client = make_client(maker_resolver=FakeResolver({1: "설비사 A"}))

    ok = client.post(
        f"{API}/projects", json={"maker_id": 1, "name": "보드", "template_id": template.id}
    )
    assert ok.status_code == 201, ok.text

    bad = client.post(
        f"{API}/projects", json={"maker_id": 9, "name": "보드", "template_id": template.id}
    )
    assert bad.status_code == 400


# =============================================================================
# 설비사 1 : N 프로젝트
# =============================================================================
def test_one_maker_can_own_several_projects(client, projects):
    rows = client.get(f"{API}/projects", params={"maker_id": 1}).json()
    assert {r["name"] for r in rows} == {"설비사1 프로젝트", "설비사1 두번째"}


# =============================================================================
# 템플릿에는 설비사 개념이 없다 (plan.md §0.1)
# =============================================================================
def test_the_template_api_has_no_maker_concept(client, template):
    """템플릿 응답에 maker 필드가 없고, 만들 때도 받지 않는다.

    이 검사가 있어야 "예전 습관대로" maker_id 를 템플릿에 되돌려 놓는 변경이
    조용히 통과하지 않는다.
    """
    row = client.get(f"{API}/templates/{template.id}").json()
    assert "maker_id" not in row
    assert "maker_name" not in row

    # maker_id 를 실어 보내도 무시된다 — 스키마에 그런 필드가 없다.
    created = client.post(
        f"{API}/templates", json={"maker_id": 5, "code": "T2", "name": "두번째 템플릿"}
    )
    assert created.status_code == 201, created.text
    assert "maker_id" not in created.json()


def test_template_code_is_globally_unique(client):
    """설비사가 없어졌으므로 `UQ(maker_id, code)` 가 `UQ(code)` 가 되었다."""
    assert client.post(
        f"{API}/templates", json={"code": "SAME", "name": "템플릿1"}
    ).status_code == 201
    assert client.post(
        f"{API}/templates", json={"code": "SAME", "name": "템플릿2"}
    ).status_code == 400


def test_only_two_tables_carry_a_maker_id():
    """`maker_id` 를 가진 테이블이 **정확히 둘**인지 확인한다.

    이식 시 호스트가 바꿔야 할 지점의 개수를 고정하는 검사다 (INTEGRATION.md §2.1).
    §0.6 이전에는 `wp_projects` 하나였고, 호스트 `makers` 테이블에 컬럼을 더할 수
    없어 표시 설정을 `wp_maker_settings` 로 분리하면서 둘이 됐다. 더 늘어나면
    여기서 먼저 깨진다.
    """
    from app.models import Base

    carrying = sorted(
        name for name, table in Base.metadata.tables.items() if "maker_id" in table.columns
    )
    assert carrying == ["wp_maker_settings", "wp_projects"]
