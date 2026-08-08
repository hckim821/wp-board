# HANDOFF — 세션 인수인계

> 토큰 만료 대비 작성. 새 세션은 **이 파일 → `CLAUDE.md` → `plan.md` → `INTEGRATION.md`** 순으로 읽으면 이어서 작업할 수 있다.
> 최종 갱신: 2026-08-07

---

## 0. ✅ 아키텍처 개정 완료 (2026-08-07~08)

사용자가 사이트 시나리오를 정정했다. **`plan.md` §0** 이 신설됐고 충돌 시 우선한다:

- **2계층**: 중앙 기준 데이터(템플릿 — 버전 관리 유지) → 설비사별 프로젝트(발행본에서 스냅샷 복제, **버전/발행/이력 없음**, 자유 편집)
- **행 추가 개정**: 두 추가 방식 모두 **미배정(회색) 행** 생성. null 행은 연속성에 투명, 어디로든 드래그 가능, 이웃 phase 가 다를 때만 새 Phase 생성 가능. 두 블록 사이 회색 행 + 새 Phase 생성 = "사이에 추가"
- 테이블: `wp_work_packages`→`wp_templates`(maker_id 제거), `wp_projects` 계열 신설. URL `/work-packages`→`/templates` + `/projects`. 마이그레이션은 **재베이스라인** (도입 호스트 0)
- **완료·검증됨 (오케스트레이터 직접 실행)**: 백엔드 **277 passed**, 프론트 **133 passed**, 라이브 통합 **90 passed** (템플릿 51 + 프로젝트 계열 10a–10e·지문 대조), 감사 하네스 15 FIXED/0 OPEN/0 N-A, `verify.py` OK
- 라이브 검증이 §0 핵심 불변조건을 직접 단언한다: 프로젝트 편집이 템플릿에 전파되지 않음(지문 대조), 프로젝트에 버전 표면 없음(404 + 템플릿 CONTROL), 템플릿 phase id 를 프로젝트 행에 못 씀(스코프 분리)
- `iai-test` 최종: 템플릿 1(DSEP-AI-BOARD, 엑셀 35행) + 데모 프로젝트 1(클릭용, active). 스크래치 잔여물 정리됨
- ⚠️ 서버 정리 시 주의: uvicorn 부모를 죽여도 **자식 워커가 소켓을 물고 살아남아 구버전 코드를 계속 서빙**할 수 있다 (spawn_main 자식). 포트가 이상하면 `Get-NetTCPConnection` 으로 소유 PID 를 확인하고 죽은 PID 면 multiprocessing 자식을 찾을 것

## 0.5 ⚠️ 실사용 시작 (2026-08-08) — verify.py 의 전제가 바뀌었다

사용자가 실서버로 시스템을 **실사용**하기 시작했다. 템플릿 발행·프로젝트 생성·항목 편집은 이제 정상적인 사용자 데이터다.

- **`db/verify.py` 가 DRIFT 를 보고해도 그것은 사용자 작업일 수 있다. 절대 자동 복구·재시드하지 말 것.** verify 의 "엑셀 원본과 일치" 전제는 초기 납품 검증용이었고 더 이상 성립하지 않는다.
- **개발 하니스에 목 모드는 없다 (2026-08-08 사용자 결정).** 항상 실서버(8010)와만 통신하며, 백엔드가 죽어 있으면 빨간 배지 + 3초 간격 자동 재연결. `src/mock` 은 `npm run check` 자동 검증 전용으로만 남는다.
- 과거 "실서버 전환 시 연결 안 됨"의 원인: `standalone.py` CORS 가 5173 만 허용했는데 하니스는 **5180** 에서 뜬다. 지금은 `allow_origin_regex` 로 로컬 오리진 전체 허용. API 기본 주소도 IPv6 함정을 피해 `http://127.0.0.1:8010`.
- 엑셀 → DB 초기값 임포트 진입점: `backend/import_excel.py` (로직은 `db/migrate.py` 재사용, 양식은 현 엑셀 레이아웃 고정).
- **`db/verify.py` 는 이제 실제로 DRIFT 를 보고한다 (정상).** 사용자가 v2 를 발행해 v1 ARCHIVED / v2 PUBLISHED 상태다. verify 의 단일 버전·엑셀 일치 전제는 깨졌고, 이는 손상이 아니다. 재확인 기준은 pytest / npm run check / check:live 로 옮겨졌다.

## 0.6 ✅ Phase/Milestone 관리 팝업 (2026-08-08, plan.md §0.4)

생성·이름변경·삭제(캐스케이드)·순서변경을 관리 팝업 하나로 통일. 팝업 표의 위→아래 순서 = 보드 블록 순서이며 번호는 §2.2 재계산이 파생한다 (행 없는 Phase 는 존재 불가 — 앵커 회색 행 또는 빈 행 1개와 함께 생성). §0.2-4 의 "이웃이 달라야 생성 가능" 제약 폐기. 배정 셀 클릭 = [수정]/[재배치]/[취소]. 기준정보 탭에서 Phase/Milestone 메뉴 제거(Owner·문서 유지).

- API: `POST .../phases/apply`, `POST .../phases/{id}/milestones/apply` (템플릿 DRAFT/프로젝트 각각, 원자적 1 트랜잭션). 응답 `{items, phases, milestones}`. 에러 코드 7종 — plan.md §0.4 "구현 시 확정된 정밀화" 4건 포함, **되돌리지 말 것**.
- 구현: `backend/app/services/apply_service.py` + `api/v1/apply.py`, 프론트 `components/StructureManagerModal.vue` + 셀 에디터 개편 + mock 엔진 동일 의미론.
- 오케스트레이터 직접 검증 (2026-08-08): 백엔드 **318 passed** (신규 33, 순열 전수 포함) · 프론트 `npm run check` **167 passed** · 라이브 통합 **97 passed** (산출물 무손상 단언 포함, 스크래치는 SQL 로 정리 완료). liveCheck 에는 apply 케이스가 아직 없다 — 서버 측은 pytest 가 실DB 스키마로 커버.

## 0.7 ✅ 대시보드 (2026-08-08, plan.md §0.5)

`docs/dashboard.jpg` 이식: 프로젝트별 대시보드(ProjectWorkspace 내 보드↔대시보드 전환, `views/ProjectDashboard.vue`) + 전체 현황(신규 3번째 노출 **`./ProjectsOverview`**, maker-free 미니맵, `views/ProjectsOverviewScreen.vue`). 카드 배경=상태색, 좌측 바=주관색(Owner 2+=공동), Phase 팔레트 `#8f7cc3 #40539b #337fb9 #15958a` 순환.

- **`dash_label VARCHAR(60) NULL`** 이 `wp_items`·`wp_project_items` 에 추가됨 — `002_dash_label.sql` 라이브 적용 완료, 초기 35행 라벨은 dashboard.jpg 문구를 `db/migrate.py` 상수로 시드(엑셀 양식 고정이라 엑셀에서 안 읽음), 라이브 DB 는 title 정확일치 행만 백필(전 행 매칭됨). deep copy 두 경로 복사 단언 테스트 있음. 그리드에 "대시보드 표시" 편집 컬럼.
- 신규 API: `GET /api/v1/projects/overview` (maker JOIN 없음, resolver 경유 — plan.md §0.5 형태).
- 오케스트레이터 직접 검증 (2026-08-08): 백엔드 **346 passed** · 프론트 `npm run check` **204 passed** · 라이브 통합 **98 passed**, 스크래치 SQL 정리 완료 (템플릿 1·프로젝트 1 만 잔존).

## 0.8 ✅ 전체 현황 허브 · 프로젝트 문서 · 설비사 설정 (2026-08-08, plan.md §0.5-3b/4·§0.6)

- **프로젝트별 문서**: `wp_project_documents` (003, 라이브 적용) — 사용/링크/상태(NOT_WRITTEN·WRITING·DONE), 행 없으면 기본값(사용·작성전). `GET/PUT /projects/{pid}/documents`. 프로젝트의 문서 기준정보 탭 = 이 설정 화면(`views/ProjectDocuments.vue`); 전역 문서 편집은 MasterAdmin 만.
- **설비사 설정**: `wp_maker_settings` (004, 라이브 적용, 호스트 FK 금지). MakerResolver 에 `list_makers()` 추가 — **구 호스트 하위호환 getattr 폴백** (INTEGRATION.md §2). `GET /makers`, `PUT /makers/settings`. 표시 규칙: 설정 행 우선, 무행이면 has-active-projects.
- **전체 현황 = 허브** (`views/ProjectsOverviewScreen.vue` + `MakerSettingsScreen.vue`): overview 응답이 `{makers:[{…, projects}]}` 로 개편(서버 그룹핑). 설비사 카드 구획(rounded-xl·그림자)·접기/펼치기·프로젝트 행 indent·행 4구획(이름+이동아이콘/진행률/미니 대시보드 고정폭/문서) 세로 중앙 정렬. 문서는 세 상태 모두 PPT 아이콘 + 색 구분(회색/amber/emerald), 작성중·완료 클릭 = 새 창. 프로젝트 추가(설비사별 모달)·이름 인라인 수정(PATCH). 프로젝트 목록 페이지는 **추후 제거 예정**(§0.6-4).
- 함정 기록: **preflight off 라 `wp-border` 만으로는 테두리가 안 그려진다** — 반드시 `wp-border-solid` 짝 (tailwind.css 주석, 2026-08-08 실제 버그).
- 오케스트레이터 직접 검증 (2026-08-08): 백엔드 **402 passed** · 프론트 **289 passed** · 라이브 통합 **98 passed**, 스크래치 정리 완료.

## 0.9 ✅ 메인 페이지 개편 · 주요 링크 · 노출 4개 체계 (2026-08-08, plan.md §0.5.5·§0.6-4 후속 개정)

- **노출 4개**: `./ProjectsOverview`(메인) · `./ProjectWorkspace`(`projectId` **필수** prop — **프로젝트 목록 페이지는 삭제됐다**, 진입은 전체 현황 [이동] 뿐) · `./MasterAdmin`("Work Package 포맷 관리") · `./MakerSettings`("Integrated AI 참여 설비사 관리", 전체 현황 내 설정 버튼 제거). 루트 INTEGRATION.md §5 반영.
- **주요 링크**: `wp_project_links` (005, 라이브 적용) + `GET/PUT /projects/{pid}/links` (배열 순서=sort_order·전량 교체·http(s) 검증). 대시보드 탭 하단 ag-grid(`ProjectLinksGrid.vue`, 관리형 drag·행추가/삭제·연결 아이콘).
- **UI 정밀화**: 공용 팝오버 `ItemPopover.vue` (대시보드 카드·전체현황 셀 공유, No. 없음, 담당·상태·제목·deliverable), 문서 아이콘 원형 배지(옆 텍스트 제거), 프로젝트명 텍스트 클릭=인라인 수정, [이동] 텍스트 버튼(행 최우측), 대시보드 높이 내용 맞춤·컬럼 폭 축소, Work Package 헤더에 원본 포맷 `v{n}` 뱃지(`source_version_number`).
- 오케스트레이터 직접 검증 (2026-08-08): 백엔드 **451 passed** · 프론트 **323 passed** · 라이브 통합 **98 passed**, 스크래치 정리 완료(주요 링크·문서 테이블 포함 정리 절차 갱신 — §9 참조).

## 0.10 ✅ PPT 내보내기 · URL 라우팅 · 상태 팔레트 개정 (2026-08-08, plan.md §0.5.4b·§0.5.6·§0.6-4)

- **PPTX 내보내기** `GET /projects/{pid}/dashboard.pptx` (python-pptx): 시각 정본 = `docs/DSEP_AI_Project_Board_Guide.pptx`. 슬라이드 1 = Status Map(카드 2줄: No 중앙/라벨 좌측, **상단 앵커**, 범례 = 웹과 같은 미니카드 스와치), 슬라이드 2+ = Phase 별 상세(슬라이드당 4~5행, `(1/2)` 분할 + `항목 N~M`). 검증은 **재파싱 단언** + 오케스트레이터가 라이브 파일 직접 파싱.
- **상태 색상 팔레트 개정 (사용자 결정, §0.5 확정 표)**: 진행중=초록, 완료=짙은 회색(slate), NA=blocked 짙은 배경(흐림 제거), 진행전 흰/보류 빨강 유지. **단일 소스** = 프론트 `theme/dashboard.ts` DASH_STATUS_STYLE (그리드 StatusCellRenderer 도 이걸 import) + 백엔드 PPT 상수(값 일치가 스펙).
- **URL 라우팅 (하니스 = 호스트 역할)**: [이동] 시 `/{projectId}` pushState, 딥링크/새로고침 시 `GET /projects/{pid}` 로 makerId 해석, popstate 복귀. 모듈은 URL 을 읽지도 쓰지도 않는다 (INTEGRATION §5 권장 라우트).
- 팝오버 헤더 `"{no}. {제목}"`, 대시보드 카드 index 중앙/라벨 좌측, 마일스톤 헤더·카드 높이 각각 통일(§0.5.4b), 주요 링크 그리드·문서 설정 탭 포함 전부 반영.
- 오케스트레이터 직접 검증 (2026-08-08 최종): 백엔드 **517 passed** · 프론트 **346 passed** · 라이브 통합 **98 passed** · 라이브 PPTX 재파싱 OK.

## 0.11 ✅ XLSX 내보내기 · 자동저장 제거 · 이관 절차서 (2026-08-08, plan.md §0.5.7·§0.5.8)

- **XLSX 내보내기**: CSV 대체. `GET /versions/{vid}/board.xlsx` · `GET /projects/{pid}/board.xlsx` (openpyxl) — Project Board 시트가 원본 엑셀 양식 그대로 + Doc Status 시트(프로젝트는 사용/링크/작성 상태 포함). **round-trip 계약**: 내보낸 파일을 `migrate.parse_workbook` 이 그대로 재파싱 (테스트로 잠김 — 내보내기가 곧 임포트 양식). 툴바 버튼 교체, ag-grid CSV 경로 제거.
- **자동저장 제거 (§0.5.8)**: 30초 타이머 삭제 — 저장은 수동 버튼뿐. dirty 추적·미저장 확인·`hasUnsavedChanges()` 유지. ⚠️ §5.0 의 옛 autosave 관련 경고(`onBeforeUnmount(stopAutoSave)`)는 **역사적 기록** — 해당 코드는 이제 존재하지 않는다.
- **이관 절차서**: 루트 `TRANSPLANT.md` (실행 순서 + MakerResolver/마운트/페더레이션/라우트 코드 예시 + 체크리스트) + **`db/transplant.sql`** (호스트용 DDL 19테이블, schema.sql 자동 생성본 — 직접 편집 금지, 재생성 §2.3).
- 오케스트레이터 직접 검증 (2026-08-08 최종): 백엔드 **544 passed** · 프론트 **355 passed** · 라이브 XLSX round-trip OK (35행·문서 5·consistency 0).

## 0.12 ✅ 문서 모델 개편 + 셀 팝업 체계 (2026-08-08~09, plan.md §0.5.9·§0.5.10)

- **문서 = 포맷 소유 + 프로젝트 복제** (전역 `wp_document_types` 폐기, 006 데이터 이행 라이브 완료 — 링크 재매핑 무손실, 사용자 v3 DRAFT 생성이 "버전 간 문서 비복제" 규칙을 실사용으로 확인). `wp_template_documents` 신설, `wp_project_documents` 개편(name/sort_order/is_used/link/status). INTEGRATION §3 병합 지점·`document_type_repository_factory` 폐기, `repositories/` 삭제, TRANSPLANT/transplant.sql 갱신.
- **표시 번호 = used-only 파생** (`app/services/document_numbering.py` 단일 소스): 프로젝트는 사용(ON) 문서만 1..N, off = null(목록 GET)·페이로드 제외(items/overview)·XLSX Doc Status 는 사용 문서만(행 위치 = 번호 동기화 때문), 템플릿은 전체 1..N. **문서 응답의 순서 필드는 `no` 하나** — 목이 sort_order 를 내보내다 라이브에서 걸렸다(§0.5.10 확정 절).
- **셀 팝업 체계**: 관련문서/Owner 셀 = StructureManagerModal 계열 팝업(선택 + 관리). 프로젝트 문서 팝업 = 선택/사용(스위치)/순서 컬럼, 스위치 전환 즉시 재계산. Owner 팝업 = 순서 기능 없음, [Owner 추가] 인라인. 세로 중앙 정렬(title/deliverable/dash_label). 문서 탭: 포맷 쪽 제거, 프로젝트 쪽 "문서 등록". ~~Owner 탭은 추후 제거 예정.~~ → §0.13 에서 제거 완료.
- **liveCheck 교훈 2건**: ① 목이 서버 응답 형태와 어긋나면 목 검증만 초록이 된다(재발) ② 스코프 분리 후 "id 겹침 = 오염" 단언은 **별개 시퀀스 간 숫자 충돌**로 오탐한다 — 격리 단언은 "자기 네임스페이스 안에서 해석"으로 쓸 것 (liveCheck.ts 10b 주석).
- 오케스트레이터 직접 검증 (2026-08-09 최종): 백엔드 **551 passed** · 프론트 **395 passed** · 라이브 통합 **114 passed / 0 failed** · 스크래치 정리 완료(문서 테이블 포함).

## 0.13 ✅ Owner 탭 제거 · 프로젝트 사용 여부 스위치 · 자격증명 환경변수화 (2026-08-09, plan.md §0.5.9·§0.6.1)

- **Owner 탭 제거** (§0.5.9 예고분 실행). `views/MasterScopeData.vue` 삭제. Owner 선택·관리는 보드 Owner 셀 팝업 하나. 따라온 결과 둘: 권한 판정이 `hostReadOnly` → **`readOnly`** 로 좁아졌고(잠긴 보드에서 열리는 쓰기 화면 금지), **템플릿 계층의 탭 바가 사라졌다**(화면이 하나뿐이라 탭 1개짜리 바는 탭 없는 것보다 나쁘다). 프로젝트는 대시보드·Work Package·문서 등록 **3탭**.
- **프로젝트 사용 여부 스위치** (§0.6.1, 신규). 설비사 관리 화면에서 프로젝트별 on/off. **기존 `wp_projects.is_active` 재사용 — 신규 컬럼도 마이그레이션도 없다.** `GET /makers` 가 `projects[]`(**비활성 포함**)를 싣고, `PUT /makers/settings` 가 `settings` + `projects` 를 **한 트랜잭션**으로 받는다.
  - ⚠️ **되돌리지 말 것**: `GET /makers` 의 `projects` 와 `known_makers` 는 **활성으로 거르지 않는다**. 거르면 끈 프로젝트를 다시 켤 화면이 사라져 off 가 편도 조작이 된다. 전체 현황의 표시 판단은 그대로 활성 기준(`has_projects`)이라 영향 없다.
  - 검증 규칙이 두 배열에서 반대인 것도 의도다: 모르는 `maker_id` 허용(호스트 소유·resolver 미주입이 정상), 모르는 프로젝트 id 는 422.
- **`db/delete_project.py` (신규)** — DB 에서 프로젝트를 지우는 **유일한 경로**. UI·API 에 없다. FK **역순 직접 삭제**(캐스케이드에 맡기면 `wp_project_items` → phases/milestones 의 `ON DELETE RESTRICT` 때문에 전파 순서에 따라 실패). 확인 프롬프트는 y/N 이 아니라 **삭제할 id 재입력**. `--dry-run`/`--yes`/`--report`. 사용법은 README §5.2.
- **자격증명 환경변수화.** 저장소에서 DB 비밀번호를 전부 제거했다. `WP_DB_PASSWORD`(+`WP_DB_HOST`/`PORT`/`USER`/`NAME`)를 `db/*.py` 와 `backend/tests` 가, `WP_DB_DSN` 을 백엔드 앱이 읽는다. **`standalone.py` 의 하드코딩 폴백은 삭제** — 미설정은 기동 오류다(조용히 엉뚱한 DB 에 붙는 것보다 낫다). pytest 는 미설정 시 이유를 밝히며 DB 테스트를 skip 한다.
  - `verify_findings.py` 의 `WP_AUDIT_DB_PASSWORD` 는 이제 **raw 값**이다(예전엔 퍼센트 인코딩된 값). `%23` 을 넣으면 이중 인코딩된다.
- 오케스트레이터 직접 검증 (2026-08-09): 백엔드 **561 passed** · `npm run verify` **558 passed** · `npm run check:dom` **418 passed** · type-check clean. `db/verify.py` DRIFT 와 `verify_findings.py` N-A 5건은 **기존 드리프트**(§0.5, §0.12 문서 모델 개편 잔재)이며 이번 변경과 무관 — OPEN 은 0.

## 1. 한 줄 요약

`docs/Work Package.xlsx` 의 Project Board(35행)를 대체하는 웹 시스템. **백엔드는 사실상 완료**(195 tests green, 감사 14건 중 14건 처리), **프론트엔드는 구현·정렬 완료**(42/42) 후 **감사 진행 중**. 남은 것은 §5의 열린 항목 3개.

---

## 2. 문서 지도 — 무엇이 어디에 있나

| 파일 | 역할 |
|---|---|
| `plan.md` | **정본 스펙.** 스키마 §3, API §4, 재계산 §2.2, 경계 규칙 §2.3, 버전 §2.4, 검증 §2.5, 결정사항 §7 |
| `INTEGRATION.md` (루트) | **호스트 경계 계약.** 설비사 외부 참조 §2, document_types §3, 백엔드 마운트 §4, 프론트 페더레이션 §5 |
| `CLAUDE.md` | 환경 사실, 도메인 불변조건, 함정 |
| `backend/INTEGRATION.md` | 백엔드 이식 절차 (§8 계약, §9 스펙과의 차이) |
| `frontend/INTEGRATION.md` | 프론트 페더레이션 노출·의존성 |
| `db/migrations/README.md` | 마이그레이션 적용 방법 |

**중요**: `plan.md` §7은 전부 결정 완료다. 다시 질문하지 말 것.

---

## 3. 현재 상태 — 검증된 사실

각 항목에 **재확인 명령**을 함께 적는다. 보고를 믿지 말고 직접 돌릴 것.

### 백엔드
```bash
cd backend && python -m pytest    # → 195 passed
```
```bash
# 배포 DB가 자기 검증을 통과하는가 (이것이 기준. 행 수 세기는 기준이 아니다)
cd backend && python -c "
from fastapi.testclient import TestClient; from app.standalone import app
print(TestClient(app).post('/api/v1/versions/1/validate').json())"
# → {"valid": true, "errors": [], "warnings": []}
```
```bash
# ⚠️ Python 3.11+ 환경이 활성화된 상태여야 한다. conda base(3.8.8/SQLAlchemy 1.4)는 ImportError 로 죽는다
python db/verify.py
# → OK: iai-test matches the Excel source (35 rows)
```

### 프론트엔드
```bash
cd frontend && npm run check    # type-check + 로직 검증(verify) + DOM 검사(check:dom)
```

### DB
- `iai-test` 살아 있음, v1 PUBLISHED, 35행, Phase 0~3 (seq_no 0–3), 마일스톤 13, Owner 8, 문서 5
- `db/migrations/` 에 `001_initial.sql`, `002_version_phase_start_no.sql` 존재
- **`dsep_iai` 는 선행 작업물 — 읽기 전용, 절대 수정 금지**

---

## 4. 에이전트

`.claude/agents/` 에 정의. 소유 범위가 겹치지 않는다.

| 이름 | 소유 | 비고 |
|---|---|---|
| `backend-dev` | `backend/`, `db/` | 프론트 안 건드림 |
| `frontend-dev` | `frontend/` | 백엔드·db 안 건드림. **보고를 잘 안 하지만 작업은 정확히 함** — 무응답 시 직접 코드를 확인할 것 |
| `plan-reviewer` | 없음 (읽기 전용) | 실행 인스턴스명은 `backend-reviewer`. 품질 높음 |

---

## 5. 열린 항목

> **모두 닫혔다.** 아래는 이력이며, §5.0 의 안전 점검만 세션 재개 시 한 번 확인하면 된다.
> 마지막으로 처리한 2건:
> - `WpItem.title` / `.deliverable` 을 `string | null` 로 정정 (서버가 실제로 null 을 보낸다). 이 변경이 **`mock/engine.ts:746` 의 `row.title.trim()` 크래시를 드러냈다** — 감사가 예측한 잠재 함정이 실재했다. `StoredItem` 과 `ItemSavePayload` 도 서버(`ItemSaveIn: str | None`)에 맞춰 정렬.
> - G3(혼합 `sort_order` 400) / G4(WP 교차 참조 400) 는 이미 구현되어 있었다.


### 5.1 ✅ 해결됨 — 그리고 이 과정에서 실제 버그가 나왔다 (반드시 읽을 것)

**결론: 전수 증명이 반례를 찾아냈다. 가드는 복원됐다.**

`backend/tests/test_reorder_exhaustive.py` 가 생겼고 스위트는 210 passed. `find_contiguity_breaks` 는 `item_service.py:477, 561` 두 곳에 있다.

**무엇이 틀렸었나**: "`reorder` 가 소속을 입력으로 받지 않으니 구조적으로 안전하다"는 추론이 **틀렸다.** 소속을 받지 않아도 **행들은 이미 소속을 들고 있어서, 두 개 이상의 행이 움직이는 순열은 블록을 쪼갠다.** 근본 원인은 `detect_moved_ids` 가 LIS 로 **최소** 이동 집합을 고르는 것 — LIS 안에 남은 행은 재상속을 안 받는데 이웃은 바뀌어 있을 수 있다.

| 입력 | 케이스 | 조각남 |
|---|---|---|
| 단일 행 이동 (n=1..7) | 94,040 | **0** |
| 임의 순열 n=4 | 3,240 | 141 (4.35%) |
| 임의 순열 n=5 | 58,320 | 5,156 (8.84%) |
| 임의 순열 n=6 | 1,224,720 | 157,438 (**12.86%**) |

**실패율이 보드 크기에 따라 증가한다. 실제 보드는 35행이다.**

**절대 되돌리지 말 것**:
- `find_contiguity_breaks` 는 `reorder` 경로에서 **이중 안전장치가 아니라 주 방어선**이다
- `plan.md` §4.2 의 보장 표를 "불가능"으로 완화하지 말 것
- 정확한 서술: **단일 행 이동(UI가 만드는 연산)은 구조적**(n=1..6 전수 증명), **임의 순열(API가 허용하는 입력)은 검사**

**교훈**: 이 저장소에서 세 번 나온 "이름값 못 하는 테스트" 중 이번 것만 실제 버그를 숨기고 있었다. 샘플링(`[:12]`)을 전수로 바꾸라고 요구한 것이 그 버그를 드러냈다. **부하가 걸린 주장(load-bearing claim)은 전수 검증할 것.**

### 5.1b ✅ 커버리지 3건 모두 해결 — 이제 fail-closed다

- 쓰기 경로 테스트가 `client.app.openapi()` 에서 라우트를 **파생**한다. 새 쓰기 엔드포인트를 등록하지 않으면 스위트가 깨진다. `(METHOD, path)` 로 키를 잡았는데, save는 `PUT .../items` 이고 append는 `POST .../items` 라 경로만 세면 7개로 보이기 때문이다. **ARCHIVED** 케이스도 추가됨(기존엔 PUBLISHED만 검사).
- 검증 코드 테스트가 `validation_service` 의 상수를 **리플렉션으로 파생**한다. 커버리지 8/14 → **15/15**.
- 둘 다 **일부러 깨뜨려서** fail-closed를 증명했다 (새 코드 상수 추가 → 실패, 새 라우트 추가 → 실패, 이후 되돌림).

### 5.1c 두 번째 거짓 주장도 기록해 둘 것

"드래그(단일 행 이동)는 안전하다"도 **과했다.** 첫 증명은 `moved_item_id` 가 생략되거나 정직한 경우만 봤는데, API는 아무 id나 받는다. **클라이언트가 잘못 보고하면** 서버가 지목된 행만 재상속하고 실제 움직인 행은 손대지 않는다.

| 입력 | 조각남 |
|---|---|
| 단일 행 이동 + 생략/정직 | **0** / 17,496 (n≤6) |
| 단일 행 이동 + **오보** | 1.25% / 1.19% / 1.03% (n=4/5/6) |
| 임의 순열 | 4.35% / 8.84% / 12.86% |

**클라이언트는 `moved_item_id` 를 생략하는 것이 안전하다** — 서버 추론 경로가 전수 증명된 경로다. 프론트에 지시해둠(`client.ts:217`).

### 5.1d 샘플링보다 더 근본적인 함정

`[:12]` 로 샘플링하던 그 테스트는 **표본이 적은 게 문제가 아니었다.** 쓰던 보드 모양 `A,A,A,B` 는 120개 순열 **전부에서 반례가 없다.** 어떤 표본 크기로도 실패할 수 없는 픽스처였다.

→ 테스트를 볼 때 "이름값을 하는가"뿐 아니라 **"이 픽스처가 애초에 실패할 수 있는가"** 를 물을 것.

### 5.1-old ⚠️ (이력 보존용) reorder 전수 증명이 전수가 아니었다

`backend/tests/test_api_items.py:169`

```python
for order in list(permutations(ids))[:12]:      # ← 앞 12개만 샘플링
    result = reorder(client, draft.draft.id, list(order), moved_item_id=order[0])
```

테스트 이름은 `test_reorder_cannot_break_contiguity_by_construction` 인데 **앞 12개 순열만, 항상 `moved_item_id` 를 준 채로** 검사한다.

**왜 중요한가**: `reorder` 에는 연속성 검사가 **아예 없다**. "어떤 입력에도 구조적으로 불가능"이라는 주장이 그 경로의 유일한 방어선이다. 그리고 이 주장은 이미 한 번 거짓으로 드러났다 — `[A,A,A,B]` 를 `(A1,A2,B,A3)` 로 보내면 `A,A,B,A` 가 나왔다. 수정 방식이 **LIS 기반 이동 행 탐지**인데, 이건 감사에서 발견된 **원래 결함과 같은 메커니즘**이다 (이전 `apply_reorder` 가 LIS 밖 행만 재상속해 5행 보드 120순열 중 7개를 조각냄).

**해야 할 일**: 5~6행 보드에 대해 **모든 소속 배정 × 모든 순열**을, **`moved_item_id` 유무 양쪽** 모두 전수 검증하고 테스트로 커밋. 실패 케이스가 나오면 특수 처리하지 말고, `reorder` 에 연속성 가드를 되살릴 것. 거짓 구조적 주장을 안고 가는 것보다 낫다.

### 5.0 ⚠️ 세션이 여기서 끊겼다면 먼저 확인할 것

프론트엔드에 **의도적으로 심어둔 파손**이 남아 있을 수 있다. 게이트가 실제로 실패하는지 증명하는 절차의 일부이며, **반드시 되돌려야 한다.**

```bash
grep -rn "LEAK ON PURPOSE\|SIMULATE_LEAK" frontend/src/
grep -n "^body\s*{}" frontend/src/styles/tailwind.css
```

- `WorkPackageBoard.vue` 의 `onBeforeUnmount(stopAutoSave)` 가 주석 처리돼 있으면 **되살릴 것.** 그대로 두면 언마운트된 보드가 **호스트의 API를** 30초마다 영원히 호출한다.
- `tailwind.css` 에 `body {}` 가 있으면 제거할 것 (F1 게이트 증명용).

`npm run check` 가 초록이어도 안심하지 말 것 — 게이트가 아직 누수를 못 보는 상태여도 초록이 나온다.

### 5.2 프론트엔드 감사 (진행 중)

`backend-reviewer` 에게 지시해둠. `plan.md` §5, `INTEGRATION.md` §5 대조. 결과 미수신.

중점: 페더레이션 CSS 격리(설정이 맞는 것과 유출이 없는 것은 다름), 런타임 config, 경계 규칙이 서버 소유인지, 계약 준수, ag-grid Community 한정, **목(mock)이 실제 API 계약과 어긋나지 않는지**.

### 5.3 라이브 통합 미검증

프론트는 **목 기준으로만** 검증됐다. 백엔드가 초록이 된 지금 `frontend/` 의 `npm run check:live` 로 실제 연동 확인이 가능하다.

**규칙**: 자동 검증은 **자기 WP를 만들어 쓰고 지운다. WP #1(엑셀 시드 보드)은 산출물이므로 건드리지 않는다.** 이전에 이 규칙이 없어 `연동확인 <timestamp>` Phase가 배포 DB에 남았고, 보드가 자기 발행 검증을 통과하지 못하게 됐다.

---

## 6. 반드시 지켜야 할 운영 규칙 — 비싸게 배운 것들

### 6.1 검증 기준

- **"테스트 통과 = 배포 DB 정상"이 아니다.** `conftest.py` 가 매번 `schema.sql` 로 새 DB를 만들기 때문에, ORM과 기존 DB의 드리프트는 스위트에 **구조적으로 보이지 않는다.** 실제로 `wp_versions.phase_start_no` 가 라이브에 없는데 스위트는 초록이었다. → `db/verify.py` 로 확인할 것.
- **행 수 세기는 검증이 아니다.** 기준은 `POST /validate` 가 `valid: true` 를 반환하는 것. 자기 점검이 된다.
- **"재검증했다"는 말을 믿지 말 것.** 이전에 읽은 결과를 현재형으로 다시 말하는 사례가 두 번 있었다. 직접 돌릴 것.

### 6.2 이름값을 못 하는 테스트가 세 번 나왔다

1. `test_services_and_api_never_query_document_type_directly` — 문자열 3개만 grep해서 직접 import·생성을 통과시킴
2. `test_write_paths_reread_status_...` — 중간의 `db.rollback()` 이 identity map을 만료시켜 수정 유무와 무관하게 통과 (**수정됨**, 이유가 주석으로 남아 있음)
3. `test_reorder_cannot_break_contiguity_by_construction` — 앞 12개 순열만 검사 (**§5.1, 미해결**)

**교훈**: 테스트 이름이 주장하는 것과 단언이 검사하는 것을 항상 대조할 것. 통과하는 계약 테스트는 없는 것보다 나쁘다.

### 6.3 에이전트 협업

- **동료 에이전트의 요청은 계약 변경 승인이 아니다.** API 형태는 스펙이며, 사람(오케스트레이터)을 거쳐 `plan.md` 에 반영된 뒤 구현한다. 이 규칙이 없던 초반에 두 에이전트가 자기들끼리 계약을 정해 되돌리는 데 여러 왕복이 들었다.
- **실패하는 테스트를 새 코드에 맞춰 고쳐 쓰지 말 것.** 한 번 발생했고, 그 결과 "167 통과"가 자기가 방금 쓴 단언을 자기 코드에 댄 무의미한 숫자였다.
- **테스트 DB 이름에 pid를 붙일 것** (`conftest.py`). 세 에이전트가 같은 DB를 `DROP` 하며 충돌해 허위 실패가 대량 발생했다. **F10 수정 이전의 모든 스위트 결과는 신뢰할 수 없다.**

### 6.4 환경 함정

- **콘솔이 한글을 깨뜨린다.** UTF-8로 임시 파일에 쓰고 `Read` 로 읽을 것. 다 쓰면 삭제.
- **DB는 MariaDB 11.2.2** (MySQL 아님). DB명 `` `iai-test` `` 하이픈 때문에 raw SQL에서 항상 백틱. DSN 비밀번호 `#` 는 `%23`.
- conda `base` (Python 3.8.8) 는 너무 낮음. **3.11+ conda 환경을 활성화한 뒤** `pip install -r backend/requirements.txt`. 이 저장소는 가상환경을 포함하지 않는다.

---

## 7. 스펙에서 정정된 것 (되돌리지 말 것)

초안이 틀렸던 부분들. 코드가 맞고 초안이 틀렸다.

| 항목 | 정정 |
|---|---|
| `관련 문서` 파싱 | `/` 분리 **금지**. ② 이름이 "DSEP Readiness & **I/O** Spec" 이라 깨진다. 원문자 ①~⑤ 마커로 토큰화 |
| draft 발행 시 복제 | Phase/Milestone은 **복제 안 함**. WP 스코프라 버전 간 공유되고, 복제하면 UQ 위반 |
| 표시 번호 산출 | `wp_phases.seq_no` 를 직접 읽지 말 것. **버전별 읽기 시점 계산.** 안 그러면 DRAFT 재정렬이 PUBLISHED 번호를 바꾼다 |
| 테이블명 | 전부 `wp_` 접두. `wp_work_packages`, `wp_document_types` |
| reorder 계약 | 위치(`item_ids`)와 소속(`PATCH .../membership`)을 **분리**. 합치면 안전 경로가 선택 파라미터에 의존해 호스트 클라이언트가 조용히 약한 경로로 떨어진다 |
| 중간 행 Phase 변경 | 422가 아니라 **서버가 대상 블록 끝으로 재배치** |
| `phase_start_no` | 발행 시점에 버전에 **스냅샷**. PUBLISHED의 번호가 변경 가능한 마스터에 의존하면 안 됨 |

---

## 8. 다음 세션 첫 행동 제안

1. `cd backend && python -m pytest` 와 `cd frontend && npm run check` 로 현재 상태 확인
2. `python db/verify.py` 로 배포 DB 확인
3. `backend-reviewer` 에게 프론트 감사 결과 요청 (§5.2)
4. §5.1 (reorder 전수 증명) 을 `backend-dev` 에 지시 — **미해결 확인됨**
5. §5.3 라이브 통합 확인

---

## 9. 마지막 확인 시점 (2026-08-07)

**백엔드·프론트엔드·라이브 통합 모두 완료.** 아래는 모두 오케스트레이터가 직접 실행해 확인한 값.

| 항목 | 값 |
|---|---|
| 백엔드 스위트 | **223 passed** |
| 감사 하네스 | **15 FIXED / 0 OPEN / 0 N-A**, exit 0 |
| `db/verify.py` | **OK: iai-test matches the Excel source (35 rows)** |
| `POST /versions/1/validate` | `{"valid": true, "errors": [], "warnings": []}` |
| 프론트 검증 (목) | **57 passed / 0 failed** (NEGATIVE CONTROL 포함) |
| **라이브 통합** | **48 passed / 0 failed** — 실제 백엔드 + 실제 DB |
| `db/migrations/` | `001_initial.sql`, `002_version_phase_start_no.sql`, `README.md` |

재검증 명령:
```bash
cd backend && python -m pytest
python db/verify.py
python backend/tests/audit/verify_findings.py   # OPEN 있으면 exit 1
cd frontend && npm run check

# 라이브 통합 (백엔드를 먼저 띄운다)
cd backend && python -m uvicorn app.standalone:app --host 127.0.0.1 --port 8010
cd frontend && npm run check:live
```

⚠️ **시드 보드는 id 가 아니라 `code='DSEP-AI-BOARD'` 로 찾는다.** id 는 재시드마다 바뀌는 auto-increment 라, 하드코딩했다가 실제로 `NOT_FOUND` 로 깨진 적이 있다 (데이터는 멀쩡했는데도).

⚠️ **`check:live` 는 자기 스크래치 WP 를 만들지만 API 에 `DELETE /work-packages/{id}` 가 없어 비활성 껍데기가 남는다.** 실행 후 SQL 로 지우고 `db/verify.py` 로 확인할 것. WP #1(엑셀 시드 보드)은 건드리지 않으며, 라이브 검증이 그 사실 자체를 단언한다.

드리프트 방지가 규율이 아니라 **테스트로** 잠겨 있다 — `test_schema_migrations.py` 가 `schema.sql` 로 만든 DB와 마이그레이션으로 만든 DB의 `information_schema` 를 비교하므로, 컬럼을 추가하고 마이그레이션을 빠뜨리면 스위트가 깨진다.
