"""이식용 번들 생성 — 호스트 프로젝트에 넣을 파일만 골라 복사하고 **검증**한다.

`TRANSPLANT.md` §1/§3.2 의 목록을 사람이 손으로 옮기는 대신 한 번에 만든다.
수동 복사의 실제 위험은 파일을 빠뜨리는 것이 아니라 **지워야 할 것을 남기는 것**이다:
`standalone.py` 하나가 따라가면 호스트 앱과 `FastAPI()` 가 충돌하고, `stub_maker_resolver.py`
가 남으면 호스트에 없는 `wp_dev_makers` 를 조회한다. 그래서 복사보다 **복사 후 감사**가
이 스크립트의 요점이다.

사용법::

    python tools/export_transplant.py                 # _transplant/ 에 생성
    python tools/export_transplant.py --out ../host   # 다른 위치에
    python tools/export_transplant.py --frontend      # dist-remote/ 도 함께 (미리 빌드 필요)
    python tools/export_transplant.py --check-only    # 이미 만든 번들만 다시 감사

생성물::

    <out>/backend/app/          FastAPI 모듈 — 개발 전용 파일 제거됨
    <out>/db/transplant.sql     호스트 DB 용 DDL (신규 설치)
    <out>/db/migrations/        번호순 마이그레이션 (기존 설치 업그레이드)
    <out>/docs/                 INTEGRATION.md · backend/INTEGRATION.md · TRANSPLANT.md
    <out>/frontend/dist-remote/ (--frontend 일 때) Module Federation remote

**이 스크립트는 개발 도구다.** 호스트로 가져가지 않는다.
"""

from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: 이식 시 반드시 빠져야 하는 파일 — `backend/tests/test_transplant_contract.py` 와 같은 목록.
#: 여기와 저기가 갈리면 계약 테스트는 통과하는데 번들은 오염된 상태가 된다.
DEV_ONLY = {"standalone.py", "stub_maker_resolver.py"}

#: 복사에서 통째로 제외할 디렉터리 이름.
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def log(message: str) -> None:
    print(message)


# =============================================================================
# 복사
# =============================================================================
def copy_backend(out: Path) -> Path:
    """`backend/app/` 을 옮기되 개발 전용 파일은 두고 온다.

    `shutil.copytree(ignore=...)` 로 **애초에 복사하지 않는다.** 복사한 뒤 지우는 방식은
    중간에 죽으면 오염된 번들을 남기고, 그 상태가 정상과 구분되지 않는다.
    """
    target = out / "backend" / "app"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in SKIP_DIRS or n in DEV_ONLY}

    shutil.copytree(REPO / "backend" / "app", target, ignore=ignore)
    return target


def copy_db(out: Path) -> None:
    db_out = out / "db"
    db_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "db" / "transplant.sql", db_out / "transplant.sql")

    migrations = db_out / "migrations"
    if migrations.exists():
        shutil.rmtree(migrations)
    shutil.copytree(
        REPO / "db" / "migrations",
        migrations,
        ignore=lambda _d, names: {n for n in names if n in SKIP_DIRS},
    )


def copy_docs(out: Path) -> None:
    docs = out / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "INTEGRATION.md", docs / "INTEGRATION.md")
    shutil.copy2(REPO / "TRANSPLANT.md", docs / "TRANSPLANT.md")
    shutil.copy2(REPO / "backend" / "INTEGRATION.md", docs / "backend-INTEGRATION.md")
    shutil.copy2(REPO / "frontend" / "INTEGRATION.md", docs / "frontend-INTEGRATION.md")
    shutil.copy2(REPO / "backend" / "requirements.txt", docs / "backend-requirements.txt")


def copy_frontend(out: Path) -> bool:
    """빌드 산출물만 옮긴다. 소스는 호스트에 가지 않는다 (federation remote)."""
    source = REPO / "frontend" / "dist-remote"
    if not source.exists():
        return False
    target = out / "frontend" / "dist-remote"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return True


# =============================================================================
# 감사 — 복사가 아니라 이쪽이 이 스크립트의 존재 이유다
# =============================================================================
def audit(app_dir: Path) -> list[str]:
    """번들이 이식 계약을 지키는지 본다 (`INTEGRATION.md` §4).

    `test_transplant_contract.py` 와 같은 규칙이되 **번들을 대상으로** 돌린다. 저장소는
    통과하는데 번들은 오염된 경우(개발 전용 파일이 따라간 경우)를 잡는 것이 목적이므로,
    저장소 테스트로는 대신할 수 없다.
    """
    problems: list[str] = []
    sources = sorted(app_dir.rglob("*.py"))

    if not sources:
        return [f"복사된 파이썬 파일이 없다: {app_dir}"]

    # ① 개발 전용 파일이 따라오지 않았는가
    for path in sources:
        if path.name in DEV_ONLY:
            problems.append(f"개발 전용 파일이 남았다: {path.relative_to(app_dir).as_posix()}")

    trees: list[tuple[Path, ast.Module]] = []
    for path in sources:
        try:
            trees.append((path, ast.parse(path.read_text(encoding="utf-8"))))
        except SyntaxError as exc:  # pragma: no cover - 복사 손상 방어
            problems.append(f"파싱 실패: {path.relative_to(app_dir).as_posix()} — {exc}")

    # ② 앱을 만드는 코드가 없는가. 문자열 검색이 아니라 AST 로 본다 — 이 저장소의
    #    docstring 은 금지 대상을 **설명하느라** 그 문자열을 그대로 담고 있다.
    for path, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                getattr(node.func, "id", None) == "FastAPI"
                or getattr(node.func, "attr", None) == "FastAPI"
            ):
                problems.append(
                    f"FastAPI() 인스턴스: {path.relative_to(app_dir).as_posix()}:{node.lineno}"
                )

    # ③ 환경변수를 직접 읽지 않는가 (설정은 `WP_` 접두 pydantic-settings 를 통해서만)
    for path, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                problems.append(
                    f"환경변수 직접 조회: {path.relative_to(app_dir).as_posix()}:{node.lineno}"
                )

    # ④ 개발 스텁 테이블을 아는 코드가 없는가
    for path in sources:
        if "wp_dev_makers" in path.read_text(encoding="utf-8"):
            problems.append(f"wp_dev_makers 참조: {path.relative_to(app_dir).as_posix()}")

    # ⑤ 설비사 테이블로 JOIN 하지 않는가 (INTEGRATION.md §2.1)
    joined = "\n".join(p.read_text(encoding="utf-8") for p in sources)
    if "JOIN makers" in joined or "join(Maker" in joined:
        problems.append("설비사 테이블 JOIN 이 있다 (INTEGRATION.md §2.1 위반)")

    # ⑥ 접속 정보 파일이 딸려오지 않았는가
    for stray in list(app_dir.parent.rglob(".env")) + list(app_dir.parent.rglob(".env.*")):
        problems.append(f"접속 정보 파일이 따라왔다: {stray}")

    return problems


def strip_sql_comments(sql: str) -> str:
    """`--` 줄 주석과 `/* */` 블록을 걷어낸다.

    **주석을 먼저 지우지 않으면 이 파일이 스스로를 위반으로 잡는다.** `transplant.sql` 의
    머리말은 "schema.sql 에서 CREATE DATABASE / USE 를 제거했다", "wp_dev_makers 는
    dev_seed.sql 에만 있다" 처럼 **금지 대상을 설명하느라** 그 문자열을 그대로 담고 있다.
    실제로 첫 실행에서 오탐 2건이 나왔고, 셋 다 주석이었다. `domCheck` 의 CSS 선택자
    감사가 주석부터 지우는 것과 같은 이유다.
    """
    without_block = []
    depth = 0
    index = 0
    while index < len(sql):
        if sql.startswith("/*", index):
            depth += 1
            index += 2
        elif sql.startswith("*/", index) and depth:
            depth -= 1
            index += 2
        else:
            if not depth:
                without_block.append(sql[index])
            index += 1
    lines = "".join(without_block).splitlines()
    return "\n".join(line.split("--", 1)[0] for line in lines)


def audit_sql(out: Path) -> list[str]:
    problems: list[str] = []
    transplant = out / "db" / "transplant.sql"
    if not transplant.exists():
        return [f"없음: {transplant}"]

    statements = strip_sql_comments(transplant.read_text(encoding="utf-8"))
    if "CREATE DATABASE" in statements or "\nUSE " in statements:
        problems.append("transplant.sql 에 CREATE DATABASE / USE 가 남아 있다 (호스트 DB 를 갈아탄다)")
    if "wp_dev_makers" in statements:
        problems.append("transplant.sql 이 개발 스텁 테이블을 만든다")
    if "CREATE TABLE" not in statements:
        problems.append("transplant.sql 에 CREATE TABLE 이 없다")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="_transplant", help="번들 생성 위치 (기본 _transplant)")
    parser.add_argument("--frontend", action="store_true", help="frontend/dist-remote 도 포함")
    parser.add_argument("--check-only", action="store_true", help="복사하지 않고 감사만")
    args = parser.parse_args()

    out = (REPO / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)

    if not args.check_only:
        log(f"번들 생성 → {out}")
        app_dir = copy_backend(out)
        copy_db(out)
        copy_docs(out)
        log(f"  backend/app  : {len(list(app_dir.rglob('*.py')))} files "
            f"(개발 전용 {len(DEV_ONLY)}종 제외)")
        log("  db           : transplant.sql + migrations/")
        log("  docs         : INTEGRATION.md · TRANSPLANT.md · requirements")
        if args.frontend:
            if copy_frontend(out):
                log("  frontend     : dist-remote/")
            else:
                log("  frontend     : ⚠️ dist-remote/ 가 없다 — 먼저 `npm run build:remote`")
    else:
        app_dir = out / "backend" / "app"

    log("")
    log("감사 (이식 계약):")
    problems = audit(app_dir) + audit_sql(out)
    if problems:
        for problem in problems:
            log(f"  ✗ {problem}")
        log("")
        log(f"{len(problems)}건. 이 상태로 호스트에 넣지 말 것.")
        return 1

    log("  ✓ 개발 전용 파일 없음 (standalone.py · stub_maker_resolver.py)")
    log("  ✓ FastAPI() 인스턴스 없음 — 호스트 앱과 충돌하지 않는다")
    log("  ✓ 환경변수 직접 조회 없음 — 호스트가 세션 팩토리만 주입하면 된다")
    log("  ✓ wp_dev_makers 참조 없음 · 설비사 테이블 JOIN 없음")
    log("  ✓ 접속 정보 파일 없음")
    log("  ✓ transplant.sql: CREATE DATABASE/USE 없음, 개발 스텁 없음")
    log("")
    log("다음: docs/TRANSPLANT.md §3.3(MakerResolver 구현) → §3.4(마운트) → §5(체크리스트)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
