"""템플릿(기준 데이터) / 버전 목록 API — plan.md §0.1, §4.2.

**설비사 개념이 없다.** 템플릿은 중앙 관리 대상이고, `maker_id` 는 프로젝트
계층에만 있다 (`api/v1/projects.py`). 그래서 이 라우터는 `MakerResolver` 를
쓰지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.exceptions import BadRequestError, WpAPIRoute
from ...deps import WpDeps
from ...models import Template
from ...schemas.template import TemplateCreateIn, TemplateOut, TemplateUpdateIn
from ...schemas.version import DraftCreateIn, VersionOut
from ...services import version_service
from ...services.board import TEMPLATE_BOARD, Board
from .master import mount_scoped_master


def _version_out(version) -> VersionOut:
    out = VersionOut.model_validate(version)
    out.is_editable = version.is_editable
    return out


def build_router(deps: WpDeps) -> APIRouter:
    router = APIRouter(route_class=WpAPIRoute, tags=["templates"])
    session_dep = Depends(deps.session)

    @router.get("/templates", response_model=list[TemplateOut])
    def list_templates(
        include_inactive: bool = Query(default=False),
        session: Session = session_dep,
    ):
        stmt = select(Template)
        if not include_inactive:
            stmt = stmt.where(Template.is_active == 1)
        return [
            TemplateOut.model_validate(t) for t in session.scalars(stmt.order_by(Template.id))
        ]

    @router.post("/templates", response_model=TemplateOut, status_code=201)
    def create_template(payload: TemplateCreateIn, session: Session = session_dep):
        duplicate = session.scalar(select(Template).where(Template.code == payload.code))
        if duplicate is not None:
            raise BadRequestError(f"이미 코드 '{payload.code}' 의 템플릿이 있습니다.")

        template = Template(**payload.model_dump())
        session.add(template)
        session.commit()
        session.refresh(template)
        return TemplateOut.model_validate(template)

    @router.get("/templates/{template_id}", response_model=TemplateOut)
    def get_template(template_id: int, session: Session = session_dep):
        return TemplateOut.model_validate(version_service.get_template(session, template_id))

    @router.put("/templates/{template_id}", response_model=TemplateOut)
    def update_template(
        template_id: int, payload: TemplateUpdateIn, session: Session = session_dep
    ):
        template = version_service.get_template(session, template_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(template, key, value)
        session.commit()
        session.refresh(template)
        return TemplateOut.model_validate(template)

    @router.get("/templates/{template_id}/versions", response_model=list[VersionOut])
    def list_versions(template_id: int, session: Session = session_dep):
        version_service.get_template(session, template_id)
        return [_version_out(v) for v in version_service.list_versions(session, template_id)]

    @router.post(
        "/templates/{template_id}/versions/draft",
        response_model=VersionOut,
        status_code=201,
    )
    def create_draft(
        template_id: int,
        payload: DraftCreateIn | None = None,
        session: Session = session_dep,
    ):
        """draft 발행 — 현재 PUBLISHED 를 deep copy 한다 (없으면 빈 v1)."""
        payload = payload or DraftCreateIn()
        draft = version_service.create_draft(
            session, template_id, created_by=payload.created_by, notes=payload.notes
        )
        session.commit()
        session.refresh(draft)
        return _version_out(draft)

    # =========================================================================
    # 템플릿 스코프 기준정보 — 프로젝트와 같은 CRUD, 다른 테이블
    # =========================================================================
    def _master_board(session: Session, template_id: int) -> Board:
        """기준정보 CRUD 용 보드.

        `scope_id` 는 쓰이지 않는다 — 이 경로는 행을 건드리지 않고 기준정보만 본다.
        `phase_start_no` 도 마찬가지다. 그래서 버전을 고르지 않고 템플릿만으로
        만든다 (기준정보는 버전이 아니라 템플릿에 매여 있다 — plan.md §2.6).
        """
        template = version_service.get_template(session, template_id)
        return Board(
            spec=TEMPLATE_BOARD,
            scope_id=0,
            master_scope_id=template.id,
            phase_start_no=template.phase_start_no,
            sync_master_seq=False,
        )

    mount_scoped_master(
        router, deps, prefix="/templates", param="template_id", resolve=_master_board
    )

    return router
