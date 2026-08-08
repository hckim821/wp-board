/**
 * Hand-written type declarations for the `wpBoard` federation remote.
 *
 * The Module Federation dts plugin shells out to plain `tsc`, which cannot read `.vue`
 * SFCs, so automatic generation is switched off (`vite.config.ts`) and this file is the
 * contract instead. Copy it into the host, or reference it from the host's `tsconfig`:
 *
 *   "include": ["...", "node_modules/@dsep/wp-board-remote/types/wpBoard.d.ts"]
 *
 * There are **four** exposed modules (`plan.md` §0.1, §0.5-3, §0.6-4). They are different
 * screens on the host's menu, not views of one thing:
 *
 *   wpBoard/MasterAdmin        기준 데이터 관리 — central, no maker. WP 템플릿 editing with
 *                              the DRAFT → PUBLISHED → ARCHIVED flow. **The global document
 *                              master is gone** (`plan.md` §0.5.10) — documents are owned by
 *                              the format and managed from the board's 관련 문서 cell.
 *   wpBoard/ProjectWorkspace   설비사 프로젝트 — `makerId` required. Project list, create
 *                              from 전체 현황 only (`projectId` required), then four tabs:
 *                              대시보드 (default) · Work Package · 문서 기준정보 · Owner.
 *                              No version UI at all.
 *   wpBoard/ProjectsOverview   전체 현황 / 프로젝트 허브 — **maker-free**: collapsible 설비사
 *                              sections, a mini dashboard per project, inline rename and
 *                              프로젝트 추가. Takes no `makerId`; opening a project is the
 *                              `onOpenProject` callback.
 *   wpBoard/MakerSettings      Integrated AI 참여 설비사 관리 — **maker-free**: which 설비사
 *                              appear on the 전체 현황. Owns no maker table; edits our own
 *                              `wp_maker_settings` and reads names through the host's
 *                              `MakerResolver`.
 */

declare module 'wpBoard/MasterAdmin' {
  import type { DefineComponent } from 'vue'

  export interface WpRuntimeConfig {
    /** e.g. `https://intranet.example.com/wp`; `/api/v1/...` is appended. */
    apiBaseUrl: string
    headers: Record<string, string>
    getAuthToken: (() => string | null | Promise<string | null>) | null
    requestTimeoutMs: number
    withCredentials: boolean
  }

  /** Host-level defaults. Per-instance props take precedence over anything set here. */
  export function configure(config: Partial<WpRuntimeConfig>): void
  export function resetConfiguration(): void

  export interface MasterAdminProps {
    /**
     * Host permission gate. Withdraws every write action, including `draft 발행`.
     *
     * There is deliberately **no `makerId`**: a template belongs to no maker. Accepting one
     * would invite per-maker templates, which is the scenario `plan.md` §0 corrects.
     */
    readOnly?: boolean
    apiBaseUrl?: string
    authToken?: string | (() => string | null | Promise<string | null>) | null
    headers?: Record<string, string>
    requestTimeoutMs?: number
    withCredentials?: boolean
    /** Supply your own transport instead of the built-in axios client. */
    dataSource?: unknown
    /** Host-owned navigation. This package never imports `vue-router`. */
    navigate?: ((target: string, params?: Record<string, unknown>) => void) | null
    /** Warn on tab close while a draft has unsaved edits. Default `true`. */
    warnOnUnload?: boolean
    /** Container height. Default `'100%'`. */
    height?: string
  }

  /**
   * Exposed instance methods — use these to guard host navigation rather than reaching
   * into the component. Applies to **both** exposed modules.
   */
  export interface WpBoardInstance {
    hasUnsavedChanges(): boolean
    save(): Promise<boolean | undefined>
    reload(): Promise<void>
  }

  const MasterAdmin: DefineComponent<
    MasterAdminProps,
    WpBoardInstance,
    unknown,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    { ready: () => void; 'dirty-change': (dirty: boolean) => void }
  >

  export default MasterAdmin
  export { MasterAdmin }
}

declare module 'wpBoard/ProjectWorkspace' {
  import type { DefineComponent } from 'vue'
  import type { WpBoardInstance, WpRuntimeConfig } from 'wpBoard/MasterAdmin'

  export type { WpRuntimeConfig, WpBoardInstance }
  export function configure(config: Partial<WpRuntimeConfig>): void
  export function resetConfiguration(): void

  export interface ProjectWorkspaceProps {
    /**
     * Host maker PK. **Required.** This module owns no maker table, no maker list API and
     * no maker picker — choosing a maker is the host's screen.
     */
    makerId: number | string
    /**
     * Which project to open (`plan.md` §0.6-4). **Required**, though it may be `null`.
     *
     * There is no project list inside this module any more — `ProjectsOverview`'s
     * `onOpenProject(projectId, makerId)` is the only entry point and hands both ids over.
     * Passing `null` renders "전체 현황에서 프로젝트를 선택하세요" rather than picking a
     * project: guessing "the first one" would silently disagree with the host about what the
     * user asked for.
     */
    projectId: number | null
    /** Display only; falls back to `설비사 #<id>`. */
    makerName?: string | null
    /** Host permission gate. Withdraws every write action. */
    readOnly?: boolean
    apiBaseUrl?: string
    authToken?: string | (() => string | null | Promise<string | null>) | null
    headers?: Record<string, string>
    requestTimeoutMs?: number
    withCredentials?: boolean
    /** Supply your own transport instead of the built-in axios client. */
    dataSource?: unknown
    /** Host-owned navigation. This package never imports `vue-router`. */
    navigate?: ((target: string, params?: Record<string, unknown>) => void) | null
    /** Warn on tab close while the board has unsaved edits. Default `true`. */
    warnOnUnload?: boolean
    /** Container height. Default `'100%'`. */
    height?: string
  }

  const ProjectWorkspace: DefineComponent<
    ProjectWorkspaceProps,
    WpBoardInstance,
    unknown,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    { ready: () => void; 'dirty-change': (dirty: boolean) => void }
  >

  export default ProjectWorkspace
  export { ProjectWorkspace }
}

declare module 'wpBoard/ProjectsOverview' {
  import type { DefineComponent } from 'vue'
  import type { WpRuntimeConfig } from 'wpBoard/MasterAdmin'

  export type { WpRuntimeConfig }
  export function configure(config: Partial<WpRuntimeConfig>): void
  export function resetConfiguration(): void

  export interface ProjectsOverviewProps {
    /**
     * There is deliberately **no `makerId`**: this screen spans every maker by design.
     *
     * `readOnly` **does** exist as of `plan.md` §0.6 — the screen gained three write paths
     * (프로젝트 추가 · 이름 수정 · 설비사 설정), and a host granting read access to the
     * overview should not thereby grant project creation.
     */
    readOnly?: boolean
    apiBaseUrl?: string
    authToken?: string | (() => string | null | Promise<string | null>) | null
    headers?: Record<string, string>
    requestTimeoutMs?: number
    withCredentials?: boolean
    /** Supply your own transport instead of the built-in axios client. */
    dataSource?: unknown
    /**
     * Host-owned navigation into one project — `(projectId, makerId)`. Typically routes to
     * the host's own screen that mounts `ProjectWorkspace` with that `makerId`.
     *
     * Fired by the row's **[이동] button** in the last column — not the name, not the row.
     * The row is mostly minimap cells the user hovers to read and a name that is itself the
     * rename trigger, so a click on either must not navigate.
     *
     * **Omit it and no 이동 button is rendered at all.** This package imports no router and
     * will not invent a destination.
     */
    onOpenProject?: ((projectId: number, makerId: number) => void) | null
    /** Container height. Default `'100%'`. */
    height?: string
  }

  export interface ProjectsOverviewInstance {
    reload(): Promise<void> | void
    /** Always `false` — nothing here is editable. Present so all three exposes match. */
    hasUnsavedChanges(): boolean
  }

  const ProjectsOverview: DefineComponent<
    ProjectsOverviewProps,
    ProjectsOverviewInstance,
    unknown,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>
  >

  export default ProjectsOverview
  export { ProjectsOverview }
}

declare module 'wpBoard/MakerSettings' {
  import type { DefineComponent } from 'vue'
  import type { WpBoardInstance, WpRuntimeConfig } from 'wpBoard/MasterAdmin'

  export type { WpRuntimeConfig }
  export function configure(config: Partial<WpRuntimeConfig>): void
  export function resetConfiguration(): void

  export interface MakerSettingsProps {
    /**
     * There is deliberately **no `makerId`**: this screen is the list of every maker.
     *
     * It owns no maker table either — the names arrive through the host's `MakerResolver`
     * and an empty list is the normal answer when none is wired.
     */
    readOnly?: boolean
    apiBaseUrl?: string
    authToken?: string | (() => string | null | Promise<string | null>) | null
    headers?: Record<string, string>
    requestTimeoutMs?: number
    withCredentials?: boolean
    /** Supply your own transport instead of the built-in axios client. */
    dataSource?: unknown
    /** Container height. Default `'100%'`. */
    height?: string
  }

  /**
   * `save()` is absent on purpose — this screen saves from its own 저장 button. Guard host
   * navigation with `hasUnsavedChanges()`, which reports pending checkbox edits.
   */
  const MakerSettings: DefineComponent<
    MakerSettingsProps,
    Pick<WpBoardInstance, 'hasUnsavedChanges' | 'reload'>,
    unknown,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>,
    Record<string, never>
  >

  export default MakerSettings
  export { MakerSettings }
}
