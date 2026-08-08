<script setup lang="ts">
import { computed, ref } from 'vue'
import { Alert as AAlert, Button as AButton, Empty as AEmpty, Spin as ASpin } from 'ant-design-vue'
import { describeApiError } from '../api/client'
import { ITEM_STATUS_LABEL, type ItemStatus, type WpItem } from '../api/types'
import { useBoardContext } from '../runtime/context'
import { buildDashboardLayout, dashboardText } from '../composables/useDashboard'
import {
  DASH_STATUS_ORDER,
  DASH_STATUS_STYLE,
  DASH_UNASSIGNED,
  OWNER_KINDS,
  ownerColor,
  UNASSIGNED_OWNER_COLOR,
} from '../theme/dashboard'
import LegendSwatch from '../components/dashboard/LegendSwatch.vue'
import ItemPopover from '../components/dashboard/ItemPopover.vue'
import ProjectLinksGrid from '../components/dashboard/ProjectLinksGrid.vue'

/**
 * 프로젝트 대시보드 — `docs/dashboard.jpg` as a screen (`plan.md` §0.5-2).
 *
 * Read-only, and it issues **no requests of its own**: everything it draws comes from the
 * rows the board store already loaded. That is the reason there is no new API for this
 * screen and the reason switching to it is instant.
 *
 * It is mounted *instead of* the grid, never alongside it — `BoardShell` swaps the two, so
 * ag-grid is torn down before this renders (§0.5-2). Two live grids on one screen is how a
 * federated remote ends up with two ag-grid module registries fighting over one DOM.
 *
 * No `<style>` block anywhere: colours are inline (chosen at runtime from a status, which
 * Tailwind's content scanner could never see) and layout is `wp-`-prefixed utilities. A
 * remote that emits unprefixed CSS is the failure mode INTEGRATION.md §5 exists to prevent.
 */
const { api, board, makerName } = useBoardContext()

const layout = computed(() => buildDashboardLayout(board.items.value))

/*
 * 높이 통일 (`plan.md` §0.5.4b) — 마일스톤 헤더끼리, 항목 카드끼리 전부 같은 높이.
 *
 * 측정 대신 **보드 전체에서 가장 긴 값이 몇 줄을 먹는지 한 번 추정**하고, 그 높이를 모든
 * 셀에 못박는다. 측정(ResizeObserver + 2-pass)은 정확하지만 카드 수만큼 관측자를 달고
 * 리플로우를 두 번 돌아야 하고, 이 화면은 읽기 전용 요약이라 그 비용을 낼 이유가 없다.
 *
 * 추정이 한 줄 빗나가도 **어긋나 보이지는 않는다** — 어긋남이 금지 사항이고, 전부 같은 높이를
 * 쓰는 한 그건 구조적으로 불가능하다. 넘치면 클램프되고, 잘린 내용은 팝오버가 보완한다(§0.5.4b).
 */
const COLUMN_CHARS = 15
const LINE_HEIGHT_PX = 15

/** 한글은 한 글자가 라틴 두 글자 폭에 가깝다 — 폭 추정에서 이 차이를 무시하면 늘 한 줄 모자란다. */
function displayWidth(text: string): number {
  let width = 0
  for (const ch of text) width += /[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uff00-\uff60]/.test(ch) ? 2 : 1
  return width
}

const linesNeeded = (text: string, max: number) =>
  Math.min(max, Math.max(1, Math.ceil(displayWidth(text) / COLUMN_CHARS)))

/** Milestone 헤더: 번호 줄 + 이름(최대 2줄). */
const milestoneHeaderHeight = computed(() => {
  const names = layout.value.phases.flatMap((p) => p.milestones.map((m) => m.name ?? ''))
  const lines = names.reduce((max, name) => Math.max(max, linesNeeded(name, 2)), 1)
  return 12 + LINE_HEIGHT_PX + lines * LINE_HEIGHT_PX + 12
})

/** 항목 카드: No 줄 + 라벨(최대 2줄). 미배정 카드도 같은 높이를 쓴다. */
const cardHeight = computed(() => {
  const labels = [
    ...layout.value.phases.flatMap((p) => p.milestones.flatMap((m) => m.items)),
    ...layout.value.unassigned,
  ].map((item) => dashboardText(item))
  const lines = labels.reduce((max, label) => Math.max(max, linesNeeded(label, 2)), 1)
  return 6 + 13 + lines * LINE_HEIGHT_PX + 6
})

const exporting = ref(false)
const exportError = ref<string | null>(null)

/**
 * Downloads the server-generated PPTX (`plan.md` §0.5.6).
 *
 * Through the api client, not `window.open`: the request must carry the same auth headers as
 * every other call, and a plain link cannot. The object URL is revoked in `finally` — an
 * un-revoked blob URL pins the whole file in memory for the life of the document, and this
 * component is mounted and unmounted repeatedly.
 */
async function exportPptx() {
  const projectId = board.projectId.value
  if (projectId == null || exporting.value) return
  exporting.value = true
  exportError.value = null
  let url: string | null = null
  try {
    const blob = await api.exportDashboardPptx(projectId)
    url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${board.project.value?.name ?? 'dashboard'}.pptx`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } catch (error) {
    exportError.value = describeApiError(error, 'PPT 내보내기에 실패했습니다.')
  } finally {
    if (url) URL.revokeObjectURL(url)
    exporting.value = false
  }
}

const projectName = computed(() => board.project.value?.name ?? '')
const makerLabel = computed(
  () => makerName ?? (board.project.value ? `설비사 #${board.project.value.maker_id}` : ''),
)

/** 상단 집계 칩 — 전체 / 진행중 / 완료 / 보류 (§0.5-2). */
const chips = computed(() => [
  { key: 'TOTAL', label: '전체', value: layout.value.total, style: null },
  {
    key: 'IN_PROGRESS',
    label: ITEM_STATUS_LABEL.IN_PROGRESS,
    value: layout.value.counts.IN_PROGRESS,
    style: DASH_STATUS_STYLE.IN_PROGRESS,
  },
  {
    key: 'DONE',
    label: ITEM_STATUS_LABEL.DONE,
    value: layout.value.counts.DONE,
    style: DASH_STATUS_STYLE.DONE,
  },
  {
    key: 'HOLD',
    label: ITEM_STATUS_LABEL.HOLD,
    value: layout.value.counts.HOLD,
    style: DASH_STATUS_STYLE.HOLD,
  },
])

const progress = computed(() =>
  layout.value.total === 0 ? 0 : Math.round((layout.value.counts.DONE / layout.value.total) * 100),
)

/**
 * Column width. Milestones sit side by side inside their phase, so a phase with four of
 * them is four columns wide — which is exactly how the deck reads, and why the whole strip
 * scrolls horizontally instead of wrapping.
 *
 * Narrowed from 176px to 128px (`plan.md` §0.5-2, 2026-08-08): the full strip was wider than
 * most screens. Labels that no longer fit are clamped to two lines and read in full from the
 * hover popover, which is cheaper than making every reader scroll horizontally.
 */
const phaseWidth = (milestoneCount: number) => `${Math.max(milestoneCount, 1) * 128 + 16}px`

function cardStyle(item: WpItem) {
  const style = DASH_STATUS_STYLE[item.status] ?? DASH_STATUS_STYLE.NOT_STARTED
  // NA 는 이제 흐림이 아니라 짙은 배경으로 차단을 표현한다 (§0.5, 2026-08-08) — opacity 없음.
  return { backgroundColor: style.bg, borderColor: style.border, color: style.text }
}

const statusText = (status: ItemStatus) => ITEM_STATUS_LABEL[status] ?? status
</script>

<template>
  <!--
    높이는 **내용만큼** (`plan.md` §0.5.5). 이전에는 `h-full` + `flex-1` 로 뷰포트를 채워,
    항목이 적은 프로젝트도 빈 공간을 크게 물고 그 아래 주요 링크 표가 화면 밖으로 밀렸다.
  -->
  <div class="wp-flex wp-flex-col wp-gap-4 wp-overflow-auto" style="max-height: 100%">
    <div class="wp-flex wp-flex-col">
    <div class="wp-mb-2 wp-flex wp-flex-wrap wp-items-center wp-gap-3">
      <div>
        <div class="wp-text-2xs" style="color: #8c8c8c">{{ makerLabel }}</div>
        <div class="wp-text-base wp-font-bold" style="color: #1f2937">{{ projectName }}</div>
      </div>

      <span
        v-for="chip in chips"
        :key="chip.key"
        class="wp-inline-flex wp-items-center wp-gap-1.5 wp-rounded-full wp-border wp-border-solid wp-px-3 wp-py-1 wp-text-xs"
        :style="{
          backgroundColor: chip.style?.bg ?? '#f8fafc',
          borderColor: chip.style?.border ?? '#e2e8f0',
          color: chip.style?.text ?? '#334155',
        }"
      >
        {{ chip.label }}
        <b>{{ chip.value }}</b>
      </span>
      <span class="wp-text-xs" style="color: #8c8c8c">진행률 {{ progress }}%</span>
      <span style="flex: 1"></span>
      <!--
        읽기 연산이므로 `readOnly` 여도 남는다 (§0.5.6). 생성은 서버(python-pptx)가 한다.
      -->
      <AButton size="small" data-wp-export-pptx :loading="exporting" @click="exportPptx">
        PPT 내보내기
      </AButton>
    </div>

    <AAlert v-if="exportError" type="error" show-icon class="wp-mb-2" :message="exportError" />

    <div class="wp-relative wp-overflow-x-auto wp-rounded wp-border wp-border-solid"
         style="border-color: #e5e7eb; background: #fbfbfd">
      <AEmpty
        v-if="layout.total === 0 && !board.loading.value"
        class="wp-py-16"
        description="행이 없습니다."
      />

      <!-- 가로 스크롤은 이 컨테이너 안에서만 — 호스트 레이아웃을 밀어내지 않는다. -->
      <div v-else class="wp-flex wp-items-start wp-gap-2 wp-p-3" style="min-width: max-content">
        <!--
          `data-wp-*` here and on the cards are assertion hooks for `npm run check:dom`.
          Attributes rather than classes on purpose: a class is styling the host could
          plausibly target, an unprefixed data attribute is inert.
        -->
        <div
          v-for="phase in layout.phases"
          :key="phase.key"
          class="wp-rounded-lg wp-p-2"
          data-wp-dash-phase
          :style="{ width: phaseWidth(phase.milestones.length), backgroundColor: '#f1f3f7' }"
        >
          <!--
            Phase 화살표 헤더. The chevron is a clip-path on an inline style rather than a
            utility class: the shape is identical for every phase, only the colour changes.
          -->
          <div
            class="wp-truncate wp-py-1.5 wp-pl-3 wp-pr-5 wp-text-xs wp-font-bold"
            :style="{
              backgroundColor: phase.color,
              color: '#ffffff',
              clipPath: 'polygon(0 0, calc(100% - 12px) 0, 100% 50%, calc(100% - 12px) 100%, 0 100%)',
            }"
            :title="`Phase ${phase.phaseSeq}. ${phase.name}`"
          >
            Phase {{ phase.phaseSeq }}. {{ phase.name }}
            <span class="wp-font-normal" style="opacity: 0.8">({{ phase.itemCount }})</span>
          </div>

          <div
            class="wp-mt-2 wp-grid wp-gap-2"
            :style="{
              gridTemplateColumns: `repeat(${Math.max(phase.milestones.length, 1)}, minmax(120px, 1fr))`,
            }"
          >
            <div v-for="milestone in phase.milestones" :key="milestone.key">
              <!-- 높이 통일 (§0.5.4b): 보드 전체에서 같은 값을 쓴다. -->
              <div
                class="wp-overflow-hidden wp-rounded wp-border wp-border-solid wp-px-2 wp-py-1.5 wp-text-center"
                data-wp-milestone-header
                :style="{
                  borderColor: phase.color,
                  backgroundColor: '#ffffff',
                  height: `${milestoneHeaderHeight}px`,
                }"
              >
                <div class="wp-text-2xs wp-font-bold" :style="{ color: phase.color }">
                  {{ milestone.numberLabel || '—' }}
                </div>
                <div class="wp-mt-0.5 wp-clamp-2 wp-text-2xs wp-leading-4" style="color: #64748b">
                  {{ milestone.name }}
                </div>
              </div>

              <div class="wp-mt-2 wp-flex wp-flex-col wp-gap-2">
                <!--
                  hover 는 공용 팝오버 (§0.5-2, 2026-08-08) — 담당·상태·action item·산출물.
                  카드 자체에는 No 와 표시 텍스트만 남긴다: 담당자 줄을 지운 것이 폭을 줄인
                  가장 큰 요인이고, 그 정보는 팝오버가 더 정확하게 말한다.
                -->
                <ItemPopover
                  v-for="item in milestone.items"
                  :key="item.id"
                  :index="item.row_no"
                  :title="item.title"
                  :deliverable="item.deliverable"
                  :owners="item.owners.map((o) => o.name)"
                  :status="item.status"
                >
                  <div
                    class="wp-relative wp-overflow-hidden wp-rounded wp-border wp-border-solid wp-py-1.5 wp-pl-2.5 wp-pr-1.5"
                    data-wp-dash-card
                    :style="{ ...cardStyle(item), height: `${cardHeight}px` }"
                  >
                    <!-- 좌측 세로 바 = 주관 (§0.5). -->
                    <i
                      class="wp-absolute wp-inset-y-0 wp-left-0"
                      style="width: 5px"
                      :style="{ backgroundColor: ownerColor(item.owners) }"
                    ></i>
                    <!--
                      index 만 가운데, 아래 표시 텍스트는 좌측 정렬 유지 (사용자 지정).
                      opacity 로 흐리지 않는다 — NA 카드는 이제 짙은 배경 + 밝은 글자라
                      (§0.5, 2026-08-08) 여기서 한 번 더 흐리면 대비가 무너진다.
                    -->
                    <div class="wp-text-center wp-text-2xs wp-font-bold">
                      {{ item.row_no }}
                    </div>
                    <div class="wp-mt-0.5 wp-clamp-2 wp-text-2xs wp-font-semibold wp-leading-4">
                      {{ dashboardText(item) }}
                    </div>
                  </div>
                </ItemPopover>
              </div>
            </div>
          </div>
        </div>

        <!-- 미배정(회색) 행은 맨 뒤 무색 컬럼으로 (§0.5-2). -->
        <div
          v-if="layout.unassigned.length > 0"
          class="wp-rounded-lg wp-p-2"
          style="width: 144px; background-color: #f1f3f7"
        >
          <div
            class="wp-truncate wp-py-1.5 wp-pl-3 wp-pr-5 wp-text-xs wp-font-bold"
            :style="{ backgroundColor: DASH_UNASSIGNED, color: '#475569' }"
          >
            미배정 <span class="wp-font-normal">({{ layout.unassigned.length }})</span>
          </div>
          <div class="wp-mt-2 wp-flex wp-flex-col wp-gap-2">
            <ItemPopover
              v-for="item in layout.unassigned"
              :key="item.id"
              :index="item.row_no"
              :title="item.title"
              :deliverable="item.deliverable"
              :owners="item.owners.map((o) => o.name)"
              :status="item.status"
            >
              <div
                class="wp-relative wp-overflow-hidden wp-rounded wp-border wp-border-dashed wp-py-1.5 wp-pl-2.5 wp-pr-1.5"
                data-wp-dash-card
                data-wp-dash-unassigned
                :style="{ ...cardStyle(item), height: `${cardHeight}px` }"
              >
                <i
                  class="wp-absolute wp-inset-y-0 wp-left-0"
                  style="width: 5px"
                  :style="{ backgroundColor: ownerColor(item.owners) }"
                ></i>
                <div class="wp-text-center wp-text-2xs wp-font-bold">{{ item.row_no }}</div>
                <div class="wp-mt-0.5 wp-clamp-2 wp-text-2xs wp-font-semibold wp-leading-4">
                  {{ dashboardText(item) || '(내용 없음)' }}
                </div>
              </div>
            </ItemPopover>
          </div>
        </div>
      </div>

      <div
        v-if="board.loading.value"
        class="wp-absolute wp-inset-0 wp-z-10 wp-flex wp-items-center wp-justify-center"
        style="background: rgba(255, 255, 255, 0.6)"
      >
        <ASpin />
      </div>
    </div>

    <!--
      하단 범례 — 주관(좌측 바) 먼저, 상태(배경) 나중 (§0.5 범례 개정).

      두 그룹이 **같은 미니 카드**를 쓰고, 각자 설명하는 것 하나만 바꾼다: 주관은 좌측 바
      색만, 상태는 배경색만. 그래서 "어느 색이 카드의 어디에 나타나는가" 를 글자가 아니라
      스와치 자체가 말한다.
    -->
    <div class="wp-mt-2 wp-flex wp-flex-wrap wp-items-center wp-gap-x-4 wp-gap-y-1 wp-text-2xs"
         style="color: #64748b">
      <b data-wp-legend-group="owner" style="color: #334155">주관 (좌측 바)</b>
      <span v-for="kind in OWNER_KINDS" :key="kind.key" class="wp-inline-flex wp-items-center wp-gap-1">
        <!-- 배경은 전부 진행전(흰색)으로 고정 — 여기서 변하는 것은 좌측 바뿐이다. -->
        <LegendSwatch
          :bg="DASH_STATUS_STYLE.NOT_STARTED.bg"
          :border="DASH_STATUS_STYLE.NOT_STARTED.border"
          :bar="kind.color"
        />
        {{ kind.label }}
      </span>
      <b class="wp-ml-2" data-wp-legend-group="status" style="color: #334155">상태 (배경)</b>
      <span v-for="status in DASH_STATUS_ORDER" :key="status" class="wp-inline-flex wp-items-center wp-gap-1">
        <!-- 좌측 바는 전부 미지정 slate 로 고정 — 여기서 변하는 것은 배경뿐이다. -->
        <LegendSwatch
          :bg="DASH_STATUS_STYLE[status].bg"
          :border="DASH_STATUS_STYLE[status].border"
          :bar="UNASSIGNED_OWNER_COLOR"
        />
        {{ statusText(status) }}
      </span>
    </div>
    </div>

    <!-- 주요 링크 (`plan.md` §0.5.5) — 대시보드 아래. -->
    <ProjectLinksGrid
      v-if="board.projectId.value != null"
      :api="api"
      :project-id="board.projectId.value"
      :read-only="board.hostReadOnly.value"
    />
  </div>
</template>
