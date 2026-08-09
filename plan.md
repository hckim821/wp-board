# Work Package 웹 관리 시스템 — 요구사항 및 개발 계획

> `docs/Work Package.xlsx` 의 **Project Board** / **Doc Status** 시트를 웹으로 대체하기 위한 설계 문서.
> 작성일: 2026-08-07

---

## 0. 아키텍처 개정 (2026-08-07) — 기준 데이터 / 프로젝트 2계층

> **이 절은 사용자의 시나리오 정정을 반영한 최상위 구조이며, 아래 절들과 충돌하면 이 절이 우선한다.**
> 기존 서술은 "설비사 1:N WP, 단일 계층"을 전제했는데 그것이 틀렸다.

### 0.1 두 계층

```
[기준 데이터 — 중앙 관리, 별도 메뉴]
  wp_document_types (전역 문서 기준정보)
  wp_templates ──▶ 버전 (DRAFT→PUBLISHED→ARCHIVED) ──▶ 항목
     ├ phases / milestones / owners  (템플릿 스코프 set)
     └ §2.4 의 draft 발행→임시저장→발행 은 **여기(템플릿)에만** 적용된다
              │
              │  프로젝트 생성 시 발행본에서 전부 deep copy (스냅샷)
              ▼
[프로젝트 — 설비사별]
  wp_projects (maker_id) ──▶ 항목 + 프로젝트 로컬 phases/milestones/owners
     · 버전 없음. draft/발행/폐기/이력 없음. 항상 직접 편집·저장
     · 추가/수정은 프로젝트에만 반영 — 중앙 기준 데이터에 영향 없음
     · Status/완료일 등 실행 필드의 실제 무대
```

| | 템플릿 (기준 데이터) | 프로젝트 |
|---|---|---|
| 소유 | 중앙 (설비사 무관) | 설비사 (`maker_id`) |
| 버전 관리 | O — §2.4 그대로 | **X** — 생성이 곧 확정, 이후 자유 편집 |
| 발행 검증 V1–V14 | 발행 시 강제 | 발행이 없으므로 **차단 검증 없음** (참조 무결성만) |
| 기준정보(phase/ms/owner) | 템플릿 set | 생성 시 복제된 로컬 사본 |
| 문서 기준정보 | 전역 공유 (복제 안 함) | 전역 공유 |

- 프로젝트 생성 = **발행된 템플릿 버전 하나를 선택**해 항목·phase·milestone·owner 를 통째로 복제. 이후 템플릿이 재발행되어도 **기존 프로젝트는 불변** (스냅샷, 전파 없음).
- `phase_start_no` 도 생성 시점 값을 프로젝트에 스냅샷.
- 그리드 동작(재계산 §2.2, 경계 §2.3, 블록 내 드래그, 회색 행 추가 §0.2)은 **양쪽 공통**.
- 설비사 외부 참조 규칙(`INTEGRATION.md` §2)의 적용 대상은 이제 `wp_projects.maker_id` 다. 템플릿에는 maker 개념이 없다.

### 0.2 행 추가 개정 — 미배정(회색) 행

기존 "insert-below 는 위 행의 phase/milestone 상속" 규칙을 폐기한다. **두 추가 방식(툴바 append, 행별 `+`) 모두 phase/milestone 이 null 인 회색 행을 만든다.**

왜: 상속 방식에서는 새 행이 항상 기존 블록 **안에** 갇힌다. 드래그도 블록 내로 제한된 지금, **기존 Phase/Milestone 사이에 새 항목·새 Phase 를 넣을 방법이 아예 없었다.** 회색 행이 그 자유도를 연다:

1. **회색 행은 어디에 있어도 연속성을 깨지 않는다** — 연속성 검사에서 null 행은 **투명(transparent)** 하다 (`P0 P0 [회색] P0` 은 위반이 아니다).
2. **회색 행은 어디로든 드래그 가능** (블록 제한의 예외 — 자기 블록이 없으므로).
3. 회색 행의 Phase 셀 에디터: **인접 Phase 를 상단에 강조** (한 번 클릭으로 "위/아래와 같게"), 전체 목록, 그리고 `+ 새 Phase 생성`.
4. **새 Phase 생성 가능 조건(회색 행)**: 위·아래 이웃의 phase 가 서로 다르거나 리스트 양끝일 때만. 같은 블록 한가운데면 그 블록이 쪼개지므로 비활성 + 사유 툴팁. (§2.3 의 "미배정 행은 항상 경계" 를 이렇게 정정한다 — 경계인 것은 맞지만 생성 허용은 **결과가 연속일 때만**.)
5. 두 블록 사이 회색 행에서 새 Phase 를 만들면 first-appearance 재계산이 **자연히 그 사이 번호를 부여**한다. 이것이 "사이에 추가"의 메커니즘 전부다 — 특별한 삽입 로직이 필요 없다.
6. Milestone 도 동일: phase 배정 후, 그 phase 블록 내부에서 같은 규칙.
7. 회색 행은 저장(무검증)에 아무 문제 없고, **템플릿 발행 시에만** V1/V2 가 잡는다. 프로젝트에는 발행이 없으므로 회색인 채로 있어도 된다.

### 0.3 소속 셀 규칙 (2026-08-08 추가 — 사용자 결정)

**배정된 행의 Phase/Milestone 셀은 잠근다.** 드래그가 블록 안으로 제한된 세계에서, 배정된 행의 소속을 셀로 바꾸는 것은 남은 유일한 "행이 멋대로 움직이는" 경로였고 사용자가 차단을 요청했다.

| 행 상태 | Phase 셀 | Milestone 셀 |
|---|---|---|
| 미배정 (회색) | 에디터 열림 — §0.2 흐름 | phase 배정 전엔 비활성 |
| phase 만 배정 | **잠김** (아래 전환만 가능) | 에디터 열림 — 그 phase 의 마일스톤 + 조건부 신규 |
| 완전 배정 | **잠김** | **잠김** |

**재분류 경로는 하나다 — `미배정으로 전환`.** 배정된 행의 셀을 클릭하면 편집기 대신 "미배정으로 전환" 액션만 제공한다(확인 후 `PATCH membership {null, null}` — 행은 제자리에서 회색이 된다. null 은 연속성에 투명하므로 안전). 이후 일반 회색 행 흐름으로 재배정한다. 분류를 바꾸는 통로가 "회색 행" 하나로 통일된다.

**배정(선택) 시 재배치는 마일스톤 블록 끝 단위다.** 회색 행에 기존 phase/milestone 을 지정하면 행은 **그 마일스톤 블록의 맨 끝**으로 이동한다 (milestone 미지정이면 phase 블록 끝). phase 블록 끝이 아니다 — 예: 2.2 를 고르면 2.2 블록 끝·2.3 앞이지, 2.4 뒤가 아니다. 서버는 이미 이렇게 동작함을 재현으로 확인했다(2026-08-08). **목(mock)이 phase 단위로만 재배치하다 이 규칙을 어겨 사용자에게 번호 뒤섞임/오류로 나타났다** — 목은 서버와 동일 규칙을 구현해야 한다.

### 0.4 Phase/Milestone 관리 팝업 (2026-08-08 추가 — 사용자 결정. 충돌 시 §0.2-4·§2.3·§2.6 을 이 절이 덮어쓴다)

Phase/Milestone 의 생성·이름 변경·삭제·순서 변경을 **하나의 관리 팝업(모달)** 로 통일한다. 팝업은 표 형태다:

- **Phase 팝업**: 보드의 Phase 들이 행으로 나열된다 (Phase 0, 1, 2 …). 행을 드래그해 순서를 바꾸고, 행 추가로 새 Phase 를 만들고, 이름을 인라인 수정하고, 행 삭제로 Phase 를 지운다.
- **Milestone 팝업**: **해당 Phase 안의** Milestone 목록만 표에 뜬다. 동작은 동일.
- [적용] 시 전체 변경이 **한 번의 원자적 요청**으로 서버에 간다. [취소] 는 아무것도 반영하지 않는다.

**순서 = 번호다 (인덱싱 규칙).** 팝업 표의 위→아래 순서가 곧 보드의 블록 순서가 되고, first-appearance 재계산(§2.2)이 그 순서에서 번호를 파생한다. Phase 0 과 1 사이에 새 Phase 를 끌어다 놓으면 기존 Phase 1 은 2 가 되고, **그 하위 행·마일스톤 표시 번호가 전부 따라 바뀐다.** 번호를 직접 만지는 로직은 어디에도 두지 않는다 — 블록을 재배열하면 번호는 §2.2 가 알아서 매긴다. 서버가 재계산 권한자이며 응답으로 전체 행 목록 + 기준정보를 돌려준다.

**행 없는 Phase 는 존재할 수 없다** — 번호가 first-appearance 파생이라 행이 없으면 번호가 정의되지 않는다. 따라서:

- **앵커 행에서 생성** (회색 행의 셀 에디터 `+ 새 Phase 생성` → 팝업): 새 Phase 의 첫 행은 그 앵커 행이다. 팝업에서 정한 위치로 앵커 행이 함께 이동한다. 위치를 팝업에서 명시하므로 **§0.2-4 의 "이웃 phase 가 달라야 생성 가능" 제약은 폐기된다** — 어떤 회색 행에서든 생성할 수 있고, `can_create_phase` 플래그는 서버가 계속 계산하지만 UI 는 더 이상 보지 않는다.
- **팝업 자체에서 행 추가로 생성** (앵커 없음): 서버가 **빈 행(ADDED, 제목 없음) 1개를 그 Phase 에 배정해 함께 생성**한다. Milestone 도 동일 (해당 phase 배정·milestone null 인 빈 행).

**삭제는 캐스케이드다.** Phase 삭제 = 그 Phase 의 모든 행 + 하위 Milestone 전부 삭제. Milestone 삭제 = 그 Milestone 의 모든 행 삭제. 팝업은 삭제 확인 시 **"하위 항목 N개가 함께 삭제됩니다"** 경고를 반드시 띄운다 (개수는 로드된 보드에서 계산). §2.6 의 "사용 중 기준정보는 하드 삭제 금지·비활성화" 규칙에서 **보드 스코프 Phase/Milestone 은 제외된다** — 이 둘은 이제 보드 구조의 일부로서 팝업이 명시적 캐스케이드로 지운다. Owner·문서는 종전대로 비활성화 방식.

**배정된 셀 클릭 = 선택 팝업.** §0.3 의 "미배정으로 전환" 단일 액션을 **행 삭제와 같은 선택 팝업**으로 바꾼다: **[수정] / [재배치(미배정으로 전환)] / [취소]**. [수정] 은 위 관리 팝업을 연다 (Phase 셀이면 Phase 팝업, Milestone 셀이면 그 phase 의 Milestone 팝업). [재배치] 는 종전의 미배정 전환(`PATCH membership {null,null}`) 그대로다.

**API (템플릿 DRAFT / 프로젝트 양쪽 동일 형태):**

```
POST /api/v1/versions/{vid}/phases/apply
POST /api/v1/versions/{vid}/phases/{phase_id}/milestones/apply
POST /api/v1/projects/{pid}/phases/apply
POST /api/v1/projects/{pid}/phases/{phase_id}/milestones/apply
```

```jsonc
// phases/apply 요청 — 팝업 표의 최종 상태
{
  "phases": [                     // 위→아래 = 새 블록 순서. 기존+신규 전부 나열
    { "id": 5, "name": "Initiation & Readiness" },   // 기존 (이름 변경 반영)
    { "id": null, "name": "새 단계" },                // 신규
    { "id": 7, "name": "Evaluation" }
  ],
  "deleted_ids": [6],             // 명시적 삭제 목록
  "anchor_item_id": 123           // (선택) 신규 1개를 회색 앵커 행으로 만들 때
}
// milestones/apply 도 동일 형태 ("milestones": [...]). 대상 phase 는 URL 로 온다.
```

서버 검증 (422): 스코프 밖/교차 계층 id, 중복 id, `phases`+`deleted_ids` 가 기존 전체 집합과 일치하지 않음, `anchor_item_id` 가 회색 행이 아니거나 신규 항목이 정확히 1개가 아님, 빈 이름/중복 이름, PUBLISHED/ARCHIVED 버전(기존 관문 409). 에러 코드: `APPLY_SET_MISMATCH`(missing/unknown/expected 동봉) · `APPLY_DUPLICATE_ID` · `APPLY_OUT_OF_SCOPE` · `APPLY_EMPTY_NAME` · `APPLY_DUPLICATE_NAME` · `APPLY_ANCHOR_INVALID` · `APPLY_BOARD_NOT_CONTIGUOUS`. 응답은 `{items, phases, milestones}` — items 는 기존 ItemOut(번호·경계 플래그) 그대로, 기준정보 두 목록이 더해진다 (팝업이 신규 항목의 id 를 여기서 읽는다).

**구현 시 확정된 정밀화 (2026-08-08, 구현 검증 완료 — 되돌리지 말 것):**

1. **삭제의 실체는 조건부다.** 템플릿의 Phase/Milestone 은 버전이 아니라 템플릿에 매여 있어 PUBLISHED 가 같은 실체를 공유한다. 다른 버전이 쓰지 않으면 하드 삭제, 쓰고 있으면 비활성화(하위 Milestone 포함) — 어느 쪽이든 해당 보드에서는 사라지므로 사용자 관점 결과는 같고, 손대지 않은 발행본은 깨지지 않는다.
2. **milestones/apply 의 anchor 조건**: `milestone_id == null` 이고 phase 가 null 이거나 대상 phase 인 행. (§0.3 상 Milestone 셀 에디터가 열리는 유일한 상태가 "phase 만 배정된 행"이므로, phase null 만 허용하면 그 흐름이 죽는다.)
3. **집합 일치의 "기존 전체 집합"** = 기준정보 테이블 전체가 아니라 **보드에 행이 있는** Phase(first-appearance 순)들. ("행 없는 Phase 는 존재할 수 없다"와 일관.)
4. **삭제된 블록에 붙어 있던 회색 행은 삭제되지 않는다** — 그 Phase 소속이 아니므로. 현재 순서에서 가장 가까운 앞쪽 생존 블록에 다시 붙는다. 팝업의 "하위 N개 삭제" 경고 개수에도 회색 행은 포함하지 않는다.

**블록 재배열 시 회색 행 처리**: 미배정 행은 **직전 배정 행에 붙어 함께 이동**한다 (블록 내부·말미의 회색 행은 그 블록과 한 몸). 보드 최상단의 선행 회색 행들은 최상단에 남는다. Milestone 재배열에서 milestone null·phase 배정 행도 같은 규칙(직전 milestone 블록에 부착).

**기준정보 화면 정리**: Owner·Phase·Milestone 탭에서 **Phase/Milestone 메뉴는 제거**한다 (관리 팝업이 대체). Owner 와 전역 문서 관리는 그대로. 기존 anchor 방식 `create-phase`/`create-milestone` 엔드포인트와 Phase/Milestone CRUD API 는 계약 유지 차원에서 남겨 두되 UI 는 사용하지 않는다.

### 0.5 대시보드 (2026-08-08 추가 — 사용자 결정)

`docs/dashboard.jpg` 를 웹으로 옮긴다. 시각 문법은 그 이미지가 정본이다: 상단에 Phase 화살표 헤더(좌→우), 그 아래 Milestone 컬럼, 각 Milestone 아래 항목 카드 스택. **카드 배경 = 상태** — 팔레트는 2026-08-08 사용자 결정으로 다음과 같이 확정 (프론트 `theme/dashboard.ts` 와 백엔드 PPT 상수, 그리드 상태 칩 등 **상태색이 나오는 모든 곳**이 이 표를 따른다):

| 상태 | bg | border | text |
|---|---|---|---|
| 진행전 NOT_STARTED | `#ffffff` | `#94a3b8` | `#334155` |
| 진행중 IN_PROGRESS (초록 계열) | `#d1fae5` | `#34d399` | `#065f46` |
| 완료 DONE (살짝 짙은 회색) | `#cbd5e1` | `#94a3b8` | `#1e293b` |
| 보류 HOLD (경고 빨강 — 미지정이라 유지) | `#fee2e2` | `#fca5a5` | `#991b1b` |
| 해당없음 NA (blocked 느낌의 짙은 색) | `#334155` | `#1e293b` | `#cbd5e1` |

NA 는 종전의 60% 흐림 대신 **짙은 배경으로 차단된 느낌**을 준다 (opacity 제거). **카드 좌측 세로 바 = 주관** (사내 개발부서 `#337fb9`, DSEP 인프라 담당자 `#202d72`, 설비사 `#15958a`, Owner 2개 이상 = 공동 `#f4a72d`; 단일 Owner 는 이름 휴리스틱, 미지정 slate). Phase 헤더 팔레트 `#8f7cc3 #40539b #337fb9 #15958a` 순환. 선행 반복의 `D:\agents\dsep-iai\frontend\src\views\ItemDashboardView.vue` / `DashboardView.vue` 가 레이아웃 참고물이나, **이 저장소의 페더레이션 제약(라우터 금지·wp- prefix·런타임 config)에 맞춰 새로 작성한다.**

**1) `dash_label` 컬럼 (신규).** 대시보드 카드에는 제목 전문이 아니라 **key action 요약 단어**가 실린다. `wp_items` · `wp_project_items` 에 `dash_label VARCHAR(60) NULL` 추가 (마이그레이션 `002_dash_label.sql` + `schema.sql` 동기 — `test_schema_migrations.py` 가 강제). 그리드에 "대시보드 표시" 편집 컬럼 추가, 저장/응답(`ItemOut`)에 포함, **draft 생성·프로젝트 생성의 deep copy 경로 모두 복사**. 카드 표시 폴백: `dash_label` 없으면 `deliverable`, 그것도 없으면 title 앞부분. 초기 35행의 라벨은 dashboard.jpg 의 문구를 `db/migrate.py` 에 상수로 박아 시드한다 (엑셀 양식은 고정이라 엑셀에서 읽지 않는다).

**2) 프로젝트 대시보드 (프로젝트별).** 데이터는 기존 프로젝트 GET 응답만으로 렌더 (신규 API 없음). 읽기 전용. 상단에 상태별 집계 칩(전체/진행중/완료/보류), 하단에 상태·주관 범례. Phase 4개 초과·회색 행(미배정 카드는 맨 뒤 "미배정" 컬럼)도 렌더가 깨지지 않아야 한다.
**(2026-08-08 개정 — 사용자 결정)** 카드가 넓어 전체 가로 폭이 과했다: **카드에서 담당자 텍스트 줄을 제거**하고 컬럼 최소 폭을 줄여 전체 폭을 축소한다. 카드에는 No + 표시 텍스트(dash_label 폴백)만 남기고, **hover 팝오버**로 담당(주관) · 상태 · action item(제목) · deliverable 을 깔끔하게 보여준다. **팝오버 포맷은 전체 현황 미니맵 셀과 공유한다** (2026-08-08 — 하나의 컴포넌트, "No." 표기는 어디에도 넣지 않는다. 헤더는 action item 제목).

**2a-1) Work Package 헤더의 원본 포맷 표기 (2026-08-08 추가).** 프로젝트명 옆 포맷(템플릿) 표시에 **원본 버전 번호**를 덧붙인다 — `ProjectOut.source_version_number: int | null` (`source_version_id` → `wp_versions.version_number` 조회, dangling 이면 null 로 표기 생략, 조회는 깨지지 않는다). 표기 예: 포맷명 + `v2`.

**2b) 프로젝트 내부 네비게이션 (2026-08-08 개정 — 사용자 결정).** 보드↔대시보드 토글을 폐기하고, 프로젝트 선택 후 화면 상단 메뉴 4개로 구분한다: **대시보드 / Work Package / 문서 기준정보(전역) / Owner**. 대시보드가 기본 탭. Work Package = 기존 보드 그리드. 문서 기준정보 = 전역 문서 마스터 관리 화면 재사용 (전역 데이터라 MasterAdmin 쪽과 같은 것을 편집한다 — 중복 진입점은 의도). Owner = 프로젝트 스코프 Owner 관리. 탭 전환 시 활성 화면만 마운트(그리드 동시 2개 금지), Work Package 에 미저장 변경이 있으면 전환 전 확인. readOnly prop 은 네 탭 모두에 전파.

**3) 전체 현황 (설비사-프로젝트 별, 별도 페이지).** 새 페더레이션 노출 **`./ProjectsOverview`** (호스트 메뉴 3번째, maker-free — 전 설비사 관망). **(2026-08-08 개정)** 화면은 **설비사별 구획**이다: maker 섹션 헤더(이름, resolver 없으면 `설비사 #id`) 아래 그 설비사의 프로젝트들이 나열된다. 프로젝트마다 **미니 대시보드** — 프로젝트 대시보드의 축소판으로, `Phase N` 라벨이 붙은 색 밴드(팔레트 순환) 아래 항목 셀을 마일스톤 단위로 묶어 나열하되 **텍스트는 숨긴다**. 진행전 항목은 **테두리 있는 빈 박스**로 보여 존재가 드러나야 하고, 셀 hover 시 팝오버로 No·key action(`dash_label` 폴백 포함)·마일스톤·상태를 보여준다. 미배정 항목은 맨 뒤 무색 밴드. 프로젝트명 클릭 시 **주입된 콜백 prop** (`onOpenProject(projectId, makerId)`) 호출 — 라우팅은 호스트 소유. 신규 API:

```
GET /api/v1/projects/overview
→ { "projects": [ { "id", "name", "maker_id", "maker_name"|null,   // resolver 없으면 null (정상)
      "counts": {"NOT_STARTED":n,"IN_PROGRESS":n,"DONE":n,"HOLD":n,"NA":n},
      "items": [ {"no","status","phase_seq"|null,"milestone_seq"|null,"dash_label"|null,
                  "title"|null,"deliverable"|null,"owners":[이름…]}, … ]  // sort_order 순, phase_seq 는 표시번호 파생값
      // title/deliverable/owners 는 2026-08-08 추가 — 팝오버가 프로젝트 대시보드와 동일 포맷이어야 해서다
  } ] }
```

active 프로젝트만, maker JOIN 금지(id + resolver 경유 — INTEGRATION §2). 미니맵의 Phase 밴딩 색은 `phase_seq` 로 위 팔레트 순환, 미배정 셀은 무색 밴드.

**3b) 전체 현황 행 레이아웃 (2026-08-08 개정 — 사용자 결정).** 프로젝트 행을 컬럼처럼 5구획으로 나눈다: **① 프로젝트명** (텍스트 클릭 = 이름 수정 모드 — §0.6-4) **② 진행률·상태 집계 ③ 미니 대시보드 ④ 문서 링크 ⑤ 이동 버튼** — 가장 우측 컬럼, **아이콘이 아니라 텍스트 버튼**("이동")으로 잘 보이게 (클릭 = `onOpenProject`). 이름 옆 이동 아이콘은 두지 않는다 (2026-08-08 정정). ③ 은 **고정 너비** — Phase 5개 기준 최대 너비를 상수로 고정해 모든 행의 ④ 시작점이 정렬된다 (짧은 보드는 여백, 초과분은 ③ 내부 가로 스크롤). ④ 는 §0.5-4 의 프로젝트 문서 중 **사용 체크된 것**을 표시: **세 상태 모두 같은 PPT 문서 아이콘**(FilePptOutlined)으로 표시하고 **색으로만 구분**한다 (2026-08-08 정정 — "작성 전" 텍스트 표기는 폐기): 작성전 회색 `#94a3b8`·클릭 불가, 작성중 amber `#d97706`, 완료 emerald `#059669`. 작성중/완료는 클릭 시 `window.open`(새 창, noopener)으로 클라우드 링크 연결 — 링크가 없으면 클릭 불가 + "링크 없음" 툴팁. 아이콘 hover 툴팁에 문서명·상태 표기. **순서 표기는 아이콘 옆 텍스트가 아니라** (2026-08-08 정정 — 나란한 숫자 텍스트는 지저분하다) **아이콘 모서리의 작은 원형 배지**로 — 문서 코드가 원문자(①~⑤)이므로 배지 숫자와 자연스럽게 대응한다.

**4) 프로젝트별 문서 링크·상태 (2026-08-08 추가 — 사용자 결정).** 전역 `wp_document_types` 는 문서의 **정의**만 갖는다. 프로젝트마다 그 문서의 **사용 여부·클라우드 링크·작성 상태**를 따로 가진다:

- 신규 테이블 `wp_project_documents(id, project_id, document_type_id, is_used TINYINT(1) NOT NULL DEFAULT 1, link_url VARCHAR(500) NULL, doc_status ENUM('NOT_WRITTEN','WRITING','DONE') NOT NULL DEFAULT 'NOT_WRITTEN', UNIQUE(project_id, document_type_id))` — 마이그레이션 `003_project_documents.sql` + `schema.sql` 동기.
- **행이 없으면 기본값이다** (사용=1·작성전·링크 없음): `GET /api/v1/projects/{pid}/documents` 는 활성 전역 문서 전부를 LEFT JOIN 으로 돌려주고, 저장은 `PUT /api/v1/projects/{pid}/documents` `{documents:[{document_type_id, is_used, link_url, doc_status}]}` 업서트. 기존 프로젝트는 마이그레이션 불요(레이지). 알 수 없는/비활성 문서 id 는 422. `link_url` 은 상태와 무관하게 null 허용.
- 프로젝트의 **문서 기준정보 탭**(§0.5-2b)은 전역 문서 편집이 아니라 **이 프로젝트 설정 화면**이 된다: 컬럼 = 사용(체크) · 코드 · 이름(전역, 읽기 전용) · 클라우드 링크(URL 입력) · 상태(작성전/작성중/완료). 전역 문서 정의 편집은 MasterAdmin 에만 남는다.
- overview 응답의 각 프로젝트에 `documents` 배열 추가 (**is_used=1 만**): `{document_type_id, code, name, doc_status, link_url}`.

### 0.5.4b 대시보드 높이 통일 (2026-08-08 추가 — 사용자 결정)

프로젝트 대시보드에서 **마일스톤 헤더 셀은 전부 같은 높이**, **항목 카드도 전부 같은 높이**여야 한다 — 각각 보드에서 가장 긴 값(가장 많은 줄)을 기준으로 통일. 구현 방식은 자유(라인 클램프 기준 고정 높이 or 측정)이되, 결과적으로 어떤 컬럼에서도 헤더끼리·카드끼리 높이가 어긋나 보이면 안 된다. 잘린 내용은 hover 팝오버가 보완한다.

### 0.5.6 대시보드 PPT 내보내기 (2026-08-08 추가 · 같은 날 다중 슬라이드로 격상 — 사용자 결정)

**시각 정본은 `docs/DSEP_AI_Project_Board_Guide.pptx`** — 그 덱과 같은 수준으로 만든다. 생성은 **백엔드 python-pptx** (내보내기는 백엔드 생성 원칙).

- `GET /api/v1/projects/{pid}/dashboard.pptx` → pptx MIME, 파일명 = 프로젝트명 (비ASCII 는 RFC 5987 filename*).
- **슬라이드 1 — Status Map** (정본 덱 slide 1): 제목, Phase 화살표(chevron) 헤더 + Phase 색 밴드(§0.5 팔레트), 마일스톤 헤더(`{파생번호} | {이름}`), 항목 카드(상태 배경 + 주관 좌측 바 + `{No} | {dash_label 폴백}`), 하단 범례. 컬럼 수 기준 자동 축소(13 마일스톤 기준 케이스), 카드 높이 통일(§0.5.4b), 미배정 맨 뒤 무색 컬럼.
- **슬라이드 2+ — Phase 별 Work Package 상세** (정본 덱 slide 2~8): Phase 당 1장 이상, **슬라이드당 4~5행**, 넘치면 `(1/2)` 식 분할과 `— 항목 N~M` 범위 표기. 각 행 = **No** · **산출물(Deliverable, 굵게)** + `· {phase.ms} {밀스톤명} | {Key Action(title)}` · **문서**(원문자 코드들) · **Owner**. 행에 상태 색 표시(상태 배지 또는 No 셀 배경 — 정본 덱은 무상태 시절 산출물이라 이 부분만 확장이다). 헤더 밴드·푸터(프로젝트명 · 페이지) 포함.
- 색상 헥스는 §0.5 가 정본 — 백엔드 상수로 중복 정의 (프론트 `theme/dashboard.ts` 와 값 일치, 어긋나면 스펙 위반). 정본 덱의 지오메트리/색은 python-pptx 로 덱을 직접 파싱해 가져올 것.
- python-pptx 를 `requirements.txt` 에 추가. import 부작용 금지 원칙 유지.
- 프론트: 대시보드 탭 **[PPT 내보내기]** 버튼 — blob 다운로드(인증 헤더 경유), readOnly 허용(읽기 연산).

### 0.5.7 XLSX 내보내기 (2026-08-08 추가 — 사용자 결정. CSV 내보내기를 대체한다)

보드 내보내기는 CSV 가 아니라 **XLSX** 이며, 수준은 **`docs/Work Package.xlsx` 원본과 동급**이다. 생성은 백엔드 openpyxl (CLAUDE.md 내보내기 원칙).

- `GET /api/v1/versions/{vid}/board.xlsx` (템플릿) / `GET /api/v1/projects/{pid}/board.xlsx` (프로젝트) → xlsx MIME, 파일명 RFC 5987.
- **Project Board 시트 = 원본 양식 그대로** (양식 고정 원칙): 컬럼 No · Phase(`Phase {n}. {이름}`) · Milestone(`{n}.{m} {이름}`) · Key Action(title) · 산출물(deliverable) · 관련 문서(원문자 코드 ` / ` 연결) · Owner(`+` 연결) · Status(원본 표기: Not Started/In Progress/Done/Hold/N/A) · 완료일. 헤더 스타일·테두리·Phase 색 밴딩(§0.5 팔레트)·열 너비·헤더 고정(freeze) 포함. **미배정(회색) 행은 Phase/Milestone 빈 셀**로 내보낸다.
- **재파싱 계약 (fail-closed)**: 완전 배정 보드를 내보낸 파일은 `db/migrate.py` 의 `parse_workbook` 이 **그대로 다시 읽을 수 있어야 한다** — 내보내기가 곧 임포트 양식이다. 시드 보드 round-trip 테스트로 잠근다.
- **Doc Status 시트** 동봉: 전역 문서 목록(원본 양식). 프로젝트 내보내기는 여기에 프로젝트별 사용/링크/작성 상태 컬럼을 덧붙인다.
- 프론트: 툴바의 CSV 내보내기를 **XLSX 다운로드 버튼으로 교체** (blob, 인증 헤더 경유). ag-grid CSV 경로 제거.

### 0.5.8 자동저장 제거 (2026-08-08 — 사용자 결정)

WP 편집 화면의 **주기적 자동저장(30초)을 제거한다.** 저장은 수동 버튼(템플릿 임시저장 / 프로젝트 저장)뿐이다. dirty 추적·탭 전환/언마운트 시 미저장 확인·`hasUnsavedChanges()` 노출은 유지 — 없애는 것은 타이머뿐이다.

### 0.5.5 프로젝트 주요 링크 (2026-08-08 추가 — 사용자 결정)

프로젝트마다 관련 Confluence 페이지·클라우드 파일(URL 에 `edm` 문자열 포함) 등 **주요 링크**를 저장한다.

- 신규 테이블 `wp_project_links(id, project_id INT NOT NULL idx, sort_order INT NOT NULL, description VARCHAR(200) NOT NULL, url VARCHAR(1000) NOT NULL)` — 마이그레이션 005 + schema.sql 동기.
- API:
```
GET /api/v1/projects/{pid}/links → { links: [{id, description, url, sort_order}] }   // sort_order 순
PUT /api/v1/projects/{pid}/links → { links: [{id|null, description, url}] }          // 배열 순서 = sort_order, 전량 교체(빠진 기존 id 는 삭제)
```
- **URL 검증 (서버 422 + 클라이언트 병행)**: `http://` 또는 `https://` 로 시작하는 인터넷 주소만 허용. 설명 공백 불가.
- **UI (프로젝트 대시보드 탭)**: 대시보드 높이를 **항목 높이에 맞춰** 줄이고(뷰포트 채우기 금지), 그 아래 **ag-grid 테이블** — 컬럼: 설명(편집) · 링크(편집, 우측에 **연결 아이콘** — 클릭 시 새 창 `window.open`, noopener). Community 관리형 row drag 로 순서 변경, 행 추가/삭제, 저장(벌크 PUT). readOnly 시 전부 비활성.

### 0.5.9 그리드 셀 편집 개편 (2026-08-08 — 일부 확정, 문서 모델은 사용자 확답 대기)

**확정 (즉시 구현):**
- **세로 가운데 정렬**: Key Action Item(title) · Deliverable · 대시보드 표시 컬럼 셀은 세로 기준 가운데 정렬 (현재 위 정렬).
- **Owner 셀 팝업**: 셀 클릭 시 인라인 에디터 대신 **Phase/Milestone 관리 팝업과 같은 스타일의 선택 팝업** — 스코프 Owner 목록에서 다중 선택(행의 owner 값 변경, 저장은 기존 수동 저장 경로) + 관리 기능(행 추가·이름 변경·삭제·드래그 순서 변경 — 기존 스코프 Owner CRUD API 사용, 사용 중 삭제는 §2.6 비활성화 규칙). ~~Owner 탭은 추후 제거 예정 — 이번엔 유지.~~ → **2026-08-09 제거 완료** (아래).

**Owner 탭 제거 (2026-08-09 확정·구현).** WP 포맷 관리와 프로젝트 양쪽에서 `Owner` 탭을 없앴다.
`views/MasterScopeData.vue` 는 삭제됐고, Owner 선택·관리는 보드 Owner 셀 팝업
(`components/OwnerManagerModal.vue`) 하나가 맡는다 — 같은 목록을 편집하는 화면이 둘일 이유가 없다.
따라온 결과 둘:

- **권한 판정이 좁아졌다.** 옛 탭은 `hostReadOnly` 만 봤다(Owner 는 버전 스코프가 아니라는 근거). 팝업은 `readOnly` 를 따른다 — 보드 셀에서 열리므로 그 보드의 편집 가능 여부를 물려받고, 발행된 버전을 보는 중에는 Owner 관리도 잠긴다.
- **템플릿 계층에는 탭 바가 사라졌다.** 남는 화면이 보드 하나뿐이라 탭 하나짜리 탭 바가 되는데, 그건 탭이 없는 것보다 나쁘다. 프로젝트는 대시보드·Work Package·문서 등록 **3개**로 줄었다.

스코프 Owner CRUD API 는 그대로다 (`GET/POST/PUT/DELETE .../owners`) — 팝업이 쓴다.

**대기였던 문서 모델 — 확정됨. §0.5.10 참조.**

### 0.5.10 문서 모델 개편 — 포맷 종속 + 프로젝트 복제 (2026-08-08 사용자 확정)

**전역 문서는 폐기된다.** 문서는 Phase/Milestone/Owner 와 같은 스코프 규칙을 따른다: **포맷(템플릿)이 소유**하고, **프로젝트 생성 시 발행본에서 복제**되며, 이후 서로 무관하다. 사용자 확정 3건: ① 포맷 종속 + 복제, ② 프로젝트 로컬 문서 행추가 허용, ③ 엑셀 표기도 **숫자로 통일** (원문자 폐기).

**스키마 (마이그레이션 `006_document_ownership.sql` — 기존 데이터 이행 포함, 손실 금지):**
```
wp_template_documents(id, template_id, name VARCHAR(200) NOT NULL, sort_order INT NOT NULL, is_active TINYINT(1) DEFAULT 1)
wp_project_documents — 개편: (id, project_id, name, sort_order, is_used, link_url, doc_status)  # document_type_id 제거
wp_item_documents.document_type_id → template_document_id (FK wp_template_documents)
wp_project_item_documents.document_type_id → project_document_id (FK wp_project_documents)
wp_document_types — 이행(각 템플릿·프로젝트로 복제 + 링크 재매핑) 후 DROP
```
문서 **표시 번호 = sort_order (1..N 연속, apply 가 재부여)**. 원문자 코드 개념 삭제.

**API:**
```
GET  /versions/{vid}/documents            팝업 로드용 목록 (또는 버전 페이로드에 documents 동봉)
POST /versions/{vid}/documents/apply      { documents:[{id|null, name}], deleted_ids } — phases/apply 동형(원자적·집합일치 422)
GET  /projects/{pid}/documents            문서 등록 탭 + 셀 팝업 공용
PUT  /projects/{pid}/documents            { documents:[{id|null, name, is_used, link_url, doc_status}], deleted_ids }
                                          — 배열 순서 = sort_order. 셀 팝업 관리부와 등록 탭이 같은 경로를 쓴다
```
삭제 캐스케이드: 해당 문서의 항목 링크 제거(응답에 재계산 items 동봉해 그리드 갱신). 템플릿 문서는 버전 간 공유되므로 다른 버전이 쓰면 §0.4 정밀화 1과 동일하게 비활성화. 검증: 빈 이름·중복/스코프 밖 id·집합 불일치 422.

**UI:**
- 관련문서 셀 팝업 (Phase/Milestone 팝업과 같은 스타일): 행의 문서 다중 선택(저장은 수동 저장 경로) + 관리(행추가·이름변경·드래그 순서변경·삭제 — 삭제 시 "N개 행에서 연결 해제" 경고). 템플릿은 DRAFT 에서만, **전역 경고 문구는 불필요해짐**(모델 변경으로). 프로젝트 팝업에는 **사용여부** 컬럼 추가.
- **WP 포맷 관리의 문서 기준정보 탭 제거** (MasterDocumentTypes — 전역 마스터 화면 폐기).
- 프로젝트의 문서 탭 이름 **"문서 등록"**: 컬럼 = 사용여부 · **순서**(1,2,3 숫자) · 문서명(수정 가능) · **문서 링크**(구 클라우드 링크) · 상태.
- 그리드 관련문서 렌더러·overview 문서·PPT 상세 슬라이드: 원문자 → 숫자.

**XLSX / 임포터 (표기 숫자 통일 ③):**
- 내보내기 '관련 문서' 셀 = 숫자 ` / ` 연결 (예: `1 / 3`). Doc Status 시트 = 순서·문서명 (+프로젝트: 사용/링크/상태).
- `db/migrate.py` `parse_documents` 개정: **숫자 토큰 허용**(round-trip 대상) + **원문자도 계속 허용**(원본 `docs/Work Package.xlsx` 최초 임포트용 — ①=순서 1 로 대응). round-trip 테스트는 숫자 표기로 갱신.

**이식 계약 갱신:** INTEGRATION.md §3 "호스트 문서 마스터 병합 지점" 폐기 — `document_type_repository_factory` 주입 파라미터 제거(도입 호스트 0, 지금이 적기). `TRANSPLANT.md` 테이블 목록·`db/transplant.sql` 재생성.

**문서 목록 GET 필드 확정 (2026-08-09 — 라이브 검증에서 목/서버 불일치 발견 후 고정):** 문서 응답의 순서 필드는 **`no`** (파생 표시번호 — 프로젝트 off 문서는 null) 하나다. `sort_order` 는 응답에 싣지 않는다 (내부 저장용). 템플릿: `{id, no, name, is_active}`, 프로젝트: `+ is_used, link_url, doc_status`. 목·타입·liveCheck 는 이 형태를 따른다. 또한 **신규 템플릿은 문서 0개로 시작**한다 — 전역 모델 전제(문서가 항상 존재)를 가정한 코드는 스코프 모델에서 깨진다.

**팝업 정밀화 (2026-08-09 사용자 피드백):**
- 프로젝트 관련문서 팝업: 가장 좌측 선택 체크 컬럼의 헤더는 **"선택"**. 사용 컬럼은 **on/off 스위치**(컬럼명 **"사용"**). "번호" 컬럼명은 **"순서"**.
- **순서 번호는 사용(ON) 문서에만 1..N 을 부여한다** — off 문서는 `—` 표시, 스위치 전환 즉시 팝업·문서 등록 탭의 순서가 재계산된다. 이 의미론은 표시 전반(그리드 뱃지·overview·XLSX '관련 문서'/Doc Status·PPT)에 일관 적용된다. 템플릿 계층에는 is_used 가 없으므로 전체 1..N 그대로.
- **Owner 팝업 단순화**: 순서 관련 기능 전부 제거 — 드래그 순서 변경·순서 index 표시/관리 없음. 목록 순서는 서버가 주는 순서 그대로.
- **Owner 추가 방식 통일**: Phase/Milestone/문서 팝업과 동일하게 **[Owner 추가] 버튼 → 행 추가 + 인라인 이름 입력** 방식으로.
- **off 문서와 선택의 일관성 (2026-08-09 버그 수정)**: 사용을 off 로 전환하면 그 문서의 **선택 체크는 즉시 해제**되고 선택은 비활성이 된다 — 사용 중 문서만 선택 가능. 적용 시 현재 행 값에서 off 문서를 제거하고, **셀 렌더러는 no 가 null(off)인 문서를 표시하지 않으며**, 수동 저장 시 document_ids 에서 off 문서를 제외한다. (서버 DB 링크는 표시에서만 드롭되므로, 렌더러 필터가 다른 행들의 잔재도 자동 정리한다.)

### 0.6 설비사 설정 · 전체 현황 허브 (2026-08-08 추가 — 사용자 결정)

**호스트 maker 테이블은 손댈 수 없다.** 이식 대상 호스트의 모델은 `makers(id, maker, maker_ko, maker_en, maker_alias)` 이며 컬럼 추가 불가. 따라서:

**1) `wp_maker_settings` (신규, 마이그레이션 004 + schema.sql 동기).** `(id, maker_id INT NOT NULL UNIQUE — 물리 FK 금지(호스트 테이블), show_in_overview TINYINT(1) NOT NULL)`. **표시 규칙**: 설정 행이 있으면 그 값, **없으면 "active 프로젝트가 있으면 표시"** — 무설정 설치에서도 전체 현황이 비지 않고, 그러면서도 체크로 양방향 제어가 된다.

**2) MakerResolver 포트 확장.** 기존 이름 해석에 **`list_makers() -> [{id, name}]`** 추가. 호스트 구현은 자기 makers 테이블에서 표시명(예: `maker_ko or maker`)을 만들어 반환, 개발 스텁은 `wp_dev_makers`. resolver 미설정이면 빈 목록이 정상(설정 화면은 안내 문구, overview 는 기존 폴백 이름 `설비사 #id`). 루트 INTEGRATION.md §2 에 포트 계약 반영.

**3) API.**
```
GET /api/v1/makers            → { makers: [{maker_id, name|null, show_in_overview(유효값), explicit(설정행 존재), has_projects}] }
PUT /api/v1/makers/settings   → { settings: [{maker_id, show_in_overview}] } 업서트
PATCH /api/v1/projects/{pid}  → { name } 프로젝트명 수정 (빈 이름 422)
GET /api/v1/projects/overview → **개편**: { makers: [{maker_id, name|null, projects:[ …기존 §0.5-3 프로젝트 형태… ]}] }
                                 — 표시 규칙 적용·설비사 단위 그룹핑을 서버가 수행. 체크된 설비사는 프로젝트 0개여도 섹션이 나온다.
```

**4) 전체 현황 = 프로젝트 허브 (프론트).**
- 설비사 섹션 **접기/펼치기** (기본 펼침). 섹션 헤더: 이름 · 프로젝트 수 · **[+ 프로젝트 추가]** (모달: 이름 + 발행본 있는 템플릿 선택 → `POST /projects`).
- **프로젝트명 인라인 수정** — 연필 아이콘 없이 **이름 텍스트 클릭 = 수정 모드** (2026-08-08 정정. 이동은 이동 아이콘이 전담하므로 이름 클릭이 비어 있다). 입력 → PATCH, Esc/blur 처리. readOnly prop 이면 추가/수정/설정 전부 비활성(이름 클릭 무동작).
- **가독성**: 글자 과소 금지 — 진행률·전체 건수·문서 영역은 본문 크기(≥12px)와 진한 색으로. 각 행의 4구획은 **세로 가운데 정렬**.
- **설비사 설정은 독립 노출이다 (2026-08-08 개정 — 사용자 결정).** 전체 현황 안의 [설비사 설정] 버튼은 **제거**하고, 설정 화면을 네 번째 페더레이션 노출 **`./MakerSettings`** 로 분리한다 (props: `apiBaseUrl`·`readOnly`, maker 무관). 내용: 설비사별 전체현황 표시 + 저장(PUT), 유효값/명시 설정 구분 표시. ~~표 한 장~~ → **카드 형태로 개편** (§0.6.1).
- **호스트 메뉴 구조 (권장 — 하니스가 시연)**: 메인 페이지 = **전체 현황** (기본 진입). 프로젝트 세부는 전체 현황의 [이동] 으로 진입. 별도 **관리** 그룹 아래 두 메뉴: **Work Package 포맷 관리** (= `./MasterAdmin`, 구 "기준 데이터 관리" 명칭 대체) · **Integrated AI 참여 설비사 관리** (= `./MakerSettings`). 메뉴 소유는 호스트지만 이 이름을 표준 라벨로 문서화한다.
- **프로젝트 이동은 URL 로 표현된다 (2026-08-08 추가 — 사용자 결정).** 전체 현황에서 [이동] 시 URL 이 `{전체현황 경로}/{projectId}` 가 된다. **라우팅 소유는 여전히 호스트**다 — 모듈은 `onOpenProject` 콜백만 부르고, URL 갱신·해석은 호스트(개발 하니스가 시연) 책임: 하니스는 history.pushState 로 `/{projectId}` 를 붙이고, 직접 진입(딥링크)·새로고침 시 URL 에서 projectId 를 읽어 `GET /projects/{pid}` 로 makerId 를 해석해 ProjectWorkspace 를 마운트하며, 뒤로 가기(popstate)로 전체 현황에 복귀한다. 실호스트용 권장 라우트 패턴은 INTEGRATION.md §5 에 기록.
- **프로젝트 목록 페이지는 제거됐다 (2026-08-08 확정 — "추후 제거 예정" 이 실행됨).** Work Package 탭의 [프로젝트 목록] 버튼도 함께 제거. 프로젝트 진입 경로는 **전체 현황의 [이동] 버튼 하나**다. 따라서 `./ProjectWorkspace` 는 **`projectId` 가 필수 prop** 이 된다 (makerId 와 함께 `onOpenProject(projectId, makerId)` 에서 온다). projectId 없이 마운트되면 빈 상태 안내("전체 현황에서 프로젝트를 선택하세요")를 렌더한다 — 예외 금지.
- **디자인 언어 (2026-08-08 사용자 피드백)**: 각지고 딱딱한 인상 금지. 설비사마다 **뚜렷한 카드 구획**(둥근 모서리 rounded-xl 이상, 은은한 그림자·옅은 배경으로 페이지와 분리), 카드 안의 프로젝트 행들은 **들여쓰기(indent)** 로 하위 항목임이 형태로 드러나야 한다. 여백을 충분히 주어 "이쁘면서 깔끔한" 인상 — 프로젝트가 여러 개여도 행 간 구분이 명확할 것 (행 사이 간격 또는 옅은 구분선, 마지막 행 여백 처리).

### 0.6.1 프로젝트 사용 여부 스위치 (2026-08-09 추가 — 사용자 결정)

설비사 관리 화면(`./MakerSettings`)에서 **설비사마다 그 설비사의 프로젝트를 나열하고, 각
프로젝트에 사용 여부 on/off 스위치**를 둔다. 목적은 "전체 현황에서 안 보이게" 이고, **DB 에서
지우는 것이 아니다.**

**1) 컬럼은 기존 `wp_projects.is_active` 다.** 신규 컬럼도 마이그레이션도 없다 — `DELETE
/projects/{id}` 가 이미 이 컬럼을 끄는 비활성화였고, 전체 현황은 이미 활성만 그린다. 스위치는
그 컬럼에 UI 를 붙인 것뿐이며, 두 경로가 같은 컬럼을 쓰는 것이 요점이다(갈리면 화면이 어긋난다).

**2) API — 기존 저장 경로에 실린다.**
```
GET /api/v1/makers          → makers[].projects: [{id, name, is_active}]   // **비활성 포함**
PUT /api/v1/makers/settings → { settings: [...], projects: [{id, is_active}] }  // 한 트랜잭션
```
설비사 체크와 프로젝트 스위치가 **한 화면의 한 저장 버튼**이므로 한 커밋으로 묶는다. 두 배열로
나뉜 이유는 검증 규칙이 반대라서다: 모르는 `maker_id` 는 **허용**(설비사는 호스트 것이고
resolver 미주입이 정상 상태), 모르는 프로젝트 id 는 **422**(우리 테이블이라 모른다고 할 이유가
없다). `projects` 가 빈 배열이면 "건드리지 말라" 이지 "전부 끄라" 가 아니다.

**3) `GET /makers` 의 `projects` 는 활성으로 거르지 않는다 — 이것이 이 기능의 불변식이다.**
다른 조회 경로는 전부 활성만 준다. 이 화면까지 그러면 스위치를 끄는 순간 다시 켤 화면이 사라져
**off 가 편도 조작**이 된다. 같은 이유로 `maker_service.known_makers` 도 비활성 프로젝트의
`maker_id` 를 센다 — 프로젝트를 전부 꺼 둔 설비사가 표에서 사라지면 안 된다. 전체 현황의 표시
판단은 영향받지 않는다: §0.6-1 의 `has_projects` 는 여전히 **활성** 기준이다.

**4) 화면은 전체 현황과 같은 카드다 (2026-08-09 사용자 피드백 — "너무 투박").**
antd `Table` 한 장이던 형태를 버린다. 설비사 밑에 프로젝트가 딸리면서 표가 무너졌기
때문이다 — 한 칸 안에 목록을 세로로 쌓게 되고, 어디까지가 한 설비사인지 경계가 사라진다.
§0.6-4 가 전체 현황에 요구한 디자인 언어를 **그대로** 쓴다: 옅은 배경(`#f8fafc`) 위의 흰
카드, `rounded-xl`, 은은한 그림자, **접기/펼치기(기본 펼침)**, 하위 프로젝트는 들여쓰기
(`ml-6`) + 행 간 옅은 구분선. 두 화면이 같은 위계(설비사 → 프로젝트)를 보여 주므로 같아
보여야 한다.
- 설비사 카드 헤더: 접기 토글 · 이름(미해석이면 `설비사 #id` + 태그) · `프로젝트 N · 사용 M` ·
  출처 태그(직접 설정 / 자동) · **전체 현황 표시 스위치**. 체크박스에서 스위치로 바꾼 것은
  아래 프로젝트 스위치와 같은 조작이기 때문이다 — 한 화면에 두 종류의 on/off 는 없다.
- 꺼진 프로젝트 행은 배경을 눌러 칠하고 `미사용 — 전체 현황에서 숨김` 태그를 단다.
- 설명 문구는 화면 **하단 한 줄**로 접었다. 상단 Alert 두 장이 정작 조작할 카드를 아래로
  밀어냈다.
- `readOnly` 면 모든 스위치가 비활성이고 [저장] 이 사라진다.

**5) 실제 삭제는 UI 에 없고 API 에도 없다.** DB 에서 지우는 경로는 관리자가 직접 실행하는
`db/delete_project.py` 뿐이다 (루트 `README.md` §5.2). 되돌릴 수 없는 조작을 화면에 두지 않는
것이 설계이며 미구현이 아니다. 스크립트는 FK **역순으로 직접** 지운다 — `wp_project_items` 가
`wp_project_phases`/`wp_project_milestones` 를 `ON DELETE RESTRICT` 로 참조해, 캐스케이드에
맡기면 전파 순서에 따라 FK 오류로 실패할 수 있기 때문이다.

## 1. 현황 분석

### 1.1 원본 엑셀 구조

**Project Board 시트** (35행 × 9컬럼)

| 컬럼 | 내용 | 특징 |
|---|---|---|
| No | 1 ~ 35 | 단순 순번. 순서 변경 시 재계산 대상 |
| Phase | `Phase 0. Pre-Infrastructure Setup` | **번호 + 이름이 한 문자열에 섞여 있음** |
| Milestone | `0.1 DSEP 환경 Gap 및 자원 구성` | **`{phase번호}.{milestone번호} 이름` 형태** |
| Key Action Item | 수행 내용 서술 | 장문 텍스트 |
| Deliverable (Check Point) | `DSEP Gap & Resource Plan` | 산출물명 |
| 관련 문서 | `① Project Charter & R&R / ② DSEP Readiness & I/O Spec` | **다중값 (N:M). ⚠️ `/` 로 분리하면 안 됨 — 문서명 "DSEP Readiness & I/O Spec" 자체에 `/` 가 포함되어 깨진다. 원문자 마커 ①~⑤ 기준으로 토큰화할 것** |
| Owner | `DSEP 인프라 담당자+사내 IT·보안` | **`+` 구분 다중값 (N:M)** |
| Status | `Not Started` | 실행 상태 |
| 완료일 | (비어있음) | |

- 상단 요약행: `전체 35 / Done 0 / 진행률 0%`
- Phase 구성: Phase 0(4행), Phase 1(10행), Phase 2(11행), Phase 3(10행)
- Milestone 구성: 0.1~0.2, 1.1~1.3, 2.1~2.4, 3.1~3.4 (총 13개)

**Doc Status 시트** (5행)

| No | 문서명 | 단계 | 관련 Gate | 작성 주체 | Status | 비고 |
|---|---|---|---|---|---|---|
| ① | Project Charter & R&R | Phase 1 | G1 | DSEP 인프라 담당자 | Not Started | 범위·KPI·역할·협업원칙·통합계획·착수승인 |
| ② | DSEP Readiness & I/O Spec | Phase 0~1 | G0·G1 | DSEP 인프라 담당자+사내 IT·보안 | Not Started | 인프라·자원연결·데이터 준비·I/O 규격·반입반출 |
| ③ | PM Management Log | Phase 2 (상시) | G2 | DSEP 인프라 담당자 | Not Started | 대장: 본 파일 RAID·Action·Decision 탭 |
| ④ | Model Submission & Evaluation | Phase 2~3 | G2·G3 | 설비사+사내 개발부서 | Not Started | Candidate 제출·평가·Acceptance 판정·Rework |
| ⑤ | Pilot, Closure & Expansion | Phase 3 | G4·G5 | 사내 개발부서+공동 | Not Started | Pilot·Go/No-Go·인계·종료·확대 |

### 1.2 환경 점검 결과 (실측)

| 항목 | 확인 내용 |
|---|---|
| DB 서버 | **MariaDB 11.2.2** (MySQL 아님) — 문법 호환되나 `CHECK` 제약/JSON 함수 동작 차이 주의 |
| 접속 | `localhost:3306` / `user01` — 접속 성공 |
| 권한 | `CREATE`, `DROP`, `ALTER`, `INDEX`, `REFERENCES` 등 전체 보유 → DB 생성 가능 |
| 기존 DB | `acais`, `auth`, **`dsep_iai`**, `eqdk_db`, `llmwiki`, `test` 등 |
| Python | 3.8.8 (Anaconda 전역) → **FastAPI/SQLAlchemy 2.x/Pydantic v2 용 별도 venv (3.11+) 권장** |
| Node | v24.12.0 → Vue3 + Vite 사용 가능 |

### 1.3 기존 `dsep_iai` DB (선행 작업물)

이미 유사 목적의 스키마가 존재하며, 이번 설계의 참고 기준으로 삼는다.

```
wp_templates → wp_template_versions (DRAFT/PUBLISHED/RETIRED) → wp_template_items (105행)
wp_phases (5) / wp_milestones (14)          ← 이미 phase/milestone 분리 시도 흔적
makers (설비사) / programs
maker_boards → maker_wp_items (35행)        ← 설비사별 인스턴스
document_types (5) → maker_document_requirements → document_submissions
maker_weekly_snapshots / weekly_snapshot_items / maker_wp_week_marks / maker_issues
```

**본 계획에서 개선하는 점**

1. `wp_template_items.phase` / `.milestone` 이 여전히 `varchar` 문자열로 남아 있음 (`phase_id`/`milestone_id` 컬럼은 추가만 되고 nullable) → **FK 필수화, 문자열 컬럼 제거**
2. Phase/Milestone 번호가 이름 문자열에 포함됨 → **`seq_no` 정수 컬럼으로 분리**
3. `owner` 가 `varchar(200)` 단일 문자열 → **기준정보 테이블 + N:M 관계로 정규화**
4. `doc_code` 단일 값 → **N:M 관계로 정규화** (원본 엑셀은 다중값)
5. 발행 시 검증 로직 부재 → **publish validation 도입**

> 신규 DB `iai-test` 로 재구축하며, 기존 `dsep_iai` 는 그대로 보존한다.

---

## 2. 핵심 설계 결정

### 2.1 [요구사항 1] Phase / Milestone 번호의 컬럼 분리

**문제**: 현재 `Phase 0. Pre-Infrastructure Setup`, `0.1 DSEP 환경 Gap 및 자원 구성` 처럼 번호가 이름에 박혀 있어 순서가 바뀌면 이름을 전부 고쳐야 함.

**해결**: 번호를 별도 정수 컬럼으로 분리하고, 화면 표시 문자열은 **조합으로 생성**한다.

| 저장 | 표시 |
|---|---|
| `phases(seq_no=0, name='Pre-Infrastructure Setup')` | `Phase 0. Pre-Infrastructure Setup` |
| `milestones(phase_id→seq_no=0, seq_no=1, name='DSEP 환경 Gap 및 자원 구성')` | `0.1 DSEP 환경 Gap 및 자원 구성` |

**"2개 컬럼" 처리**: Milestone 표시번호 `1.2` 의 앞자리(major)는 **소속 Phase 의 `seq_no` 에서 파생**하고, 뒷자리(minor)만 `milestones.seq_no` 로 저장한다.
→ major 를 별도 저장하면 Phase 번호 변경 시 두 곳이 어긋날 수 있으므로 **파생값으로 통일**. API 응답에는 `phase_no`, `milestone_no`, `milestone_display("1.2")` 를 모두 내려주어 프론트가 조합 로직을 갖지 않도록 한다.

**Phase 시작 번호**: 원본이 `Phase 0` 부터 시작하므로 WP 단위 설정값 `phase_start_no` (기본 0)를 둔다.

### 2.2 [요구사항 3] 순서 재계산(Renumbering) 알고리즘

행 목록은 `sort_order` 로 정렬된 단일 리스트다. Phase/Milestone 번호는 **행 순서상 최초 등장 순서**로 결정된다.

```
renumber(rows):                          # rows: sort_order 오름차순
  phase_no = {}, next_phase = phase_start_no
  ms_no    = {}, next_ms = {}            # phase_id -> 다음 milestone 번호

  for r in rows:
      if r.phase_id not in phase_no:
          phase_no[r.phase_id] = next_phase; next_phase += 1
          next_ms[r.phase_id]  = 1
      key = (r.phase_id, r.milestone_id)
      if key not in ms_no:
          ms_no[key] = next_ms[r.phase_id]; next_ms[r.phase_id] += 1

  # phases.seq_no / milestones.seq_no 에 반영, rows.sort_order 1..N 재부여
```

**전제 — 블록 연속성(contiguity)**: 같은 Phase 의 행들은 반드시 연속해야 한다. Milestone 도 Phase 블록 내에서 연속해야 한다. 이 전제가 깨지면 번호 부여가 불가능하므로, 아래 UI 규칙으로 **구조적으로 깨질 수 없게** 만든다.

**행 추가 (각 행의 `+` 버튼 / 툴바 append)** — **§0.2 로 개정됨**
- 클릭한 행 **바로 아래**(툴바는 맨 끝)에 **미배정(회색) 행** 삽입. phase/milestone = null, 상속하지 않는다.
- 회색 행은 연속성 검사에서 투명하므로 어디에 있어도 위반이 아니다.
- 삽입 후 `renumber()` 실행 (null 행은 번호 부여에서 건너뜀)

**행 이동 (ag-grid row drag) — 같은 Milestone 블록 안에서만 가능**

- 드래그는 **자기 Phase·Milestone 블록 내부의 순서 변경**만 수행한다. **소속은 절대 바뀌지 않는다.**
- 블록 밖으로 끌면 드롭이 거부되고 원래 위치로 되돌아간다. 사유를 안내한다.
- 이동 후 `renumber()` 실행 — 블록 내부 순서만 바뀌므로 Phase/Milestone 번호는 그대로다.
- **소속 변경은 오직 Phase/Milestone 셀 편집(`PATCH .../membership`)으로만 한다.**

> **왜 바꿨나 (2026-08-07).** 초안은 "드롭 후 바로 위 행의 소속을 상속"이었다. 그러면 다른 Phase 영역으로 끌었을 때 **아무 경고 없이 그 행의 Phase 가 재배정된다.** 순서만 바꾸려던 사용자에게는 분류가 멋대로 바뀌는 것으로 보이고, 원래 Phase 의 마지막 행을 끌어내면 그 Phase 자체가 사라진다. 재현:
>
> ```
> 전: 행1(P0) 행2(P0) │ 행3(P1) 행4(P1) 행5(P1)
> 행1 을 P1 블록 가운데로 드래그 →
> 후: 행2(P0) │ 행3(P1) 행1(P1←바뀜) 행4(P1) 행5(P1)     breaks: 없음
> ```
>
> **부수 효과 하나가 크다**: 드래그가 소속을 건드리지 않으면 `reorder` 는 소속을 재유도할 이유가 없어진다. LIS 기반 이동 행 탐지(`apply_position_change`, `moved_item_id`)가 통째로 불필요해지고, 그와 함께 §4.2 에 기록된 **조각남 확률(임의 순열 n=6 에서 12.86%, 오보 시 ~1%)의 원인도 사라진다.** 남는 규칙은 하나다 — **행은 자기 소속을 들고 다니며, 순서만 바뀐다.**

**행 삭제**: 삭제 후 `renumber()`. 빈 Phase/Milestone 은 번호 부여 대상에서 제외 (기준정보 자체는 보존, `is_active` 유지)

### 2.3 [요구사항 3] Phase/Milestone 셀 편집 — 경계(boundary) 규칙

Phase/Milestone 셀 클릭 시 커스텀 셀 에디터(드롭다운)가 열린다.

**경계 판정**
행 `R` 이 인덱스 `i` 일 때,
- **상단 경계**: `i == 0` 이거나 `rows[i-1].phase_id != R.phase_id`
- **하단 경계**: `i == last` 이거나 `rows[i+1].phase_id != R.phase_id`
- **경계 행** = 상단 경계 또는 하단 경계 (즉 자기 Phase 블록의 첫 행이거나 마지막 행)

Milestone 도 동일하되, 판정 범위는 **자기 Phase 블록 내부**로 한정한다.

**드롭다운 동작**

| 행 위치 | 기존 항목 선택 | `+ 새 Phase 생성` |
|---|---|---|
| 경계 행 | ✅ 인접 블록으로 병합 | ✅ **활성** |
| 중간 행 | ⚠️ 선택 시 "대상 Phase 블록 끝으로 행이 이동됩니다" 확인 후 이동 | ❌ **비활성** (사유 툴팁 표시) |

> **중간 행 이동은 서버가 수행한다.** `PATCH .../items/{iid}/membership` 이 대상 블록 끝으로의 **재배치까지 처리**한다. 여기서 422 로 거부하면 목적지 인덱스 계산이 셀 에디터로 넘어가는데, 그 판단을 클라이언트에서 몰아내는 것이 §2.3 의 존재 이유다. 422 는 정말로 불가능한 요청에만 쓴다.
>
> 연속성 오류를 반환할 때는 **사용자가 편집한 행**을 가리켜야 한다. 블록이 갈라져 보이는 지점(뒤쪽 행)을 가리키면 그리드가 엉뚱한 셀을 하이라이트한다.
>
> **미배정 행(`phase_id = null`)의 새 Phase 생성 조건 (§0.2-4 로 정정).** 미배정 행이 경계인 것은 맞지만, 생성 허용 기준은 "경계인가"가 아니라 **"만들었을 때 결과가 연속인가"** 다: 위·아래 이웃의 phase 가 서로 다르거나 리스트 양끝이면 허용, 같은 블록 한가운데면 그 블록이 쪼개지므로 422/비활성. `can_create_phase` 는 이 기준으로 계산한다.

**새 Phase 생성 시 삽입 위치**
- `R` 이 상단 경계 → 현재 Phase **앞**에 신규 Phase 삽입
- `R` 이 하단 경계 → 현재 Phase **뒤**에 신규 Phase 삽입
- 블록 크기가 1이면 양쪽 경계 동시 성립 → 위치 모호성 없음 (기존 Phase 를 그 자리에서 대체)

> **비활성 사유**: 블록 중간 행에서 새 Phase 를 만들면 기존 Phase 가 두 조각으로 쪼개져 연속성이 깨지기 때문. 사용자에게 "Phase 경계 행에서만 새 Phase 를 만들 수 있습니다" 툴팁으로 안내한다.

**(선택) 확장**: 연속된 N개 행을 다중 선택해 한 번에 새 Phase 로 묶는 기능 — 2차 개발 후보

### 2.4 [요구사항 2] 버전 관리 — 상태 전이

> **적용 범위 (§0 개정): 이 절 전체는 템플릿(기준 데이터)에만 적용된다.** 프로젝트에는 버전·draft·발행·폐기·이력이 없다 — 생성이 곧 확정이고 이후 자유 편집이다.

```
                  ┌─────────────────────────────────────────┐
                  │                                         │
   (최초)      ┌──▼──┐   draft 발행    ┌───────┐   임시저장   │
   ──────────▶ │ 없음 │ ─────────────▶ │ DRAFT │ ◀───────────┘
               └─────┘                └───┬───┘   (검증 없음, 반복 가능)
                  ▲                       │
                  │                       │ 발행 (validation 통과 시)
                  │                       ▼
                  │                 ┌───────────┐
   draft 발행 ────┴───────────────  │ PUBLISHED │
   (deep copy)                      └─────┬─────┘
                                          │ 신규 버전 발행 시
                                          ▼
                                    ┌──────────┐
                                    │ ARCHIVED │
                                    └──────────┘
```

| 액션 | 동작 |
|---|---|
| **draft 발행** | 현재 `PUBLISHED` 버전의 **items 와 그 N:M 연관관계(문서·Owner)** 를 deep copy 하여 `version_number + 1` 의 `DRAFT` 생성. PUBLISHED 가 없으면 빈 v1 DRAFT 생성 |

> **Phase/Milestone 은 복제하지 않는다.** §3.2 에서 이들은 **버전이 아니라 WP 스코프**이므로 버전 간 공유된다. 복제하면 `UQ(work_package_id, name)` 에 걸린다.
>
> **표시 번호는 버전별로 읽는 시점에 계산한다.** Phase/Milestone 이 WP 스코프로 공유되는 이상, 표시 번호를 `wp_phases.seq_no` 에서 그대로 읽으면 **DRAFT 를 재정렬했을 때 PUBLISHED 의 번호까지 바뀌어 불변성이 깨진다.** 각 버전의 항목 순서를 기준으로 §2.2 알고리즘을 적용해 번호를 산출하고, `seq_no` 는 편집 가능한 버전에서만 기록한다.
| **임시저장** | **검증 없이** 현재 그리드 상태를 DRAFT 에 그대로 저장 (§2.5) |
| **발행** | 검증 통과 시 `DRAFT → PUBLISHED`, 기존 `PUBLISHED → ARCHIVED`, `published_at` 기록. 실패 시 오류 목록 반환하고 상태 유지 |

**불변 규칙 (DB 제약 + 서비스 레이어)**
- WP 당 `DRAFT` 는 **최대 1개** (부분 유니크 인덱스 대체: 서비스 레이어 검사 + 생성 트랜잭션 락)
- WP 당 `PUBLISHED` 는 **최대 1개**
- `PUBLISHED` / `ARCHIVED` 버전의 items 는 **수정 불가** (읽기 전용, API 레벨 차단)
- **상태 검사는 잠금 하에서 한다.** 상태를 잠금 없이 읽고 통과시키면, 검사와 쓰기 사이에 다른 요청이 발행/폐기를 끝낼 수 있다. 실제로 `임시저장 vs 발행` 은 발행된 버전을 덮어쓰고, `폐기 vs 발행` 은 **PUBLISHED 가 하나도 없는 상태**를 만든다 (이후 draft 발행이 빈 보드를 만든다). 버전 행을 잠근 뒤 상태를 다시 읽고 진행할 것

> **원칙: PUBLISHED 버전의 유효성과 번호는 변경 가능한 기준정보에 의존해서는 안 된다.**
>
> Phase/Milestone/Owner 는 WP 스코프라 버전 간 공유된다. 여기서 **이름 수정 같은 표시용 변경은 전파되어도 좋다** (오타 수정이 과거 버전에도 반영되는 편이 자연스럽다). 그러나 **구조를 바꾸는 변경은 발행된 버전에 닿으면 안 된다.**
>
> | 변경 | 발행 버전 전파 |
> |---|---|
> | Phase/Milestone 이름 수정 | 허용 (표시용) |
> | Milestone 의 소속 Phase 변경 | **금지** — 사용 중이면 거부. 발행 버전이 `MILESTONE_PHASE_MISMATCH` 로 무효화된다 |
> | `phase_start_no` 변경 | **금지** — 발행 시점에 **버전에 스냅샷**하고, 발행 버전의 표시 번호는 스냅샷에서 산출한다 |
>
> 버전은 자기 표시 파라미터를 스스로 들고 있어야 한다.
- 버전 비교(diff) 기능: PUBLISHED vs DRAFT 변경분 표시 — 2차 개발 후보

### 2.5 [요구사항 4] 검증(Validation)

**임시저장 — 검증 없음**
- 필수값 누락, Phase 미지정, 빈 문자열 모두 허용하고 저장
- 단, **참조 무결성만 최소 보장** (존재하지 않는 `phase_id` 등 FK 위반은 400)
- `phase_id` / `milestone_id` 는 nullable → 미지정 상태 저장 가능

**발행 — 전체 검증**

| # | 규칙 | 오류 코드 |
|---|---|---|
| V1 | 모든 행에 `phase_id` 지정 | `PHASE_REQUIRED` |
| V2 | 모든 행에 `milestone_id` 지정 | `MILESTONE_REQUIRED` |
| V3 | `milestone.phase_id == row.phase_id` (소속 불일치 금지) | `MILESTONE_PHASE_MISMATCH` |
| V4 | Phase 블록 연속성 | `PHASE_NOT_CONTIGUOUS` |
| V5 | Milestone 블록 연속성 (Phase 내부) | `MILESTONE_NOT_CONTIGUOUS` |
| V6 | Phase `seq_no` 가 `phase_start_no` 부터 빈틈없이 연속 | `PHASE_SEQ_GAP` |
| V7 | Milestone `seq_no` 가 Phase 내에서 1부터 빈틈없이 연속 | `MILESTONE_SEQ_GAP` |
| V8 | 행마다 **관련 문서 1개 이상** | `DOCUMENT_REQUIRED` |
| V9 | 행마다 **Owner 1명 이상** | `OWNER_REQUIRED` |
| V10 | `title`(Key Action Item) 필수 | `TITLE_REQUIRED` |
| V11 | `deliverable` 필수 | `DELIVERABLE_REQUIRED` |
| V12 | 참조된 document_type / owner 가 `is_active` | `INACTIVE_REFERENCE` |
| V13 | 행 0개인 버전 발행 금지 | `EMPTY_VERSION` |
| V14 | 사용되지 않는(빈) Phase/Milestone 존재 시 경고 | `ORPHAN_PHASE` / `ORPHAN_MILESTONE` (warning) |

**두 가지 필수 요건**

1. **`/validate` 와 `/publish` 는 같은 상태를 평가해야 한다.** 한쪽만 재계산 후 검증하면, 미리보기에서 `PHASE_SEQ_GAP` 을 보여주고도 발행은 성공하는 모순이 생긴다. 사용자가 대응할 수 없는 오류를 보게 되므로 두 경로의 전처리를 일치시킨다.
2. **V13 을 제외한 모든 오류는 `item_id` / `row_no` / `field` 를 채운다.** 그리드가 셀을 하이라이트할 수 없는 오류는 사용자에게 무의미하다. V6/V7(번호 불연속)도 해당 Phase/Milestone 의 **첫 행**을 가리켜야 한다.

**응답 형식** — 그리드가 해당 셀을 바로 하이라이트할 수 있도록 위치 정보를 포함. 발행 실패(422) 응답도 **`POST /validate` 와 동일한 형태**로 내려서 프론트가 파서를 하나만 갖게 한다 (`body.detail.errors`):

```json
{
  "valid": false,
  "errors": [
    { "code": "OWNER_REQUIRED", "level": "error",
      "item_id": 12, "row_no": 12, "field": "owners",
      "message": "12행: Owner가 지정되지 않았습니다." },
    { "code": "PHASE_NOT_CONTIGUOUS", "level": "error",
      "item_id": 20, "row_no": 20, "field": "phase_id",
      "message": "Phase 1 블록이 연속되지 않습니다. (20행)" }
  ],
  "warnings": [
    { "code": "ORPHAN_PHASE", "level": "warning",
      "phase_id": 7, "message": "Phase '보류'에 속한 항목이 없습니다." }
  ]
}
```

### 2.6 [요구사항 5] 기준정보(Master Data) 스코프

**전제 구조 (§0 개정)**: 설비사는 **프로젝트**를 여럿 가지며(설비사 1:N 프로젝트), 각 프로젝트는 발행된 템플릿에서 생성된다. 설비사 테이블은 **호스트 프로젝트 소유**이므로 이 저장소에서 만들지 않고, **`wp_projects.maker_id`** 정수 컬럼 + 인덱스로만 참조한다 (물리 FK 없음). 템플릿은 중앙 소유라 maker 개념이 없다. 상세 규칙은 [`INTEGRATION.md`](INTEGRATION.md) §2.

| 기준정보 | 스코프 | 근거 |
|---|---|---|
| **Document Type** (Doc Status) | **전역(Global)** | "전체 설비사의 아이템들에 공통 적용" |
| **Owner** | **WP 단위** | "이 WP로 관리되는 설비사 안에서만" |
| **Phase** | **WP 단위** | 동일 |
| **Milestone** | **WP 단위** (Phase 하위) | 동일 |
| **Maker(설비사)** | **호스트 소유 — 외부 참조** | 이 저장소에서 관리하지 않음 |

- 전역 기준정보는 `/api/master/document-types` 로 별도 관리 화면 제공 (CRUD)
- WP 스코프 기준정보는 `/api/wps/{wp_id}/owners`, `/phases`, `/milestones` 로 관리
- **삭제 정책**: 사용 중인 기준정보는 **hard delete 금지**. `is_active=false` 로 비활성화하고, 사용처가 없을 때만 실제 삭제 허용. 삭제 API 는 사용 건수를 함께 반환한다.

---

## 3. DB 스키마 설계 (`iai-test`)

### 3.1 ERD 개요

```
   [호스트 프로젝트 소유]
   makers  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐   ← 물리 FK 없음. maker_id 정수 + 인덱스로만 참조
                              ╎
                              ▼
work_packages ──┬──▶ wp_versions ──▶ wp_items ──┬──▶ wp_item_documents ──▶ document_types (전역)
 (maker_id)     │        (DRAFT/PUBLISHED/       └──▶ wp_item_owners ─────▶ wp_owners
                │         ARCHIVED)                                             ▲
                ├──▶ wp_phases ──▶ wp_milestones                                │
                └────────────────────────────────────────────────────────────────┘
                       (모두 work_package_id 스코프)
```

### 3.2 테이블 정의

> **실제 테이블명은 모두 `wp_` 접두를 붙인다** ([`INTEGRATION.md`](INTEGRATION.md) §4 — 호스트 스키마와 공존해야 하므로). 아래 표기 중 접두가 빠진 두 개의 실제 이름은 **`wp_work_packages`**, **`wp_document_types`** 다. 특히 `document_types` 는 호스트에 동명 테이블이 있을 가능성이 가장 높은 대상이라 접두가 필수다.

**`work_packages`** — WP 컨테이너 (설비사/아이템 컨텍스트)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| **maker_id** | **INT NOT NULL** | **호스트 설비사 테이블 참조. 물리 FK 없음, `idx_wp_maker` 인덱스만** |
| code | VARCHAR(50) | 식별 코드. UQ(maker_id, code) |
| name | VARCHAR(200) | 예: `DSEP AI Project Board` |
| description | TEXT | |
| phase_start_no | INT NOT NULL DEFAULT 0 | Phase 번호 시작값 |
| is_active | TINYINT(1) DEFAULT 1 | |
| created_at / updated_at | DATETIME | |

> 설비사 이름 등 부가 정보는 `MakerResolver` 포트로 호스트에 위임한다. 미주입 시 API 는 `maker_id` 만 반환하고 정상 동작한다 ([`INTEGRATION.md`](INTEGRATION.md) §2.2).

**`wp_versions`** — 버전

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| work_package_id | INT FK → work_packages | |
| version_number | INT | UQ(work_package_id, version_number) |
| status | ENUM('DRAFT','PUBLISHED','ARCHIVED') | |
| source_version_id | INT FK → wp_versions NULL | deep copy 원본 |
| notes | TEXT | |
| published_at / archived_at | DATETIME NULL | |
| created_by / published_by | VARCHAR(100) NULL | |
| created_at / updated_at | DATETIME | |

**`wp_phases`** — Phase 기준정보 (WP 스코프)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| work_package_id | INT FK | |
| name | VARCHAR(200) | 번호 제외한 순수 이름 |
| seq_no | INT | **재계산 대상** |
| is_active | TINYINT(1) | |
| UQ(work_package_id, name) | | |

**`wp_milestones`** — Milestone 기준정보

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| work_package_id | INT FK | 조회 편의를 위한 비정규화 |
| phase_id | INT FK → wp_phases | |
| name | VARCHAR(255) | |
| seq_no | INT | **재계산 대상** (Phase 내 1부터) |
| is_active | TINYINT(1) | |
| UQ(phase_id, name) | | |

> 표시 문자열 = `{phase.seq_no}.{milestone.seq_no} {milestone.name}`

**`wp_owners`** — Owner 기준정보 (WP 스코프)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| work_package_id | INT FK | |
| name | VARCHAR(200) | 예: `DSEP 인프라 담당자`, `사내 IT·보안`, `공동(구매·법무·보안)` |
| sort_order | INT | |
| is_active | TINYINT(1) | |
| UQ(work_package_id, name) | | |

**`document_types`** — 문서 기준정보 (**전역**)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| code | VARCHAR(20) UQ | `①` ~ `⑤` |
| name | VARCHAR(255) | `Project Charter & R&R` |
| phase_label | VARCHAR(100) | `Phase 0~1` (표시용 자유 텍스트) |
| gate_code | VARCHAR(50) | `G0·G1` |
| default_owner | VARCHAR(200) | 작성 주체 |
| status | ENUM('NOT_STARTED','IN_PROGRESS','DONE','HOLD','NA') | |
| remark | TEXT | 비고 |
| sort_order | INT | |
| is_active | TINYINT(1) | |

**`wp_items`** — 행(Work Package 항목)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT PK AI | |
| version_id | INT FK → wp_versions | |
| sort_order | INT NOT NULL | **표시 순서 = No 컬럼**, 재계산 대상 |
| phase_id | INT FK → wp_phases **NULL 허용** | 임시저장 시 미지정 가능 |
| milestone_id | INT FK → wp_milestones **NULL 허용** | |
| title | TEXT | Key Action Item |
| deliverable | TEXT | Deliverable (Check Point) |
| gate_code | VARCHAR(20) NULL | |
| status | ENUM('NOT_STARTED','IN_PROGRESS','DONE','HOLD','NA') DEFAULT 'NOT_STARTED' | 실행 상태 |
| completion_date | DATE NULL | 완료일 |
| origin | ENUM('INHERITED','ADDED') DEFAULT 'INHERITED' | DRAFT 에서 신규 추가된 행 표시 |
| source_item_id | INT NULL | deep copy 추적용 |
| created_at / updated_at | DATETIME | |
| INDEX(version_id, sort_order) | | |

**`wp_item_documents`** — 행 ↔ 문서 (N:M)

| 컬럼 | 타입 |
|---|---|
| item_id | INT FK → wp_items (ON DELETE CASCADE) |
| document_type_id | INT FK → document_types |
| sort_order | INT |
| PK(item_id, document_type_id) | |

**`wp_item_owners`** — 행 ↔ Owner (N:M)

| 컬럼 | 타입 |
|---|---|
| item_id | INT FK → wp_items (ON DELETE CASCADE) |
| owner_id | INT FK → wp_owners |
| sort_order | INT |
| PK(item_id, owner_id) | |

### 3.3 산출물

- `db/schema.sql` — `CREATE DATABASE` + 전체 `CREATE TABLE` DDL
- `db/seed.sql` — 엑셀 원본 35행 + Doc Status 5건 + Phase 4개 / Milestone 13개 / Owner 마스터 시드 (v1 PUBLISHED 로 등록)
- `db/migrate.py` — 엑셀 → DB 임포트 스크립트 (`관련 문서` 는 원문자 ①~⑤ 마커로 토큰화, `Owner` 는 `+` 분리)

### 3.4 주의사항

- **DB명 `iai-test` 의 하이픈**: SQL 에서 항상 백틱 필요 (`` CREATE DATABASE `iai-test` ``). SQLAlchemy DSN 에서도 그대로 사용 가능하나, 도구 호환성 문제 소지가 있어 `iai_test` 를 권장. **요청대로 `iai-test` 로 생성하되 이 점을 인지할 것.**
- **비밀번호의 `#`**: DSN URL 에서 `%23` 으로 인코딩 필요
  `mysql+pymysql://user01:<WP_DB_PASSWORD>@localhost:3306/iai-test?charset=utf8mb4`
  접속 정보는 저장소에 두지 않는다 — 환경변수(`WP_DB_DSN` / `WP_DB_PASSWORD`)로 받는다.
- **Charset**: 전 테이블 `utf8mb4` / `utf8mb4_unicode_ci` (한글 + `①`, `·` 등 특수문자)
- **MariaDB**: `ENUM` 사용 가능. 단 `CHECK` 제약은 MySQL 과 동작이 달라 검증은 애플리케이션 레이어에서 수행

---

## 4. 백엔드 (FastAPI)

### 4.1 구조

```
backend/
├── app/
│   ├── main.py
│   ├── core/          config.py, database.py, exceptions.py
│   ├── models/        SQLAlchemy ORM
│   ├── schemas/       Pydantic
│   ├── api/v1/        work_packages.py, versions.py, items.py, master.py
│   └── services/
│       ├── renumber_service.py     # §2.2 알고리즘 (서버가 최종 권한)
│       ├── validation_service.py   # §2.5 발행 검증
│       └── version_service.py      # deep copy / 상태 전이
├── tests/
└── requirements.txt
```

### 4.2 API 목록

> **§0 개정에 따른 구획**: 아래 기존 표(work-packages/versions/items)는 **템플릿 편집 API** 다. URL 은 `/api/v1/templates/...` 로 개칭한다. 프로젝트 API 를 추가한다:

**프로젝트** (버전 개념 없음 — 모든 편집이 직접 반영)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/v1/projects?maker_id=` | 설비사의 프로젝트 목록 |
| POST | `/api/v1/projects` | **생성** — `{maker_id, name, template_id}` (해당 템플릿의 최신 발행본에서 deep copy) 또는 `template_version_id` 지정 |
| GET | `/api/v1/projects/{pid}` | 프로젝트 + 전체 행 (그리드 로드) |
| PUT | `/api/v1/projects/{pid}/items` | 직접 저장 (무검증 bulk replace) |
| POST | `/api/v1/projects/{pid}/items` (+`/{iid}/insert-below`) | **회색 행** 추가 (§0.2) |
| POST | `/api/v1/projects/{pid}/items/reorder` | 블록 내 순서 변경 (회색 행은 자유) |
| PATCH | `/api/v1/projects/{pid}/items/{iid}/membership` | 소속 변경 (재배치 포함) |
| POST | `.../items/{iid}/create-phase` / `create-milestone` | **프로젝트 로컬** 생성 — 템플릿에 영향 없음 |
| CRUD | `/api/v1/projects/{pid}/owners·phases·milestones` | 프로젝트 로컬 기준정보 |
| DELETE | `/api/v1/projects/{pid}` | 비활성화 |

행 조작의 재계산·경계 플래그 응답 규약은 템플릿 쪽과 동일하다 (서버가 전체 목록 + 플래그 반환).

**Work Package / 버전**

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/v1/work-packages` | WP 목록 |
| GET | `/api/v1/work-packages/{id}/versions` | 버전 목록 |
| GET | `/api/v1/versions/{vid}` | 버전 + 전체 행 조회 (그리드 로드용) |
| POST | `/api/v1/work-packages/{id}/versions/draft` | **draft 발행** (deep copy) |
| PUT | `/api/v1/versions/{vid}/items` | **임시저장** — 전체 행 일괄 저장, 검증 없음 |
| POST | `/api/v1/versions/{vid}/validate` | 검증만 수행 (발행 전 미리보기) |
| POST | `/api/v1/versions/{vid}/publish` | **발행** — 검증 후 상태 전이 |
| DELETE | `/api/v1/versions/{vid}` | DRAFT 폐기 |

**행 조작** (즉시 반영형, 서버 재계산 결과 반환)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/versions/{vid}/items` | **빈 행 추가(append).** `insert-below` 는 기준 행이 있어야 하므로, 행이 0개인 신규 DRAFT 를 시작할 수단이 필요하다 |
| POST | `/api/v1/versions/{vid}/items/{iid}/insert-below` | 아래에 행 추가 (phase/milestone 상속) |
| POST | `/api/v1/versions/{vid}/items/{iid}/create-phase` | **경계 행에서 새 Phase 생성** (§2.3). 생성 + 배정 + 재계산이 묶인 원자적 연산 |
| POST | `/api/v1/versions/{vid}/items/{iid}/create-milestone` | 경계 행에서 새 Milestone 생성 |
| POST | `/api/v1/versions/{vid}/items/reorder` | **위치만** 변경 (드래그) + 재계산 |
| PATCH | `/api/v1/versions/{vid}/items/{iid}/membership` | **소속만** 변경 (§2.3 셀 편집) + 이동 + 재계산 |
| DELETE | `/api/v1/versions/{vid}/items/{iid}` | 행 삭제 + 재계산 |

**`create-phase` / `create-milestone`** — 기준 행(anchor)만 받고 **위치 파라미터를 두지 않는다.** 기준 행은 자기 자리를 지킨 채 `phase_id` 만 바뀌므로, 앞/뒤 삽입 여부는 그 행이 블록의 어느 경계에 있었는지에서 자동으로 따라 나온다. 중간 행이면 422.

**위치 변경과 소속 변경은 반드시 분리한다.** 두 연산을 한 엔드포인트에 합치면 소속을 클라이언트가 실어 보내게 되고, §2.2 의 구조적 보장이 "선택적으로만" 성립하게 된다.

```jsonc
// POST .../items/reorder — 순서만. 각 행은 자기 소속을 그대로 들고 간다.
{ "item_ids": [12, 3, 7, ...] }

// PATCH .../items/{iid}/membership — §2.3 셀 편집. 서버가 이동 + 연속성 검사.
{ "phase_id": 2, "milestone_id": 5 }
```

**`reorder` 는 소속을 재유도하지 않는다.** 각 행은 자기 `phase_id`/`milestone_id` 를 그대로 유지하고 위치만 바뀐다. `moved_item_id` 는 더 이상 받지 않는다.

| 입력 | 결과 |
|---|---|
| 블록 내부 순열 (UI 가 만드는 유일한 연산) | 항상 연속 — 소속이 안 바뀌므로 구조적으로 보장 |
| 블록을 가로지르는 순열 | **422** — `find_contiguity_breaks` 가 저장 전에 거부 |
| `membership` | 서버가 대상 블록 끝으로 재배치, 위반 시 422 |

> **이 단순화가 무엇을 없앴는가.** 이전 설계는 `reorder` 가 소속을 재유도했고, LIS 가 고르는 최소 이동 집합 밖의 행이 재상속을 못 받아 조각남이 발생했다 — 임의 순열 n=6 에서 **12.86%**, `moved_item_id` 오보 시 ~1%. 소속 재유도를 없애면 **그 실패 모드 자체가 존재하지 않는다.** 가드는 남겨 둔다(호스트의 다른 클라이언트가 임의 순열을 보낼 수 있으므로). 이력은 [`HANDOFF.md`](HANDOFF.md) §5.1·§5.1c 참조.

> ⚠️ **"소속을 받지 않으니 구조적으로 안전하다"는 추론은 틀렸다.** 실제로 이 추론에 근거해 `reorder` 에서 가드를 제거했다가 버그를 만들었다.
>
> **근본 원인**: `detect_moved_ids` 는 LIS 로 **최소** 이동 집합을 고른다. LIS 안에 남은 행은 소속을 재상속받지 않는데, **그 행의 이웃은 바뀌어 있을 수 있다.** 소속을 입력으로 받지 않아도 행들이 이미 소속을 들고 있기 때문이다.
>
> 임의 순열의 실패율은 **보드 크기에 따라 증가한다** (위 표: 4.35% → 8.84% → 12.86%). **실제 보드는 35행이다.**
>
> 최소 반례 — 보드 `[A/0, B/1, C/2, C/3]`, 순서 `(1,3,2,4)`, `moved_item_id=1` → `C/2, C/2, B/1, C/3` (C 가 두 조각). 같은 순서에서 **행 2가 실제로 움직였는데 클라이언트가 행 1이라고 보고한** 경우이므로, 이것은 동시에 "오보" 사례이기도 하다.
>
> **주장이 두 번 과했다는 점을 기록해 둔다.** 처음엔 "소속을 안 받으니 안전"(거짓), 고친 뒤엔 "드래그 범위에서는 안전"(역시 과함 — 정직한 보고 전제가 빠져 있었다). 두 번 다 작은 정의역 전수 탐색이 잡아냈다.
>
> 따라서 `find_contiguity_breaks` 는 `reorder` 경로에서 **이중 안전장치가 아니라 주 방어선**이다. 이 문구를 "불가능"으로 완화하지 말 것.
>
> 반례의 존재 자체가 **양성 사실로 테스트에 박혀 있다**. 나중에 누가 파생 로직을 완전하게 만들면 그 테스트가 먼저 깨지면서 "이제 가드를 제거해도 된다"고 알려준다 — 반례가 조용히 사라지지 않는다.

> **왜 합치지 않는가 (이식 관점).** 합친 형태에서는 "안전한 경로"가 선택 파라미터(`moved_item_id`)에 의존하게 된다. 호스트 프로젝트의 다른 클라이언트가 그 파라미터를 빼먹으면 **조용히 약한 경로로 떨어진다.** 안전이 기본값이 아니라 옵트인이 되는 구조는 이 저장소가 피하려는 결함 그 자체다. 분리하면 소속 변경 의도가 엔드포인트로 드러나고, 각 연산의 책임이 하나가 된다.
>
> 다만 **분리가 `reorder` 를 안전하게 만들어주지는 않는다** — 위 표의 경고를 볼 것. 분리의 이득은 의도의 명시성이지 보장의 강화가 아니다.
>
> 다만 정직하게 기록하면: 연속성은 원래도 **전역적으로** 구조적이지 않았다. 임시저장(`PUT .../items`)은 §2.5 에 따라 의도적으로 무검증이라 조각난 보드를 만들 수 있고, V4/V5 가 발행 시점에 잡는다. 즉 보장은 **행 조작 엔드포인트에서 구조적, 임시저장에서 의도적 부재**였다. 위 분리는 그 원래 성질을 되돌리는 것이다.

**기준정보**

| Method | Path | 설명 |
|---|---|---|
| GET/POST/PUT/DELETE | `/api/v1/master/document-types` | 전역 문서 |
| GET/POST/PUT/DELETE | `/api/v1/work-packages/{id}/owners` | WP 스코프 Owner |
| GET/POST/PUT/DELETE | `/api/v1/work-packages/{id}/phases` | WP 스코프 Phase |
| GET/POST/PUT/DELETE | `/api/v1/work-packages/{id}/milestones` | WP 스코프 Milestone |

**설계 원칙**
- 행 조작 API 는 **재계산된 전체 행 목록**을 응답으로 반환 → 프론트는 그대로 교체하면 되므로 클라이언트/서버 상태 불일치 방지
- 임시저장은 **전량 교체(bulk replace)** 방식 — 부분 diff 보다 단순하고 순서 재계산과 궁합이 좋음
- 재계산 로직은 **서버가 최종 권한**. 프론트는 UX 를 위해 낙관적으로 미리 계산하되, 응답으로 덮어씀

### 4.3 응답 예시 (`GET /api/v1/versions/{vid}`)

```json
{
  "version": { "id": 2, "version_number": 2, "status": "DRAFT", "work_package_id": 1 },
  "items": [
    {
      "id": 101, "sort_order": 1, "row_no": 1,
      "phase_id": 1, "phase_no": 0, "phase_name": "Pre-Infrastructure Setup",
      "phase_display": "Phase 0. Pre-Infrastructure Setup",
      "milestone_id": 1, "milestone_no": 1,
      "milestone_display": "0.1 DSEP 환경 Gap 및 자원 구성",
      "is_phase_block_start": true, "is_phase_block_end": false,
      "is_milestone_block_start": true, "is_milestone_block_end": false,
      "can_create_phase": true, "can_create_milestone": true,
      "title": "기존 DSEP 환경의 추가 필요사항(서버, Storage, 계정, 보안 등)을 점검하고 반영 계획을 확정",
      "deliverable": "DSEP Gap & Resource Plan",
      "documents": [{ "id": 2, "code": "②", "name": "DSEP Readiness & I/O Spec" }],
      "owners":    [{ "id": 1, "name": "DSEP 인프라 담당자" }],
      "status": "NOT_STARTED", "completion_date": null, "origin": "INHERITED"
    }
  ]
}
```

> `is_*_block_start/end` 와 `can_create_*` 를 **서버가 계산해서 내려줌** → 프론트의 경계 판정 로직 중복 제거, §2.3 규칙이 한 곳에만 존재.

---

## 5. 프론트엔드 (Vue3 + TS + Tailwind + antd + ag-grid Community)

### 5.1 구조

```
frontend/src/
├── api/            axios 클라이언트, 타입 정의
├── stores/         Pinia — wpStore, versionStore, masterStore
├── views/
│   ├── WorkPackageBoard.vue     # 메인 그리드
│   ├── MasterDocumentTypes.vue  # 전역 문서 관리
│   └── MasterWpData.vue         # Owner/Phase/Milestone 관리
├── components/grid/
│   ├── WpGrid.vue
│   ├── PhaseCellEditor.vue      # §2.3 드롭다운
│   ├── MilestoneCellEditor.vue
│   ├── MultiSelectCellEditor.vue # 문서/Owner 다중 선택
│   ├── RowActionRenderer.vue     # 행 추가/삭제 버튼
│   └── PhaseCellRenderer.vue     # 블록 첫 행만 라벨 표시
└── composables/    useRenumber.ts (낙관적 재계산), useValidation.ts
```

### 5.2 그리드 컬럼

| 컬럼 | 위젯 | 비고 |
|---|---|---|
| ⠿ | rowDrag | 드래그 핸들 |
| No | 읽기전용 | `sort_order` |
| Phase | PhaseCellEditor | 블록 첫 행만 라벨 표시, 나머지는 흐리게 |
| Milestone | MilestoneCellEditor | 동일 |
| Key Action Item | large text editor | |
| Deliverable | text editor | |
| 관련 문서 | MultiSelect (antd Select) | 전역 document_types |
| Owner | MultiSelect | WP 스코프 owners |
| Status | select | |
| 완료일 | date picker | |
| 작업 | RowActionRenderer | `+` 아래 행추가 / `🗑` 삭제 |

### 5.3 ag-grid Community(무료) 제약 — 확인 필요 항목

| 기능 | 무료 가능 여부 | 대응 |
|---|---|---|
| Managed row drag (`rowDragManaged`) | ✅ Community | 그대로 사용 |
| 커스텀 셀 에디터 / 렌더러 | ✅ Community | 그대로 사용 |
| CSV Export | ✅ Community | 사용 |
| **Row Grouping** | ❌ Enterprise | Phase 그룹핑 대신 **셀 렌더러 + 배경색 밴딩**으로 시각 구분 |
| **Excel Export** | ❌ Enterprise | CSV 또는 백엔드 openpyxl 생성으로 대체 |
| **Context Menu** | ❌ Enterprise | antd Dropdown 으로 자체 구현 |
| **Range Selection / Clipboard 확장** | ❌ Enterprise | 기본 복사만 지원 |
| `colDef.rowSpan` | ⚠️ **구현 시 검증 필요** | row drag 와 충돌 소지 → **미사용 권장**, 렌더러 방식으로 대체 |

> Phase/Milestone 의 시각적 그룹핑은 **rowSpan/grouping 없이**, 블록 첫 행에만 라벨을 렌더하고 Phase 별로 좌측 컬러 바 + 행 배경 밴딩을 적용하는 방식으로 구현한다 (`docs/dashboard.jpg` 의 Phase 색상 체계 재활용).

### 5.4 화면 흐름

```
[WP 선택] → [버전 선택 드롭다운: v2(DRAFT) / v1(PUBLISHED) / ...]
                      │
        ┌─────────────┴──────────────┐
   DRAFT 선택                   PUBLISHED/ARCHIVED 선택
        │                             │
   편집 모드                      읽기 전용 모드
   [임시저장] [발행] [폐기]        [draft 발행] 버튼만
```

- 상단 툴바: 진행률 요약(`전체 35 / Done 0 / 진행률 0%`) — 엑셀 요약행 대체
- 발행 실패 시: antd `notification` 으로 오류 개수 표시 + **해당 셀 빨간 테두리 + 첫 오류 행으로 스크롤**
- 미저장 변경 존재 시 라우트 이탈 경고
- 임시저장은 명시적 버튼 + 30초 자동저장(옵션)

---

## 6. 개발 단계 계획

| 단계 | 산출물 | 비고 |
|---|---|---|
| **0. 계획 확정** | 본 `plan.md` | §7 확인 필요 사항 회신 후 착수 |
| **1. DB 구축** | `db/schema.sql`, `db/seed.sql`, `iai-test` DB 실제 생성 | 엑셀 35행 임포트 → v1 PUBLISHED |
| **2. 백엔드 기반** | FastAPI 프로젝트, ORM 모델, 조회 API | venv(3.11+) 구성 포함 |
| **3. 버전/저장 API** | draft 발행, 임시저장, 행 CRUD | |
| **4. 재계산·검증** | `renumber_service`, `validation_service`, 발행 API | **핵심 로직 — 단위 테스트 필수** |
| **5. 프론트 기반** | Vite + Vue3 + TS + Tailwind + antd, 라우팅, API 클라이언트 | |
| **6. 그리드** | ag-grid 연동, 컬럼, 드래그, 행추가/삭제 | |
| **7. 셀 에디터** | Phase/Milestone 경계 규칙, 다중선택 에디터 | **핵심 UX** |
| **8. 기준정보 화면** | 전역 문서 / WP 스코프 Owner·Phase·Milestone CRUD | |
| **9. 발행 UX** | 검증 오류 하이라이트, 버전 전환, 읽기전용 모드 | |
| **10. 마무리** | 진행률 요약, CSV 내보내기, E2E 점검 | |

**우선순위**: 1 → 2 → 3 → 4 → 5 → 6 → 7 이 임계 경로. 8~10 은 병행 가능.

**테스트 중점**
- `renumber_service`: 행 추가 / 이동 / 삭제 / Phase 경계 이동 / 빈 Phase 발생 시나리오
- `validation_service`: V1~V14 각 규칙별 케이스
- 버전 deep copy 후 원본 불변성

---

## 7. 결정 사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | **WP 와 설비사의 관계** | ~~설비사 1:N WP 단일 계층~~ → **§0 으로 개정 (2026-08-07)**: 중앙 템플릿(버전 관리) → 설비사별 프로젝트(스냅샷 복제, 버전 없음) **2계층**. 설비사 참조는 `wp_projects.maker_id` 정수 + 인덱스만 (물리 FK 없음) |
| 2 | **기존 `dsep_iai` DB** | 신규 `iai-test` 로 재구축. `dsep_iai` 는 **읽기 전용 참고자료로 보존**, 수정하지 않음 |
| 3 | **인증/권한** | **이번 범위 제외.** 호스트 프로젝트가 담당. `created_by` / `published_by` 컬럼만 예약 |
| 4 | **Status / 완료일** | `wp_items` 에 유지. 발행 검증 대상이 아닌 실행 필드로 취급 |
| 5 | **Gate 코드 (G0~G5)** | `wp_items.gate_code` 컬럼으로 보유하되 이번 화면에서는 선택 입력. 발행 필수값 아님 |
| 6 | **DB명** | 요청대로 `` `iai-test` `` 사용. 하이픈 때문에 raw SQL 에서 **항상 백틱** 필요 |

**미확정 (구현 중 재검토)**
- `document_types` 를 호스트의 문서 마스터와 병합할지 — 이식 시점 판단. 리포지토리 한 곳으로 접근을 격리해 교체 비용을 낮춰 둔다 ([`INTEGRATION.md`](INTEGRATION.md) §3)
- 다중 행 선택으로 새 Phase 묶기 (§2.3) — 2차 개발 후보
- 버전 간 diff 표시 (§2.4) — 2차 개발 후보
