# TRANSPLANT.md — 호스트 프로젝트 이관 절차서

> **계약의 정본은 [`INTEGRATION.md`](INTEGRATION.md)** (+ `backend/INTEGRATION.md`, `frontend/INTEGRATION.md`) 다.
> 이 문서는 그 계약을 **실행 순서대로** 풀어 쓴 절차서이며, 충돌 시 INTEGRATION.md 가 우선한다.
>
> 이 저장소는 독립 실행형이 아니다. 백엔드는 **이미 가동 중인 FastAPI 프로젝트**에 라우터로 마운트되고,
> 프론트엔드는 **Module Federation remote** 로 호스트 앱에 편입된다.

## 0.0 먼저: 번들을 자동으로 만든다 — `tools/export_transplant.py`

아래 §1 의 목록을 손으로 옮기는 대신 한 번에 만든다.

```bash
python tools/export_transplant.py                    # _transplant/ 에 생성 (프론트=소스 복사)
python tools/export_transplant.py --out ../host       # 다른 위치에
python tools/export_transplant.py --frontend remote   # 프론트를 federation remote 로
python tools/export_transplant.py --frontend none     # 백엔드·DB 만
python tools/export_transplant.py --check-only        # 이미 만든 번들만 다시 감사
```

```
_transplant/
  backend/app/          FastAPI 모듈 — 개발 전용 파일이 **애초에 복사되지 않는다**
  db/transplant.sql     신규 설치용 DDL
  db/migrations/        기존 설치 업그레이드용
  docs/                 INTEGRATION.md · TRANSPLANT.md · backend-requirements.txt
  frontend/src/         (--frontend src, 기본) dev/ · mock/ 을 뺀 소스
  frontend/wp-board.css (--frontend src) 빌드된 스타일시트
  frontend/MERGE.md     (--frontend src) 편입 절차 — Tailwind 함정 포함
  frontend/dist-remote/ (--frontend remote)
```

> **프론트 소스 복사 시 유일한 함정: Tailwind 설정을 병합하지 말 것.** `prefix` 와
> `corePlugins.preflight` 는 **빌드 단위** 설정이라 한 빌드에 두 벌을 둘 수 없다. 호스트가
> Tailwind 를 기본 설정으로 쓰는데 `prefix: 'wp-'` 를 넣으면 호스트 자신의 유틸리티가 전부
> 무효가 된다. 대신 **빌드된 `wp-board.css` 한 장을 import** 하고, 호스트 Tailwind 의
> `content` 에서 우리 폴더를 **제외**한다. 자세한 것은 생성된 `frontend/MERGE.md`.

**요점은 복사가 아니라 복사 후 감사다.** 수동 이관의 실제 사고는 파일을 빠뜨리는 것이 아니라
**지워야 할 것을 남기는 것**이다 — `standalone.py` 하나가 따라가면 호스트 앱과 `FastAPI()` 가
충돌하고, `stub_maker_resolver.py` 가 남으면 호스트에 없는 `wp_dev_makers` 를 조회한다.
스크립트는 매번 여섯 가지를 확인하고, 하나라도 걸리면 **exit 1** 로 멈춘다:

| 검사 | 걸리면 생기는 일 |
|---|---|
| 개발 전용 파일 부재 | 호스트 앱과 충돌 / 없는 테이블 조회 |
| `FastAPI()` 인스턴스 부재 (AST) | 앱이 둘이 된다 |
| `os.environ`·`getenv` 직접 조회 부재 | 호스트 환경변수와 뒤섞인다 |
| `wp_dev_makers` 참조 · 설비사 JOIN 부재 | 호스트에 없는 테이블 (§2.1 위반) |
| `.env` 류 부재 | 개발 접속 정보 유출 |
| `transplant.sql` 에 `CREATE DATABASE`/`USE`·개발 스텁 부재 | 호스트 DB 를 갈아탄다 |
| (소스 복사) `dev/`·`mock/` 부재 | 하니스·목이 호스트 번들에 들어간다 |
| (소스 복사) **상대 import 자기완결성** | 호스트 빌드가 깨진다 |
| (소스 복사) `import.meta.env`·`vue-router`·antd 리셋 부재 | 개발값 고정 · 라우터 충돌 · 호스트 스타일 파괴 |
| (소스 복사) CSS 선택자가 전부 `wp-` 네임스페이스 | 호스트 스타일로 샌다 |

자기완결성 검사가 이 중 가장 강하다: `dev/`·`mock/` 을 뺀 뒤 남은 참조를 **실제로 풀어 본다.**
문자열 패턴은 참조가 어떤 모양일지 미리 알아야 하지만, 이쪽은 모양과 무관하게 잡는다.

> 문자열이 아니라 **AST** 로 보고, SQL 은 **주석을 걷어낸 뒤** 본다. 이 저장소의 주석은 금지
> 대상을 *설명하느라* 그 문자열을 그대로 담고 있어서, 순진하게 검색하면 자기 자신을 위반으로
> 잡는다 — 첫 실행에서 실제로 오탐 2건이 났고 셋 다 주석이었다.

이 스크립트는 **개발 도구다.** 호스트로 가져가지 않는다.

## 0. 이관 순서 한눈에

| 순서 | 작업 | 상세 |
|---|---|---|
| 1 | DB — `wp_*` 테이블 19개 생성 | §2 (`db/transplant.sql`) |
| 2 | 백엔드 — 모듈 복사, 개발 전용 파일 삭제 | §3.1~3.2 |
| 3 | 백엔드 — `MakerResolver` 구현 (호스트 `makers` 테이블 기반) | §3.3 |
| 4 | 백엔드 — `create_wp_router()` 마운트 | §3.4 |
| 5 | 프론트 — remote 빌드·배포 (`dist-remote/`) | §4.1 |
| 6 | 프론트 — 호스트 federation 설정 (singleton 5종) | §4.2 |
| 7 | 프론트 — 노출 4개를 호스트 메뉴/라우트에 배치 | §4.3 |
| 8 | 프론트 — `hasUnsavedChanges()` 라우터 가드 연결 | §4.4 |
| 9 | 검증 체크리스트 | §5 |

---

## 1. 구성 요소

| 경로 | 이관 대상? | 내용 |
|---|---|---|
| `db/transplant.sql` | ✅ | 호스트 DB 용 DDL (테이블 19개, 아래 §2) |
| `db/migrations/` | ✅ (업그레이드 시) | 번호순 SQL 마이그레이션 001~006 |
| `backend/app/` | ✅ | FastAPI 모듈 (라우터 팩토리·서비스·모델) |
| `frontend/dist-remote/` | ✅ (빌드 산출물) | Module Federation remote |
| `backend/app/standalone.py` 등 | ❌ 삭제 | 개발 전용 (§3.2 목록) |
| `db/schema.sql`, `db/seed.sql`, `db/dev_seed.sql`, `db/migrate.py`, `db/verify.py` | ❌ | 개발/시드 도구 (호스트에 가져가지 않는다) |

---

## 2. DB

### 2.1 신규 설치 — `db/transplant.sql`

호스트 DB 를 선택(USE)한 상태에서 **`db/transplant.sql`** 을 실행한다.
`db/schema.sql` 에서 `CREATE DATABASE` / `USE` 두 문장만 제거한 자동 생성본이며, `wp_` 접두 테이블 19개를 만든다 (기존 테이블과 이름 충돌 없음).

생성되는 테이블(의존 순서 = 파일 내 순서):

| 계열 | 테이블 | 역할 |
|---|---|---|
| 템플릿 | `wp_templates` `wp_versions` `wp_phases` `wp_milestones` `wp_owners` **`wp_template_documents`** `wp_items` `wp_item_documents` `wp_item_owners` | 중앙 기준 데이터 (버전 관리) |
| 프로젝트 | `wp_projects` `wp_project_phases` `wp_project_milestones` `wp_project_owners` `wp_project_items` **`wp_project_documents`** `wp_project_item_documents` `wp_project_item_owners` | 설비사별 보드 (발행본 스냅샷, 버전 없음) |
| 프로젝트 부가 | `wp_project_links` (주요 링크) | |
| 설비사 부가 | `wp_maker_settings` (전체 현황 표시 여부 — 호스트 `makers.id` 논리 참조, **물리 FK 없음**) | |

> **전역 테이블은 없다** (plan.md §0.5.10). 문서는 `wp_document_types` 라는 전역
> 마스터였다가 **템플릿 소유 + 프로젝트 복제**로 바뀌었다 — Phase/Milestone/Owner 와
> 같은 규칙이다. 그래서 "호스트 문서 마스터와 병합" 이라는 이음매(구 INTEGRATION §3)와
> `document_type_repository_factory` 주입 파라미터가 함께 사라졌다.

**호스트 테이블로 향하는 FK 는 하나도 없다.** `maker_id` 는 `wp_projects` · `wp_maker_settings` 두 곳뿐이며 인덱스만 있다 (호스트가 `BIGINT`/`UUID` 를 쓰면 이 두 컬럼만 타입 변경).

### 2.2 기존 설치 업그레이드 — `db/migrations/`

이미 운영 중인 설치에는 `transplant.sql` 이 아니라(‑ `CREATE TABLE IF NOT EXISTS` 라 컬럼 추가가 안 된다) **`db/migrations/` 를 번호순으로** 호스트의 마이그레이션 러너로 적용한다:

```
001_initial.sql            테이블 초기 세트
002_dash_label.sql         wp_items·wp_project_items 에 dash_label
003_project_documents.sql  wp_project_documents
004_maker_settings.sql     wp_maker_settings
005_project_links.sql      wp_project_links
006_document_ownership.sql 문서 모델 개편 — 전역 wp_document_types 폐기,
                           wp_template_documents 신설 + 프로젝트 복제,
                           링크 재매핑 (**데이터 이행 포함**)
```

> ⚠️ **006 은 데이터 이행을 포함한다.** 전역 문서를 각 템플릿·프로젝트로 복제하고
> 링크를 재매핑한 뒤에야 원본을 지운다. 적용 직후 파일 끝 주석의 검증 쿼리 3종이
> 전부 0 인지, 링크 총수가 적용 전과 같은지 확인할 것.

### 2.3 `transplant.sql` 재생성 (스키마가 바뀌었을 때)

정본은 `db/schema.sql` 이다. 재생성:

```bash
python - <<'EOF'
import io, re
src = io.open('db/schema.sql', encoding='utf-8').read()
body = re.sub(r'(?m)^(CREATE DATABASE|USE ).*\n', '', src)
head = io.open('db/transplant.sql', encoding='utf-8').read().split('-- [DDL]\n', 1)[0]
io.open('db/transplant.sql', 'w', encoding='utf-8').write(head + '-- [DDL]\n' + body)
EOF
```

### 2.4 적용하지 말 것

- `db/dev_seed.sql` — 개발 스텁 (`wp_dev_makers`, 데모 프로젝트). **호스트에 절대 미적용.**
- `db/seed.sql` — 엑셀 원본 35행 시드. 초기 템플릿이 필요하면 검토 후 선택 적용 (백틱 `iai-test` 참조 제거 필요).

---

## 3. 백엔드

### 3.1 복사

`backend/app/` 패키지를 호스트 프로젝트 아래로 통째로 옮긴다 (내부는 전부 상대 import — 부모 경로 무관).
의존성은 `backend/requirements.txt` 를 **호환 범위 선언**으로 읽고 호스트 버전과 대조한다:
`fastapi>=0.115` · `SQLAlchemy>=2.0.30,<2.1` · `pydantic>=2.7` · `pydantic-settings>=2.3` · `PyMySQL>=1.1.1` · `python-pptx>=1.0`(PPT 내보내기 안 쓰면 생략 가능 — 없어도 라우터는 뜨고 해당 엔드포인트만 501) · openpyxl(XLSX 내보내기).

### 3.2 삭제 (개발 전용 — 반드시)

```
backend/app/standalone.py            # 유일한 FastAPI() 생성 지점 — 호스트 앱과 충돌 방지
backend/app/ports/stub_maker_resolver.py
backend/tests/
backend/.env  backend/.env.example   # 개발 접속 정보 — 애초에 복사해 오지 말 것
db/migrate.py  db/verify.py         # 함께 삭제 (verify 가 migrate 를 import 한다)
db/delete_project.py                # 관리자용 삭제 스크립트 (개발 DB 기준)
db/dev_seed.sql
```

환경변수도 `.env` 도 필요 없다 — 세션 팩토리를 주입받으므로 라이브러리 경로는 `WP_*` 없이
동작한다. `.env` 를 읽는 코드는 위 삭제 목록 안에만 있고, `core/config.py` 에는 `env_file` 이
없다. `python-dotenv` 도 `requirements-dev.txt` 에만 있으므로 호스트 의존성에 추가되지 않는다.

### 3.3 MakerResolver 구현 (호스트 `makers` 테이블)

호스트 모델이 `makers(id, maker, maker_ko, maker_en, maker_alias)` 일 때의 구현 예:

```python
from app.ports.maker_resolver import MakerResolver  # 이관된 경로에 맞게 조정

class HostMakerResolver:
    """호스트 makers 테이블 → WP 모듈 포트. 표시명 규칙은 호스트가 정한다."""
    def __init__(self, session_factory):
        self._sf = session_factory

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        with self._sf() as s:
            rows = s.query(Maker).filter(Maker.id.in_(maker_ids)).all()
            return {m.id: (m.maker_ko or m.maker) for m in rows}

    def exists(self, maker_id: int) -> bool:
        with self._sf() as s:
            return s.query(Maker.id).filter(Maker.id == maker_id).first() is not None

    def list_makers(self) -> list[tuple[int, str]]:
        # 설비사 설정·전체 현황용 — 프로젝트가 없는 설비사도 나와야 한다 (plan.md §0.6)
        with self._sf() as s:
            return [(m.id, m.maker_ko or m.maker) for m in s.query(Maker).order_by(Maker.id)]
```

미주입도 정상 동작한다(이름 생략·목록 빈 값). `list_makers` 가 없는 구 구현도 죽지 않지만, 설비사 설정 화면이 목록을 못 받으므로 **새 호스트는 반드시 구현**한다.

### 3.4 마운트

```python
from app.router import create_wp_router   # 이관된 경로에 맞게 조정

app.include_router(
    create_wp_router(
        session_factory=host_session_factory,          # 호스트의 sessionmaker
        maker_resolver=HostMakerResolver(host_session_factory),
        prefix="/api/v1/wp",                           # 호스트 URL 정책에 맞게
    )
)
```

- import 시점 부작용 없음(엔진·CORS·미들웨어·로깅 없음) — CORS 등은 호스트 앱 설정을 그대로 쓴다.
- `prefix` 를 바꾸면 프론트의 `apiBaseUrl` 뒤에 클라이언트가 `/api/v1` 을 덧붙이는 규약과 맞는지 확인한다
  (`frontend/INTEGRATION.md` — 기본 규약은 `apiBaseUrl` = 프리픽스 **앞**까지).

---

## 4. 프론트엔드

### 4.1 빌드

```bash
cd frontend && npm run build:remote     # → dist-remote/ (remoteEntry.js 포함)
```

`dist-remote/` 를 정적 호스팅하고 호스트에서 그 URL 을 remote 로 등록한다. `src/dev/`·`src/mock/` 은 번들에 없다.

### 4.2 호스트 federation 설정

**singleton 5종의 버전이 호스트와 겹치는지 먼저 확인한다**: `vue ^3.5` · `ant-design-vue ^4.2` · `ag-grid-community 33.3` · `ag-grid-vue3 33.3` · `dayjs ^1.11`.

```ts
// 호스트 vite.config.ts (webpack 도 동형)
federation({
  remotes: { wpBoard: { type: 'module', entry: 'https://…/remoteEntry.js' } },
  shared: {
    vue: { singleton: true },
    'ant-design-vue': { singleton: true },
    'ag-grid-community': { singleton: true },
    'ag-grid-vue3': { singleton: true },
    dayjs: { singleton: true },
  },
})
```

### 4.3 노출 4개 → 호스트 메뉴/라우트

| 노출 | 권장 메뉴/라우트 | 필수 props |
|---|---|---|
| `wpBoard/ProjectsOverview` | **메인** — `/wp` | `apiBaseUrl`, `onOpenProject` |
| `wpBoard/ProjectWorkspace` | `/wp/:projectId` | `apiBaseUrl`, `makerId`, `projectId` |
| `wpBoard/MasterAdmin` | 관리 > "Work Package 포맷 관리" | `apiBaseUrl` |
| `wpBoard/MakerSettings` | 관리 > "Integrated AI 참여 설비사 관리" | `apiBaseUrl` |

```ts
// 호스트 라우터 예 — URL 소유는 호스트다 (모듈은 URL 을 읽지도 쓰지도 않는다)
{ path: '/wp', component: () => import('wpBoard/ProjectsOverview'),
  props: { apiBaseUrl: API_BASE,
           onOpenProject: (projectId: number, makerId: number) =>
             router.push(`/wp/${projectId}`) } },
{ path: '/wp/:projectId', component: () => import('wpBoard/ProjectWorkspace'),
  // makerId 는 onOpenProject 인자로 받거나, 딥링크면 GET /projects/{pid} 의 maker_id 로 해석
  props: route => ({ apiBaseUrl: API_BASE, projectId: Number(route.params.projectId), makerId: resolvedMakerId }) },
```

`apiBaseUrl`·토큰은 **런타임 props** 로 넘긴다 (빌드타임 env 금지 — 개발값이 번들에 박힌다).

### 4.4 미저장 보호

이 패키지는 의도적으로 `vue-router` 가 없다. **호스트 라우터 가드에 `hasUnsavedChanges()` 를 연결하지 않으면
편집 중 화면 이동 시 변경이 조용히 사라진다** (자동저장은 없다 — 수동 저장뿐, plan.md §0.5.8):

```ts
onBeforeRouteLeave(() => {
  if (wpRef.value?.hasUnsavedChanges()) return window.confirm('저장하지 않은 변경이 있습니다. 나가시겠습니까?')
})
```

---

## 5. 검증 체크리스트

- [ ] `wp_*` 테이블 19개 생성 확인, 호스트 테이블로의 FK **0개** 확인
- [ ] 라우터 마운트 후 `GET {prefix}/templates` · `GET {prefix}/projects/overview` 200
- [ ] resolver 주입 상태에서 overview 에 설비사 이름이 나오는지 (미주입이면 `설비사 #id` 폴백)
- [ ] 호스트 화면에서 remote 마운트 → 언마운트 → 재마운트 반복, 콘솔 오류·타이머 잔존 없음
- [ ] 호스트의 기존 화면 스타일이 remote 마운트 후에도 변하지 않는지 육안 확인 (Tailwind `wp-` prefix / preflight off)
- [ ] singleton 5종이 **한 인스턴스**인지 (Vue devtools 에 Vue 가 두 개 뜨면 실패)
- [ ] 라우터 가드에서 미저장 확인이 동작하는지 (§4.4)
- [ ] XLSX / PPTX 내보내기 다운로드 동작 (PPT 미사용 호스트는 python-pptx 미설치 → 해당 버튼만 실패가 정상)
