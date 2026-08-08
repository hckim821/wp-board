<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import type { CellClassParams, ColDef, GridApi, GridReadyEvent } from 'ag-grid-community'
import { AgGridVue } from 'ag-grid-vue3'
import { Alert as AAlert, Button as AButton, Spin as ASpin } from 'ant-design-vue'
import { describeApiError, type WpApiClient } from '../../api/client'
import { isValidLinkUrl, type ProjectLink } from '../../api/types'
import { ensureAgGridModules, wpGridTheme } from '../../theme/agTheme'
import LinkOpenRenderer from './LinkOpenRenderer.vue'
import LinkDeleteRenderer from './LinkDeleteRenderer.vue'

/**
 * 주요 링크 — the editable table under the project dashboard (`plan.md` §0.5.5).
 *
 * Ordinary **managed row drag**, not `useBlockDrag`. That composable exists to confine a
 * board row to its Phase·Milestone block; links have no blocks, so confinement here would be
 * a rule with nothing to enforce. Array order is `sort_order` and the whole list is replaced
 * on save, which is why reordering needs no endpoint of its own.
 *
 * URL validation is duplicated from the server on purpose: the server answers 422 and that is
 * the authority, but a user who mistypes a link should see it while typing rather than on
 * submit. `isValidLinkUrl` is the single expression both the cell decoration and the save
 * guard use — and the mock server uses it too, so the two cannot drift.
 */
const props = defineProps<{
  api: WpApiClient
  projectId: number
  readOnly?: boolean
}>()

const rows = shallowRef<ProjectLink[]>([])
const baseline = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const gridApi = shallowRef<GridApi<ProjectLink> | null>(null)

let live = true
/** Local ids for rows that do not exist server-side yet. Negative so they cannot collide. */
let nextLocalId = -1

const editable = computed(() => !props.readOnly)

const fingerprint = (list: readonly ProjectLink[]) =>
  JSON.stringify(list.map((l) => [l.id, l.description, l.url]))

const dirty = computed(() => fingerprint(rows.value) !== baseline.value)

/** Every row that would be refused, so the button can say how many rather than just refuse. */
const invalidRows = computed(() =>
  rows.value.filter((l) => !l.description.trim() || !isValidLinkUrl(l.url)),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const response = await props.api.listProjectLinks(props.projectId)
    if (!live) return
    rows.value = response.links.map((l) => ({ ...l }))
    baseline.value = fingerprint(rows.value)
  } catch (caught) {
    if (live) error.value = describeApiError(caught, '주요 링크를 불러오지 못했습니다.')
  } finally {
    if (live) loading.value = false
  }
}

async function save() {
  if (!editable.value || invalidRows.value.length > 0) return
  saving.value = true
  error.value = null
  try {
    const response = await props.api.saveProjectLinks(
      props.projectId,
      // A negative id is local-only; the server reads null as "insert".
      rows.value.map((l) => ({
        id: l.id > 0 ? l.id : null,
        description: l.description.trim(),
        url: l.url.trim(),
      })),
    )
    if (!live) return
    rows.value = response.links.map((l) => ({ ...l }))
    baseline.value = fingerprint(rows.value)
  } catch (caught) {
    if (live) error.value = describeApiError(caught, '저장에 실패했습니다.')
  } finally {
    if (live) saving.value = false
  }
}

function addRow() {
  rows.value = [
    ...rows.value,
    { id: nextLocalId--, description: '', url: '', sort_order: rows.value.length + 1 },
  ]
}

function removeRow(id: number) {
  rows.value = rows.value.filter((l) => l.id !== id)
}

/** Managed drag has already reordered ag-grid's view; read it back and mirror it. */
function onRowDragEnd() {
  const ordered: ProjectLink[] = []
  gridApi.value?.forEachNodeAfterFilterAndSort((node) => {
    if (node.data) ordered.push(node.data)
  })
  if (ordered.length === rows.value.length) rows.value = ordered
}

function patch(id: number, field: 'description' | 'url', value: string) {
  rows.value = rows.value.map((l) => (l.id === id ? { ...l, [field]: value } : l))
}

const columnDefs = computed<ColDef<ProjectLink>[]>(() => [
  {
    colId: 'drag',
    headerName: '',
    width: 34,
    minWidth: 34,
    maxWidth: 34,
    rowDrag: editable.value,
    sortable: false,
    resizable: false,
  },
  {
    colId: 'description',
    headerName: '설명',
    flex: 1,
    minWidth: 180,
    valueGetter: (p) => p.data?.description ?? '',
    valueSetter: (p) => {
      if (!p.data) return false
      patch(p.data.id, 'description', String(p.newValue ?? ''))
      return true
    },
    editable: editable.value,
    cellEditor: 'agTextCellEditor',
    cellClassRules: {
      'wp-cell-error': (p: CellClassParams<ProjectLink>) => !(p.data?.description ?? '').trim(),
    },
  },
  {
    colId: 'url',
    headerName: '링크',
    flex: 2,
    minWidth: 260,
    valueGetter: (p) => p.data?.url ?? '',
    valueSetter: (p) => {
      if (!p.data) return false
      patch(p.data.id, 'url', String(p.newValue ?? ''))
      return true
    },
    editable: editable.value,
    cellEditor: 'agTextCellEditor',
    // 연결 아이콘은 셀 **오른쪽**에 붙는다 (§0.5.5) — 편집 중인 텍스트를 가리지 않는다.
    cellRenderer: 'LinkOpenRenderer',
    cellClassRules: {
      'wp-cell-error': (p: CellClassParams<ProjectLink>) => !isValidLinkUrl(p.data?.url),
    },
    tooltipValueGetter: (p) =>
      isValidLinkUrl(p.data?.url) ? '' : 'http:// 또는 https:// 로 시작하는 주소여야 합니다.',
  },
  {
    colId: 'actions',
    headerName: '',
    width: 64,
    minWidth: 64,
    sortable: false,
    resizable: false,
    editable: false,
    hide: !editable.value,
    cellRenderer: 'LinkDeleteRenderer',
  },
])

const components = { LinkOpenRenderer, LinkDeleteRenderer }

function onGridReady(event: GridReadyEvent<ProjectLink>) {
  gridApi.value = event.api
}

onMounted(() => {
  ensureAgGridModules()
  void load()
})

onBeforeUnmount(() => {
  // 대시보드 탭을 떠나면 이 그리드도 함께 사라진다 — 인스턴스를 남기지 않는다 (§0.5.5).
  live = false
  gridApi.value = null
})

defineExpose({ reload: load, hasUnsavedChanges: () => dirty.value })
</script>

<template>
  <div class="wp-flex wp-flex-col wp-gap-2" data-wp-links>
    <div class="wp-flex wp-items-center wp-gap-2">
      <span class="wp-text-sm wp-font-semibold" style="color: #0f172a">주요 링크</span>
      <span class="wp-text-xs" style="color: #94a3b8">
        Confluence · 클라우드 파일 등. 순서는 끌어서 바꿉니다.
      </span>
      <span style="flex: 1"></span>
      <span v-if="dirty && editable" class="wp-text-xs" style="color: #d97706">
        저장하지 않은 변경
      </span>
      <template v-if="editable">
        <AButton size="small" data-wp-link-add @click="addRow">행 추가</AButton>
        <AButton
          type="primary"
          size="small"
          data-wp-link-save
          :loading="saving"
          :disabled="!dirty || invalidRows.length > 0"
          @click="save"
        >
          저장
        </AButton>
      </template>
    </div>

    <AAlert v-if="error" type="error" show-icon :message="error" />
    <AAlert
      v-else-if="invalidRows.length > 0"
      type="warning"
      show-icon
      data-wp-link-invalid
      :message="`${invalidRows.length}개 행을 고쳐야 저장할 수 있습니다 — 설명은 필수이고, 링크는 http:// 또는 https:// 로 시작해야 합니다.`"
    />

    <ASpin :spinning="loading">
      <div class="wp-grid-host" data-wp-links-grid style="height: 220px">
        <AgGridVue
          :key="editable ? 'edit' : 'read'"
          style="width: 100%; height: 100%"
          :theme="wpGridTheme"
          :columnDefs="columnDefs"
          :rowData="rows"
          :components="components"
          :getRowId="(p: { data: ProjectLink }) => String(p.data.id)"
          :rowDragManaged="editable"
          :animateRows="true"
          :singleClickEdit="true"
          :stopEditingWhenCellsLoseFocus="true"
          :context="{ removeRow, editable }"
          :overlayNoRowsTemplate="'<span style=&quot;color:#8c8c8c&quot;>등록된 링크가 없습니다.</span>'"
          @grid-ready="onGridReady"
          @row-drag-end="onRowDragEnd"
        />
      </div>
    </ASpin>
  </div>
</template>
