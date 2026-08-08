<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { App, Empty as AEmpty, TabPane as ATabPane, Tabs as ATabs } from 'ant-design-vue'
import type { WpApiClient } from '../api/client'
import { createHttpApiClient } from '../api/client'
import { resolveConfig, type WpRuntimeConfig } from '../runtime/config'
import {
  BOARD_CONTEXT,
  type Notifier,
  type DocumentPicker,
  type DocumentPickerRequest,
  type OwnerPicker,
  type OwnerPickerRequest,
  type StructureManager,
  type StructureManagerRequest,
} from '../runtime/context'
import { createBoardStore, type BoardTier } from '../stores/board'
import { createMasterStore } from '../stores/master'
import { ensureAgGridModules } from '../theme/agTheme'
import StructureManagerModal from '../components/StructureManagerModal.vue'
import OwnerManagerModal from '../components/OwnerManagerModal.vue'
import DocumentManagerModal from '../components/DocumentManagerModal.vue'
import BoardScreen from '../views/BoardScreen.vue'
import ProjectDashboard from '../views/ProjectDashboard.vue'
import ProjectDocuments from '../views/ProjectDocuments.vue'

/**
 * Wiring layer shared by both exposed modules: builds this instance's API client and
 * stores, provides them, and owns the screen switch. Split out of the exposed components
 * so it can sit *inside* `<a-app>` and therefore use the context-bound
 * message/notification instances.
 *
 * `tier` is what makes it two products (`plan.md` §0.1):
 *
 *  - `'template'` → 기준 데이터 관리. Central, maker-free. Templates with the full
 *    version flow, plus the global document master and the template's own
 *    Owner/Phase/Milestone sets.
 *  - `'project'` → 설비사 프로젝트. A project list that creates from a published format,
 *    then the same grid with no version UI at all. Master screens here edit the
 *    project's *own* copies.
 */
const props = defineProps<{
  tier: BoardTier
  /** Null on the template tier, where there is no maker to speak of (`plan.md` §0.1). */
  makerId: number | string | null
  /** Project tier only. Null = nothing selected; the board renders an empty state. */
  projectId: number | null
  makerName: string | null
  readOnly: boolean
  warnOnUnload: boolean
  dataSource: WpApiClient | null
  runtimeConfig: Partial<WpRuntimeConfig>
  navigate: ((target: string, params?: Record<string, unknown>) => void) | null
  popupContainer: () => HTMLElement
}>()

const emit = defineEmits<{ (e: 'ready'): void; (e: 'dirty-change', dirty: boolean): void }>()

// Context-bound message/notification rather than the module-level statics: the statics
// configure a singleton shared with the host, which a remote has no business touching.
const app = App.useApp()
const notify: Notifier = {
  info: (text) => app.message.info(text),
  success: (text) => app.message.success(text),
  warn: (text) => app.message.warning(text),
  error: (text, description) =>
    app.notification.error({ message: text, description, duration: 8 }),
}

/**
 * One client and one pair of stores per mounted instance — never module scope, so two
 * boards in the same host cannot see each other's state (INTEGRATION.md §5).
 */
const api: WpApiClient = props.dataSource ?? createHttpApiClient(resolveConfig(props.runtimeConfig))
const master = createMasterStore(api)
const board = createBoardStore(api, master, {
  tier: props.tier,
  // Getters, not values: the host may change any of these on a mounted board.
  makerId: () => props.makerId,
  projectId: () => props.projectId,
  forceReadOnly: () => props.readOnly,
  onError: (text) => notify.error(text),
})

/**
 * The Phase/Milestone 관리 팝업 lives here, not in the cell editors that open it
 * (`plan.md` §0.4).
 *
 * An ag-grid popup cell editor is destroyed the instant editing stops, so a modal rendered
 * inside one would be torn down with it before the user could touch it. One instance at the
 * shell, opened through the context, also means the [수정] action on a locked cell and the
 * `+ 새 Phase 생성` action in the editor reach the very same screen.
 *
 * `v-if` rather than an `open` prop: the popup's whole state is derived from the board at
 * the moment it opens, so a fresh mount is the state reset.
 */
const structureRequest = ref<StructureManagerRequest | null>(null)
const structure: StructureManager = {
  open: (request) => {
    structureRequest.value = request
  },
}

/** Owner 선택·관리 팝업 (`plan.md` §0.5.9) — same hosting rule as the structure popup. */
const ownerRequest = ref<OwnerPickerRequest | null>(null)
const ownerPicker: OwnerPicker = {
  open: (request) => {
    ownerRequest.value = request
  },
}

/** 관련 문서 선택·관리 팝업 (`plan.md` §0.5.10) — same hosting rule again. */
const documentRequest = ref<DocumentPickerRequest | null>(null)
const documentPicker: DocumentPicker = {
  open: (request) => {
    documentRequest.value = request
  },
}

provide(BOARD_CONTEXT, {
  api,
  board,
  master,
  notify,
  structure,
  ownerPicker,
  documentPicker,
  makerId: props.makerId,
  makerName: props.makerName,
  navigate: props.navigate,
  popupContainer: props.popupContainer,
})

/**
 * 프로젝트 내부 네비게이션 — 3 tabs (`plan.md` §0.5-2b, 2026-08-08 개정).
 *
 * This replaced a 보드↔대시보드 radio toggle that sat *inside* the board tab. The toggle put
 * two things at two different levels of the same screen — a view switch nested under a tab
 * bar — and the revision flattens them: on a project, 대시보드 · Work Package · 문서 등록 are
 * peers, with 대시보드 the landing screen.
 *
 * 탭은 셋씩 두 번 줄었다. 문서 탭이 프로젝트 전용이 되면서 템플릿에서 빠졌고 (§0.5.10),
 * **Owner 탭은 제거됐다** (§0.5.9 의 예고분) — Owner 선택과 관리는 보드 Owner 셀이 여는
 * `OwnerManagerModal` 이 한자리에서 하므로, 같은 목록을 편집하는 화면이 둘일 이유가 없다.
 * 그래서 템플릿 계층에는 화면이 하나뿐이고 탭 바 자체가 없다.
 */
type TabKey = 'dashboard' | 'board' | 'documents'

const tab = ref<TabKey>('board')

/** On the project tier the board tab shows the list until a project is opened. */
const projectOpen = computed(() => board.tier === 'project' && board.projectId.value != null)

/**
 * The tab bar exists only on an open project.
 *
 * Before a project is opened, its tabs address something that does not exist yet, and a bar
 * of disabled tabs over a list screen is noise. The template tier now has a single screen —
 * a one-tab bar is the same noise with a different cause — so it shows none either.
 */
const showTabs = computed(() => projectOpen.value)

/** Host-selected project id. Null renders the empty state (`plan.md` §0.6-4). */
const projectId = computed(() => props.projectId)

/**
 * Opening a project lands on 대시보드 (§0.5-2b); closing it resets, so the *next* project
 * does not open onto whichever tab the last one was left on.
 */
watch(projectOpen, (open) => {
  tab.value = open ? 'dashboard' : 'board'
})

/**
 * Guarded tab switch — `:activeKey` + `@change` rather than `v-model`, so leaving Work
 * Package with unsaved edits can be refused.
 *
 * The edits are not lost either way (the store holds them and 저장 still works on return),
 * but a grid that vanishes mid-edit reads as a discard, so it is confirmed. Only *leaving*
 * the grid asks; the other two tabs have nothing pending to lose.
 */
function switchTab(next: TabKey) {
  if (next === tab.value) return
  if (tab.value === 'board' && board.dirty.value) {
    app.modal.confirm({
      title: '저장하지 않은 변경이 있습니다',
      content:
        'Work Package 화면을 벗어나면 편집 화면이 닫힙니다. 변경 내용은 유지되지만 저장되지는 않습니다. 계속할까요?',
      okText: '이동',
      cancelText: '취소',
      onOk: () => {
        tab.value = next
      },
    })
    return
  }
  tab.value = next
}

// Push dirty state to the host so its router can guard navigation without polling —
// this package never imports vue-router (INTEGRATION.md §5).
watch(board.dirty, (value) => emit('dirty-change', value))

// A host that swaps the selected maker without remounting must get a reloaded workspace,
// not a stale one. Templates are central, so only the project tier cares.
watch(
  () => [props.makerId, props.projectId],
  () => {
    if (board.tier === 'project') void board.init()
  },
)

// `projectId` is what selects the board now, so an unused local computed would be dead
// weight; it exists only to keep the template readable.
void projectId

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!board.dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  ensureAgGridModules()
  if (props.warnOnUnload) window.addEventListener('beforeunload', onBeforeUnload)
  await board.init()
  emit('ready')
})

onBeforeUnmount(() => {
  // Repeated mount/unmount is an explicit requirement — leave nothing behind.
  window.removeEventListener('beforeunload', onBeforeUnload)
})

defineExpose({
  hasUnsavedChanges: () => board.dirty.value,
  save: () => board.save(),
  reload: () => board.reload(),
})
</script>

<template>
  <div class="wp-flex wp-h-full wp-flex-col">
    <!--
      3 tabs on an open project, none on a template (`plan.md` §0.5-2b). `:activeKey` +
      `@change` rather than `v-model`, because leaving Work Package with unsaved edits is
      refusable.
    -->
    <ATabs
      v-if="showTabs"
      :activeKey="tab"
      size="small"
      class="wp-mb-1"
      @change="(key: string | number) => switchTab(key as TabKey)"
    >
      <ATabPane key="dashboard" tab="대시보드" />
      <ATabPane key="board" tab="Work Package" />
      <!--
        문서 탭은 **프로젝트 전용**이 됐다 (`plan.md` §0.5.10). 전역 문서 마스터가 사라졌으므로
        WP 포맷 관리에는 편집할 전역 문서가 없고, 템플릿의 문서는 보드의 관련문서 셀 팝업에서
        관리한다. 프로젝트 쪽은 사용여부·링크·상태가 있어 별도 화면이 남는다.
      -->
      <ATabPane key="documents" tab="문서 등록" />
      <!--
        Phase · Milestone · Owner 는 전부 여기 없다. 앞의 둘은 관리 팝업이 대신하고 (`plan.md`
        §0.4) — 순서가 곧 번호라 보드 옆에서 편집하는 것이 요점이다 — Owner 탭도 같은 이유로
        제거됐다 (§0.5.9): 보드 Owner 셀 팝업이 선택과 관리를 함께 한다.
      -->
    </ATabs>

    <div class="wp-min-h-0 wp-flex-1">
      <!--
        Exactly one screen is mounted at a time (§0.5-2b). `v-if`/`v-else-if` rather than
        `v-show`: two live ag-grid instances in one host is how a federated remote ends up
        with two module registries fighting over one DOM.
      -->
      <ProjectDashboard v-if="tab === 'dashboard' && projectOpen" />
      <template v-else-if="tab === 'board'">
        <BoardScreen v-if="board.tier === 'template' || projectOpen" />
        <!--
          프로젝트 목록 화면은 없다 (`plan.md` §0.6-4). 진입은 전체 현황의 [이동] 뿐이고,
          `projectId` 없이 마운트되면 목록을 대신 그리는 대신 안내만 한다 — 여기서 목록을
          그리면 호스트가 준 진입점을 우회하는 두 번째 경로가 다시 생긴다.
        -->
        <AEmpty
          v-else
          class="wp-py-16"
          description="전체 현황에서 프로젝트를 선택하세요."
        />
      </template>
      <!--
        같은 탭, 계층에 따라 다른 화면 (`plan.md` §0.5-4). 템플릿에서는 전역 문서의 *정의*를
        편집하고, 프로젝트에서는 그 문서의 *사용 여부·링크·작성 상태*를 설정한다. 프로젝트에서
        전역 정의를 고칠 수 있으면 한 설비사 화면이 모든 프로젝트가 공유하는 문서 이름을
        바꿔버린다.
      -->
      <ProjectDocuments v-else-if="tab === 'documents'" />
    </div>

    <StructureManagerModal
      v-if="structureRequest"
      :request="structureRequest"
      @close="structureRequest = null"
    />

    <OwnerManagerModal
      v-if="ownerRequest"
      :request="ownerRequest"
      @close="ownerRequest = null"
    />

    <DocumentManagerModal
      v-if="documentRequest"
      :request="documentRequest"
      @close="documentRequest = null"
    />
  </div>
</template>
