<script setup lang="ts">
import { computed } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import type { WpItem } from '../../api/types'
import { phaseColor } from '../../theme/palette'

/**
 * Phase column, block-first-row-only labelling.
 *
 * ag-grid Community has no Row Grouping and `colDef.rowSpan` fights with managed row
 * drag (`plan.md` §5.3), so a phase block is conveyed by rendering its label once — on
 * the block's first row — over a continuous left colour bar.
 */
const props = defineProps<{ params: ICellRendererParams<WpItem> }>()

const item = computed(() => props.params.data ?? null)
const color = computed(() => phaseColor(item.value?.phase_no))
const isStart = computed(() => item.value?.is_phase_block_start ?? false)
const unassigned = computed(() => item.value?.phase_id == null)
</script>

<template>
  <div class="wp-relative wp-flex wp-h-full wp-items-center wp-pl-3">
    <span
      class="wp-absolute wp-left-0 wp-top-0 wp-h-full wp-w-[3px]"
      :style="{ backgroundColor: color.accent }"
      aria-hidden="true"
    />

    <template v-if="unassigned">
      <span class="wp-text-xs wp-italic" style="color: #bfbfbf">미지정</span>
    </template>
    <template v-else-if="isStart">
      <span class="wp-truncate wp-text-[13px] wp-font-semibold" :style="{ color: color.text }">
        {{ item?.phase_display }}
      </span>
    </template>
    <template v-else>
      <!-- Continuation rows stay quiet so the eye reads one block, not N repeats. -->
      <span class="wp-select-none wp-text-xs" style="color: #d9d9d9">〃</span>
    </template>
  </div>
</template>
