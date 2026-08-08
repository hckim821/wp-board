<script setup lang="ts">
import { computed, ref } from 'vue'
import { App as AApp, ConfigProvider as AConfigProvider } from 'ant-design-vue'
import koKR from 'ant-design-vue/es/locale/ko_KR'
import 'dayjs/locale/ko'
import { createHttpApiClient, type WpApiClient } from '../api/client'
import { resolveConfig, type WpRuntimeConfig } from '../runtime/config'
import ProjectsOverviewScreen from '../views/ProjectsOverviewScreen.vue'
import '../styles/tailwind.css'

/**
 * `ProjectsOverview` — 전체 현황, the host's third menu item (`plan.md` §0.5-3).
 *
 * Deliberately **maker-free**: it takes no `makerId` and shows every active project of every
 * maker, because comparing them is the whole point of the screen. It still owns no maker
 * table — names arrive pre-resolved on the payload, or null.
 *
 * It does not mount `BoardShell`. There is no board here, no scope, no master data and
 * nothing editable, so the board store and its Phase/Milestone machinery would be dead
 * weight — and loading ag-grid for a screen with no grid is exactly the kind of cost a host
 * notices. `grid.css` is likewise not imported.
 *
 * Host contract, same as the other two exposes (INTEGRATION.md §5): antd's global reset is
 * never pulled in, the `ConfigProvider` is confined to this subtree, configuration is read
 * at runtime from props, and there is no router dependency — navigation into a project is
 * the `onOpenProject` callback.
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
    /**
     * Host permission gate. Withdraws 프로젝트 추가 · 이름 수정 · 설비사 설정 (`plan.md` §0.6).
     *
     * This screen used to have no `readOnly` at all because it wrote nothing. §0.6 gave it
     * three write paths, so the prop exists now — a host that grants read access to the
     * overview should not thereby grant project creation.
     */
    readOnly?: boolean
    /**
     * Host-owned navigation. Called with the clicked project and the maker it belongs to,
     * so the host can route to its own project screen (typically `ProjectWorkspace` with
     * that `makerId`). Omit it and rows are inert.
     */
    onOpenProject?: ((projectId: number, makerId: number) => void) | null
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
    onOpenProject: null,
    height: '100%',
  },
)

const root = ref<HTMLElement | null>(null)
const screen = ref<InstanceType<typeof ProjectsOverviewScreen> | null>(null)


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

/**
 * One client per mounted instance — never module scope, so two overviews in one host cannot
 * share state (INTEGRATION.md §5).
 */
const api: WpApiClient = props.dataSource ?? createHttpApiClient(resolveConfig(runtimeConfig.value))

defineExpose({
  reload: () => screen.value?.reload(),
  /** Present for symmetry with the other two exposes; nothing here can be dirty. */
  hasUnsavedChanges: () => false,
})
</script>

<template>
  <div ref="root" class="wp-root" :style="{ height: props.height }">
    <AConfigProvider :locale="koKR" :get-popup-container="popupContainer">
      <AApp class="wp-h-full">
        <div class="wp-h-full wp-p-2">
          <ProjectsOverviewScreen
            ref="screen"
            :api="api"
            :read-only="props.readOnly"
            :on-open-project="props.onOpenProject"
          />
        </div>
      </AApp>
    </AConfigProvider>
  </div>
</template>
