<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import type {
  CellClassParams,
  CellClickedEvent,
  ColDef,
  GridApi,
  GridReadyEvent,
  RowClassParams,
  RowDragEndEvent,
  ValueSetterParams,
} from 'ag-grid-community'
import { AgGridVue } from 'ag-grid-vue3'
import { Button as AButton, Modal as AModal } from 'ant-design-vue'
import {
  ITEM_STATUS_LABEL,
  visibleDocuments,
  type ItemStatus,
  type OwnerRef,
  type WpItem,
} from '../../api/types'
import { useBoardContext } from '../../runtime/context'
import {
  BLOCK_DRAG_REFUSED,
  BLOCK_DRAG_SOLE_ROW,
  canDragRow,
  isWithinBlockOrder,
} from '../../composables/useBlockDrag'
import { phaseColor } from '../../theme/palette'
import { wpGridTheme } from '../../theme/agTheme'
import MilestoneCellEditor from './MilestoneCellEditor.vue'
import MilestoneCellRenderer from './MilestoneCellRenderer.vue'
import PhaseCellEditor from './PhaseCellEditor.vue'
import PhaseCellRenderer from './PhaseCellRenderer.vue'
import RowActionRenderer from './RowActionRenderer.vue'
import StatusCellRenderer from './StatusCellRenderer.vue'
import TagListRenderer from './TagListRenderer.vue'
import DateCellEditor from './DateCellEditor.vue'
import ClampCellRenderer from './ClampCellRenderer.vue'

const { board, notify, popupContainer, structure, ownerPicker, documentPicker } =
  useBoardContext()

/**
 * §0.3 — an assigned row's membership cells are **locked**.
 *
 * With drag confined to blocks, the cell editor was the last remaining way for a row to
 * move somewhere the user did not intend, and the user asked for it closed.
 *
 * "Locked" means genuinely not editable — no editor opens — rather than an editor that
 * refuses. A click offers a choice of the two things that *are* available (§0.4):
 *
 *  - **수정** — the Phase/Milestone 관리 팝업, for renaming, reordering or deleting the block
 *    this row belongs to;
 *  - **재배치** — 미배정으로 전환, which grays the row in place so it can be reassigned through
 *    the ordinary gray-row flow.
 */
const phaseEditable = (item: WpItem | undefined) => editable.value && item?.phase_id == null
const milestoneEditable = (item: WpItem | undefined) =>
  editable.value && item?.phase_id != null && item?.milestone_id == null

const LOCKED_HINT =
  '배정된 소속은 셀에서 직접 바꿀 수 없습니다. 클릭해 [수정](관리 창) 또는 [재배치](미배정 전환)를 고르세요.'

/**
 * The [수정] / [재배치] / [취소] choice a locked membership cell offers (`plan.md` §0.4).
 *
 * A three-way choice, so it is a Modal with its own footer rather than `modal.confirm` —
 * antd's confirm has exactly two buttons, and squeezing a third action into 취소 is how a
 * destructive default gets picked by accident.
 */
const choice = ref<{ item: WpItem; level: 'phase' | 'milestone' } | null>(null)

function closeChoice() {
  choice.value = null
}

function openManagerFromCell() {
  const current = choice.value
  closeChoice()
  if (!current) return
  structure.open(
    current.level === 'phase'
      ? { kind: 'phase' }
      : { kind: 'milestone', phaseId: current.item.phase_id },
  )
}

function unassignFromCell() {
  const current = choice.value
  closeChoice()
  if (current) void board.unassign(current.item.id)
}

/**
 * A click on a locked membership cell. ag-grid opens nothing for a non-editable cell, so
 * this is where the §0.4 choice lives.
 */
function onCellClicked(event: CellClickedEvent<WpItem>) {
  const item = event.data
  if (!item || !editable.value || board.saving.value) return
  const column = event.column.getColId()
  if (column === 'phase_id' && item.phase_id != null) choice.value = { item, level: 'phase' }
  if (column === 'milestone_id' && item.milestone_id != null) {
    choice.value = { item, level: 'milestone' }
  }
  if (column === 'owners') ownerPicker.open({ itemId: item.id })
  if (column === 'documents') documentPicker.open({ itemId: item.id })
}

const gridApi = shallowRef<GridApi<WpItem> | null>(null)
const host = ref<HTMLElement | null>(null)
const flashTimer = ref<number | null>(null)

const editable = computed(() => !board.readOnly.value)

const components = {
  PhaseCellRenderer,
  MilestoneCellRenderer,
  StatusCellRenderer,
  TagListRenderer,
  ClampCellRenderer,
  RowActionRenderer,
  PhaseCellEditor,
  MilestoneCellEditor,
  DateCellEditor,
}

/** Marks a cell the last publish attempt rejected (`plan.md` §2.5 response shape). */
const hasError = (params: CellClassParams<WpItem>, field: string) =>
  !!params.data && (board.errorFields.value.get(params.data.id)?.has(field) ?? false)

const errorRule = (field: string) => ({
  'wp-cell-error': (params: CellClassParams<WpItem>) => hasError(params, field),
})

function patch(params: ValueSetterParams<WpItem>, patchValue: Partial<WpItem>): boolean {
  if (!params.data) return false
  board.patchItem(params.data.id, patchValue)
  return true
}

const columnDefs = computed<ColDef<WpItem>[]>(() => [
  {
    colId: 'drag',
    headerName: '',
    width: 34,
    minWidth: 34,
    maxWidth: 34,
    // A per-row callback, not a flag: a row with nowhere legal to go gets no handle. ag-grid
    // keeps the column's width and merely hides the icon (`ag-invisible`) when `rowDrag` is
    // a function, so the grid does not jump. Re-evaluated whenever a row's data object is
    // replaced, which every mutation does.
    //
    // Gray rows always qualify — they may be dropped anywhere (`plan.md` §0.2.2), and that
    // freedom is the whole mechanism for opening a new Phase between two existing ones.
    rowDrag: editable.value ? (params) => canDragRow(board.items.value, params.data) : false,
    sortable: false,
    resizable: false,
    // The grab cursor and the tooltip follow the handle, so a row that cannot be dragged
    // does not advertise that it can and still says why when asked.
    cellClass: (params: CellClassParams<WpItem>) =>
      editable.value && canDragRow(board.items.value, params.data) ? 'wp-cursor-grab' : '',
    tooltipValueGetter: (params) =>
      !editable.value || canDragRow(board.items.value, params.data) ? '' : BLOCK_DRAG_SOLE_ROW,
  },
  {
    colId: 'no',
    headerName: 'No',
    width: 58,
    minWidth: 58,
    valueGetter: (p) => p.data?.row_no,
    cellClass: 'wp-text-center wp-text-xs',
    editable: false,
  },
  {
    colId: 'phase_id',
    headerName: 'Phase',
    width: 210,
    valueGetter: (p) => p.data?.phase_display ?? '',
    cellRenderer: 'PhaseCellRenderer',
    cellEditor: 'PhaseCellEditor',
    cellEditorPopup: true,
    cellEditorPopupPosition: 'under',
    // Per row, not per grid: only an unassigned row's phase may be picked (§0.3).
    editable: (params) => phaseEditable(params.data),
    tooltipValueGetter: (params) =>
      editable.value && params.data?.phase_id != null ? LOCKED_HINT : '',
    cellClassRules: {
      ...errorRule('phase_id'),
      'wp-cell-locked': (params: CellClassParams<WpItem>) =>
        editable.value && params.data?.phase_id != null,
    },
  },
  {
    colId: 'milestone_id',
    headerName: 'Milestone',
    width: 220,
    valueGetter: (p) => p.data?.milestone_display ?? '',
    cellRenderer: 'MilestoneCellRenderer',
    cellEditor: 'MilestoneCellEditor',
    cellEditorPopup: true,
    cellEditorPopupPosition: 'under',
    // Open only once a phase exists and while the milestone is still unset (§0.3).
    editable: (params) => milestoneEditable(params.data),
    tooltipValueGetter: (params) =>
      editable.value && params.data?.milestone_id != null ? LOCKED_HINT : '',
    cellClassRules: {
      ...errorRule('milestone_id'),
      'wp-cell-locked': (params: CellClassParams<WpItem>) =>
        editable.value && params.data?.milestone_id != null,
    },
  },
  {
    colId: 'title',
    headerName: 'Key Action Item',
    flex: 2,
    minWidth: 260,
    valueGetter: (p) => p.data?.title ?? '',
    valueSetter: (p) => patch(p, { title: String(p.newValue ?? '') }),
    editable: editable.value,
    cellEditor: 'agLargeTextCellEditor',
    cellEditorPopup: true,
    cellEditorParams: { rows: 6, cols: 60, maxLength: 2000 },
    // 세로 가운데 정렬 (§0.5.9): 셀이 flex 박스가 되고 클램프는 렌더러 안쪽 span 이 맡는다.
    cellRenderer: 'ClampCellRenderer',
    cellClass: 'wp-cell-mid',
    tooltipValueGetter: (p) => p.data?.title ?? '',
    cellClassRules: errorRule('title'),
  },
  {
    colId: 'deliverable',
    headerName: 'Deliverable (Check Point)',
    flex: 1,
    minWidth: 180,
    valueGetter: (p) => p.data?.deliverable ?? '',
    valueSetter: (p) => patch(p, { deliverable: String(p.newValue ?? '') }),
    editable: editable.value,
    cellEditor: 'agTextCellEditor',
    cellRenderer: 'ClampCellRenderer',
    cellClass: 'wp-cell-mid',
    tooltipValueGetter: (p) => p.data?.deliverable ?? '',
    cellClassRules: errorRule('deliverable'),
  },
  {
    colId: 'dash_label',
    headerName: '대시보드 표시',
    width: 150,
    // 대시보드 카드는 몇 단어 폭이라 제목 전문을 자르면 읽히지 않는다 (`plan.md` §0.5-1).
    // 서버 컬럼이 VARCHAR(60) 이므로 편집기에서 같은 길이로 자른다.
    valueGetter: (p) => p.data?.dash_label ?? '',
    valueSetter: (p) => patch(p, { dash_label: String(p.newValue ?? '').slice(0, 60) || null }),
    editable: editable.value,
    cellEditor: 'agTextCellEditor',
    cellEditorParams: { maxLength: 60 },
    // 짧은 한 줄이라 클램프가 필요 없다 — 셀만 flex 로 두면 텍스트 노드가 가운데로 온다.
    cellClass: 'wp-cell-mid wp-text-xs',
    tooltipValueGetter: (p) =>
      p.data?.dash_label ? p.data.dash_label : '대시보드 카드에 표시할 요약 (비우면 Deliverable)',
  },
  {
    colId: 'documents',
    headerName: '관련 문서',
    width: 200,
    // 표시는 숫자다 (`plan.md` §0.5.10) — 원문자 코드는 모델에서 사라졌다.
    // 렌더러와 **같은 술어**를 쓴다 — 규칙을 두 번 적으면 한쪽만 검사에 덮인다 (§0.5.10).
    valueGetter: (p) =>
      visibleDocuments(p.data?.documents ?? [])
        .map((d) => `${d.no}. ${d.name}`)
        .join(', '),
    cellRenderer: 'TagListRenderer',
    cellRendererParams: { source: 'documents' },
    /*
     * Owner 셀과 같은 이유로 인라인 에디터가 아니라 셸의 팝업이다 (§0.5.10): 선택과 문서
     * 기준정보 관리를 한 창에서 하므로, ag-grid 편집기가 닫히면 사라지는 자리에 둘 수 없다.
     */
    editable: false,
    cellClass: 'wp-cell-mid',
    cellClassRules: errorRule('documents'),
    tooltipValueGetter: () => (editable.value ? '클릭해 관련 문서를 선택하거나 관리합니다.' : ''),
  },
  {
    colId: 'owners',
    headerName: 'Owner',
    width: 180,
    valueGetter: (p) => (p.data?.owners ?? []).map((o) => o.name).join(' + '),
    valueSetter: (p) => patch(p, { owners: p.newValue as OwnerRef[] }),
    cellRenderer: 'TagListRenderer',
    cellRendererParams: { source: 'owners' },
    /*
     * 인라인 에디터가 아니라 **팝업**이다 (`plan.md` §0.5.9). 선택과 Owner 기준정보 관리를
     * 한 창에서 하므로, ag-grid 편집기가 닫히는 순간 사라지는 자리에 둘 수 없다 — 그래서
     * 셀은 편집 불가로 두고 클릭이 셸의 모달을 연다 (Phase/Milestone 셀과 같은 방식, §0.4).
     */
    editable: false,
    cellClass: 'wp-cell-mid',
    cellClassRules: errorRule('owners'),
    tooltipValueGetter: () => (editable.value ? '클릭해 Owner 를 선택하거나 관리합니다.' : ''),
  },
  {
    colId: 'status',
    headerName: 'Status',
    width: 110,
    valueGetter: (p) => p.data?.status ?? 'NOT_STARTED',
    valueSetter: (p) => patch(p, { status: p.newValue as ItemStatus }),
    valueFormatter: (p) => ITEM_STATUS_LABEL[p.value as ItemStatus] ?? '',
    cellRenderer: 'StatusCellRenderer',
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: Object.keys(ITEM_STATUS_LABEL) },
    editable: editable.value,
  },
  {
    colId: 'completion_date',
    headerName: '완료일',
    width: 118,
    valueGetter: (p) => p.data?.completion_date ?? '',
    valueSetter: (p) => patch(p, { completion_date: (p.newValue as string | null) || null }),
    cellEditor: 'DateCellEditor',
    cellEditorPopup: true,
    editable: editable.value,
    cellClass: 'wp-text-xs',
  },
  {
    colId: 'actions',
    headerName: '작업',
    width: 92,
    minWidth: 92,
    pinned: 'right',
    sortable: false,
    resizable: false,
    editable: false,
    hide: !editable.value,
    cellRenderer: 'RowActionRenderer',
  },
])

/**
 * Must stay `false`. ag-grid dispatches `rowDragEnd` *before* applying the drop, so with
 * this on {@link onRowDragEnd} would read the pre-drag order back out and wave every
 * cross-block drag through.
 */
const SUPPRESS_MOVE_WHEN_DRAGGING = false

const defaultColDef: ColDef<WpItem> = {
  resizable: true,
  sortable: false,
  suppressMovable: true,
  suppressHeaderMenuButton: true,
}

/** Phase colour banding — the Community-safe stand-in for Row Grouping (`plan.md` §5.3). */
function getRowStyle(params: RowClassParams<WpItem>) {
  const color = phaseColor(params.data?.phase_no)
  return {
    backgroundColor: params.data?.is_phase_block_start ? color.tintStrong : color.tint,
  }
}

function getRowClass(params: RowClassParams<WpItem>) {
  // 회색 행 (`plan.md` §0.2) reads as unassigned at a glance; it is never *also* a phase
  // block start, because it has no phase to start.
  if (params.data && params.data.phase_id == null) return 'wp-row-unassigned'
  return params.data?.is_phase_block_start ? 'wp-row-phase-start' : ''
}

function onGridReady(event: GridReadyEvent<WpItem>) {
  gridApi.value = event.api
}

/**
 * Managed row drag, confined to the row's own Phase·Milestone block (`plan.md` §2.2).
 *
 * ag-grid has already reordered its own view by the time this fires — `rowDragEnd` is
 * dispatched before the drop is applied only when `suppressMoveWhenRowDragging` is on, and
 * it is deliberately off here so the resulting order can be read back. Community offers no
 * hook to veto a drop mid-drag, so the refusal happens here: the store is still the truth,
 * so pushing its rows back into the grid undoes the move, and nothing was sent.
 */
function onRowDragEnd(event: RowDragEndEvent<WpItem>) {
  const ordered: number[] = []
  event.api.forEachNodeAfterFilterAndSort((node) => {
    if (node.data) ordered.push(node.data.id)
  })

  const current = board.items.value
  if (!isWithinBlockOrder(current, ordered)) {
    // A fresh array, so ag-grid's immutable row-data path sees an order that disagrees
    // with the one the drag left behind and rebuilds it. Same objects, so nothing repaints
    // beyond the move being undone.
    event.api.setGridOption('rowData', current.slice())
    notify.warn(BLOCK_DRAG_REFUSED)
    return
  }

  // Only the resulting order is sent — not membership, and not which row moved. Each row
  // keeps its own phase/milestone server-side; position is the whole payload.
  void board.applyReorder(ordered)
}

/*
 * Full redraw after the grid ingests a new item list.
 *
 * ag-grid's change detection repaints a cell only when its **value** changes, but the
 * Phase/Milestone renderers (label vs 〃), the phase colour banding and the drag-handle
 * visibility all depend on flags *outside* the cell value (`is_*_block_start`,
 * `canDragRow`). Concretely: 미배정으로 전환 on a block's first row makes the next row the
 * new block start — its `milestone_display` is unchanged, so without this redraw the cell
 * keeps rendering the stale 〃 and the block's label silently disappears from the board
 * (user-reported, 2026-08-08).
 *
 * This hangs off ag-grid's own `rowDataUpdated` event, NOT a Vue watch on
 * `board.items.value`: the watch fires before ag-grid has processed the new `rowData`
 * prop, so a redraw there repaints from the **old** rows and the stale 〃 survives —
 * observed directly when this fix was first written as a watch. The event fires after
 * ingestion, which is the only ordering that works. `redrawRows` re-evaluates renderers,
 * rowStyle and rowDrag; at 35-ish rows the cost is irrelevant, and mutations only land
 * after editing ends, so no editor gets torn down mid-keystroke.
 */
function onRowDataUpdated(event: { api: GridApi<WpItem> }) {
  event.api.redrawRows()
}

// Cell error decoration is derived from store state ag-grid cannot observe on its own.
watch(
  () => board.errorFields.value,
  () => gridApi.value?.refreshCells({ force: true }),
)

watch(
  () => board.readOnly.value,
  () => gridApi.value?.refreshCells({ force: true }),
)

/** Jumps to and flashes the row a publish error points at (`plan.md` §5.4). */
function focusItem(itemId: number) {
  const api = gridApi.value
  if (!api) return
  const node = api.getRowNode(String(itemId))
  if (!node) return
  api.ensureNodeVisible(node, 'middle')

  // The flash is a class on ag-grid's own row element, so it has to be found in the DOM;
  // scoped to this grid's host so a second board mounted alongside is unaffected.
  requestAnimationFrame(() => {
    const element = host.value?.querySelector(`.ag-row[row-id="${itemId}"]`)
    if (!element) return
    element.classList.add('wp-row-flash')
    if (flashTimer.value != null) window.clearTimeout(flashTimer.value)
    flashTimer.value = window.setTimeout(() => {
      element.classList.remove('wp-row-flash')
      flashTimer.value = null
    }, 1900)
  })
}

/*
 * `exportCsv()` 가 여기 있었다 — 제거됐다 (`plan.md` §0.5.7).
 *
 * 내보내기는 백엔드 openpyxl 의 XLSX 다. ag-grid Community 의 CSV 로는 원본 엑셀 양식(헤더
 * 스타일·Phase 색 밴딩·freeze·Doc Status 시트)을 낼 수 없고, §0.5.7 은 내보낸 파일이
 * `parse_workbook` 으로 다시 읽히기까지 요구한다.
 */

onBeforeUnmount(() => {
  if (flashTimer.value != null) window.clearTimeout(flashTimer.value)
  flashTimer.value = null
  gridApi.value = null
})

defineExpose({ focusItem })
</script>

<template>
  <div
    ref="host"
    data-wp-board-grid
    class="wp-grid-host"
    :class="{ 'wp-grid-readonly': !editable }"
    style="height: 100%"
  >
    <!--
      `rowDragManaged` is an initial grid option, so the grid is rebuilt when the version
      switches between DRAFT (editable) and PUBLISHED/ARCHIVED (read-only).
    -->
    <AgGridVue
      :key="editable ? 'edit' : 'read'"
      style="width: 100%; height: 100%"
      :theme="wpGridTheme"
      :columnDefs="columnDefs"
      :defaultColDef="defaultColDef"
      :rowData="board.items.value"
      :components="components"
      :getRowId="(p: { data: WpItem }) => String(p.data.id)"
      :getRowStyle="getRowStyle"
      :getRowClass="getRowClass"
      :rowDragManaged="editable"
      :suppressMoveWhenRowDragging="SUPPRESS_MOVE_WHEN_DRAGGING"
      :animateRows="true"
      :singleClickEdit="true"
      :stopEditingWhenCellsLoseFocus="true"
      :suppressCellFocus="!editable"
      :tooltipShowDelay="400"
      :overlayNoRowsTemplate="'<span style=&quot;color:#8c8c8c&quot;>행이 없습니다.</span>'"
      @grid-ready="onGridReady"
      @cell-clicked="onCellClicked"
      @row-drag-end="onRowDragEnd"
      @row-data-updated="onRowDataUpdated"
    />

    <!-- §0.4 — three actions, so a custom footer rather than antd's two-button confirm. -->
    <AModal
      :open="choice != null"
      :title="choice?.level === 'phase' ? 'Phase 셀' : 'Milestone 셀'"
      :width="460"
      :get-container="popupContainer"
      @cancel="closeChoice"
    >
      <p class="wp-mb-1">
        이 행은 이미
        <b>{{
          choice?.level === 'phase' ? choice?.item.phase_display : choice?.item.milestone_display
        }}</b>
        에 속해 있습니다. 무엇을 할까요?
      </p>
      <ul class="wp-mt-2 wp-text-xs" style="color: #8c8c8c">
        <li>· <b>수정</b> — {{ choice?.level === 'phase' ? 'Phase' : 'Milestone' }} 관리 창에서 이름·순서·삭제를 편집합니다.</li>
        <li>· <b>재배치</b> — 이 행만 미배정(회색) 행으로 되돌립니다. 위치는 그대로이며, 이후 원하는 곳에 다시 지정할 수 있습니다.</li>
      </ul>
      <template #footer>
        <AButton @click="closeChoice">취소</AButton>
        <AButton @click="unassignFromCell">재배치</AButton>
        <AButton type="primary" @click="openManagerFromCell">수정</AButton>
      </template>
    </AModal>
  </div>
</template>
