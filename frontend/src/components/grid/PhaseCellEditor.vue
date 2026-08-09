<script setup lang="ts">
import { computed } from 'vue'
import type { ICellEditorParams } from 'ag-grid-community'
import { Button as AButton } from 'ant-design-vue'
import type { WpItem, WpPhase } from '../../api/types'
import { useBoardContext } from '../../runtime/context'
import { phaseColor } from '../../theme/palette'

/**
 * Phase dropdown for an unassigned (gray) row — `plan.md` §0.2.3, §0.4.
 *
 * **This editor only ever opens on a gray row** (`plan.md` §0.3): an assigned row's Phase
 * cell is locked, and clicking it offers the [수정] / [재배치] choice instead. So there is no
 * boundary-row or middle-row case here, and no relocation confirm — picking a phase moves
 * the row to the end of that phase's block, which is what the user asked for by picking it.
 *
 * Its neighbours' phases are offered first, as one-click "위/아래와 같게".
 *
 * **`+ 새 Phase 생성` no longer creates anything here.** It opens the 관리 팝업 with this row
 * as the anchor (§0.4), where the user also chooses *where* the new phase goes. Because the
 * position is stated there, §0.2.4's "the neighbouring phases must differ" precondition is
 * retired: the server still computes `can_create_phase` and this component no longer reads
 * it. That is not the client taking over a server rule — it is the rule no longer applying
 * to this path.
 *
 * The *neighbour lookup* below is client-side, and deliberately so: it decides which two
 * buttons to show first, nothing more. Whether the resulting board is legal is still the
 * server's answer to `membership` / `phases/apply`.
 */
const props = defineProps<{ params: ICellEditorParams<WpItem> }>()

const { board, master, structure } = useBoardContext()

const item = computed(() => props.params.data)
const phases = computed(() => master.activePhases.value)

/**
 * The nearest assigned phase above and below, read past other gray rows.
 *
 * Same transparency the contiguity check uses: a gray row parked next to another gray row
 * still has Phase 0 "above" it. Anything else would offer the user a shortcut that lands
 * them somewhere other than where the seam looks.
 */
const neighbours = computed<{ above: WpPhase | null; below: WpPhase | null }>(() => {
  const rows = board.items.value
  const index = rows.findIndex((r) => r.id === item.value.id)
  if (index < 0) return { above: null, below: null }

  const seek = (step: -1 | 1) => {
    for (let i = index + step; i >= 0 && i < rows.length; i += step) {
      const id = rows[i]!.phase_id
      if (id != null) return phases.value.find((p) => p.id === id) ?? null
    }
    return null
  }
  return { above: seek(-1), below: seek(1) }
})

/** Shown only when they add something — a neighbour that is not already the row's own. */
const shortcuts = computed(() => {
  const { above, below } = neighbours.value
  const out: { label: string; phase: WpPhase }[] = []
  if (above) out.push({ label: '위와 같게', phase: above })
  if (below && below.id !== above?.id) out.push({ label: '아래와 같게', phase: below })
  return out
})

/** Cancels the edit: this editor commits through the store, never through a cell value. */
function close() {
  props.params.api.stopEditing(true)
}

function choose(phase: WpPhase) {
  if (phase.id === item.value.phase_id) return close()
  const id = item.value.id
  close()
  /*
   * No confirm. Picking a neighbour's phase from a seam leaves the row where it stands
   * (the seam already *is* that block's end), and picking a distant one moves it to the
   * end of that block — which is the stated meaning of picking it. A dialog here would ask
   * the user to re-approve the thing they just clicked.
   */
  void board.assignPhase(id, phase.id)
}

/**
 * Hands off to the 관리 팝업 with this row as the anchor (`plan.md` §0.4).
 *
 * The editor closes first: it is an ag-grid popup and would be destroyed underneath the
 * modal anyway, and the modal is owned by the shell precisely so it survives that.
 */
function openManager() {
  const id = item.value.id
  close()
  structure.open({ kind: 'phase', anchorItemId: id })
}

defineExpose({
  /** Value is unchanged by design — the mutation went through the store. */
  getValue: () => props.params.value,
})
</script>

<template>
  <div
    class="wp-w-[320px] wp-overflow-hidden wp-rounded-md wp-border wp-border-solid wp-bg-white wp-text-[13px] wp-shadow-lg"
    style="border-color: #e4e4e4"
  >
    <div
      class="wp-flex wp-items-center wp-justify-between wp-border-0 wp-border-b wp-border-solid wp-px-3 wp-py-2 wp-text-xs wp-font-medium"
      style="border-color: #f0f0f0; color: #8c8c8c"
    >
      <span>Phase 선택</span>
      <span style="color: #8c8c8c">미배정 행</span>
    </div>

    <!--
      §0.2.3 — a gray row's most likely destination is one of the two blocks it is already
      touching, so those come first and cost one click. The full list is still right below;
      this is an accelerator, not a restriction.
    -->
    <div
      v-if="shortcuts.length > 0"
      class="wp-border-0 wp-border-b wp-border-solid wp-px-2 wp-py-2"
      style="border-color: #f0f0f0; background-color: #fafafa"
    >
      <p class="wp-mb-1 wp-px-1 wp-text-2xs" style="color: #bfbfbf">인접 Phase</p>
      <button
        v-for="shortcut in shortcuts"
        :key="shortcut.label"
        type="button"
        class="wp-flex wp-w-full wp-items-center wp-gap-2 wp-rounded wp-px-2 wp-py-1.5 wp-text-left hover:wp-bg-white"
        @click="choose(shortcut.phase)"
      >
        <span
          class="wp-h-3 wp-w-[3px] wp-shrink-0 wp-rounded"
          :style="{ backgroundColor: phaseColor(shortcut.phase.seq_no).accent }"
        />
        <span class="wp-shrink-0 wp-font-medium">{{ shortcut.label }}</span>
        <span class="wp-truncate wp-text-xs" style="color: #8c8c8c">
          Phase {{ shortcut.phase.seq_no }}. {{ shortcut.phase.name }}
        </span>
      </button>
    </div>

    <div class="wp-max-h-[240px] wp-overflow-y-auto wp-py-1">
      <button
        v-for="phase in phases"
        :key="phase.id"
        type="button"
        class="wp-flex wp-w-full wp-items-center wp-gap-2 wp-px-3 wp-py-1.5 wp-text-left hover:wp-bg-slate-50"
        :style="phase.id === item.phase_id ? { backgroundColor: '#F5F5F5', fontWeight: 600 } : {}"
        @click="choose(phase)"
      >
        <span
          class="wp-h-3 wp-w-[3px] wp-shrink-0 wp-rounded"
          :style="{ backgroundColor: phaseColor(phase.seq_no).accent }"
        />
        <span class="wp-truncate">Phase {{ phase.seq_no }}. {{ phase.name }}</span>
      </button>
      <p v-if="phases.length === 0" class="wp-px-3 wp-py-2 wp-text-xs" style="color: #bfbfbf">
        등록된 Phase가 없습니다.
      </p>
    </div>

    <div class="wp-border-0 wp-border-t wp-border-solid wp-px-2 wp-py-2" style="border-color: #f0f0f0">
      <AButton block size="small" :disabled="board.readOnly.value" @click="openManager">
        ＋ 새 Phase 생성
      </AButton>
      <p class="wp-mt-1 wp-px-1 wp-text-2xs" style="color: #bfbfbf">
        Phase 관리 창이 열리고, 이 행이 새 Phase 의 첫 행이 됩니다.
      </p>
    </div>
  </div>
</template>
