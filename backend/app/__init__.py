"""Work Package 보드 — 호스트 FastAPI 프로젝트에 이식되는 **모듈**.

이 패키지는 애플리케이션이 아니다 (INTEGRATION.md §4). 호스트는 두 줄이면 된다::

    from wp_module.app import create_wp_router

    app.include_router(
        create_wp_router(session_factory=MySessionLocal, maker_resolver=MyMakerResolver())
    )

**import 시점 부작용이 없다.** 이 패키지를 import 해도 엔진이 만들어지지 않고,
CORS·미들웨어·로깅이 설정되지 않으며 `create_all()` 도 돌지 않는다.
앱이 존재하는 유일한 지점은 `app/standalone.py` 이고 그것은 개발 전용이다.
"""

from .deps import WpDeps
from .ports.maker_resolver import MakerResolver
from .router import create_wp_router

__all__ = ["create_wp_router", "WpDeps", "MakerResolver"]
