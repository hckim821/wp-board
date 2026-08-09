# Backend Integration Guide

루트 [`INTEGRATION.md`](../INTEGRATION.md) 의 백엔드 측면 구체화 문서.

이 디렉터리의 코드는 **독립 실행형 애플리케이션이 아니라, 이미 가동 중인 다른
FastAPI 프로젝트에 이식되는 모듈**이다. 호스트가 할 일은 import 한 줄 +
`include_router` 한 줄이 전부다.

## 계층 구조 (plan.md §0)

```
[기준 데이터 — 중앙]  wp_templates ─▶ 버전(DRAFT/PUBLISHED/ARCHIVED) ─▶ 행
                      + phase/milestone/owner (템플릿 스코프)
                      draft 발행 → 저장 → 발행 검증(V1~V14) 은 **여기에만** 있다
                              │  프로젝트 생성 시 전부 deep copy (스냅샷)
                              ▼
[프로젝트 — 설비사별]  wp_projects ─▶ 행 + 프로젝트 로컬 phase/milestone/owner
                      버전 없음. 생성이 곧 확정, 이후 자유 편집.
```

* **설비사 참조는 `wp_projects.maker_id` 한 곳뿐이다.** 템플릿에는 maker 개념이 없다.
* 문서도 복제한다 (§0.5.10) — 전역 공유는 폐기됐다.
* 그리드 규칙(재계산 §2.2 · 경계 §2.3 · 회색 행 §0.2 · 드래그)은 **양쪽이 같다.**
  백엔드도 `item_service` 한 벌을 공유한다 — 스코프만 `Board` 로 주입받는다.
* 라우터는 **여전히 하나**다. 계층이 늘었다고 마운트 지점이 늘지 않는다.

---

## 1. 노출 표면 (Exposed Surface)

호스트가 알아야 할 공개 심볼은 넷뿐이다.

```python
from wp_module.app import create_wp_router, WpDeps, MakerResolver
from wp_module.app.core.database import create_session_factory   # (선택) 편의 함수
```

| 심볼 | 위치 | 역할 |
|---|---|---|
| `create_wp_router(...)` | `app/router.py` | **유일한 진입점.** 배선이 끝난 `APIRouter` 반환 |
| `MakerResolver` | `app/ports/maker_resolver.py` | 설비사 조회 포트 (Protocol). 호스트가 구현 |
| `WpDeps` | `app/deps.py` | 주입 컨테이너. 보통 직접 만질 일은 없다 |
| `create_session_factory(dsn)` | `app/core/database.py` | 호스트에 세션 팩토리가 없을 때만 |

```python
def create_wp_router(
    *,
    session_factory: Callable[[], Session],   # 필수
    maker_resolver: MakerResolver | None = None,
    prefix: str = "/api/v1",
    tags: list[str] | None = None,
) -> APIRouter
```

---

## 2. 배선 (3단계)

```python
# 호스트 프로젝트의 main.py
from wp_module.app import create_wp_router
from .database import SessionLocal          # 호스트가 이미 갖고 있는 것
from .integrations import HostMakerResolver # 아래 §3 참고

app.include_router(
    create_wp_router(
        session_factory=SessionLocal,
        maker_resolver=HostMakerResolver(SessionLocal),
        prefix="/api/v1",
    )
)
```

1. 스키마 적용 — **최초 설치인지 업그레이드인지에 따라 파일이 다르다** (§2.1)
2. 위 코드 두 줄 추가
3. 끝

### 2.1 스키마: 설치와 업그레이드는 다른 파일이다

| 상황 | 적용할 것 |
|---|---|
| 빈 DB 에 처음 설치 | `db/schema.sql` (맨 위 `CREATE DATABASE` / `USE` 두 줄 제거) |
| 이미 적용된 DB 를 올림 | `db/migrations/` 를 번호순으로, 아직 안 돌린 것부터 |

> ⚠️ **`db/schema.sql` 은 설치 전용이다.** `CREATE TABLE IF NOT EXISTS` 를 쓰므로
> 기존 DB 에 다시 실행해도 **아무것도 바뀌지 않는다** — 새 컬럼이 추가되지 않고
> 오류도 나지 않는다. 업그레이드에 쓰면 조용히 실패하고, 그 다음 ORM 읽기가
> `Unknown column` 으로 죽는다. 실제로 그렇게 개발 서버가 멈춘 적이 있다.

**마이그레이션 적용 방법 (호스트 러너)**

산출물은 **평문 SQL** 이다. Alembic 을 쓰지 않는 것은 의도적이다 — 호스트에는
이미 자기 마이그레이션 도구와 자기 버전 테이블이 있고, 우리 도구를 강요하는 것이
바로 이 문서가 막으려는 host coupling 이다.

```bash
# 호스트가 어떤 러너를 쓰든, 하는 일은 "번호순으로 SQL 실행" 이다.
for f in db/migrations/*.sql; do mysql -u USER -p HOSTDB < "$f"; done
```

- 파일명은 `NNN_snake_case.sql`. 이미 적용한 번호는 호스트의 버전 테이블에 기록한다.
- 대부분 재실행 안전하게 작성돼 있다 (`ADD COLUMN IF NOT EXISTS` 등). 이는
  MariaDB 확장이므로, MySQL 호스트를 위한 대안을 각 파일 주석에 적어 두었다.
- 어떤 파일도 `CREATE DATABASE` / `USE` 를 포함하지 않는다.

`db/schema.sql` 은 "001 부터 마지막 마이그레이션까지 전부 적용한 상태" 와 항상
같아야 하며, `backend/tests/test_schema_migrations.py` 가 두 경로로 DB 를 만들어
`information_schema` 를 비교해 강제한다. 컬럼을 추가하면서 마이그레이션을
빠뜨리면 그 테스트가 깨진다.

> **재기준선 (2026-08-07).** `plan.md` §0 이 컨테이너 이름과 소유 관계를 바꾸고
> (`wp_work_packages` → `wp_templates`, `maker_id` 제거) 프로젝트 계층 7개 테이블을
> 들이면서, **001 을 새 스키마로 다시 쓰고 002 를 접어 넣었다.** RENAME/DROP/CREATE 가
> 뒤섞인 거대한 003 을 만드는 대신 그렇게 한 이유는 하나다 — **아직 이 스키마를 채택한
> 호스트가 없다.** 올릴 기존 설치가 없는 마이그레이션에 복잡도를 지불할 이유가 없다.
>
> 이 판단은 그 전제에만 의존한다. 한 곳이라도 채택한 뒤에는 번호를 이어 붙이는 수밖에
> 없다. **이미 이전 스키마를 적용한 DB 가 있다면 001 을 그대로 돌릴 수 없다** — 그
> 경우는 새로 만들어 데이터를 옮기는 편이 빠르다 (테이블 16개, FK 재배선 포함).

**호스트가 하지 않아도 되는 일**

- 예외 핸들러 등록 — `WpAPIRoute` 가 라우터 안에서 도메인 예외를 HTTP 로 변환한다
- 미들웨어 / CORS / 로깅 설정 — 이 모듈은 손대지 않는다
- `Base.metadata.create_all()` — 스키마는 SQL 파일로 관리한다
- 환경변수 설정 — `session_factory` 를 넘기면 설정 없이 동작한다

### 지켜지는 규칙 (테스트로 고정)

`tests/test_transplant_contract.py` 가 아래를 자동 검사한다. 위반하면 테스트가 깨진다.

| 규칙 | 검사 |
|---|---|
| `schema.sql` == 마이그레이션 전부 적용 | 두 경로로 DB 를 만들어 `information_schema` 비교 |
| 마이그레이션이 ORM 컬럼을 전부 덮는다 | `Base.metadata` 대조 |
| 마이그레이션 재실행 안전 | 두 번 적용 후 스키마 동일 |
| 라이브러리 코드에 `FastAPI()` 없음 | AST 로 `FastAPI(...)` 호출 탐색 |
| import 시점 부작용 없음 | 모듈 최상위 함수 호출 금지 (`lru_cache` 등 예외) |
| 패키지 내부는 상대 import | `from app.x import` 사용 금지 |
| 설정은 `WP_` 접두 | `WpSettings.env_prefix` |
| `os.environ` / `os.getenv` 직접 조회 없음 | AST 속성 접근 탐색 |
| 모든 테이블 `wp_` 접두 | `Base.metadata` |
| 모듈 밖으로 나가는 FK 없음 | `Base.metadata` FK 순회 |
| `maker_id` 인덱스 O / 물리 FK X | 컬럼 메타데이터 |
| **`maker_id` 를 가진 테이블은 `wp_projects` 하나뿐** | `Base.metadata` 전수 — 늘어나면 깨진다 |
| 라우터 2개 동시 마운트 가능 | 서로 다른 prefix 로 실제 마운트 |
| 프로젝트에 버전 엔드포인트 없음 | OpenAPI 경로 표에서 `versions`/`publish`/`validate`/`draft` 부재 확인 |

---

## 3. 설비사(Maker) — 호스트가 채워야 할 유일한 구멍

설비사 테이블은 **호스트 소유**다. 이 모듈은 테이블을 만들지 않고, JOIN 하지
않으며, `wp_projects.maker_id` 정수 값까지만 다룬다. 물리 FK 도 없다 —
대상이 다른 스키마에 있을 수 있어 제약을 걸면 이식 DDL 이 실패한다.

> **§0 에서 위치가 바뀌었다.** 예전에는 `wp_work_packages.maker_id` 였다. 템플릿이
> 중앙 기준 데이터가 되면서 설비사 개념이 프로젝트로 내려갔고, 그래서 구멍은
> 여전히 **정확히 하나**다. `test_maker_id_has_an_index_but_no_foreign_key` 가
> `maker_id` 를 가진 테이블이 늘어나지 않는지 함께 확인한다.

```python
class HostMakerResolver:
    def __init__(self, session_factory):
        self._sf = session_factory

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        """찾지 못한 id 는 결과에서 빼면 된다. 예외를 던질 필요 없다."""
        with self._sf() as s:
            rows = s.query(Maker.id, Maker.name).filter(Maker.id.in_(maker_ids)).all()
        return {r.id: r.name for r in rows}

    def exists(self, maker_id: int) -> bool:
        with self._sf() as s:
            return s.query(Maker.id).filter(Maker.id == maker_id).first() is not None
```

**계약**

- **미주입이 정상 상태다.** resolver 가 없으면 응답에서 `maker_name` 이 `null` 이 될
  뿐, 나머지는 그대로 동작한다. 예외를 던지지 않는다.
- **고아 참조가 조회를 깨뜨리지 않는다.** 호스트에 없는 `maker_id` 는 이름만 비운다.
- **구현이 터져도 조회는 성공한다.** `resolve()` 가 예외를 던지면 이름 없이 넘어간다.
  설비사 이름은 부가 정보이지 이 모듈의 정합성 요건이 아니다.
- `exists()` 검증은 resolver 가 주입된 경우에만 수행한다 (프로젝트 생성 시).
- **설비사 1 : N 프로젝트.** 같은 템플릿에서 몇 개를 만들든 서로 독립이다.
- **템플릿 API 는 resolver 를 아예 쓰지 않는다.** 응답에 `maker_id`/`maker_name` 이
  없고, 요청에서도 받지 않는다.

`maker_id` 타입을 `BIGINT` / `VARCHAR` 로 바꿔야 한다면 **`wp_projects.maker_id`
컬럼 하나만** 고치면 된다. 다른 곳에 타입 가정을 퍼뜨리지 않았다.

---

## 4. 문서 — **전역이 아니다** (구 "문서 마스터 병합 지점" 폐기)

**이 절은 폐기됐다** (plan.md §0.5.10, 2026-08-08 사용자 확정).

문서는 전역 `wp_document_types` 였고 호스트 문서 마스터와의 가장 유력한 병합
지점이었다. 이제 Phase/Milestone/Owner 와 **같은 스코프 규칙**을 따른다:

| | 소유 | 복제 |
|---|---|---|
| `wp_template_documents` | 템플릿 | draft 생성 시 **복제 안 함** (버전이 아니라 템플릿에 매인다) |
| `wp_project_documents` | 프로젝트 | 프로젝트 생성 시 발행본에서 **복제** |

- 표시 번호는 `sort_order`(1..N 연속). **원문자 코드(①②)는 폐기**됐다.
- `create_wp_router()` 에서 **`document_type_repository_factory` 파라미터가 사라졌고**
  `app/repositories/` 패키지도 삭제됐다. 호스트가 문서에 대해 할 일은 없다 — 전역
  테이블이 없으므로 충돌할 것도 병합할 것도 없다.
- 링크(`wp_item_documents` / `wp_project_item_documents`)의 FK 는 **CASCADE** 다.
  문서를 지우면 항목 링크가 함께 사라진다 (§0.5.10 삭제 캐스케이드).

`tests/test_transplant_contract.py::test_no_document_repository_seam_remains` 와
`::test_documents_are_board_scoped_not_global` 이 이 부재를 고정한다.

---

## 5. 환경변수 (`WP_` 접두)

라이브러리 경로는 세션 팩토리를 주입받으므로 **환경변수 없이 동작한다.**
아래는 `standalone.py` 와, 굳이 환경변수로 배선하려는 호스트를 위한 것이다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `WP_DB_DSN` | `None` | SQLAlchemy DSN. **기본값에 접속 정보를 넣지 않았다** |
| `WP_API_PREFIX` | `/api/v1` | `create_wp_router(prefix=...)` 가 우선 |
| `WP_ECHO_SQL` | `false` | SQL 로깅 |
| `WP_POOL_PRE_PING` | `true` | |
| `WP_POOL_RECYCLE` | `3600` | |

DSN 주의사항 두 가지 (실측 확인):

- 비밀번호의 `#` 는 **반드시 `%23`** 으로 인코딩한다. 안 하면 DSN 이 조용히 잘린다.
- DB 명 `iai-test` 의 하이픈은 SQLAlchemy DSN 에서는 그대로 써도 되지만,
  **raw SQL 에서는 항상 백틱**이 필요하다.

```
mysql+pymysql://user01:<WP_DB_PASSWORD>@localhost:3306/iai-test?charset=utf8mb4
```

접속 정보는 **저장소에 두지 않는다.** `standalone.py` 에도 하드코딩 폴백이 없어
`WP_DB_DSN` 미설정은 기동 오류다 — 조용히 엉뚱한 DB 에 붙는 것보다 낫다.
개발용 스크립트(`db/migrate.py`·`db/verify.py`·`db/delete_project.py`)와 테스트는
`WP_DB_PASSWORD`(+선택적 `WP_DB_HOST`/`PORT`/`USER`/`NAME`)를 읽는다.

값은 gitignore 된 **`backend/.env`** 에 둔다 (키만 든 `backend/.env.example` 이 커밋본).

> ⚠️ **이식 시 `.env` 는 따라가지 않는다.** `core/config.py` 에는 `env_file` 이 **없고**,
> 라이브러리 코드는 파일에서 설정을 읽지 않는다. `.env` 를 읽는 곳은 개발 전용 진입점뿐이다
> — `app/standalone.py`(삭제 대상) · `tests/` · `db/*.py`(둘 다 이식 대상 아님). `python-dotenv`
> 도 같은 이유로 `requirements-dev.txt` 에만 있다. 호스트는 종전대로 세션 팩토리를 직접
> 주입하며, 환경변수도 `.env` 도 필요 없다.

---

## 6. 의존성 버전

검증 환경: **Python 3.11.14 / MariaDB 11.2.2**

| 패키지 | 선언 범위 | 검증 버전 |
|---|---|---|
| fastapi | `>=0.115,<1.0` | 0.141.1 |
| SQLAlchemy | `>=2.0.30,<2.1` | 2.0.51 |
| pydantic | `>=2.7,<3.0` | 2.13.4 |
| pydantic-settings | `>=2.3,<3.0` | |
| PyMySQL | `>=1.1.1,<2.0` | |
| uvicorn | `>=0.30` | **개발 전용** |

전역 Anaconda 파이썬은 3.8.8 이라 SQLAlchemy 2.x / Pydantic v2 를 돌릴 수 없다.
Python **3.11+** 환경에서 `pip install -r backend/requirements.txt` 로 설치한다. 이 저장소는 가상환경을 포함하지 않는다.

---

## 7. 개발 전용 자산 — 이식 시 삭제

| 파일 | 이유 |
|---|---|
| `app/standalone.py` | **이 저장소에서 `FastAPI()` 를 만드는 유일한 파일.** CORS/미들웨어도 여기만 |
| `app/ports/stub_maker_resolver.py` | `wp_dev_makers` 를 읽는 유일한 코드 |
| `db/dev_seed.sql` | `wp_dev_makers` 테이블 + 스텁 데이터 |
| `db/migrate.py` | 최초 엑셀 임포트 스크립트 (접속 정보를 직접 갖는다) |
| `db/verify.py` | **`migrate.py` 와 반드시 함께 지운다** (아래) |
| `backend/tests/` | |
| `db/schema.sql` 상단 `CREATE DATABASE` / `USE` 2줄 | 호스트 DB 위에서 실행하므로 불필요 |

> ⚠️ **`db/verify.py` 와 `db/migrate.py` 는 한 묶음이다.** `verify.py` 는 모듈
> 최상위에서 `migrate.py` 를 import 해 엑셀 파서를 재사용한다. `migrate.py` 만
> 지우면 `verify.py` 가 **import 시점에 죽는다.** 애초에 `verify.py` 는
> `iai-test` 를 엑셀 원본과 대조하는 도구라 이식 후에는 의미가 없다 — 호스트의
> 데이터는 엑셀에서 온 것이 아니기 때문이다. 둘 다 지우는 것이 맞다.
>
> `db/migrations/` 는 **지우지 않는다.** 그쪽은 호스트가 계속 쓰는 업그레이드
> 경로다 (§2.1).

`db/schema.sql` 본문에는 `wp_dev_makers` 가 **없다** — 운영 스키마와 개발 스텁은
파일 단위로 분리되어 있고, 테스트가 이를 검사한다.

---

## 8. API 표면 — `plan.md` §4.2 의 계약

**이 절은 계약을 기술한다.** 계획서와 다른 점은 §9 에 "차이" 로만 적는다 —
구현에 맞춰 이 절을 고치지 않는다.

모든 경로는 `prefix` 아래에 붙는다 (기본 `/api/v1`).

### 계층 1 — 템플릿 (기준 데이터) / 버전

설비사 개념이 없다. 응답에 `maker_id` 가 없고 요청에서도 받지 않는다.

| Method | Path |
|---|---|
| GET | `/templates` (`?include_inactive=`) |
| POST | `/templates` |
| GET · PUT | `/templates/{id}` |
| GET | `/templates/{id}/versions` |
| POST | `/templates/{id}/versions/draft` |
| GET | `/versions/{vid}` |
| PUT | `/versions/{vid}/items` — 임시저장 (전량 교체, 검증 없음) |
| POST | `/versions/{vid}/validate` |
| POST | `/versions/{vid}/publish` |
| DELETE | `/versions/{vid}` |
| GET | `/versions/{vid}/board.xlsx` — 보드를 **원본 엑셀 양식** XLSX 로 (§0.5.7, 아래) |

**행 조작** — 전부 재계산된 **전체 행 목록**(`{"items": [...]}`)을 반환한다.

| Method | Path | 설명 |
|---|---|---|
| POST | `/versions/{vid}/items` | 맨 끝에 **회색 행** 추가 (201). 행 0개인 버전의 진입점 |
| POST | `/versions/{vid}/items/{iid}/insert-below` | 기준 행 아래에 **회색 행**. 소속을 상속하지 **않는다** (§0.2) |
| POST | `/versions/{vid}/items/{iid}/create-phase` | 결과가 연속인 행에서 새 Phase (§2.3 / §0.2-4) |
| POST | `/versions/{vid}/items/{iid}/create-milestone` | 같은 규칙으로 새 Milestone |
| POST | `/versions/{vid}/items/reorder` | **위치만** 변경 (드래그) |
| PATCH | `/versions/{vid}/items/{iid}/membership` | **소속만** 변경 (§2.3 셀 편집) |
| DELETE | `/versions/{vid}/items/{iid}` | 행 삭제 |

**Phase/Milestone 관리 팝업** (§0.4) — 이 둘만 응답이 `{items, phases, milestones}`
(`BoardOut`)다. 기준정보를 만들고 지우는 연산이라 그 두 목록도 함께 돌려준다.

| Method | Path | 설명 |
|---|---|---|
| POST | `/versions/{vid}/phases/apply` | 팝업 표의 최종 상태를 **원자적으로** 반영 |
| POST | `/versions/{vid}/phases/{pid}/milestones/apply` | 그 Phase 안의 Milestone 에 대해 동일 |

### 계층 2 — 프로젝트 (설비사별)

**버전 관련 엔드포인트가 하나도 없다.** draft 발행 / validate / publish / 폐기는
템플릿에만 있다. 프로젝트는 생성이 곧 확정이고 이후 편집이 바로 반영된다.
`test_projects_have_no_version_endpoints` 가 라우트 표에서 그 부재를 확인한다.

| Method | Path | 설명 |
|---|---|---|
| GET | `/projects` (`?maker_id=`, `?include_inactive=`) | 설비사의 프로젝트 목록 |
| GET | `/projects/overview` | **전체 현황** — 설비사 섹션 + 집계 + 미니맵 + 문서 (아래) |
| POST | `/projects` | **생성 = deep copy** (아래) |
| PATCH | `/projects/{pid}` | **이름만** 수정 (전체 현황의 인라인 수정). 빈/공백 이름 422 |
| GET | `/projects/{pid}` | 프로젝트 + 재계산된 전체 행 |
| PUT | `/projects/{pid}` | 이름·설명 등 수정 |
| DELETE | `/projects/{pid}` | **비활성화** (실제로 지우지 않는다) |
| PUT | `/projects/{pid}/items` | 직접 저장 (전량 교체, 참조 무결성만) |
| POST | `/projects/{pid}/items` (+ `/{iid}/insert-below`) | 회색 행 추가 |
| POST | `/projects/{pid}/items/reorder` | 위치만 변경 |
| PATCH | `/projects/{pid}/items/{iid}/membership` | 소속만 변경 |
| POST | `/projects/{pid}/items/{iid}/create-phase` · `create-milestone` | **프로젝트 로컬** 생성 |
| DELETE | `/projects/{pid}/items/{iid}` | 행 삭제 |
| POST | `/projects/{pid}/phases/apply` | 관리 팝업 적용 (§0.4). 템플릿과 **같은 구현** |
| POST | `/projects/{pid}/phases/{phid}/milestones/apply` | 위와 동일 |
| GET | `/projects/{pid}/documents` | 프로젝트별 문서 링크·상태 (아래) |
| PUT | `/projects/{pid}/documents` | 위의 업서트 |
| GET | `/projects/{pid}/links` | 프로젝트 주요 링크, `sort_order` 순 (아래) |
| PUT | `/projects/{pid}/links` | 위의 **전량 교체** |
| GET | `/projects/{pid}/dashboard.pptx` | 대시보드를 **16:9 다중 슬라이드** PPTX 로 (아래) |
| GET | `/projects/{pid}/board.xlsx` | 보드를 **원본 엑셀 양식** XLSX 로 (아래) |

행 조작의 요청·응답 규약은 템플릿 쪽과 **완전히 같다** — 재계산된 전체 행 목록 +
경계 플래그. 백엔드가 같은 `item_service` 를 쓰기 때문이지, 두 벌을 맞춰 놓은 것이
아니다.

```jsonc
// POST /projects — 발행된 템플릿 버전 하나를 골라 통째로 복제한다.
{ "maker_id": 3, "name": "A사 2026 도입", "template_id": 1 }
// 특정 버전을 고정하려면:
{ "maker_id": 3, "name": "...", "template_version_id": 7 }
```

**생성의 성질**

- **한 트랜잭션이다.** 실패하면 반쯤 복제된 프로젝트가 남지 않는다.
- **DRAFT 는 원본이 될 수 없다** (400). 확정되지 않은 작업본을 스냅샷으로 굳히면
  발행의 의미가 사라진다.
- phase/milestone/owner 는 **로컬 사본**이 되고, 행은 그 사본을 가리킨다.
  문서 기준정보는 전역이라 복제하지 않고 같은 행을 참조한다.
- `phase_start_no` 는 **원본 버전의 실효값**을 스냅샷한다.
- **전파가 없다.** 템플릿을 재발행해도 기존 프로젝트는 바뀌지 않고, 프로젝트를
  고쳐도 템플릿은 바뀌지 않는다. 그래서 "템플릿 변경을 프로젝트에 반영" 하는
  엔드포인트가 **없다** — 있으면 스냅샷이 아니게 된다.

**출처 표시 — `source_version_number`**

`ProjectOut` 은 `source_template_id` / `source_version_id` 와 함께
**`source_version_number`** 를 내려준다 (Work Package 헤더의 "어느 포맷의 몇
버전에서 왔는가"). `source_version_id` 는 auto-increment 라 사람이 읽는 번호가
아니므로 화면에 그대로 쓸 수 없다.

- **`null` 이 정상 상태다.** `source_version_id` 에는 물리 FK 가 없어 — 원본이
  지워져도 출처 이력은 남기려고 일부러 걸지 않았다 — 고아 참조가 생길 수 있고,
  그때는 번호만 비고 프로젝트 조회는 그대로 성공한다. 설비사 이름과 같은 규칙이다.
- 복제로 만들지 않은 프로젝트(`source_version_id` 자체가 없는 경우)도 `null` 이다.
- 목록·단건·수정 응답이 **모두 같은 값**을 싣는다. 조회는 프로젝트마다가 아니라
  `IN` 하나로 묶는다.

### 프로젝트별 문서 링크·상태 — plan.md §0.5-4

**프로젝트가 문서를 소유한다** (§0.5.10). 생성 시 템플릿 문서에서 복제되고, 이후
이름 변경·행 추가·삭제가 자유롭다. 전역 마스터가 없으므로 "여기서는 못 고친다" 는
제약도 사라졌다.

```jsonc
// GET  /projects/{pid}/documents
{ "documents": [ { "document_type_id": 1, "code": "①", "name": "Project Charter & R&R",
                   "is_used": true, "link_url": null, "doc_status": "NOT_WRITTEN" } ] }

// PUT  /projects/{pid}/documents — 업서트. 목록에 없는 문서는 손대지 않는다.
{ "documents": [ { "document_type_id": 1, "is_used": true,
                   "link_url": "https://drive.example.com/charter", "doc_status": "WRITING" } ] }
```

- **행이 없는 것이 정상 상태다.** 없으면 기본값(사용=1 · `NOT_WRITTEN` · 링크 없음)
  으로 읽고, 처음 저장할 때 행이 생긴다(lazy upsert). 그래서 **기존 프로젝트에
  백필이 필요 없고**, 전역 문서가 새로 추가돼도 다음 조회에서 저절로 따라 나온다.
  `create_project` 의 deep copy 대상에 이 테이블이 없는 것도 그래서다.
- `doc_status` 는 `NOT_WRITTEN | WRITING | DONE` — 행 상태(`ItemStatus`)와 **다른
  집합**이다. 문서에는 보류도 NA 도 없다.
- `link_url` 은 **작성 상태와 무관하게 null 이 허용된다.** 완료된 문서의 링크를
  아직 못 받았을 수 있다.
- **비활성 전역 문서는 목록에서 빠지고 저장도 422** (`DOCUMENT_NOT_AVAILABLE`).
  같은 문서를 두 번 보내면 422 (`DOCUMENT_DUPLICATED`). 검증을 전부 끝낸 뒤에
  쓰므로 422 면 아무것도 저장되지 않는다.
- **PUT 은 부분 목록이다** (행 저장의 전량 교체와 다르다). 문서 목록의 정본은 전역
  마스터이지 이 요청이 아니므로, "목록에 없으면 삭제" 를 적용하면 다른 화면이 방금
  추가한 전역 문서의 프로젝트 설정이 조용히 지워진다.
- 문서 정의는 **주입된 `DocumentTypeRepository` 로만** 읽는다. "활성 문서 전부에
  프로젝트 행을 LEFT JOIN" 이라는 의미론을 SQL 조인이 아니라 파이썬 병합으로
  구현한 이유가 그것이다 — 조인을 쓰면 교체 대상 테이블 이름이 서비스에 박힌다.

### 프로젝트 주요 링크 — plan.md §0.5.5

Confluence 페이지·클라우드 파일처럼 프로젝트가 **자유롭게 늘리고 줄이는** 외부 링크
목록. 바로 위의 문서 설정과 이름이 비슷하지만 성격이 반대다.

| | 문서 설정 (§0.5-4) | 주요 링크 (§0.5.5) |
|---|---|---|
| 목록의 정본 | 프로젝트 문서(복제본) | **이 화면** |
| 행이 없을 때 | 기본값으로 읽힌다 | 없는 것이다 |
| 저장 | 부분 업서트 | **전량 교체** |

```jsonc
// GET  /projects/{pid}/links      — sort_order 순
{ "links": [ { "id": 4, "description": "설계 Confluence", "url": "https://…", "sort_order": 1 } ] }

// PUT  /projects/{pid}/links      — 배열 순서 = sort_order, 빠진 id 는 삭제
{ "links": [ { "id": 4,    "description": "설계 Confluence", "url": "https://…" },
             { "id": null, "description": "신규",            "url": "https://…" } ] }
```

- **`sort_order` 를 요청에서 받지 않는다.** 순서의 정본은 배열 위치이고 서버가 다시
  매긴다. 둘 다 받으면 낡은 번호가 조용히 직전 재정렬을 되돌린다.
- 재정렬·수정·추가·삭제가 **한 번의 저장에 섞여** 들어오는 것이 정상 사용이다
  (화면이 관리형 row drag 를 쓴다). 그래서 전량 교체이고, 삭제 전용 엔드포인트가
  없다.
- **URL 은 `http://` 또는 `https://` 로 시작해야 한다** (스킴 대소문자 무관).
  스킴만 있고 주소가 없는 값(`https://`)도 거부한다 — 통과시키면 클릭해도 아무 데도
  가지 않는 링크가 저장된다. 설명은 공백일 수 없다. 둘 다 앞뒤 공백을 떼고 저장한다.
- 오류는 422 이며 `index`(0-based) · `row_no`(1-based) · `field` 를 실어 그리드가
  문제의 셀을 짚을 수 있다. 코드: `LINK_URL_INVALID` · `LINK_DESCRIPTION_REQUIRED` ·
  `LINK_OUT_OF_SCOPE` · `LINK_DUPLICATED`.
- **검증을 전부 끝낸 뒤에 쓴다.** 422 면 커밋에 도달하지 않아 재정렬도 삭제도
  저장되지 않는다.
- 다른 프로젝트의 링크 id 는 `LINK_OUT_OF_SCOPE` 다. 프로젝트 삭제 시 CASCADE 로
  함께 지워진다 — 링크는 프로젝트 밖에서 의미를 갖지 않는다.

### 보드 XLSX 내보내기 — plan.md §0.5.7 (CSV 를 대체한다)

`GET /versions/{vid}/board.xlsx` (템플릿) · `GET /projects/{pid}/board.xlsx` (프로젝트)
→ `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

**양식은 `docs/Work Package.xlsx` 원본 그대로다.** 시트 두 장(`Project Board`,
`Doc Status`), 머리말 위치, 헤더 행(4행), 컬럼 순서, 서식(Malgun Gothic 9.5, 남색
헤더, 얇은 테두리, Phase 색 밴딩, 열 너비, `F5` 창 고정)은 원본 파일을 openpyxl 로
열어 뽑은 **실측값**이다.

> **내보내기가 곧 임포트 양식이다.** 완전히 배정된 보드를 내보낸 파일은
> `db/migrate.py` 의 `parse_workbook` 이 **그대로 다시 읽을 수 있어야 한다.** 그래서
> 아래 표기는 취향이 아니라 계약이다:
>
> | 컬럼 | 표기 | 되읽는 쪽 |
> |---|---|---|
> | Phase | `Phase {n}. {이름}` | `PHASE_RE` |
> | Milestone | `{n}.{m} {이름}` | `MILESTONE_RE` |
> | 관련 문서 | `{원문자} {문서명}` 을 ` / ` 로 연결 | **원문자**가 토큰 경계 (§1.1) |
> | Owner | `+` 연결 | `parse_owners` |
> | Status | `Not Started` / `In Progress` / `Done` / `Hold` / `N/A` | `STATUS_MAP` |
>
> `tests/test_board_xlsx.py` 의 round-trip 테스트가 이 계약을 fail-closed 로 잠근다 —
> 시드 보드를 내보내 다시 파싱하고 35행의 필드를 대조하며, 정합성 검사까지 통과하는지
> 본다. NEGATIVE CONTROL 도 함께 있다 (표기를 흩뜨리면 반드시 죽는다).

- **미배정(회색) 행은 Phase/Milestone 이 빈 셀**이다. 원본 양식에 없던 상태이므로
  **재파싱 대상이 아니다** — 파서는 빈 Phase 셀을 형식 오류로 거부하고, 그것이 옳다.
  왕복을 약속하는 것은 "완전히 배정된 보드" 뿐이다.
- **Doc Status 시트**는 전역 문서 목록(원본 양식 7컬럼). **프로젝트 내보내기에만**
  `사용` · `클라우드 링크` · `작성 상태` 세 컬럼이 덧붙는다 (§0.5-4). 저장된 행이 없는
  문서는 기본값(사용 `O` · 작성 전)으로 나간다.
- **읽기 연산이다.** PUBLISHED/ARCHIVED 버전도 내보낼 수 있다 — 불변 규칙은 쓰기를
  막는 것이지 읽기를 막는 것이 아니다.
- 파일명은 템플릿이면 `{템플릿명} v{번호}`, 프로젝트면 프로젝트명. RFC 5987.

> **`openpyxl` 은 선택 의존성이다.** python-pptx 와 같은 규율로 함수 안에서 늦게
> import 하므로, 없어도 `create_wp_router()` 는 뜨고 나머지 API 는 전부 동작한다.
> 이 두 엔드포인트만 **501 `EXPORT_UNAVAILABLE`** 로 답한다.

### 대시보드 PPTX 내보내기 — plan.md §0.5.6

`GET /projects/{pid}/dashboard.pptx` → **16:9 다중 슬라이드** pptx. `Content-Type` 은
`application/vnd.openxmlformats-officedocument.presentationml.presentation`.

**시각 정본은 `docs/DSEP_AI_Project_Board_Guide.pptx` 다.** 치수·폰트 크기·크롬 색은
그 덱을 python-pptx 로 파싱해 뽑은 **실측값**이며 추정이 아니다.

| 슬라이드 | 내용 |
|---|---|
| 1 | **Status Map** — Phase chevron + 마일스톤 헤더 + 카드 격자 + 범례 (정본 slide 1) |
| 2~ | **Phase 별 상세** — Phase 하나가 한 장 이상, 한 장에 5행 (정본 slide 2~8) |

- **화면 캡처가 아니라 데이터에서 다시 그린다.** 스크롤 밖의 항목도 빠지지 않고,
  폰트·색이 보는 사람의 환경에 좌우되지 않는다. 그리드와 **같은 조회 경로**
  (`build_item_views`)를 쓰므로 번호·소속·문서·Owner 이름이 화면과 일치한다.
- **Status Map 은 언제나 한 장이다.** 컬럼 수(전체 마일스톤 + 미배정)와 한 컬럼의
  최대 카드 수로 폭·높이·폰트를 자동 축소한다. 기준 케이스는 엑셀 원본 보드
  (Phase 4 · Milestone 13 · 35행)이며, 거기서는 정본 덱의 치수가 **축소 없이 그대로**
  쓰인다. 카드 높이는 컬럼과 무관하게 하나로 통일한다 (§0.5.4b).
- **상세 슬라이드**의 행은 `No · **Deliverable**(굵게) + · {phase.ms} {마일스톤명} |
  {title} · 문서 원문자 · Owner`. 나뉜 Phase 는 제목에 `(1/2)` 와 `— 항목 N~M` 이
  붙고, 나뉘지 않으면 페이지 표기를 달지 않는다. 미배정 행은 **맨 뒤 자기 그룹**
  (`UNASSIGNED ITEMS`)으로 나온다. 푸터는 프로젝트명 + 페이지 번호.
- **상태 색 확장** — 상세 슬라이드의 `No` 셀을 상태색 배지로 칠한다. 정본 덱에는
  없는 확장이며, 상세에서도 진행 상태가 한눈에 들어오게 하려는 것이다.
- **읽기 연산이다** — `readOnly` 여도 허용된다. 행이 0개인 프로젝트는 Status Map
  한 장만 나오고 오류가 아니다.
- 파일명은 프로젝트명이며 **RFC 5987** 로 싣는다: ASCII 폴백 `filename=` 과
  UTF-8 정본 `filename*=` 를 **둘 다** 보낸다. 한글 프로젝트명이 기본이라
  `filename=` 만 쓰면 mojibake 가 된다.

> **`python-pptx` 는 선택 의존성이다.** `dashboard_pptx_service` 가 함수 안에서 늦게
> import 하므로, 설치돼 있지 않아도 `create_wp_router()` 는 뜨고 나머지 API 는 전부
> 정상 동작한다. 이 엔드포인트만 **501 `EXPORT_UNAVAILABLE`** 로 답한다. PPT 기능을
> 쓰지 않는 호스트에 설치를 강요하지 않으려는 것이다.

> ⚠️ **색 상수가 두 곳에 있다.** §0.5 가 정본이고 `backend/app/services/dashboard_theme.py`
> 와 `frontend/src/theme/dashboard.ts` 가 각자 적어 둔다 (언어도 배포 단위도 달라
> 공유할 방법이 없다). 드리프트는 규율이 아니라 테스트로 막는다 —
> `tests/test_dashboard_pptx.py` 가 프론트 파일을 **직접 파싱해** 팔레트·상태색·
> 주관색·라벨·휴리스틱 판정 순서를 대조하며, 한쪽만 고치면 스위트가 깨진다.
>
> **Phase·상태·주관 팔레트만은 정본 덱을 따르지 않는다.** 그 셋은 §0.5 가 못박은
> 값이고 화면과 픽셀 단위로 맞아야 한다. 정본 덱의 색은 사실상 같은 색이지만
> (`8E7CC3` vs `8F7CC3`) 한 자리씩 달라, 덱 쪽을 쓰면 화면과 어긋난다. 제목·테두리·
> 푸터처럼 **화면에 대응물이 없는 색만** 덱에서 가져왔다 (`DECK_*` 상수).

### 설비사 설정 `GET/PUT /makers` — plan.md §0.6

호스트의 설비사 테이블에는 컬럼을 더할 수 없으므로, "전체 현황에 표시할까" 같은
우리 쪽 상태를 `wp_maker_settings` 에 따로 둔다. **설비사를 만들거나 이름을 고치는
엔드포인트는 없다.**

| Method | Path | 설명 |
|---|---|---|
| GET | `/makers` | 설정 화면의 표 — 이름 · 프로젝트 유무 · 표시 여부 |
| PUT | `/makers/settings` | 업서트 (부분 목록). 응답은 갱신된 표 |

```jsonc
{ "makers": [ { "maker_id": 3, "name": "A 설비",   // resolver 없으면 null
                "show_in_overview": true,          // 규칙 적용 후 **유효값**
                "explicit": false,                 // 설정 행이 있는가
                "has_projects": true } ] }
```

**표시 규칙 (§0.6-1) — 서버가 적용한다:**

| 설정 행 | 유효값 |
|---|---|
| 있음 | `show_in_overview` 그대로 |
| 없음 | **active 프로젝트가 있으면 표시** |

무설정을 "숨김" 으로 두면 설치 직후 전체 현황이 비어 고장처럼 보이고, "표시" 로
두면 체크를 풀어도 설비사가 추가될 때마다 되살아난다. 프로젝트 유무를 기본값으로
삼으면 두 문제가 동시에 사라지고 체크 한 번으로 **강제 표시·강제 숨김 양쪽**이
가능해진다. `show_in_overview`(유효값)와 `explicit`(명시 여부)를 둘 다 내려주는
것은 화면이 그 둘을 구분해 보여주기 위해서이고, **규칙을 다시 계산하라는 뜻이
아니다** — 클라이언트가 계산하면 설정 화면과 전체 현황이 갈린다.

`maker_id` 의 존재는 저장 시 검증하지 않는다. resolver 미주입이 정상 상태이므로
존재 검증을 전제로 걸면 그런 설치에서 설정 자체가 불가능해진다. 고아 설정은 이름
없는 빈 섹션이 될 뿐이다.

### 전체 현황 `GET /projects/overview` — plan.md §0.5-3, §0.6-3

전 설비사를 한 화면에 늘어놓는 **읽기 전용** 관망 뷰. `maker_id` 로 필터하지
않는다. **최상위가 설비사 섹션이다** (§0.6-3 개편 — 이전 판은 `projects` 평면
배열이었다).

```jsonc
{ "makers": [ {
    "maker_id": 3, "name": "A 설비",              // resolver 미주입이면 null (정상)
    "projects": [ {                                // 체크된 설비사는 **빈 배열**일 수 있다
      "id": 1, "name": "A사 2026 도입", "maker_id": 3, "maker_name": "A 설비",
      "counts": { "NOT_STARTED": 30, "IN_PROGRESS": 3, "DONE": 2, "HOLD": 0, "NA": 0 },
      "items": [ { "no": 1, "status": "DONE", "phase_seq": 0, "milestone_seq": 1,
                   "dash_label": "Gap·자원 계획",
                   "title": "…", "deliverable": "…",       // 둘 다 null 가능
                   "owners": ["DSEP 인프라 담당자"] } ],     // id 가 아니라 **이름**
      "documents": [ { "document_type_id": 1, "code": "①", "name": "Project Charter & R&R",
                       "doc_status": "WRITING", "link_url": "https://…" } ]   // 사용 중인 것만
    } ]
} ] }
```

- **섹션 목록에 표시 규칙이 이미 적용돼 있다.** 클라이언트는 받은 대로 그린다.
- **프로젝트 0개인 섹션이 나올 수 있다** — 설정에서 명시적으로 켠 경우다. 그래야
  그 설비사에 첫 프로젝트를 추가할 자리가 생긴다.
- 섹션 목록은 `resolver 목록 ∪ 프로젝트가 쓰는 maker_id ∪ 설정 행` 이다. 그래서
  resolver 가 없어도, 호스트에서 사라진 고아 `maker_id` 여도 프로젝트는 보인다.
- 프로젝트 카드의 `maker_name` 은 섹션의 `name` 과 **같은 값**이다.
- **활성 프로젝트만** 나온다 (`is_active=1`).
- `items` 는 `sort_order` 순이고, 그리드용 `ItemOut` 의 **축약형**이다. 프로젝트
  수 × 항목 수만큼 셀이 그려지므로 제목·문서·Owner·경계 플래그는 싣지 않는다.
- `phase_seq` / `milestone_seq` 는 저장값이 아니라 **그리드와 같은 재계산기가
  행 순서에서 파생한 표시 번호**다 (`ItemOut.phase_no` / `.milestone_no` 와 같은
  값). 미배정(회색) 행은 둘 다 `null` 이고 뒤 행의 번호를 밀지 않는다.
- `counts` 는 **다섯 키가 항상 모두** 나온다 (0 이어도 생략하지 않는다).
- `documents` 는 **`is_used=1` 인 것만** 담는다 (§0.5-3b 의 ④ 구획). 저장된 행이
  없는 프로젝트는 기본값이 사용=1 이라 활성 전역 문서가 전부 들어온다. `is_used`
  필드를 싣지 않는 것은 의도다 — 항상 참이라 클라이언트가 다시 거를 것이 없다.
- `items[].title` / `.deliverable` / `.owners` 는 미니맵 셀의 **hover 팝오버**용이다
  (§0.5-3 개편). 팝오버가 프로젝트 대시보드 카드와 같은 포맷(담당 · 상태 ·
  action item · deliverable)이어야 해서 들어왔다. `owners` 는 id 가 아니라
  **이름 배열**이다 — Owner id 는 프로젝트 로컬 사본의 것이라 이 화면에서 쓸 데가
  없고, 내려보내면 그것으로 조회할 수 있다는 잘못된 인상만 준다.
- **카드 표시 폴백(`dash_label` → `deliverable` → `title` 앞부분)은 서버가 적용하지
  않는다.** 셋을 있는 그대로 내려보내고 화면이 고른다 (§0.5-1 과 같은 이유 — 서버가
  채우면 "라벨이 비어 있다" 는 사실이 응답에서 사라진다).
- 이 셋이 늘었어도 `items` 는 여전히 그리드용 `ItemOut` 의 **축약형**이다. 문서·
  Owner id·경계 플래그·완료일은 들어 있지 않다.
- 설비사 테이블로 **JOIN 하지 않는다.** 이름은 `MakerResolver` 를 한 번만
  호출해 일괄 조회하며, 미주입·고아 참조·resolver 예외 어느 쪽도 이 조회를
  깨뜨리지 않는다 (§3).
- **아무것도 쓰지 않는다.** 그리드 경로(`renumber_and_persist`)를 재사용하지
  않고 순수 함수 `renumber()` 만 쓴다 — 프로젝트 보드는 `sync_master_seq=True`
  라, 보드 경로를 재사용했다면 관망 화면을 여는 것만으로 기준정보의 `seq_no` 가
  갱신됐을 것이다.

### 행 추가는 항상 **회색(미배정) 행**이다 — plan.md §0.2

두 추가 경로(`items` append, `insert-below`) 모두 `phase_id`/`milestone_id` 가
`null` 인 행을 만든다. **소속을 상속하지 않는다.**

이전 계약은 기준 행의 소속을 상속했는데, 드래그가 블록 내부로 제한된 뒤로는 그
규칙이 새 행을 기존 블록 **안에** 가둬 **기존 Phase 사이에 항목을 넣을 방법을
없앴다.**

| 규칙 | 내용 |
|---|---|
| **투명성** | 회색 행은 연속성 판정에 보이지 않는다. `P0 P0 [회색] P0` 은 위반이 **아니다** |
| **자유 이동** | 회색 행은 블록 제한의 예외다. 투명하므로 위치가 판정에 영향을 주지 않는다 |
| **생성 조건** | `can_create_phase` 는 "새 Phase 를 배정해도 결과가 연속인가" 와 **동치**다 |
| **사이 번호** | 두 블록 사이 회색 행에서 Phase 를 만들면 first-appearance 재계산이 저절로 가운데 번호를 준다 |

> ⚠️ **"미배정 행은 항상 경계이므로 항상 생성 가능" 은 틀렸다.** 한 블록 한가운데
> 놓인 회색 행에서 만들면 그 블록이 두 조각으로 쪼개진다. 경계인 것과 생성 가능한
> 것은 다르며, 서버가 내려주는 `can_create_phase` / `can_create_milestone` 을 그대로
> 쓰면 된다 — 클라이언트가 다시 판단하지 말 것.
>
> 근거는 전수 증명이다 (`tests/test_gray_row_exhaustive.py`): n ≤ 5 의 **모든**
> (phase, milestone) 배정 × 모든 행에 대해 플래그와 "배정 후 연속" 이 **양방향으로**
> 일치함을 센다. 한쪽 방향만 보면 지나치게 보수적인 플래그도 통과하는데, §0.2 가
> 열려던 "사이에 추가" 가 바로 그렇게 막혀 있었다.

### 위치와 소속은 분리되어 있다

```jsonc
// POST .../items/reorder — 순서만. 각 행은 자기 소속을 그대로 들고 간다.
{ "item_ids": [12, 3, 7] }

// PATCH .../items/{iid}/membership — 소속만. 서버가 **마일스톤 블록** 끝으로 옮긴다.
{ "phase_id": 2, "milestone_id": 5 }
```

| 엔드포인트 | 소속 | 연속성 |
|---|---|---|
| `reorder` | **절대 안 바뀐다** | 조각나면 422, 아무것도 저장하지 않음 |
| `membership` | 요청이 지정 | 서버가 옮긴 뒤 검사, 위반 시 422 |

**`reorder` 는 소속을 재유도하지 않는다.** 각 행은 자기 `phase_id`/`milestone_id`
를 그대로 유지하고 위치만 바뀐다 (plan.md §2.2). 드래그로 행의 분류가 바뀌는 일은
없다 — 소속 변경의 유일한 통로는 `membership` 이다.

`moved_item_id` 는 **더 이상 받지 않는다.** 아무것도 재유도하지 않는 연산에서 어느
행이 끌렸는지는 의미가 없다. 보내도 무시된다.

| 입력 | 결과 |
|---|---|
| 블록 내부 순열 (UI 가 만드는 유일한 요청) | 항상 200. 소속 불변이므로 구조적으로 연속 |
| 블록을 가로지르지만 결과가 연속인 순열 (예: 블록 통째로 맞바꾸기) | 200. 소속은 그대로고 표시 번호만 다시 매겨진다 |
| 결과가 조각나는 순열 | **422** — 아무것도 저장하지 않는다 |

> **예전 계약과의 차이.** 이전에는 `reorder` 가 이동한 행의 소속을 새 앞행에서
> 재상속시켰다. 그래서 다른 Phase 영역으로 끌면 **아무 경고 없이 그 행의 Phase 가
> 재배정됐고**, 원래 Phase 의 마지막 행을 끌어내면 그 Phase 자체가 사라졌다.
> 재유도가 없어지면서 그 실패 모드(임의 순열 n=6 에서 12.86% 조각남,
> `moved_item_id` 오보 시 ~1%)도 함께 사라졌다 — 확률이 낮아진 것이 아니라
> **사건이 정의되지 않는다.**
>
> 다만 가드는 남는다. 호스트의 다른 클라이언트는 UI 없이 임의 순서를 보낼 수 있고,
> 그 순서가 조각나면 `reorder` 는 이제 고쳐 주지 않으므로 **거부가 유일한 대응**이다.

증거는 `backend/tests/test_reorder_exhaustive.py` 에 있다. n ≤ 6 의 모든 연속 보드
배치 × **모든 순열** 185,389건에서 소속 불변을 전수 확인하고(위반 0), 블록 내부
순열 3,223건이 모두 연속임을 전수 확인하며, 조각나는 순열이 **존재한다는 사실도
함께 고정**한다 — 반례가 사라져 검사를 없앨 수 있게 되면 그 테스트가 먼저 깨져
알려 준다.

`membership` 은 **중간 행이라도 422 를 내지 않는다.** §2.3 이 정한 대로 대상
블록 끝으로 서버가 옮긴다 — 그 목적지 계산이야말로 클라이언트에서 떼어내려는
판단이다.

#### 목적지 규칙 — **마일스톤 블록 단위다** (plan.md §0.3)

"대상 블록 끝" 이 어느 블록인지가 핵심이다. 서버는 아래 순서로 정한다.

| 요청 | 목적지 |
|---|---|
| `{phase, milestone}` | **그 마일스톤 블록의 끝.** 보드에 그 마일스톤이 없으면 아래로 |
| `{phase, null}` | 그 **Phase 블록**의 끝 |
| 대상 블록이 아직 보드에 없음 | **제자리** (옮길 곳이 없다) |
| `{null, null}` | **제자리** — 행이 그 자리에서 회색이 된다 (§0.3 재분류 경로) |

> ⚠️ **Phase 블록 끝이 아니다.** 보드가 `b1(2.1) c1(2.2) c2(2.2) d1(2.3) d2(2.3)` 일 때
> `{phase: 2, milestone: 2.2}` 는 **c2 뒤·d1 앞**이지 d2 뒤가 아니다. Phase 단위로만
> 재배치하면 사용자에게 **번호 뒤섞임**으로 나타난다 — 목(mock)이 실제로 그렇게
>구현되어 이 증상이 보고됐다. 서버와 같은 규칙을 구현할 것.
>
> 이 구분은 대상 마일스톤이 자기 Phase 의 **마지막이 아닐 때만** 드러난다. 마지막이면
> 마일스톤 블록 끝과 Phase 블록 끝이 같은 자리라 두 구현이 똑같이 동작한다 —
> 테스트 픽스처를 그렇게 만들면 잘못된 구현도 통과한다.
> (`test_assigning_a_milestone_lands_at_that_milestone_block_end_not_the_phase_end`)

**`{null, null}` = 미배정으로 전환.** §0.3 은 이것을 배정된 행의 **유일한 재분류
경로**로 정한다. 행은 **제자리에서** 회색이 되고(양쪽 id 가 null), 200 을 반환하며,
나머지 행의 번호는 흔들리지 않는다 — null 은 연속성에 투명하기 때문이다. 블록
한가운데 행을 비워도 422 가 아니다. 옮기는 구현은 사용자가 "행이 멋대로 움직인다"
고 느끼는 동작이며, §0.3 이 배정된 행의 소속 셀을 잠그면서 없애려던 것이다.

`create-phase` / `create-milestone` 은 기준 행을 **경로**로 받고 위치 파라미터를
두지 않는다. 기준 행이 제자리를 지킨 채 소속만 바뀌므로 앞/뒤는 그 행이 어느
경계에 있었는지에서 저절로 정해진다. 중간 행이면 422
(`PHASE_BOUNDARY_VIOLATION` / `MILESTONE_BOUNDARY_VIOLATION`).

### 임시저장의 순서 규칙

**순서의 정본은 배열 위치다.** `sort_order` 를 실어 보내도 되지만 주장(assertion)
으로만 취급하며, 배열 위치와 다르면 **400** 이다. 둘 중 하나를 이기게 하는 규칙은
결국 정본이 둘이라는 뜻이라, 낡은 `sort_order` 가 조용히 직전 reorder 를 되돌려도
아무도 눈치채지 못한다.

**기준정보**

| Method | Path |
|---|---|
| GET/POST | `/master/document-types` · PUT/DELETE `/master/document-types/{id}` |
| GET/POST | `/templates/{id}/owners` · PUT/DELETE `.../owners/{oid}` |
| GET/POST | `/templates/{id}/phases` · PUT/DELETE `.../phases/{pid}` |
| GET/POST | `/templates/{id}/milestones` · PUT/DELETE `.../milestones/{mid}` |
| GET/POST | `/projects/{id}/owners` · PUT/DELETE `.../owners/{oid}` |
| GET/POST | `/projects/{id}/phases` · PUT/DELETE `.../phases/{pid}` |
| GET/POST | `/projects/{id}/milestones` · PUT/DELETE `.../milestones/{mid}` |

네 DELETE 는 모두 `{id, deleted, deactivated, usage_count, message}` 를 반환한다.
사용 중이면 지우지 않고 비활성화한다 (plan.md §2.6).

**발행 버전은 변경 가능한 기준정보에 의존하지 않는다** (plan.md §2.4).

| 변경 | 동작 |
|---|---|
| Phase/Milestone 이름 수정 | 허용 — 표시용이므로 과거 버전에 전파되어도 좋다 |
| 사용 중인 Milestone 의 소속 Phase 변경 | **409** — 발행 버전이 무효가 된다 |
| `phase_start_no` 변경 | 발행 시점에 **버전에 스냅샷**되므로 발행 버전에 영향 없음 |

### HTTP 상태 코드

| 코드 | 의미 |
|---|---|
| 400 | 참조 무결성 위반, 불완전한 reorder 목록, `sort_order` 불일치 |
| 404 | 대상 없음 |
| 409 | 상태 전이 위반 (PUBLISHED/ARCHIVED 수정, DRAFT 중복, 사용 중 Milestone 재배치) |
| 422 | 도메인 규칙 거부 — 발행 검증 실패, §2.3 경계 위반, 연속성 위반 |

오류 본문은 항상 **평평하다**: `{"detail": {"code", "message", ...부가정보}}`.
발행 실패는 `POST /validate` 와 **같은 형태**라 프론트가 파서를 하나만 갖는다.

```jsonc
// 발행 검증 실패 — §2.5 형식이 detail 바로 아래에 붙는다
{ "detail": { "code": "VALIDATION_FAILED", "message": "...",
              "valid": false, "errors": [...], "warnings": [...] } }

// 경계 규칙 위반 — 셀을 바로 짚을 수 있게 위치를 담는다
{ "detail": { "code": "PHASE_BOUNDARY_VIOLATION", "message": "...",
              "item_id": 37, "row_no": 2, "field": "phase_id" } }
```

V13(`EMPTY_VERSION`)을 뺀 모든 검증 오류는 `item_id` / `row_no` / `field` 를
채운다. V6/V7 은 해당 Phase/Milestone 의 **첫 행**을 가리킨다.
경고 코드는 `ORPHAN_PHASE` 와 `ORPHAN_MILESTONE` 이며 발행을 막지 않는다.

## 9. 구현이 계획서와 다른 곳

이식성·불변식 때문에 의도적으로 다르게 만든 지점이다.

| # | `plan.md` | 구현 | 이유 |
|---|---|---|---|
| 1 | `work_packages`, `document_types` (접두 없음) | `wp_templates`, `wp_document_types` | 루트 `INTEGRATION.md` §4 "`wp_` 접두 테이블명" 과 §6 "접두라 충돌 없음" 을 따랐다. 특히 `document_types` 는 호스트와 충돌 가능성이 가장 높은 이름이다 |
| 2 | `app/main.py` (§4.1) | `app/router.py` + `app/standalone.py` | `main.py` 는 앱을 뜻한다. 라이브러리 코드에 앱이 없어야 하므로 팩토리(`router.py`)와 개발용 앱(`standalone.py`)으로 나눴다 |
| 3 | draft 발행 시 "items / phases / milestones / 연관관계를 **전부** deep copy" (§2.4) | 행과 N:M 만 복사 | phases/milestones 는 §3.2 에서 **WP 스코프**(`work_package_id`)로 정의되어 버전에 속하지 않는다. 복사하면 `UQ(work_package_id, name)` 에 걸린다 |
| 4 | Phase/Milestone 번호를 `seq_no` 에 저장 (§2.2) | 저장은 하되, **조회 시 번호는 그 버전의 행 순서에서 파생** | 기준정보가 WP 스코프라 여러 버전이 공유한다. `seq_no` 만 읽으면 DRAFT 를 편집할 때 **PUBLISHED 의 표시 번호까지 바뀌어** 불변성이 깨진다 |
| 5 | `milestone_display("1.2")` (§2.1) vs `"0.1 이름"` (§4.3) | 둘 다 제공 (`milestone_no_display`, `milestone_display`) | 두 절의 예시가 서로 달라 프론트가 조합하지 않아도 되도록 모두 내려준다 |
| 6 | V14 = `ORPHAN_PHASE` | `ORPHAN_MILESTONE` 경고 추가 | 쓰이지 않는 Milestone 도 같은 성격의 잔여 기준정보다. warning 이라 발행을 막지 않는다 |
| 7 | `관련 문서` 는 `/` 로 분리 | **원문자(①~⑤)를 토큰 경계로 분리** | `② DSEP Readiness & I/O Spec` 의 `I/O` 가 구분자로 오인된다. 실제로 `/` split 구현이 이 셀에서 실패했다 |
| 8 | §4.2 에 없음 (당시) | `POST /versions/{vid}/items` 등 3종 | 승인 후 `plan.md` §4.2 에 반영됨. 더 이상 차이가 아니다 |

**해소된 차이** — 아래는 한때 이 표에 있었으나 `plan.md` 에 반영되어 차이가 아니게 됐다.

* 빈 행 추가 / `create-phase` / `create-milestone` — §4.2 에 정식 등재
* reorder 본문 — §4.2 가 `item_ids` **하나**로 확정하고, 소속 변경은
  `PATCH .../membership` 으로 분리. 한때 두 연산을 합친 `entries[]` 형태로
  구현했으나 되돌렸다. 합치면 "안전한 경로" 가 선택 파라미터에 의존하게 되어,
  그 파라미터를 빠뜨린 호스트 클라이언트가 조용히 약한 경로로 떨어진다.
  `moved_item_id` 도 §2.2 개정(드래그를 블록 내부로 제한)과 함께 제거됐다 —
  소속을 재유도하지 않는 연산에는 쓸 곳이 없다
* 발행 422 의 평평한 본문 — §2.5 에 반영
* `phase_start_no` 스냅샷 · 사용 중 Milestone 재배치 금지 — §2.4 에 반영
* 행 추가의 상속 규칙 — §0.2 가 **회색 행**으로 정정. 상속은 삭제됐다
* `wp_work_packages` / `maker_id` — §0.1 이 템플릿(중앙)과 프로젝트(설비사별)로
  나누면서 컨테이너가 `wp_templates` 가 되고 maker 는 `wp_projects` 로 내려갔다

**구현 판단 (계획서가 정하지 않은 것)**

| # | 사안 | 선택 | 이유 |
|---|---|---|---|
| A | 두 계층의 행 조작 로직 | `Board` 를 받는 **한 벌** (`services/board.py`) | 두 벌이면 재계산·경계 규칙이 조용히 갈라진다. 사용자에게는 "템플릿에서는 되는데" 로 나타나고, 고칠 곳이 두 곳이라는 사실을 먼저 발견해야 한다 |
| B | 기준정보 CRUD 12종 | `mount_scoped_master()` 로 두 계층에 같은 핸들러를 단다 | 같은 이유. 삭제 정책(사용 중이면 비활성화)이 양쪽에서 자동으로 같아진다 |
| C | 스코프 경로 파라미터 이름 | 핸들러는 `scope_id`, 등록 시 `__signature__` 로 `template_id`/`project_id` 로 노출 | URL 은 위치 매칭이라 동작에는 차이가 없지만, OpenAPI 에 `/templates/{scope_id}` 가 새면 스펙을 읽는 쪽이 혼란스럽다. `__signature__` 교체는 파이썬 표준이며 FastAPI 내부에 의존하지 않는다 |
| D | `wp_projects.source_template_id` / `source_version_id` | 물리 FK 없음 | `Item.source_item_id` 와 같은 이유 — 원본이 지워져도 출처 이력은 남아야 한다. 프로젝트는 스냅샷이라 원본 삭제가 내용에 영향을 주지 않는다 |
| E | `DELETE /projects/{pid}` | 비활성화 | 프로젝트에는 실행 이력(Status/완료일)이 쌓인다. 되돌릴 수 없는 삭제를 기본값으로 두지 않는다 |
| F | 데모 프로젝트 | `db/dev_seed.sql` 에만 | `db/seed.sql` 은 중앙 기준 데이터다. 특정 설비사의 흔적을 남기지 않는다 |
| G | `phases/apply` 의 "기존 전체 집합" | **보드에 행이 있는** Phase 들 (first-appearance 순) | §0.4 는 "행 없는 Phase 는 존재할 수 없다" 고 정한다. 기준정보 테이블 전체를 집합으로 삼으면, 다른 버전만 쓰는 Phase 나 비활성 Phase 까지 팝업이 나열해야 한다 |
| H | `phases/apply` 삭제 시 기준정보 실체 | 다른 곳에서 안 쓰면 하드 삭제, 쓰면 **비활성화** (하위 Milestone 도 함께) | §0.4 는 캐스케이드 하드 삭제를 말하지만, 템플릿의 Phase 는 **버전이 아니라 템플릿**에 매인다. PUBLISHED 가 쓰고 있는 것을 물리적으로 지우면 손대지도 않은 발행본이 깨진다. 어느 쪽이든 이 보드에서는 사라지므로 사용자가 보는 결과는 같다 |
| I | `milestones/apply` 의 앵커 조건 | `milestone_id is null` 이고 phase 가 null 이거나 대상 Phase 인 행 | §0.4 는 "회색 행" 이라고만 쓰는데, Milestone 층위에서 셀 에디터가 열리는 상태는 §0.3 상 **"phase 만 배정된 행"** 이다. 문자 그대로 `phase_id is null` 만 받으면 정작 그 흐름을 못 쓴다. 엄격한 해석에서 유효한 요청은 전부 그대로 유효하다 |
| J | apply 응답 | `{items, phases, milestones}` (`BoardOut`) | §0.4 가 요구하는 "전체 보드 페이로드". 행만 돌려주면 팝업이 방금 만든 Phase 의 id 를 몰라 곧바로 두 번째 요청을 한다 |

---

## 10. 로컬 실행

```bash
# 1) DB 구축 + 엑셀 임포트 (최초 1회)
python db/migrate.py --with-dev-seed --emit-sql

# 2) 개발 서버
cd backend
python -m uvicorn app.standalone:app --reload --port 8000
#   http://localhost:8000/docs

# 3) 테스트 (별도 DB `iai_test_pytest` 를 만들었다 지운다)
cd backend
python -m pytest
```

`db/migrate.py` 의 다른 모드: `--dry-run` (파싱·검사만), `--emit-sql`
(`db/seed.sql` 재생성), `--dump PATH` (파싱 결과를 UTF-8 JSON 으로).

> 콘솔이 cp949 라 한글 출력이 깨진다. 스크립트는 숫자 요약만 출력하고,
> 한글이 필요하면 UTF-8 파일로 쓴다.
