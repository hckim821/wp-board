<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import MasterAdmin from '../remote/MasterAdminRemote.vue'
import ProjectWorkspace from '../remote/ProjectWorkspaceRemote.vue'
import ProjectsOverview from '../remote/ProjectsOverviewRemote.vue'
import MakerSettings from '../remote/MakerSettingsRemote.vue'

/**
 * Local harness standing in for the host application. NEVER SHIPPED — `src/dev` is
 * excluded from the federation entries and from `dist-remote`.
 *
 * It exists to prove what INTEGRATION.md §5/§6 actually care about:
 *   1. the **menu** is here, outside the modules (`plan.md` §0.1). 기준 데이터 관리 and
 *      설비사 관리 take no maker at all.
 *   2. the maker is resolved *here* and passed in as `makerId` / `makerName`
 *   3. mount → unmount → remount leaves nothing behind
 *   4. two instances can be mounted at once without sharing state
 *   5. the host's own global CSS (`host.css`) survives the remote being on screen
 *
 * **프로젝트는 메뉴 항목이 아니다** (2026-08-09 사용자 결정). 진입 경로가 전체 현황의
 * [이동] 하나뿐이므로 (`plan.md` §0.6-4) 메뉴에 두면 "고른 프로젝트가 없는 프로젝트
 * 화면" 이라는, 아무도 원하지 않는 상태로 가는 버튼이 된다. 그래서 `openProject` 가
 * 채워져 있을 때만 존재하는 화면이고, 그 값은 [이동] 콜백이나 딥링크로만 들어온다.
 *
 * **가짜 설비사 표도 없다** (같은 결정). 예전에는 `A설비 주식회사` / `B테크놀로지` 를
 * 여기 박아 두고 버튼으로 골랐는데, 설비사를 고르는 것은 호스트의 일이지 *이 목록이
 * 정답이라는 뜻은 아니었다* — 실제 DB 의 설비사 id 와 무관한 숫자였고, 그 상태로
 * 프로젝트 화면에 들어가면 남의 설비사를 보고 있게 된다. 지금은 열린 프로젝트에서
 * 거꾸로 해석한다: `GET /projects/{id}` 가 주는 `maker_id` · `maker_name` 을 호스트가
 * 읽어서 prop 으로 내린다. 이름 해석이 호스트 책임이라는 계약이 그대로 드러난다.
 *
 * 목 모드는 **없다** (2026-08-08 사용자 결정). 하니스는 항상 실서버(8010)와
 * 통신한다 — 목으로 시작하면 발행·저장이 인메모리에만 남고 새로고침에 증발하는
 * 사고가 실제로 있었다. `src/mock` 은 `npm run check`(자동 검증) 전용으로만 남는다.
 * `data-source` prop 을 주지 않으므로 BoardShell 이 `apiBaseUrl` 로 실제 HTTP
 * 클라이언트를 만든다.
 */

/**
 * The host's own menu. Each item mounts a different federated module.
 *
 * `'projects'` is **not** a menu item — it is the screen `openProject` puts us on.
 */
type Screen = 'overview' | 'projects' | 'master' | 'makers'

/**
 * 전체 현황 이 기본 진입 화면이다 (`plan.md` §0.6-4). It is the hub: projects are created,
 * renamed and entered from there, and 프로젝트 is where its [이동] button lands.
 */
const screen = ref<Screen>('overview')

/**
 * 열린 프로젝트, 그리고 그것을 여느라 호스트가 해석한 설비사.
 *
 * 셋을 한 객체로 묶은 것은 **함께 정해지고 함께 사라지기** 때문이다. 예전처럼 따로 두면
 * "설비사는 1번인데 프로젝트는 7번 설비사 것" 같은 조합이 타입상 가능해지고, 실제로 가짜
 * 설비사 버튼이 그 상태를 만들 수 있었다. `null` 이면 프로젝트 화면 자체가 없다.
 */
const openProject = ref<{
  projectId: number
  makerId: number
  makerName: string | null
} | null>(null)
const mounted = ref(true)
const split = ref(false)
const backend = ref<'probing' | 'live' | 'down'>('probing')
const readOnly = ref(false)
const dirty = ref(false)

// `import.meta.env` is legal *here* and nowhere else: this file is dev-only, so nothing
// it inlines can end up in the federated bundle (INTEGRATION.md §5).
// 기본은 127.0.0.1 — uvicorn 이 `--host 127.0.0.1` 로 뜨므로, Windows 에서
// `localhost` 가 ::1(IPv6) 로 먼저 풀리는 환경까지 확실히 커버한다.
const liveApiBase = import.meta.env.VITE_WP_API_BASE ?? 'http://127.0.0.1:8010'

const mountKey = ref(0)

/**
 * 백엔드 생존 확인. 죽어 있으면 3초마다 재시도해서, uvicorn 을 띄우는 즉시
 * 배지가 초록으로 바뀐다. 연결 실패는 모드 전환 사유가 아니라 **그냥 오류**다.
 */
let probeTimer: ReturnType<typeof setTimeout> | null = null

async function probeBackend() {
  const base = liveApiBase.replace(/\/+$/, '')
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 1500)
    const res = await fetch(`${base}/health`, { signal: controller.signal })
    clearTimeout(timer)
    if (res.ok) {
      const wasDown = backend.value === 'down'
      backend.value = 'live'
      if (wasDown) remount() // 죽은 동안 실패한 초기 로드를 다시 태운다
      return
    }
  } catch {
    /* not reachable */
  }
  backend.value = 'down'
  probeTimer = setTimeout(probeBackend, 3000)
}
void probeBackend()
onBeforeUnmount(() => {
  if (probeTimer) clearTimeout(probeTimer)
  window.removeEventListener('popstate', onPopState)
})

function remount() {
  mounted.value = false
  mountKey.value += 1
  requestAnimationFrame(() => (mounted.value = true))
}

/**
 * 메뉴 클릭. **프로젝트는 여기로 오지 않는다** — 메뉴에 없기 때문이다.
 *
 * 어느 메뉴를 누르든 열린 프로젝트는 닫는다. 메뉴는 전부 설비사 무관 화면이라, 프로젝트를
 * 열어 둔 채 두면 URL 만 `/` 로 돌아가고 상태는 남는 어긋남이 생긴다.
 */
function switchScreen(next: Exclude<Screen, 'projects'>) {
  screen.value = next
  openProject.value = null
  setUrl('/', true)
  remount()
}

const isProjects = computed(() => screen.value === 'projects' && openProject.value != null)
const isOverview = computed(() => screen.value === 'overview')
const isMakers = computed(() => screen.value === 'makers')

/**
 * The `onOpenProject` callback, played by the host.
 *
 * This is the whole point of the prop: `ProjectsOverview` has no router and no idea where a
 * project lives, so it hands the ids back and *this* file decides that "open a project"
 * means switch the maker and mount `ProjectWorkspace`. A real host would push a route here.
 */
/*
 * ─────────────────────────── URL 라우팅 (호스트 역할) ───────────────────────────
 *
 * **모듈은 URL 을 읽지도 쓰지도 않는다** (`plan.md` §0.6-4, 루트 INTEGRATION.md §5). 전부
 * 여기, 즉 호스트를 흉내 내는 하니스의 몫이다 — 라우팅 소유권이 호스트에 있다는 계약을 이
 * 파일이 실제로 증명한다. 실제 호스트라면 이 자리에 vue-router 가 들어간다.
 *
 * 경로는 `/{projectId}` 하나뿐이다. 관리 화면들은 라우팅 대상이 아니므로 `/` 로 되돌린다.
 */
const PROJECT_PATH = /^\/(\d+)\/?$/

function projectIdFromUrl(): number | null {
  const matched = PROJECT_PATH.exec(window.location.pathname)
  return matched ? Number(matched[1]) : null
}

function setUrl(path: string, push: boolean) {
  if (window.location.pathname === path) return
  if (push) window.history.pushState({}, '', path)
  else window.history.replaceState({}, '', path)
}

/**
 * Resolves which maker a project belongs to, **and what it is called**.
 *
 * A deep link carries only the project id, and `ProjectWorkspace` needs the maker too — so the
 * host looks it up, exactly as INTEGRATION.md §5 tells a real one to. The module is never asked
 * to derive it.
 *
 * 이름까지 여기서 읽는 이유: 설비사 이름은 호스트 소유다. 서버는 `MakerResolver` 를 거쳐
 * `maker_name` 을 실어 주고(미주입이면 `null`), 그 `null` 을 그대로 넘기는 것도 계약의
 * 일부다 — 모듈은 `설비사 #{id}` 로 대신 표시한다.
 */
async function resolveProject(
  projectId: number,
): Promise<{ makerId: number; makerName: string | null } | null> {
  try {
    const response = await fetch(`${liveApiBase.replace(/\/+$/, '')}/api/v1/projects/${projectId}`)
    if (!response.ok) return null
    const body = (await response.json()) as {
      project?: { maker_id?: number; maker_name?: string | null }
    }
    const makerId = body?.project?.maker_id
    if (makerId == null) return null
    return { makerId, makerName: body?.project?.maker_name ?? null }
  } catch {
    return null
  }
}

/** Opens a project from a URL. Falls back to 전체 현황 when it does not exist (404). */
async function openFromUrl(projectId: number) {
  const resolved = await resolveProject(projectId)
  if (resolved == null) {
    // eslint-disable-next-line no-console
    console.warn('[host] no such project, returning to 전체 현황', projectId)
    openProject.value = null
    screen.value = 'overview'
    setUrl('/', false)
    remount()
    return
  }
  openProject.value = { projectId, ...resolved }
  screen.value = 'projects'
  remount()
}

function openProjectFromOverview(projectId: number, makerIdFromOverview: number) {
  // eslint-disable-next-line no-console
  console.log('[host] onOpenProject', { projectId, makerId: makerIdFromOverview })
  // 콜백은 id 둘만 준다 (그게 계약이다). 이름은 호스트가 따로 해석하므로, 먼저 띄우고
  // 이름이 도착하면 채운다 — 이름 하나 때문에 화면 전환을 기다릴 이유가 없다.
  openProject.value = { projectId, makerId: makerIdFromOverview, makerName: null }
  screen.value = 'projects'
  setUrl(`/${projectId}`, true)
  remount()
  void resolveProject(projectId).then((resolved) => {
    if (resolved && openProject.value?.projectId === projectId) {
      openProject.value = { projectId, ...resolved }
    }
  })
}

/** 뒤로 가기 — URL 이 정본이므로 거기서 다시 읽는다. */
function onPopState() {
  const projectId = projectIdFromUrl()
  if (projectId == null) {
    openProject.value = null
    screen.value = 'overview'
    remount()
    return
  }
  void openFromUrl(projectId)
}
window.addEventListener('popstate', onPopState)

// 딥링크·새로고침: 기동 시 한 번 URL 을 읽는다.
const bootProjectId = projectIdFromUrl()
if (bootProjectId != null) void openFromUrl(bootProjectId)
</script>

<template>
  <div>
    <div class="host-bar">
      <h1>호스트 애플리케이션 (dev harness)</h1>

      <span class="host-note">메뉴:</span>
      <button
        class="host-btn"
        :data-active="screen === 'overview'"
        @click="switchScreen('overview')"
      >
        전체 현황
      </button>
      <!--
        프로젝트 메뉴 항목은 **없다** (2026-08-09). 진입은 전체 현황의 [이동] 하나뿐이라
        (`plan.md` §0.6-4) 메뉴에 두면 "고른 프로젝트가 없는 프로젝트 화면" 으로 가는
        버튼이 된다.
      -->

      <!--
        관리 그룹 — 일상 화면(전체 현황·프로젝트)과 시각적으로 구분한다 (`plan.md` §0.6-4).
        호스트 메뉴의 생김새는 호스트가 정하지만, 넷이 같은 줄에 평평하게 놓이면 어느 것이
        관리자용인지 드러나지 않는다.
      -->
      <span class="host-note" style="border-left: 1px solid #d9d9d9; padding-left: 12px">
        관리:
      </span>
      <button
        class="host-btn"
        :data-active="screen === 'master'"
        @click="switchScreen('master')"
      >
        Work Package 포맷 관리
      </button>
      <button
        class="host-btn"
        :data-active="screen === 'makers'"
        @click="switchScreen('makers')"
      >
        Integrated AI 참여 설비사 관리
      </button>

      <!--
        설비사 고정 목록은 **없다**. 열린 프로젝트에서 거꾸로 해석한 값을 보여 준다 —
        고르는 화면이 아니라 해석 결과라는 점이 그대로 드러나야 한다.
      -->
      <span v-if="isProjects && openProject" class="host-note">
        [이동] 으로 진입 — 호스트가 해석한 설비사:
        {{ openProject.makerName ?? `#${openProject.makerId} (이름 미해석)` }} ·
        projectId {{ openProject.projectId }}
      </span>
      <span v-else-if="isOverview" class="host-note">
        전체 현황은 전 설비사 관망 — makerId prop 이 없고, [이동] 은 onOpenProject 콜백으로 돌아온다
      </span>
      <span v-else-if="isMakers" class="host-note">
        설비사 관리도 makerId 가 없다 — 이 화면이 곧 전체 설비사 목록이다
      </span>
      <span v-else class="host-note">기준 데이터는 설비사와 무관 — makerId prop 자체가 없다</span>

      <span style="flex: 1"></span>

      <span
        v-if="backend === 'live'"
        class="host-note"
        style="font-weight: 600; color: #389e0d"
      >
        ● 실서버 연결됨 — DB에 저장됩니다
      </span>
      <span
        v-else-if="backend === 'down'"
        class="host-note"
        style="font-weight: 600; color: #cf1322"
      >
        ✖ 백엔드({{ liveApiBase }}) 연결 안 됨 — uvicorn 을 띄우면 자동 재연결됩니다
      </span>
      <span v-else class="host-note">백엔드 확인 중…</span>
      <button class="host-btn" :data-active="readOnly" @click="readOnly = !readOnly">
        readOnly prop
      </button>
      <button class="host-btn" :data-active="split" @click="split = !split">
        2개 동시 마운트
      </button>
      <button class="host-btn" @click="remount">언마운트 → 재마운트</button>
      <span class="host-note">미저장: {{ dirty ? 'Y' : 'N' }}</span>
    </div>

    <div class="host-stage">
      <div class="host-panel">
        <template v-if="mounted">
          <ProjectWorkspace
            v-if="openProject"
            :key="`a-${mountKey}`"
            :maker-id="openProject.makerId"
            :project-id="openProject.projectId"
            :maker-name="openProject.makerName"
            :read-only="readOnly"
            :api-base-url="liveApiBase"
            :warn-on-unload="false"
            @dirty-change="(value: boolean) => (dirty = value)"
          />
          <ProjectsOverview
            v-else-if="isOverview"
            :key="`a-${mountKey}`"
            :api-base-url="liveApiBase"
            :read-only="readOnly"
            :on-open-project="openProjectFromOverview"
          />
          <MakerSettings
            v-else-if="isMakers"
            :key="`a-${mountKey}`"
            :api-base-url="liveApiBase"
            :read-only="readOnly"
          />
          <MasterAdmin
            v-else
            :key="`a-${mountKey}`"
            :read-only="readOnly"
            :api-base-url="liveApiBase"
            :warn-on-unload="false"
            @dirty-change="(value: boolean) => (dirty = value)"
          />
        </template>
        <p v-else class="host-note">언마운트됨</p>
      </div>

      <div v-if="split" class="host-panel">
        <!-- Second instance, its own client: proves there is no shared module state. -->
        <template v-if="mounted">
          <ProjectWorkspace
            v-if="openProject"
            :key="`b-${mountKey}`"
            :maker-id="openProject.makerId"
            :project-id="openProject.projectId"
            :maker-name="`${openProject.makerName ?? `설비사 #${openProject.makerId}`} (2번째 인스턴스)`"
            :api-base-url="liveApiBase"
            :warn-on-unload="false"
          />
          <!-- 콜백을 주지 않은 두 번째 인스턴스 — 행이 클릭 불가로 렌더되는지 눈으로 확인한다. -->
          <ProjectsOverview
            v-else-if="isOverview"
            :key="`b-${mountKey}`"
            :api-base-url="liveApiBase"
          />
          <MakerSettings
            v-else-if="isMakers"
            :key="`b-${mountKey}`"
            :api-base-url="liveApiBase"
          />
          <MasterAdmin
            v-else
            :key="`b-${mountKey}`"
            :api-base-url="liveApiBase"
            :warn-on-unload="false"
          />
        </template>
      </div>
    </div>
  </div>
</template>
