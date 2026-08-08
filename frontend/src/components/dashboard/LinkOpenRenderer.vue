<script setup lang="ts">
import { computed } from 'vue'
import { LinkOutlined } from '@ant-design/icons-vue'
import { isValidLinkUrl, type ProjectLink } from '../../api/types'

/**
 * The 링크 cell: the URL text, plus a connect icon pinned to the cell's **right** edge
 * (`plan.md` §0.5.5).
 *
 * Right rather than left so it never sits over the text the user is editing. It appears only
 * for a URL that would actually open — an icon that does nothing when clicked is worse than
 * no icon, because the user concludes the link is broken rather than unfinished.
 */
const props = defineProps<{ params: { data?: ProjectLink; value?: string } }>()

const url = computed(() => props.params?.data?.url ?? props.params?.value ?? '')
const openable = computed(() => isValidLinkUrl(url.value))

function open(event: MouseEvent) {
  // ag-grid opens the editor on click (singleClickEdit); the icon is not an edit gesture.
  event.stopPropagation()
  if (!openable.value) return
  // `noopener`: without it the opened page gets a live handle back into the HOST window.
  window.open(url.value.trim(), '_blank', 'noopener')
}
</script>

<template>
  <div class="wp-flex wp-w-full wp-items-center wp-gap-1">
    <span class="wp-truncate" style="flex: 1">{{ url }}</span>
    <button
      v-if="openable"
      type="button"
      data-wp-link-open
      aria-label="새 창으로 열기"
      class="wp-inline-flex wp-shrink-0 wp-cursor-pointer wp-items-center"
      style="background: none; border: none; padding: 0 2px; color: #1d4ed8"
      @click="open"
    >
      <LinkOutlined />
    </button>
  </div>
</template>
