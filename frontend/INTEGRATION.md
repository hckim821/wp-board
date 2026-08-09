# Frontend Integration — `wpBoard` remote

루트 [`INTEGRATION.md`](../INTEGRATION.md) §5 의 프론트엔드 구체화 문서.
이 패키지는 **애플리케이션이 아니라 노출 컴포넌트 넷**이다 (`plan.md` §0 개정, §0.5 대시보드, §0.6 설비사 설정).

---

## 1. 노출 표면 (Exposed surface)

| | |
|---|---|
| Remote 이름 | `wpBoard` |
| Entry | `dist-remote/remoteEntry.js` |
| 노출 모듈 | `./MasterAdmin` → `src/entries/masterAdmin.ts`<br>`./ProjectWorkspace` → `src/entries/projectWorkspace.ts`<br>`./ProjectsOverview` → `src/entries/projectsOverview.ts`<br>`./MakerSettings` → `src/entries/makerSettings.ts` |
| 빌드 | `npm run build:remote` (→ `dist-remote/`) |

**넷은 호스트 메뉴의 서로 다른 화면이다** (`plan.md` §0.1, §0.5-3, §0.6-4). 하나를 다른 하나의
탭으로 넣지 말 것 — 소유자도, 권한도, 심지어 `makerId` 의 유무도 다르다.

권장 메뉴 배치는 일상 화면 둘(**전체 현황** 이 기본 진입, **프로젝트**)과 시각적으로 구분된
**관리 그룹** 둘(**Work Package 포맷 관리** = `MasterAdmin`, **Integrated AI 참여 설비사 관리**
= `MakerSettings`)이다. 넷이 한 줄에 평평하게 놓이면 어느 것이 관리자용인지 드러나지 않는다.

| | `./MasterAdmin` | `./ProjectWorkspace` | `./ProjectsOverview` | `./MakerSettings` |
|---|---|---|---|---|
| 메뉴 | Work Package 포맷 관리 | 프로젝트 | 전체 현황 (기본) | Integrated AI 참여 설비사 관리 |
| 소유 | 중앙 (설비사 무관) | 설비사 1곳 | 중앙 (**전 설비사 관망**) | 중앙 (설비사 목록) |
| `makerId` prop | **없다** | **필수** | **없다** | **없다** |
| 쓰기 | O | O | **제한적** — 프로젝트 추가·이름 수정 (§0.6) | 표시 설정만 |
| 버전 관리 | O — draft 발행 / 임시저장 / 발행 / 폐기 | **X** — 생성이 곧 확정, 이후 직접 저장 | 해당 없음 | 해당 없음 |
| 내용 | WP 템플릿 편집 (탭 없음, 화면 하나) | 프로젝트 세부 + 내부 탭 3개 | 설비사 구획 + 미니 대시보드 | 표시 대상 설비사 + 프로젝트 사용 여부 |
| ag-grid | 로드함 | 로드함 | **로드하지 않음** | **로드하지 않음** |

`./MasterAdmin` 에는 **탭 바가 없다.** 화면이 보드 하나뿐이기 때문이다 — Phase·Milestone 은
순서가 곧 번호라 보드 셀에서 여는 **관리 팝업**(§0.4)이 맡고, 문서는 프로젝트 전용 탭이 되었으며
(§0.5.10), **Owner 탭은 제거됐다** (§0.5.9). Owner 선택과 관리는 보드 Owner 셀 팝업
(`components/OwnerManagerModal.vue`)이 한자리에서 한다 — 같은 목록을 편집하는 화면이 둘일
이유가 없다.

프로젝트를 **연 뒤**에는 탭이 셋이다 (`plan.md` §0.5-2b): **대시보드**(기본) · **Work
Package**(그리드) · **문서 등록**. 문서 탭이 프로젝트에만 남은 이유는 그쪽에 *사용 여부·클라우드
링크·작성 상태*가 있어서다 (§0.5-4). 프로젝트를 고르기 전에는 탭 바가 아예 없다 — 셋 중 셋이
아직 없는 프로젝트를 가리키므로, 비활성 탭 줄을 목록 위에 띄우는 것은 소음이다.

`./ProjectsOverview` 는 탭도 툴바도 없다. 그리드가 없으므로 ag-grid 를 아예 import 하지
않는다 — 이 화면만 붙이는 호스트는 1MB 짜리 ag-grid 청크를 내려받지 않는다. 노출을 셋으로
쪼갠 이유가 정확히 이것이다.

```ts
// 호스트 — 기준 데이터 메뉴
import MasterAdmin, { configure } from 'wpBoard/MasterAdmin'
// 호스트 — 프로젝트 메뉴
import ProjectWorkspace from 'wpBoard/ProjectWorkspace'
// 호스트 — 전체 현황 메뉴 (기본 진입)
import ProjectsOverview from 'wpBoard/ProjectsOverview'
// 호스트 — 관리 메뉴
import MakerSettings from 'wpBoard/MakerSettings'

configure({ apiBaseUrl: 'https://intranet.example.com/wp' })
```

```vue
<!-- 기준 데이터 관리: makerId 를 넘길 곳이 없다 -->
<MasterAdmin
  :read-only="!canEditMasterData"
  height="calc(100vh - 120px)"
  @dirty-change="onDirty"
/>

<!-- 설비사 프로젝트 -->
<ProjectWorkspace
  :maker-id="selectedMakerId"
  :maker-name="selectedMakerName"
  :read-only="!canEditProjects"
  height="calc(100vh - 120px)"
  @dirty-change="onDirty"
/>

<!--
  전체 현황: makerId 가 없다. 행 클릭은 콜백으로 되돌아오며, 어디로 보낼지는 호스트가 정한다.
  콜백을 주지 않으면 행은 클릭 불가로 렌더된다 — 이 패키지는 목적지를 지어내지 않는다.
-->
<ProjectsOverview
  :on-open-project="(projectId, makerId) => router.push({
    name: 'wp-project', params: { makerId }, query: { project: projectId },
  })"
  height="calc(100vh - 120px)"
/>
```

각 entry 가 내보내는 것 이외는 전부 내부 구현이며 예고 없이 바뀔 수 있다.
타입 선언은 [`types/wpBoard.d.ts`](types/wpBoard.d.ts) 참조.

> **왜 entry 가 둘인가.** 한 배럴(`src/index.ts`)을 두 이름으로 노출하면 프로젝트 화면만 쓰는
> 호스트도 관리 화면 코드를 통째로 내려받는다. `src/index.ts` 는 로컬 개발 편의용으로 남아
> 있을 뿐 **노출되지 않는다.**

### Props — 공통

| Prop | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `readOnly` | `boolean` | `false` | 호스트 권한 게이트. **`draft 발행` 을 포함한 모든 쓰기 액션이 사라진다.** `./ProjectsOverview` 에는 없다 — 애초에 쓰기가 없다 |
| `apiBaseUrl` | `string` | `configure()` 값 | `/api/v1/...` 가 뒤에 붙는다 |
| `authToken` | `string \| (() => string \| null \| Promise<string \| null>)` | `null` | 함수를 주면 매 요청마다 호출 |
| `headers` | `Record<string, string>` | `{}` | 전 요청에 병합 |
| `requestTimeoutMs` | `number` | `30000` | |
| `withCredentials` | `boolean` | `false` | |
| `dataSource` | `WpApiClient` | `null` | 자체 transport 주입용 탈출구 |
| `navigate` | `(target, params?) => void` | `null` | 호스트 라우팅 위임 |
| `warnOnUnload` | `boolean` | `true` | 미저장 변경이 있을 때 탭 종료 경고 |
| `height` | `string` | `'100%'` | |

`./ProjectsOverview` 는 위 표에서 `readOnly` · `navigate` · `warnOnUnload` 를 갖지 않는다.

### Props — `./ProjectWorkspace` 전용

| Prop | 타입 | 기본값 | 설명 |
|---|---|---|---|
| **`makerId`** | `number \| string` | — | **필수.** 호스트 설비사 PK. 이 모듈은 설비사 목록/조회 API 를 갖지 않는다 (§2) |
| **`projectId`** | `number \| null` | — | **필수** (null 허용). 열 프로젝트. `null` 이면 "전체 현황에서 프로젝트를 선택하세요" 안내만 렌더한다 — **첫 프로젝트를 대신 열지 않는다** |
| `makerName` | `string \| null` | `null` | 표시 전용. 아래 3단 폴백 |

`workPackageId` prop 은 **없어졌다.** 템플릿 선택은 관리 화면의 툴바가 담당한다.

**설비사 표시명은 3단으로 떨어진다** (2026-08-09). 대시보드 제목과 Work Package 툴바가
같은 규칙을 쓴다 — 두 제목이 다른 이름을 내면 안 되기 때문이다.

1. `makerName` prop — 호스트가 직접 준 이름.
2. `project.maker_name` — 서버가 **호스트의 `MakerResolver`** 를 거쳐 실어 보낸 이름. 전달
   경로만 다를 뿐 출처는 똑같이 호스트다. resolver 를 주입했다면 prop 을 주지 않아도 된다.
3. `설비사 #<id>` — 위 둘이 다 없을 때만. 즉 **resolver 도 prop 도 없는 설치**에서만 보인다.

> ⚠️ `makerName`(과 `makerId`)은 **마운트된 보드에서 바꿔도 반영된다.** 예전에는 셸이
> `provide()` 시점의 값을 스냅샷으로 잡아 두어, 이름을 비동기로 해석해 나중에 내려주는
> 호스트는 영영 갱신되지 않았다 — 증상은 멀쩡히 이름이 있는 설비사 옆에 `설비사 #1` 이
> 찍히는 것이었다. 지금은 getter 로 넘긴다.

**프로젝트 목록 화면도 없어졌다** (`plan.md` §0.6-4). 진입은 전체 현황의 `onOpenProject` **하나
뿐**이며, 그래서 `projectId` 가 필수 prop 이다. 모듈 안에 목록을 남겨 두면 호스트가 준 진입점을
우회하는 두 번째 경로가 계속 살아 있게 된다. 프로젝트 생성도 전체 현황의 모달로 옮겨졌다.

Work Package 탭 헤더에는 원본 **포맷 이름과 발행 버전**(`v2`)이 함께 표시된다. 서버가
`source_version_number` 를 주지 않으면 버전 표기는 생략한다.

프로젝트 내부는 **탭 3개**다 (`plan.md` §0.5-2b, 2026-08-08 개정 — 이전의 보드↔대시보드
라디오 토글을 대체한다). 호스트가 붙일 것은 없다 — prop 도 이벤트도 없다. 계약상 알아둘 점 셋:

* **활성 화면만 마운트된다.** `v-show` 가 아니라 `v-if` 라, 다른 탭으로 가면 ag-grid 는
  파괴된다. 한 호스트 안에 살아 있는 그리드 인스턴스는 언제나 최대 하나다.
* **대시보드가 기본 탭**이고, 프로젝트를 닫았다 다시 열면 다시 대시보드로 돌아온다.
  대시보드는 이미 불러온 행만 그리므로 추가 요청이 없다.
* **Work Package 를 떠날 때만** 미저장 확인을 묻는다. 편집 내용은 어느 쪽이든 유지되지만
  (스토어가 들고 있고 돌아와서 저장하면 된다), 편집 중이던 그리드가 사라지는 것은 폐기처럼
  보이기 때문이다.

`readOnly` 는 세 탭 모두에 전파된다. Owner 편집은 이제 보드 Owner 셀 팝업 하나뿐이고, 그쪽은
`hostReadOnly` 가 아니라 **`readOnly`** 를 따른다 (§0.5.9) — 보드 셀에서 열리므로 그 보드의
편집 가능 여부를 물려받는다. 잠긴 보드에서 열리는 쓰기 화면은 있으면 안 된다.

### Props — `./MakerSettings` 전용

`makerId` 도 `onOpenProject` 도 없다. 공통 props 중 `readOnly` 만 의미가 있으며, 켜면 목록은
그대로 보이되 **모든 스위치**가 비활성화되고 `저장` 이 사라진다.

인스턴스 메서드는 `reload()` 와 `hasUnsavedChanges()` 다. **후자는 진짜로 변할 수 있다** —
스위치만 만지고 저장하지 않은 상태가 존재하므로, 호스트 라우터 가드에 연결할 것.

화면 형태는 **전체 현황과 같은 카드**다 (`plan.md` §0.6.1): 옅은 배경 위 흰 카드, 설비사마다
접기/펼치기(기본 펼침), 하위 프로젝트는 들여쓰기. 표 한 장이던 이전 판은 설비사 밑에
프로젝트가 딸리면서 무너졌다. 호스트가 붙일 것은 없다 — 높이만 `height` 로 준다.

#### 프로젝트 사용 여부 스위치

설비사 카드 안에 그 설비사의 프로젝트를 나열하고 각 프로젝트에 on/off 스위치를 둔다
(`wp_projects.is_active`). **off 는 전체 현황에서 감추기이지 삭제가 아니다** — 항목·상태·
완료일은 남고 다시 켜면 그대로 돌아온다. 설비사의 전체현황 표시 스위치와 **같은 저장 버튼**을
쓰며, `PUT /makers/settings` 한 번에 `settings` 와 `projects` 두 배열로 실려 **한 트랜잭션**으로
반영된다. 두 배열이 나뉘어 있는 이유는 규칙이 달라서다: 모르는 `maker_id` 는 허용(설비사는
호스트 것이고 resolver 미주입이 정상 상태), 모르는 프로젝트 id 는 **422**.

이 화면의 목록에는 **꺼진 프로젝트도 들어 있다.** `GET /makers` 의 `projects` 는 활성으로
거르지 않는다 — 거르면 스위치를 끄는 순간 다시 켤 화면이 사라져 off 가 편도 조작이 된다.
같은 이유로 프로젝트를 전부 꺼 둔 설비사도 표에 남는다(그 설비사의 전체 현황 표시는 여전히
꺼진다 — 표시 규칙은 §0.6-1 그대로 **활성** 기준이다).

> 호스트가 알아둘 것: **UI 에는 실제 삭제가 없고 API 에도 없다.** DB 에서 지우는 경로는
> 관리자가 직접 실행하는 `db/delete_project.py` 뿐이다 (루트 `README.md` §5.2).

### Props — `./ProjectsOverview` 전용

| Prop | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `onOpenProject` | `(projectId: number, makerId: number) => void` | `null` | **호스트 라우팅.** 행의 **이동 아이콘** 클릭 시 호출. 보통 `ProjectWorkspace` 를 그 `makerId` 로 띄우는 호스트 화면으로 보낸다 |
| `readOnly` | `boolean` | `false` | 프로젝트 추가 · 이름 수정 · 설비사 설정을 모두 withdraw (§0.6). 조회와 이동은 그대로 남는다 |

`onOpenProject` 를 주지 않으면 **이동 아이콘 자체가 렌더되지 않는다.** 기본 목적지 같은 것은
없다 — 이 패키지에는 라우터가 없고, 라우팅은 호스트 소유다.

**URL 은 호스트가 소유한다.** 이 모듈은 URL 을 읽지도 쓰지도 않는다 (`plan.md` §0.6-4). 권장
경로는 전체 현황 아래 `/{projectId}` 이며 — 예: `/wp` → `ProjectsOverview`, `/wp/:projectId` →
`ProjectWorkspace` — `onOpenProject(projectId, makerId)` 를 받은 호스트가 그 경로로 push 하고,
딥링크·새로고침에서는 `GET /api/v1/projects/{pid}` 의 `maker_id` 로 `makerId` prop 을 해석해
마운트한다. 뒤로 가기는 호스트의 `popstate` 몫이다. `src/dev/DevHarness.vue` 가 이 배선을
그대로 구현하고 있으니 참고할 것 — 하니스는 호스트 역할이고, 그래서 이 코드가 모듈이 아니라
거기 있다는 사실 자체가 계약의 증명이다.

이 화면은 §0.6 이후 **프로젝트 허브**다: 설비사 섹션 접기/펼치기(기본 펼침), 섹션마다
`＋ 프로젝트 추가`, 프로젝트명 인라인 수정. 설비사 설정은 여기 **없다** — `./MakerSettings`
라는 별도 노출이 됐다. 다른 화면을 먼저 열어야만 닿는 관리 화면은 호스트가 메뉴에 놓을 수도,
따로 권한을 걸 수도, 링크할 수도 없기 때문이다.

이름 수정은 **이름 텍스트 클릭**으로 들어간다 (연필 아이콘은 제거됐다 — 이동은 이동 아이콘
전담이라 이름 클릭이 비어 있었고, 실제 편집 진입점이 옆의 14px 글리프에 숨어 있었다). Enter
저장 · Esc 취소 · blur 저장이며, hover 시 점선 밑줄로 편집 가능함을 알린다. `readOnly` 면 이름
클릭은 무동작이고 밑줄·커서 힌트도 나오지 않는다. 새 기능은 여기에만 넣는다 — `프로젝트` 메뉴의 목록 페이지는 **추후 제거
예정**이다 (`plan.md` §0.6-4).

인스턴스 메서드는 `reload()` 와 `hasUnsavedChanges()`(항상 `false` — 편집은 즉시 저장된다)
둘뿐이다.

### Events / 인스턴스 메서드 — 양쪽 동일

| | |
|---|---|
| `@ready` | 최초 로드 완료 |
| `@dirty-change(dirty: boolean)` | 미저장 변경 상태 변화 |
| `hasUnsavedChanges(): boolean` | **라우트 가드에서 이걸 호출하라.** 이 패키지는 `vue-router` 를 import 하지 않는다 |
| `save(): Promise<boolean>` | 저장 강제 실행 (템플릿=임시저장, 프로젝트=직접 저장) |
| `reload(): Promise<void>` | 현재 버전/프로젝트 재조회 |

**두 화면 모두 미저장 변경을 만들 수 있다.** 관리 화면은 DRAFT 편집으로, 프로젝트 화면은
셀 편집으로 — 프로젝트는 발행이 없어 "임시" 상태가 아예 없지만, 저장 버튼을 누르기 전까지는
똑같이 미저장이다. 따라서 **가드는 두 화면 모두에 걸어야 한다.**

```ts
// 호스트 라우터 가드 예시 — 어느 쪽 ref 든 같은 인터페이스다
router.beforeEach((to, from, next) => {
  const screen = masterRef.value ?? projectRef.value
  if (screen?.hasUnsavedChanges() && !confirm('저장하지 않은 변경이 있습니다. 이동할까요?')) {
    return next(false)
  }
  next()
})
```

---

## 2. 설비사(Maker) — 이 모듈은 관여하지 않는다

루트 [`INTEGRATION.md`](../INTEGRATION.md) §2.4 확정 사항.

- 설비사 목록/이름 조회 API 가 **이 모듈에 없다.** grep 해도 나오지 않는다.
- `makerId` 는 **불투명(opaque) 값**이다. 타입이 `number | string` 인 이유는 호스트가
  `BIGINT` 든 `UUID` 든 쓸 수 있기 때문이며, 이 모듈은 API 쿼리 파라미터로 그대로 흘려보내기만 한다.
- 설비사 선택 UI 는 **호스트의 화면**이다. `src/dev/DevHarness.vue` 가 그 역할을 흉내 내며,
  설비사 목록이 모듈 바깥에 있다는 점을 그대로 보여준다.
- **설비사 개념은 `./ProjectWorkspace` 에만 있다.** `./MasterAdmin` 은 `makerId` prop 자체가
  없다 — 템플릿은 중앙 소유이고 설비사와 무관하다 (`plan.md` §0.1). 관리 화면에 설비사를
  넘길 방법이 없다는 것이 그 사실의 기계적 보장이다.
- 템플릿 선택은 관리 화면 툴바가, 프로젝트 선택은 프로젝트 목록이 담당한다. 둘 다 이 모듈 소유다.

---

## 3. 스타일 격리 (가장 중요한 항목)

페더레이션 remote 가 호스트를 망가뜨리는 가장 흔한 경로가 전역 CSS 다. 방어선은 네 겹이다.

1. **`corePlugins.preflight: false`** — Tailwind 의 전역 element reset 미사용.
2. **`prefix: 'wp-'`** — 모든 유틸리티가 `wp-flex`, `wp-text-xs` 형태. 호스트가 Tailwind 를
   쓰더라도 규칙이 충돌하지 않는다.
> ⚠️ **preflight 를 끈 대가**: 브라우저 기본 `border-style` 은 `none` 이라, preflight 없이는
> `wp-border`/`wp-border-b` 같은 **두께만 주는 유틸리티가 아무것도 그리지 않는다.** 실선이
> 필요한 곳은 반드시 `wp-border-solid` 를 함께 붙인다 (`styles/tailwind.css` 주석).
> 2026-08-08 대시보드의 진행전 셀이 투명했던 원인이 이것이고, 색만 확인하던 단언은 그때
> 통과했다 — `borderColor` 는 style 이 `none` 이어도 그대로 읽히기 때문이다. 지금은
> `check:dom` 이 마운트된 트리 전체에서 이 짝을 감사하고, 스타일시트 수준에서도 두 경우를
> 직접 잰다.

3. **`@tailwind base` 미사용** — preflight 를 꺼도 base 레이어는
   `*, ::before, ::after { --tw-*: … }` 라는 **전역 셀렉터**를 내보낸다. 같은 변수 기본값을
   `src/styles/tailwind.css` 에서 `.wp-root` 하위로 한정해 직접 선언한다.
4. **antd 전역 reset 미import** — `ant-design-vue/dist/reset.css` 를 부르지 않는다. v4 는
   cssinjs 로 컴포넌트별 스타일을 런타임 주입하므로 전역 오염이 없다.
   `ConfigProvider` 는 노출 컴포넌트 내부에만 존재하고, `message`/`notification` 도
   전역 static 대신 `App.useApp()` 컨텍스트 인스턴스를 쓴다 (static 은 호스트와 공유되는
   싱글턴을 건드린다).

빌드 산출 CSS 는 검증 가능하다 — `dist-remote/assets/style-*.css` 의 모든 셀렉터가
`.wp-` 로 시작한다(예외는 `@keyframes wp-row-flash` 뿐).

```bash
tr '}' '\n' < dist-remote/assets/style-*.css | grep -oE '^[^{]+' | grep -vE '^\.(wp-|hover)'
```

antd 팝업은 `document.body` 가 아니라 **`.wp-root` 안으로 portal** 된다
(`ConfigProvider :get-popup-container`). 우리 스타일이 닿는 영역 안에 머무르게 하기 위함이다.

**ag-grid** 는 v33 Theming API 를 쓴다 — 테마가 JS 객체(`src/theme/agTheme.ts`)이므로
`ag-grid.css` / `ag-theme-*.css` 전역 스타일시트 import 가 아예 없다.

---

## 4. 런타임 설정 — `import.meta.env` 를 쓰지 않는 이유

Vite 는 `import.meta.env` 를 **빌드 시점에 인라인**한다. 모듈 스코프에서 읽으면 개발용 값이
호스트가 내려받는 번들에 그대로 박힌다. 따라서 API base URL·토큰은 전부 런타임 경로다.

우선순위: **props > `configure()` > 내장 기본값**

`configure()` 가 쓰는 `hostDefaults` 는 이 패키지의 **유일한 모듈 스코프 상태**이며,
호스트가 한 번 설정하는 구성값일 뿐 보드 상태가 아니다. 인스턴스별 props 가 항상 이긴다 —
서로 다른 백엔드를 보는 보드 두 개를 동시에 띄울 수 있다.

예외는 `src/dev/**` 하나뿐이다. 이 디렉터리는 배포되지 않으므로 `import.meta.env` 를 쓴다.

---

## 5. 인스턴스 격리 / 마운트 생명주기

- **Pinia 미사용.** 루트 `INTEGRATION.md` §5 는 "호스트의 활성 Pinia 에 의존하지 않는다 /
  모듈 스코프 가변 상태를 두지 않는다" 를 요구한다. Pinia 로 이를 만족시키려면 인스턴스별
  `createPinia()` 를 만들어 스토어 호출마다 넘겨야 하는데, 그럴 바에는 의존성을 없애는 편이
  낫다. 대신 `createBoardStore()` / `createMasterStore()` **팩토리**를 노출 컴포넌트에서
  인스턴스마다 만들고 `provide()` 로 내려준다 (`src/runtime/context.ts`).
  → `plan.md` §5.1 의 "stores/ Pinia" 에서 의도적으로 벗어난 부분.
- 스토어 옵션(`makerId`, `readOnly`)은 **값이 아니라 getter** 로 받는다. 호스트가 마운트된
  보드의 prop 을 바꿔도(설비사 전환, 권한 회수) 반영된다.
- `createBoardStore` 는 `tier: 'template' | 'project'` 하나로 두 계층을 모두 돌린다. 그리드
  동작(재계산·경계·드래그·회색 행)은 양쪽이 **같아야** 하므로 구현이 하나여야 하고, 다른 것은
  버전 기계장치뿐이라 그 차이는 툴바와 두 개의 배너에만 있다.
- `vue-router` import 없음. `navigate` prop 과 `hasUnsavedChanges()` 로 위임.
- **자동저장은 없다** (`plan.md` §0.5.8). 30초 주기 `setInterval` 이 있었고 제거됐다 — 저장은
  수동 버튼(템플릿 임시저장 / 프로젝트 저장)뿐이다. **유지되는 것**: dirty 추적, 탭 전환·언마운트
  시 미저장 확인, `hasUnsavedChanges()` 노출. 없앤 것은 타이머뿐이다.
- 타이머·리스너 정리: 오류 행 flash `setTimeout`, `beforeunload` 리스너를 `onBeforeUnmount`
  에서 해제한다. `check:dom` 은 보드를 띄운 뒤 **주기 타이머가 0개**임을 확인하며, 그 부정
  단언이 계측 고장으로 통과하지 않도록 직접 만든 인터벌로 계측이 살아 있음을 먼저 증명한다.
- ag-grid 모듈 등록은 **import 시점이 아니라 `onMounted`** 에서 1회 수행
  (`ensureAgGridModules()`).
- 보드 ↔ 대시보드 전환은 `v-if` **교체**다 (`plan.md` §0.5-2). 그리드를 숨기는 것이 아니라
  언마운트하므로 한 화면에 살아 있는 ag-grid 인스턴스는 언제나 최대 하나다.
- `ProjectsOverview` 는 마운트 시 요청 하나를 던지고, 응답 전에 언마운트되면 그 응답을
  버린다(`live` 플래그). 반복 마운트/언마운트가 요구사항이므로 늦게 도착한 응답이 사라진
  컴포넌트의 ref 를 건드리지 않게 한다.
- 마운트 → 언마운트 → 재마운트, 그리고 2개 동시 마운트를 `npm run check:dom` 이 실제로 검증한다
  (세 노출 전부).

---

## 6. Federation singletons

`vite.config.ts` 의 `shared` 선언. 호스트 버전이 범위를 벗어나면 사본이 두 개 로드되어
**inject 실패(Vue) / 모듈 레지스트리 분리(ag-grid)** 가 발생한다.

| 패키지 | 요구 범위 | 두 벌이면 생기는 일 |
|---|---|---|
| `vue` | `^3.5.41` | provide/inject 단절, reactivity 분리 |
| `ant-design-vue` | `^4.2.6` | 테마 컨텍스트 분리 |
| `ag-grid-community` | `33.3.2` (고정) | `ModuleRegistry` 가 둘로 갈려 그리드가 비어 뜬다 |
| `ag-grid-vue3` | `33.3.2` (고정) | ag-grid-community 와 버전이 일치해야 한다 |
| `dayjs` | `^1.11.13` | DatePicker 로케일 불일치 |

ag-grid 두 패키지는 **정확히 같은 버전**이어야 하므로 캐럿 없이 고정한다.

---

## 7. 백엔드 계약 — `plan.md` §4.2 (team-lead 승인본)

프론트는 아래 엔드포인트만 호출한다.

### 7.0 두 계층, 하나의 행 조작 (`plan.md` §0, §4.2)

URL 이 두 갈래다. **행 조작의 모양은 양쪽이 똑같고, 앞부분만 다르다.**

```
템플릿(기준 데이터)   /api/v1/templates/{tid}/...     /api/v1/versions/{vid}/items/...
프로젝트(설비사)      /api/v1/projects/{pid}/...      /api/v1/projects/{pid}/items/...
```

클라이언트는 이것을 `BoardScope` 하나로 표현한다:

```ts
type BoardScope =
  | { kind: 'template'; templateId: number; versionId: number }
  | { kind: 'project'; projectId: number }
```

`itemsBase(scope)` 가 행 URL 을, `masterBase(scope)` 가 기준정보 URL 을 만든다. 둘이 다른
이유는 **템플릿의 phase/milestone/owner 는 버전이 아니라 템플릿에 속하기** 때문이다 — 버전으로
키를 잡으면 DRAFT 마다 Phase 목록이 따로 생긴다.

프로젝트 전용:

```jsonc
GET    /api/v1/projects?maker_id=7
POST   /api/v1/projects        { "maker_id": 7, "name": "...", "template_id": 3 }   // 발행본 deep copy
GET    /api/v1/projects/{pid}
PUT    /api/v1/projects/{pid}/items    { "items": [...] }   // 무검증 전량 교체
DELETE /api/v1/projects/{pid}                               // 비활성화

GET    /api/v1/projects/overview                            // 전체 현황 (§7.6) — maker 무관
```

> ⚠️ **라우트 순서**: `/projects/overview` 는 `/projects/{pid}` 보다 **먼저** 선언되어야 한다.
> 뒤에 두면 `overview` 가 `pid` 로 잡혀 422 가 난다. 서버 쪽 함정이지만 자체 transport 를
> 만드는 호스트도 같은 순서를 지켜야 한다.

**프로젝트에는 버전 API 가 아예 없다.** `validate` / `publish` / `draft` / `discard` 는 버전
id 를 받으므로 프로젝트 id 로는 호출조차 되지 않는다 — UI 에서 감춘 것이 아니라 연산이 없다.
`POST /projects` 는 **발행된** 템플릿 버전만 받는다 (DRAFT 지정 시 422).

### 7.1 행 조작 — 위치와 소속은 별개의 엔드포인트다

아래는 템플릿 쪽 URL 로 적었지만, `/versions/{vid}` 를 `/projects/{pid}` 로 바꾸면 그대로
프로젝트 쪽이다.

```jsonc
// 드래그 이동 — 위치만. 소속도, `moved_item_id` 도 받지 않는다.
POST  /api/v1/versions/{vid}/items/reorder
{ "item_ids": [12, 3, 7, ...] }

// §2.3 셀 편집 — 소속만. 서버가 행을 재배치하고 연속성을 검증한다.
PATCH /api/v1/versions/{vid}/items/{iid}/membership
{ "phase_id": 2, "milestone_id": 5 }

// §2.3 생성 — 기준 행은 경로에, 위치 인자는 없다. create + assign + renumber 가 한 트랜잭션.
// 프로젝트 쪽에서 부르면 **프로젝트 로컬** Phase 가 생긴다. 중앙 템플릿은 그대로다.
POST  /api/v1/versions/{vid}/items/{iid}/create-phase       { "name": "..." }
POST  /api/v1/versions/{vid}/items/{iid}/create-milestone   { "name": "..." }

// 미배정(회색) 행 추가 — 맨 끝 / 특정 행 아래. 둘 다 아무것도 상속하지 않는다 (§0.2)
POST  /api/v1/versions/{vid}/items
POST  /api/v1/versions/{vid}/items/{iid}/insert-below

// §0.4 Phase/Milestone 관리 팝업 — 팝업 전체를 한 번에. 응답은 items + phases + milestones
POST  /api/v1/versions/{vid}/phases/apply
POST  /api/v1/versions/{vid}/phases/{phase_id}/milestones/apply
```

> ⚠️ apply 두 개는 `masterBase` 가 아니라 **`itemsBase`** 를 쓴다 — 템플릿에서도
> `/templates/{tid}` 가 아니라 `/versions/{vid}` 다. 이 호출은 기준정보뿐 아니라 **행까지
> 다시 배열**하고, 행은 버전에 속하기 때문이다. `createHttpApiClient` 가 그렇게 만든다.

### 7.1.3 `phases/apply` — 순서가 곧 번호다 (`plan.md` §0.4)

```jsonc
POST /api/v1/versions/{vid}/phases/apply
{
  "phases": [                                     // 위→아래 = 새 블록 순서
    { "id": 5, "name": "Initiation & Readiness" },// 기존 (이름 변경 반영)
    { "id": null, "name": "새 단계" },             // 신규
    { "id": 7, "name": "Evaluation" }
  ],
  "deleted_ids": [6],                             // 명시적 삭제
  "anchor_item_id": 123                           // (선택) 신규 1개를 이 회색 행으로 만든다
}
```

계약에서 놓치기 쉬운 것 다섯:

1. **"기존 전체 집합" 은 기준정보 테이블이 아니라 _보드에 행이 있는_ Phase 다** (first-appearance
   순). 요청은 diff 가 아니라 최종 상태이고, `phases` + `deleted_ids` 가 그 집합과 정확히
   일치하지 않으면 **422 `APPLY_SET_MISMATCH`**. 빠뜨린 id 를 "삭제"로 읽지 않기 위한 규칙이다.
   행이 하나도 없는 Phase 는 애초에 번호가 없으므로 팝업에 뜨지도, 페이로드에 실리지도 않고,
   apply 는 그런 항목을 건드리지 않는다.
2. **번호를 보내지 않는다.** 배열 순서가 블록 순서가 되고, first-appearance 재계산(§2.2)이
   거기서 번호를 파생한다. 0 과 1 사이에 새 Phase 를 넣으면 기존 1 은 2 가 되고 그 하위
   마일스톤 표시번호까지 전부 따라 바뀐다 — 클라이언트는 그 사실을 알 필요가 없다.
3. **행 없는 Phase 는 만들 수 없다.** `anchor_item_id` 가 있으면 그 행이 신규 항목의
   첫 행이 되고(따라서 신규 항목은 **정확히 1개**여야 한다), 없으면 서버가 빈 행 1개를 만들어
   붙인다.
   - `phases/apply` 의 앵커: **완전 미배정(회색) 행**.
   - `milestones/apply` 의 앵커: `milestone_id == null` 이고 phase 가 **null 이거나 대상
     phase** 인 행. 후자만 허용하면 "phase 만 배정된 행에서 새 Milestone" (§0.3) 은 되지만
     회색 행에서 곧장 만드는 길이 막힌다. 회색 행이 앵커면 phase 와 신규 milestone 을 **함께**
     받고 그 phase 블록 안으로 이동한다.
4. **삭제는 캐스케이드다.** 그 Phase 의 모든 행과 하위 Milestone 이 함께 사라진다. §2.6 의
   "사용 중이면 비활성화" 규칙은 **보드 스코프 Phase/Milestone 에는 적용되지 않는다** — 이
   둘은 재사용 기준정보가 아니라 보드 구조다. Owner·문서는 종전대로 비활성화된다.
   (기준정보 행 자체는 다른 버전이 쓰고 있으면 서버가 비활성화로 처리한다. 보드에서 사라지는
   결과는 같으므로 `src/mock` 은 그냥 제거한다.)
5. **삭제되는 블록에 붙어 있던 회색 행은 삭제되지 않는다.** 앞쪽 생존 블록에 다시 붙고, 앞에
   생존 블록이 없으면 최상단에 남는다. 그래서 팝업의 **"하위 N개" 경고에 회색 행은 세지
   않는다** — 사라지지 않는 것을 사라진다고 예고하지 않기 위해서다.

**재배열 시 회색 행**: 미배정 행은 **직전 배정 행에 붙어 함께 이동**한다. 보드 최상단의 선행
회색 행들은 최상단에 남는다. Milestone apply 도 같은 규칙이며, 대상 Phase 블록 **바깥은
건드리지 않는다.**

`milestones/apply` 는 `"milestones"` 키만 다르고 형태가 같다. 대상 Phase 는 URL 에 온다.

**422 코드** (`detail.code`):

| 코드 | 언제 |
|---|---|
| `APPLY_SET_MISMATCH` | 유지+삭제가 기존 집합과 불일치. `detail` 에 `missing` / `unknown` / `expected` 동봉 |
| `APPLY_DUPLICATE_ID` | 같은 id 가 두 번, 또는 유지와 삭제에 동시 지정 |
| `APPLY_OUT_OF_SCOPE` | 이 보드에 행이 없는 id, 다른 스코프/계층의 id, 또는 URL 의 phase_id 가 이 보드 것이 아님 |
| `APPLY_EMPTY_NAME` | 이름이 공백 |
| `APPLY_DUPLICATE_NAME` | 이름 중복 |
| `APPLY_ANCHOR_INVALID` | 앵커 행이 조건에 안 맞거나, 앵커가 있는데 신규 항목이 1개가 아님 |
| `APPLY_BOARD_NOT_CONTIGUOUS` | 결과 보드가 조각남 (`detail.breaks`) |

비-DRAFT 템플릿 버전은 기존 관문 그대로 **409** 다 (422 아님).

### 7.0.1 미배정(회색) 행 — `plan.md` §0.2

행 추가 두 경로가 **모두** `phase_id`/`milestone_id` 가 null 인 행을 만든다. 상속은 폐기됐다.

- **연속성 검사에서 null 행은 투명하다.** `P0 P0 [회색] P0` 은 위반이 아니다. 경계 플래그와
  드래그 규칙도 같은 방식으로 회색 행을 건너뛰어 읽는다 — 셋 중 하나만 불투명하게 읽으면
  UI 가 서버가 거부할 동작을 제안하게 된다.
- **회색 행은 어디로든 드래그 가능**하고, 배정된 행은 여전히 자기 블록 안으로 제한된다.
  이 비대칭이 "기존 Phase 사이에 새 Phase 넣기"를 가능하게 하는 유일한 장치다:
  회색 행 추가 → 경계로 끌기 → `create-phase` → first-appearance 재계산이 그 사이 번호를 준다.
- **`can_create_phase` 는 서버가 계속 계산하지만 UI 는 더 이상 읽지 않는다** (§0.4).
  §0.2.4 의 "위·아래 이웃의 Phase 가 달라야 생성 가능" 제약은 **폐기됐다** — `+ 새 Phase 생성`
  이 이제 아무것도 만들지 않고 **관리 팝업을 열기** 때문이다. 위치를 팝업에서 명시하므로
  "블록 한가운데에서 만들면 쪼개진다"는 상황 자체가 생기지 않는다. 플래그는 페이로드에 계속
  실려 오고(`WpItem`), `create-phase` 엔드포인트도 계약 유지 차원에서 그 규칙을 계속 강제한다.
  클라이언트가 서버 규칙을 가져간 것이 아니라, 그 규칙이 이 경로에 더는 적용되지 않는다.
- 회색 행은 저장에 아무 문제가 없고, **템플릿 발행 시에만** V1/V2 가 셀 좌표와 함께 잡는다.
  프로젝트에는 발행이 없으므로 회색인 채로 남아도 된다.

**왜 나뉘어 있는가.** 하나의 엔드포인트가 `{entries[], moved_item_id?}` 로 둘을 겸하면
**안전한 경로가 선택적 필드에 의존**하게 된다. 호스트 쪽 클라이언트가 `moved_item_id` 를
빠뜨리는 순간 조용히 "클라이언트가 소속을 지정하는" 경로로 떨어진다. 기본값이 안전하지 않은
쪽으로 뒤집히는 것은 이 저장소가 피하려는 결함 유형 그 자체다.

`reorder` 는 소속을 받지도, 재유도하지도 않는다 — **각 행은 자기 `phase_id`/`milestone_id`
를 그대로 들고 자리만 바꾼다** (`plan.md` §2.2, 2026-08-07 개정). 소속 변경은
`PATCH membership` 한 곳으로 모이고, 거기서 서버가 재배치·검증한다 (422 시 무저장).

> ⚠️ **"소속을 안 받으니 드래그는 잘못된 보드를 만들 수 없다"는 서술은 삭제되었다.** 행이
> 이미 소속을 들고 있으므로 두 블록을 교차시키는 순열은 여전히 블록을 조각낸다. `reorder`
> 의 연속성 검사는 이중 안전장치가 아니라 **주 방어선**이다. 그리고 연속성만으로는 부족하다:
> `[A/Phase0, B/Phase1]` 에서 A 를 맨 뒤로 보내면 보드는 연속인 채로 **Phase 번호만 조용히
> 뒤바뀐다.** 서버는 그것을 재정렬과 구분할 수 없으므로, **드래그를 자기 Phase·Milestone
> 블록 안으로 제한하는 것은 그리드의 책임**이다 (`src/composables/useBlockDrag.ts`).
> 호스트가 `dataSource` 로 직접 `reorder` 를 호출한다면 그 제한도 직접 져야 한다.

**생성이 원자적이어야 하는 이유**: 이전 구현은 기준정보 `POST .../phases` 뒤에 순서 변경을
따로 호출했는데, 그 사이에 실패하면 **기준정보에 고아 Phase 가 남는다.** 전용 엔드포인트는
한 트랜잭션이므로 그 상태가 생기지 않는다.

**스코프 교차 참조는 400 이다.** 프로젝트의 phase/milestone/owner 는 생성 시점에 만들어진
**복사본**이라 id 가 템플릿 쪽과 다르다. 템플릿의 phase_id 를 프로젝트 행에 쓰려고 하면
`INVALID_REFERENCE` 로 거부된다 — 두 계층을 하나의 클라이언트가 오가는 이상, 이건 이론적
위험이 아니라 캐시 하나만 잘못 살아 있어도 나는 사고다.

### 7.1.1 경계 플래그는 절대 클라이언트에서 계산하지 않는다

`can_create_phase` / `can_create_milestone` 는 §2.3 의 **권한(authorization)** 이며 서버만 계산한다.
이 패키지에는 그 규칙의 구현이 **없다** — `grep can_create_phase: src/` 는 `src/mock`(서버 대역)
과 타입 선언 외에는 잡히지 않는다.

낙관적 재계산은 **표시값에만** 적용한다 (`useRenumber.ts`: `sort_order`/`row_no`/번호/블록 첫·끝행).
이것들은 화면용이고 서버 응답이 오면 자동으로 교정된다. 반면 플래그를 추측하면 규칙이 두 벌이 되어
서로 어긋날 수 있고, 사용자가 마주치는 쪽은 클라이언트 사본이다.

→ 낙관적 페인트 직후에는 `BoardStore.flagsStale` 이 선다. 예전에는 이 동안 셀 에디터가
`새 Phase 생성` 을 비활성화했는데, **§0.4 이후로는 그럴 필요가 없다** — 그 버튼은 이제 요청을
보내지 않고 관리 팝업을 열 뿐이라 플래그가 낡았는지와 무관하다. `flagsStale` 은 계속 서고,
낙관적 페인트가 신뢰할 수 없는 상태임을 나타내는 신호로 남아 있다.

소속도 마찬가지로 추측하지 않는다. 드래그된 행이 어느 Phase 에 들어가는지는 서버가 앞행에서
파생하므로, 낙관적 페인트는 이전 소속을 그대로 두고 응답이 교정한다.

### 7.1.2 임시저장에는 `sort_order` 를 보내지 않는다

배열 위치가 정본이다. 둘 다 보내면 어긋날 여지가 생기고 서버는 400 으로 거부한다.

### 7.2 응답 형식 — 주의할 차이

| 엔드포인트 | 응답 |
|---|---|
| `PUT /versions/{vid}/items` (임시저장) | `{ version, items }` — 행 조작 API 와 달리 **버전까지** 돌려준다 |
| `POST /versions/{vid}/publish` | 성공 시 `{ version, items }` |
| `POST .../publish` **실패** | **HTTP 422** + `{ detail: { code: "VALIDATION_FAILED", valid, errors, warnings } }` |
| `insert-below` / `reorder` / `DELETE items/{id}` | `{ items }` |
| `POST .../phases/apply`, `.../milestones/apply` | `{ items, phases, milestones }` — 재계산된 **보드 전체** |

apply 응답의 세 목록은 전부 **필수**다. `items` 는 여느 행 조작과 같은 `ItemOut` 목록(번호·경계
플래그 포함)이고, 기준정보 두 목록이 함께 온다. 그래서 팝업은 방금 만든 Phase/Milestone 의 id
를 두 번째 왕복 없이 응답에서 읽을 수 있고, 스토어는 재조회 없이 스코프 기준정보를 교체한다
(`board.ts: applyStructure` → `master.absorbScopeData`). 자체 transport 를 쓰는 호스트는 세
목록을 모두 채워야 한다 — 셋 중 하나라도 빠지면 셀 에디터가 보드와 어긋난 목록을 제시한다.

발행 실패가 200 이 아니라 **422** 라는 점이 중요하다. `createHttpApiClient.publish()` 가 이를
풀어서 `{ valid: false, errors, warnings }` 로 돌려주므로, 호출하는 쪽은 성공/실패를 한 형식으로 다룬다.

### 7.11 보드 XLSX 내보내기 (`plan.md` §0.5.7)

```
GET /api/v1/versions/{vid}/board.xlsx      (템플릿)
GET /api/v1/projects/{pid}/board.xlsx      (프로젝트)
→ application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

- 클라이언트는 `itemsBase(scope)` 아래에 붙이므로 **한 메서드가 두 계층을 다 처리**한다
  (`exportBoardXlsx(scope)`). 행이 사는 자리와 같으며, 그게 맞다 — 내보내는 것이 그 행들이다.
- PPT 와 동일한 blob 흐름이다 (§7.10): api 클라이언트 → object URL → `a[download]` → revoke.
- **ag-grid CSV 내보내기는 제거됐다.** Community 의 CSV 로는 원본 엑셀 양식(헤더 스타일·Phase
  색 밴딩·freeze·Doc Status 시트)을 낼 수 없고, §0.5.7 은 내보낸 파일이 `parse_workbook` 으로
  **다시 읽히기**까지 요구한다 — CSV 로는 성립하지 않는 계약이다.
- 읽기 연산이므로 `readOnly` 에서도 버튼이 남는다.

### 7.10 대시보드 PPT 내보내기 (`plan.md` §0.5.6)

```
GET /api/v1/projects/{pid}/dashboard.pptx
→ application/vnd.openxmlformats-officedocument.presentationml.presentation
```

- 생성은 **백엔드 python-pptx** 다. CLAUDE.md 의 openpyxl 경로와 같은 원칙 — 내보내기는 서버가
  만든다. 프론트는 바이트를 나르기만 한다.
- **api 클라이언트를 거친다** (`responseType: 'blob'`). `window.open` 이나 `<a href>` 로 직접
  받으면 인증 헤더가 실리지 않는다 — 이 모듈의 토큰은 런타임 인터셉터로 붙기 때문이다.
- 받은 blob 은 object URL → `a[download]` → **revoke** 순으로 처리한다. revoke 를 빠뜨리면
  문서 수명 내내 파일이 메모리에 붙어 있고, 이 화면은 반복 마운트 대상이다.
- **읽기 연산이라 `readOnly` 에서도 남는다.**
- 파일명은 프로젝트명. 비ASCII 는 서버가 RFC 5987 `filename*` 로 내려준다.

### 7.12 문서 모델 — 포맷 소유 + 프로젝트 복제 (`plan.md` §0.5.10)

**전역 문서 마스터(`/master/document-types`)는 폐기됐다.** 문서는 Phase·Milestone·Owner 와 같은
스코프 규칙을 따른다: 포맷이 소유하고, 프로젝트 생성 시 발행본에서 복제되며, 이후 서로 무관하다.

```jsonc
GET  /api/v1/versions/{vid}/documents        → { "documents": [ { "id", "name", "sort_order", "is_active" } ] }
POST /api/v1/versions/{vid}/documents/apply    { "documents": [ { "id"|null, "name" } ], "deleted_ids": [] }
                                             → { "documents": [...], "items": [...] }
GET  /api/v1/projects/{pid}/documents        → { "documents": [ { "id", "name", "sort_order",
                                                                 "is_used", "link_url", "doc_status" } ] }
PUT  /api/v1/projects/{pid}/documents          { "documents": [ { "id"|null, "name", "is_used",
                                                                 "link_url", "doc_status" } ], "deleted_ids": [] }
                                             → 같은 형식 + "items"
```

- **응답의 순서 필드는 `no` 하나다** (§0.5.10 필드 확정). `sort_order` 는 서버 내부의 저장
  위치일 뿐 **응답에 실리지 않는다**. `no` 는 **사용(ON) 문서에만 1..N** 으로 파생되며, 미사용
  문서는 **`no: null`** 이다. 저장 위치와 표시 번호를 분리한 이유는 스위치를 껐다 켜도 남의
  위치가 흔들리지 않게 하기 위함이다 — 토글마다 저장 순서를 다시 매기면 아무도 건드리지 않은
  행까지 바뀐다.
- **`no == null` 은 곧 "쓰지 않는 문서"** 이고, 프론트는 그것을 **어디에도 그리지 않는다**
  (`api/types.ts: visibleDocuments`). 팝업에서 사용을 끄면 그 문서의 선택이 즉시 풀리고 다시
  고를 수 없으며, 수동 저장 시 `document_ids` 에서도 빠진다. 셋 중 하나라도 빠지면 그 문서를
  링크하던 **다른 행들**에 잔재가 남는다 — 사용자가 신고한 버그가 정확히 그것이었다.
- 실측 응답 형태: 템플릿 `{id, no, name, is_active}` / 프로젝트 `{id, no, name, is_used,
  link_url, doc_status}`. **GET 은 계층에 따라 다른 형태를 준다** — `/versions/{vid}/documents`
  와 `/projects/{pid}/documents` 는 같은 엔드포인트 모양이지만 같은 payload 가 아니다.

> ⚠️ 이 필드 계약은 **라이브에서만 깨졌던** 자리다. 목이 저장 필드 `sort_order` 를 그대로
> 내보내는 바람에 `npm run check` 는 초록인데 실서버 응답과 어긋났고, 프로젝트 GET 이 템플릿
> 형태를 돌려주는 바람에 `is_used` 가 undefined 여서 팝업이 미사용 문서까지 번호를 매겼다.
> 목이 서버와 다른 규칙을 쓰면 검사는 **자기 자신하고만** 일치한다 (`plan.md` §0.3 의 전례).
> `verify` §23d 가 응답 키 집합을 필드 단위로 못박아 재발을 막는다.
- 원문자 코드(①~⑤) 개념은 사라졌다 — 손으로 적는 코드는 위치와 어긋날 수 있고, 사용자가 실제로
  바꾸는 것은 위치다. 행 payload 의 문서는 `{id, no, name}` 이며 `no` 는 nullable 이다.
  그리드 칩·overview 배지·팝오버가 모두 이 파생을 따른다.
- **집합 일치 계약**은 `phases/apply` 와 같다: 유지분과 `deleted_ids` 가 현재 전체 집합과 정확히
  맞아야 하며, 아니면 422. 빠뜨린 id 가 삭제로 읽히면 안 되기 때문이다.
- **삭제는 캐스케이드**다 — 그 문서를 참조하던 모든 행에서 링크가 끊긴다. 그래서 두 쓰기 응답
  모두 **재계산된 `items`** 를 함께 싣는다. 이것을 무시하면 그리드가 사라진 문서를 계속 그린다.
- 검증: 빈 이름 · 이름 중복 · 스코프 밖 id · 집합 불일치 = 422.
- UI 는 보드의 **관련 문서 셀 팝업**(Owner 팝업과 같은 형태)과 프로젝트의 **문서 등록 탭**이며,
  둘 다 같은 엔드포인트를 쓴다. 프로젝트 쪽에는 **사용**(antd Switch)·문서 링크·상태 컬럼이 더
  있고, **프로젝트 로컬 문서 추가**가 허용된다. 컬럼명은 **선택 · 사용 · 순서**이며, 순서는
  스위치를 끄는 즉시 낙관적으로 다시 계산된다.

**Owner 팝업에는 순서 개념이 없다** (§0.5.10 정밀화). 드래그 재정렬과 순서 열을 제거했고 —
Owner 는 번호로 불리지 않으므로 순서를 보이면 관리 대상만 하나 늘어난다 — 목록은 서버가 준
순서를 그대로 쓴다. 추가는 다른 팝업들과 같은 **인라인 행** 방식이다: [＋ Owner 추가] 가 빈
행을 붙이고, 이름을 넣어야 생성된다.

> ⚠️ 인라인 이름 입력의 **blur 커밋은 한 틱 미뤄야 한다.** 동기적으로 커밋하면 antd 의 blur
> 핸들러 안에서 `<a-input>` 이 언마운트되고, antd 가 자기 내부 ref 를 null 로 역참조하며 죽는다
> (`check:dom` 이 단언 실패가 아니라 런타임 예외로 잡아냈다). `nextTick` 한 번이면 된다.

### 7.9 프로젝트 주요 링크 (`plan.md` §0.5.5)

```jsonc
GET /api/v1/projects/{pid}/links → { "links": [ { "id", "description", "url", "sort_order" } ] }
PUT /api/v1/projects/{pid}/links   { "links": [ { "id"|null, "description", "url" } ] }
```

- **배열 순서가 `sort_order`** 다. 요청에는 `sort_order` 를 싣지 않는다 — 보드 행과 같은 규칙
  (§7.1.2)이며, 둘 다 보내면 어긋날 여지가 생긴다. 응답에는 1..N 으로 담겨 온다.
- PUT 은 **전량 교체**다. 기존 id 를 payload 에서 빼면 **삭제**된다.
- **검증 두 가지**: `description` 공백 불가, `url` 은 `http://` 또는 `https://` 로 시작. 어느
  행 하나라도 걸리면 **전체 저장이 422** 로 거부되고 아무것도 쓰이지 않는다 — 중간까지 저장된
  상태가 남으면 사용자가 무엇이 반영됐는지 알 수 없다.
- 클라이언트도 같은 규칙을 갖는다(`isValidLinkUrl`). 서버가 권위이고, 클라이언트 쪽은 제출이
  아니라 **타이핑 중에** 알려주기 위한 것이다. 같은 표현 하나를 그리드 셀 표시·저장 가드·목
  서버가 함께 쓰므로 셋이 어긋날 수 없다.
- UI 는 프로젝트 **대시보드 탭 아래**의 ag-grid 다. Community 관리형 row drag 로 순서를 바꾸고,
  링크 셀 오른쪽의 연결 아이콘이 `window.open(url, '_blank', 'noopener')` 를 부른다. 아이콘은
  **열 수 있는 링크에만** 나온다.

### 7.8 설비사 설정 (`plan.md` §0.6)

```jsonc
GET  /api/v1/makers            → { "makers": [ { "maker_id", "name"|null,
                                                 "show_in_overview", "explicit", "has_projects" } ] }
PUT  /api/v1/makers/settings     { "settings": [ { "maker_id", "show_in_overview" } ] }   // 업서트
PATCH /api/v1/projects/{pid}     { "name" }        // 프로젝트명 수정, 빈 이름 422
```

**표시 규칙은 세 갈래이고 서버가 판정한다:**

| 상황 | 결과 |
|---|---|
| `wp_maker_settings` 행 있음 | 그 값 (프로젝트 유무와 무관하게 켜고 끈다) |
| 행 없음 + active 프로젝트 있음 | 표시 |
| 행 없음 + 프로젝트 없음 | 숨김 |

세 번째가 아니라 **두 번째**가 핵심이다: 아무것도 설정하지 않은 설치에서도 전체 현황이 비지
않으므로, 설정 화면을 먼저 찾아내야 기능이 동작하는 상황이 생기지 않는다.

- `show_in_overview` 는 **유효값**, `explicit` 은 **설정행 존재 여부**다. 설정 화면이 둘을 나눠
  보여주는 이유는, 자동 규칙으로 켜진 설비사는 마지막 프로젝트가 비활성되는 순간 사라지기
  때문이다 — 체크박스만 보이면 그것이 버그로 읽힌다.
- 목록의 모집단은 **resolver 의 `list_makers()` ∪ 프로젝트를 가진 maker_id** 다. resolver 가
  더 이상 돌려주지 않는 maker 의 프로젝트가 있어도 설정 화면에서 사라지면 그 섹션을 끌 방법이
  없어진다 (루트 §2.2 의 폴백 규칙과 같다).
- **resolver 미주입이면 목록이 빌 수 있고 그것이 정상이다.** 설정 화면은 오류가 아니라 안내
  문구를 띄운다.

### 7.3 필드명

- 임시저장 행의 문서 배열은 **`document_ids`** 다 (`document_type_ids` 아님).
- `dash_label`(`VARCHAR(60) NULL`) — 대시보드 카드 캡션 (`plan.md` §0.5-1). `ItemOut` 과
  `ItemSaveIn` 양쪽에 있고, draft 생성·프로젝트 생성 **deep copy 두 경로 모두** 복사된다.
  발행 검증 대상이 **아니다** — 비어 있어도 정상이며, 카드는 `deliverable` → title 앞부분으로
  대체한다. 자체 transport 를 쓰는 호스트가 이 필드를 빠뜨리면 저장이 조용히 라벨을 지운다.
- 임시저장 payload 에 **`sort_order` 는 없다. 배열 위치가 정본이다** (§7.1.2). 이전 판에는
  "보내면 그 값이 정본이고 프론트는 항상 보낸다" 고 적혀 있었는데 **틀린 서술**이었다 —
  코드는 처음부터 보내지 않았고(`stores/board.ts`), 지금 서버는 `sort_order` 와 배열 위치가
  섞이면 **400** 으로 거부한다. 자체 transport 를 구현하는 호스트가 이 문장을 따라가면 400 을 맞는다.
- 응답 행에는 `milestone_no_display`(`"0.1"`)가 추가로 온다. 프론트는 `milestone_display` 를 쓴다.
- `VersionOut.is_editable` — 서버가 판단한 편집 가능 여부. 프론트의 읽기전용 모드 근거다.

### 7.4 오류 응답 — 전부 `{ detail: { code, message, ... } }`

도메인 오류의 `detail` 은 **문자열이 아니라 객체**다. 그대로 알림에 넘기면
`[object Object]` 가 뜬다. `describeApiError()`(`api/client.ts`) 한 곳에서 세 가지 형태를
모두 처리한다 — 객체(`detail.message`), FastAPI 요청 검증 배열(`[{loc,msg}]`), 문자열.

| 상황 | 응답 |
|---|---|
| 발행 검증 실패 | `422` + `{ detail: { code: "VALIDATION_FAILED", valid, errors, warnings } }` — **평평한 한 겹** |
| 블록 연속성 위반 | `422` + `{ detail: { code: "PHASE_NOT_CONTIGUOUS" \| "MILESTONE_NOT_CONTIGUOUS", message, breaks: [...] } }` |
| 경계 규칙 위반 | `422` + `{ detail: { code: "PHASE_BOUNDARY_VIOLATION" \| ..., item_id, row_no, field } }` |
| PUBLISHED 수정 시도 | `409` |
| 기준정보 이름 중복 | `400` |

`publish()` 는 `VALIDATION_FAILED` 422 를 풀어 `{ valid: false, errors, warnings }` 로 돌려주므로
호출부는 성공/실패를 한 형식으로 다룬다. 그 밖의 오류는 그대로 던진다.

### 7.5 검증 응답

`plan.md` §2.5 형식 그대로. 프론트는 `item_id` + `field` 로 셀을 하이라이트하며,
`field` 는 `phase_id | milestone_id | title | deliverable | documents | owners` 중 하나다.
`item_id` 가 없는 오류(`EMPTY_VERSION`, `PHASE_SEQ_GAP`, `MILESTONE_SEQ_GAP`)는 셀 대신 배너로 표시한다.

**오류 코드는 union 이 아니라 `string` 으로 받는다.** 서버가 §2.5 표에 없는 코드를 추가할 수 있고
(이미 `ORPHAN_MILESTONE` 이 추가됐다), 경고는 발행을 막지 않으므로 **모르는 코드도 그냥 표시**해야 한다.
`ORPHAN_MILESTONE` 은 `phase_id` 와 `milestone_id` 를 함께 싣는다.

### 7.6 전체 현황 — `GET /api/v1/projects/overview` (`plan.md` §0.5-3)

`./ProjectsOverview` 가 부르는 **유일한** 엔드포인트이며, 이 모듈에서 설비사 경계를 넘는
유일한 호출이다. active 프로젝트만 내려온다.

**응답이 `plan.md` §0.6 에서 개편됐다** — 최상위가 `projects` 가 아니라 **`makers`** 다.

```jsonc
{ "makers": [ {
    "maker_id": 7,
    "name": "G정밀",               // resolver 미구성이면 null — 오류가 아니라 정상 상태
    "projects": [ {                // 체크된 설비사는 이 배열이 비어도 섹션이 온다
      "id": 12, "name": "2026 AI 과제 1차",
      "maker_id": 7, "maker_name": "G정밀",
      "counts": { "NOT_STARTED": 30, "IN_PROGRESS": 3, "DONE": 2, "HOLD": 0, "NA": 0 },
      "items": [ { "no": 1, "status": "DONE", "phase_seq": 0, "milestone_seq": 1,
                   "dash_label": "Gap·자원 계획" }, … ],   // sort_order 순
      "documents": [ { "document_type_id": 3, "code": "①", "name": "…",
                       "doc_status": "DONE", "link_url": "https://…" }, … ]
    } ]
} ] }
```

**그룹핑과 표시 규칙은 서버가 한다.** 클라이언트가 `maker_id` 로 버킷을 나누던 방식은 제거됐다
— 그러면 이미 프로젝트가 있는 설비사만 보일 수 있어서, 표시하기로 체크했지만 아직 시작하지
않은 설비사를 띄울 방법도, 그 첫 프로젝트를 만들 자리도 없었다.

- `items` 는 **`sort_order` 순**이고 `no` 는 1..N 이다.
- **`dash_label` 은 이미 폴백이 적용된 표시용 값이다** (§0.5-1 의 `dash_label` → `deliverable`
  → title 앞부분). 이 payload 에는 `deliverable` 도 `title` 도 없어서 클라이언트가 그 폴백을
  물리적으로 실행할 수 없다 — 서버가 풀어 보내지 않으면 라벨을 안 넣은 행이 전부 `(내용 없음)`
  으로 뜨고, 갓 만든 프로젝트에서는 그게 35행 전부다. 대안은 프로젝트 전체 × 항목마다 긴 텍스트
  두 개를 더 싣는 것이었다. 몇 단어짜리 캡션을 위해 그럴 이유가 없어 **서버에서 해결**한다.
- `phase_seq` 는 `phases.seq_no` 가 아니라 **표시 번호**(§2.2 first-appearance)다. 저장된
  `seq_no` 를 그대로 실으면 미니맵 밴딩이 프로젝트 보드의 Phase 번호와 어긋난다.
- 미배정(회색) 행은 `phase_seq` · `milestone_seq` 가 **둘 다 null** 이며, 맨 뒤 무색 밴드로
  모인다 (`sort_order` 상 어디에 있었든).
- 화면은 `maker_id` 로 **클라이언트에서** 설비사 구획을 만든다. payload 를 maker 로 감싸지
  않는 것은 의도다 — 이 모듈은 maker 테이블을 갖지 않는다 (루트 §2.4).
- `documents` 는 **`is_used = 1` 인 것만** 싣는다 (§0.5-4). `is_used` 필드 자체는 없다 —
  실려 있다는 사실이 곧 그 값이다.

### 7.7 프로젝트 문서 링크·상태 — `/projects/{pid}/documents` (`plan.md` §0.5-4)

```jsonc
GET /api/v1/projects/{pid}/documents
→ { "documents": [ { "document_type_id", "code", "name",
                     "is_used": true, "link_url": null, "doc_status": "NOT_WRITTEN" }, … ] }

PUT /api/v1/projects/{pid}/documents
  { "documents": [ { "document_type_id", "is_used", "link_url", "doc_status" }, … ] }
→ 같은 형식 (저장 후 전체)
```

- **행이 없으면 기본값이다.** GET 은 활성 전역 문서 **전부**를 LEFT JOIN 으로 돌려주며, 저장한
  적 없는 문서도 `is_used=true · doc_status='NOT_WRITTEN' · link_url=null` 로 나온다. 프론트는
  행을 만들어내지 않는다 — 목록은 언제나 서버 것이다.
- PUT 은 **업서트**다. 일부만 보내도 나머지는 그대로 남는다 (전량 교체가 아니다).
- `code` · `name` 은 전역 정의라 **응답에만** 있고 요청에는 없다. 프로젝트가 고칠 수 없다.
- `link_url` 은 `doc_status` 와 **무관하게** null 이 될 수 있다. 빈 문자열은 null 로 저장한다.
- 알 수 없거나 **비활성** 문서 id 는 **422**. 비활성 문서는 GET 목록에서도 빠진다.
- `counts` 는 다섯 키가 항상 존재한다(0 포함). 합계는 `items.length` 와 같아야 한다.
- **maker JOIN 금지** — id 만 싣고 이름은 `MakerResolver` 를 거친다 (루트 §2).

---

## 8. 개발 / 검증

```bash
npm install
npm run dev          # http://localhost:5180 — 목 데이터로 즉시 동작
npm run type-check   # vue-tsc (앱 + 체크 스크립트 두 벌)
npm run verify       # 재계산·경계·apply·버전·검증·대시보드/전체현황·문서 계약·순서 (558 checks, 목)
npm run check:dom    # jsdom 마운트·그리드·팝업·탭·문서/Owner 셀 팝업·허브·XLSX/PPT (439 checks, 목)
npm run check        # 위 세 개
npm run build:remote # dist-remote/
```

**실서버 연동 확인** — 목이 아니라 가동 중인 백엔드에 붙는다:

```bash
# 백엔드: python -m uvicorn app.standalone:app --port 8010
WP_API_BASE=http://localhost:8010 npm run check:live
```

> ### ⚠️ `iai-test` 는 스크래치 DB 가 아니라 **산출물**이다
>
> 납품 템플릿은 엑셀 35행을 적재한 **납품 대상 보드**이며, 동시에 `standalone.py` 가 바라보는
> 개발 DB 이기도 하다. 이전 버전의 이 스크립트는 그 보드에 직접 Phase 를 만들었고 하나를
> 남겼는데, 그 때문에 실제 Phase 4개의 `seq_no` 가 전부 밀려 **납품 보드가 자기 발행 검증을
> 통과하지 못하는 상태**가 됐다.
>
> 그래서 지금은:
> * **납품 템플릿에는 GET 만 한다.** 읽기 전용 형상 검사 용도.
> * 모든 쓰기는 스크립트가 **직접 만든 임시 템플릿** 에서 일어나고, 끝나면 정리한다.
> * 임시 템플릿 생성이 실패하거나 납품 템플릿 id 로 돌아오면 **즉시 중단**한다 — 납품 보드로
>   절대 fallback 하지 않는다.
> * 종료 시 납품 템플릿의 전체 행을 시작 시점과 **지문 비교**해 손대지 않았음을 증명한다.
>
> **남는 잔재 하나**: 템플릿 하드 삭제가 없어 임시 템플릿은 `is_active=false` 로 비활성화만
> 되고 껍데기가 남는다. 쌓이면 SQL 로 지운다.
>
> ⚠️ **`plan.md` §0 재구조화 이후 아직 한 번도 돌리지 않았다.** URL 이
> `/work-packages/...` → `/templates/...` 로 바뀌고 `/projects/...` 가 추가됐으며 백엔드가
> 병행 작업 중이다. `check:live` 는 새 계약으로 갱신되어 타입 검사는 통과하지만, 마지막
> 그린 실행은 개정 이전 API 기준이다. 여기서 나는 실패는 "계약이 움직였다"는 신호로 먼저
> 의심할 것.
>
> 드리프트가 의심되면 손으로 고치지 말고 `python db/verify.py` 로 확인·보고한다.

`npm run dev` 는 실서버 없이도 동작한다 — `src/mock` 이 renumber/validate 를 포함한
인메모리 백엔드를 제공하고, 하니스가 이를 `dataSource` prop 으로 주입한다.
실서버로 붙이려면 하니스 상단 토글을 켜고 `VITE_WP_API_BASE` 를 지정하거나
`vite.config.ts` 의 `/api` 프록시(`WP_DEV_API_TARGET`)를 쓴다.

---

## 9. 배포 제외 대상

| 경로 | |
|---|---|
| `src/dev/**` | 로컬 하니스 + 검증 스크립트. `src/index.ts` 에서 도달 불가 |
| `src/mock/**` | 인메모리 백엔드 + 엑셀 시드. 동일 |
| `index.html` | 하니스 전용 |
| `dist/`, `dist-check/` | 하니스 빌드 / 검증 빌드 |

`dist-remote/` 만이 산출물이다. `src/index.ts` 에서 시작하는 import 그래프에
`src/dev` 나 `src/mock` 이 들어오지 않는지가 유일한 확인 사항이다.

---

## 10. ag-grid Community 제약 대응 (`plan.md` §5.3)

| 기능 | 대응 |
|---|---|
| Row Grouping (Enterprise) | Phase 블록 **첫 행에만 라벨 렌더** + Phase 별 좌측 컬러 바 + 행 배경 밴딩. 팔레트는 `docs/dashboard.jpg` (`src/theme/palette.ts`) |
| `colDef.rowSpan` | **미사용.** managed row drag 와 충돌 소지 |
| Excel Export (Enterprise) | **백엔드 openpyxl XLSX** (§0.5.7). ag-grid CSV 경로는 제거됐다 |
| Context Menu (Enterprise) | 행 단위 액션은 `작업` 컬럼의 antd 버튼 |
| Range Selection (Enterprise) | 미사용 |

**상태 색은 표 하나가 전부를 지배한다.** `plan.md` §0.5 의 표가 정본이고, 코드에서는
`theme/dashboard.ts` 의 `DASH_STATUS_STYLE` 한 곳이다 — 대시보드 카드·전체 현황 미니맵 셀·범례·
팝오버·**그리드 상태 칩**이 전부 여기를 읽는다. `theme/palette.ts` 에 있던 `STATUS_COLORS` 는
제거했다: 같은 다섯 상태에 다른 다섯 쌍의 hex 를 들고 있었고, 두 표가 일치해야 한다는 요구는
곧 두 표가 어긋난다는 뜻이다. 백엔드 PPT 상수도 같은 표를 복제하며, 어긋나면 스펙 위반이다.

2026-08-08 개정으로 진행중이 초록, 완료가 짙은 회색, NA 가 **짙은 배경 + 밝은 글자**가 됐다.
NA 의 종전 `opacity: 0.6` 흐림은 없앴다 — 흐림은 좌측 주관 바와 테두리까지 같이 죽였고,
"비활성" 과 "해당 없음" 을 같은 모양으로 만들었다. 다섯 상태 전부 배경 대비 글자 명암비가
**4.5:1 이상**임을 `npm run verify` 가 계산해서 확인한다.

**대시보드와 전체 현황에는 ag-grid 가 없다.** 전체 현황의 미니 대시보드는 `Phase N` 라벨이
붙은 색 밴드 아래 마일스톤 단위로 셀을 묶어 늘어놓은 것이고, 셀은 텍스트가 없다. 진행전 항목은
흰 배경 + **slate-400 테두리**의 빈 박스로, 15px 에서도 존재가 드러나야 하기 때문이다 (§0.5-3
개정이 지적한 부분 — slate-200 은 흰 행 위에서 그냥 사라졌다).

**프로젝트 대시보드의 높이는 통일된다** (§0.5.4b): 마일스톤 헤더끼리, 항목 카드끼리 각각 같은
높이다. 측정(ResizeObserver + 2-pass) 대신 **보드 전체에서 가장 긴 값이 몇 줄인지 한 번 추정**해
그 높이를 전부에 못박는다 — 한글은 라틴의 두 배 폭으로 세며, 추정이 한 줄 빗나가도 *어긋나
보이지는 않는다*(전부 같은 값을 쓰므로 구조적으로 불가능). 넘치는 내용은 클램프되고 hover
팝오버가 보완한다.

**전체 현황의 시각 구조** (§0.6-4 디자인 언어): 페이지는 옅은 배경(`#f8fafc`), 설비사는 그 위의
**흰 카드**(`rounded-xl` + 옅은 그림자), 프로젝트 행은 카드 안에서 **들여쓰기**(`ml-6`)되어
하위 항목임이 형태로 드러난다. 행 사이는 간격과 옅은 구분선을 함께 쓴다 — 간격만으로는 미니
대시보드가 큰 행에서 경계가 흐려지고, 선만으로는 다시 각져 보인다. 직각 테두리를 나열하던
이전 판이 "각지고 딱딱하다" 는 피드백을 받은 지점이다.

**전체 현황 행은 5구획**이다 (§0.5-3b, 2026-08-08 정정): ① 프로젝트명(클릭 = 이름 수정)
② 진행률·집계 ③ 미니 대시보드 ④ 문서 ⑤ **[이동] 텍스트 버튼**. 이동은 이름 옆의 아이콘에서
마지막 칸의 버튼으로 옮겼다 — 행에서 가장 자주 쓰이는 동작치고 16px 아이콘은 너무 작았고,
바로 옆 문서 칩 아이콘들과 혼동됐다. 트랙 폭이 전부 고정이라 ⑤ 도 모든 행에서 같은 x 에 선다. ③ 의 너비는 **상수 740px 고정**이라 모든 행의 ④ 가 같은 x 에서 시작한다
— 내용에 맞춰 늘어나면 12행짜리 프로젝트가 35행짜리보다 문서를 왼쪽으로 당겨 열이 어긋난다.
넘치는 보드는 ③ **안에서** 가로 스크롤한다. 이동은 **아이콘만** 담당한다 (이름 클릭은 텍스트를
고르려는 클릭까지 화면 전환으로 만든다).

④ 의 문서 칩은 **세 상태 모두 같은 `FilePptOutlined` 아이콘이고 색으로만 구분한다** (§0.5-3b,
2026-08-08 정정): 작성전 `#94a3b8`·클릭 불가, 작성중 `#d97706`, 완료 `#059669`. 순서는 아이콘
옆 텍스트가 아니라 **모서리의 작은 원형 배지**로 표시하며, 배지 숫자는 **문서 코드(원문자
①~⑤)에서 유도**한다 — 배열 인덱스로 매기면 어떤 문서의 사용 체크를 끄는 순간 ①③④ 가 1·2·3
으로 다시 매겨져 문서 설정 화면의 코드와 어긋난다. 배지는 중립색(`#475569`)이다: 상태는 이미
아이콘 색이 말하므로 배지까지 물들이면 두 신호가 같은 것을 두 번 말하며 서로의 대비를 깎는다. 작성전을 "작성 전"
이라는 **글자**로 그리던 이전 판은 넷째 칸을 글리프와 텍스트가 섞인 줄로 만들어, 그 칸이 존재하는
이유인 한눈 스캔을 없앴다. 링크 규칙은 그대로 — 작성중/완료 + 링크가 있을 때만 새 창으로 열리고,
없으면 클릭 불가에 "링크 없음" 툴팁이 붙는다.

**범례는 두 그룹 모두 같은 미니 카드**(`components/dashboard/LegendSwatch.vue`)를 쓴다. 주관은
좌측 바 색만 바뀌고 상태는 배경색만 바뀌므로, "어느 색이 카드의 어디에 나타나는가" 를 스와치
자체가 말한다. 순서는 **주관 → 상태**. 전체 현황 범례는 같은 스와치를 쓰되 **바가 없다** —
그 화면의 셀에는 주관 바가 없기 때문이다 (overview payload 에 owner 가 없다).
 카드 스택과 미니맵은 순수 DOM + `wp-` 유틸리티
이며, 색은 런타임에 상태에서 고르므로 전부 인라인 스타일이다 — `wp-bg-[#…]` 처럼 JS 로 조립한
클래스는 Tailwind 의 content 스캐너가 볼 수 없어 애초에 생성되지 않는다. 팔레트는
`src/theme/dashboard.ts` 에 고정값으로 있고(`plan.md` §0.5 가 hex 를 못박았다),
그리드 행 배경용 `src/theme/palette.ts` 와는 **일부러 별개**다: 35줄 텍스트 뒤에 깔리는 색과
헤더·카드에 쓰는 색은 요구가 다르다.

Phase/Milestone **관리 팝업**(`components/StructureManagerModal.vue`, `plan.md` §0.4)은
의도적으로 ag-grid 가 **아니다**. 이름 다섯 줄을 그리자고 모달 안에 두 번째 그리드
인스턴스를 세울 이유가 없고, 그리드 쪽 드래그 동작(블록 제한, managed drag)은 여기서 오히려
방해다 — 이 목록에는 블록이 없다. antd Modal + HTML5 draggable 행 + ↑/↓ 버튼으로 끝난다.
행은 핸들을 누르고 있는 동안에만 `draggable` 이 되어 이름 입력이 드래그에 먹히지 않는다.

**Owner 셀은 인라인 에디터가 아니라 팝업이다** (`plan.md` §0.5.9). Phase/Milestone 셀과 같은
방식으로 셀은 편집 불가로 두고 클릭이 **셸의 모달**을 연다 — ag-grid 팝업 에디터는 편집이 끝나는
순간 파괴되므로 그 안에 모달을 두면 같이 사라진다. 창 하나에 두 가지가 들어 있고, 둘은 저장
경로가 다르다:

* **선택**(체크박스 → [적용])은 행의 owner 값만 바꾼다. `board.patchItem` 이므로 dirty 가 되고,
  저장은 툴바의 수동 저장이다 (§0.5.8 이후 유일한 저장 경로).
* **관리**(추가·이름 변경·삭제·순서)는 스코프 Owner 기준정보라 **즉시 API** 다. 보드 저장
  payload 에 들어가지 않으므로 함께 흘려보낼 방법이 없다.

순서 변경은 **옮겨진 행마다 `PUT .../owners/{id}` 한 번**이다. `WpOwner.sort_order` 가 쓰기
가능한 필드이고 벌크 재정렬 엔드포인트는 없다 — Owner 목록은 이름 몇 개라 비용이 없지만, 보드
행(순서 자체가 payload)과 다른 방식이라는 점은 알아둘 것. 계약 변경은 하지 않았다.

Key Action Item · Deliverable · 대시보드 표시 셀은 **세로 가운데 정렬**이다. 클램프는
`-webkit-box` 라 한 요소가 flex 컨테이너를 겸할 수 없어서, 셀이 flex 가 되고 클램프는 안쪽
span(`ClampCellRenderer`)이 맡는다. 종전의 `padding-top: 5px` 눈속임은 제거됐다.

`Owner` 탭(옛 `views/MasterScopeData.vue`)은 **제거됐다** (§0.5.9 의 예고분). 그 파일은 없고,
Owner 선택·관리는 이 팝업 하나가 맡는다. 권한 판정이 `hostReadOnly` 에서 `readOnly` 로
좁아진 것이 함께 따라온 결과다 — 위 §Props 참고.

`rowDragManaged` 는 **초기 그리드 옵션**이라 런타임 변경이 불가능하다. DRAFT ↔ 읽기전용
전환 시 `:key` 로 그리드를 재생성한다 (버전 전환 시에만 발생하므로 비용은 무시할 수준).

`suppressMoveWhenRowDragging` 은 **반드시 `false`** 여야 한다. ag-grid 는 `rowDragEnd` 를
드롭 적용 *이전*에 발행하므로, 이 옵션을 켜면 핸들러가 드래그 전 순서를 읽게 되고 블록 가드가
모든 교차 드래그를 통과시킨다. Community 에는 드래그 중 드롭을 거부하는 훅이 없어, 거부는
`rowDragEnd` 에서 스토어의 행을 그리드에 되돌려 넣는 방식으로 한다.

---

## 11. 이식 체크리스트 (루트 §6 프론트엔드 항목)

- [ ] 호스트에 remote 등록 후 `wpBoard/MasterAdmin` · `wpBoard/ProjectWorkspace` ·
      `wpBoard/ProjectsOverview` 를 **각각 다른 메뉴 항목**으로 import
- [ ] `ProjectWorkspace` 에 `makerId` 주입 — 호스트 설비사 선택 화면에서 전달
      (`MasterAdmin` 에는 넘길 prop 이 없다)
- [ ] `configure({ apiBaseUrl })` 또는 `apiBaseUrl` prop
- [ ] `authToken` 연결 (호스트 인증은 이 모듈 범위 밖)
- [ ] shared singleton 버전이 호스트와 일치하는지 확인 (§6)
- [ ] 호스트 화면에서 스타일 오염 육안 확인 (§3 의 CSS 감사 명령 포함)
- [ ] `hasUnsavedChanges()` 를 호스트 라우터 가드에 연결 — **편집 가능한 두 화면 모두**
      (`ProjectsOverview` 는 항상 `false`)
- [ ] `ProjectsOverview` 에 `onOpenProject` 연결 — 없으면 행 클릭이 동작하지 않는다
- [ ] 백엔드에 `GET /api/v1/projects/overview` 와 `items.dash_label` 이 있는지 확인 (§7.6, §7.3)
- [ ] `dist-remote/` 만 배포, `src/dev`·`src/mock` 미포함 확인
- [ ] 마운트 → 언마운트 → 재마운트 동작 확인 (`npm run check:dom` 이 자동 검증)
