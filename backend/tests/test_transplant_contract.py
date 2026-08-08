"""이식 계약(INTEGRATION.md)을 코드로 못박는다.

여기 있는 규칙들은 **조용히 어긋나기 쉽다.** 누군가 편의상 `FastAPI()` 를 하나
만들거나, 설비사 테이블로 JOIN 을 하나 추가해도 기능 테스트는 전부 통과한다.
그래서 별도 파일로 둔다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import create_wp_router
from app.core.config import WpSettings
from app.models import Base

APP_DIR = Path(__file__).resolve().parents[1] / "app"
DB_DIR = Path(__file__).resolve().parents[2] / "db"

#: 앱을 만들어도 되는 유일한 파일 (개발 전용)
DEV_ONLY_FILES = {"standalone.py"}
#: 개발 전용 설비사 스텁을 참조해도 되는 유일한 파일
STUB_ONLY_FILES = {"stub_maker_resolver.py"}


def library_sources() -> list[Path]:
    return [p for p in APP_DIR.rglob("*.py") if p.name not in DEV_ONLY_FILES]


def trees() -> list[tuple[Path, ast.Module]]:
    """소스를 AST 로 읽는다.

    문자열 검색으로는 안 된다 — 이 저장소의 docstring 은 "`FastAPI()` 를 만들지
    않는다" 처럼 금지 대상을 **설명하느라** 그 문자열을 그대로 담고 있어서
    자기 자신이 위반으로 잡힌다.
    """
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in library_sources()]


# =============================================================================
# §4 — 애플리케이션이 아니라 모듈이다
# =============================================================================
def test_no_fastapi_instance_in_library_code():
    """`FastAPI()` 와 `fastapi.FastAPI()` 를 모두 잡는다.

    이름만 보던 판정은 속성 호출 형태를 놓쳤다. 위반을 통과시키는 계약 테스트는
    없는 것보다 나쁘다.
    """
    offenders = [
        f"{path.relative_to(APP_DIR).as_posix()}:{node.lineno}"
        for path, tree in trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", None) == "FastAPI"
            or getattr(node.func, "attr", None) == "FastAPI"
        )
    ]
    assert offenders == [], f"라이브러리 코드에 FastAPI() 인스턴스: {offenders}"


def test_no_module_level_side_effects():
    """import 시점에 엔진 생성·미들웨어·create_all 이 일어나면 안 된다.

    모듈 최상위에 '함수 호출' 자체가 없는지 본다 (데코레이터·상수·클래스 정의 제외).
    """
    # `BoardSpec` 은 **frozen dataclass 생성자**다. `TEMPLATE_BOARD` /
    # `PROJECT_BOARD` 는 어느 테이블 묶음을 쓰는지 적어 둔 상수이며, import 시점에
    # DB 도 네트워크도 건드리지 않는다. 이 예외가 나중에 부작용 있는 함수에
    # 재사용되지 않도록 아래에서 **정말 frozen dataclass 인지** 확인한다.
    allowed_calls = {
        "lru_cache", "dataclass", "field", "runtime_checkable", "TypeVar", "BoardSpec",
    }
    offenders: list[str] = []

    def module_level_statements(body):
        """`try:` / `if:` / `with:` 안에 숨은 최상위 실행문까지 펼친다.

        `tree.body` 만 훑던 판정은 `try: engine = create_engine(...)` 같은 형태를
        그냥 통과시켰다 — 실제로는 import 시점에 실행되는데도.
        """
        for node in body:
            if isinstance(node, (ast.Try, ast.If, ast.With)):
                yield from module_level_statements(node.body)
                yield from module_level_statements(getattr(node, "orelse", []))
                yield from module_level_statements(getattr(node, "finalbody", []))
                for handler in getattr(node, "handlers", []):
                    yield from module_level_statements(handler.body)
            else:
                yield node

    for path, tree in trees():
        for node in module_level_statements(tree.body):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            name = getattr(value.func, "id", None) or getattr(value.func, "attr", None)
            if name not in allowed_calls:
                offenders.append(f"{path.relative_to(APP_DIR).as_posix()}:{node.lineno} {name}()")

    assert offenders == [], f"import 시점 부작용 의심: {offenders}"


def test_the_board_spec_allowance_is_still_a_frozen_dataclass():
    """위 예외 목록의 `BoardSpec` 이 여전히 무해한지 확인한다.

    "허용 목록에 이름을 올린다" 는 것은 검사를 그만큼 약하게 만드는 일이다.
    그 이름이 나중에 부작용 있는 무언가로 바뀌면 `test_no_module_level_side_effects`
    가 조용히 통과해 버린다. 그래서 예외의 **근거**를 따로 고정한다.
    """
    import dataclasses

    from app.services.board import PROJECT_BOARD, TEMPLATE_BOARD, BoardSpec

    assert dataclasses.is_dataclass(BoardSpec)
    assert BoardSpec.__dataclass_params__.frozen is True
    # 상수는 모델 클래스와 컬럼 이름만 담는다 — 세션도 엔진도 들고 있지 않다.
    for spec in (TEMPLATE_BOARD, PROJECT_BOARD):
        assert isinstance(spec.item_scope_attr, str)
        assert isinstance(spec.master_scope_attr, str)


def test_packages_use_relative_imports_only():
    """`from app.x import y` 를 쓰면 다른 부모 경로 아래로 옮겼을 때 깨진다."""
    offenders = [
        f"{path.relative_to(APP_DIR).as_posix()}:{node.lineno}"
        for path, tree in trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and (node.module or "").startswith("app")
    ]
    assert offenders == [], f"절대 import 사용: {offenders}"


def test_settings_are_namespaced_under_wp():
    assert WpSettings.model_config["env_prefix"] == "WP_"


def test_no_direct_environ_access_anywhere_in_the_package():
    """설정은 `WP_` 접두 pydantic-settings 를 통해서만 읽는다.

    **개발 전용 파일까지 포함해 검사한다.** 예전에는 `standalone.py` 를 면제했고
    그 안에 도달 불가능한 `os.environ.get("WP_DB_DSN")` 폴백이 남아 있었다.
    죽은 코드였지만 저장소에 남은 유일한 직접 조회였고, 급히 설정 하나가
    필요할 때 복사해 갈 본보기가 된다. 남겨 둘 이유가 없으므로 면제도 없앤다.
    """
    offenders = [
        f"{path.relative_to(APP_DIR).as_posix()}:{node.lineno}"
        for path in APP_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}
    ]
    assert offenders == [], f"환경변수 직접 조회: {offenders}"


def test_only_standalone_reads_settings():
    """`WP_*` 환경변수는 **라이브러리 경로에 필요 없다** — 이 사실을 고정한다.

    루트 계약이 "호스트는 세션 팩토리만 넘기면 되고 환경변수 설정은 불필요"
    라고 단언하는 근거다. 서비스나 API 가 `get_settings()` 를 하나라도 부르기
    시작하면 그 단언이 조용히 거짓이 되므로, 호출 지점을 여기서 못박는다.
    """
    callers = {
        path.relative_to(APP_DIR).as_posix()
        for path in APP_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "get_settings"
    }
    assert callers == {"standalone.py"}, (
        f"`get_settings()` 는 개발 전용 앱에서만 불려야 한다. 실제 호출: {sorted(callers)}"
    )


def test_the_router_factory_needs_nothing_but_a_session_factory(session_factory):
    router = create_wp_router(session_factory=session_factory)
    assert router.prefix == "/api/v1"

    # OpenAPI 스키마로 확인한다. FastAPI 가 include_router 를 지연 처리하므로
    # `app.routes` 를 직접 훑으면 아직 펼쳐지지 않은 항목이 섞인다.
    app = FastAPI()
    app.include_router(router)
    paths = set(app.openapi()["paths"])

    assert "/api/v1/templates" in paths
    assert "/api/v1/versions/{version_id}/items/reorder" in paths
    # §0.5.10 — 전역 문서 마스터 경로는 폐기됐다.
    assert "/api/v1/versions/{version_id}/documents/apply" in paths


def test_two_routers_can_be_mounted_side_by_side(session_factory):
    """모듈 전역 가변 상태가 있다면 두 마운트가 서로를 덮어쓴다."""
    app = FastAPI()
    app.include_router(create_wp_router(session_factory=session_factory, prefix="/a/v1"))
    app.include_router(create_wp_router(session_factory=session_factory, prefix="/b/v1"))

    client = TestClient(app)
    assert client.get("/a/v1/templates").status_code == 200
    assert client.get("/b/v1/templates").status_code == 200


def test_prefix_is_configurable(session_factory):
    app = FastAPI()
    app.include_router(create_wp_router(session_factory=session_factory, prefix="/host/wp"))
    assert TestClient(app).get("/host/wp/templates").status_code == 200


# =============================================================================
# §2 / §4 — 테이블 소유 경계
# =============================================================================
def test_every_table_is_wp_prefixed():
    bad = [name for name in Base.metadata.tables if not name.startswith("wp_")]
    assert bad == [], f"`wp_` 접두가 없는 테이블: {bad}"


def test_no_foreign_key_points_outside_this_module():
    """호스트 테이블(특히 설비사)로 향하는 FK 가 없어야 이식 DDL 이 통과한다."""
    owned = set(Base.metadata.tables)
    escaping = [
        f"{table.name}.{fk.parent.name} -> {fk.column.table.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name not in owned
    ]
    assert escaping == [], f"모듈 밖으로 나가는 FK: {escaping}"


def test_maker_id_has_an_index_but_no_foreign_key():
    """설비사 참조가 있는 테이블은 **정확히 둘**이고, 어느 쪽도 물리 FK 가 없다.

    호스트가 `maker_id` 타입을 바꿀 때 손댈 컬럼의 개수를 고정하는 검사다.
    `wp_projects` 하나였다가 §0.6 의 `wp_maker_settings` 로 둘이 됐다 — 호스트
    `makers` 테이블에 컬럼을 더할 수 없어 우리 쪽 표시 설정을 별도 테이블에
    둬야 했기 때문이다. **더 늘어나면 여기서 먼저 깨진다.**

    두 컬럼 모두 인덱스는 있어야 한다 (`wp_maker_settings` 는 UNIQUE 가 겸한다).
    """
    carrying = sorted(
        name for name, table in Base.metadata.tables.items() if "maker_id" in table.columns
    )
    assert carrying == ["wp_maker_settings", "wp_projects"], (
        f"maker_id 를 가진 테이블이 바뀌었다: {carrying}"
    )

    for name in carrying:
        maker_id = Base.metadata.tables[name].c.maker_id
        assert maker_id.foreign_keys == set(), f"{name}.maker_id 에 물리 FK 가 걸려 있다"
        assert maker_id.nullable is False

    projects = Base.metadata.tables["wp_projects"].c.maker_id
    assert projects.index is True, "maker_id 인덱스가 없다 — 조회는 항상 maker_id 로 필터링된다"
    settings = Base.metadata.tables["wp_maker_settings"].c.maker_id
    assert settings.unique is True, "설비사 하나에 설정 하나 — UNIQUE 가 없으면 업서트가 깨진다"


def test_no_maker_master_table_is_declared_here():
    """**설비사 자체**를 선언하지 않는다 (INTEGRATION.md §2).

    "이름에 maker 가 들어가면 실패" 로는 더 이상 안 된다 — §0.6 의
    `wp_maker_settings` 는 설비사 마스터가 아니라 `maker_id` 를 키로 하는 우리
    쪽 부가 상태다. 그래서 판정을 **이름이 아니라 내용**으로 바꾼다: 설비사의
    신원(이름/코드)을 담은 테이블이 있으면 실패. 그것이 있다는 것은 호스트
    테이블을 여기서 복제했다는 뜻이고, 그 순간 어느 쪽이 정본인지 모르게 된다.
    """
    identity_columns = {"maker", "maker_ko", "maker_en", "maker_alias", "maker_name"}
    offenders = [
        name
        for name, table in Base.metadata.tables.items()
        if identity_columns & set(table.columns.keys())
        or (name.rstrip("s").endswith("maker"))
    ]
    assert offenders == [], f"설비사 마스터를 선언했다: {offenders}"


def test_schema_sql_does_not_contain_the_dev_maker_stub():
    schema = (DB_DIR / "schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE" in schema
    assert "wp_dev_makers" not in schema.replace("wp_dev_makers 는", "")


def test_the_dev_maker_stub_lives_only_in_dev_seed():
    assert "wp_dev_makers" in (DB_DIR / "dev_seed.sql").read_text(encoding="utf-8")


def test_only_the_stub_resolver_reads_the_dev_maker_table():
    """이식 시 함께 지워질 파일(`standalone.py`, 스텁)만 이 테이블을 알아도 된다."""
    offenders = [
        path.relative_to(APP_DIR).as_posix()
        for path in library_sources()
        if path.name not in STUB_ONLY_FILES and "wp_dev_makers" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"wp_dev_makers 를 참조하는 다른 코드: {offenders}"


def test_no_sql_joins_to_a_maker_table():
    sources = "\n".join(p.read_text(encoding="utf-8") for p in library_sources())
    assert "JOIN makers" not in sources
    assert "join(Maker" not in sources


# =============================================================================
# §3 (문서 마스터 이음매) 는 **폐기됐다** — plan.md §0.5.10.
#
# 전역 문서가 사라지고 문서가 템플릿 소유가 되면서 "호스트 문서 마스터와의 병합
# 지점" 자체가 없어졌다. `document_type_repository_factory` 주입 파라미터도 함께
# 제거됐다. 아래가 그 부재를 고정한다 — 되살아나면 깨진다.
# =============================================================================
def test_no_document_repository_seam_remains():
    """리포지토리 패키지도, 주입 파라미터도 없어야 한다."""
    import inspect

    assert not (APP_DIR / "repositories").exists(), "리포지토리 패키지가 되살아났다"
    params = set(inspect.signature(create_wp_router).parameters)
    assert "document_type_repository_factory" not in params
    assert params == {"session_factory", "maker_resolver", "prefix", "tags"}


def test_documents_are_board_scoped_not_global():
    """문서 테이블이 템플릿·프로젝트 스코프 컬럼을 갖는지 (전역이 아닌지)."""
    from app.models import Base

    assert "wp_document_types" not in Base.metadata.tables
    assert "template_id" in Base.metadata.tables["wp_template_documents"].columns
    assert "project_id" in Base.metadata.tables["wp_project_documents"].columns


def test_error_detail_keys_never_collide_with_the_envelope():
    """오류 본문은 평평하다 — `detail` 의 키가 봉투 키를 덮어쓰면 안 된다.

    `WpError.to_payload()` 가 dict `detail` 을 최상위로 펼치므로, `code` 나
    `message` 를 담은 detail 이 생기면 오류 코드가 조용히 바뀐다.
    """
    import app.services.item_service as item_service
    import app.services.master_service as master_service
    import app.services.version_service as version_service

    reserved = {"code", "message"}
    offenders: list[str] = []

    for module in (item_service, master_service, version_service):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.keyword) and node.arg == "detail"):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and key.value in reserved:
                    offenders.append(
                        f"{Path(module.__file__).name}:{node.value.lineno} detail['{key.value}']"
                    )
    assert offenders == [], f"봉투 키와 충돌하는 detail: {offenders}"


def test_publish_failure_and_validate_share_one_shape(client, board, db):
    """`POST /validate` 와 발행 422 가 같은 형태여야 프론트가 파서를 하나만 갖는다."""
    from app.models import Item

    db.add(Item(version_id=board.published.id, sort_order=1, title="제목"))
    db.commit()

    from app.services import version_service

    draft = version_service.create_draft(db, board.wp.id)
    db.commit()

    preview = client.post(f"/api/v1/versions/{draft.id}/validate").json()
    failure = client.post(f"/api/v1/versions/{draft.id}/publish")

    assert failure.status_code == 422
    body = failure.json()["detail"]
    assert set(preview) <= set(body), "발행 실패 본문이 /validate 형태를 포함하지 않는다"
    assert {e["code"] for e in body["errors"]} == {e["code"] for e in preview["errors"]}
