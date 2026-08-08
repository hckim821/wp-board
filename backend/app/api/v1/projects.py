"""프로젝트 API — plan.md §0.1, §4.2.

**버전 관련 엔드포인트가 하나도 없다.** draft 발행 / 임시저장 / validate / publish /
폐기는 템플릿 계층에만 있다. 프로젝트는 생성이 곧 확정이고, 이후 모든 편집이 바로
반영된다.

행 조작 엔드포인트의 응답 규약은 템플릿과 **같다** — 재계산된 전체 행 목록 +
경계 플래그. 서비스도 같은 것을 쓴다 (`item_service` 는 `Board` 만 안다). 그래서
그리드 동작이 두 계층에서 어긋날 수 없다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ...core.exceptions import BadRequestError, WpAPIRoute
from ...deps import WpDeps
from ...ports.maker_resolver import maker_exists, resolve_names
from ...schemas.item import (
    ItemInsertIn,
    ItemListOut,
    ItemsSaveIn,
    MembershipIn,
    MilestoneFromRowIn,
    PhaseFromRowIn,
    ReorderIn,
)
from ...schemas.project import (
    ProjectCreateIn,
    ProjectDetailOut,
    ProjectDocumentListOut,
    ProjectDocumentsSaveIn,
    ProjectLinkListOut,
    ProjectLinksSaveIn,
    ProjectOut,
    ProjectRenameIn,
    ProjectsOverviewOut,
    ProjectUpdateIn,
)
from ...services import (
    board_xlsx_service,
    dashboard_pptx_service,
    item_service,
    project_document_service,
    project_link_service,
    project_service,
)
from .apply import mount_board_apply
from .downloads import PPTX_MEDIA_TYPE, XLSX_MEDIA_TYPE, attachment
from .master import mount_scoped_master



def build_router(deps: WpDeps) -> APIRouter:
    router = APIRouter(route_class=WpAPIRoute, tags=["projects"])
    session_dep = Depends(deps.session)

    def _to_out(project, names: dict[int, str], versions: dict[int, int]) -> ProjectOut:
        out = ProjectOut.model_validate(project)
        # 둘 다 **못 찾으면 비워 둔다** — 고아 참조가 조회를 깨뜨리지 않는다.
        # 설비사 이름과 원본 버전 번호 모두 물리 FK 없는 논리 참조다.
        out.maker_name = names.get(project.maker_id)
        out.source_version_number = versions.get(project.id)
        return out

    def _one(session: Session, project) -> ProjectOut:
        return _to_out(
            project,
            resolve_names(deps.maker_resolver, [project.maker_id]),
            project_service.source_version_numbers(session, [project]),
        )

    def _detail(session: Session, project) -> ProjectDetailOut:
        board = project_service.board_of(project)
        items = item_service.load_ordered_items(session, board)
        return ProjectDetailOut(
            project=_one(session, project),
            items=item_service.build_item_views(
                session, board, items
            ),
        )

    def _board(session: Session, project_id: int):
        """행 조작의 공통 입구. 프로젝트에는 상태 관문이 없으므로 존재 확인이 전부다."""
        return project_service.board_of(project_service.get_project(session, project_id))

    def _recomputed(session: Session, project_id: int) -> ItemListOut:
        board = _board(session, project_id)
        items = item_service.load_ordered_items(session, board)
        return ItemListOut(
            items=item_service.build_item_views(
                session, board, items
            )
        )

    # =========================================================================
    # 프로젝트 자체
    # =========================================================================
    @router.get("/projects", response_model=list[ProjectOut])
    def list_projects(
        maker_id: int | None = Query(default=None, description="호스트 설비사 PK 로 필터"),
        include_inactive: bool = Query(default=False),
        session: Session = session_dep,
    ):
        projects = project_service.list_projects(
            session, maker_id=maker_id, include_inactive=include_inactive
        )
        # 설비사 테이블로 JOIN 하지 않는다. 이름은 포트를 통해서만 얻는다.
        # 원본 버전 번호도 프로젝트마다가 아니라 한 번에 읽는다.
        names = resolve_names(deps.maker_resolver, [p.maker_id for p in projects])
        versions = project_service.source_version_numbers(session, projects)
        return [_to_out(p, names, versions) for p in projects]

    # ⚠️ `/projects/{project_id}` **보다 먼저** 등록해야 한다. FastAPI 는 등록
    # 순서대로 매칭하므로, 뒤에 두면 "overview" 가 project_id 로 잡혀 422 가 난다.
    @router.get("/projects/overview", response_model=ProjectsOverviewOut)
    def projects_overview(session: Session = session_dep):
        """전체 현황 (plan.md §0.5-3, §0.6-3 개편) — **설비사 섹션**으로 묶어 준다.

        읽기 전용이며 설비사에 매이지 않는다 (전 설비사 관망). 표시 규칙과
        그룹핑은 서버가 적용하므로 클라이언트는 받은 대로 그리면 된다.
        resolver 가 없으면 이름이 `null` 로 나간다 — 오류가 아니다.
        """
        makers = project_service.overview(
            session, deps.maker_resolver
        )
        # 섹션 이름은 서비스가 이미 채웠다. 프로젝트 카드의 `maker_name` 도
        # 같은 값이라야 하므로 여기서 한 번에 맞춘다 (조회는 추가로 하지 않는다).
        for maker in makers:
            for project in maker.projects:
                project.maker_name = maker.name
        return ProjectsOverviewOut(makers=makers)

    @router.post("/projects", response_model=ProjectDetailOut, status_code=201)
    def create_project(payload: ProjectCreateIn, session: Session = session_dep):
        """생성 — 발행된 템플릿 버전에서 **전부 복제**한다. 한 트랜잭션이다.

        중간에 실패하면 커밋하지 않으므로 반쯤 복제된 프로젝트가 남지 않는다.
        """
        # resolver 가 주입된 경우에만 설비사 존재를 검증한다.
        if not maker_exists(deps.maker_resolver, payload.maker_id):
            raise BadRequestError(f"호스트에 없는 maker_id 입니다: {payload.maker_id}")

        project = project_service.create_project(
            session,
            maker_id=payload.maker_id,
            name=payload.name,
            description=payload.description,
            template_id=payload.template_id,
            template_version_id=payload.template_version_id,
            created_by=payload.created_by,
        )
        session.commit()
        session.refresh(project)
        return _detail(session, project)

    @router.get("/projects/{project_id}", response_model=ProjectDetailOut)
    def get_project(project_id: int, session: Session = session_dep):
        """그리드 로드용 — 프로젝트 + 재계산된 전체 행."""
        return _detail(session, project_service.get_project(session, project_id))

    @router.put("/projects/{project_id}", response_model=ProjectOut)
    def update_project(
        project_id: int, payload: ProjectUpdateIn, session: Session = session_dep
    ):
        project = project_service.get_project(session, project_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(project, key, value)
        session.commit()
        session.refresh(project)
        return _one(session, project)

    @router.patch("/projects/{project_id}", response_model=ProjectOut)
    def rename_project(
        project_id: int, payload: ProjectRenameIn, session: Session = session_dep
    ):
        """프로젝트명 인라인 수정 (plan.md §0.6-3).

        `PUT` 과 따로 두는 이유: 전체 현황의 연필 아이콘은 **이름 하나만** 고친다.
        `PUT` 은 `ProjectUpdateIn` 의 모든 필드를 받으므로, 그리로 보내면
        `phase_start_no` 나 `is_active` 를 실수로 함께 덮어쓸 여지가 생긴다.
        받는 필드가 하나뿐인 경로에는 그 사고가 아예 없다.

        빈 이름·공백뿐인 이름은 422 다 (`ProjectRenameIn`).
        """
        project = project_service.rename(session, project_id, payload.name)
        session.commit()
        session.refresh(project)
        return _one(session, project)

    @router.delete("/projects/{project_id}", response_model=ProjectOut)
    def deactivate_project(project_id: int, session: Session = session_dep):
        """**비활성화**한다 — 실제로 지우지 않는다 (plan.md §4.2).

        프로젝트에는 실행 이력이 쌓이므로, 되돌릴 수 없는 삭제를 기본값으로 두지
        않는다.
        """
        project = project_service.deactivate(session, project_id)
        session.commit()
        session.refresh(project)
        return _one(session, project)

    # =========================================================================
    # 행 — 템플릿과 같은 규약 (재계산된 전체 목록 + 경계 플래그)
    # =========================================================================
    @router.put("/projects/{project_id}/items", response_model=ProjectDetailOut)
    def save_items(project_id: int, payload: ItemsSaveIn, session: Session = session_dep):
        """직접 저장 — 전량 교체, **검증 없음** (참조 무결성만).

        프로젝트에는 발행이 없으므로 이것이 유일한 일괄 저장 경로다. 필수값 누락도
        회색 행도 그대로 저장된다 (plan.md §0.1 — 차단 검증 없음).
        """
        board = _board(session, project_id)
        item_service.bulk_replace(
            session, board, payload.items
        )
        session.commit()
        return _detail(session, project_service.get_project(session, project_id))

    @router.post("/projects/{project_id}/items", response_model=ItemListOut, status_code=201)
    def append_item(
        project_id: int,
        payload: ItemInsertIn | None = None,
        session: Session = session_dep,
    ):
        """목록 맨 끝에 **회색 행**을 추가한다 (§0.2)."""
        item_service.append_item(
            session, _board(session, project_id), payload or ItemInsertIn(),
        )
        session.commit()
        return _recomputed(session, project_id)

    @router.post("/projects/{project_id}/items/{item_id}/insert-below", response_model=ItemListOut)
    def insert_below(
        project_id: int,
        item_id: int,
        payload: ItemInsertIn | None = None,
        session: Session = session_dep,
    ):
        """기준 행 바로 아래에 **회색 행**을 추가한다 (§0.2). 소속을 상속하지 않는다."""
        item_service.insert_below(
            session, _board(session, project_id), item_id, payload or ItemInsertIn(),
        )
        session.commit()
        return _recomputed(session, project_id)

    @router.post("/projects/{project_id}/items/reorder", response_model=ItemListOut)
    def reorder_items(project_id: int, payload: ReorderIn, session: Session = session_dep):
        """**위치만** 변경 (드래그) + 재계산. 각 행은 자기 소속을 그대로 유지한다."""
        item_service.reorder(session, _board(session, project_id), payload.item_ids)
        session.commit()
        return _recomputed(session, project_id)

    @router.patch(
        "/projects/{project_id}/items/{item_id}/membership", response_model=ItemListOut
    )
    def change_membership(
        project_id: int, item_id: int, payload: MembershipIn, session: Session = session_dep
    ):
        """**소속만** 변경 (§2.3 셀 편집) + 이동 + 재계산."""
        item_service.change_membership(
            session, _board(session, project_id), item_id, payload.phase_id, payload.milestone_id
        )
        session.commit()
        return _recomputed(session, project_id)

    @router.post("/projects/{project_id}/items/{item_id}/create-phase", response_model=ItemListOut)
    def create_phase_from_row(
        project_id: int, item_id: int, payload: PhaseFromRowIn, session: Session = session_dep
    ):
        """**프로젝트 로컬** Phase 를 만든다 — 템플릿에 영향이 없다 (plan.md §4.2)."""
        item_service.create_phase_from_row(
            session, _board(session, project_id), item_id, payload.name
        )
        session.commit()
        return _recomputed(session, project_id)

    @router.post(
        "/projects/{project_id}/items/{item_id}/create-milestone", response_model=ItemListOut
    )
    def create_milestone_from_row(
        project_id: int, item_id: int, payload: MilestoneFromRowIn, session: Session = session_dep
    ):
        """**프로젝트 로컬** Milestone 을 만든다."""
        item_service.create_milestone_from_row(
            session, _board(session, project_id), item_id, payload.name
        )
        session.commit()
        return _recomputed(session, project_id)

    @router.delete("/projects/{project_id}/items/{item_id}", response_model=ItemListOut)
    def delete_item(project_id: int, item_id: int, session: Session = session_dep):
        item_service.delete_item(session, _board(session, project_id), item_id)
        session.commit()
        return _recomputed(session, project_id)

    # =========================================================================
    # 프로젝트 문서 (plan.md §0.5.10)
    #
    # §0.5.10 이전에는 전역 문서에 프로젝트별 설정만 붙이는 화면이었다. 이제
    # 문서를 프로젝트가 소유하므로 **행 추가·이름 변경·삭제**까지 여기서 한다.
    # =========================================================================
    @router.get("/projects/{project_id}/documents", response_model=ProjectDocumentListOut)
    def list_documents(project_id: int, session: Session = session_dep):
        """이 프로젝트의 문서 전부 (`sort_order` 순).

        **있는 행이 전부다** — 예전의 "행이 없으면 기본값" lazy 규칙은 문서가
        복제 대상이 되면서 사라졌다.
        """
        project_service.get_project(session, project_id)      # 없으면 404
        return ProjectDocumentListOut(
            documents=project_document_service.list_documents_out(session, project_id)
        )

    @router.put("/projects/{project_id}/documents", response_model=ProjectDocumentListOut)
    def save_documents(
        project_id: int, payload: ProjectDocumentsSaveIn, session: Session = session_dep
    ):
        """**전량 교체** — 배열 순서 = `sort_order`, `deleted_ids` 로 명시 삭제.

        삭제하면 그 문서를 쓰던 **항목 링크가 함께 사라지므로**, 응답에 재계산된
        행 목록을 함께 실어 그리드가 곧바로 갱신되게 한다 (§0.5.10).

        검증(빈 이름·중복·스코프)을 전부 끝낸 뒤에 쓰므로 422 면 아무것도 바뀌지
        않는다.
        """
        project_service.get_project(session, project_id)
        project_document_service.replace_documents(
            session, project_id, payload.documents, payload.deleted_ids
        )
        session.commit()

        board = _board(session, project_id)
        return ProjectDocumentListOut(
            documents=project_document_service.list_documents_out(session, project_id),
            items=item_service.build_item_views(
                session, board, item_service.load_ordered_items(session, board)
            ),
        )

    # =========================================================================
    # 대시보드 PPTX 내보내기 (plan.md §0.5.6)
    # =========================================================================
    @router.get(
        "/projects/{project_id}/dashboard.pptx",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "application/vnd.openxmlformats-officedocument"
                    ".presentationml.presentation": {}
                },
                "description": "슬라이드 1장짜리 PPTX",
            }
        },
    )
    def export_dashboard_pptx(project_id: int, session: Session = session_dep):
        """대시보드를 **16:9 한 장**으로 내보낸다.

        화면 캡처가 아니라 데이터에서 다시 그린다 — 스크롤 밖의 항목도 빠지지
        않고, 폰트·색이 보는 사람의 환경에 좌우되지 않는다.

        **읽기 연산이다.** `readOnly` 여도 허용된다.
        """
        name, payload = dashboard_pptx_service.dashboard_pptx(
            session, project_id
        )
        return Response(
            content=payload,
            media_type=PPTX_MEDIA_TYPE,
            headers={"Content-Disposition": attachment(f"{name}.pptx")},
        )

    @router.get(
        "/projects/{project_id}/board.xlsx",
        response_class=Response,
        responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "원본 양식 XLSX"}},
    )
    def export_board_xlsx(project_id: int, session: Session = session_dep):
        """보드를 **`docs/Work Package.xlsx` 원본 양식**으로 내보낸다 (§0.5.7).

        Doc Status 시트에 이 프로젝트의 **사용·링크·작성 상태**가 덧붙는다.
        읽기 연산이며 `readOnly` 여도 허용된다.
        """
        name, payload = board_xlsx_service.project_board_xlsx(
            session, project_id
        )
        return Response(
            content=payload,
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": attachment(f"{name}.xlsx")},
        )

    # =========================================================================
    # 프로젝트 주요 링크 (plan.md §0.5.5)
    #
    # §0.5-4 의 문서 설정과 **다른 것**이다. 그쪽은 전역 문서 마스터가 정한
    # 집합에 링크·상태를 붙이는 부분 업서트이고, 이쪽은 프로젝트가 자유롭게
    # 늘리고 줄이는 목록의 전량 교체다.
    # =========================================================================
    @router.get("/projects/{project_id}/links", response_model=ProjectLinkListOut)
    def list_links(project_id: int, session: Session = session_dep):
        """`sort_order` 순. 화면의 drag 순서가 그대로 유지된다."""
        project_service.get_project(session, project_id)      # 없으면 404
        return ProjectLinkListOut(links=project_link_service.list_links(session, project_id))

    @router.put("/projects/{project_id}/links", response_model=ProjectLinkListOut)
    def save_links(
        project_id: int, payload: ProjectLinksSaveIn, session: Session = session_dep
    ):
        """**전량 교체** — 배열 순서가 곧 `sort_order`, 빠진 기존 링크는 삭제.
        한 트랜잭션이다.

        검증(URL 스킴 · 설명 공백 · 스코프)을 전부 끝낸 뒤에 쓰므로, 422 면
        커밋에 도달하지 않아 아무것도 바뀌지 않는다. 오류에는 `row_no` 와
        `field` 가 실려 그리드가 문제의 셀을 짚을 수 있다.
        """
        project_service.get_project(session, project_id)
        project_link_service.replace_links(session, project_id, payload.links)
        session.commit()
        # 커밋 뒤 다시 읽는다 — 신규 행의 id 와 최종 `sort_order` 를 응답에 담아야
        # 클라이언트가 그대로 교체할 수 있다 (행 조작 API 와 같은 규약).
        return ProjectLinkListOut(
            links=project_link_service.list_links(session, project_id)
        )

    # =========================================================================
    # 프로젝트 로컬 기준정보 — 템플릿과 같은 CRUD, 다른 테이블
    # =========================================================================
    mount_scoped_master(
        router,
        deps,
        prefix="/projects",
        param="project_id",
        resolve=lambda session, pid: _board(session, pid),
    )

    # Phase/Milestone 관리 팝업 (§0.4) — 템플릿과 **같은 구현**이다. 프로젝트에는
    # 상태 관문이 없으므로 `resolve` 가 존재 확인만 한다.
    mount_board_apply(
        router,
        deps,
        prefix="/projects",
        param="project_id",
        resolve=lambda session, pid: _board(session, pid),
    )

    return router
