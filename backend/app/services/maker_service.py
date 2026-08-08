"""설비사 설정 — plan.md §0.6.

이 모듈이 소유한 판단은 하나뿐이다: **이 설비사를 전체 현황에 보여줄 것인가.**

## 표시 규칙 (§0.6-1)

| 설정 행 | 유효값 |
|---|---|
| 있음 | `show_in_overview` 그대로 |
| 없음 | **active 프로젝트가 있으면 표시** |

무설정을 "숨김" 으로 두면 설치 직후 전체 현황이 텅 비고, 사용자는 화면이
고장 났다고 읽는다. 반대로 "표시" 로 두면 설정 화면에서 체크를 풀어도 다음
설비사가 추가될 때마다 다시 나타난다. 프로젝트 유무를 기본값으로 삼으면 두 문제가
동시에 사라지고, **체크 한 번으로 강제 표시·강제 숨김 양쪽이 가능**해진다 —
프로젝트 0개인 설비사를 켜 두는 것도, 프로젝트가 있는 설비사를 숨기는 것도 된다.

그래서 이 규칙은 **서버에 있어야 한다.** 클라이언트가 `explicit` 와 `has_projects`
를 보고 스스로 계산하면 설정 화면과 전체 현황이 각자 구현하게 되고, 둘이 갈리는
순간 "체크했는데 안 나온다" 가 된다.

## 설비사 목록의 출처

`MakerResolver.list_makers()` 다. resolver 가 없으면 빈 목록이고 (정상 상태),
그때는 **실제로 프로젝트가 참조하는 `maker_id`** 로 목록을 대신한다 — 이름 없는
설비사라도 자기 프로젝트를 볼 수 있어야 하기 때문이다. 설비사 테이블로 JOIN 하는
경로는 어느 쪽에도 없다 (INTEGRATION.md §2.1).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.exceptions import UnprocessableEntityError
from ..models import MakerSetting, Project
from ..ports.maker_resolver import MakerResolver, list_makers, resolve_names
from ..schemas.maker import (
    MakerProjectOut,
    MakerProjectVisibilityIn,
    MakerSettingSaveIn,
    MakerSummaryOut,
)


def settings_by_maker(session: Session) -> dict[int, MakerSetting]:
    return {row.maker_id: row for row in session.scalars(select(MakerSetting))}


def projects_by_maker(session: Session) -> dict[int, list[Project]]:
    """설비사 → 그 설비사의 프로젝트 전부. **비활성도 포함한다.**

    설정 화면 전용 조회다. 다른 경로는 `project_service.list_projects` 를 쓰고 그쪽
    기본값은 활성만인데, 여기서 같은 기본값을 쓰면 한 번 끈 프로젝트가 어느 화면에도
    나타나지 않아 다시 켤 방법이 사라진다.

    순서는 **id 순** — 이름순이 아니다. 전체 현황(`project_service.list_projects`)이
    id 순으로 그리므로, 같은 프로젝트가 두 화면에서 다른 자리에 있으면 사용자는
    같은 목록이라고 읽지 않는다.

    설비사 테이블로 JOIN 하지 않는다 — `maker_id` 로 묶기만 한다
    (INTEGRATION.md §2.1).
    """
    grouped: dict[int, list[Project]] = {}
    for project in session.scalars(select(Project).order_by(Project.id)):
        grouped.setdefault(project.maker_id, []).append(project)
    return grouped


def maker_ids_with_active_projects(session: Session) -> set[int]:
    """**active 프로젝트를 가진** 설비사 id. 표시 규칙의 기본값 입력이다."""
    return set(
        session.scalars(
            select(Project.maker_id).where(Project.is_active == 1).distinct()
        )
    )


def effective_visibility(setting: MakerSetting | None, has_projects: bool) -> bool:
    """§0.6-1 의 표시 규칙 — **이 함수가 그 규칙의 유일한 정본이다.**"""
    if setting is not None:
        return bool(setting.show_in_overview)
    return has_projects


def known_makers(
    session: Session, resolver: MakerResolver | None
) -> list[tuple[int, str | None]]:
    """이 화면이 알아야 할 설비사 전체 `(id, 이름|None)`.

    셋을 합집합한다 — 어느 하나만 봐도 빠지는 설비사가 생긴다.

    * **resolver 목록** — 프로젝트가 아직 없는 설비사는 여기에만 있다.
    * **프로젝트의 `maker_id`** — 호스트에서 지워졌거나 resolver 가 모르는
      고아 참조도 자기 프로젝트를 잃지 않아야 한다 (§2.2). **비활성 프로젝트도
      센다**: 프로젝트를 전부 꺼 둔 설비사가 목록에서 빠지면 그 스위치를 다시 켤
      화면이 사라져 off 가 사실상 되돌릴 수 없는 조작이 된다. 전체 현황에는
      영향이 없다 — 그쪽 판단은 `effective_visibility` 가 `has_projects`(활성
      기준)로 따로 내린다.
    * **설정 행의 `maker_id`** — 체크해 둔 설비사는 프로젝트가 0개여도 남아야
      한다. 설정만 남고 목록에서 빠지면 체크가 조용히 무효가 된다.

    이름을 못 찾은 설비사는 `None` 으로 둔다. 폴백 문구(`설비사 #id`)는 화면이
    만든다 — 서버가 채워 내려주면 "이름을 모른다" 는 사실이 응답에서 사라진다.
    """
    names: dict[int, str | None] = {}
    for maker_id, name in list_makers(resolver):
        names.setdefault(maker_id, name)

    extra = set(session.scalars(select(Project.maker_id).distinct())) | set(
        session.scalars(select(MakerSetting.maker_id))
    )
    missing = sorted(extra - set(names))
    if missing:
        # resolver 가 목록은 못 주어도 개별 이름은 알 수 있다 (구현이 다른 경로).
        resolved = resolve_names(resolver, missing)
        for maker_id in missing:
            names[maker_id] = resolved.get(maker_id)

    return sorted(names.items(), key=lambda pair: (pair[1] is None, pair[1] or "", pair[0]))


def list_maker_summaries(
    session: Session, resolver: MakerResolver | None
) -> list[MakerSummaryOut]:
    """`GET /makers` — 설정 화면이 그리는 표 그대로.

    `show_in_overview`(유효값)와 `explicit`(설정 행 존재)를 **둘 다** 내려준다.
    화면이 "체크됨" 과 "체크하지 않았는데 프로젝트가 있어서 켜진 것" 을 구분해
    보여줘야 하기 때문이다 (§0.6-4).
    """
    settings = settings_by_maker(session)
    with_projects = maker_ids_with_active_projects(session)
    projects = projects_by_maker(session)

    return [
        MakerSummaryOut(
            maker_id=maker_id,
            name=name,
            show_in_overview=effective_visibility(
                settings.get(maker_id), maker_id in with_projects
            ),
            explicit=maker_id in settings,
            has_projects=maker_id in with_projects,
            projects=[
                MakerProjectOut(id=p.id, name=p.name, is_active=bool(p.is_active))
                for p in projects.get(maker_id, [])
            ],
        )
        for maker_id, name in known_makers(session, resolver)
    ]


def save_settings(
    session: Session, payload: list[MakerSettingSaveIn]
) -> list[MakerSetting]:
    """업서트. **한 트랜잭션이고, 목록에 없는 설비사는 손대지 않는다.**

    `maker_id` 의 존재를 검증하지 않는 것은 의도다. 호스트 설비사 테이블은 우리
    것이 아니고 resolver 는 미주입이 정상 상태이므로, "호스트에 있는 id 인가" 를
    저장의 전제로 걸면 resolver 없는 설치에서 설정 자체가 불가능해진다. 고아 설정
    행은 조회를 깨뜨리지 않는다 — 이름이 비고 프로젝트가 0개인 섹션이 될 뿐이다.
    """
    seen: set[int] = set()
    duplicated: set[int] = set()
    for entry in payload:
        if entry.maker_id in seen:
            duplicated.add(entry.maker_id)
        seen.add(entry.maker_id)
    if duplicated:
        raise UnprocessableEntityError(
            f"같은 설비사가 두 번 들어 있습니다: {sorted(duplicated)}",
            code="MAKER_DUPLICATED",
            detail={"maker_ids": sorted(duplicated)},
        )

    existing = settings_by_maker(session)
    for entry in payload:
        row = existing.get(entry.maker_id)
        if row is None:
            row = MakerSetting(maker_id=entry.maker_id)
            session.add(row)
            existing[entry.maker_id] = row
        row.show_in_overview = 1 if entry.show_in_overview else 0

    session.flush()
    return list(existing.values())


def save_project_visibility(
    session: Session, payload: list[MakerProjectVisibilityIn]
) -> list[Project]:
    """프로젝트 표시 on/off 저장 — **행을 지우지 않는다.**

    `wp_projects.is_active` 만 바꾼다. 끈 프로젝트는 전체 현황에서 빠지지만 항목·
    상태·완료일은 그대로 남아 있고, 다시 켜면 그대로 돌아온다. 실제 삭제는
    UI 에 없으며 관리자가 `db/delete_project.py` 를 직접 실행할 때만 일어난다.

    설비사 id 와 달리 **프로젝트 id 는 검증한다.** 프로젝트는 우리 테이블이므로
    "호스트에 있을지도 모른다" 는 변명이 성립하지 않는다 — 없는 id 를 조용히
    넘기면 화면은 저장됐다고 표시하고 값은 아무 데도 남지 않는다.
    """
    seen: set[int] = set()
    duplicated: set[int] = set()
    for entry in payload:
        if entry.id in seen:
            duplicated.add(entry.id)
        seen.add(entry.id)
    if duplicated:
        raise UnprocessableEntityError(
            f"같은 프로젝트가 두 번 들어 있습니다: {sorted(duplicated)}",
            code="PROJECT_DUPLICATED",
            detail={"project_ids": sorted(duplicated)},
        )
    if not seen:
        return []

    rows = {
        project.id: project
        for project in session.scalars(select(Project).where(Project.id.in_(seen)))
    }
    missing = sorted(seen - set(rows))
    if missing:
        raise UnprocessableEntityError(
            f"없는 프로젝트입니다: {missing}",
            code="PROJECT_NOT_FOUND",
            detail={"project_ids": missing},
        )

    for entry in payload:
        rows[entry.id].is_active = 1 if entry.is_active else 0

    session.flush()
    return list(rows.values())
