<script setup lang="ts">
import { DeleteOutlined } from '@ant-design/icons-vue'
import type { ProjectLink } from '../../api/types'

/** Row delete for the 주요 링크 table (`plan.md` §0.5.5). Local only until 저장. */
const props = defineProps<{
  params: { data?: ProjectLink; context?: { removeRow?: (id: number) => void; editable?: boolean } }
}>()

function remove() {
  const id = props.params?.data?.id
  if (id != null) props.params.context?.removeRow?.(id)
}
</script>

<template>
  <button
    v-if="props.params?.context?.editable"
    type="button"
    data-wp-link-delete
    aria-label="행 삭제"
    class="wp-inline-flex wp-cursor-pointer wp-items-center"
    style="background: none; border: none; padding: 2px; color: #b91c1c"
    @click="remove"
  >
    <DeleteOutlined />
  </button>
</template>
