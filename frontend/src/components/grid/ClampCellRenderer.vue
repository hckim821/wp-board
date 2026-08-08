<script setup lang="ts">
import { computed } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import type { WpItem } from '../../api/types'

/**
 * Two-line clamped text, vertically centred in its cell (`plan.md` §0.5.9).
 *
 * A renderer exists here for one reason: the clamp is `display: -webkit-box`, and a single
 * element cannot be both that and a flex container. So the **cell** becomes the flex box
 * (`wp-cell-mid`) and this span is the clamped child it centres. The previous approach
 * pinned the text to the top with a `padding-top: 5px` nudge on the clamp itself, which is
 * what §0.5.9 asks to undo.
 */
const props = defineProps<{ params: ICellRendererParams<WpItem> }>()

const text = computed(() => String(props.params?.value ?? ''))
</script>

<template>
  <span class="wp-clamp-2 wp-w-full">{{ text }}</span>
</template>
