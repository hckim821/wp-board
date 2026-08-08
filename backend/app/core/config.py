"""설정 — `WP_` 접두 환경변수 (INTEGRATION.md §4).

코드 어디서도 `os.environ` 을 직접 읽지 않는다. 호스트의 환경변수와 섞이지
않도록 접두를 강제하고, 인스턴스는 **지연 생성**한다 (import 부작용 금지).

라이브러리 코드 경로는 세션 팩토리를 주입받으므로 사실상 이 설정이 필요 없다.
`db_dsn` 은 `standalone.py` 와, 호스트가 굳이 환경변수로 배선하고 싶을 때를 위한
편의 값이다. **기본값에 접속 정보를 넣지 않는다** — 개발용 DSN 은
`standalone.py` 에만 있다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class WpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WP_", extra="ignore")

    #: SQLAlchemy DSN. 비밀번호의 `#` 는 `%23` 으로 인코딩해야 한다
    #: (인코딩하지 않으면 DSN 이 조용히 잘린다).
    db_dsn: str | None = None

    #: `create_wp_router()` 의 기본 prefix. 호스트가 인자로 덮어쓸 수 있다.
    api_prefix: str = "/api/v1"

    echo_sql: bool = False
    pool_pre_ping: bool = True
    pool_recycle: int = 3600


@lru_cache(maxsize=1)
def get_settings() -> WpSettings:
    """지연 생성 + 캐시. 모듈 로드 시점에는 아무것도 읽지 않는다."""
    return WpSettings()
