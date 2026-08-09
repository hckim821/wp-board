"""테스트 픽스처.

두 종류의 테스트가 있다.

* **순수 테스트** — `renumber_service` / `validation_service`. DB 없이 돈다.
  두 모듈이 순수 함수만 갖도록 설계한 것의 배당금이다.
* **DB 테스트** — 실제 MariaDB 에 `db/schema.sql` **원본을 그대로 적용**해서
  만든 테스트 DB 위에서 돈다. `Base.metadata.create_all()` 을 쓰지 않는 이유는,
  그러면 ORM 과 실제 DDL 이 어긋나도 테스트가 통과해 버리기 때문이다.
  여기서는 스키마 파일 자체가 검증 대상이다.

DB 에 붙지 못하면 DB 테스트는 skip 된다 (순수 테스트는 그대로 돈다).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import create_session_factory
from app.models import Milestone, Owner, Phase, Template, TemplateDocument, Version
from app.models.base import VersionStatus
from app.router import create_wp_router

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"

# `backend/.env` (`backend/.env.example` 참고). 없거나 python-dotenv 가 없으면
# 건너뛰고 셸 환경변수만 쓴다. 기존 환경변수를 덮어쓰지 않으므로, 셸에서 다른 DB 를
# 겨눠도 `.env` 가 그것을 되돌리지 않는다.
try:  # pragma: no cover - 설치 여부에 따른 분기
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

#: 접속 정보는 **환경변수**로 받는다 — 저장소에 비밀번호를 두지 않는다.
#:
#: 비밀번호만 기본값이 없다. 나머지는 로컬 개발 기본값이 있어도 비밀이 아니지만,
#: 비밀번호에 기본값을 두는 순간 그 기본값이 곧 저장소에 적힌 비밀번호가 된다.
DB_HOST = os.environ.get("WP_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("WP_DB_PORT", "3306"))
DB_USER = os.environ.get("WP_DB_USER", "user01")
DB_PASSWORD = os.environ.get("WP_DB_PASSWORD", "")
#: DSN 에서는 `#` 를 `%23` 으로 — 인코딩하지 않으면 DSN 이 조용히 잘린다.
DB_PASSWORD_URL = quote_plus(DB_PASSWORD)
#: 운영 `iai-test` 를 건드리지 않도록 별도 DB 를 쓴다.
#
#: **프로세스마다 이름이 다르다.** 고정 이름을 쓰면 두 pytest 가 동시에 돌 때
#: (예: 다른 에이전트가 감사용으로 같은 스위트를 실행할 때) 서로의 DB 를
#: DROP/CREATE 하면서 상대 테이블을 지워 버린다. 그러면 "Table ... doesn't
#: exist" 가 무작위로 터져 코드 결함처럼 보인다. 실제로 그 일이 있었다.
TEST_DB = f"iai_test_pytest_{os.getpid()}"

SERVER_DSN = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD_URL}@{DB_HOST}:{DB_PORT}/?charset=utf8mb4"
TEST_DSN = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD_URL}@{DB_HOST}:{DB_PORT}/{TEST_DB}?charset=utf8mb4"
)

#: FK 역순. TRUNCATE 대신 DELETE 를 쓰는 이유는 FK 제약을 켠 채로 지우기 위해서다.
WIPE_ORDER = [
    "wp_maker_settings",
    "wp_project_links",
    "wp_project_documents",
    "wp_project_item_owners",
    "wp_project_item_documents",
    "wp_project_items",
    "wp_project_milestones",
    "wp_project_phases",
    "wp_project_owners",
    "wp_projects",
    "wp_item_owners",
    "wp_item_documents",
    "wp_items",
    "wp_versions",
    "wp_milestones",
    "wp_phases",
    "wp_owners",
    "wp_template_documents",
    "wp_templates",
]


def _schema_statements() -> list[str]:
    """`db/schema.sql` 에서 CREATE TABLE 문만 뽑는다.

    맨 앞의 `CREATE DATABASE` / `USE` 두 줄은 개발용이고 이식 시 제거 대상이므로
    (schema.sql 주석 참고) 테스트에서도 건너뛴다. 나머지 DDL 은 **손대지 않고**
    그대로 실행한다.
    """
    raw = SCHEMA_PATH.read_text(encoding="utf-8")
    statements: list[str] = []
    buffer: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            buffer = []
            head = statement.upper()
            if head.startswith("CREATE DATABASE") or head.startswith("USE "):
                continue
            statements.append(statement)
    return statements


@pytest.fixture(scope="session")
def session_factory():
    # 비밀번호가 없으면 접속 오류 메시지("Access denied") 로 끝나서 원인이 안 보인다.
    # 무엇을 설정해야 하는지 먼저 말한다.
    if not DB_PASSWORD:
        pytest.skip(
            "WP_DB_PASSWORD 환경변수가 없어 DB 테스트를 건너뜁니다. "
            "PowerShell: $env:WP_DB_PASSWORD = 'xxxx'"
        )
    try:
        server = create_session_factory(SERVER_DSN)
        with server() as s:
            s.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DB}`"))
            s.execute(
                text(
                    f"CREATE DATABASE `{TEST_DB}` DEFAULT CHARACTER SET utf8mb4 "
                    "DEFAULT COLLATE utf8mb4_unicode_ci"
                )
            )
            s.commit()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MariaDB 에 연결할 수 없어 DB 테스트를 건너뜁니다: {exc}")

    factory = create_session_factory(TEST_DSN)
    with factory() as s:
        for statement in _schema_statements():
            s.execute(text(statement))
        s.commit()

    yield factory

    with factory() as s:
        s.execute(text("SELECT 1"))
    with create_session_factory(SERVER_DSN)() as s:
        s.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DB}`"))
        s.commit()


@pytest.fixture
def db(session_factory):
    """테스트마다 깨끗한 DB 를 준다."""
    with session_factory() as s:
        for table in WIPE_ORDER:
            s.execute(text(f"DELETE FROM `{table}`"))
        s.commit()
    with session_factory() as s:
        yield s


@pytest.fixture
def make_client(session_factory):
    """라우터를 임시 앱에 마운트한 TestClient 를 만든다.

    라이브러리 코드가 앱을 만들지 않으므로 **테스트가 직접 앱을 만든다**.
    이 자체가 마운트 계약(호스트 앱 + `include_router` 한 줄)의 검증이기도 하다.
    """

    def _make(maker_resolver=None, prefix: str = "/api/v1") -> TestClient:
        app = FastAPI()
        app.include_router(
            create_wp_router(
                session_factory=session_factory,
                maker_resolver=maker_resolver,
                prefix=prefix,
            )
        )
        return TestClient(app)

    return _make


@pytest.fixture
def client(make_client):
    return make_client()


# =============================================================================
# 데이터 픽스처
# =============================================================================
class Board:
    """테스트용 보드 한 세트 (템플릿 + 기준정보 + PUBLISHED v1).

    `services.board.Board` 와 이름이 겹치지만 다른 것이다 — 이쪽은 테스트가 만든
    데이터 묶음이고, 저쪽은 서비스가 받는 스코프 기술자다.
    """

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@pytest.fixture
def board(db):
    """Phase 2개 / Milestone 3개 / Owner 2명 / 문서 2건 을 가진 템플릿을 만든다.

    행은 만들지 않는다. 행 배치는 테스트마다 다르므로 각자 구성한다.
    """
    wp = Template(code="TEST-WP", name="테스트 보드", phase_start_no=0)
    db.add(wp)
    db.flush()

    p0 = Phase(template_id=wp.id, name="Pre-Infrastructure Setup", seq_no=0)
    p1 = Phase(template_id=wp.id, name="Initiation & Readiness", seq_no=1)
    db.add_all([p0, p1])
    db.flush()

    m01 = Milestone(template_id=wp.id, phase_id=p0.id, name="환경 Gap", seq_no=1)
    m02 = Milestone(template_id=wp.id, phase_id=p0.id, name="I/O 연결", seq_no=2)
    m11 = Milestone(template_id=wp.id, phase_id=p1.id, name="Scope 정의", seq_no=1)
    db.add_all([m01, m02, m11])

    o1 = Owner(template_id=wp.id, name="DSEP 인프라 담당자", sort_order=1)
    o2 = Owner(template_id=wp.id, name="사내 개발부서", sort_order=2)
    db.add_all([o1, o2])

    # 문서는 §0.5.10 부터 **템플릿 스코프**다 (전역 아님). 표시 번호 = sort_order.
    d1 = TemplateDocument(template_id=wp.id, name="Project Charter & R&R", sort_order=1)
    d2 = TemplateDocument(template_id=wp.id, name="DSEP Readiness & I/O Spec", sort_order=2)
    db.add_all([d1, d2])

    version = Version(
        template_id=wp.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        published_by="test",
        # 발행 버전은 표시 파라미터를 스스로 들고 있어야 한다 (plan.md §2.4).
        phase_start_no=0,
    )
    db.add(version)
    db.commit()

    for entity in (wp, p0, p1, m01, m02, m11, o1, o2, d1, d2, version):
        db.refresh(entity)

    return Board(
        wp=wp, p0=p0, p1=p1, m01=m01, m02=m02, m11=m11,
        o1=o1, o2=o2, d1=d1, d2=d2, published=version,
    )


