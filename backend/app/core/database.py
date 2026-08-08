"""세션 팩토리 — **호스트가 주입한다** (INTEGRATION.md §4).

이 모듈은 import 시점에 엔진을 만들지 않는다. 모듈 전역에 엔진/세션을 두지도
않는다. 호스트는 자기 세션 팩토리를 `create_wp_router(session_factory=...)` 로
넘기며, 이 파일을 수정할 필요가 없다.

`create_session_factory()` 는 단독 실행(`standalone.py`)과 테스트를 위한
편의 함수일 뿐이며, 호출해야만 엔진이 생긴다.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(
    dsn: str,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
    pool_recycle: int = 3600,
) -> sessionmaker[Session]:
    """DSN 으로 엔진 + 세션 팩토리를 만든다 (호출 시점에만 생성).

    `iai-test` 처럼 하이픈이 들어간 DB 명, 그리고 `%23` 로 인코딩된 비밀번호를
    그대로 쓸 수 있다.
    """
    engine = create_engine(
        dsn,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        pool_recycle=pool_recycle,
        future=True,
    )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
