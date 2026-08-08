"""기준정보 API.

스코프가 두 종류다 (plan.md §2.6, §0.1)

* `/master/document-types` — **전역**. 두 계층이 공유하며 복제하지 않는다.
* `/templates/{id}/owners|phases|milestones` — **템플릿 스코프**.
* `/projects/{id}/owners|phases|milestones` — **프로젝트 로컬 사본**.

뒤의 두 묶음은 URL 과 스코프 해석만 다르고 나머지가 같다. 그래서
`mount_scoped_master()` 하나로 양쪽을 만든다 — 12개 엔드포인트를 두 벌 적으면
한쪽만 고쳐질 것이고, 그런 종류의 드리프트가 이 저장소가 반복해서 겪은 문제다.

삭제는 hard delete 를 시도하지 않는다. 사용 중이면 비활성화하고 사용 건수를
함께 돌려준다.
"""

from __future__ import annotations

import functools
import inspect
from typing import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.exceptions import WpAPIRoute
from ...deps import WpDeps
from ...schemas.master import (
    DeleteResultOut,
    MilestoneCreateIn,
    MilestoneOut,
    MilestoneUpdateIn,
    OwnerCreateIn,
    OwnerOut,
    OwnerUpdateIn,
    PhaseCreateIn,
    PhaseOut,
    PhaseUpdateIn,
)
from ...services import master_service
from ...services.board import Board


def _phase_out(phase) -> PhaseOut:
    out = PhaseOut.model_validate(phase)
    out.display = master_service.phase_display(phase)
    return out


def _milestone_out(milestone, phase) -> MilestoneOut:
    out = MilestoneOut.model_validate(milestone)
    out.no_display = master_service.milestone_no_display(milestone, phase)
    out.display = master_service.milestone_display(milestone, phase)
    return out


def _as_path_param(fn, name: str):
    """핸들러의 `scope_id` 인자를 `name` 으로 노출한다.

    `__signature__` 를 갈아 끼우는 것은 파이썬 표준 메커니즘이고 FastAPI 가 그것을
    존중한다 — 라우터 내부(`dependant`, `path_format`)를 손대지 않는다. 덕분에
    핸들러 본문은 계층에 무관하게 한 벌로 남고, URL·OpenAPI 에는 `template_id` /
    `project_id` 가 제대로 드러난다.
    """
    signature = inspect.signature(fn)
    parameters = [
        p.replace(name=name) if p.name == "scope_id" else p
        for p in signature.parameters.values()
    ]

    @functools.wraps(fn)
    def wrapper(**kwargs):
        kwargs["scope_id"] = kwargs.pop(name)
        return fn(**kwargs)

    wrapper.__signature__ = signature.replace(parameters=parameters)
    return wrapper


def _route(method, name: str):
    """`@_route(router.get, "template_id")(path, ...)` — 등록 직전에 이름을 바꾼다."""

    def register(*args, **kwargs):
        def decorate(fn):
            method(*args, **kwargs)(_as_path_param(fn, name))
            return fn

        return decorate

    return register


def mount_scoped_master(
    router: APIRouter,
    deps: WpDeps,
    *,
    prefix: str,
    param: str,
    resolve: Callable[[Session, int], Board],
) -> None:
    """보드 스코프 기준정보 CRUD 12종을 `router` 에 단다.

    Args:
        prefix: `/templates` 또는 `/projects`.
        param: 경로 파라미터 이름 (`template_id` / `project_id`). 핸들러는 전부
            `scope_id` 로 쓰고, 등록 직전에 `__signature__` 를 갈아 끼워 이 이름으로
            노출한다 (`_as_path_param`). FastAPI 내부를 건드리지 않는 표준 방법이며,
            OpenAPI 에 `/templates/{scope_id}` 같은 낯선 이름이 새는 것을 막는다.
        resolve: `(session, scope_id) -> Board`. 대상의 존재 확인까지 여기서
            끝낸다 — 없으면 404 를 던진다.
    """
    session_dep = Depends(deps.session)
    base = f"{prefix}/{{{param}}}"

    # ------------------------------------------------------------------ Owner
    @_route(router.get, param)(
f"{base}/owners", response_model=list[OwnerOut], name=f"{param}_list_owners")
    def list_owners(scope_id: int, session: Session = session_dep):
        return master_service.list_owners(session, resolve(session, scope_id))

    @_route(router.post, param)(
        f"{base}/owners", response_model=OwnerOut, status_code=201, name=f"{param}_create_owner"
    )
    def create_owner(scope_id: int, payload: OwnerCreateIn, session: Session = session_dep):
        entity = master_service.create_owner(session, resolve(session, scope_id), payload)
        session.commit()
        session.refresh(entity)
        return entity

    @_route(router.put, param)(
f"{base}/owners/{{owner_id}}", response_model=OwnerOut, name=f"{param}_update_owner")
    def update_owner(
        scope_id: int, owner_id: int, payload: OwnerUpdateIn, session: Session = session_dep
    ):
        entity = master_service.update_owner(
            session, resolve(session, scope_id), owner_id, payload
        )
        session.commit()
        session.refresh(entity)
        return entity

    @_route(router.delete, param)(
        f"{base}/owners/{{owner_id}}", response_model=DeleteResultOut, name=f"{param}_delete_owner"
    )
    def delete_owner(scope_id: int, owner_id: int, session: Session = session_dep):
        result = master_service.delete_owner(session, resolve(session, scope_id), owner_id)
        session.commit()
        return result

    # ------------------------------------------------------------------ Phase
    @_route(router.get, param)(
f"{base}/phases", response_model=list[PhaseOut], name=f"{param}_list_phases")
    def list_phases(scope_id: int, session: Session = session_dep):
        return [_phase_out(p) for p in master_service.list_phases(session, resolve(session, scope_id))]

    @_route(router.post, param)(
        f"{base}/phases", response_model=PhaseOut, status_code=201, name=f"{param}_create_phase"
    )
    def create_phase(scope_id: int, payload: PhaseCreateIn, session: Session = session_dep):
        entity = master_service.create_phase(session, resolve(session, scope_id), payload)
        session.commit()
        session.refresh(entity)
        return _phase_out(entity)

    @_route(router.put, param)(
f"{base}/phases/{{phase_id}}", response_model=PhaseOut, name=f"{param}_update_phase")
    def update_phase(
        scope_id: int, phase_id: int, payload: PhaseUpdateIn, session: Session = session_dep
    ):
        entity = master_service.update_phase(session, resolve(session, scope_id), phase_id, payload)
        session.commit()
        session.refresh(entity)
        return _phase_out(entity)

    @_route(router.delete, param)(
        f"{base}/phases/{{phase_id}}", response_model=DeleteResultOut, name=f"{param}_delete_phase"
    )
    def delete_phase(scope_id: int, phase_id: int, session: Session = session_dep):
        result = master_service.delete_phase(session, resolve(session, scope_id), phase_id)
        session.commit()
        return result

    # -------------------------------------------------------------- Milestone
    @_route(router.get, param)(
        f"{base}/milestones", response_model=list[MilestoneOut], name=f"{param}_list_milestones"
    )
    def list_milestones(
        scope_id: int,
        phase_id: int | None = Query(default=None),
        session: Session = session_dep,
    ):
        board = resolve(session, scope_id)
        phases = {p.id: p for p in master_service.list_phases(session, board)}
        return [
            _milestone_out(m, phases.get(m.phase_id))
            for m in master_service.list_milestones(session, board, phase_id)
        ]

    @_route(router.post, param)(
        f"{base}/milestones",
        response_model=MilestoneOut,
        status_code=201,
        name=f"{param}_create_milestone",
    )
    def create_milestone(scope_id: int, payload: MilestoneCreateIn, session: Session = session_dep):
        board = resolve(session, scope_id)
        entity = master_service.create_milestone(session, board, payload)
        session.commit()
        session.refresh(entity)
        return _milestone_out(entity, session.get(board.spec.phase_cls, entity.phase_id))

    @_route(router.put, param)(
        f"{base}/milestones/{{milestone_id}}",
        response_model=MilestoneOut,
        name=f"{param}_update_milestone",
    )
    def update_milestone(
        scope_id: int, milestone_id: int, payload: MilestoneUpdateIn, session: Session = session_dep
    ):
        board = resolve(session, scope_id)
        entity = master_service.update_milestone(session, board, milestone_id, payload)
        session.commit()
        session.refresh(entity)
        return _milestone_out(entity, session.get(board.spec.phase_cls, entity.phase_id))

    @_route(router.delete, param)(
        f"{base}/milestones/{{milestone_id}}",
        response_model=DeleteResultOut,
        name=f"{param}_delete_milestone",
    )
    def delete_milestone(scope_id: int, milestone_id: int, session: Session = session_dep):
        result = master_service.delete_milestone(session, resolve(session, scope_id), milestone_id)
        session.commit()
        return result


def build_router(deps: WpDeps) -> APIRouter:
    """전역 문서 기준정보만 담는다.

    보드 스코프 CRUD 는 `mount_scoped_master()` 로 템플릿·프로젝트 라우터가
    각자 단다 — 그래야 URL 이 자기 계층 아래에 놓인다.
    """
    router = APIRouter(route_class=WpAPIRoute, tags=["master-data"])
    session_dep = Depends(deps.session)

    return router
