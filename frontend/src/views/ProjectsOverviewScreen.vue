<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Input as AInput,
  Spin as ASpin,
  Tooltip as ATooltip,
} from 'ant-design-vue'
import { describeApiError, type WpApiClient } from '../api/client'
import {
  DOC_WRITE_STATUS_LABEL,
  ITEM_STATUS_LABEL,
  type DocWriteStatus,
  type ItemStatus,
  type MakerOverviewGroup,
  type OverviewDocument,
  type OverviewItem,
  type ProjectOverview,
} from '../api/types'
import {
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  FilePptOutlined,
  PlusOutlined,
  RightOutlined,
} from '@ant-design/icons-vue'
import { buildOverviewGroups } from '../composables/useDashboard'
import ProjectCreateModal from '../components/dashboard/ProjectCreateModal.vue'
import { DASH_STATUS_ORDER, DASH_STATUS_STYLE, DASH_UNASSIGNED } from '../theme/dashboard'
import LegendSwatch from '../components/dashboard/LegendSwatch.vue'
import ItemPopover from '../components/dashboard/ItemPopover.vue'

/**
 * 전체 현황 — 설비사 구획 → 프로젝트 → 미니 대시보드 (`plan.md` §0.5-3, 2026-08-08 개정).
 *
 * The previous version was a flat project list with an unlabelled minimap strip. The
 * revision makes it two levels deep: makers own sections, and each project carries a
 * shrunk-down copy of its own dashboard — `Phase N` bands, milestone sub-groups, one cell
 * per item, no text.
 *
 * As of §0.6 it is also the **project hub**: sections collapse, each carries a
 * `+ 프로젝트 추가` button, and project names are renamed in place. The 프로젝트 메뉴's own
 * list page still exists but is slated for removal, so new affordances land here only.
 *
 * 설비사 설정 is **not** here any more. It became its own expose (`./MakerSettings`) so the
 * host can put it on its own menu — an admin screen reached only by first opening a
 * different screen is one the host cannot place, permission, or link to.
 *
 * **The server groups now** (§0.6). This screen used to bucket a flat `projects` array by
 * `maker_id`, which could only ever surface makers that already had a project — leaving no
 * way to show, let alone start, an empty one. The display rule (설정행 우선, 없으면 active
 * 프로젝트 유무) lives server-side with it.
 *
 * Cells use antd `Tooltip` rather than a native `title`: §0.5-3 asks for a popover with four
 * distinct fields, and a `title` attribute is one untyped line the browser styles. The cost
 * is one wrapper component per item — antd renders the popup itself lazily, so a hidden
 * tooltip is cheap, and `data-wp-cell-hint` carries the same text for `check:dom` so the
 * assertion does not have to simulate a hover.
 */
const props = defineProps<{
  api: WpApiClient
  /** Host-owned navigation into one project. The move icon is hidden without it. */
  onOpenProject?: ((projectId: number, makerId: number) => void) | null
  /** Host permission gate — withdraws 추가 · 이름 수정 · 설비사 설정 (§0.6). */
  readOnly?: boolean
}>()

const makers = shallowRef<MakerOverviewGroup[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

/** Collapsed sections, by maker id. Absent = expanded, so the default is 펼침 (§0.6). */
const collapsed = ref<Set<number>>(new Set())
/** The project whose name is being edited in place, and the draft value. */
const renamingId = ref<number | null>(null)
const renameDraft = ref('')
const busy = ref(false)
/** The maker whose 프로젝트 추가 modal is open. */
const creatingFor = ref<MakerOverviewGroup | null>(null)
/** The live rename field, so entering edit mode can focus it. */
const renameInput = ref<{ input?: HTMLInputElement } | null>(null)

/**
 * Guards the late response of a request whose component is already gone.
 *
 * The exposed component must survive repeated mount/unmount (INTEGRATION.md §5), and this
 * screen issues its one request on mount — unmounting during the round trip would otherwise
 * write to refs nobody is watching.
 */
let live = true

async function load() {
  loading.value = true
  error.value = null
  try {
    const response = await props.api.getProjectsOverview()
    if (!live) return
    makers.value = response.makers ?? []
  } catch (caught) {
    if (!live) return
    error.value = describeApiError(caught, '전체 현황을 불러오지 못했습니다.')
  } finally {
    if (live) loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  live = false
})

const clickable = computed(() => typeof props.onOpenProject === 'function')
const editable = computed(() => !props.readOnly)

const makerLabelOf = (maker: MakerOverviewGroup) =>
  maker.name?.trim() ? maker.name : `설비사 #${maker.maker_id}`

const isCollapsed = (maker: MakerOverviewGroup) => collapsed.value.has(maker.maker_id)

function toggle(maker: MakerOverviewGroup) {
  const next = new Set(collapsed.value)
  if (next.has(maker.maker_id)) next.delete(maker.maker_id)
  else next.add(maker.maker_id)
  collapsed.value = next
}

/**
 * The maker id comes from the **section**, not from `project.maker_id`.
 *
 * They agree today, but the section is what the server grouped by, so it is the authority;
 * reading it off the project would quietly resurrect the client-side grouping §0.6 removed.
 */
function open(maker: MakerOverviewGroup, project: ProjectOverview) {
  props.onOpenProject?.(project.id, maker.maker_id)
}

/**
 * Enters rename mode. The **name text itself** is the trigger (`plan.md` §0.6-4, 2026-08-08).
 *
 * There used to be a pencil icon beside it. Navigation belongs to the move icon, so clicking
 * the name did nothing at all — a click target that looks like a label and behaves like one
 * while the actual affordance hides in a 14px glyph next to it.
 */
function startRename(project: ProjectOverview) {
  if (!editable.value) return
  renamingId.value = project.id
  renameDraft.value = project.name
  // Focus after the input exists; selecting the text makes "type over it" the default.
  void nextTick(() => {
    const input = renameInput.value?.input
    input?.focus()
    input?.select()
  })
}

function cancelRename() {
  renamingId.value = null
  renameDraft.value = ''
}

/**
 * Commits the edit. Reachable three ways — Enter, the ✓ button, and blur — so it has to be
 * idempotent: `renamingId` is cleared first, and a second call for a row that is no longer
 * being edited returns immediately.
 */
async function commitRename(project: ProjectOverview) {
  if (renamingId.value !== project.id) return
  const next = renameDraft.value.trim()
  if (!next || next === project.name) return cancelRename()
  renamingId.value = null
  busy.value = true
  try {
    await props.api.renameProject(project.id, next)
    renameDraft.value = ''
    await load()
  } catch (caught) {
    error.value = describeApiError(caught, '이름을 바꾸지 못했습니다.')
  } finally {
    busy.value = false
  }
}

async function onProjectCreated() {
  creatingFor.value = null
  await load()
}

const progressOf = (project: ProjectOverview) => {
  const total = project.items.length
  return total === 0 ? 0 : Math.round((project.counts.DONE / total) * 100)
}

const groupsOf = (project: ProjectOverview) => buildOverviewGroups(project.items)

const cellStyle = (status: ItemStatus) => {
  const style = DASH_STATUS_STYLE[status] ?? DASH_STATUS_STYLE.NOT_STARTED
  return { backgroundColor: style.bg, borderColor: style.border }
}

/**
 * Card caption for the tooltip.
 *
 * The overview payload carries only `dash_label` — it has no `deliverable` and no `title` to
 * fall back to. The §0.5-1 fallback chain therefore runs **server-side**, and this field
 * arrives already resolved (INTEGRATION.md §7.6). What is left here is the case where the row
 * genuinely has nothing at all in any of the three.
 */
const captionOf = (item: OverviewItem) => item.dash_label?.trim() || '(내용 없음)'

const statusText = (status: ItemStatus) => ITEM_STATUS_LABEL[status] ?? status

const milestoneTextOf = (item: OverviewItem) =>
  item.phase_seq != null && item.milestone_seq != null
    ? `${item.phase_seq}.${item.milestone_seq}`
    : '미배정'

/**
 * The popover's fields, flattened so `check:dom` can assert without simulating a hover.
 *
 * Mirrors the popover exactly, index prefix included — an assertion that described something
 * other than what the user sees would be worse than none.
 */
const cellHint = (item: OverviewItem) =>
  `${item.no}. ${captionOf(item)} · ${milestoneTextOf(item)} · ${statusText(item.status)}`

const CHIP_STATUSES: ItemStatus[] = ['IN_PROGRESS', 'DONE', 'HOLD']

/**
 * Fixed width of 구획 ③ (`plan.md` §0.5-3b).
 *
 * Every row's ④ 문서 링크 area has to start at the same x, and it cannot if the minimap sizes
 * itself to its content — a 12-row project would pull its documents left of a 35-row one and
 * the column would zigzag. So the width is a constant and boards shorter than it simply leave
 * whitespace.
 *
 * Sized for a five-phase board, which is the §0.5-3b brief: 35 cells × 15px, plus the 2px
 * intra-milestone gaps, the 8px gaps between milestone groups and between bands, plus one
 * phase of headroom ≈ 740. Anything larger scrolls **inside** ③ rather than widening the row,
 * so a 60-row board cannot push the documents off screen.
 */
const MINIMAP_WIDTH_PX = 740

/**
 * 문서 상태 색 (`plan.md` §0.5-3b, 2026-08-08 정정).
 *
 * **All three states now draw the same `FilePptOutlined` and differ only in colour.** The
 * first version rendered 작성전 as the words "작성 전" instead of an icon, which made the
 * fourth column a ragged mix of glyphs and text and destroyed the at-a-glance scan the column
 * exists for. Grey is the "not started" signal, exactly as the white cell is on the minimap.
 */
const DOC_STATUS_COLOR: Record<DocWriteStatus, string> = {
  NOT_WRITTEN: '#94a3b8',
  WRITING: '#d97706',
  DONE: '#059669',
}

const isWritten = (doc: OverviewDocument) => doc.doc_status !== 'NOT_WRITTEN'
const canOpen = (doc: OverviewDocument) => isWritten(doc) && !!doc.link_url

/**
 * Opens the cloud document in a new tab.
 *
 * `noopener` is not decoration: without it the opened page gets a live `window.opener`
 * handle back into the **host** application, which is a privilege this module has no business
 * handing out to a link an end user typed into a form.
 */
function openDocument(doc: OverviewDocument) {
  if (!canOpen(doc)) return
  window.open(doc.link_url!, '_blank', 'noopener')
}

/**
 * The order number shown in the badge on the icon's corner.
 *
 * As of `plan.md` §0.5.10 the payload carries `no` outright — it is `sort_order`, renumbered
 * by every apply. The old derivation from a circled `code` character is gone with the code.
 *
 * Document codes are circled numerals (①~⑤), so the badge digit lines up with the code
 * naturally — ① becomes 1. Derived from the character rather than from the array index,
 * because the index would renumber the moment a maker unticks a document: ①③④ would badge
 * as 1·2·3 and stop matching the codes the 문서 설정 screen shows.
 *
 * Falls back to the raw code for a host whose codes are not circled numerals, and to the
 * position only when even that is unusable.
 */
function docBadge(doc: OverviewDocument, index: number): string {
  return String(doc.no ?? index + 1)
}

/** 문서명 · 상태, plus why it cannot be opened when it cannot (§0.5-3b). */
const docTooltip = (doc: OverviewDocument) => {
  const head = `${doc.no}. ${doc.name} — ${DOC_WRITE_STATUS_LABEL[doc.doc_status]}`
  if (!isWritten(doc)) return head
  return doc.link_url ? `${head} · 클릭하면 새 창으로 엽니다` : `${head} · 링크 없음`
}

defineExpose({ reload: load })
</script>

<template>
  <div class="wp-flex wp-h-full wp-flex-col">
    <div class="wp-mb-2 wp-flex wp-items-center wp-gap-3">
      <div class="wp-text-base wp-font-bold" style="color: #1f2937">전체 현황</div>
      <span class="wp-text-xs" style="color: #475569">
        설비사별 프로젝트 진행 상황. 사각형 한 칸이 항목 하나이며, 색 띠는 Phase 입니다.
      </span>
    </div>

    <AAlert v-if="error" type="error" show-icon banner class="wp-mb-2" :message="error" />

    <!--
      페이지는 옅은 배경, 설비사는 그 위의 흰 카드 (`plan.md` §0.6-4 디자인 언어). 직각
      테두리를 나열하던 이전 판이 "각지고 딱딱하다" 는 피드백을 받은 지점이다.
    -->
    <div
      class="wp-relative wp-min-h-0 wp-flex-1 wp-overflow-auto wp-rounded-xl wp-p-3"
      style="background: #f8fafc"
    >
      <AEmpty
        v-if="!loading && makers.length === 0 && !error"
        class="wp-py-16"
        description="표시할 설비사가 없습니다. [설비사 설정] 에서 전체 현황에 표시할 설비사를 선택하세요."
      />

      <!-- 설비사 구획 — 접기/펼치기, 기본 펼침 (§0.6). -->
      <section
        v-for="maker in makers"
        :key="maker.maker_id"
        class="wp-mb-4 wp-rounded-xl wp-p-4"
        data-wp-maker-group
        style="background: #ffffff; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04)"
      >
        <div class="wp-flex wp-items-center wp-gap-2">
          <button
            type="button"
            data-wp-maker-toggle
            class="wp-inline-flex wp-cursor-pointer wp-items-center wp-gap-1.5"
            style="background: none; border: none; padding: 0; font: inherit; color: #0f766e"
            :aria-expanded="!isCollapsed(maker)"
            @click="toggle(maker)"
          >
            <RightOutlined v-if="isCollapsed(maker)" style="font-size: 12px" />
            <DownOutlined v-else style="font-size: 12px" />
            <span class="wp-text-sm wp-font-bold">{{ makerLabelOf(maker) }}</span>
          </button>
          <span class="wp-text-xs" style="color: #475569">
            프로젝트 {{ maker.projects.length }}
          </span>
          <span style="flex: 1"></span>
          <AButton
            v-if="editable"
            size="small"
            type="primary"
            ghost
            data-wp-add-project
            @click="creatingFor = maker"
          >
            <PlusOutlined /> 프로젝트 추가
          </AButton>
        </div>

        <!-- 체크된 설비사는 프로젝트가 0개여도 섹션이 온다 (§0.6). -->
        <div
          v-if="!isCollapsed(maker) && maker.projects.length === 0"
          class="wp-ml-6 wp-mt-3 wp-rounded-xl wp-border wp-border-dashed wp-p-5 wp-text-center wp-text-xs"
          data-wp-maker-empty
          style="border-color: #cbd5e1; color: #64748b; background: #f8fafc"
        >
          아직 프로젝트가 없습니다.
          <template v-if="editable">[＋ 프로젝트 추가] 로 첫 프로젝트를 만드세요.</template>
        </div>

        <!--
          프로젝트 행은 헤더보다 **들여쓴다** (§0.6-4) — 카드 안에서 하위 항목임이 위계가 아니라
          형태로 드러나야 한다. 행 사이는 간격 + 옅은 구분선 둘 다: 간격만으로는 미니 대시보드가
          큰 행에서 경계가 흐려지고, 선만으로는 다시 각져 보인다.
        -->
        <div
          v-for="(project, index) in (isCollapsed(maker) ? [] : maker.projects)"
          :key="project.id"
          class="wp-ml-6 wp-rounded-lg wp-px-3 wp-py-3"
          data-wp-overview-row
          :class="index > 0 ? 'wp-mt-2 wp-border-t wp-border-solid' : 'wp-mt-3'"
          style="border-color: #f1f5f9"
        >
          <!--
            4구획 (§0.5-3b). Fixed track widths, not `flex-wrap`: ④ 의 시작점이 모든 행에서
            같은 x 에 있어야 하고, 내용에 맞춰 늘어나는 트랙으로는 그것이 불가능하다.
          -->
          <!--
            5구획 (§0.5-3b, 2026-08-08 정정 — 이동 버튼이 마지막 칸으로 나왔다), **세로 가운데
            정렬**. `items-start` 로 두면 미니 대시보드가 가장 높아 나머지가 전부 위쪽에 붙어
            읽기 어렵다. 트랙 폭이 전부 고정이라 ⑤ 도 모든 행에서 같은 x 에 선다.
          -->
          <div
            class="wp-grid wp-items-center wp-gap-3"
            :style="{ gridTemplateColumns: `240px 190px ${MINIMAP_WIDTH_PX}px minmax(170px, 1fr) 88px` }"
          >
            <!-- ① 프로젝트명 + 인라인 수정 + 이동 아이콘 -->
            <div class="wp-flex wp-items-center wp-gap-1.5" data-wp-col-name>
              <template v-if="renamingId === project.id">
                <AInput
                  ref="renameInput"
                  v-model:value="renameDraft"
                  size="small"
                  data-wp-rename-input
                  :disabled="busy"
                  @press-enter="commitRename(project)"
                  @keyup.esc="cancelRename"
                  @blur="commitRename(project)"
                />
                <!--
                  `mousedown.prevent` on both buttons: without it the input blurs first, the
                  blur commits, and 취소 arrives too late to cancel anything.
                -->
                <button
                  type="button"
                  data-wp-rename-commit
                  aria-label="이름 저장"
                  class="wp-inline-flex wp-cursor-pointer wp-items-center"
                  style="background: none; border: none; padding: 2px; color: #059669"
                  @mousedown.prevent
                  @click="commitRename(project)"
                >
                  <CheckOutlined />
                </button>
                <button
                  type="button"
                  data-wp-rename-cancel
                  aria-label="취소"
                  class="wp-inline-flex wp-cursor-pointer wp-items-center"
                  style="background: none; border: none; padding: 2px; color: #94a3b8"
                  @mousedown.prevent
                  @click="cancelRename"
                >
                  <CloseOutlined />
                </button>
              </template>
              <template v-else>
              <!--
                이름 텍스트 자체가 수정 진입점이다 (§0.6-4, 2026-08-08). hover 시 점선 밑줄이
                드러나 편집 가능함을 알린다 — `hover:` 변형이라 별도 스타일 블록이 필요 없고,
                호스트로 새는 전역 규칙도 만들지 않는다.
              -->
              <ATooltip :title="editable ? '클릭해 이름 수정' : undefined">
                <span
                  data-wp-rename-project
                  class="wp-truncate wp-text-sm wp-font-semibold wp-border-0 wp-border-b wp-border-dashed wp-border-transparent"
                  :class="editable ? 'wp-cursor-pointer hover:wp-border-slate-400' : ''"
                  style="color: #0f172a"
                  @click="startRename(project)"
                >
                  {{ project.name }}
                </span>
              </ATooltip>
              </template>
            </div>

            <!-- ② 진행률 · 상태 집계 -->
            <div class="wp-flex wp-flex-wrap wp-items-center wp-gap-1" data-wp-col-counts>
              <span class="wp-w-full wp-text-xs wp-font-medium" style="color: #334155">
                전체 {{ project.items.length }}개 · 진행률 {{ progressOf(project) }}%
              </span>
              <span
                v-for="status in CHIP_STATUSES"
                :key="status"
                class="wp-inline-flex wp-items-center wp-gap-1 wp-rounded-full wp-border wp-border-solid wp-px-2 wp-py-0.5 wp-text-xs"
                :style="{
                  backgroundColor: DASH_STATUS_STYLE[status].bg,
                  borderColor: DASH_STATUS_STYLE[status].border,
                  color: DASH_STATUS_STYLE[status].text,
                }"
              >
                {{ ITEM_STATUS_LABEL[status] }} <b>{{ project.counts[status] }}</b>
              </span>
            </div>

            <!--
              ③ 미니 대시보드 — 고정 너비. 넘치면 이 안에서만 가로 스크롤하고 행을 넓히지
              않는다. `wp-flex-wrap` 이 아니라 `nowrap` 인 이유도 같다: 줄바꿈하면 행 높이가
              프로젝트마다 달라져 ④ 가 다시 어긋난다.
            -->
            <div
              class="wp-flex wp-items-start wp-gap-2 wp-overflow-x-auto"
              data-wp-col-minimap
              :style="{ width: `${MINIMAP_WIDTH_PX}px` }"
            >
            <div v-for="group in groupsOf(project)" :key="group.key" data-wp-phase-band>
              <div
                class="wp-truncate wp-rounded-sm wp-px-1.5 wp-py-0.5 wp-text-center wp-text-2xs wp-font-bold"
                :style="{
                  backgroundColor: group.color ?? DASH_UNASSIGNED,
                  color: group.color ? '#ffffff' : '#475569',
                }"
              >
                {{ group.label }}
              </div>
              <div class="wp-mt-1 wp-flex wp-items-start wp-gap-2">
                <!-- 마일스톤 소그룹 — 라벨은 hover 로만 (§0.5-3). -->
                <div
                  v-for="milestone in group.milestones"
                  :key="milestone.key"
                  class="wp-flex wp-gap-0.5"
                  data-wp-milestone-group
                  :title="milestone.label || '미배정'"
                >
                  <!--
                    프로젝트 대시보드와 **같은 팝오버** (§0.5-3, 2026-08-08). 이전에는 여기만
                    한 줄 툴팁이라, 같은 항목이 어느 화면에서 보느냐에 따라 다른 것을 말했다.
                  -->
                  <ItemPopover
                    v-for="item in milestone.items"
                    :key="item.no"
                    :index="item.no"
                    :title="item.title"
                    :deliverable="item.deliverable"
                    :owners="item.owners"
                    :status="item.status"
                  >
                    <div
                      class="wp-rounded-sm wp-border wp-border-solid"
                      data-wp-minimap-cell
                      :data-wp-cell-hint="cellHint(item)"
                      style="width: 15px; height: 15px"
                      :style="cellStyle(item.status)"
                    ></div>
                  </ItemPopover>
                </div>
              </div>
            </div>
            </div>

            <!-- ④ 문서 링크 (§0.5-3b / §0.5-4). 사용 체크된 것만 서버가 보낸다. -->
            <div class="wp-flex wp-flex-wrap wp-items-center wp-gap-1.5" data-wp-col-documents>
              <span
                v-if="project.documents.length === 0"
                class="wp-text-xs"
                style="color: #64748b"
              >
                사용 문서 없음
              </span>
              <ATooltip
                v-for="(doc, docIndex) in project.documents"
                :key="doc.id"
                :title="docTooltip(doc)"
              >
                <!--
                  작성전은 아이콘 없이 '작성 전' 글자로 (§0.5-3b) — 아이콘을 주면 열 수 있어
                  보인다. 작성중·완료는 아이콘 + 코드이며, 링크가 없으면 색만 유지한 채
                  클릭 불가로 둔다.
                -->
                <button
                  type="button"
                  data-wp-doc-chip
                  :data-wp-doc-status="doc.doc_status"
                  :data-wp-doc-openable="canOpen(doc) ? 'yes' : 'no'"
                  :disabled="!canOpen(doc)"
                  class="wp-relative wp-inline-flex wp-items-center wp-rounded-lg wp-border wp-border-solid wp-p-1.5"
                  :style="{
                    background: '#ffffff',
                    borderColor: DOC_STATUS_COLOR[doc.doc_status],
                    color: DOC_STATUS_COLOR[doc.doc_status],
                    cursor: canOpen(doc) ? 'pointer' : 'default',
                  }"
                  @click="openDocument(doc)"
                >
                  <!-- 세 상태 같은 아이콘, 색으로만 구분 (§0.5-3b 정정). 크기는 본문 이상. -->
                  <FilePptOutlined style="font-size: 18px" />
                  <!--
                    순서는 아이콘 옆 텍스트가 아니라 **모서리 배지**로 (§0.5-3b, 2026-08-08).
                    배지는 중립색이다 — 상태는 아이콘 색이 말하므로, 배지까지 물들이면 두 신호가
                    같은 것을 두 번 말하면서 서로의 대비를 깎는다.
                  -->
                  <span
                    data-wp-doc-badge
                    class="wp-absolute wp-inline-flex wp-items-center wp-justify-center wp-rounded-full wp-border wp-border-solid wp-font-semibold"
                    style="
                      top: -5px;
                      right: -5px;
                      width: 14px;
                      height: 14px;
                      font-size: 9px;
                      line-height: 1;
                      background: #ffffff;
                      border-color: #cbd5e1;
                      color: #475569;
                    "
                  >
                    {{ docBadge(doc, docIndex) }}
                  </span>
                </button>
              </ATooltip>
            </div>

            <!--
              ⑤ 이동 — **텍스트 버튼**이다 (§0.5-3b, 2026-08-08 정정). 이름 옆의 16px 아이콘은
              이 행에서 가장 자주 쓰이는 동작치고는 너무 작고, 문서 칩 아이콘들과도 헷갈렸다.
              콜백이 없으면 렌더하지 않는다 — 이 패키지는 목적지를 지어내지 않는다.
            -->
            <div class="wp-flex wp-items-center wp-justify-end" data-wp-col-open>
              <AButton
                v-if="clickable"
                type="primary"
                size="small"
                data-wp-open-project
                @click="open(maker, project)"
              >
                이동
              </AButton>
            </div>
          </div>
        </div>
      </section>

      <div
        v-if="loading"
        class="wp-absolute wp-inset-0 wp-z-10 wp-flex wp-items-center wp-justify-center"
        style="background: rgba(255, 255, 255, 0.6)"
      >
        <ASpin />
      </div>
    </div>

    <ProjectCreateModal
      v-if="creatingFor"
      :api="props.api"
      :maker-id="creatingFor.maker_id"
      :maker-label="makerLabelOf(creatingFor)"
      @created="onProjectCreated"
      @cancel="creatingFor = null"
    />

    <div
      class="wp-mt-1 wp-flex wp-flex-wrap wp-items-center wp-gap-x-4 wp-gap-y-1 wp-text-xs"
      style="color: #475569"
    >
      <!--
        같은 `LegendSwatch` 를 쓰되 **좌측 바가 없다**. 이 화면의 미니 대시보드 셀에는 주관 바가
        없기 때문이다 — overview payload 는 owner 를 싣지 않는다. 바가 그려진 스와치를 여기에
        두면 존재하지 않는 셀을 설명하게 된다. 그래서 주관 범례도 없다.
      -->
      <b data-wp-legend-group="status" style="color: #334155">상태 (배경)</b>
      <span
        v-for="status in DASH_STATUS_ORDER"
        :key="status"
        class="wp-inline-flex wp-items-center wp-gap-1"
      >
        <LegendSwatch
          :bg="DASH_STATUS_STYLE[status].bg"
          :border="DASH_STATUS_STYLE[status].border"
        />
        {{ ITEM_STATUS_LABEL[status] }}
      </span>
      <span v-if="!clickable" class="wp-ml-2">
        (호스트가 <code>onOpenProject</code> 를 전달하지 않아 프로젝트명 클릭은 동작하지 않습니다)
      </span>
    </div>
  </div>
</template>
