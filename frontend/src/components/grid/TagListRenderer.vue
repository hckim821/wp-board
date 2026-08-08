<script setup lang="ts">
import { computed } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import { visibleDocuments, type DocumentRef, type OwnerRef, type WpItem } from '../../api/types'

/**
 * Renders the `/`- and `+`-separated multi-values of the source sheet as chips.
 *
 * A document chip leads with its **number** (`plan.md` §0.5.10) — the derived `no`, which
 * replaced the circled `code`. Owners have no number and render as bare names, so the
 * discriminator is `'no' in entry` rather than a source check: the entry type decides its own
 * label, and adding a third source later cannot silently pick the wrong branch.
 */
const props = defineProps<{
  params: ICellRendererParams<WpItem> & { source: 'documents' | 'owners' }
}>()

/**
 * `no == null` 인 문서는 **그리지 않는다** (`plan.md` §0.5.10 정밀화).
 *
 * null 은 "사용하지 않는 문서" 라는 뜻이고, 그런 문서가 행에 남아 있는 것은 정리되지 않은
 * 잔재다. 여기서 거르면 그 문서를 참조하던 **다른 행들의 잔재까지** 한꺼번에 사라진다 —
 * 팝업이 손댄 행만 고쳐서는 닿지 않는 곳이다.
 */
const entries = computed<(DocumentRef | OwnerRef)[]>(() => {
  const data = props.params.data
  if (!data) return []
  if (props.params.source === 'owners') return data.owners
  return visibleDocuments(data.documents)
})

/**
 * 미사용 문서는 번호 없이 이름만 (`plan.md` §0.5.10 정밀화).
 *
 * `no` 가 null 인 것은 "번호가 아직 없다" 가 아니라 "사용하지 않는 문서" 라는 뜻이고, 거기에
 * 임의의 숫자를 찍으면 사용 문서의 1..N 과 섞여 읽힌다.
 */
const label = (entry: DocumentRef | OwnerRef) =>
  'no' in entry ? (entry.no == null ? entry.name : `${entry.no}. ${entry.name}`) : entry.name
</script>

<template>
  <div class="wp-flex wp-h-full wp-flex-wrap wp-items-center wp-gap-1 wp-py-1">
    <span v-if="entries.length === 0" class="wp-text-xs wp-italic" style="color: #bfbfbf">—</span>
    <span
      v-for="entry in entries"
      :key="entry.id"
      class="wp-max-w-full wp-truncate wp-rounded wp-border wp-border-solid wp-px-1.5 wp-py-px wp-text-2xs"
      style="border-color: #e4e4e4; background-color: #fafafa; color: #595959"
      :title="label(entry)"
    >
      {{ label(entry) }}
    </span>
  </div>
</template>
