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
import re
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


def copy_frontend_remote(out: Path) -> bool:
    """Module Federation 방식 — 빌드 산출물만. 소스는 호스트에 가지 않는다."""
    source = REPO / "frontend" / "dist-remote"
    if not source.exists():
        return False
    target = out / "frontend" / "dist-remote"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return True


#: 소스 복사 시 **가져가지 않는** 디렉터리. 개발 하니스와 목은 배포 대상이 아니다.
FRONTEND_DEV_DIRS = {"dev", "mock"}

#: 빌드된 스타일시트를 찾을 순서. 앞쪽일수록 배포 빌드에 가깝다.
BUILT_CSS_CANDIDATES = (
    Path("dist-remote") / "wp-board-remote.css",
    Path("dist") / "wp-board-remote.css",
    Path("dist-check") / "wp-board-remote.css",
)


def find_built_css() -> Path | None:
    for candidate in BUILT_CSS_CANDIDATES:
        path = REPO / "frontend" / candidate
        if path.exists():
            return path
    return None


def copy_frontend_src(out: Path) -> tuple[Path, Path | None]:
    """소스 복사 방식 — `src/` 에서 개발 전용 디렉터리를 뺀 것 + **빌드된 CSS 한 장**.

    CSS 를 소스가 아니라 산출물로 가져가는 이유가 이 방식의 핵심이다. Tailwind 설정은
    **빌드 단위**라 한 빌드에 prefix 를 두 벌 둘 수 없다. 호스트가 이미 Tailwind 를
    기본 설정으로 쓰고 있으면 `prefix: 'wp-'` 를 병합하는 순간 호스트 자신의 유틸리티가
    전부 깨진다. 우리 클래스명(`wp-flex` …)은 이미 빌드된 스타일시트가 정의하고 있으므로,
    호스트는 그 파일을 **한 번 import 하고 우리 디렉터리를 자기 Tailwind `content` 에서
    제외**하면 된다 — 설정 병합이 아예 필요 없어진다.
    """
    target = out / "frontend" / "src"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    def ignore(directory: str, names: list[str]) -> set[str]:
        skip = {n for n in names if n in SKIP_DIRS}
        # `src/` 바로 아래의 dev·mock 만 제외한다. 더 깊은 곳의 같은 이름은 건드리지 않는다.
        if Path(directory).resolve() == (REPO / "frontend" / "src").resolve():
            skip |= {n for n in names if n in FRONTEND_DEV_DIRS}
        return skip

    shutil.copytree(REPO / "frontend" / "src", target, ignore=ignore)

    types_src = REPO / "frontend" / "types" / "wpBoard.d.ts"
    if types_src.exists():
        types_dir = out / "frontend" / "types"
        types_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(types_src, types_dir / "wpBoard.d.ts")

    css = find_built_css()
    if css is not None:
        shutil.copy2(css, out / "frontend" / "wp-board.css")
    return target, css


FRONTEND_DEPS = [
    ("vue", "^3.5.41"),
    ("ant-design-vue", "^4.2.6"),
    ("@ant-design/icons-vue", "^7.0.1"),
    ("ag-grid-community", "33.3.2"),
    ("ag-grid-vue3", "33.3.2"),
    ("axios", "^1.7.9"),
    ("dayjs", "^1.11.13"),
]


def write_frontend_readme(out: Path, css: Path | None) -> None:
    deps = "\n".join(f'    "{name}": "{version}",' for name, version in FRONTEND_DEPS)
    css_note = (
        f"`wp-board.css` 는 `frontend/{css.relative_to(REPO / 'frontend').as_posix()}` 에서 왔다."
        if css is not None
        else "⚠️ **빌드된 CSS 가 없다.** `cd frontend && npm run build` 를 먼저 돌리고 다시 export 할 것."
    )
    (out / "frontend" / "MERGE.md").write_text(
        f"""# 프론트엔드 소스 편입 절차

이 번들은 **소스 복사** 방식이다 (Module Federation 아님).

```
src/          컴포넌트·스토어·API 클라이언트 — dev/ 와 mock/ 은 빠져 있다
types/        wpBoard.d.ts
wp-board.css  빌드된 스타일시트 — {css_note}
```

## 1. 파일 배치

`src/` 를 호스트 프로젝트 안 한 폴더로 옮긴다 (예: `src/modules/wp-board/`).
내부 import 는 전부 상대 경로라 위치는 자유다.

## 2. 스타일 — ⚠️ 여기가 유일한 함정

**호스트의 Tailwind 설정에 우리 설정을 병합하지 말 것.** Tailwind 의 `prefix` 와
`corePlugins.preflight` 는 **빌드 단위 설정**이라 한 빌드에 두 벌을 둘 수 없다. 호스트가
Tailwind 를 기본 설정으로 쓰고 있는데 `prefix: 'wp-'` 를 넣으면 호스트 자신의 유틸리티가
전부 무효가 된다.

대신 **빌드된 스타일시트 한 장을 import** 한다. 우리 클래스명(`wp-flex`, `wp-rounded-xl` …)은
이미 이 파일이 정의하고 있다.

```ts
// 호스트 진입점에서 한 번만
import './modules/wp-board/wp-board.css'
```

그리고 호스트의 `tailwind.config.js` `content` 에서 **이 폴더를 제외**한다. 포함하면
호스트 Tailwind 가 `wp-` 클래스를 자기 규칙으로 다시 만들려다 실패하거나(prefix 불일치)
중복 규칙을 낸다.

```js
content: [
  './src/**/*.{{vue,ts}}',
  '!./src/modules/wp-board/**',   // ← 우리 폴더는 제외
],
```

> 스타일시트는 **`.wp-root` 아래로만** 규칙을 낸다. preflight 가 꺼져 있어 호스트의
> `h1`·`button`·`table` 기본 스타일을 건드리지 않는다 — 이 성질은 `check:dom` 섹션 H 가
> 실제 파일을 읽어 검증한다.
>
> ⚠️ 이 방식은 **우리 소스를 고쳐도 CSS 가 갱신되지 않는다.** `wp-` 클래스를 새로 쓰면
> 원본 저장소에서 `npm run build` 후 `wp-board.css` 를 다시 가져와야 한다. 클래스명을
> 바꾸지 않는 수정(로직·문구)은 그대로 반영된다.

## 3. 의존성

호스트 `package.json` 에 추가한다. **버전은 이 저장소가 검증한 조합**이며, ag-grid 는
`ag-grid-community` 와 `ag-grid-vue3` 의 버전이 **정확히 같아야** 한다.

```json
  "dependencies": {{
{deps}
  }}
```

- ag-grid 는 **Community 플랜만** 쓴다. Enterprise 를 추가하지 말 것 — Row Grouping 대신
  셀 렌더러 + 색 밴딩으로 구현돼 있다 (`CLAUDE.md`).
- antd 의 전역 리셋(`ant-design-vue/dist/reset.css`)은 **import 하지 않는다.** 호스트
  스타일을 덮어쓴다.

## 4. 컴포넌트 사용

노출은 넷이다. `src/index.ts` 가 그대로 진입점이다.

```ts
import {{ ProjectsOverview, ProjectWorkspace, MasterAdmin, MakerSettings }}
  from './modules/wp-board/src'
```

| 컴포넌트 | 호스트 메뉴 | 필수 prop |
|---|---|---|
| `ProjectsOverview` | 전체 현황 (기본 진입) | `onOpenProject(projectId, makerId)` |
| `ProjectWorkspace` | (메뉴 없음 — 위 콜백으로만 진입) | `makerId` · `projectId` |
| `MasterAdmin` | Work Package 포맷 관리 | — |
| `MakerSettings` | Integrated AI 참여 설비사 관리 | — |

API 주소는 **런타임에** `apiBaseUrl` prop 으로 준다 (`import.meta.env` 를 모듈 스코프에서
읽지 않는다 — 그러면 개발값이 번들에 박힌다). `/api/v1` 은 클라이언트가 붙이므로 **넣지 말 것.**

미저장 가드는 `hasUnsavedChanges()` 인스턴스 메서드를 호스트 라우터에 연결한다.

자세한 계약은 `../docs/frontend-INTEGRATION.md`.
""",
        encoding="utf-8",
    )


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


def strip_js_comments(source: str) -> str:
    """`/* */` 블록, `//` 로 시작하는 줄, `<!-- -->` 를 걷어낸다.

    문자열 안의 `//` 는 건드리지 않는다 — 줄 **전체**가 주석인 경우만 지운다. `'http://…'`
    같은 값이 있는 줄을 반토막 내면 오히려 없는 위반을 만들어낸다.

    이 저장소의 주석은 금지 대상을 *설명하느라* 그 이름을 그대로 담고 있다. 실제로
    `import.meta.env` 3건, `vue-router` 5건이 전부 주석이었다 — 걷어내지 않으면 멀쩡한
    번들이 위반 8건으로 보고된다.
    """
    text = re.sub(r"/\*[\s\S]*?\*/", "", source)
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def audit_frontend_src(src_dir: Path) -> list[str]:
    """소스 복사 방식의 계약 감사 (`frontend/INTEGRATION.md` §5)."""
    problems: list[str] = []
    if not src_dir.exists():
        return [f"복사된 프론트 소스가 없다: {src_dir}"]

    for name in FRONTEND_DEV_DIRS:
        if (src_dir / name).exists():
            problems.append(f"개발 전용 디렉터리가 남았다: src/{name}/")

    files = [p for p in src_dir.rglob("*") if p.suffix in {".ts", ".vue", ".tsx", ".js"}]
    if not files:
        return problems + [f"복사된 소스 파일이 없다: {src_dir}"]

    for path in files:
        code = strip_js_comments(path.read_text(encoding="utf-8"))
        where = path.relative_to(src_dir).as_posix()

        # 개발 전용 디렉터리로의 import 가 남아 있으면 호스트 빌드가 깨진다.
        if re.search(r"""from\s+['"][^'"]*/(dev|mock)/""", code):
            problems.append(f"제거된 디렉터리를 import 한다: {where}")

        # 번들 타임 환경변수 — 개발값이 그대로 박힌다 (§5).
        if "import.meta.env" in code:
            problems.append(f"import.meta.env 를 읽는다: {where}")

        # 라우팅은 호스트 소유다.
        if re.search(r"""from\s+['"]vue-router['"]""", code):
            problems.append(f"vue-router 를 import 한다: {where}")

        # antd 전역 리셋은 호스트 스타일을 덮어쓴다.
        if "ant-design-vue/dist/reset" in code:
            problems.append(f"antd 전역 리셋을 import 한다: {where}")

        # **자기완결성** — 상대 import 가 전부 복사본 안에서 풀리는가.
        #
        # 위 패턴 검사보다 이쪽이 결정적이다. `dev/`·`mock/` 을 빼고 나서 어딘가가 아직
        # 그것을 가리키고 있으면 호스트 빌드가 깨지는데, 그 참조가 어떤 문자열 모양인지는
        # 미리 알 수 없다. 실제로 풀어 보면 모양과 무관하게 잡힌다.
        for specifier in re.findall(r"""(?:from|import)\s+['"](\.[^'"]+)['"]""", code):
            if not resolves_within(path, specifier):
                problems.append(f"끊어진 상대 import: {where} → {specifier}")

    return problems


#: TS/Vue 해석 순서. 확장자 없는 지정자와 디렉터리 index 를 모두 시도한다.
_RESOLVE_SUFFIXES = ("", ".ts", ".vue", ".d.ts", ".js", ".tsx", ".css", ".json")


def resolves_within(importer: Path, specifier: str) -> bool:
    base = (importer.parent / specifier).resolve()
    for suffix in _RESOLVE_SUFFIXES:
        if suffix and base.with_name(base.name + suffix).is_file():
            return True
        if not suffix and base.is_file():
            return True
    if base.is_dir():
        for suffix in ("index.ts", "index.vue", "index.js"):
            if (base / suffix).is_file():
                return True
    return False


def audit_frontend_css(out: Path) -> list[str]:
    """스타일시트가 호스트 밖으로 새지 않는지 — `check:dom` 섹션 H 와 같은 규칙."""
    css_path = out / "frontend" / "wp-board.css"
    if not css_path.exists():
        return ["빌드된 wp-board.css 가 없다 — `npm run build` 후 다시 export 할 것"]

    css = css_path.read_text(encoding="utf-8")
    if len(css) < 1000:
        return [f"wp-board.css 가 비정상적으로 작다 ({len(css)} bytes)"]

    stripped = re.sub(r"/\*[\s\S]*?\*/", "", css)
    stripped = re.sub(r"@[a-z-]+[^{]*\{", "{", stripped, flags=re.IGNORECASE)
    escaping: list[str] = []
    for rule in stripped.split("}"):
        for selector in (rule.split("{")[0] or "").split(","):
            selector = selector.strip()
            if not selector or selector in {"from", "to"} or re.fullmatch(r"\d+%", selector):
                continue
            names = [m.replace("\\", "") for m in re.findall(r"\.((?:[\w-]|\\.)+)", selector)]
            if not any(n.startswith("wp-") or ":wp-" in n for n in names):
                escaping.append(selector)
    if escaping:
        unique = sorted(set(escaping))[:5]
        return [f"호스트로 새는 선택자 {len(set(escaping))}종: {unique}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="_transplant", help="번들 생성 위치 (기본 _transplant)")
    parser.add_argument(
        "--frontend",
        choices=("src", "remote", "none"),
        default="src",
        help="프론트 포함 방식: src=소스 복사(기본) · remote=dist-remote/ · none=제외",
    )
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
        if args.frontend == "remote":
            if copy_frontend_remote(out):
                log("  frontend     : dist-remote/")
            else:
                log("  frontend     : ⚠️ dist-remote/ 가 없다 — 먼저 `npm run build:remote`")
        elif args.frontend == "src":
            src_dir, css = copy_frontend_src(out)
            write_frontend_readme(out, css)
            log(f"  frontend/src : {len(list(src_dir.rglob('*.vue'))) + len(list(src_dir.rglob('*.ts')))}"
                f" files (dev/ · mock/ 제외)")
            log(f"  frontend     : wp-board.css {'+ MERGE.md' if css else '없음(빌드 필요) + MERGE.md'}")
    else:
        app_dir = out / "backend" / "app"

    log("")
    log("감사 (이식 계약):")
    problems = audit(app_dir) + audit_sql(out)
    if args.frontend == "src":
        problems += audit_frontend_src(out / "frontend" / "src")
        problems += audit_frontend_css(out)
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
    if args.frontend == "src":
        log("  ✓ 프론트: dev/ · mock/ 없음, import.meta.env · vue-router · antd 리셋 없음")
        log("  ✓ 스타일시트: 모든 선택자가 wp- 로 네임스페이스됨 (호스트로 새지 않는다)")
    log("")
    log("다음: docs/TRANSPLANT.md §3.3(MakerResolver 구현) → §3.4(마운트) → §5(체크리스트)")
    if args.frontend == "src":
        log("      프론트는 frontend/MERGE.md — Tailwind 설정을 병합하지 말 것(§2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
