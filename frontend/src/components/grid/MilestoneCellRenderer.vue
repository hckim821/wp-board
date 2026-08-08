<script setup lang="ts">
import { computed } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import type { WpItem } from '../../api/types'
import { phaseColor } from '../../theme/palette'

const props = defineProps<{ params: ICellRendererParams<WpItem> }>()

const item = computed(() => props.params.data ?? null)
const color = computed(() => phaseColor(item.value?.phase_no))
const isStart = computed(() => item.value?.is_milestone_block_start ?? false)
const unassigned = computed(() => item.value?.milestone_id == null)
</script>

<template>
  <div class="wp-flex wp-h-full wp-items-center">
    <span v-if="unassigned" class="wp-text-xs wp-italic" style="color: #bfbfbf">미지정</span>
    <span
      v-else-if="isStart"
      class="wp-truncate wp-rounded wp-px-1.5 wp-py-0.5 wp-text-[12px] wp-font-medium"
      :style="{ backgroundColor: color.tintStrong, color: color.text }"
    >
      {{ item?.milestone_display }}
    </span>
    <span v-else class="wp-select-none wp-pl-1.5 wp-text-xs" style="color: #d9d9d9">〃</span>
  </div>
</template>
