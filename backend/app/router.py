"""마운트 계약의 유일한 입구 — `create_wp_router()` (INTEGRATION.md §4).

호스트가 할 일은 두 줄이다::

    from wp_module.app import create_wp_router

    app.include_router(create_wp_router(session_factory=SessionLocal))

**라이브러리 코드에 `FastAPI()` 인스턴스가 없다.** 이 팩토리는 완전히 배선된
`APIRouter` 를 돌려주고, CORS·미들웨어·예외 핸들러·로깅을 건드리지 않는다.
도메인 예외의 HTTP 변환은 `WpAPIRoute` 가 라우터 안에서 처리하므로 호스트가
핸들러를 등록할 필요도 없다.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter
from sqlalchemy.orm import Session

from .api.v1 import items, makers, master, projects, templates, versions
from .core.exceptions import WpAPIRoute
from .deps import WpDeps
from .ports.maker_resolver import MakerResolver


def create_wp_router(
    *,
    session_factory: Callable[[], Session],
    maker_resolver: MakerResolver | None = None,
    prefix: str = "/api/v1",
    tags: list[str] | None = None,
) -> APIRouter:
    """배선이 끝난 라우터를 만든다.

    Args:
        session_factory: 호출하면 `Session` 을 주는 것 (`sessionmaker` 등).
            호스트가 자기 것을 넘긴다. 이 모듈은 엔진을 만들지 않는다.
        maker_resolver: 설비사 이름 조회 포트. **생략이 정상**이며, 그 경우
            응답에서 `maker_name` 이 빠질 뿐 나머지는 그대로 동작한다.
        prefix: 마운트 경로. 호스트의 라우팅 규칙에 맞춰 바꿀 수 있다.
        tags: OpenAPI 태그 덮어쓰기.
    """
    deps = WpDeps(session_factory=session_factory, maker_resolver=maker_resolver)

    router = APIRouter(prefix=prefix.rstrip("/"), route_class=WpAPIRoute)
    # 두 계층이 **하나의** 라우터에 함께 실린다 (plan.md §0.1). 호스트가 마운트할
    # 것은 여전히 `create_wp_router(...)` 한 줄이다 — 계층이 늘었다고 마운트 지점을
    # 늘리면 그것 자체가 이식 비용이 된다.
    for build in (
        templates.build_router,      # 기준 데이터 (중앙)
        versions.build_router,       # 템플릿 버전 — draft/발행/폐기
        items.build_router,          # 템플릿 버전의 행
        projects.build_router,       # 프로젝트 (설비사별) + 그 행 + 로컬 기준정보
        makers.build_router,         # 설비사 표시 설정 (설비사 자체는 호스트 소유)
        master.build_router,         # 전역 문서 기준정보
    ):
        router.include_router(build(deps), tags=tags)
    return router
