<script setup lang="ts">
import { computed } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import { ITEM_STATUS_LABEL, type ItemStatus, type WpItem } from '../../api/types'
import { DASH_STATUS_STYLE } from '../../theme/dashboard'

const props = defineProps<{ params: ICellRendererParams<WpItem> }>()

const status = computed<ItemStatus>(() => props.params.data?.status ?? 'NOT_STARTED')
/** 같은 표를 쓴다 — 그리드 칩과 대시보드 카드가 다른 색으로 같은 상태를 말하면 안 된다. */
const style = computed(() => DASH_STATUS_STYLE[status.value] ?? DASH_STATUS_STYLE.NOT_STARTED)
</script>

<template>
  <div class="wp-flex wp-h-full wp-items-center">
    <span
      class="wp-rounded-full wp-border wp-border-solid wp-px-2 wp-py-0.5 wp-text-2xs wp-font-medium"
      :style="{ backgroundColor: style.bg, color: style.text, borderColor: style.border }"
    >
      {{ ITEM_STATUS_LABEL[status] }}
    </span>
  </div>
</template>
