# Integration Rules

이 저장소의 코드는 **독립 실행형 애플리케이션이 아니다.** 프론트엔드는 다른 프로젝트에 **Module Federation remote** 로 편입되고, 백엔드는 **이미 가동 중인 다른 FastAPI 프로젝트**에 이식된다.

따라서 호스트 프로젝트에 대한 결합(host coupling)은 스타일 문제가 아니라 **결함**으로 취급한다. 이 문서가 그 경계에 대한 최종 계약이며, `backend/INTEGRATION.md` 와 `frontend/INTEGRATION.md` 는 이 문서를 각 측면에서 구체화한다. **실행 순서대로 따라 하는 절차서는 [`TRANSPLANT.md`](TRANSPLANT.md)** (호스트용 DDL `db/transplant.sql` 포함).

---

## 1. 소유 경계 (Ownership Boundary)

| 대상 | 소유자 | 비고 |
|---|---|---|
| Work Package / 버전 / 항목 | **이 저장소** | `wp_` 접두 테이블 |
| Phase / Milestone / Owner 기준정보 | **이 저장소** | WP 스코프 |
| 문서 (Document) | **이 저장소** | 템플릿 소유 + 프로젝트 복제 (§3 — 전역 아님, plan.md §0.5.10) |
| **설비사(Maker)** | **호스트 프로젝트** | §2 — 여기서 테이블을 만들지 않는다 |
| 인증 / 사용자 / 권한 | **호스트 프로젝트** | 이번 범위 밖 |
| 라우팅 / 레이아웃 / 전역 스타일 | **호스트 프로젝트** | 프론트는 컴포넌트만 제공 |

---

## 2. 설비사(Maker) — 외부 참조 규칙

**확정 사항 (plan.md §0 개정 반영)**: 설비사는 여러 개 존재하고, **설비사 하나가 여러 프로젝트를 가진다** (1:N). 프로젝트는 중앙 템플릿의 발행본에서 생성된다. 설비사 테이블은 **이미 다른 프로젝트에 선언되어 있으므로 이 저장소에서 생성하지 않는다.** `maker_id` 는 **프로젝트에만** 있다 — 템플릿은 중앙 소유다.

### 2.1 DB 규칙

```sql
-- wp_projects
maker_id INT NOT NULL,              -- 호스트 설비사 테이블의 PK (논리적 참조)
KEY idx_wp_maker (maker_id),        -- 인덱스만 건다
UNIQUE KEY uq_wp_maker_code (maker_id, code)
-- FOREIGN KEY 제약을 걸지 않는다
```

- **물리 FK 제약 금지.** 대상 테이블이 이 스키마에 없고, 별도 DB/스키마에 있을 수도 있다. 제약을 걸면 이식 시 DDL 이 실패한다.
- **인덱스는 반드시 건다.** 조회는 항상 `maker_id` 로 필터링된다.
- 타입은 `INT` 로 가정한다. 호스트가 `BIGINT` 또는 `UUID`/`VARCHAR` 를 쓴다면 **이 컬럼 하나만** 바꾸면 되도록 다른 곳에 타입 가정을 퍼뜨리지 않는다.
- **설비사 테이블로의 JOIN 을 작성하지 않는다.** 쿼리는 `maker_id` 값까지만 다룬다.

### 2.2 애플리케이션 규칙

설비사 이름 등 부가 정보가 필요하면 **포트(port)를 통해 호스트에게 위임**한다. 직접 조회하지 않는다.

```python
# backend/app/ports/maker_resolver.py
class MakerResolver(Protocol):
    def resolve(self, maker_ids: list[int]) -> dict[int, str]: ...
    def exists(self, maker_id: int) -> bool: ...
    def list_makers(self) -> list[tuple[int, str]]: ...   # (id, 표시명) — 설비사 설정·전체 현황용 (plan.md §0.6)
```

- 호스트는 **`create_wp_router(maker_resolver=...)`** 로 구현체를 주입한다 (`backend/app/router.py:32`). 별도의 `configure()` 함수는 **없다** — 주입 지점은 라우터 팩토리 하나다.
- `list_makers()` 의 표시명은 호스트가 정한다 — 예: `maker_ko or maker`. 호스트 스키마(`makers(id, maker, maker_ko, maker_en, maker_alias)`)에 우리 코드는 컬럼을 추가하지 않으며, 전체 현황 표시 여부 같은 우리 쪽 부가 상태는 `wp_maker_settings(maker_id UNIQUE, …)` 에 물리 FK 없이 둔다.
- `resolve()` 로 `list_makers()` 를 대신할 수 없다. 그쪽은 **이미 아는 id** 의 이름을 채우는 것이고, 이쪽은 **아직 프로젝트가 하나도 없는 설비사**까지 알아야 한다 — 설정에서 체크해 두면 프로젝트 0개인 설비사도 전체 현황에 섹션이 나와야 하기 때문이다 (plan.md §0.6-1).
- **`maker_id` 를 가진 테이블은 이제 둘이다** (`wp_projects`, `wp_maker_settings`). 호스트가 id 타입을 바꾼다면 두 컬럼 다 바꾼다. 개수는 `test_transplant_contract.py::test_maker_id_has_an_index_but_no_foreign_key` 가 고정한다.
- **미주입이 정상 상태다.** resolver 가 없으면 API 는 `maker_id` 만 반환하고 `maker_name` 은 생략하며, `list_makers()` 는 빈 목록으로 간주한다. 예외를 던지지 않는다.
- **`list_makers()` 는 나중에 추가된 메서드라 없어도 죽지 않는다.** §0.6 이전 계약(`resolve`/`exists` 두 개)에 맞춰 구현한 호스트가 그대로 살아 있을 수 있으므로, 이 모듈은 `getattr` 로 확인하고 없으면 빈 목록으로 취급한다 (`ports/maker_resolver.py:list_makers`). 그런 호스트에서도 보드·프로젝트는 전혀 영향받지 않고, 설비사 설정 화면만 "목록을 제공하지 않는 호스트" 로 동작한다 — 그때 전체 현황은 **프로젝트가 실제로 참조하는 `maker_id`** 로 폴백하므로 기존 프로젝트는 계속 보인다. 새 호스트는 반드시 구현할 것.
- `list_makers()` 가 `(id, name)` 쌍이 아닌 것을 돌려주면 빈 목록으로 떨어진다. 절반만 해석된 목록을 화면에 내보내지 않는다.
- 고아 참조(`maker_id` 가 호스트에 없는 경우)는 **조회를 깨뜨리지 않는다.** 이름을 비우고 넘어간다. 물리 FK 가 없으므로 정합성은 호스트가 책임진다.
- **생성 시에만** `exists()` 검증을 수행하며, 그것도 resolver 가 주입된 경우에 한한다. 수정은 `maker_id` 를 받지 않으므로(`WorkPackageUpdateIn` 에서 제외) 검증할 대상이 없다.

### 2.3 개발 전용 스텁

로컬 단독 실행을 위해 `db/dev_seed.sql` 에 `wp_dev_makers` 를 둔다.

- 이름에 `dev` 를 명시하고, **이식 시 삭제 대상**임을 주석과 `INTEGRATION.md` 양쪽에 기록한다.
- 운영 스키마(`db/schema.sql`)에는 **포함하지 않는다.**
- 이 테이블을 참조하는 코드는 `StubMakerResolver` 한 곳뿐이어야 한다.

### 2.4 프론트엔드 규칙

- 설비사 목록/이름을 조회하는 API 를 이 모듈이 갖지 않는다.
- 노출 컴포넌트는 `makerId` 를 **필수 prop** 으로 받는다. 설비사 선택 UI 는 호스트의 책임이다.
- 표시용 이름이 필요하면 `makerName` 을 선택적 prop 으로 받는다.

---

## 3. 문서 — 전역이 아니다 (구 "호스트 문서 마스터 병합 지점" 폐기)

**이 절은 폐기됐다** (plan.md §0.5.10, 2026-08-08 사용자 확정).

문서는 전역 `wp_document_types` 였고 호스트 문서 마스터와의 **가장 유력한 병합 지점**
이었다. 사용자 결정으로 문서가 Phase/Milestone/Owner 와 같은 스코프 규칙 위로
옮겨지면서 그 이음매 자체가 없어졌다:

- **포맷(템플릿)이 소유**한다 — `wp_template_documents(template_id, name, sort_order)`
- **프로젝트 생성 시 복제**된다 — `wp_project_documents(project_id, name, sort_order, …)`
- 표시 번호는 `sort_order`(1..N). 원문자 코드(①②)는 폐기.

따라서 **`create_wp_router(document_type_repository_factory=...)` 파라미터는 없다.**
`app/repositories/` 패키지도 삭제됐다. 호스트가 문서에 대해 할 일은 아무것도 없다 —
전역 테이블이 없으므로 충돌할 것도, 병합할 것도 없다.
`test_transplant_contract.py::test_no_document_repository_seam_remains` 가 그 부재를
고정한다.

---

## 4. 백엔드 — 마운트 계약

**애플리케이션이 아니라 모듈이다.**

- 라이브러리 코드에 `FastAPI()` 인스턴스를 만들지 않는다. `create_wp_router(prefix=...)` 팩토리가 완전히 배선된 `APIRouter` 를 반환한다. 호스트는 import 한 줄 + `include_router` 한 줄이면 된다.
- **import 시점 부작용 금지**: 엔진 생성, CORS, 미들웨어, 로깅 설정, `create_all()` 전부 금지.
- 세션 팩토리는 호스트가 주입한다. 모듈 파일을 수정하지 않고 교체 가능해야 한다.
- 설정은 `WP_` 접두 환경변수(pydantic-settings). 코드 곳곳의 `os.environ` 직접 조회 금지.
- 자체 `Base`, `wp_` 접두 테이블명, **호스트 테이블로 향하는 FK 없음**.
- 패키지 내부는 상대 import — 다른 부모 경로 아래로 통째로 옮겨도 동작해야 한다.
- `backend/app/standalone.py` 만이 앱을 구성하는 유일한 지점이며 **개발 전용**이다.

## 5. 프론트엔드 — 페더레이션 계약

**앱이 아니라 노출 컴포넌트다.**

- **전역 CSS 오염 금지** — 페더레이션 remote 가 호스트를 망가뜨리는 가장 흔한 경로다. Tailwind 는 `corePlugins.preflight: false` + `wp-` prefix, `content` 는 이 패키지로만 한정. antd 전역 reset 미사용, `ConfigProvider` 는 노출 컴포넌트 내부에 가둔다.
- `vue-router` 를 import 하거나 존재를 가정하지 않는다. 화면 전환은 props/주입 콜백으로 호스트에 위임한다.
- 호스트의 활성 Pinia 에 의존하지 않는다. 두 인스턴스가 동시에 마운트돼도 상태가 섞이는 모듈 스코프 가변 상태를 두지 않는다.
- API base URL·토큰은 **런타임**에 props 또는 `configure()` 로 받는다. 모듈 스코프의 `import.meta.env` 조회는 개발값을 번들에 박아버리므로 금지.
- **singleton 은 5개다**: `vue`, `ant-design-vue`, `ag-grid-community`, `ag-grid-vue3`, **`dayjs`**. dayjs 버전이 어긋나면 DatePicker 로케일이 갈린다.
- 노출 모듈은 **넷**이다 (plan.md §0 개정·§0.5·§0.6): `./ProjectsOverview` (**메인 페이지** — 전체 현황 허브, maker 무관, [이동] 은 `onOpenProject(projectId, makerId)` 콜백으로 호스트에 위임), `./ProjectWorkspace` (설비사 프로젝트 세부 — `makerId`·`projectId` 필수 prop, 프로젝트 목록 화면은 없다: 진입은 전체 현황의 `onOpenProject` 가 유일하며 projectId 미지정 마운트는 빈 상태 안내를 렌더), `./MasterAdmin` (Work Package 포맷 관리 — 템플릿·전역 문서, maker 무관), `./MakerSettings` (Integrated AI 참여 설비사 관리 — 전체 현황 표시 여부, maker 무관). 권장 메뉴: 전체 현황을 기본 진입으로, MasterAdmin·MakerSettings 는 **관리** 그룹 하위에 "Work Package 포맷 관리" · "Integrated AI 참여 설비사 관리" 라벨로. 메뉴와 라우팅 소유는 호스트다.
- **권장 라우트 (plan.md §0.6-4)**: 전체 현황 경로 아래 `/{projectId}` 로 프로젝트 세부를 표현한다 — 예: `/wp` → ProjectsOverview, `/wp/:projectId` → ProjectWorkspace. `onOpenProject(projectId, makerId)` 를 받으면 호스트 라우터가 그 경로로 push 하고, 딥링크/새로고침은 `GET /api/v1/projects/{pid}` 의 `maker_id` 로 `makerId` prop 을 해석해 마운트한다. 모듈은 URL 을 읽지도 쓰지도 않는다.
- 노출 컴포넌트는 반복 마운트/언마운트를 견뎌야 한다 — 그리드 인스턴스, 리스너, 타이머를 정리한다.
- `src/dev/` (로컬 하니스) 와 `src/mock/` (목 API) 는 **둘 다 개발 전용**이며 배포되지 않는다. `src/index.ts` 에서 도달 불가능해야 한다.

---

## 6. 이식 체크리스트

이식 시점에 아래를 확인한다.

**백엔드**
- [ ] ⚠️ **`db/schema.sql` 의 첫 두 줄(`CREATE DATABASE ... iai-test` / `USE iai-test`)을 반드시 제거한 뒤** 호스트 DB 위에서 `CREATE TABLE` 만 실행한다. 그대로 돌리면 — 실행 계정에 `CREATE DATABASE` 권한이 있으면 **오류 없이 새 `iai-test` DB 에 전 테이블이 생기고**, 권한이 없으면 첫 줄에서 실패한다. 어느 쪽이든 두 줄을 지우고 실행해야 한다. (`wp_` 접두라 테이블명 충돌은 없음)
- [ ] **이후 버전 업그레이드는 `db/migrations/` 를 호스트의 마이그레이션 러너로 적용한다.** `schema.sql` 은 **신규 설치 전용**이며, `CREATE TABLE IF NOT EXISTS` 라서 기존 DB 에 컬럼을 추가하지 **못한다**. 상세: `db/migrations/README.md`
- [ ] `db/dev_seed.sql` 과 `wp_dev_makers` **미적용**
- [ ] `create_wp_router(prefix=..., session_factory=...)` 로 라우터 마운트 — import 한 줄 + `include_router` 한 줄
- [ ] `MakerResolver` 구현체 주입 (선택 — 미주입 시 `maker_id` 만 반환하며 정상 동작)
- [ ] 삭제: `backend/app/standalone.py`, `backend/app/ports/stub_maker_resolver.py`, `db/dev_seed.sql`, `db/migrate.py`(**하드코딩된 접속정보 포함**), **`db/verify.py`**, `backend/tests/`
  > `verify.py` 는 모듈 로드 시점에 `migrate.py` 를 import 한다(`verify.py:48`). **둘은 반드시 함께 지운다** — `migrate.py` 만 지우면 남은 `verify.py` 가 import 에서 죽는다. 어차피 `verify.py` 는 `iai-test` 를 엑셀 원본과 대조하는 도구라 이식 후에는 의미가 없다.
- [ ] `WP_*` 환경변수는 **불필요하다** — 세션 팩토리를 주입받으므로 라이브러리 경로는 환경변수 없이 동작한다. `standalone.py` 전용이다

**프론트엔드**
- [ ] remote 등록 후 `./WorkPackageBoard` import
- [ ] `makerId`(필수), API base URL, `authToken` 주입
- [ ] **`hasUnsavedChanges()` 를 호스트 라우터 가드에 연결** — 이 패키지는 의도적으로 `vue-router` 를 갖지 않으므로, 호스트가 연결하지 않으면 **저장 안 된 DRAFT 편집이 화면 이동 시 조용히 사라진다.** 모듈 쪽에서는 감지할 수 없다
- [ ] shared singleton **5종**(dayjs 포함) 버전이 호스트와 일치하는지 확인
- [ ] 호스트 화면에서 스타일 오염 없는지 육안 확인 (Tailwind prefix / preflight)
- [ ] `src/dev/` 와 `src/mock/` 미배포 확인
- [ ] 마운트 → 언마운트 → 재마운트 동작 확인
