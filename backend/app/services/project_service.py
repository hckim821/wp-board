"""프로젝트 — plan.md §0.1.

프로젝트는 **발행된 템플릿 버전의 스냅샷**이다. 이 모듈의 일은 두 가지뿐이다.

1. **생성 = deep copy** — 항목·phase·milestone·owner 를 프로젝트 로컬 테이블로
   통째로 복제한다. 한 트랜잭션이다. 부분 복제된 프로젝트는 존재할 수 없어야 한다.
2. **보드 제공** — 그 뒤의 모든 편집은 `item_service` 가 `Board` 를 통해 한다.
   템플릿과 같은 구현이다.

## 없는 것

버전, draft, 발행, 폐기, V1~V14 차단 검증 — 전부 없다 (plan.md §0.1 표).
프로젝트는 생성이 곧 확정이고 이후 직접 편집한다. 그래서

* 쓰기 경로에 `lock_editable_version` 같은 상태 관문이 없다. 상태가 하나뿐이다.
* 회색 행이 남아 있어도 된다 (§0.2-7). 잡아 줄 발행 시점이 없기 때문이다.
* 저장은 참조 무결성만 본다.

## 전파하지 않는다

템플릿이 재발행되어도 기존 프로젝트는 바뀌지 않는다. 그래서 이 모듈에는 "템플릿
변경을 프로젝트에 반영" 하는 함수가 없다 — 있으면 스냅샷이 아니게 된다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.exceptions import BadRequestError, NotFoundError
from ..models import (
    Project,
    ProjectDocument,
    ProjectItem,
    ProjectItemDocument,
    ProjectItemOwner,
    ProjectMilestone,
    ProjectOwner,
    ProjectPhase,
    Version,
    VersionStatus,
)
from ..models.base import ItemOrigin, ItemStatus
from ..ports.maker_resolver import MakerResolver
from ..schemas.project import (
    OverviewDocumentOut,
    OverviewItemOut,
    OverviewMakerOut,
    OverviewProjectOut,
    StatusCounts,
)
from .board import PROJECT_BOARD, Board
from .document_numbering import display_numbers
from .renumber_service import renumber
from . import item_service, maker_service, project_document_service, version_service


# =============================================================================
# 조회 / 보드
# =============================================================================
def get_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"프로젝트 {project_id} 을(를) 찾을 수 없습니다.")
    return project


def board_of(project: Project) -> Board:
    """프로젝트를 **보드**로 감싼다.

    `scope_id` 와 `master_scope_id` 가 둘 다 프로젝트 id 다 — 행도 기준정보도
    프로젝트에 직접 매달려 있기 때문이다 (템플릿 쪽은 행이 버전에, 기준정보가
    템플릿에 매달려 둘이 다르다).

    `sync_master_seq` 는 항상 참이다. 버전이 없어 "읽기 전용 상태" 자체가 없으므로,
    번호를 보류할 이유가 없다.
    """
    return Board(
        spec=PROJECT_BOARD,
        scope_id=project.id,
        master_scope_id=project.id,
        phase_start_no=project.phase_start_no,
        sync_master_seq=True,
    )


def source_version_numbers(session: Session, projects: list[Project]) -> dict[int, int]:
    """`project.id` → 원본 버전의 `version_number`.

    **찾지 못한 프로젝트는 결과에서 빠진다** (예외가 아니다). `source_version_id`
    에는 물리 FK 가 없어 — 원본이 지워져도 출처 이력은 남겨야 하므로 일부러
    걸지 않았다 — 고아 참조가 정상적으로 존재할 수 있고, 그때 헤더의 버전 번호만
    비면 될 뿐 프로젝트 조회가 깨지면 안 된다. `MakerResolver.resolve` 가 모르는
    id 를 결과에서 빼는 것과 같은 규칙이다.

    프로젝트마다 묻지 않고 `IN` 하나로 읽는다 — 목록 화면이 프로젝트 수만큼
    쿼리를 내지 않게.
    """
    version_ids = {p.source_version_id for p in projects if p.source_version_id is not None}
    if not version_ids:
        return {}

    numbers = {
        row.id: row.version_number
        for row in session.execute(
            select(Version.id, Version.version_number).where(Version.id.in_(version_ids))
        )
    }
    return {
        p.id: numbers[p.source_version_id]
        for p in projects
        if p.source_version_id in numbers
    }


def list_projects(
    session: Session, *, maker_id: int | None = None, include_inactive: bool = False
) -> list[Project]:
    stmt = select(Project)
    if maker_id is not None:
        stmt = stmt.where(Project.maker_id == maker_id)
    if not include_inactive:
        stmt = stmt.where(Project.is_active == 1)
    return list(session.scalars(stmt.order_by(Project.id)))


# =============================================================================
# 전체 현황 (plan.md §0.5-3)
# =============================================================================
def overview(
    session: Session, resolver: MakerResolver | None = None
) -> list[OverviewMakerOut]:
    """전체 현황 — **설비사 섹션**으로 묶어 돌려준다 (plan.md §0.6-3).

    표시 규칙(§0.6-1)과 그룹핑을 **서버가** 수행한다. 클라이언트가 하면 설정
    화면과 두 벌이 되고, 둘이 갈리는 순간 "체크했는데 안 나온다" 가 된다.

    설비사 목록은 `maker_service.known_makers` 가 만든다 — resolver 목록 ∪
    프로젝트가 실제로 쓰는 id ∪ 설정 행. resolver 가 없어도 프로젝트가 있는
    설비사는 전부 나오고, 이름만 `null` 이 된다.

    **프로젝트 0개인 섹션이 나올 수 있다** — 설정에서 명시적으로 켜 둔 경우다.
    """
    visible: list[tuple[int, str | None]] = []
    settings = maker_service.settings_by_maker(session)
    with_projects = maker_service.maker_ids_with_active_projects(session)
    for maker_id, name in maker_service.known_makers(session, resolver):
        if maker_service.effective_visibility(
            settings.get(maker_id), maker_id in with_projects
        ):
            visible.append((maker_id, name))

    grouped = _project_summaries(session, [m for m, _ in visible])
    return [
        OverviewMakerOut(maker_id=maker_id, name=name, projects=grouped.get(maker_id, []))
        for maker_id, name in visible
    ]


def _project_summaries(
    session: Session, maker_ids: list[int]
) -> dict[int, list[OverviewProjectOut]]:
    """활성 프로젝트를 설비사별로 묶어 요약한다 — 상태 집계 + 미니맵 + 문서.

    **읽기 전용이다.** 그리드 경로와 달리 `renumber_and_persist` 를 부르지
    않는다. 순수 함수 `renumber()` 만 써서 표시 번호를 파생하므로, 관망 화면을
    열었다는 이유로 기준정보의 `seq_no` 나 `sort_order` 가 바뀌는 일이 없다.
    (프로젝트 보드는 `sync_master_seq=True` 라, 무심코 보드 경로를 재사용했다면
    조회가 곧 쓰기가 됐을 것이다.)

    행은 **프로젝트마다 한 번씩이 아니라 한 방에** 읽는다. 프로젝트 수만큼
    쿼리가 늘면 설비사가 늘수록 이 화면만 느려진다.

    설비사 이름은 여기서 채우지 않는다 — 이름은 포트가 주고, 이 함수는
    `maker_id` 로 묶기만 한다 (INTEGRATION.md §2.1: 설비사 테이블 JOIN 금지).
    """
    projects = [p for p in list_projects(session) if p.maker_id in set(maker_ids)]
    if not projects:
        return {}

    project_ids = [p.id for p in projects]
    rows = session.scalars(
        select(ProjectItem)
        .where(ProjectItem.project_id.in_(project_ids))
        .order_by(ProjectItem.project_id, ProjectItem.sort_order, ProjectItem.id)
        # 팝오버가 Owner 이름을 쓴다 (§0.5-3). `selectinload` 가 없으면 행마다
        # 연관 조회가 나가 이 화면만 항목 수에 비례해 느려진다.
        .options(selectinload(ProjectItem.owners))
    )
    by_project: dict[int, list[ProjectItem]] = {p.id: [] for p in projects}
    for item in rows:
        by_project[item.project_id].append(item)

    # Owner 는 프로젝트 로컬 사본이라 프로젝트마다 id 가 다르다. 이름만 쓰므로
    # id → 이름 표 하나로 충분하고, 쿼리도 한 번이면 된다.
    owner_names = {
        owner.id: owner.name
        for owner in session.scalars(
            select(ProjectOwner).where(ProjectOwner.project_id.in_(project_ids))
        )
    }

    # 문서 설정도 프로젝트마다가 아니라 한 번에 (§0.5-4). 저장된 행이 없는
    # 프로젝트는 기본값(사용=1)이라 활성 문서가 전부 들어온다.
    documents = project_document_service.by_project(session, [p.id for p in projects])
    document_numbers = {pid: display_numbers(rows) for pid, rows in documents.items()}

    result: dict[int, list[OverviewProjectOut]] = {}
    for project in projects:
        items = by_project[project.id]
        numbering = renumber(
            item_service.to_row_refs(items), phase_start_no=project.phase_start_no
        )

        tally = {status.value: 0 for status in ItemStatus}
        cells: list[OverviewItemOut] = []
        for item, row in zip(items, numbering.rows):
            tally[ItemStatus(item.status).value] += 1
            cells.append(
                OverviewItemOut(
                    no=row.sort_order,
                    status=item.status,
                    phase_seq=row.phase_no,
                    milestone_seq=row.milestone_no,
                    dash_label=item.dash_label,
                    title=item.title,
                    deliverable=item.deliverable,
                    # 기준정보에서 사라진 Owner 는 조용히 건너뛴다 — 그리드의
                    # `build_item_views` 와 같은 규칙이다.
                    owners=[
                        owner_names[o.owner_id]
                        for o in item.owners
                        if o.owner_id in owner_names
                    ],
                )
            )

        result.setdefault(project.maker_id, []).append(
            OverviewProjectOut(
                id=project.id,
                name=project.name,
                maker_id=project.maker_id,
                counts=StatusCounts(**tally),
                items=cells,
                # **사용 중인 것만.** 안 쓰는 문서는 이 화면의 ④ 구획에 자리를
                # 차지할 이유가 없다 (§0.5-3b).
                # 사용 중인 것만 담고, 번호도 그것만 세어 매긴다 (§0.5.10) —
                # 그래서 이 배열의 `no` 는 언제나 1..N 연속이다.
                documents=[
                    OverviewDocumentOut(
                        id=d.id,
                        no=document_numbers[project.id][d.id],
                        name=d.name,
                        doc_status=d.doc_status,
                        link_url=d.link_url,
                    )
                    for d in documents[project.id]
                    if d.is_used
                ],
            )
        )
    return result


# =============================================================================
# 생성 — deep copy
# =============================================================================
def _source_version(
    session: Session, template_id: int | None, template_version_id: int | None
) -> Version:
    """복제 원본 버전을 고른다.

    `template_version_id` 를 주면 그것을, 아니면 템플릿의 현재 PUBLISHED 를 쓴다.
    **발행되지 않은 버전에서는 만들 수 없다** — DRAFT 는 아직 확정되지 않은
    작업본이고, 그것을 스냅샷으로 굳히면 "검증을 통과한 기준" 이라는 발행의 의미가
    사라진다.
    """
    if template_version_id is not None:
        version = session.get(Version, template_version_id)
        if version is None:
            raise NotFoundError(f"템플릿 버전 {template_version_id} 을(를) 찾을 수 없습니다.")
        if template_id is not None and version.template_id != template_id:
            raise BadRequestError(
                f"버전 {template_version_id} 은(는) 템플릿 {template_id} 의 것이 아닙니다."
            )
        if version.status == VersionStatus.DRAFT:
            raise BadRequestError(
                "DRAFT 버전으로는 프로젝트를 만들 수 없습니다. 먼저 발행하세요."
            )
        return version

    if template_id is None:
        raise BadRequestError("template_id 또는 template_version_id 중 하나는 필요합니다.")

    version_service.get_template(session, template_id)
    published = version_service.find_by_status(session, template_id, VersionStatus.PUBLISHED)
    if published is None:
        raise BadRequestError(
            f"템플릿 {template_id} 에 발행된 버전이 없습니다. 발행 후 프로젝트를 만들 수 있습니다."
        )
    return published


def create_project(
    session: Session,
    *,
    maker_id: int,
    name: str,
    template_id: int | None = None,
    template_version_id: int | None = None,
    description: str | None = None,
    created_by: str | None = None,
) -> Project:
    """발행된 템플릿 버전 하나를 골라 **전부 복제**한다 (plan.md §0.1).

    복제 대상: 항목 + N:M 연관 + phase/milestone/owner/**문서** + `phase_start_no`.
    §0.5.10 이후로 복제하지 않는 것은 없다 — 문서가 마지막 예외였다.

    표시 번호가 흔들리지 않도록 `phase_start_no` 는 **원본 버전의 실효값**을
    스냅샷한다 (발행 버전은 자기 스냅샷을, 그것이 없으면 템플릿의 현재 값을 쓴다).
    나중에 템플릿의 값을 바꿔도 이미 만들어진 프로젝트의 번호는 그대로다.
    """
    source = _source_version(session, template_id, template_version_id)

    project = Project(
        maker_id=maker_id,
        name=name,
        description=description,
        source_template_id=source.template_id,
        source_version_id=source.id,
        phase_start_no=version_service.effective_phase_start_no(session, source),
        created_by=created_by,
    )
    session.add(project)
    session.flush()

    source_board = version_service.board_of(session, source)

    # 기준정보를 먼저 복제하고 **원본 id → 사본 id** 표를 만든다. 행이 그 표를 통해
    # 자기 로컬 phase/milestone/owner 를 가리킨다.
    phase_map: dict[int, int] = {}
    for src in master_source(session, source_board, "phase"):
        copy = ProjectPhase(
            project_id=project.id, name=src.name, seq_no=src.seq_no,
            is_active=src.is_active, source_phase_id=src.id,
        )
        session.add(copy)
        session.flush()
        phase_map[src.id] = copy.id

    milestone_map: dict[int, int] = {}
    for src in master_source(session, source_board, "milestone"):
        copy = ProjectMilestone(
            project_id=project.id,
            phase_id=phase_map[src.phase_id],
            name=src.name,
            seq_no=src.seq_no,
            is_active=src.is_active,
            source_milestone_id=src.id,
        )
        session.add(copy)
        session.flush()
        milestone_map[src.id] = copy.id

    owner_map: dict[int, int] = {}
    for src in master_source(session, source_board, "owner"):
        copy = ProjectOwner(
            project_id=project.id, name=src.name, sort_order=src.sort_order,
            is_active=src.is_active, source_owner_id=src.id,
        )
        session.add(copy)
        session.flush()
        owner_map[src.id] = copy.id

    # **문서도 복제한다** (§0.5.10). 예전에는 전역이라 유일한 예외였다.
    document_map: dict[int, int] = {}
    for src in master_source(session, source_board, "document"):
        copy = ProjectDocument(
            project_id=project.id, name=src.name, sort_order=src.sort_order,
            is_used=1, link_url=None,
        )
        session.add(copy)
        session.flush()
        document_map[src.id] = copy.id

    for src in item_service.load_ordered_items(session, source_board):
        copy = ProjectItem(
            project_id=project.id,
            sort_order=src.sort_order,
            phase_id=phase_map.get(src.phase_id) if src.phase_id else None,
            milestone_id=milestone_map.get(src.milestone_id) if src.milestone_id else None,
            title=src.title,
            deliverable=src.deliverable,
            dash_label=src.dash_label,
            gate_code=src.gate_code,
            status=src.status,
            completion_date=src.completion_date,
            # 프로젝트 입장에서 템플릿에서 온 행은 전부 "물려받은" 행이다.
            origin=ItemOrigin.INHERITED,
            source_item_id=src.id,
        )
        # 문서는 전역이므로 id 를 그대로 쓴다. Owner 는 로컬 사본으로 매핑한다.
        copy.documents = [
            ProjectItemDocument(
                project_document_id=document_map[d.template_document_id], sort_order=d.sort_order
            )
            for d in src.documents
            if d.template_document_id in document_map
        ]
        copy.owners = [
            ProjectItemOwner(owner_id=owner_map[o.owner_id], sort_order=o.sort_order)
            for o in src.owners
            if o.owner_id in owner_map
        ]
        session.add(copy)

    session.flush()
    return project


def master_source(session: Session, board: Board, kind: str) -> list:
    """복제 원본이 될 기준정보를 정렬된 순서로 읽는다."""
    spec = board.spec
    model = {
        "phase": spec.phase_cls, "milestone": spec.milestone_cls,
        "owner": spec.owner_cls, "document": spec.document_cls,
    }[kind]
    stmt = select(model).where(spec.master_scope(model) == board.master_scope_id)
    # 정렬 키는 kind 마다 다르다. dict 로 한 번에 만들면 Phase 에 없는 `phase_id`
    # 까지 즉시 평가되어 AttributeError 가 난다.
    if kind == "milestone":
        order = (model.phase_id, model.seq_no, model.id)
    elif kind in ("owner", "document"):
        order = (model.sort_order, model.id)
    else:
        order = (model.seq_no, model.id)
    return list(session.scalars(stmt.order_by(*order)))


# =============================================================================
# 이름 수정 / 비활성화
# =============================================================================
def rename(session: Session, project_id: int, name: str) -> Project:
    """프로젝트명만 바꾼다 (plan.md §0.6-3).

    공백 처리는 `ProjectRenameIn` 이 이미 했다. 여기서 다시 하지 않는 이유는
    검증의 정본을 하나로 두기 위해서다 — 두 곳에서 다듬으면 규칙이 갈린다.
    """
    project = get_project(session, project_id)
    project.name = name
    session.flush()
    return project



def deactivate(session: Session, project_id: int) -> Project:
    """`DELETE /projects/{pid}` — **지우지 않고 비활성화한다** (plan.md §4.2).

    프로젝트에는 실행 이력(Status/완료일)이 쌓인다. 되돌릴 수 없는 삭제를 기본
    동작으로 두면, 잘못 누른 한 번이 그 이력을 통째로 없앤다. 기준정보 삭제 정책과
    같은 태도다.
    """
    project = get_project(session, project_id)
    project.is_active = 0
    session.flush()
    return project
