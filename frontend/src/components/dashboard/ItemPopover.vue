<script setup lang="ts">
import { computed } from 'vue'
import { Popover as APopover } from 'ant-design-vue'
import { ITEM_STATUS_LABEL, type ItemStatus } from '../../api/types'
import { DASH_STATUS_STYLE, ownerKindFromNames, OWNER_KINDS } from '../../theme/dashboard'

/**
 * The hover popover shared by the project dashboard's cards and the 전체 현황 minimap cells
 * (`plan.md` §0.5-2 / §0.5-3, 2026-08-08).
 *
 * **One component, deliberately.** The two screens show the same item from different
 * distances, and before this they disagreed about what hovering one meant: the dashboard card
 * printed the owner inline and the minimap offered a single-line tooltip. Sharing it also
 * fixes the shape in one place — header is the action item, body is 담당 · 상태 · deliverable.
 *
 * **The index is a prefix on the title, not a row of its own** (2026-08-08 revision). It was
 * first removed outright, on the grounds that a row number means little when read across
 * projects; the revision puts it back as `"1. 제목"` because it is how people refer to an item
 * out loud. What does not come back is the separate `No.` line — one label, one line.
 *
 * Takes owner **names**, not `OwnerRef`s: the overview payload carries names only (its
 * projects each own a separate copy of the owner table), and a component that demanded ids
 * could not serve it.
 */
const props = defineProps<{
  /** 항목 번호. Prefixed onto the title as `1. …`; omitted when null. */
  index?: number | null
  title: string | null
  deliverable: string | null
  owners: string[]
  status: ItemStatus
}>()

const kind = computed(() => ownerKindFromNames(props.owners))

const ownerLabel = computed(() => {
  if (props.owners.length === 0) return '미지정'
  // 2명 이상은 이름을 다 보여주되 '공동' 임을 함께 밝힌다 — 색 바만으로는 몇 명인지 모른다.
  if (props.owners.length > 1) return `${props.owners.join(' + ')} (공동)`
  return props.owners[0]!
})

const ownerColorOf = computed(
  () => OWNER_KINDS.find((k) => k.key === kind.value)?.color ?? '#cbd5e1',
)

const statusStyle = computed(() => DASH_STATUS_STYLE[props.status] ?? DASH_STATUS_STYLE.NOT_STARTED)

const headline = computed(() => {
  const text = (props.title ?? '').trim() || '(제목 없음)'
  return props.index == null ? text : `${props.index}. ${text}`
})
</script>

<template>
  <APopover :mouse-enter-delay="0.2" placement="top">
    <template #title>
      <div data-wp-popover-title class="wp-text-xs wp-font-semibold" style="max-width: 320px; color: #0f172a">
        {{ headline }}
      </div>
    </template>
    <template #content>
      <div data-wp-popover-body class="wp-flex wp-flex-col wp-gap-1.5 wp-text-xs" style="max-width: 320px">
        <div class="wp-flex wp-items-start wp-gap-2">
          <span class="wp-shrink-0" style="width: 52px; color: #94a3b8">담당</span>
          <span class="wp-inline-flex wp-items-center wp-gap-1.5" style="color: #334155">
            <i
              class="wp-inline-block wp-shrink-0 wp-rounded-sm"
              style="width: 4px; height: 12px"
              :style="{ backgroundColor: ownerColorOf }"
            ></i>
            {{ ownerLabel }}
          </span>
        </div>
        <div class="wp-flex wp-items-start wp-gap-2">
          <span class="wp-shrink-0" style="width: 52px; color: #94a3b8">상태</span>
          <span
            class="wp-inline-flex wp-items-center wp-rounded-full wp-border wp-border-solid wp-px-2"
            :style="{
              backgroundColor: statusStyle.bg,
              borderColor: statusStyle.border,
              color: statusStyle.text,
            }"
          >
            {{ ITEM_STATUS_LABEL[props.status] ?? props.status }}
          </span>
        </div>
        <div class="wp-flex wp-items-start wp-gap-2">
          <span class="wp-shrink-0" style="width: 52px; color: #94a3b8">산출물</span>
          <span style="color: #334155">{{ (props.deliverable ?? '').trim() || '—' }}</span>
        </div>
      </div>
    </template>
    <slot />
  </APopover>
</template>
