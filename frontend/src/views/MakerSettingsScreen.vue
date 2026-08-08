<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import {
  Alert as AAlert,
  Button as AButton,
  Checkbox as ACheckbox,
  Spin as ASpin,
  Switch as ASwitch,
  Table as ATable,
  Tag as ATag,
} from 'ant-design-vue'
import { describeApiError, type WpApiClient } from '../api/client'
import type { MakerProject, MakerProjectVisibilityPayload, MakerSetting } from '../api/types'

/**
 * 설비사 설정 — which makers appear on the 전체 현황 (`plan.md` §0.6).
 *
 * Its own federated expose (`./MakerSettings`, `plan.md` §0.6-4). It began as a second
 * screen inside `ProjectsOverview`, reachable only by opening that screen first — which the
 * host could neither place on its own menu nor permission separately. There is no back
 * button here for the same reason: navigation belongs to the host.
 *
 * The row shows the **effective** value and where it came from. That distinction is the
 * whole design of §0.6: with no `wp_maker_settings` row the answer is derived from "does it
 * have active projects", so a maker can be visible today and vanish when its last project is
 * archived. A screen that only showed a checkbox would make that look like a bug.
 *
 * This module still owns no maker table. The names arrive from the host's `MakerResolver`,
 * and an **empty list is the normal answer** when the host wired none (root §2.2) — hence the
 * guidance instead of an error.
 *
 * ## 프로젝트 사용 여부
 *
 * Each maker's projects hang under it with their own on/off switch, writing
 * `wp_projects.is_active`. Off means **hidden from 전체 현황**, nothing more: the rows, their
 * statuses and completion dates stay in the database and come back untouched when it is
 * switched on again.
 *
 * That is why the list this screen renders includes inactive projects while every other read
 * path filters them out. If it did not, switching one off would remove it from the only screen
 * that could switch it back on — a one-way door built out of a toggle.
 *
 * **Nothing here deletes.** The API exposes no hard delete at all; an administrator runs
 * `db/delete_project.py` by hand when a project really has to go (README §관리자 도구). Keeping
 * the destructive path off the screen is the point — a switch and a delete button side by side
 * is one mis-click away from losing execution history.
 */
const props = defineProps<{
  api: WpApiClient
  /** Host permission gate — the whole screen is read-only without it. */
  readOnly?: boolean
}>()

const rows = ref<MakerSetting[]>([])
const baseline = shallowRef('')
/**
 * `project_id → is_active` as the server last reported it.
 *
 * Only the switches that actually moved are sent (§0.6 `projects` is a partial list), so the
 * loaded values have to be kept next to the edited ones. Deriving it from `baseline` would mean
 * parsing the fingerprint string back apart, which is what fingerprints are for not being.
 */
const baselineProjects = shallowRef(new Map<number, boolean>())
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

let live = true

const editable = computed(() => !props.readOnly)

/** `?? []` throughout: a server predating the `projects` field must not blank the screen. */
const projectsOf = (maker: MakerSetting): MakerProject[] => maker.projects ?? []

const fingerprint = (list: readonly MakerSetting[]) =>
  JSON.stringify(
    list.map((m) => [
      m.maker_id,
      m.show_in_overview,
      projectsOf(m).map((p) => [p.id, p.is_active]),
    ]),
  )

const dirty = computed(() => fingerprint(rows.value) !== baseline.value)

/** Deep enough to cover `projects` — a shallow copy would let edits reach the response object. */
const adopt = (makers: readonly MakerSetting[]) => {
  rows.value = makers.map((m) => ({ ...m, projects: projectsOf(m).map((p) => ({ ...p })) }))
  baseline.value = fingerprint(rows.value)
  baselineProjects.value = new Map(
    rows.value.flatMap((m) => projectsOf(m).map((p) => [p.id, p.is_active] as const)),
  )
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const response = await props.api.listMakers()
    if (!live) return
    adopt(response.makers)
  } catch (caught) {
    if (live) error.value = describeApiError(caught, '설비사 목록을 불러오지 못했습니다.')
  } finally {
    if (live) loading.value = false
  }
}

/** Only the switches that moved. Untouched projects are left out, not re-asserted. */
const changedProjects = (): MakerProjectVisibilityPayload[] =>
  rows.value.flatMap((m) =>
    projectsOf(m)
      .filter((p) => baselineProjects.value.get(p.id) !== p.is_active)
      .map((p) => ({ id: p.id, is_active: p.is_active })),
  )

async function save() {
  if (!editable.value) return
  saving.value = true
  error.value = null
  try {
    const response = await props.api.saveMakerSettings(
      rows.value.map((m) => ({ maker_id: m.maker_id, show_in_overview: m.show_in_overview })),
      changedProjects(),
    )
    if (!live) return
    adopt(response.makers)
  } catch (caught) {
    if (live) error.value = describeApiError(caught, '저장에 실패했습니다.')
  } finally {
    if (live) saving.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  live = false
})

const labelOf = (row: MakerSetting) =>
  row.name?.trim() ? row.name : `설비사 #${row.maker_id}`

const columns = [
  { title: '설비사', key: 'name', width: 220 },
  { title: '프로젝트 사용 여부', key: 'projects' },
  { title: '전체 현황 표시', key: 'show', width: 190 },
]

defineExpose({ reload: load, hasUnsavedChanges: () => dirty.value })
</script>

<template>
  <div class="wp-flex wp-h-full wp-flex-col">
    <div class="wp-mb-2 wp-flex wp-items-center wp-gap-2">
      <div class="wp-text-base wp-font-bold" style="color: #1f2937">
        Integrated AI 참여 설비사 관리
      </div>
      <span style="flex: 1"></span>
      <span v-if="dirty && editable" class="wp-text-xs" style="color: #d97706">
        저장하지 않은 변경이 있습니다
      </span>
      <AButton
        v-if="editable"
        type="primary"
        size="small"
        :loading="saving"
        :disabled="!dirty"
        @click="save"
      >
        저장
      </AButton>
    </div>

    <AAlert v-if="error" type="error" show-icon banner class="wp-mb-2" :message="error" />

    <AAlert
      type="info"
      show-icon
      class="wp-mb-2"
      message="체크하지 않아도 진행 중인 프로젝트가 있는 설비사는 자동으로 표시됩니다. 체크는 그 자동 규칙을 덮어씁니다 — 켜면 프로젝트가 없어도 표시되고, 끄면 있어도 숨겨집니다."
    />

    <AAlert
      type="warning"
      show-icon
      class="wp-mb-2"
      message="프로젝트 스위치를 끄면 전체 현황에서만 사라집니다. 항목·상태·완료일은 그대로 남아 있고 다시 켜면 복구됩니다. 데이터베이스에서 실제로 지우려면 관리자가 db/delete_project.py 를 직접 실행해야 하며, 그 삭제는 되돌릴 수 없습니다."
    />

    <ASpin :spinning="loading">
      <AAlert
        v-if="!loading && rows.length === 0 && !error"
        type="warning"
        show-icon
        message="표시할 설비사가 없습니다. 호스트가 설비사 이름 해석기(MakerResolver)를 연결하지 않았고, 아직 프로젝트도 없는 상태입니다. 프로젝트를 만들면 그 설비사가 여기에 나타납니다."
      />
      <ATable
        v-else
        :columns="columns"
        :data-source="rows"
        :pagination="false"
        row-key="maker_id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <span class="wp-text-sm wp-font-medium" style="color: #0f172a">
              {{ labelOf(record as MakerSetting) }}
            </span>
            <ATag v-if="!(record as MakerSetting).name" class="wp-ml-2" color="default">
              이름 미해석
            </ATag>
          </template>
          <!--
            프로젝트별 on/off. 끄면 전체 현황에서만 빠지고 DB 행은 그대로 남는다 —
            그래서 이 목록에는 **꺼진 프로젝트도 들어 있다**. 안 그러면 끄는 순간
            다시 켤 화면이 없어진다.
          -->
          <template v-else-if="column.key === 'projects'">
            <div
              v-if="projectsOf(record as MakerSetting).length === 0"
              class="wp-text-xs"
              style="color: #94a3b8"
            >
              프로젝트 없음
            </div>
            <div v-else class="wp-flex wp-flex-col wp-gap-1">
              <div
                v-for="project in projectsOf(record as MakerSetting)"
                :key="project.id"
                class="wp-flex wp-items-center wp-gap-2"
              >
                <ASwitch
                  size="small"
                  :checked="project.is_active"
                  :disabled="!editable"
                  :data-wp-project-active="project.id"
                  @change="(v: unknown) => (project.is_active = !!v)"
                />
                <span
                  class="wp-text-xs"
                  :style="{ color: project.is_active ? '#0f172a' : '#94a3b8' }"
                >
                  {{ project.name }}
                </span>
                <ATag v-if="!project.is_active" color="default">미사용</ATag>
              </div>
            </div>
          </template>
          <template v-else-if="column.key === 'show'">
            <div class="wp-flex wp-items-center wp-gap-2">
              <ACheckbox
                :checked="(record as MakerSetting).show_in_overview"
                :disabled="!editable"
                :data-wp-maker-show="(record as MakerSetting).maker_id"
                @change="(e: { target: { checked: boolean } }) => ((record as MakerSetting).show_in_overview = e.target.checked)"
              />
              <!-- 유효값이 어디서 왔는지 — 명시 설정인지 자동 규칙인지 (§0.6). -->
              <ATag
                :color="(record as MakerSetting).explicit ? 'blue' : 'default'"
                :data-wp-maker-origin="(record as MakerSetting).explicit ? 'explicit' : 'auto'"
              >
                {{ (record as MakerSetting).explicit ? '직접 설정' : '자동 (프로젝트 유무)' }}
              </ATag>
            </div>
          </template>
        </template>
      </ATable>
    </ASpin>
  </div>
</template>
