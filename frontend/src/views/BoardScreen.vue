<script setup lang="ts">
import { computed, ref } from 'vue'
import { Alert as AAlert, Empty as AEmpty, Spin as ASpin } from 'ant-design-vue'
import { describeApiError } from '../api/client'
import type { ValidationResult } from '../api/types'
import { useBoardContext } from '../runtime/context'
import BoardToolbar from '../components/BoardToolbar.vue'
import WpGrid from '../components/grid/WpGrid.vue'

/**
 * The board — grid, toolbar, and (template tier only) the publish/validate feedback loop.
 *
 * **One screen for both tiers.** The renumbering, the boundary rules, the block-confined
 * drag and the gray-row flow are identical on a template and on a project (`plan.md`
 * §0.1); only the surrounding version machinery differs, and that difference lives in the
 * toolbar and in the two banners below. Forking this component per tier would mean every
 * future grid fix had to be made twice, and the project tier is the one users actually
 * spend their day in.
 */
const { api, board, notify } = useBoardContext()

const grid = ref<InstanceType<typeof WpGrid> | null>(null)
const exporting = ref(false)

const isTemplate = computed(() => board.tier === 'template')
const warnings = computed(() => board.validation.value?.warnings ?? [])
const errorCount = computed(() => board.validation.value?.errors.length ?? 0)

/*
 * 자동저장은 **없다** (`plan.md` §0.5.8). 30초 주기 `setInterval` 이 여기 있었고, 타이머만
 * 제거했다 — dirty 추적, 탭 전환·언마운트 시 미저장 확인, `hasUnsavedChanges()` 노출은 그대로다.
 * 저장은 툴바의 수동 버튼(템플릿 임시저장 / 프로젝트 저장)뿐이다.
 */

function reportIssues(result: ValidationResult, successMessage: string) {
  if (result.valid) {
    notify.success(successMessage)
    if (result.warnings.length > 0) {
      notify.warn(`경고 ${result.warnings.length}건이 있습니다.`)
    }
    return
  }
  const preview = result.errors
    .slice(0, 5)
    .map((issue) => `· ${issue.message}`)
    .join('\n')
  notify.error(
    `검증 오류 ${result.errors.length}건`,
    result.errors.length > 5 ? `${preview}\n· 외 ${result.errors.length - 5}건` : preview,
  )
  const first = result.errors.find((issue) => issue.item_id != null)
  if (first?.item_id != null) grid.value?.focusItem(first.item_id)
}

async function publish() {
  const result = await board.publish()
  if (result) reportIssues(result, '발행되었습니다.')
}

async function validate() {
  const result = await board.validateOnly()
  if (result) reportIssues(result, '검증을 통과했습니다.')
}

/**
 * 보드 XLSX 다운로드 (`plan.md` §0.5.7).
 *
 * PPT 내보내기와 같은 형태다 — api 클라이언트로 blob 을 받아(인증 헤더 경유) object URL 을
 * 만들고, anchor 로 내려받고, **revoke** 한다. revoke 를 빠뜨리면 문서 수명 내내 파일이
 * 메모리에 남는다.
 */
async function exportXlsx() {
  const scope = board.scope.value
  if (!scope || exporting.value) return
  exporting.value = true
  let url: string | null = null
  try {
    const blob = await api.exportBoardXlsx(scope)
    url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = isTemplate.value
      ? `${board.template.value?.code ?? 'template'}-v${board.version.value?.version_number ?? 0}.xlsx`
      : `${board.project.value?.name ?? 'project'}.xlsx`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } catch (error) {
    notify.error('XLSX 내보내기에 실패했습니다.', describeApiError(error, ''))
  } finally {
    if (url) URL.revokeObjectURL(url)
    exporting.value = false
  }
}
</script>

<template>
  <div class="wp-flex wp-h-full wp-flex-col">
    <BoardToolbar
      :exporting="exporting"
      @publish="publish"
      @validate="validate"
      @export-xlsx="exportXlsx"
    />

    <AAlert
      v-if="board.readOnly.value && (board.version.value || board.project.value)"
      type="info"
      show-icon
      banner
      class="wp-mb-2"
      :message="
        board.hostReadOnly.value
          ? '읽기 전용 — 이 보드에 대한 편집 권한이 없습니다.'
          : `읽기 전용 — 발행되었거나 보관된 버전입니다. 수정하려면 'draft 발행'으로 새 DRAFT 를 만드세요.`
      "
    />

    <AAlert
      v-if="isTemplate && errorCount > 0"
      type="error"
      show-icon
      banner
      class="wp-mb-2"
      :message="`발행 검증 오류 ${errorCount}건 — 표시된 셀을 수정한 뒤 다시 발행하세요.`"
    />

    <AAlert
      v-for="(warning, index) in warnings"
      :key="`${warning.code}-${warning.phase_id ?? ''}-${warning.milestone_id ?? ''}-${index}`"
      type="warning"
      show-icon
      banner
      class="wp-mb-2"
      :message="warning.message"
    />

    <div class="wp-relative wp-min-h-0 wp-flex-1">
      <div
        v-if="isTemplate && board.versionId.value == null && !board.loading.value"
        class="wp-py-16"
      >
        <AEmpty description="이 템플릿에는 아직 버전이 없습니다. 'draft 발행'으로 시작하세요." />
      </div>
      <WpGrid v-else ref="grid" />

      <!-- Overlay rather than a wrapping Spin, so the grid keeps its flex height. -->
      <div
        v-if="board.loading.value"
        class="wp-absolute wp-inset-0 wp-z-10 wp-flex wp-items-center wp-justify-center"
        style="background: rgba(255, 255, 255, 0.6)"
      >
        <ASpin />
      </div>
    </div>

    <p v-if="!board.readOnly.value" class="wp-px-1 wp-pt-1 wp-text-2xs" style="color: #bfbfbf">
      행 추가는 <b>미배정(회색) 행</b>을 만듭니다 — 원하는 자리로 끌어다 놓고 Phase 를 지정하세요.
      두 Phase 사이에 놓고 ‘새 Phase 생성’ 을 누르면 그 사이 번호로 들어갑니다. 번호는 서버가
      재계산합니다.
    </p>
  </div>
</template>
