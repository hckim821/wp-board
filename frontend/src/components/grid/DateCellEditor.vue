<script setup lang="ts">
import { ref } from 'vue'
import type { ICellEditorParams } from 'ag-grid-community'
import { DatePicker as ADatePicker } from 'ant-design-vue'
import dayjs, { type Dayjs } from 'dayjs'
import type { WpItem } from '../../api/types'

/** 완료일 picker. The wire format is a plain `YYYY-MM-DD` date, never a datetime. */
const props = defineProps<{ params: ICellEditorParams<WpItem> }>()

const value = ref<Dayjs | undefined>(
  props.params.data.completion_date ? dayjs(props.params.data.completion_date) : undefined,
)

defineExpose({
  getValue: () => (value.value ? value.value.format('YYYY-MM-DD') : null),
})
</script>

<template>
  <div class="wp-bg-white wp-p-1.5 wp-shadow-lg">
    <ADatePicker
      v-model:value="value"
      class="wp-w-[160px]"
      value-format="YYYY-MM-DD"
      placeholder="완료일"
      :get-popup-container="(node: HTMLElement) => node.parentElement ?? node"
    />
  </div>
</template>
