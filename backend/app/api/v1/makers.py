"""설비사 설정 API — plan.md §0.6-3.

**설비사를 만들거나 지우는 엔드포인트가 없다.** 설비사는 호스트 소유이고
(INTEGRATION.md §2), 여기서 다루는 것은 우리 쪽 표시 설정뿐이다. 목록은 언제나
`MakerResolver` 포트를 거치며 설비사 테이블로 JOIN 하지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.exceptions import WpAPIRoute
from ...deps import WpDeps
from ...schemas.maker import MakerSettingsSaveIn, MakersOut
from ...services import maker_service


def build_router(deps: WpDeps) -> APIRouter:
    router = APIRouter(route_class=WpAPIRoute, tags=["makers"])
    session_dep = Depends(deps.session)

    @router.get("/makers", response_model=MakersOut)
    def list_makers(session: Session = session_dep):
        """설정 화면의 표 — 이름 · 프로젝트 유무 · 표시 여부(유효값 + 명시 여부)
        · **그 설비사의 프로젝트 목록(비활성 포함)**.

        resolver 가 없으면 설비사 **전체** 목록을 얻을 수 없으므로, 프로젝트가
        참조하는 id 와 설정 행이 있는 id 만으로 표를 만든다 (이름은 `null`).
        빈 표가 나오는 것도 정상이며, 화면은 안내 문구를 띄운다 (§0.6-2).
        """
        return MakersOut(
            makers=maker_service.list_maker_summaries(session, deps.maker_resolver)
        )

    @router.put("/makers/settings", response_model=MakersOut)
    def save_settings(payload: MakerSettingsSaveIn, session: Session = session_dep):
        """업서트 — **한 트랜잭션**. 목록에 없는 설비사·프로젝트는 손대지 않는다.

        `maker_id` 의 존재는 검증하지 않는다. resolver 미주입이 정상 상태이므로
        존재 검증을 전제로 걸면 그런 설치에서 설정 자체가 불가능해진다
        (`maker_service.save_settings` 참고). `project.id` 는 반대로 검증한다 —
        우리 테이블이라 모른다고 할 이유가 없다.

        설비사 체크와 프로젝트 스위치가 **한 화면의 한 저장 버튼**이므로 한
        커밋으로 묶는다. 프로젝트만 따로 쓰는 경로(`PUT /projects/{id}`)도 여전히
        있지만 그쪽은 건당 커밋이라 이 화면에는 맞지 않는다.

        프로젝트 off 는 **표시만 끈다.** 행은 남으며 실제 삭제는 이 API 어디에도
        없다 — 관리자가 `db/delete_project.py` 를 직접 실행할 때만 일어난다.
        """
        maker_service.save_settings(session, payload.settings)
        maker_service.save_project_visibility(session, payload.projects)
        session.commit()
        return MakersOut(
            makers=maker_service.list_maker_summaries(session, deps.maker_resolver)
        )

    return router
