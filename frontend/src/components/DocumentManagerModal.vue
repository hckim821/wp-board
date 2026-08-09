<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Button as AButton,
  Checkbox as ACheckbox,
  Input as AInput,
  Modal as AModal,
  Select as ASelect,
  Switch as ASwitch,
  Tooltip as ATooltip,
} from 'ant-design-vue'
import {
  DOC_WRITE_STATUS_LABEL,
  type DocumentRef,
  type DocWriteStatus,
  type ProjectDocument,
  type TemplateDocument,
} from '../api/types'
import { useBoardContext, type DocumentPickerRequest } from '../runtime/context'

/**
 * 관련 문서 선택·관리 팝업 — `plan.md` §0.5.10.
 *
 * Same two-jobs-one-window shape as the Owner popup, but the halves commit **together**
 * rather than separately: a document apply can delete, and deleting unlinks that document
 * from every row, so the row selection has to be resolved after the server has renumbered.
 * The management half is a whole-list apply (order = 표시 번호) and the selection half is a
 * local `patchItem` that the toolbar's 저장 later persists.
 *
 * **No global-scope warning anywhere.** Documents used to be a global master shared by every
 * template and project, and every screen that touched them said so. §0.5.10 made them
 * scope-owned like Phase/Milestone/Owner, so there is nothing left to warn about — the
 * absence of that banner is the model change, not an oversight.
 *
 * The project tier adds 사용 · 문서 링크 · 상태 columns; a template has no such notions.
 */
const props = defineProps<{ request: DocumentPickerRequest }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { board, master, popupContainer } = useBoardContext()

const isProject = board.tier === 'project'
const item = computed(() => board.items.value.find((row) => row.id === props.request.itemId))
const editable = computed(() => !board.readOnly.value)

interface EditorRow {
  /** Stable across reorders — the array index is not, and Vue would recycle inputs. */
  key: string
  id: number | null
  name: string
  is_used: boolean
  link_url: string | null
  doc_status: DocWriteStatus
}

let nextKey = 0
const rows = ref<EditorRow[]>(
  (master.documents.value as unknown as (TemplateDocument & Partial<ProjectDocument>)[]).map(
    (d) => ({
      key: `d${nextKey++}`,
      id: d.id,
      name: d.name,
      is_used: d.is_used ?? true,
      link_url: d.link_url ?? null,
      doc_status: d.doc_status ?? 'NOT_WRITTEN',
    }),
  ),
)
const deletedIds = ref<number[]>([])
const selected = ref<Set<number>>(new Set((item.value?.documents ?? []).map((d) => d.id)))
const applying = ref(false)

const dragFrom = ref<number | null>(null)
const dragOver = ref<number | null>(null)
const dragArmed = ref<number | null>(null)

const statusOptions = (Object.keys(DOC_WRITE_STATUS_LABEL) as DocWriteStatus[]).map((value) => ({
  value,
  label: DOC_WRITE_STATUS_LABEL[value],
}))

/**
 * 표시 순서 — **사용(ON) 행에만 1..N** (`plan.md` §0.5.10 정밀화).
 *
 * 로컬 행에서 바로 계산하므로 스위치를 끄는 즉시 아래 행들의 번호가 당겨진다. 서버 응답을
 * 기다렸다면 토글할 때마다 번호가 한 박자 늦게 따라와, 무엇이 바뀐 것인지 읽기 어렵다.
 */
const displayNo = computed(() => {
  const map = new Map<string, number>()
  let next = 1
  for (const row of rows.value) if (row.is_used) map.set(row.key, next++)
  return map
})

/** How many board rows link a document — the number the delete warning quotes (§0.5.10). */
const usageOf = (id: number | null) =>
  id == null ? 0 : board.items.value.filter((row) => row.documents.some((d) => d.id === id)).length

function toggle(id: number, checked: boolean) {
  const next = new Set(selected.value)
  if (checked) next.add(id)
  else next.delete(id)
  selected.value = next
}

/**
 * 사용 스위치 — off 로 바꾸면 그 문서의 **선택도 즉시 풀린다** (`plan.md` §0.5.10 정밀화).
 *
 * 두 상태를 따로 두면 "이 행이 참조하지만 프로젝트에서는 쓰지 않는 문서" 라는, 화면 어디에도
 * 표현할 수 없는 조합이 만들어진다. 실제로 그 조합이 남아 셀에 잔재로 찍혔다 — off 로 바꿨는데
 * 선택이 살아 있었고, 그 문서를 갖던 다른 행들에도 그대로 남았다.
 *
 * 되돌릴 때 자동으로 다시 선택되지는 않는다. 껐다 켜는 것은 취소가 아니라 두 번의 결정이고,
 * 사용자가 원래 무엇을 골랐는지 추측해 되살리는 쪽이 더 놀랍다.
 */
function setUsed(row: EditorRow, value: boolean) {
  row.is_used = value
  if (!value && row.id != null) toggle(row.id, false)
}

function addRow() {
  rows.value = [
    ...rows.value,
    {
      key: `d${nextKey++}`,
      id: null,
      name: '',
      is_used: true,
      link_url: null,
      doc_status: 'NOT_WRITTEN',
    },
  ]
}

/**
 * Removes a row, warning first when board rows still link it.
 *
 * The count is knowable here — the rows are in the store — so the warning states it rather
 * than describing the rule in the abstract, and the deletion cascade is what actually
 * happens on apply.
 */
function removeRow(index: number) {
  const row = rows.value[index]
  if (!row) return
  const linked = usageOf(row.id)
  if (
    linked > 0 &&
    !window.confirm(
      `'${row.name}' 은(는) 항목 ${linked}개에서 사용 중입니다. 삭제하면 그 항목들에서 연결이 해제됩니다. 계속할까요?`,
    )
  ) {
    return
  }
  if (row.id != null) deletedIds.value = [...deletedIds.value, row.id]
  rows.value = rows.value.filter((_, i) => i !== index)
}

function onDragStart(index: number) {
  dragFrom.value = index
}
function onDragEnter(index: number) {
  dragOver.value = index
}
function onDragEnd() {
  dragFrom.value = null
  dragOver.value = null
  dragArmed.value = null
}
function onDrop(index: number) {
  const from = dragFrom.value
  onDragEnd()
  if (from == null || from === index) return
  const next = [...rows.value]
  const [moved] = next.splice(from, 1)
  if (!moved) return
  next.splice(index, 0, moved)
  rows.value = next
}

/**
 * [적용] — the list first, then the row's selection.
 *
 * Order matters: the apply renumbers and may delete, so the row's document list is rebuilt
 * from the response rather than from what was on screen when the user clicked.
 */
async function apply() {
  if (!editable.value) return emit('close')
  applying.value = true
  try {
    const payload = rows.value.map((r) => ({
      id: r.id,
      name: r.name.trim(),
      is_used: r.is_used,
      link_url: r.link_url,
      doc_status: r.doc_status,
    }))
    const ok = isProject
      ? await board.applyProjectDocumentPlan({ documents: payload, deleted_ids: deletedIds.value })
      : await board.applyDocumentPlan({
          documents: payload.map((r) => ({ id: r.id, name: r.name })),
          deleted_ids: deletedIds.value,
        })
    if (!ok) return

    /*
     * 선택은 **id 로** 되살린다. 이름 매칭이 필요할 것 같지만 아니다 — 새로 추가한 행은 아직
     * id 가 없어 체크박스가 비활성이므로 애초에 선택될 수 없고, 기존 행은 이름·순서가 바뀌어도
     * id 가 그대로다. 삭제된 문서는 응답 목록에 없으므로 자연히 빠진다.
     */
    /*
     * 사용하지 않는 문서는 선택에서도 빠진다 — 스위치를 끌 때 이미 풀리지만, 응답의 `no` 로
     * 한 번 더 거른다. 서버가 최종 판정자이고, 이 창 밖에서 off 가 된 문서가 있을 수 있다.
     */
    const picked: DocumentRef[] = (master.documents.value as TemplateDocument[])
      .filter((d) => selected.value.has(d.id) && d.no != null)
      .map((d) => ({ id: d.id, no: d.no, name: d.name }))
    const row = item.value
    if (row) board.patchItem(row.id, { documents: picked })
    emit('close')
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <AModal
    :open="true"
    :title="isProject ? '관련 문서 선택 · 관리 (프로젝트)' : '관련 문서 선택 · 관리'"
    :width="isProject ? 820 : 560"
    :get-container="popupContainer"
    :mask-closable="false"
    :confirm-loading="applying"
    ok-text="적용"
    cancel-text="취소"
    :ok-button-props="{ disabled: !editable }"
    @ok="apply"
    @cancel="emit('close')"
  >
    <p class="wp-mb-2 wp-text-xs" style="color: #8c8c8c">
      체크한 문서가 이 행의 관련 문서가 됩니다. <b>순서</b>는 사용(ON) 문서에만 1..N 으로 매겨지고,
      목록 편집(추가·이름·순서·삭제)은 [적용] 을 눌러야 서버에 반영됩니다.
    </p>
    <p v-if="!editable" class="wp-mb-2 wp-text-xs" style="color: #d48806">
      읽기 전용입니다 — 열람만 가능합니다.
    </p>

    <table class="wp-w-full wp-text-[13px]" data-wp-doc-table>
      <thead>
        <tr style="color: #8c8c8c">
          <th class="wp-w-8" />
          <th class="wp-w-12 wp-py-1 wp-font-medium">선택</th>
          <th v-if="isProject" class="wp-w-14 wp-py-1 wp-font-medium">사용</th>
          <th class="wp-w-12 wp-py-1 wp-text-left wp-font-medium">순서</th>
          <th class="wp-py-1 wp-text-left wp-font-medium">문서명</th>
          <th v-if="isProject" class="wp-w-52 wp-py-1 wp-text-left wp-font-medium">문서 링크</th>
          <th v-if="isProject" class="wp-w-28 wp-py-1 wp-text-left wp-font-medium">상태</th>
          <th class="wp-w-16" />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="row.key"
          :draggable="dragArmed === index"
          class="wp-border-0 wp-border-t wp-border-solid"
          data-wp-doc-row
          :style="{
            borderColor: '#f0f0f0',
            backgroundColor: dragOver === index && dragFrom !== index ? '#e6f4ff' : 'transparent',
          }"
          @dragstart="onDragStart(index)"
          @dragenter="onDragEnter(index)"
          @dragover.prevent
          @drop.prevent="onDrop(index)"
          @dragend="onDragEnd"
        >
          <td
            class="wp-select-none wp-py-1 wp-text-center"
            :class="editable ? 'wp-cursor-grab' : ''"
            style="color: #bfbfbf"
            title="끌어서 순서 변경"
            @mousedown="editable && (dragArmed = index)"
            @mouseup="dragArmed = null"
          >
            ⋮⋮
          </td>
          <td class="wp-py-1 wp-text-center">
            <ATooltip
              :title="
                row.id == null
                  ? '먼저 [적용] 으로 문서를 만들어야 선택할 수 있습니다.'
                  : !row.is_used
                    ? '사용(ON) 인 문서만 선택할 수 있습니다.'
                    : ''
              "
            >
              <ACheckbox
                :checked="row.id != null && selected.has(row.id)"
                :disabled="!editable || row.id == null || !row.is_used"
                :data-wp-doc-pick="row.id ?? 'new'"
                @change="
                  (e: { target: { checked: boolean } }) =>
                    row.id != null && toggle(row.id, e.target.checked)
                "
              />
            </ATooltip>
          </td>
          <td v-if="isProject" class="wp-py-1 wp-text-center">
            <ASwitch
              size="small"
              :checked="row.is_used"
              :disabled="!editable"
              data-wp-doc-used
              @change="(v: unknown) => setUsed(row, !!v)"
            />
          </td>
          <!-- 순서는 입력이 아니라 **사용 행 중의 위치**다 (§0.5.10 정밀화) — 끌어서 바꾼다. -->
          <td class="wp-py-1" data-wp-doc-no style="color: #64748b">
            {{ displayNo.get(row.key) ?? '—' }}
          </td>
          <td class="wp-py-1">
            <AInput v-model:value="row.name" size="small" :disabled="!editable" data-wp-doc-name />
          </td>
          <td v-if="isProject" class="wp-py-1">
            <AInput
              :value="row.link_url ?? ''"
              size="small"
              allow-clear
              placeholder="https://…"
              :disabled="!editable"
              @update:value="(v: string) => (row.link_url = v || null)"
            />
          </td>
          <td v-if="isProject" class="wp-py-1">
            <ASelect
              :value="row.doc_status"
              :options="statusOptions"
              size="small"
              style="width: 100%"
              :disabled="!editable"
              :get-popup-container="popupContainer"
              @update:value="(v: unknown) => (row.doc_status = v as DocWriteStatus)"
            />
          </td>
          <td class="wp-py-1 wp-text-right">
            <AButton
              v-if="editable"
              size="small"
              type="link"
              danger
              data-wp-doc-delete
              @click="removeRow(index)"
            >
              삭제
            </AButton>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="editable" class="wp-mt-3">
      <AButton size="small" data-wp-doc-add @click="addRow">＋ 문서 추가</AButton>
    </div>
  </AModal>
</template>
