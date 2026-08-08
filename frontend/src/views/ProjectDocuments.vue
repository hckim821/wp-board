<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import {
  Alert as AAlert,
  Button as AButton,
  Input as AInput,
  Select as ASelect,
  Spin as ASpin,
  Switch as ASwitch,
  Table as ATable,
} from 'ant-design-vue'
import { describeApiError } from '../api/client'
import {
  DOC_WRITE_STATUS_LABEL,
  type DocWriteStatus,
  type ProjectDocument,
} from '../api/types'
import { useBoardContext } from '../runtime/context'

/**
 * 프로젝트 문서 설정 — the project tier's 문서 기준정보 tab (`plan.md` §0.5-4).
 *
 * This **replaced** the global document editor on this tab. The global table holds a
 * document's *definition* (code, name, gate, remark) and is edited in one place only —
 * `MasterAdmin`. What a project owns is narrower and entirely its own: whether it uses the
 * document at all, where the cloud copy lives, and how far along it is. Editing the global
 * definition from inside a project would have let one maker's screen rename a document
 * every other project shares.
 *
 * `code` and `name` are therefore rendered as plain text, not inputs.
 *
 * The list is always the server's: a project with no stored rows still receives every active
 * document with the §0.5-4 defaults (사용·작성전·링크 없음), so nothing here synthesises rows.
 */
const { api, board, notify } = useBoardContext()

const rows = ref<ProjectDocument[]>([])
/** The last server state, for dirty comparison. Never mutated. */
const baseline = shallowRef<string>('')
const loading = ref(false)
const saving = ref(false)

/** Host permission gate. Consistent with the other master screens (§0.5-2b). */
const locked = computed(() => board.hostReadOnly.value)

const statusOptions = (Object.keys(DOC_WRITE_STATUS_LABEL) as DocWriteStatus[]).map((value) => ({
  value,
  label: DOC_WRITE_STATUS_LABEL[value],
}))

const fingerprint = (list: readonly ProjectDocument[]) =>
  JSON.stringify(list.map((d) => [d.id, d.name, d.is_used, d.link_url ?? '', d.doc_status]))

const dirty = computed(() => fingerprint(rows.value) !== baseline.value)

const usedCount = computed(() => rows.value.filter((d) => d.is_used).length)

/**
 * 표시 순서 — **사용(ON) 문서에만** 1..N (`plan.md` §0.5.10 정밀화).
 *
 * 팝업과 같은 파생이며 로컬에서 즉시 계산한다: 스위치를 끄면 저장 전에도 아래 번호가 당겨져야
 * 무엇이 바뀌는지 보인다.
 */
const displayNo = computed(() => {
  const map = new Map<number, number>()
  let next = 1
  for (const row of rows.value) if (row.is_used) map.set(row.id, next++)
  return map
})

async function load() {
  const projectId = board.projectId.value
  if (projectId == null) return
  loading.value = true
  try {
    const response = await api.listProjectDocuments(projectId)
    rows.value = response.documents.map((d) => ({ ...d }))
    baseline.value = fingerprint(rows.value)
  } catch (error) {
    notify.error('문서 설정을 불러오지 못했습니다.', describeApiError(error, ''))
  } finally {
    loading.value = false
  }
}

async function save() {
  const projectId = board.projectId.value
  if (projectId == null || locked.value) return
  saving.value = true
  try {
    const response = await api.saveProjectDocuments(projectId, {
      // 배열 순서가 sort_order 다 (§0.5.10) — 번호를 따로 보내지 않는다.
      documents: rows.value.map((d) => ({
        id: d.id > 0 ? d.id : null,
        name: d.name.trim(),
        is_used: d.is_used,
        // 빈 입력은 null 로 — '' 를 저장하면 링크가 있는 것처럼 취급된다.
        link_url: (d.link_url ?? '').trim() || null,
        doc_status: d.doc_status,
      })),
      deleted_ids: deletedIds.value,
    })
    rows.value = response.documents.map((d) => ({ ...d }))
    deletedIds.value = []
    baseline.value = fingerprint(rows.value)
    // 문서를 지우면 서버가 항목 링크까지 끊고 재계산한 행을 함께 돌려준다 (§0.5.10 캐스케이드).
    if (response.items) board.items.value = response.items
    notify.success('저장되었습니다.')
  } catch (error) {
    notify.error('저장에 실패했습니다.', describeApiError(error, ''))
  } finally {
    saving.value = false
  }
}

const columns = [
  { title: '사용', key: 'is_used', width: 64 },
  { title: '순서', key: 'sort_order', width: 56 },
  { title: '문서명', key: 'name' },
  { title: '문서 링크', key: 'link_url', width: 320 },
  { title: '상태', key: 'doc_status', width: 120 },
  { title: '', key: 'actions', width: 64 },
]

/** Local ids for rows not yet on the server. Negative so they cannot collide. */
let nextLocalId = -1
const deletedIds = ref<number[]>([])

function addRow() {
  rows.value = [
    ...rows.value,
    {
      id: nextLocalId--,
      name: '',
      // 표시 번호는 서버가 파생해 준다 — 새 행은 저장 전까지 번호가 없다 (§0.5.10 필드 확정).
      no: null,
      is_used: true,
      link_url: null,
      doc_status: 'NOT_WRITTEN',
    },
  ]
}

/** 프로젝트 로컬 문서 삭제. 항목 링크는 서버가 함께 끊는다 (§0.5.10). */
function removeRow(row: ProjectDocument) {
  const linked = board.items.value.filter((i) => i.documents.some((d) => d.id === row.id)).length
  if (
    linked > 0 &&
    !window.confirm(`'${row.name}' 은(는) 항목 ${linked}개에서 사용 중입니다. 삭제하면 그 항목들에서 연결이 해제됩니다. 계속할까요?`)
  ) {
    return
  }
  if (row.id > 0) deletedIds.value = [...deletedIds.value, row.id]
  rows.value = rows.value.filter((d) => d.id !== row.id)
}

onMounted(load)

defineExpose({ reload: load, hasUnsavedChanges: () => dirty.value })
</script>

<template>
  <ASpin :spinning="loading">
    <div class="wp-flex wp-flex-col wp-gap-3">
      <AAlert
        type="info"
        show-icon
        message="이 프로젝트의 문서 목록입니다. 생성 시 포맷에서 복제되었고 이후 포맷과 무관합니다 — 이름·순서·사용 여부·링크·상태를 모두 여기서 바꾸고, 이 프로젝트만의 문서를 추가할 수도 있습니다."
      />

      <div class="wp-flex wp-items-center wp-gap-2">
        <span class="wp-text-2xs" style="color: #8c8c8c">
          사용 {{ usedCount }} / 전체 {{ rows.length }}
        </span>
        <span v-if="dirty && !locked" class="wp-text-2xs" style="color: #d97706">
          저장하지 않은 변경이 있습니다
        </span>
        <span style="flex: 1"></span>
        <AButton v-if="!locked" size="small" data-wp-doc-add @click="addRow">문서 추가</AButton>
        <AButton
          v-if="!locked"
          type="primary"
          size="small"
          :loading="saving"
          :disabled="!dirty"
          @click="save"
        >
          저장
        </AButton>
        <span v-else class="wp-text-2xs" style="color: #8c8c8c">읽기 전용 — 편집 권한이 없습니다.</span>
      </div>

      <ATable
        :columns="columns"
        :data-source="rows"
        :pagination="false"
        row-key="id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'sort_order'">
            <!-- 순서는 **사용(ON) 문서에만** 1..N (§0.5.10 정밀화) — 입력 칸이 아니다. -->
            <span data-wp-doc-order style="color: #64748b">
              {{ displayNo.get((record as ProjectDocument).id) ?? '—' }}
            </span>
          </template>
          <template v-else-if="column.key === 'name'">
            <AInput
              :value="(record as ProjectDocument).name"
              :disabled="locked"
              size="small"
              data-wp-doc-name
              @update:value="(v: string) => ((record as ProjectDocument).name = v)"
            />
          </template>
          <template v-else-if="column.key === 'actions'">
            <AButton
              v-if="!locked"
              size="small"
              type="link"
              danger
              data-wp-doc-delete
              @click="removeRow(record as ProjectDocument)"
            >
              삭제
            </AButton>
          </template>
          <template v-else-if="column.key === 'is_used'">
            <ASwitch
              size="small"
              :checked="(record as ProjectDocument).is_used"
              :disabled="locked"
              data-wp-doc-used
              @change="(v: unknown) => ((record as ProjectDocument).is_used = !!v)"
            />
          </template>
          <template v-else-if="column.key === 'link_url'">
            <AInput
              :value="(record as ProjectDocument).link_url ?? ''"
              :disabled="locked"
              size="small"
              allow-clear
              placeholder="https://…"
              @update:value="(v: string) => ((record as ProjectDocument).link_url = v || null)"
            />
          </template>
          <template v-else-if="column.key === 'doc_status'">
            <ASelect
              :value="(record as ProjectDocument).doc_status"
              :options="statusOptions"
              :disabled="locked"
              size="small"
              style="width: 100%"
              @update:value="(v: unknown) => ((record as ProjectDocument).doc_status = v as DocWriteStatus)"
            />
          </template>
        </template>
      </ATable>
    </div>
  </ASpin>
</template>
