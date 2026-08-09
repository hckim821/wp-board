<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Spin as ASpin,
  Switch as ASwitch,
  Tag as ATag,
} from 'ant-design-vue'
import { DownOutlined, RightOutlined } from '@ant-design/icons-vue'
import { describeApiError, type WpApiClient } from '../api/client'
import type { MakerProject, MakerProjectVisibilityPayload, MakerSetting } from '../api/types'

/**
 * 설비사 설정 — 무엇이 전체 현황에 보이는가 (`plan.md` §0.6, §0.6.1).
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
 * ## 화면 형태 — 전체 현황과 같은 카드 (2026-08-09 개편)
 *
 * 이전 판은 antd `Table` 한 장이었다. 설비사 밑에 프로젝트가 딸리면서 그 형태가 무너졌다 —
 * 표의 한 칸 안에 목록을 세로로 쌓게 되고, 설비사가 몇만 늘어도 화면이 세로로 끝없이
 * 길어지며 어디까지가 한 설비사인지 경계가 사라진다. 그래서 `plan.md` §0.6-4 가 전체
 * 현황에 요구한 것과 **같은 언어**를 쓴다: 옅은 배경 위의 흰 카드, 둥근 모서리, 접기/펼치기
 * (기본 펼침), 하위 항목은 들여쓰기. 두 화면이 같은 것(설비사 → 프로젝트)을 보여 주므로
 * 같아 보여야 한다.
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
 * `db/delete_project.py` by hand when a project really has to go (README §5.2). Keeping
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
 * Only the switches that actually moved are sent (§0.6.1 `projects` is a partial list), so the
 * loaded values have to be kept next to the edited ones. Deriving it from `baseline` would mean
 * parsing the fingerprint string back apart, which is what fingerprints are for not being.
 */
const baselineProjects = shallowRef(new Map<number, boolean>())
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

/** Collapsed cards, by maker id. Absent = expanded, so the default is 펼침 (§0.6-4). */
const collapsed = ref<Set<number>>(new Set())

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

const labelOf = (row: MakerSetting) => (row.name?.trim() ? row.name : `설비사 #${row.maker_id}`)

const isCollapsed = (row: MakerSetting) => collapsed.value.has(row.maker_id)

function toggle(row: MakerSetting) {
  const next = new Set(collapsed.value)
  if (next.has(row.maker_id)) next.delete(row.maker_id)
  else next.add(row.maker_id)
  collapsed.value = next
}

/** 사용 중(on) 프로젝트 수 — 카드 헤더의 요약. */
const activeCountOf = (row: MakerSetting) => projectsOf(row).filter((p) => p.is_active).length

defineExpose({ reload: load, hasUnsavedChanges: () => dirty.value })
</script>

<template>
  <div class="wp-flex wp-h-full wp-flex-col">
    <div class="wp-mb-2 wp-flex wp-items-center wp-gap-3">
      <div class="wp-text-base wp-font-bold" style="color: #1f2937">
        Integrated AI 참여 설비사 관리
      </div>
      <span class="wp-text-xs" style="color: #475569">
        전체 현황에 무엇을 보여줄지 정합니다. 끄는 것은 숨기는 것이며, 지우는 것이 아닙니다.
      </span>
      <span style="flex: 1"></span>
      <span
        v-if="dirty && editable"
        class="wp-rounded-full wp-px-2.5 wp-py-0.5 wp-text-xs wp-font-medium"
        style="background: #fef3c7; color: #b45309"
      >
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
      <span v-else class="wp-text-xs" style="color: #94a3b8">읽기 전용 — 편집 권한이 없습니다.</span>
    </div>

    <AAlert v-if="error" type="error" show-icon banner class="wp-mb-2" :message="error" />

    <!--
      페이지는 옅은 배경, 설비사는 그 위의 흰 카드 — 전체 현황과 같은 언어다
      (`plan.md` §0.6-4). 두 화면이 같은 위계(설비사 → 프로젝트)를 보여 주므로.
    -->
    <div
      class="wp-relative wp-min-h-0 wp-flex-1 wp-overflow-auto wp-rounded-xl wp-p-3"
      style="background: #f8fafc"
    >
      <AEmpty
        v-if="!loading && rows.length === 0 && !error"
        class="wp-py-16"
        description="표시할 설비사가 없습니다. 호스트가 설비사 이름 해석기(MakerResolver)를 연결하지 않았고, 아직 프로젝트도 없는 상태입니다. 프로젝트를 만들면 그 설비사가 여기에 나타납니다."
      />

      <section
        v-for="row in rows"
        :key="row.maker_id"
        class="wp-mb-4 wp-rounded-xl wp-p-4"
        data-wp-maker-card
        style="background: #ffffff; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04)"
      >
        <!-- 카드 헤더: 접기/펼치기 · 이름 · 요약 · 전체 현황 표시 스위치 -->
        <div class="wp-flex wp-items-center wp-gap-2">
          <button
            type="button"
            data-wp-maker-toggle
            class="wp-inline-flex wp-cursor-pointer wp-items-center wp-gap-1.5"
            style="background: none; border: none; padding: 0; font: inherit; color: #0f766e"
            :aria-expanded="!isCollapsed(row)"
            @click="toggle(row)"
          >
            <RightOutlined v-if="isCollapsed(row)" style="font-size: 12px" />
            <DownOutlined v-else style="font-size: 12px" />
            <span class="wp-text-sm wp-font-bold">{{ labelOf(row) }}</span>
          </button>

          <ATag v-if="!row.name" color="default">이름 미해석</ATag>

          <span class="wp-text-xs" style="color: #475569">
            프로젝트 {{ projectsOf(row).length }}
            <template v-if="projectsOf(row).length > 0">
              · 사용 {{ activeCountOf(row) }}
            </template>
          </span>

          <span style="flex: 1"></span>

          <!--
            유효값이 어디서 왔는지 — 명시 설정인지 자동 규칙인지 (§0.6-1). 이 구분이 없으면
            "체크하지 않았는데 켜져 있다" 가 고장으로 읽힌다.
          -->
          <ATag
            :color="row.explicit ? 'blue' : 'default'"
            :data-wp-maker-origin="row.explicit ? 'explicit' : 'auto'"
          >
            {{ row.explicit ? '직접 설정' : '자동 (프로젝트 유무)' }}
          </ATag>
          <span class="wp-text-xs wp-font-medium" style="color: #334155">전체 현황 표시</span>
          <ASwitch
            size="small"
            :checked="row.show_in_overview"
            :disabled="!editable"
            :data-wp-maker-show="row.maker_id"
            @change="(v: unknown) => (row.show_in_overview = !!v)"
          />
        </div>

        <!--
          프로젝트는 헤더보다 **들여쓴다** (§0.6-4) — 카드 안에서 하위 항목임이 위계가 아니라
          형태로 드러나야 한다. 이 목록에는 **꺼진 프로젝트도 들어 있다**: 안 그러면 끄는
          순간 다시 켤 화면이 사라진다 (§0.6.1).
        -->
        <template v-if="!isCollapsed(row)">
          <div
            v-if="projectsOf(row).length === 0"
            class="wp-ml-6 wp-mt-3 wp-rounded-xl wp-border wp-border-dashed wp-p-5 wp-text-center wp-text-xs"
            data-wp-maker-empty
            style="border-color: #cbd5e1; color: #64748b; background: #f8fafc"
          >
            아직 프로젝트가 없습니다. 전체 현황에서 추가할 수 있습니다.
          </div>

          <div
            v-for="(project, index) in projectsOf(row)"
            :key="project.id"
            class="wp-ml-6 wp-flex wp-items-center wp-gap-3 wp-rounded-lg wp-px-3 wp-py-2"
            data-wp-project-row
            :class="index > 0 ? 'wp-mt-1 wp-border-t wp-border-solid' : 'wp-mt-3'"
            :style="{
              borderColor: '#f1f5f9',
              background: project.is_active ? 'transparent' : '#f8fafc',
            }"
          >
            <ASwitch
              size="small"
              :checked="project.is_active"
              :disabled="!editable"
              :data-wp-project-active="project.id"
              @change="(v: unknown) => (project.is_active = !!v)"
            />
            <span
              class="wp-truncate wp-text-sm"
              :style="{
                color: project.is_active ? '#0f172a' : '#94a3b8',
                fontWeight: project.is_active ? 500 : 400,
              }"
            >
              {{ project.name }}
            </span>
            <ATag v-if="!project.is_active" color="default">미사용 — 전체 현황에서 숨김</ATag>
          </div>
        </template>
      </section>

      <div
        v-if="loading"
        class="wp-absolute wp-inset-0 wp-flex wp-items-center wp-justify-center"
        style="background: rgba(248, 250, 252, 0.6)"
      >
        <ASpin />
      </div>
    </div>

    <!--
      화면 아래 한 줄 안내. 위쪽 Alert 두 장을 여기로 접었다 — 설명이 화면 절반을 먹으면
      정작 조작할 카드가 아래로 밀린다.
    -->
    <div class="wp-mt-2 wp-flex wp-flex-wrap wp-items-center wp-gap-x-4 wp-gap-y-1 wp-text-xs" style="color: #64748b">
      <span>
        <b style="color: #334155">전체 현황 표시</b> — 끄지 않아도 진행 중인 프로젝트가 있는 설비사는
        자동으로 표시됩니다. 스위치는 그 자동 규칙을 덮어씁니다.
      </span>
      <span>
        <b style="color: #334155">프로젝트 스위치</b> — 끄면 전체 현황에서만 사라집니다. 항목·상태·완료일은
        그대로 남고 다시 켜면 복구됩니다. 데이터베이스에서 실제로 지우려면 관리자가
        <code>db/delete_project.py</code> 를 직접 실행해야 하며, 그 삭제는 되돌릴 수 없습니다.
      </span>
    </div>
  </div>
</template>
