<script setup lang="ts">
import { computed, ref } from 'vue'
import { App as AApp, ConfigProvider as AConfigProvider } from 'ant-design-vue'
import koKR from 'ant-design-vue/es/locale/ko_KR'
import 'dayjs/locale/ko'
import { createHttpApiClient, type WpApiClient } from '../api/client'
import { resolveConfig, type WpRuntimeConfig } from '../runtime/config'
import MakerSettingsScreen from '../views/MakerSettingsScreen.vue'
import '../styles/tailwind.css'

/**
 * `MakerSettings` — Integrated AI 참여 설비사 관리 (`plan.md` §0.6-4).
 *
 * The fourth exposed module. It was a second screen inside `ProjectsOverview`, reachable only
 * by opening the overview and pressing a button there; as its own expose the host can put it
 * on its own menu, permission it separately, and link to it directly — none of which is
 * possible for a screen buried inside another one.
 *
 * **Maker-free in the same sense as the others**: it takes no `makerId` and owns no maker
 * table. What it edits is *our* `wp_maker_settings`, keyed by an id we never dereference; the
 * names come from the host's `MakerResolver`, and an empty list is the normal answer when the
 * host wired none (root `INTEGRATION.md` §2.2).
 *
 * No ag-grid here either — there is no grid on this screen, so the chunk is never loaded.
 */
const props = withDefaults(
  defineProps<{
    apiBaseUrl?: string
    authToken?: string | (() => string | null | Promise<string | null>) | null
    headers?: Record<string, string>
    requestTimeoutMs?: number
    withCredentials?: boolean
    /** Escape hatch: supply a transport instead of the built-in axios client. */
    dataSource?: WpApiClient | null
    /** Host permission gate. Renders the table but withdraws the checkboxes and 저장. */
    readOnly?: boolean
    /** Height of the container. The host owns layout; this is a convenience. */
    height?: string
  }>(),
  {
    apiBaseUrl: undefined,
    authToken: null,
    headers: undefined,
    requestTimeoutMs: undefined,
    withCredentials: undefined,
    dataSource: null,
    readOnly: false,
    height: '100%',
  },
)

const root = ref<HTMLElement | null>(null)
const screen = ref<InstanceType<typeof MakerSettingsScreen> | null>(null)

const popupContainer = () => root.value ?? document.body

const runtimeConfig = computed<Partial<WpRuntimeConfig>>(() => ({
  apiBaseUrl: props.apiBaseUrl,
  headers: props.headers,
  requestTimeoutMs: props.requestTimeoutMs,
  withCredentials: props.withCredentials,
  getAuthToken:
    typeof props.authToken === 'function'
      ? props.authToken
      : props.authToken
        ? () => props.authToken as string
        : null,
}))

/** One client per mounted instance — never module scope (INTEGRATION.md §5). */
const api: WpApiClient = props.dataSource ?? createHttpApiClient(resolveConfig(runtimeConfig.value))

defineExpose({
  reload: () => screen.value?.reload(),
  /** Unsaved checkbox changes are real — wire this into the host's route guard. */
  hasUnsavedChanges: () => screen.value?.hasUnsavedChanges() ?? false,
})
</script>

<template>
  <div ref="root" class="wp-root" :style="{ height: props.height }">
    <AConfigProvider :locale="koKR" :get-popup-container="popupContainer">
      <AApp class="wp-h-full">
        <div class="wp-h-full wp-p-2">
          <MakerSettingsScreen ref="screen" :api="api" :read-only="props.readOnly" />
        </div>
      </AApp>
    </AConfigProvider>
  </div>
</template>
