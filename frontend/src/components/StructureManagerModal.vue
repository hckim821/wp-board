<script setup lang="ts">
import { computed, ref } from 'vue'
import { App, Button as AButton, Input as AInput, Modal as AModal } from 'ant-design-vue'
import type { StructureEntry } from '../api/types'
import { useBoardContext, type StructureManagerRequest } from '../runtime/context'
import { phaseColor } from '../theme/palette'

/**
 * Phase / Milestone 관리 팝업 — `plan.md` §0.4.
 *
 * One table, four operations: reorder by dragging, add, rename inline, delete. [적용] sends
 * the table's final state as a single request; [취소] sends nothing at all.
 *
 * **Order is the numbering.** The rows top to bottom become the board's block order, and
 * first-appearance renumbering (§2.2) derives every number from that. Nothing here assigns
 * a number — the 번호 column is a *preview* of what the server will compute, shown so the
 * user can see that dropping a new phase between 0 and 1 pushes the old 1 to 2 before they
 * commit to it.
 *
 * Deliberately not an ag-grid instance: a second grid inside a modal would cost a Community
 * grid's worth of machinery to render a list of five names, and none of ag-grid's row-drag
 * behaviour (block confinement, managed drag) is wanted here — this list has no blocks.
 *
 * The list must contain **every** phase/milestone of the scope, including ones no row uses,
 * because the payload is a final state: the server checks that the kept and deleted ids add
 * up to exactly what it has and refuses (422) otherwise, precisely so a forgotten id cannot
 * read as a deletion.
 */
const props = defineProps<{ request: StructureManagerRequest }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { board, master, notify, popupContainer } = useBoardContext()
const { modal } = App.useApp()

const isPhase = props.request.kind === 'phase'
const phaseId = props.request.phaseId ?? null
const anchorItemId = props.request.anchorItemId ?? null

interface EditorRow {
  /** Stable across reorders — the array index is not, and Vue would recycle inputs. */
  key: string
  id: number | null
  name: string
}

let nextKey = 0
const rowKey = () => `r${nextKey++}`

const phaseStartNo = computed(
  () =>
    (board.tier === 'template'
      ? board.template.value?.phase_start_no
      : board.project.value?.phase_start_no) ?? 0,
)

/** Display number of the phase whose milestones are being managed. */
const parentPhaseNo = computed(() => {
  if (isPhase || phaseId == null) return null
  const row = board.items.value.find((r) => r.phase_id === phaseId)
  if (row?.phase_no != null) return row.phase_no
  return master.phases.value.find((p) => p.id === phaseId)?.seq_no ?? null
})

const parentPhaseName = computed(
  () => master.phases.value.find((p) => p.id === phaseId)?.name ?? '',
)

/**
 * The existing entries: the ones **with rows on this board**, in first-appearance order.
 *
 * Both halves of that are load-bearing.
 *
 * *In board order*, because `seq_no` is the **result** of the last renumber rather than its
 * input — sorting by it can disagree with the board the user is looking at. First appearance
 * cannot.
 *
 * *With rows*, because that is precisely the set the server's apply expects back, and
 * because an entry with no rows has no first appearance, hence no number and no position in
 * a list whose entire meaning is order. Master rows nothing references are outside this
 * screen; they are neither shown nor sent, and apply leaves them alone.
 */
function existingEntries(): EditorRow[] {
  const seen: number[] = []
  if (isPhase) {
    const byId = new Map(master.phases.value.map((p) => [p.id, p]))
    for (const row of board.items.value) {
      if (row.phase_id != null && !seen.includes(row.phase_id) && byId.has(row.phase_id)) {
        seen.push(row.phase_id)
      }
    }
    return seen.map((id) => ({ key: rowKey(), id, name: byId.get(id)!.name }))
  }

  const byId = new Map(
    master.milestones.value.filter((m) => m.phase_id === phaseId).map((m) => [m.id, m]),
  )
  for (const row of board.items.value) {
    if (row.phase_id !== phaseId) continue
    if (row.milestone_id != null && !seen.includes(row.milestone_id) && byId.has(row.milestone_id)) {
      seen.push(row.milestone_id)
    }
  }
  return seen.map((id) => ({ key: rowKey(), id, name: byId.get(id)!.name }))
}

/**
 * Where a new entry created from an anchor row naturally belongs.
 *
 * The anchor is a gray row sitting somewhere on the board, and the block it is about to
 * become starts exactly there — so the new entry's default slot is after however many
 * blocks already appear above it. The user can drag it elsewhere; this is just the position
 * that matches where they clicked.
 */
function anchorIndex(): number {
  if (anchorItemId == null) return 0
  const seen = new Set<number>()
  for (const row of board.items.value) {
    if (row.id === anchorItemId) break
    if (isPhase) {
      if (row.phase_id != null) seen.add(row.phase_id)
    } else if (row.phase_id === phaseId && row.milestone_id != null) {
      seen.add(row.milestone_id)
    }
  }
  return seen.size
}

const rows = ref<EditorRow[]>(existingEntries())
const deletedIds = ref<number[]>([])
const applying = ref(false)

if (anchorItemId != null) {
  rows.value.splice(anchorIndex(), 0, { key: rowKey(), id: null, name: '' })
}

/**
 * How many board rows a deletion would take with it — the N in the warning (§0.4).
 *
 * **Unassigned rows are not counted, because they are not deleted.** A gray row parked
 * inside a block that goes away survives and reattaches to the preceding surviving block, so
 * counting it would promise the user a loss that does not happen. This falls out of matching
 * on `phase_id` / `milestone_id`, which a gray row has neither of.
 */
function rowCount(id: number): number {
  return board.items.value.filter((r) => (isPhase ? r.phase_id === id : r.milestone_id === id))
    .length
}

/** Milestones of a phase that actually have rows — the same set the popup would list. */
const childMilestoneCount = (id: number) => {
  if (!isPhase) return 0
  const seen = new Set<number>()
  for (const row of board.items.value) {
    if (row.phase_id === id && row.milestone_id != null) seen.add(row.milestone_id)
  }
  return seen.size
}

/** `Phase 2` / `1.3` — what the server will compute once this order is applied. */
function previewNo(index: number): string {
  if (isPhase) return `Phase ${phaseStartNo.value + index}`
  return `${parentPhaseNo.value ?? '?'}.${index + 1}`
}

/**
 * With an anchor there may be exactly one new entry — the anchor row is its first board row,
 * and a second new entry would have none (§0.4). Without an anchor the server makes a blank
 * row for each, so any number is fine.
 */
const newEntryLimitReached = computed(
  () => anchorItemId != null && rows.value.some((r) => r.id == null),
)

function addRow() {
  if (newEntryLimitReached.value) return
  rows.value = [...rows.value, { key: rowKey(), id: null, name: '' }]
}

function move(from: number, to: number) {
  if (from === to || to < 0 || to >= rows.value.length) return
  const next = [...rows.value]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved!)
  rows.value = next
}

function removeRow(index: number) {
  const row = rows.value[index]
  if (!row) return
  if (row.id == null) {
    rows.value = rows.value.filter((_, i) => i !== index)
    return
  }

  const rowsLost = rowCount(row.id)
  const milestonesLost = childMilestoneCount(row.id)
  const label = isPhase ? 'Phase' : 'Milestone'
  const detail = isPhase
    ? `행 ${rowsLost}개와 하위 Milestone ${milestonesLost}개가 함께 삭제됩니다.`
    : `행 ${rowsLost}개가 함께 삭제됩니다.`

  modal.confirm({
    title: `${label} 삭제`,
    content: `'${row.name}' 을(를) 삭제하면 하위 항목 ${rowsLost + milestonesLost}개가 함께 삭제됩니다. ${detail} 되돌릴 수 없습니다.`,
    okText: '삭제',
    okType: 'danger',
    cancelText: '취소',
    onOk: () => {
      deletedIds.value = [...deletedIds.value, row.id!]
      rows.value = rows.value.filter((r) => r.key !== row.key)
    },
  })
}

// ── drag reorder ──
// The row is only draggable while the handle is held, so the name inputs stay selectable.
const dragArmed = ref<number | null>(null)
const dragFrom = ref<number | null>(null)
const dragOver = ref<number | null>(null)

function onDragStart(index: number) {
  dragFrom.value = index
}
function onDragEnter(index: number) {
  dragOver.value = index
}
function onDrop(index: number) {
  if (dragFrom.value != null) move(dragFrom.value, index)
  onDragEnd()
}
function onDragEnd() {
  dragArmed.value = null
  dragFrom.value = null
  dragOver.value = null
}

async function apply() {
  const entries: StructureEntry[] = rows.value.map((r) => ({ id: r.id, name: r.name.trim() }))
  if (entries.some((e) => !e.name)) {
    notify.warn('이름이 비어 있는 항목이 있습니다.')
    return
  }
  const names = entries.map((e) => e.name)
  if (new Set(names).size !== names.length) {
    notify.warn('같은 이름이 두 번 이상 있습니다.')
    return
  }

  applying.value = true
  try {
    const ok = isPhase
      ? await board.applyPhasePlan({
          phases: entries,
          deleted_ids: deletedIds.value,
          anchor_item_id: anchorItemId,
        })
      : await board.applyMilestonePlan(phaseId!, {
          milestones: entries,
          deleted_ids: deletedIds.value,
          anchor_item_id: anchorItemId,
        })
    if (!ok) return
    notify.success(isPhase ? 'Phase 목록을 적용했습니다.' : 'Milestone 목록을 적용했습니다.')
    emit('close')
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <AModal
    :open="true"
    :title="isPhase ? 'Phase 관리' : `Milestone 관리 — Phase ${parentPhaseNo ?? '?'}. ${parentPhaseName}`"
    :width="640"
    :get-container="popupContainer"
    :mask-closable="false"
    :confirm-loading="applying"
    ok-text="적용"
    cancel-text="취소"
    :ok-button-props="{ disabled: board.readOnly.value }"
    @ok="apply"
    @cancel="emit('close')"
  >
    <p class="wp-mb-2 wp-text-xs" style="color: #8c8c8c">
      표의 위→아래 순서가 보드의 블록 순서가 되고, 번호는 그 순서에서 자동으로 매겨집니다.
      번호를 직접 입력하는 곳은 없습니다. [적용] 을 눌러야 서버에 반영됩니다.
    </p>
    <p
      v-if="anchorItemId != null"
      class="wp-mb-2 wp-rounded wp-px-2 wp-py-1.5 wp-text-xs"
      style="background-color: #f6ffed; color: #52705a"
    >
      선택한 미배정(회색) 행이 새 {{ isPhase ? 'Phase' : 'Milestone' }} 의 첫 행이 됩니다.
      원하는 위치로 끌어다 놓으세요.
    </p>

    <table class="wp-w-full wp-text-[13px]">
      <thead>
        <tr style="color: #8c8c8c">
          <th class="wp-w-8" />
          <th class="wp-w-20 wp-py-1 wp-text-left wp-font-medium">번호</th>
          <th class="wp-py-1 wp-text-left wp-font-medium">이름</th>
          <th class="wp-w-16 wp-py-1 wp-text-right wp-font-medium">행</th>
          <th class="wp-w-28" />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="row.key"
          :draggable="dragArmed === index"
          class="wp-border-t wp-border-solid"
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
            class="wp-cursor-grab wp-select-none wp-py-1 wp-text-center"
            style="color: #bfbfbf"
            title="끌어서 순서 변경"
            @mousedown="dragArmed = index"
            @mouseup="dragArmed = null"
          >
            ⋮⋮
          </td>
          <td class="wp-py-1">
            <span class="wp-flex wp-items-center wp-gap-1.5">
              <span
                v-if="isPhase"
                class="wp-h-3 wp-w-[3px] wp-shrink-0 wp-rounded"
                :style="{ backgroundColor: phaseColor(phaseStartNo + index).accent }"
              />
              <span :style="row.id == null ? { color: '#1677ff', fontWeight: 600 } : {}">
                {{ previewNo(index) }}
              </span>
            </span>
          </td>
          <td class="wp-py-1 wp-pr-2">
            <AInput
              v-model:value="row.name"
              size="small"
              :placeholder="isPhase ? 'Phase 이름 (번호 제외)' : 'Milestone 이름 (번호 제외)'"
              :disabled="board.readOnly.value"
            />
          </td>
          <td class="wp-py-1 wp-text-right wp-text-xs" style="color: #8c8c8c">
            {{ row.id == null ? '신규' : rowCount(row.id) }}
          </td>
          <td class="wp-py-1 wp-text-right">
            <div class="wp-flex wp-justify-end wp-gap-0.5">
              <AButton size="small" type="text" :disabled="index === 0" @click="move(index, index - 1)">
                ↑
              </AButton>
              <AButton
                size="small"
                type="text"
                :disabled="index === rows.length - 1"
                @click="move(index, index + 1)"
              >
                ↓
              </AButton>
              <AButton
                size="small"
                type="text"
                danger
                :disabled="board.readOnly.value"
                @click="removeRow(index)"
              >
                삭제
              </AButton>
            </div>
          </td>
        </tr>
        <tr v-if="rows.length === 0">
          <td colspan="5" class="wp-py-4 wp-text-center wp-text-xs" style="color: #bfbfbf">
            항목이 없습니다. 아래 ‘행 추가’ 로 만드세요.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="wp-mt-2 wp-flex wp-items-center wp-gap-2">
      <AButton
        size="small"
        :disabled="board.readOnly.value || newEntryLimitReached"
        @click="addRow"
      >
        ＋ {{ isPhase ? 'Phase' : 'Milestone' }} 추가
      </AButton>
      <span v-if="newEntryLimitReached" class="wp-text-2xs" style="color: #bfbfbf">
        미배정 행에서 열었을 때는 신규 1개만 만들 수 있습니다.
      </span>
      <span v-else-if="anchorItemId == null" class="wp-text-2xs" style="color: #bfbfbf">
        추가한 항목에는 빈 행 1개가 함께 만들어집니다.
      </span>
    </div>
    <p v-if="deletedIds.length > 0" class="wp-mt-2 wp-text-xs" style="color: #cf1322">
      삭제 예정 {{ deletedIds.length }}건 — [적용] 을 눌러야 실제로 삭제됩니다.
    </p>
  </AModal>
</template>
