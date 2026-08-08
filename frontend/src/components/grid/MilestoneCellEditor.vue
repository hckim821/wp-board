<script setup lang="ts">
import { computed } from 'vue'
import type { ICellEditorParams } from 'ag-grid-community'
import { Button as AButton } from 'ant-design-vue'
import type { WpItem, WpMilestone } from '../../api/types'
import { useBoardContext } from '../../runtime/context'

/**
 * Milestone dropdown — §0.2.6 / §0.4, one level down from the Phase editor.
 *
 * Only milestones of the row's own phase are offered: V3 forbids a row whose milestone
 * belongs to a different phase, so the UI simply never allows it to be constructed.
 *
 * **This editor only ever opens on a row that has a phase and no milestone** (`plan.md`
 * §0.3): an assigned milestone is locked and offers the [수정] / [재배치] choice instead, and
 * a row with no phase cannot pick a milestone at all. That row is the *milestone*-level gray
 * row — transparent to milestone contiguity, free to move inside its phase block, and
 * offered its neighbours' milestones as one-click shortcuts.
 *
 * Picking one moves the row to the end of **that milestone's block** (§0.3), not the end of
 * the phase — 2.2 lands before 2.3, not after 2.4.
 *
 * `+ 새 Milestone 생성` opens the 관리 팝업 for this row's phase, anchored on this row (§0.4);
 * `can_create_milestone` is no longer read here for the same reason as in the Phase editor.
 */
const props = defineProps<{ params: ICellEditorParams<WpItem> }>()

const { board, master, structure } = useBoardContext()

const item = computed(() => props.params.data)
const milestones = computed(() => master.milestonesOfPhase(item.value.phase_id))
const phaseMissing = computed(() => item.value.phase_id == null)

/**
 * Nearest assigned milestone above and below, read past transparent rows and confined to
 * this row's own phase — a milestone may not span two phases, so a neighbour in another
 * phase is no neighbour at all here.
 */
const shortcuts = computed(() => {
  const rows = board.items.value
  const index = rows.findIndex((r) => r.id === item.value.id)
  if (index < 0) return []

  const seek = (step: -1 | 1) => {
    for (let i = index + step; i >= 0 && i < rows.length; i += step) {
      const row = rows[i]!
      if (row.phase_id != null && row.phase_id !== item.value.phase_id) return null
      if (row.milestone_id != null) {
        return milestones.value.find((m) => m.id === row.milestone_id) ?? null
      }
    }
    return null
  }

  const above = seek(-1)
  const below = seek(1)
  const out: { label: string; milestone: WpMilestone }[] = []
  if (above) out.push({ label: '위와 같게', milestone: above })
  if (below && below.id !== above?.id) out.push({ label: '아래와 같게', milestone: below })
  return out
})

function close() {
  props.params.api.stopEditing(true)
}

function label(milestone: WpMilestone) {
  return `${item.value.phase_no ?? '?'}.${milestone.seq_no} ${milestone.name}`
}

function choose(milestone: WpMilestone) {
  if (milestone.id === item.value.milestone_id) return close()
  const id = item.value.id
  close()
  void board.assignMilestone(id, milestone.id)
}

/** Hands off to the 관리 팝업 for this row's phase, with this row as the anchor (§0.4). */
function openManager() {
  const id = item.value.id
  const phaseId = item.value.phase_id
  close()
  structure.open({ kind: 'milestone', phaseId, anchorItemId: id })
}

defineExpose({ getValue: () => props.params.value })
</script>

<template>
  <div
    class="wp-w-[340px] wp-overflow-hidden wp-rounded-md wp-border wp-border-solid wp-bg-white wp-text-[13px] wp-shadow-lg"
    style="border-color: #e4e4e4"
  >
    <div
      class="wp-flex wp-items-center wp-justify-between wp-border-b wp-border-solid wp-px-3 wp-py-2 wp-text-xs wp-font-medium"
      style="border-color: #f0f0f0; color: #8c8c8c"
    >
      <span>Milestone 선택</span>
      <span v-if="!phaseMissing" style="color: #8c8c8c">미배정 행</span>
    </div>

    <p v-if="phaseMissing" class="wp-px-3 wp-py-3 wp-text-xs" style="color: #bfbfbf">
      Phase 를 먼저 지정해야 Milestone 을 선택할 수 있습니다.
    </p>

    <template v-else>
      <div
        v-if="shortcuts.length > 0"
        class="wp-border-b wp-border-solid wp-px-2 wp-py-2"
        style="border-color: #f0f0f0; background-color: #fafafa"
      >
        <p class="wp-mb-1 wp-px-1 wp-text-2xs" style="color: #bfbfbf">인접 Milestone</p>
        <button
          v-for="shortcut in shortcuts"
          :key="shortcut.label"
          type="button"
          class="wp-flex wp-w-full wp-items-center wp-gap-2 wp-rounded wp-px-2 wp-py-1.5 wp-text-left hover:wp-bg-white"
          @click="choose(shortcut.milestone)"
        >
          <span class="wp-shrink-0 wp-font-medium">{{ shortcut.label }}</span>
          <span class="wp-truncate wp-text-xs" style="color: #8c8c8c">
            {{ label(shortcut.milestone) }}
          </span>
        </button>
      </div>

      <div class="wp-max-h-[240px] wp-overflow-y-auto wp-py-1">
        <button
          v-for="milestone in milestones"
          :key="milestone.id"
          type="button"
          class="wp-flex wp-w-full wp-px-3 wp-py-1.5 wp-text-left hover:wp-bg-slate-50"
          :style="
            milestone.id === item.milestone_id
              ? { backgroundColor: '#F5F5F5', fontWeight: 600 }
              : {}
          "
          @click="choose(milestone)"
        >
          <span class="wp-truncate">{{ label(milestone) }}</span>
        </button>
        <p
          v-if="milestones.length === 0"
          class="wp-px-3 wp-py-2 wp-text-xs"
          style="color: #bfbfbf"
        >
          이 Phase에 등록된 Milestone이 없습니다.
        </p>
      </div>

      <div class="wp-border-t wp-border-solid wp-px-2 wp-py-2" style="border-color: #f0f0f0">
        <AButton block size="small" :disabled="board.readOnly.value" @click="openManager">
          ＋ 새 Milestone 생성
        </AButton>
        <p class="wp-mt-1 wp-px-1 wp-text-2xs" style="color: #bfbfbf">
          Milestone 관리 창이 열리고, 이 행이 새 Milestone 의 첫 행이 됩니다.
        </p>
      </div>
    </template>
  </div>
</template>
