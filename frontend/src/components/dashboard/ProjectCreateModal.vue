<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  Alert as AAlert,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Modal as AModal,
  Select as ASelect,
} from 'ant-design-vue'
import { describeApiError, type WpApiClient } from '../../api/client'
import type { WpTemplate, WpVersion } from '../../api/types'

/**
 * 프로젝트 추가, from a 설비사 section of the 전체 현황 (`plan.md` §0.6).
 *
 * Deliberately **not** shared with `views/ProjectList.vue`'s dialog. That one lives inside
 * `BoardShell` and drives the board store — it selects the created project and opens it. This
 * one has no store, no board and no context at all: it takes an api client and a maker id as
 * props, creates, and tells its parent to reload. Making one component serve both would have
 * meant threading the board store into a screen that deliberately does not have one.
 *
 * Only **published** formats are offered. A project is a snapshot, and a snapshot of a draft
 * is a snapshot of nothing anyone agreed to — the server answers 422 either way, but a
 * dropdown that lists an option the server rejects is a worse way to find out.
 */
const props = defineProps<{
  api: WpApiClient
  makerId: number
  makerLabel: string
}>()

const emit = defineEmits<{ (e: 'created'): void; (e: 'cancel'): void }>()

const name = ref('')
const templateId = ref<number | null>(null)
const versionId = ref<number | null>(null)
const templates = ref<WpTemplate[]>([])
const publishedVersions = ref<Map<number, WpVersion[]>>(new Map())
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

let live = true

/**
 * Which templates have a published version, asked of `listVersions` one call per template.
 *
 * The server has no `published_version_id` on the template row — the client used to invent
 * one, which silently filtered every format out of the create dialog. Formats are a short
 * curated set and the calls go out in parallel.
 */
async function load() {
  loading.value = true
  error.value = null
  try {
    const list = await props.api.listTemplates()
    const byTemplate = new Map<number, WpVersion[]>()
    await Promise.all(
      list.map(async (template) => {
        const versions = await props.api.listVersions(template.id)
        const published = versions
          .filter((v) => v.status === 'PUBLISHED' || v.status === 'ARCHIVED')
          .sort((a, b) => b.version_number - a.version_number)
        if (published.length > 0) byTemplate.set(template.id, published)
      }),
    )
    if (!live) return
    templates.value = list
    publishedVersions.value = byTemplate
    templateId.value = publishable.value[0]?.id ?? null
  } catch (caught) {
    if (live) error.value = describeApiError(caught, '포맷 목록을 불러오지 못했습니다.')
  } finally {
    if (live) loading.value = false
  }
}

const publishable = computed(() =>
  templates.value.filter((t) => t.is_active && publishedVersions.value.has(t.id)),
)

const templateOptions = computed(() =>
  publishable.value.map((t) => ({ value: t.id, label: `${t.name} (${t.code})` })),
)

const versionOptions = computed(() => {
  if (templateId.value == null) return []
  return (publishedVersions.value.get(templateId.value) ?? []).map((v) => ({
    value: v.id,
    label:
      `v${v.version_number} — ${v.published_at?.slice(0, 10) ?? ''}` +
      (v.status === 'ARCHIVED' ? ' (이전 발행본)' : ' (현재 발행본)'),
  }))
})

watch(templateId, () => {
  versionId.value = versionOptions.value[0]?.value ?? null
})

async function submit() {
  const trimmed = name.value.trim()
  if (!trimmed) {
    error.value = '프로젝트 이름을 입력하세요.'
    return
  }
  if (templateId.value == null) {
    error.value = '기준 포맷을 선택하세요.'
    return
  }
  saving.value = true
  error.value = null
  try {
    await props.api.createProject({
      maker_id: props.makerId,
      name: trimmed,
      template_id: templateId.value,
      template_version_id: versionId.value,
    })
    emit('created')
  } catch (caught) {
    error.value = describeApiError(caught, '프로젝트 생성에 실패했습니다.')
  } finally {
    saving.value = false
  }
}

void load()
onBeforeUnmount(() => {
  live = false
})
</script>

<template>
  <AModal
    :open="true"
    :title="`프로젝트 추가 — ${props.makerLabel}`"
    ok-text="생성"
    cancel-text="취소"
    :confirm-loading="saving"
    @ok="submit"
    @cancel="emit('cancel')"
  >
    <AAlert v-if="error" type="error" show-icon class="wp-mb-2" :message="error" />
    <AAlert
      v-else-if="!loading && publishable.length === 0"
      type="warning"
      show-icon
      class="wp-mb-2"
      message="발행된 기준 포맷이 없습니다. ‘기준 데이터 관리’에서 템플릿을 발행한 뒤 다시 시도하세요."
    />

    <AForm layout="vertical">
      <AFormItem label="프로젝트 이름" required>
        <AInput v-model:value="name" placeholder="예) 2026 AI 과제 2차" @press-enter="submit" />
      </AFormItem>
      <AFormItem label="기준 포맷" required>
        <ASelect
          :value="templateId ?? undefined"
          :options="templateOptions"
          :loading="loading"
          style="width: 100%"
          @change="(value: unknown) => (templateId = Number(value))"
        />
      </AFormItem>
      <AFormItem label="발행 버전" required>
        <ASelect
          :value="versionId ?? undefined"
          :options="versionOptions"
          style="width: 100%"
          @change="(value: unknown) => (versionId = Number(value))"
        />
      </AFormItem>
    </AForm>
    <p class="wp-text-xs" style="color: #64748b">
      선택한 포맷의 <b>선택한 발행 버전</b>에서 항목·Phase·Milestone·Owner 가 통째로 복사됩니다.
      이후 포맷이 다시 발행되어도 이 프로젝트는 바뀌지 않습니다.
    </p>
  </AModal>
</template>
