<script setup lang="ts">
/**
 * One legend swatch, shaped like the card it explains (`plan.md` §0.5, 범례 개정).
 *
 * Both legends on the dashboard use this same mini card, and each varies exactly the one
 * thing it is describing: 주관 changes only the left bar, 상태 changes only the background.
 * The previous version used a square for one and a **circle** for the other, which made the
 * two look like unrelated vocabularies and — worse — said nothing about *where* on a card
 * the colour appears. A reader had to be told "좌측 바 = 주관" in words; now the swatch shows it.
 *
 * `bar: null` renders the box with no bar at all. That is not a styling convenience: the
 * 전체 현황 minimap cells genuinely have no owner bar (the overview payload carries no
 * owners), so its legend has to explain a plain box or it would be describing a cell that
 * does not exist.
 */
withDefaults(
  defineProps<{
    bg: string
    border: string
    /** Left bar colour, or null for a bar-less box. */
    bar?: string | null
  }>(),
  { bar: null },
)
</script>

<template>
  <i
    class="wp-relative wp-inline-block wp-overflow-hidden wp-rounded-sm wp-border wp-border-solid wp-align-middle"
    data-wp-legend-swatch
    style="width: 22px; height: 14px"
    :style="{ backgroundColor: bg, borderColor: border }"
  >
    <i
      v-if="bar"
      class="wp-absolute wp-inset-y-0 wp-left-0"
      data-wp-legend-bar
      style="width: 4px"
      :style="{ backgroundColor: bar }"
    ></i>
  </i>
</template>
