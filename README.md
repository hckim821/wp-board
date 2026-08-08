# DSEP Work Package 보드

`docs/Work Package.xlsx` 의 **Project Board** 시트(35행)를 대체하는 웹 관리 시스템.
Phase/Milestone 자동 재계산, 버전 관리(draft 발행 → 임시저장 → 발행), 기준정보 관리를 제공한다.

> **이 저장소는 독립 실행형 제품이 아니다.** 프론트엔드는 다른 프로젝트에 Module Federation remote 로,
> 백엔드는 이미 가동 중인 다른 FastAPI 프로젝트에 이식된다. 아래 실행 방법은 **개발·검증용**이며,
> 이식 절차는 [`INTEGRATION.md`](INTEGRATION.md) 에 있다.

| 스택 | |
|---|---|
| 프론트 | Vue 3 · TypeScript · Tailwind · Ant Design Vue · AG Grid **Community** |
| 백엔드 | FastAPI · SQLAlchemy 2.x · Pydantic v2 |
| DB | MariaDB 11.2.2 (MySQL 호환 문법) |

---

## 1. 사전 준비

| 항목 | 요구 | 확인 |
|---|---|---|
| Python | **3.11+** | 전역 3.8 로는 안 된다 (SQLAlchemy 2.x 미지원) |
| Node.js | 20+ | 검증 환경 v24.12.0 |
| MariaDB / MySQL | 실행 중 | `localhost:3306` |

### 1.1 DB 접속 정보 — 환경변수

**저장소에 비밀번호를 두지 않는다.** 스크립트와 테스트는 환경변수로 받는다.

| 변수 | 기본값 | 쓰는 곳 |
|---|---|---|
| `WP_DB_HOST` | `localhost` | `db/*.py`, `backend/tests` |
| `WP_DB_PORT` | `3306` | 〃 |
| `WP_DB_USER` | `user01` | 〃 |
| `WP_DB_PASSWORD` | **없음 — 필수** | 〃 |
| `WP_DB_NAME` | `iai-test` | 〃 |
| `WP_DB_DSN` | **없음 — 필수** | 백엔드 앱 (`app/standalone.py`, pydantic-settings) |

```bash
# bash
export WP_DB_PASSWORD='...'
export WP_DB_DSN='mysql+pymysql://user01:...%23@localhost:3306/iai-test?charset=utf8mb4'
```

```powershell
# PowerShell
$env:WP_DB_PASSWORD = '...'
$env:WP_DB_DSN = 'mysql+pymysql://user01:...%23@localhost:3306/iai-test?charset=utf8mb4'
```

> ⚠️ DB 명 `` `iai-test` `` 의 하이픈 때문에 raw SQL 에서는 **항상 백틱**이 필요하다.
> DSN 에서는 비밀번호의 `#` 를 `%23` 으로 인코딩해야 한다 — 안 하면 DSN 이 **조용히 잘려**
> 인증 실패처럼 보인다.
>
> `WP_DB_DSN` 미설정은 백엔드 기동 **오류**다. 하드코딩 폴백을 두지 않았다 — 조용히
> 엉뚱한 DB 에 붙는 것보다 뜨지 않는 편이 낫다.

---

## 2. 최초 설치

### 2.1 백엔드 의존성

**Python 3.11+ 환경을 활성화한 뒤** 설치한다. conda 사용 예:

```bash
conda create -n wp-board python=3.11 -y
conda activate wp-board
pip install -r backend/requirements.txt
```

> ⚠️ **conda `base` 환경(Python 3.8.8)에서는 동작하지 않는다.** SQLAlchemy 2.x 가 요구하는
> `DeclarativeBase` 가 없어 `db/verify.py` 가 `ImportError` 로 죽고, Pydantic v2 도 쓸 수 없다.
>
> 아래 README 의 모든 `python ...` 명령은 **3.11+ 환경이 활성화된 상태**를 전제한다.
> `python --version` 으로 먼저 확인할 것.

### 2.2 DB 생성 + 엑셀 데이터 임포트

```bash
# 저장소 루트에서
python db/migrate.py

# 또는 백엔드 폴더에서 — 같은 로직의 진입점 (backend/import_excel.py)
cd backend && python import_excel.py
```

`iai-test` DB 를 만들고 스키마를 적용한 뒤 `docs/Work Package.xlsx` 의
**Project Board** 시트 35행을 **v1 PUBLISHED** 로 적재한다.
`backend/import_excel.py` 는 `db/migrate.py` 를 그대로 재사용하는 백엔드 최상단
진입점이라 옵션도 동일하다. 엑셀 양식은 현재 레이아웃 고정이며, 컬럼/헤더가
바뀌면 적재 대신 파싱 오류가 난다. 결과:

```
1 WP · v1 PUBLISHED · 35 items · 4 phases (seq_no 0–3) · 13 milestones
8 owners · 5 document types · 37 doc links · 45 owner links
```

유용한 옵션 (`db/migrate.py`, `backend/import_excel.py` 공통):

| 명령 | 용도 |
|---|---|
| `--dry-run` | DB 를 건드리지 않고 파싱·정합성만 확인 |
| `--emit-sql` | `db/seed.sql` 재생성 |
| `--skip-schema` | 스키마 적용 없이 데이터만 재적재 |
| `--apply-migrations` | `db/migrations/` 번호순 적용 (데이터 불변) |
| `--with-dev-seed` | 개발용 설비사 스텁(`wp_dev_makers`)까지 적용 |

SQL 파일로 직접 만들려면 `db/schema.sql` → `db/seed.sql` 순으로 적용해도 된다.

> ⚠️ 재적재는 시드 템플릿(DSEP-AI-BOARD)과 그 버전/행을 지우고 다시 만든다.
> 실사용 데이터가 쌓인 뒤에는 `--dry-run` / `--emit-sql` 외의 실행에 주의할 것
> ([`HANDOFF.md`](HANDOFF.md) §0.5). 적재 후 확인은 `python db/verify.py`.

### 2.3 프론트엔드 의존성

```bash
cd frontend
npm install
```

---

## 3. 실행

### 3.1 백엔드 (개발 서버)

```bash
cd backend
export WP_DB_DSN='mysql+pymysql://user01:...%23@localhost:3306/iai-test?charset=utf8mb4'
python -m uvicorn app.standalone:app --host 127.0.0.1 --port 8010 --reload
```

- 헬스체크: <http://127.0.0.1:8010/health>
- API 문서: <http://127.0.0.1:8010/docs>

> `standalone.py` 는 **개발 전용**이다. 라이브러리 코드에는 `FastAPI()` 인스턴스가 없고,
> 호스트는 `create_wp_router()` 로 라우터만 마운트한다 ([`INTEGRATION.md`](INTEGRATION.md) §4).

### 3.2 프론트엔드 (개발 하니스)

```bash
cd frontend
npm run dev
```

<http://localhost:5180> 에서 열린다. 하니스는 **항상 실서버(8010)와 통신한다** —
목 모드는 없다. 백엔드가 죽어 있으면 상단에 빨간 배지가 뜨고 3초 간격으로
자동 재연결을 시도하므로, uvicorn 을 띄우면 곧바로 붙는다.
(`src/mock` 은 `npm run check` 자동 검증 전용이다.)

API 주소가 기본값(`http://127.0.0.1:8010`)과 다르면:

```bash
# frontend/.env.local
VITE_WP_API_BASE=http://다른호스트:포트
```

> **`/api/v1` 을 붙이지 말 것.** 클라이언트가 자동으로 덧붙인다(`api/client.ts:115`).
> 붙여 쓰면 `/api/v1/api/v1/...` 로 요청이 나간다.

---

## 4. 검증

작업 후에는 아래를 돌린다. **보고가 아니라 이 출력이 상태의 근거다.**

```bash
# 백엔드 단위/통합 테스트
cd backend && python -m pytest
# → 561 passed

# 배포 DB 가 엑셀 원본과 일치하는가 (스키마 + 데이터 드리프트)
python db/verify.py
# → OK: iai-test matches the Excel source (35 rows)

# 과거 감사 지적이 되살아나지 않았는가 (OPEN 이면 exit 1)
python backend/tests/audit/verify_findings.py
# → {'FIXED': 11, 'OPEN': 0, 'N-A': 5}

# 프론트: 타입체크 + 로직 검증 + DOM/CSS 격리 검사
cd frontend && npm run check
# → npm run verify 558 passed, 0 failed / npm run check:dom 418 passed, 0 failed
```

> **DB 를 쓰는 검증은 `WP_DB_PASSWORD` 를 요구한다** (저장소에 비밀번호를 두지 않는다).
> 미설정이면 pytest 의 DB 테스트는 그 이유를 밝히며 skip 되고, `db/*.py` 는 멈춘다.
>
> `db/verify.py` 가 **DRIFT 를 보고하는 것은 현재 정상이다** — 사용자가 실사용을
> 시작해 v2 발행·항목 편집이 쌓였고, 이 스크립트는 "단일 버전 · 엑셀 원본 일치" 라는
> 초기 납품 전제로 만들어졌다 ([`HANDOFF.md`](HANDOFF.md) §0.5). 자동 복구하지 말 것.
>
> `verify_findings.py` 의 **N-A 5건도 기존 드리프트**다. §0.5.10 에서 전역 문서 마스터를
> 폐기하면서 그 하네스가 참조하던 심볼(`docs_for` · `DocumentType` ·
> `repositories/document_type_repository.py`)이 사라졌다. **OPEN 이 0 인 것**이 이
> 스크립트가 지키는 조건이다.

### 라이브 통합 (실제 백엔드 + 실제 DB)

```bash
# 1) 백엔드를 8010 에 띄운 상태에서
cd frontend && npm run check:live
# → 47 passed, 0 failed
```

⚠️ **실행 후 정리가 필요하다.** 이 검증은 자기 스크래치 WP 를 만들지만
API 에 `DELETE /work-packages/{id}` 가 없어 **비활성 껍데기가 남는다.**
SQL 로 지운 뒤 `db/verify.py` 로 확인한다. 시드 보드(WP #1)는 건드리지 않으며,
검증 자체가 그 사실을 단언한다(`WP #1 untouched`).

---

## 5. 프로젝트 사용 여부와 관리자 도구

### 5.1 사용 여부 스위치 (UI)

**Integrated AI 참여 설비사 관리**(`./MakerSettings`) 화면은 설비사마다 그 설비사의
프로젝트를 나열하고, 각 프로젝트에 **사용 여부 on/off 스위치**를 둔다.

| | |
|---|---|
| 컬럼 | `wp_projects.is_active` |
| off 의 효과 | **전체 현황(`GET /projects/overview`)에서 빠진다.** 그게 전부다 |
| 남는 것 | 항목·상태·완료일·문서·링크 전부. 다시 켜면 그대로 돌아온다 |
| 저장 | 설비사 체크박스와 **같은 [저장] 버튼**, `PUT /makers/settings` 한 트랜잭션 |

이 화면의 프로젝트 목록에는 **꺼진 프로젝트도 나온다.** 다른 조회 경로
(`GET /projects`, 전체 현황)는 활성만 보여주므로, 이 화면까지 활성만 보여주면
스위치를 끄는 순간 다시 켤 화면이 사라져 off 가 편도 조작이 된다.
같은 이유로 프로젝트를 전부 꺼 둔 설비사도 설정 표에 남는다.

`DELETE /projects/{id}` 도 같은 컬럼을 끄는 **비활성화**이며 행을 지우지 않는다.

> ⚠️ **UI 어디에도 실제 삭제는 없다.** 그건 실수를 막는 설계이지 미구현이 아니다.

### 5.2 완전 삭제 — `db/delete_project.py` (관리자 도구)

데이터베이스에서 프로젝트를 **정말로 지우는 유일한 경로**다. API 에 없고, 관리자가
직접 실행한다.

```bash
# 접속 비밀번호는 환경변수로만 받는다 (저장소에 두지 않는다)
export WP_DB_PASSWORD=xxxx          # PowerShell: $env:WP_DB_PASSWORD = 'xxxx'

python db/delete_project.py 12                 # 12번 프로젝트 삭제
python db/delete_project.py 12 13 14           # 여러 개를 한 트랜잭션으로
python db/delete_project.py 12 --dry-run       # 지워질 건수만 세고 아무것도 안 함
python db/delete_project.py 12 --yes           # 확인 프롬프트 생략 (배치용)
python db/delete_project.py 12 --report r.json # 대상 상세를 UTF-8 JSON 으로
```

| 환경변수 | 기본값 |
|---|---|
| `WP_DB_HOST` | `localhost` |
| `WP_DB_PORT` | `3306` |
| `WP_DB_USER` | `user01` |
| `WP_DB_PASSWORD` | **없음 — 미설정이면 실행을 거부한다** |
| `WP_DB_NAME` | `iai-test` |

동작:

1. 지워질 행을 **표별로 먼저 센다**(`--dry-run` 이면 여기서 끝).
2. 확인 프롬프트는 y/N 이 아니라 **삭제할 id 를 그대로 다시 입력**받는다 — 되돌릴 수
   없는 조작에 습관적인 엔터가 통하면 안 되기 때문이다. `--yes` 로 생략할 수 있다.
3. FK **역순으로 직접** 지운다: `wp_project_item_owners` → `wp_project_item_documents`
   → `wp_project_items` → `wp_project_owners` → `wp_project_documents` →
   `wp_project_links` → `wp_project_milestones` → `wp_project_phases` → `wp_projects`.
   여러 프로젝트를 넘겨도 커밋은 한 번이다.

> `DELETE FROM wp_projects` 한 줄로 끝내지 않는 이유: `wp_project_items` 는
> `wp_project_phases` / `wp_project_milestones` 를 **`ON DELETE RESTRICT`** 로 참조하고
> `wp_project_item_owners` 는 `wp_project_owners` 를 같은 방식으로 참조한다
> (`db/schema.sql` 13·15). 캐스케이드 전파 순서가 그 제약을 먼저 건드리면 삭제 전체가
> FK 오류로 실패한다.

> ⚠️ **되돌릴 수 없다.** 백업이 없으면 복구 수단이 없다. 지우기 전에
> `--dry-run` 으로 대상과 건수를 먼저 확인할 것.

---

## 6. 구조

```
docs/            원본 엑셀, 대시보드 이미지
db/
  schema.sql     신규 설치 전용 DDL  ⚠️ 기존 DB 를 업그레이드하지 못한다
  migrations/    번호순 SQL 마이그레이션 — 업그레이드 경로
  seed.sql       엑셀 35행 시드
  migrate.py     엑셀 → DB 임포터 (CLI)
  verify.py      배포 DB ↔ 엑셀 대조 (스키마 + 데이터)
  delete_project.py  프로젝트 완전 삭제 — 관리자 전용, UI 에 없는 유일한 파괴 경로 (§5.2)
backend/
  import_excel.py  엑셀 → DB 초기값 임포트 진입점 (로직은 db/migrate.py 재사용)
  app/           router.py(마운트 팩토리) · services · api/v1 · models · repositories · ports
  app/standalone.py   개발 전용 앱 — 이식 시 삭제
  tests/         561 tests + tests/audit/ 재검증 하네스
frontend/
  src/index.ts   페더레이션 노출 진입점
  src/remote/    노출 컴포넌트
  src/components/grid/  AG Grid 셀 에디터·렌더러
  src/dev/  src/mock/   개발 전용 — 배포되지 않음
```

### 문서

| 파일 | 내용 |
|---|---|
| [`plan.md`](plan.md) | **정본 스펙** — 스키마 §3, API §4, 재계산 §2.2, 경계 규칙 §2.3, 버전 §2.4, 검증 §2.5 |
| [`INTEGRATION.md`](INTEGRATION.md) | **이식 계약** — 소유 경계, 설비사 외부 참조, 마운트/페더레이션 규칙, 이식 체크리스트 |
| [`TRANSPLANT.md`](TRANSPLANT.md) | **이관 절차서** — 실행 순서, 호스트용 DDL(`db/transplant.sql`), 마운트/페더레이션 코드 예시 |
| `backend/INTEGRATION.md` | 백엔드 이식 절차 |
| `frontend/INTEGRATION.md` | 페더레이션 노출·의존성 |
| [`CLAUDE.md`](CLAUDE.md) | 환경 사실, 도메인 불변조건 |
| [`HANDOFF.md`](HANDOFF.md) | 현재 상태, 운영 규칙, 되돌리면 안 되는 정정 사항 |

---

## 7. 호스트 프로젝트로 이관

이 저장소의 산출물은 **다른 프로젝트 안에서 동작하는 것이 최종 형태**다. 절차 전체는
[`TRANSPLANT.md`](TRANSPLANT.md) 가 실행 순서(9단계)로 안내한다 — 요약:

| 단계 | 작업 | 도구 |
|---|---|---|
| DB | 호스트 DB 에 `wp_*` 테이블 19개 생성 | [`db/transplant.sql`](db/transplant.sql) — `schema.sql` 에서 DB 생성/USE 만 뺀 자동 생성본 |
| DB (업그레이드) | 기존 설치는 마이그레이션 번호순 적용 | `db/migrations/001` → `005` |
| 백엔드 | `backend/app/` 복사 → 개발 전용 파일 삭제 → `MakerResolver` 구현 → `create_wp_router()` 마운트 | 코드 예시 TRANSPLANT.md §3 |
| 프론트 | `npm run build:remote` → 호스트 federation 등록(singleton 5종) → 노출 4개를 메뉴/라우트에 배치 → 미저장 가드 연결 | 코드 예시 TRANSPLANT.md §4 |
| 검증 | FK 0개·스타일 격리·싱글턴·가드 동작 확인 | 체크리스트 TRANSPLANT.md §5 |

- **계약의 정본은 [`INTEGRATION.md`](INTEGRATION.md)** — 무엇이 허용/금지인지는 그쪽이 최종이고, TRANSPLANT.md 는 그 계약을 순서대로 실행하는 절차서다.
- 노출 모듈은 4개: `ProjectsOverview`(메인) · `ProjectWorkspace` · `MasterAdmin`("Work Package 포맷 관리") · `MakerSettings`("Integrated AI 참여 설비사 관리").
- 설비사(maker) 테이블은 호스트 소유 — 이 모듈은 FK 없이 id 만 들고, 이름·목록은 `MakerResolver` 포트로 위임한다.
- `db/transplant.sql` 은 **직접 편집 금지** (schema.sql 이 정본, 재생성 방법은 TRANSPLANT.md §2.3).

## 8. 알아둘 함정

**한글이 콘솔에서 깨진다.** DB 행이나 엑셀 셀을 stdout 으로 출력하지 말 것.
UTF-8 로 임시 파일에 쓰고 열어 볼 것.

**AG Grid 는 Community 플랜만 쓴다.** Row Grouping / Excel Export / Context Menu /
Range Selection 은 Enterprise 다. Phase 그룹핑은 행 그룹핑이 아니라 **셀 렌더러 + 색상 밴딩**으로
구현돼 있다. Enterprise 의존성을 추가하지 말 것.

**`db/schema.sql` 은 기존 DB 를 업그레이드하지 못한다.** `CREATE TABLE IF NOT EXISTS` 라
컬럼이 추가되지 않는다. 업그레이드는 `db/migrations/` 로 한다. 이 규칙은
`tests/test_schema_migrations.py` 가 강제한다 — 컬럼을 추가하고 마이그레이션을 빠뜨리면
스위트가 깨진다.

**테스트가 통과한다고 그 테스트가 실패할 수 있다는 뜻은 아니다.** 이 저장소에서 실제로
네 번, 이름이 검증 내용보다 강하게 주장하는 테스트가 나왔고 그중 하나는 실제 버그를
감추고 있었다. 게이트를 추가할 때는 **먼저 깨뜨려서 빨간 것을 확인**할 것.
프론트 검증 스위트에 NEGATIVE CONTROL 이 상주하는 이유다.

**부하가 걸린 주장은 전수 탐색으로 결론지을 것.** "여러 경우를 확인했다"와
"정의역을 전수 열거했다"는 보고서에서 같은 모양이지만 증거로서의 무게가 다르다.
자세한 사례는 [`HANDOFF.md`](HANDOFF.md) §6.
