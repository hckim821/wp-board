<script setup lang="ts">
import { computed } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import { Button as AButton, Popconfirm as APopconfirm, Tooltip as ATooltip } from 'ant-design-vue'
import type { WpItem } from '../../api/types'
import { useBoardContext } from '../../runtime/context'

const props = defineProps<{ params: ICellRendererParams<WpItem> }>()

const { board, popupContainer } = useBoardContext()
const item = computed(() => props.params.data ?? null)
const disabled = computed(() => board.readOnly.value || board.saving.value)

/**
 * Inserts an **unassigned (gray) row** directly below (`plan.md` §0.2).
 *
 * It inherits nothing on purpose: an inherited row is born inside a block, and since drag
 * is confined to blocks there was previously no way to open a new Phase between two
 * existing ones. A gray row can be dragged to any seam and classified there.
 */
function insertBelow() {
  if (item.value) void board.insertBelow(item.value.id)
}

function remove() {
  if (item.value) void board.deleteItem(item.value.id)
}
</script>

<template>
  <div class="wp-flex wp-h-full wp-items-center wp-gap-1">
    <ATooltip title="아래에 미배정(회색) 행 추가 — Phase·Milestone 은 이후 셀에서 지정" :get-popup-container="popupContainer">
      <AButton size="small" type="text" :disabled="disabled" @click="insertBelow">
        <span class="wp-text-base wp-leading-none">＋</span>
      </AButton>
    </ATooltip>

    <APopconfirm
      title="이 행을 삭제할까요?"
      ok-text="삭제"
      cancel-text="취소"
      :disabled="disabled"
      :get-popup-container="popupContainer"
      @confirm="remove"
    >
      <AButton size="small" type="text" danger :disabled="disabled">
        <span class="wp-text-sm wp-leading-none">🗑</span>
      </AButton>
    </APopconfirm>
  </div>
</template>
