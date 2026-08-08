"""스키마 산출물 3종이 서로 어긋나지 않는지 검사한다.

`db/schema.sql` (신규 설치) · `db/migrations/*.sql` (업그레이드) · ORM 모델 —
셋은 같은 것을 말해야 하는데, 서로를 강제하는 장치가 없으면 조용히 갈라진다.
실제로 `wp_versions.phase_start_no` 를 모델과 schema.sql 에만 넣고 live DB 에는
넣지 않아 개발 서버가 멈춘 적이 있다.

**기존 스위트가 이걸 구조적으로 못 잡는 이유**: `conftest.py` 는 매 실행마다
`schema.sql` 로 **새 DB** 를 만든다. 그래서 "ORM 이 기대하는 것 vs 이미 존재하는
DB" 의 어긋남은 영원히 보이지 않는다. 이 파일은 그 사각지대를 직접 겨냥한다.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.database import create_session_factory
from app.models import Base

from conftest import SERVER_DSN, _schema_statements

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"


def _statements(sql: str) -> list[str]:
    out: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            buffer = []
            head = statement.upper()
            if statement and not head.startswith(("CREATE DATABASE", "USE ")):
                out.append(statement)
    tail = "\n".join(buffer).strip()
    if tail:
        out.append(tail)
    return out


def _columns_of(session, database: str) -> dict[str, dict[str, tuple]]:
    rows = session.execute(
        text(
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :db"
        ),
        {"db": database},
    ).all()
    shape: dict[str, dict[str, tuple]] = {}
    for table, column, ctype, nullable in rows:
        shape.setdefault(table, {})[column] = (ctype, nullable)
    return shape


class _ScratchDb:
    """일회용 DB. 배포 대상(`iai-test`)을 절대 건드리지 않는다.

    이름에 pid 를 붙인다 — 고정 이름을 쓰면 두 pytest 가 동시에 돌 때
    서로의 DB 를 DROP 한다 (`iai_test_pytest` 에서 실제로 겪은 일).
    """

    def __init__(self, name: str):
        self.name = f"{name}_{os.getpid()}"
        self._server = create_session_factory(SERVER_DSN)

    def __enter__(self):
        with self._server() as s:
            s.execute(text(f"DROP DATABASE IF EXISTS `{self.name}`"))
            s.execute(
                text(
                    f"CREATE DATABASE `{self.name}` DEFAULT CHARACTER SET utf8mb4 "
                    "DEFAULT COLLATE utf8mb4_unicode_ci"
                )
            )
            s.commit()
        return self

    def apply(self, statements: list[str]) -> None:
        with self._server() as s:
            s.execute(text(f"USE `{self.name}`"))
            for statement in statements:
                s.execute(text(statement))
            s.commit()

    def columns(self) -> dict[str, dict[str, tuple]]:
        with self._server() as s:
            return _columns_of(s, self.name)

    def __exit__(self, *exc):
        with self._server() as s:
            s.execute(text(f"DROP DATABASE IF EXISTS `{self.name}`"))
            s.commit()


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


# =============================================================================
# schema.sql == 마이그레이션 전부 적용
# =============================================================================
def test_migrations_reproduce_schema_sql():
    """신규 설치 경로와 업그레이드 경로가 같은 스키마에 도달해야 한다.

    이 테스트가 있으면 컬럼을 추가하면서 마이그레이션을 빠뜨릴 수 없다.
    """
    with _ScratchDb("iai_schema_fresh") as fresh, _ScratchDb("iai_schema_migrated") as migrated:
        fresh.apply(_schema_statements())
        for path in migration_files():
            migrated.apply(_statements(path.read_text(encoding="utf-8")))

        assert fresh.columns() == migrated.columns(), (
            "db/schema.sql 과 db/migrations/ 의 결과가 다르다 — "
            "컬럼을 추가하면서 한쪽을 빠뜨렸을 가능성이 높다"
        )


def test_migrations_cover_every_orm_column():
    """업그레이드 경로만 밟은 DB 도 ORM 이 기대하는 컬럼을 전부 가져야 한다."""
    with _ScratchDb("iai_schema_orm") as db:
        for path in migration_files():
            db.apply(_statements(path.read_text(encoding="utf-8")))
        shape = db.columns()

        missing: list[str] = []
        for table_name, table in Base.metadata.tables.items():
            if table_name not in shape:
                missing.append(table_name)
                continue
            missing += [
                f"{table_name}.{c.name}" for c in table.columns if c.name not in shape[table_name]
            ]
        assert missing == [], f"마이그레이션에 빠진 ORM 컬럼: {missing}"


def test_migrations_are_re_runnable():
    """같은 마이그레이션을 두 번 돌려도 깨지지 않아야 한다 (호스트 재시도 대비)."""
    with _ScratchDb("iai_schema_twice") as db:
        files = [_statements(p.read_text(encoding="utf-8")) for p in migration_files()]
        for statements in files:
            db.apply(statements)
        before = db.columns()
        for statements in files:
            db.apply(statements)
        assert db.columns() == before


def test_schema_sql_cannot_upgrade_an_existing_database():
    """**schema.sql 은 설치 전용이다.**

    `CREATE TABLE IF NOT EXISTS` 라서 기존 DB 에 다시 돌려도 컬럼이 추가되지
    않는다 — 조용히 아무 일도 일어나지 않는다. 이 함정을 문서가 아니라 테스트로
    박아 둔다. 업그레이드는 반드시 db/migrations/ 로 한다.

    재기준선(001 이 002 를 흡수) 이후로는 "나중 마이그레이션이 더한 컬럼" 이라는
    자연스러운 소재가 없다. 그래서 **컬럼을 직접 떨어뜨려** 같은 성질을 확인한다 —
    소재가 사라졌다고 검사를 지우면, 정작 다음에 컬럼을 추가할 때 이 함정을 잡아
    줄 것이 없다.
    """
    with _ScratchDb("iai_schema_upgrade") as db:
        db.apply(_statements((MIGRATIONS_DIR / "001_initial.sql").read_text(encoding="utf-8")))
        assert "phase_start_no" in db.columns()["wp_versions"]

        db.apply(["ALTER TABLE `wp_versions` DROP COLUMN `phase_start_no`"])
        assert "phase_start_no" not in db.columns()["wp_versions"]

        db.apply(_schema_statements())          # 설치용 DDL 을 업그레이드처럼 사용
        assert "phase_start_no" not in db.columns()["wp_versions"], (
            "schema.sql 이 기존 DB 를 올릴 수 있다면 이 테스트의 전제가 바뀐 것이다"
        )


# =============================================================================
# verify.py 의 스키마 드리프트 검사가 실제로 드리프트를 잡는가
# =============================================================================
def _load_verify():
    spec = importlib.util.spec_from_file_location("wp_verify", REPO_ROOT / "db" / "verify.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_verify_detects_a_missing_column(monkeypatch):
    """건강한 경우에만 확인한 검사기는 쓸모가 없다. 아픈 경우로 확인한다."""
    verify = _load_verify()

    with _ScratchDb("iai_schema_drift") as db:
        db.apply(_schema_statements())
        monkeypatch.setattr(verify.migrate, "DB_NAME", db.name)

        factory = create_session_factory(SERVER_DSN)
        with factory() as s:
            s.execute(text(f"USE `{db.name}`"))
            cursor = s.connection().connection.cursor()

            assert verify.check_schema(cursor) == []          # 멀쩡한 상태

            s.execute(text("ALTER TABLE `wp_versions` DROP COLUMN `phase_start_no`"))
            s.commit()

            problems = verify.check_schema(cursor)
            assert [p["kind"] for p in problems] == ["missing_column"]
            assert problems[0]["table"] == "wp_versions"
            assert problems[0]["columns"] == ["phase_start_no"]
