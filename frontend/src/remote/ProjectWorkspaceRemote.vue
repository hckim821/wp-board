<script setup lang="ts">
import { computed, ref } from 'vue'
import { App as AApp, ConfigProvider as AConfigProvider } from 'ant-design-vue'
import koKR from 'ant-design-vue/es/locale/ko_KR'
import 'dayjs/locale/ko'
import type { WpApiClient } from '../api/client'
import type { WpRuntimeConfig } from '../runtime/config'
import BoardShell from './BoardShell.vue'
import '../styles/tailwind.css'
import '../styles/grid.css'

/**
 * `ProjectWorkspace` — 설비사 프로젝트. The other exposed component (`plan.md` §0.1,
 * INTEGRATION.md §5).
 *
 * A project list, the create-from-published-format dialog, and then the board itself with
 * **no version UI at all** — no draft, no publish, no discard, no history. Creation is the
 * commit; everything after it saves directly. Status and 완료일 are the point of this
 * screen.
 *
 * Host contract (INTEGRATION.md §5):
 *  - `makerId` is required and opaque; this module has no maker list and no maker API.
 *    Choosing a maker is the host's screen.
 *  - The antd `ConfigProvider` is confined to this subtree and antd's global reset is
 *    never imported, so the host's own antd/theme is untouched.
 *  - Runtime configuration arrives as props or through `configure()`, never from
 *    `import.meta.env`.
 *  - No `vue-router`: navigation is delegated through the `navigate` prop.
 */
const props = withDefaults(
  defineProps<{
    /** Host maker PK. Opaque — only ever passed through to the API. */
    makerId: number | string
    /**
     * Which project to open (`plan.md` §0.6-4). **Required**, though it may be `null`.
     *
     * There is no project list inside this module any more — 전체 현황's `onOpenProject` is
     * the only entry point, and it hands both ids over. Passing `null` renders an empty
     * state rather than picking a project on the user's behalf: guessing "the first one"
     * would silently disagree with the host about what was asked for.
     */
    projectId: number | null
    /** Display only. Omit it and the header falls back to `설비사 #<id>`. */
    makerName?: string | null
    /** Host permission gate. Withdraws every write action. */
    readOnly?: boolean
    apiBaseUrl?: string
    authToken?: string | (() => string | null | Promise<string | null>) | null
    headers?: Record<string, string>
    requestTimeoutMs?: number
    withCredentials?: boolean
    /** Escape hatch: supply a transport instead of the built-in axios client. */
    dataSource?: WpApiClient | null
    /** Called for host-owned navigation. Nothing in this package routes on its own. */
    navigate?: ((target: string, params?: Record<string, unknown>) => void) | null
    /** Warn on tab close while the board has unsaved edits. */
    warnOnUnload?: boolean
    /** Height of the container. The host owns layout; this is a convenience. */
    height?: string
  }>(),
  {
    makerName: null,
    readOnly: false,
    apiBaseUrl: undefined,
    authToken: null,
    headers: undefined,
    requestTimeoutMs: undefined,
    withCredentials: undefined,
    dataSource: null,
    navigate: null,
    warnOnUnload: true,
    height: '100%',
  },
)

const emit = defineEmits<{ (e: 'ready'): void; (e: 'dirty-change', dirty: boolean): void }>()

const root = ref<HTMLElement | null>(null)
const shell = ref<InstanceType<typeof BoardShell> | null>(null)

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

defineExpose({
  /** Ask before routing away — the host owns the router, so it owns the guard. */
  hasUnsavedChanges: () => shell.value?.hasUnsavedChanges() ?? false,
  save: () => shell.value?.save(),
  reload: () => shell.value?.reload(),
})
</script>

<template>
  <div ref="root" class="wp-root" :style="{ height: props.height }">
    <AConfigProvider :locale="koKR" :get-popup-container="popupContainer">
      <AApp class="wp-h-full">
        <BoardShell
          ref="shell"
          tier="project"
          :maker-id="props.makerId"
          :project-id="props.projectId"
          :maker-name="props.makerName"
          :read-only="props.readOnly"
          :warn-on-unload="props.warnOnUnload"
          :data-source="props.dataSource"
          :runtime-config="runtimeConfig"
          :navigate="props.navigate"
          :popup-container="popupContainer"
          @ready="emit('ready')"
          @dirty-change="(value: boolean) => emit('dirty-change', value)"
        />
      </AApp>
    </AConfigProvider>
  </div>
</template>
