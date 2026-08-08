import axios, { type AxiosInstance } from 'axios'
import type { WpRuntimeConfig } from '../runtime/config'
import type {
  BoardApplyResponse,
  BoardScope,
  CreateFromRowPayload,
  ItemSavePayload,
  ItemsResponse,
  MakerProjectVisibilityPayload,
  MakerSettingPayload,
  MakersResponse,
  MasterScope,
  MembershipPayload,
  MilestonesApplyPayload,
  PhasesApplyPayload,
  ProjectCreatePayload,
  ProjectDetail,
  ProjectDocumentsApplyPayload,
  ProjectDocumentsResponse,
  TemplateDocumentsApplyPayload,
  TemplateDocumentsResponse,
  ProjectLinkSavePayload,
  ProjectLinksResponse,
  ProjectsOverviewResponse,
  PublishResult,
  ReorderRequest,
  ValidationResult,
  VersionDetail,
  WpMilestone,
  WpOwner,
  WpPhase,
  TemplateDocument,
  WpItem,
  WpProject,
  WpTemplate,
  WpVersion,
} from './types'

/**
 * Everything this module needs from a backend.
 *
 * Declared as an interface so the dev harness can hand in an in-memory implementation
 * (`src/mock`) and a host can hand in its own adapter without this package ever caring
 * which one it got.
 *
 * Note what is *absent*: there is no maker list or maker lookup endpoint. Makers belong
 * to the host (INTEGRATION.md §2.4); this module only ever receives a `makerId`, and only
 * the project tier has any use for one.
 *
 * The shape follows `plan.md` §0's two tiers. Template-only operations (versions,
 * publishing) and project-only operations (create from a template) are named separately;
 * everything the two tiers share — every row operation, every master-data operation —
 * takes a {@link BoardScope} instead of a bare id, so there is exactly one implementation
 * of the grid's behaviour rather than two that can drift.
 */
export interface WpApiClient {
  // ───────────────────────────────────── 기준 데이터 (중앙, maker 무관)

  listTemplates(): Promise<WpTemplate[]>
  createTemplate(body: Partial<WpTemplate>): Promise<WpTemplate>
  updateTemplate(id: number, body: Partial<WpTemplate>): Promise<WpTemplate>
  listVersions(templateId: number): Promise<WpVersion[]>
  getVersion(versionId: number): Promise<VersionDetail>

  createDraft(templateId: number): Promise<WpVersion>
  discardDraft(versionId: number): Promise<void>
  /** 임시저장. Answers with the version too, so `updated_at` stays fresh. */
  saveVersionItems(versionId: number, items: ItemSavePayload[]): Promise<VersionDetail>
  validate(versionId: number): Promise<ValidationResult>
  /**
   * 발행. Resolves with `valid: false` and the §2.5 issue list when the server rejects
   * it — the transport-level 422 is unwrapped here so callers see one shape either way.
   */
  publish(versionId: number): Promise<PublishResult>

  // ───────────────────────────────────────────── 프로젝트 (설비사별)

  listProjects(makerId: number | string): Promise<WpProject[]>
  /**
   * Deep-copies the chosen published template version. Creation is the only commit.
   *
   * Answers with `{project, items}` — the whole board, not just the new row. That is worth
   * typing accurately rather than unwrapping to the project alone: the caller opens the
   * board next, and the rows are already here. `check:live` caught this the hard way; the
   * client had it as a bare `WpProject`, so `created.id` was `undefined` and the very next
   * call went to `/projects/undefined`.
   */
  createProject(body: ProjectCreatePayload): Promise<ProjectDetail>
  getProject(projectId: number): Promise<ProjectDetail>
  /**
   * 전체 현황 — every **active** project of every maker, in one read (`plan.md` §0.5-3).
   *
   * Maker-free by design: it takes no `makerId` and is the one call in this module that
   * deliberately crosses makers, because the screen exists to compare them. Names arrive
   * pre-resolved (or null) — there is still no maker endpoint here.
   */
  getProjectsOverview(): Promise<ProjectsOverviewResponse>

  /**
   * 이 프로젝트의 문서 사용 여부·링크·작성 상태 (`plan.md` §0.5-4).
   *
   * Answers with **every active global document**, LEFT JOINed — a project that has never
   * saved anything still gets the full list with defaults, so the screen never has to
   * synthesise rows the server did not send.
   */
  /** 프로젝트명 수정 (`plan.md` §0.6). 빈 이름은 422. */
  renameProject(projectId: number, name: string): Promise<WpProject>

  /**
   * 설비사 목록 + 전체 현황 표시 설정 (`plan.md` §0.6).
   *
   * Still no maker *table* here: the names come from the host's own `MakerResolver`, and an
   * empty list is the normal answer when the host wired none. The settings themselves are
   * ours (`wp_maker_settings`), keyed by an id we never dereference.
   */
  listMakers(): Promise<MakersResponse>
  /**
   * One call, one transaction, one 저장 button — maker checkboxes **and** the per-project
   * on/off switches nested under them.
   *
   * They are split into two arrays rather than nested because they answer to different
   * tables (`wp_maker_settings` vs `wp_projects.is_active`) and different rules: an unknown
   * `maker_id` is accepted (makers are the host's, and no resolver is a normal state) while
   * an unknown project id is a 422. Sending them together is what keeps a half-applied
   * screen from existing.
   *
   * `projects` omitted means "leave projects alone" — **not** "turn them all off".
   */
  saveMakerSettings(
    settings: MakerSettingPayload[],
    projects?: MakerProjectVisibilityPayload[],
  ): Promise<MakersResponse>

  /**
   * 보드 XLSX (`plan.md` §0.5.7) — CSV 내보내기를 대체한다.
   *
   * `itemsBase(scope)` 아래에 붙으므로 템플릿은 `/versions/{vid}/board.xlsx`, 프로젝트는
   * `/projects/{pid}/board.xlsx` 가 된다. 행이 사는 곳과 같은 자리이며, 그게 맞다 — 내보내는
   * 것이 바로 그 행들이다.
   *
   * 생성은 백엔드 openpyxl 이다. ag-grid Community 의 CSV 내보내기로는 원본 엑셀 양식(헤더
   * 스타일·Phase 색 밴딩·freeze·Doc Status 시트)을 낼 수 없고, §0.5.7 은 내보낸 파일이
   * `parse_workbook` 으로 **다시 읽혀야** 한다고까지 요구한다 — CSV 로는 성립하지 않는 계약이다.
   */
  exportBoardXlsx(scope: BoardScope): Promise<Blob>

  /**
   * 대시보드 PPTX 한 장 (`plan.md` §0.5.6).
   *
   * Generated **server-side** by python-pptx, matching the openpyxl precedent in CLAUDE.md:
   * exports are the backend's job. This client only carries the bytes, which is also why it
   * goes through the configured transport rather than a bare `window.open` — the download has
   * to inherit the same auth headers as every other call, and a link element cannot.
   *
   * A read operation, so it stays available under `readOnly`.
   */
  exportDashboardPptx(projectId: number): Promise<Blob>

  /**
   * 문서 목록 (`plan.md` §0.5.10). 셀 팝업과 문서 등록 탭이 함께 쓴다.
   *
   * `itemsBase(scope)` 아래라 템플릿은 `/versions/{vid}/documents`, 프로젝트는
   * `/projects/{pid}/documents` 가 된다 — 문서는 이제 스코프 소유이고, 템플릿 쪽은 버전이
   * 아니라 템플릿에 속하지만 **행 링크를 함께 재계산**하므로 행과 같은 base 를 쓴다 (§0.4 의
   * `phases/apply` 와 같은 이유).
   */
  listDocuments(scope: BoardScope): Promise<TemplateDocumentsResponse | ProjectDocumentsResponse>

  /** 템플릿 문서 apply — `phases/apply` 동형. 원자적이고 집합이 맞아야 한다 (422). */
  applyTemplateDocuments(
    scope: BoardScope,
    payload: TemplateDocumentsApplyPayload,
  ): Promise<DocumentsApplyResponse>

  /** 주요 링크 (`plan.md` §0.5.5). `sort_order` 순. */
  listProjectLinks(projectId: number): Promise<ProjectLinksResponse>
  /**
   * Whole-list replace: array order becomes `sort_order`, and an existing id left out of the
   * payload is **deleted**. 422 on a blank description or a non-http(s) URL.
   */
  saveProjectLinks(
    projectId: number,
    links: ProjectLinkSavePayload[],
  ): Promise<ProjectLinksResponse>

  listProjectDocuments(projectId: number): Promise<ProjectDocumentsResponse>
  /**
   * 프로젝트 문서 전량 교체 (`plan.md` §0.5.10). 배열 순서 = `sort_order`.
   *
   * 셀 팝업의 관리부와 문서 등록 탭이 **같은 경로**를 쓴다 — 한쪽에서 추가한 문서가 다른
   * 쪽에서 보이지 않으면 두 화면이 다른 목록을 말하게 된다.
   */
  saveProjectDocuments(
    projectId: number,
    payload: ProjectDocumentsApplyPayload,
  ): Promise<ProjectDocumentsResponse>
  /** Direct save — no validation, no publish step (`plan.md` §0.1). */
  saveProjectItems(projectId: number, items: ItemSavePayload[]): Promise<ProjectDetail>
  deleteProject(projectId: number): Promise<void>

  // ─────────────────────────────── 행 조작 — 두 계층 공통, scope 로 구분

  /**
   * Appends an **unassigned (gray) row** at the end (`plan.md` §0.2).
   *
   * Also the only entry point for a version with no rows at all, since `insert-below`
   * needs an anchor.
   */
  appendRow(scope: BoardScope): Promise<ItemsResponse>
  /**
   * Inserts an **unassigned (gray) row** directly below `itemId`.
   *
   * It deliberately inherits nothing. Inheriting trapped every new row inside an existing
   * block, and with drag confined to blocks that left no way at all to open a new
   * Phase/Milestone between two existing ones (`plan.md` §0.2).
   */
  insertBelow(scope: BoardScope, itemId: number): Promise<ItemsResponse>
  deleteItem(scope: BoardScope, itemId: number): Promise<ItemsResponse>

  /**
   * Position only. Every row keeps its own phase/milestone — see {@link ReorderRequest}
   * for why membership and the moved id are neither sent nor accepted.
   */
  reorder(scope: BoardScope, itemIds: number[]): Promise<ItemsResponse>

  /** §2.3 cell edit. The server relocates the row and validates contiguity. */
  setMembership(
    scope: BoardScope,
    itemId: number,
    payload: MembershipPayload,
  ): Promise<ItemsResponse>

  /**
   * §2.3 creation. Atomic: create + assign + renumber in one transaction, so a failure
   * cannot leave an orphaned Phase behind. 422 when the server's `can_create_phase` says
   * the result would not be contiguous.
   *
   * On the project tier this creates a **project-local** phase; the central template is
   * untouched (`plan.md` §0.1).
   */
  createPhaseFromRow(
    scope: BoardScope,
    itemId: number,
    payload: CreateFromRowPayload,
  ): Promise<ItemsResponse>
  createMilestoneFromRow(
    scope: BoardScope,
    itemId: number,
    payload: CreateFromRowPayload,
  ): Promise<ItemsResponse>

  /**
   * §0.4 — the whole Phase 관리 팝업, applied in **one** request.
   *
   * Create, rename, delete and reorder all land together because they are one edit: moving
   * a phase between two others renumbers every phase after it and every milestone under
   * them, so a sequence of small calls would show the user a series of half-renumbered
   * boards and could strand them halfway through. [취소] sends nothing at all.
   *
   * Deletion here is a **cascade** and not a deactivation — board-scoped phases and
   * milestones are part of the board's structure rather than reusable master data, so §2.6's
   * "deactivate what is in use" rule does not apply to them (§0.4). Owners and document
   * types keep it.
   */
  applyPhases(scope: BoardScope, payload: PhasesApplyPayload): Promise<BoardApplyResponse>
  /** Same, for the milestones of one phase. The phase is named in the URL. */
  applyMilestones(
    scope: BoardScope,
    phaseId: number,
    payload: MilestonesApplyPayload,
  ): Promise<BoardApplyResponse>

  // ────────────────────────────────────────────────────────── 기준정보

  listOwners(scope: MasterScope): Promise<WpOwner[]>
  createOwner(scope: MasterScope, body: Partial<WpOwner>): Promise<WpOwner>
  updateOwner(scope: MasterScope, id: number, body: Partial<WpOwner>): Promise<WpOwner>
  deleteOwner(scope: MasterScope, id: number): Promise<DeleteResult>

  listPhases(scope: MasterScope): Promise<WpPhase[]>
  createPhase(scope: MasterScope, body: Partial<WpPhase>): Promise<WpPhase>
  updatePhase(scope: MasterScope, id: number, body: Partial<WpPhase>): Promise<WpPhase>
  deletePhase(scope: MasterScope, id: number): Promise<DeleteResult>

  listMilestones(scope: MasterScope): Promise<WpMilestone[]>
  createMilestone(scope: MasterScope, body: Partial<WpMilestone>): Promise<WpMilestone>
  updateMilestone(scope: MasterScope, id: number, body: Partial<WpMilestone>): Promise<WpMilestone>
  deleteMilestone(scope: MasterScope, id: number): Promise<DeleteResult>
}

/**
 * Answer to a document apply (`plan.md` §0.5.10).
 *
 * Carries the recomputed **items** as well as the documents: deleting a document unlinks it
 * from every row that referenced it, so the grid has to be told. Same shape and same reason
 * as `BoardApplyResponse` for phases.
 */
export interface DocumentsApplyResponse {
  documents: TemplateDocument[]
  items: WpItem[]
}

/** `plan.md` §2.6 — delete endpoints report usage instead of cascading. */
export interface DeleteResult {
  id?: number
  deleted: boolean
  deactivated: boolean
  usage_count: number
  message?: string
}

/**
 * URL base for **row** operations. A template's rows hang off its version, a project's off
 * the project itself.
 */
export function itemsBase(scope: BoardScope): string {
  return scope.kind === 'template' ? `/versions/${scope.versionId}` : `/projects/${scope.projectId}`
}

/**
 * URL base for **master data**. Deliberately not the same as {@link itemsBase}: a
 * template's phases belong to the template across every one of its versions, so keying
 * them by version would give each draft its own phase list.
 */
export function masterBase(scope: MasterScope): string {
  return scope.kind === 'template'
    ? `/templates/${scope.templateId}`
    : `/projects/${scope.projectId}`
}

function createHttp(config: WpRuntimeConfig): AxiosInstance {
  const http = axios.create({
    baseURL: `${config.apiBaseUrl.replace(/\/+$/, '')}/api/v1`,
    timeout: config.requestTimeoutMs,
    withCredentials: config.withCredentials,
    headers: { ...config.headers },
  })

  http.interceptors.request.use(async (req) => {
    if (config.getAuthToken) {
      const token = await config.getAuthToken()
      if (token) req.headers.set('Authorization', `Bearer ${token}`)
    }
    return req
  })

  return http
}

/**
 * Pulls a human-readable message out of the server's error envelope.
 *
 * Domain errors arrive as `{ detail: { code, message, … } }` — an **object**, not a
 * string. Reading `detail` directly and handing it to a notification renders
 * `[object Object]`, which is what every 409 / contiguity-422 / duplicate-name 400 looked
 * like before. FastAPI's own request-validation errors use a third shape (an array of
 * `{ loc, msg }`), so all three are handled here rather than at each call site.
 */
export function describeApiError(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail

  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry as { msg?: string })?.msg)
      .filter((msg): msg is string => !!msg)
    if (messages.length > 0) return messages.join('\n')
  }
  if (detail && typeof detail === 'object') {
    const { message, code } = detail as { message?: unknown; code?: unknown }
    if (typeof message === 'string' && message) return message
    if (typeof code === 'string' && code) return code
  }

  return (error as Error)?.message || fallback
}

/**
 * Publish failure arrives as `422 { detail: { code: 'VALIDATION_FAILED', errors, … } }`
 * rather than a 200 body, so it is turned back into a plain result here. Anything else —
 * a 409 on a non-DRAFT, a network error — is left to propagate.
 */
export function unwrapValidationFailure(error: unknown): PublishResult | null {
  const response = (error as { response?: { status?: number; data?: unknown } })?.response
  if (response?.status !== 422) return null
  const detail = (response.data as { detail?: Record<string, unknown> })?.detail
  if (!detail || detail.code !== 'VALIDATION_FAILED') return null
  return {
    valid: false,
    errors: (detail.errors as PublishResult['errors']) ?? [],
    warnings: (detail.warnings as PublishResult['warnings']) ?? [],
  }
}

/** HTTP implementation of {@link WpApiClient}. */
export function createHttpApiClient(config: WpRuntimeConfig): WpApiClient {
  const http = createHttp(config)
  const get = async <T>(url: string, params?: object): Promise<T> =>
    (await http.get<T>(url, { params })).data
  const post = async <T>(url: string, body?: unknown): Promise<T> =>
    (await http.post<T>(url, body)).data
  const put = async <T>(url: string, body?: unknown): Promise<T> =>
    (await http.put<T>(url, body)).data
  const patch = async <T>(url: string, body?: unknown): Promise<T> =>
    (await http.patch<T>(url, body)).data
  const del = async <T>(url: string): Promise<T> => (await http.delete<T>(url)).data

  const rows = (scope: BoardScope) => `${itemsBase(scope)}/items`
  const master = (scope: MasterScope, collection: string) => `${masterBase(scope)}/${collection}`

  return {
    listTemplates: () => get('/templates'),
    createTemplate: (body) => post('/templates', body),
    updateTemplate: (id, body) => put(`/templates/${id}`, body),
    listVersions: (templateId) => get(`/templates/${templateId}/versions`),
    getVersion: (vid) => get(`/versions/${vid}`),

    createDraft: (templateId) => post(`/templates/${templateId}/versions/draft`, {}),
    discardDraft: (vid) => del(`/versions/${vid}`),
    saveVersionItems: (vid, items) => put(`/versions/${vid}/items`, { items }),
    validate: (vid) => post(`/versions/${vid}/validate`),
    publish: async (vid) => {
      try {
        const detail = await post<VersionDetail>(`/versions/${vid}/publish`, {})
        return { valid: true, errors: [], warnings: [], version: detail.version }
      } catch (error) {
        const result = unwrapValidationFailure(error)
        if (result) return result
        throw error
      }
    },

    listProjects: (makerId) => get('/projects', { maker_id: makerId }),
    createProject: (body) => post('/projects', body),
    getProject: (pid) => get(`/projects/${pid}`),
    getProjectsOverview: () => get('/projects/overview'),
    renameProject: (pid, name) => patch(`/projects/${pid}`, { name }),
    listMakers: () => get('/makers'),
    saveMakerSettings: (settings, projects) =>
      put('/makers/settings', { settings, projects: projects ?? [] }),
    exportBoardXlsx: async (scope) =>
      (await http.get<Blob>(`${itemsBase(scope)}/board.xlsx`, { responseType: 'blob' })).data,
    exportDashboardPptx: async (pid) =>
      (await http.get<Blob>(`/projects/${pid}/dashboard.pptx`, { responseType: 'blob' })).data,
    listDocuments: (scope) => get(`${itemsBase(scope)}/documents`),
    applyTemplateDocuments: (scope, payload) =>
      post(`${itemsBase(scope)}/documents/apply`, payload),
    listProjectLinks: (pid) => get(`/projects/${pid}/links`),
    saveProjectLinks: (pid, links) => put(`/projects/${pid}/links`, { links }),
    listProjectDocuments: (pid) => get(`/projects/${pid}/documents`),
    saveProjectDocuments: (pid, payload) => put(`/projects/${pid}/documents`, payload),
    saveProjectItems: (pid, items) => put(`/projects/${pid}/items`, { items }),
    deleteProject: (pid) => del(`/projects/${pid}`),

    appendRow: (scope) => post(rows(scope), {}),
    insertBelow: (scope, iid) => post(`${rows(scope)}/${iid}/insert-below`, {}),
    deleteItem: (scope, iid) => del(`${rows(scope)}/${iid}`),

    reorder: (scope, itemIds) => post(`${rows(scope)}/reorder`, { item_ids: itemIds }),
    setMembership: (scope, iid, payload) => patch(`${rows(scope)}/${iid}/membership`, payload),
    createPhaseFromRow: (scope, iid, payload) =>
      post(`${rows(scope)}/${iid}/create-phase`, payload),
    createMilestoneFromRow: (scope, iid, payload) =>
      post(`${rows(scope)}/${iid}/create-milestone`, payload),

    /*
     * Note the base: `itemsBase`, not `masterBase`. On the template tier that means
     * `/versions/{vid}/phases/apply` even though a template's phases belong to the
     * *template* — because this call rewrites rows as well as master data, and the rows
     * belong to one version (`plan.md` §0.4 URL list).
     */
    applyPhases: (scope, payload) => post(`${itemsBase(scope)}/phases/apply`, payload),
    applyMilestones: (scope, phaseId, payload) =>
      post(`${itemsBase(scope)}/phases/${phaseId}/milestones/apply`, payload),

    listOwners: (scope) => get(master(scope, 'owners')),
    createOwner: (scope, body) => post(master(scope, 'owners'), body),
    updateOwner: (scope, id, body) => put(`${master(scope, 'owners')}/${id}`, body),
    deleteOwner: (scope, id) => del(`${master(scope, 'owners')}/${id}`),

    listPhases: (scope) => get(master(scope, 'phases')),
    createPhase: (scope, body) => post(master(scope, 'phases'), body),
    updatePhase: (scope, id, body) => put(`${master(scope, 'phases')}/${id}`, body),
    deletePhase: (scope, id) => del(`${master(scope, 'phases')}/${id}`),

    listMilestones: (scope) => get(master(scope, 'milestones')),
    createMilestone: (scope, body) => post(master(scope, 'milestones'), body),
    updateMilestone: (scope, id, body) => put(`${master(scope, 'milestones')}/${id}`, body),
    deleteMilestone: (scope, id) => del(`${master(scope, 'milestones')}/${id}`),
  }
}
