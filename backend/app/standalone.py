"""[DEV ONLY] 로컬 단독 실행용 앱.

**이 파일은 이 저장소에서 `FastAPI()` 를 만드는 유일한 지점이며, 이식 시 삭제
대상이다** (INTEGRATION.md §4 / §6 체크리스트).

라이브러리 코드가 앱을 만들지 않기 때문에, CORS·미들웨어·로깅처럼 프로세스를
소유하는 설정은 전부 여기 모여 있다. 호스트에 이식할 때 이 파일만 버리면
호스트의 설정과 충돌할 여지가 사라진다.

실행::

    cd backend
    python -m uvicorn app.standalone:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# `backend/.env` 를 프로세스 환경으로 올린다 (`backend/.env.example` 참고).
#
# **여기서만 한다.** 파일에서 설정을 읽는 것은 프로세스를 소유하는 쪽의 일이고,
# 이 파일이 이 저장소에서 앱을 만드는 유일한 지점이자 이식 시 삭제 대상이다.
# `core/config.py` 에 `env_file` 을 걸면 호스트에 이식된 라이브러리가 호스트
# 디렉터리에서 제멋대로 `.env` 를 찾게 된다 (INTEGRATION.md §4 위반).
#
# 경로를 **명시**한다. 인자 없는 `load_dotenv()` 는 호출자 위치에서 위로 훑기
# 때문에, 호스트 트리에 놓였을 때 남의 `.env` 를 집어들 수 있다. 여기서는 언제나
# `backend/.env` 하나다 — 어느 디렉터리에서 uvicorn 을 띄우든 같은 파일이다.
#
# python-dotenv 는 requirements-dev.txt 에만 있다. 없으면 그냥 건너뛰고 셸
# 환경변수만 쓴다 — 개발 편의 기능이 없다고 앱이 뜨지 못하면 안 된다.
# `load_dotenv` 는 기본적으로 기존 환경변수를 **덮어쓰지 않는다.**
try:  # pragma: no cover - 설치 여부에 따른 분기
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass

from .core.config import get_settings
from .core.database import create_session_factory
from .ports.stub_maker_resolver import StubMakerResolver
from .router import create_wp_router

# 개발용 DSN 의 형태. **접속 정보는 저장소에 두지 않는다** — 비밀번호가 든 기본값은
# 곧 저장소에 적힌 비밀번호이고, 이 파일은 개발 전용이라 더더욱 그럴 이유가 없다.
#
# 비밀번호의 `#` 는 반드시 `%23` 으로 인코딩해야 한다 — 안 하면 DSN 이 조용히 잘린다.
# DB 명 `iai-test` 의 하이픈은 SQLAlchemy DSN 에서는 그대로 써도 된다.
DEV_DSN_EXAMPLE = "mysql+pymysql://user01:비밀번호%23@localhost:3306/iai-test?charset=utf8mb4"


def build_app() -> FastAPI:
    settings = get_settings()
    # `WP_DB_DSN` 은 pydantic-settings 가 `env_prefix="WP_"` 로 이미 읽는다.
    # 예전에 `or os.environ.get("WP_DB_DSN")` 폴백이 있었는데 도달 불가능한
    # 죽은 코드였고, **저장소 전체에서 유일한 `os.environ`** 이기도 했다.
    # 설정을 급히 하나 읽고 싶을 때 복사해 갈 본보기가 되므로 지웠다 —
    # 라이브러리 코드의 직접 환경변수 조회는 INTEGRATION.md §4 위반이다.
    #
    # 하드코딩 폴백이 사라졌으므로 미설정은 **오류**다. 조용히 엉뚱한 DB 에 붙는
    # 것보다 뜨지 않는 편이 낫다.
    dsn = settings.db_dsn
    if not dsn:
        raise RuntimeError(
            "WP_DB_DSN 환경변수를 설정하세요.\n"
            f"  예: {DEV_DSN_EXAMPLE}\n"
            "  PowerShell: $env:WP_DB_DSN = 'mysql+pymysql://...'"
        )

    session_factory = create_session_factory(dsn, echo=settings.echo_sql)

    app = FastAPI(
        title="Work Package Board (standalone dev)",
        description=(
            "개발 전용 하니스입니다. 운영에서는 호스트 FastAPI 앱이 "
            "`create_wp_router()` 로 라우터만 마운트합니다."
        ),
        version="0.1.0",
    )
    # CORS 는 앱의 관심사다. 라이브러리 코드에서는 절대 설정하지 않는다.
    # 하니스가 5173 이 아니라 **5180** 에서 뜬다(frontend/vite.config.ts) — 포트를
    # 나열했다가 실제 포트가 빠져 브라우저에서 전부 차단된 적이 있다. dev 전용
    # 앱이므로 로컬 오리진은 포트와 무관하게 전부 허용한다.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(
        create_wp_router(
            session_factory=session_factory,
            # 운영에서는 호스트가 자기 설비사 테이블을 읽는 구현체를 넣는다.
            # 이 스텁은 개발용 `wp_dev_makers` 를 본다.
            maker_resolver=StubMakerResolver(session_factory),
            prefix=settings.api_prefix,
        )
    )

    @app.get("/health", tags=["dev"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = build_app()
