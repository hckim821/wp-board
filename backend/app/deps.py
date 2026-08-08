"""의존성 컨테이너.

**모듈 전역 가변 상태를 두지 않는다.** 세션 팩토리와 `MakerResolver` 는
`create_wp_router(...)` 인자로 들어와 이 객체에 담기고, 엔드포인트는 클로저로
그것을 붙잡는다. 그래서

* 호스트는 모듈 파일을 고치지 않고 자기 세션 팩토리를 넣을 수 있고,
* 서로 다른 DB 를 보는 라우터 두 개를 같은 앱에 마운트해도 섞이지 않는다.

전역 `configure()` 로 했다면 두 번째가 불가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from .ports.maker_resolver import MakerResolver


@dataclass(frozen=True)
class WpDeps:
    #: 호스트가 주입하는 세션 팩토리 (`sessionmaker` 등 호출하면 Session 을 주는 것).
    session_factory: Callable[[], Session]
    #: 미주입이 정상 상태다 (INTEGRATION.md §2.2).
    maker_resolver: MakerResolver | None = None
    def session(self) -> Iterator[Session]:
        """요청 스코프 세션.

        **커밋은 엔드포인트가 명시적으로 한다.** 여기서 자동 커밋하지 않는 이유는
        실패 경로를 단순하게 만들기 위해서다 — 예외가 나면 커밋이 일어나지 않고
        `close()` 가 트랜잭션을 되돌린다. 발행 검증 실패 시 "상태 유지" 가
        공짜로 보장된다.
        """
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()
