<script setup lang="ts">
import { computed } from 'vue'
import {
  Button as AButton,
  Divider as ADivider,
  Popconfirm as APopconfirm,
  Progress as AProgress,
  Select as ASelect,
  Tag as ATag,
  Tooltip as ATooltip,
} from 'ant-design-vue'
import { VERSION_STATUS_LABEL, type VersionStatus } from '../api/types'
import { useBoardContext } from '../runtime/context'

/**
 * Board toolbar for both tiers (`plan.md` §0.1).
 *
 * The version machinery — the version select, 임시저장 / 검증 / 발행 / 폐기, draft 발행 — is
 * the **template editor's** and appears only there. A project has no versions at all, so
 * offering any of it would be offering an operation that does not exist; the project tier
 * gets one 저장 button and the actual point of that screen, which is the rows.
 *
 * What both share: the progress summary that replaced the spreadsheet's header row, the
 * gray-row counter (§0.2), 행 추가, and the server-generated XLSX export (§0.5.7 — CSV 와
 * 자동저장은 2026-08-08 에 제거됐다: 저장은 수동 버튼뿐이다, §0.5.8).
 */
const props = defineProps<{ exporting: boolean }>()

const emit = defineEmits<{
  (e: 'publish'): void
  (e: 'validate'): void
  (e: 'export-xlsx'): void
}>()

const { board, makerName, makerId, popupContainer } = useBoardContext()

const isTemplate = computed(() => board.tier === 'template')

const versionOptions = computed(() =>
  board.versions.value.map((version) => ({
    value: version.id,
    label: `v${version.version_number} · ${VERSION_STATUS_LABEL[version.status]}`,
  })),
)

const templateOptions = computed(() =>
  board.templates.value.map((t) => ({ value: t.id, label: t.name })),
)

const statusColor: Record<VersionStatus, string> = {
  DRAFT: 'processing',
  PUBLISHED: 'success',
  ARCHIVED: 'default',
}

const summary = computed(() => board.summary.value)
const hasDraft = computed(() => !!board.draftVersion.value)

/**
 * Which action set to show. Keyed on the store's read-only state, not on version status:
 * the host can revoke write access on a DRAFT, and then neither the save actions nor
 * 'draft 발행' (itself a write) may be offered.
 */
const canEdit = computed(() => !board.readOnly.value)
const canBranch = computed(
  () => isTemplate.value && !board.hostReadOnly.value && board.version.value?.status !== 'DRAFT',
)
/**
 * 설비사 표시명 — 세 단계로 떨어진다 (2026-08-09).
 *
 *   1. `makerName` prop — 호스트가 직접 준 이름. 이름 짓기는 호스트의 일이므로 이것이 우선.
 *   2. `project.maker_name` — 서버가 **호스트의 `MakerResolver`** 를 거쳐 실어 보낸 이름.
 *      전달 경로만 다를 뿐 출처는 똑같이 호스트다. 개발 하니스에서는 `wp_dev_makers.name`.
 *   3. `설비사 #{id}` — 위 둘이 다 없을 때만. 이름을 지어내지 않는다는 뜻이지, 여기까지
 *      내려오는 것이 정상이라는 뜻은 아니다.
 *
 * 2번이 없던 시절에는 호스트가 prop 을 늦게 주기만 해도 곧장 3번으로 떨어졌다.
 */
const makerLabel = computed(
  () => makerName() ?? board.project.value?.maker_name ?? `설비사 #${makerId()}`,
)

/** `v2`, or empty when the server sent no version number (`plan.md` §0.6). */
const sourceVersionLabel = computed(() => {
  const number = board.project.value?.source_version_number
  return number == null ? '' : `v${number}`
})
</script>

<template>
  <div class="wp-flex wp-flex-wrap wp-items-center wp-gap-x-3 wp-gap-y-2 wp-px-1 wp-py-2">
    <template v-if="isTemplate">
      <ATag color="purple" class="wp-m-0">기준 데이터</ATag>

      <ASelect
        :value="board.templateId.value ?? undefined"
        :options="templateOptions"
        :disabled="board.templates.value.length <= 1"
        size="small"
        style="min-width: 240px"
        :get-popup-container="popupContainer"
        @change="(value: unknown) => board.selectTemplate(Number(value))"
      />

      <ASelect
        :value="board.versionId.value ?? undefined"
        :options="versionOptions"
        size="small"
        style="min-width: 170px"
        :get-popup-container="popupContainer"
        @change="(value: unknown) => board.selectVersion(Number(value))"
      />

      <ATag
        v-if="board.version.value"
        :color="statusColor[board.version.value.status]"
        class="wp-m-0"
      >
        {{ VERSION_STATUS_LABEL[board.version.value.status] }}
      </ATag>
    </template>

    <template v-else>
      <ATag color="blue" class="wp-m-0">{{ makerLabel }}</ATag>
      <span class="wp-text-sm wp-font-medium">{{ board.project.value?.name }}</span>
      <ATooltip
        :title="`생성 시점의 '${board.sourceTemplateName.value ?? '알 수 없는 포맷'}'${sourceVersionLabel ? ` ${sourceVersionLabel}` : ''} 발행본에서 복제되었습니다. 이후 템플릿 변경은 전파되지 않습니다.`"
        :get-popup-container="popupContainer"
      >
        <!--
          포맷 이름 옆에 **원본 발행 버전**을 함께 보인다 (`plan.md` §0.6). 어느 발행본에서
          떠온 스냅샷인지가 이 화면에서 유일하게 드러나는 자리다. 서버가 번호를 주지 않으면
          (프로젝트가 원본보다 오래 살아남은 경우) 배지를 생략한다 — `v?` 를 지어내지 않는다.
        -->
        <ATag class="wp-m-0" data-wp-format-tag>
          포맷: {{ board.sourceTemplateName.value ?? '—' }}
          <b v-if="sourceVersionLabel" data-wp-format-version>{{ sourceVersionLabel }}</b>
        </ATag>
      </ATooltip>
    </template>

    <ADivider type="vertical" class="wp-m-0" />

    <div class="wp-flex wp-items-center wp-gap-2 wp-text-xs" style="color: #595959">
      <span>전체 <b>{{ summary.total }}</b></span>
      <span>Done <b>{{ summary.done }}</b></span>
      <AProgress
        :percent="summary.percent"
        size="small"
        style="width: 110px; margin: 0"
        :stroke-color="summary.percent === 100 ? '#17A085' : '#3B82C4'"
      />
      <!--
        The gray-row counter. Unassigned rows are legal and persist, so this is a note
        rather than a warning — but on the template tier they will block 발행, and a user
        who added ten of them should not first learn that from the validation panel.
      -->
      <ATooltip
        v-if="board.unassignedCount.value > 0"
        :title="
          isTemplate
            ? '미배정(회색) 행은 저장은 되지만 발행 검증에서 막힙니다. Phase 셀에서 지정하세요.'
            : '미배정(회색) 행입니다. 프로젝트에서는 이대로 두어도 괜찮습니다.'
        "
        :get-popup-container="popupContainer"
      >
        <span style="color: #8c8c8c">미배정 <b>{{ board.unassignedCount.value }}</b></span>
      </ATooltip>
    </div>

    <div class="wp-ml-auto wp-flex wp-items-center wp-gap-2">
      <span v-if="board.dirty.value" class="wp-text-xs" style="color: #d48806">
        저장되지 않은 변경
      </span>

      <template v-if="canEdit">
        <!--
          자동저장 스위치가 여기 있었다 — 제거됐다 (`plan.md` §0.5.8). 저장은 아래 수동
          버튼뿐이고, 미저장 경고는 그대로 남아 있다.
        -->
        <ATooltip
          title="맨 아래에 미배정(회색) 행을 추가합니다. 원하는 위치로 끌어다 놓고 Phase 를 지정하세요."
          :get-popup-container="popupContainer"
        >
          <AButton size="small" :disabled="board.saving.value" @click="board.appendRow()">
            행 추가
          </AButton>
        </ATooltip>

        <AButton size="small" :loading="board.saving.value" @click="board.save()">
          {{ isTemplate ? '임시저장' : '저장' }}
        </AButton>

        <template v-if="isTemplate">
          <AButton size="small" @click="emit('validate')">검증</AButton>
          <AButton
            size="small"
            type="primary"
            :loading="board.saving.value"
            @click="emit('publish')"
          >
            발행
          </AButton>
          <APopconfirm
            title="이 DRAFT 를 폐기할까요? 되돌릴 수 없습니다."
            ok-text="폐기"
            cancel-text="취소"
            :get-popup-container="popupContainer"
            @confirm="board.discardDraft()"
          >
            <AButton size="small" danger>폐기</AButton>
          </APopconfirm>
        </template>
      </template>

      <template v-else-if="canBranch">
        <ATooltip
          :title="hasDraft ? '이미 작성중인 DRAFT 가 있습니다.' : ''"
          :get-popup-container="popupContainer"
        >
          <span>
            <AButton
              size="small"
              type="primary"
              :disabled="hasDraft"
              :loading="board.saving.value"
              @click="board.createDraft()"
            >
              draft 발행
            </AButton>
          </span>
        </ATooltip>
      </template>

      <!-- XLSX 는 서버(openpyxl)가 만든다 — ag-grid CSV 경로는 제거됐다 (§0.5.7). -->
      <AButton size="small" :loading="props.exporting" @click="emit('export-xlsx')">
        XLSX 내보내기
      </AButton>
    </div>
  </div>
</template>
