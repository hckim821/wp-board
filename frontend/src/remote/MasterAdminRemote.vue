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
 * `MasterAdmin` — 기준 데이터 관리. One of the two exposed components (`plan.md` §0.1,
 * INTEGRATION.md §5).
 *
 * Central and **maker-free**: this is where WP 템플릿 are edited through the full
 * DRAFT → PUBLISHED → ARCHIVED flow, and where the global document master lives. There is
 * deliberately no `makerId` prop — a template belongs to no maker, and accepting one would
 * invite a host to scope templates per maker, which is the scenario `plan.md` §0 corrects.
 *
 * Host contract (INTEGRATION.md §5):
 *  - The antd `ConfigProvider` is confined to this subtree and antd's global reset is
 *    never imported, so the host's own antd/theme is untouched.
 *  - Runtime configuration (`apiBaseUrl`, token, headers) arrives as props or through
 *    `configure()` — never from `import.meta.env`, which would bake dev values into the
 *    federated bundle.
 *  - No `vue-router`: navigation is delegated through the `navigate` prop.
 */
const props = withDefaults(
  defineProps<{
    /** Host permission gate. Withdraws every write action, including `draft 발행`. */
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
    /** Warn on tab close while a draft has unsaved edits. */
    warnOnUnload?: boolean
    /** Height of the container. The host owns layout; this is a convenience. */
    height?: string
  }>(),
  {
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

/**
 * antd popups are portalled here rather than to `document.body`, so they land inside the
 * subtree our (prefixed, preflight-free) styles actually cover.
 */
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
  <!--
    `wp-root` is the anchor for every style rule this package emits. Tailwind runs with
    preflight off and a `wp-` prefix, so nothing here can reach outside this element.
  -->
  <div ref="root" class="wp-root" :style="{ height: props.height }">
    <AConfigProvider :locale="koKR" :get-popup-container="popupContainer">
      <AApp class="wp-h-full">
        <BoardShell
          ref="shell"
          tier="template"
          :maker-id="null"
          :project-id="null"
          :maker-name="null"
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
