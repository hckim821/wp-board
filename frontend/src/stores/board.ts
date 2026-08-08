import { computed, ref, shallowRef } from 'vue'
import { describeApiError, type WpApiClient } from '../api/client'
import type {
  BoardApplyResponse,
  BoardScope,
  ItemSavePayload,
  ItemsResponse,
  MilestonesApplyPayload,
  PhasesApplyPayload,
  ProjectDocumentsApplyPayload,
  ValidationIssue,
  ValidationResult,
  WpItem,
  WpProject,
  WpTemplate,
  WpVersion,
} from '../api/types'
import { renumberItems } from '../composables/useRenumber'
import type { MasterStore } from './master'

/**
 * Which tier this board is editing (`plan.md` §0.1).
 *
 * `'template'` is the 기준 데이터 editor: versions, 임시저장 / 발행 / 폐기, V1–V14 at
 * publish time. `'project'` is a maker's live board: no versions, no publish, edits land
 * directly. The **grid** is identical on both — same renumbering, same boundary rules,
 * same drag constraint — which is why one store serves both instead of two that would
 * drift apart.
 */
export type BoardTier = 'template' | 'project'

export interface BoardStoreOptions {
  tier: BoardTier
  /**
   * Options are getters, not values.
   *
   * The host owns these props and may change any of them on a live board — swapping the
   * selected maker, or revoking write access — without remounting. Capturing them once at
   * construction silently ignored those changes.
   */
  /** Null on the template tier — templates are central and maker-free (`plan.md` §0.1). */
  makerId: () => number | string | null
  /**
   * Which project to open (`plan.md` §0.6-4). Project tier only.
   *
   * The store used to *list* a maker's projects and open the first one. There is no project
   * list screen any more — 전체 현황 is the only entry point and it hands the id in — so the
   * store opens what it is given and nothing else. Opening "the first one" would silently
   * disagree with the host about which project the user asked for.
   */
  projectId?: () => number | null
  /** Forces read-only regardless of version status (host-level permission gate). */
  forceReadOnly?: () => boolean
  onError?: (message: string) => void
}

/**
 * Board state: the open container (a template's version, or a project) and its rows.
 *
 * Per-instance factory (see {@link createMasterStore} for why). The invariants worth
 * knowing:
 *
 *  1. **The server owns numbering.** Every row mutation replaces `items` with the list
 *     the server returned. Local renumbering happens first, purely so the grid does not
 *     flash stale row numbers, and is always overwritten.
 *  2. **Row mutations flush pending cell edits first.** The mutation endpoints answer
 *     with the server's view of the rows, which would otherwise silently discard
 *     unsaved edits, so anything dirty is saved before the mutation is sent.
 *  3. **Every row call goes through `scope`.** There is no version id or project id
 *     threaded through the row operations — one code path, two tiers.
 */
export function createBoardStore(api: WpApiClient, master: MasterStore, options: BoardStoreOptions) {
  const tier = options.tier

  // ── template tier ──
  const templates = shallowRef<WpTemplate[]>([])
  const templateId = ref<number | null>(null)
  const versions = shallowRef<WpVersion[]>([])
  const versionId = ref<number | null>(null)

  // ── project tier ──
  const projects = shallowRef<WpProject[]>([])
  const projectId = ref<number | null>(null)

  const items = shallowRef<WpItem[]>([])

  const loading = ref(false)
  const saving = ref(false)
  const dirty = ref(false)
  /**
   * True while the rows on screen came from an optimistic repaint rather than the server.
   *
   * `can_create_phase` / `can_create_milestone` are authorization for §2.3/§0.2 and only
   * the server computes them, so after a local renumber the copies we are holding are
   * stale. The cell editors disable "새 Phase 생성" while this is set instead of guessing —
   * a briefly disabled menu item costs far less than two implementations of one rule.
   */
  const flagsStale = ref(false)
  const validation = ref<ValidationResult | null>(null)

  const template = computed(() => templates.value.find((t) => t.id === templateId.value) ?? null)
  const version = computed(() => versions.value.find((v) => v.id === versionId.value) ?? null)
  const project = computed(() => projects.value.find((p) => p.id === projectId.value) ?? null)
  const draftVersion = computed(() => versions.value.find((v) => v.status === 'DRAFT') ?? null)
  const publishedVersion = computed(
    () => versions.value.find((v) => v.status === 'PUBLISHED') ?? null,
  )

  /** The container every row operation addresses. Null until something is open. */
  const scope = computed<BoardScope | null>(() => {
    if (tier === 'template') {
      if (templateId.value == null || versionId.value == null) return null
      return { kind: 'template', templateId: templateId.value, versionId: versionId.value }
    }
    return projectId.value == null ? null : { kind: 'project', projectId: projectId.value }
  })

  /**
   * The host revoked write access outright. Distinct from {@link readOnly}: a version
   * that is merely PUBLISHED can still be branched with 'draft 발행', but a host-imposed
   * lock has to suppress that too — creating a draft is a write.
   */
  const hostReadOnly = computed(() => !!options.forceReadOnly?.())

  /**
   * `plan.md` §2.4 — only a DRAFT is writable on the template tier.
   *
   * A project has no version to be read-only *for*: creation is the commit and everything
   * after it is direct editing (§0.1). So the only thing that can lock a project board is
   * the host.
   */
  const readOnly = computed(() => {
    if (hostReadOnly.value) return true
    if (tier === 'project') return projectId.value == null
    return !version.value || version.value.status !== 'DRAFT'
  })

  const summary = computed(() => {
    const total = items.value.length
    const done = items.value.filter((r) => r.status === 'DONE').length
    return { total, done, percent: total === 0 ? 0 : Math.round((done / total) * 100) }
  })

  /**
   * Name of the format the open project was copied from.
   *
   * Resolved from the template list rather than read off the project payload: the server
   * sends `source_template_id`, not a denormalised name. Null when the source template has
   * been removed — a project outliving its format is legal, so this reads as unknown
   * rather than breaking the toolbar.
   */
  const sourceTemplateName = computed(() => {
    const id = project.value?.source_template_id
    if (id == null) return null
    return templates.value.find((t) => t.id === id)?.name ?? null
  })

  /** How many rows are still unassigned — the gray rows of §0.2, shown in the toolbar. */
  const unassignedCount = computed(() => items.value.filter((r) => r.phase_id == null).length)

  /** item_id → the fields the last publish attempt rejected, for cell highlighting. */
  const errorFields = computed(() => {
    const map = new Map<number, Set<string>>()
    for (const issue of validation.value?.errors ?? []) {
      if (issue.item_id == null || !issue.field) continue
      const set = map.get(issue.item_id) ?? new Set<string>()
      set.add(issue.field)
      map.set(issue.item_id, set)
    }
    return map
  })

  /**
   * Surfaces a failure through the host-supplied reporter and swallows it.
   *
   * Deliberately non-throwing: these actions are called straight from template handlers,
   * and a rejected promise there becomes an unhandled rejection in the *host's* console.
   */
  function report(error: unknown, fallback: string): void {
    options.onError?.(describeApiError(error, fallback))
  }

  // ───────────────────────────────────────────────────── loading

  async function init(): Promise<void> {
    loading.value = true
    try {
      if (tier === 'template') {
        templates.value = await api.listTemplates()
        const first = templates.value.find((t) => t.is_active) ?? templates.value[0]
        if (first) await selectTemplate(first.id)
      } else {
        /*
         * The toolbar needs the *name* behind a project's `source_template_id`, and the
         * payload carries only the id — so the template list is still loaded here. The
         * **project** list is not: 전체 현황 chose the project and passed its id in.
         */
        templates.value = await api.listTemplates()
        const wanted = options.projectId?.() ?? null
        if (wanted != null) await selectProject(wanted)
        else closeProject()
      }
    } catch (error) {
      report(error, '초기 데이터를 불러오지 못했습니다.')
    } finally {
      loading.value = false
    }
  }

  // ── template tier ──

  async function selectTemplate(id: number): Promise<void> {
    templateId.value = id
    validation.value = null
    dirty.value = false
    versions.value = await api.listVersions(id)
    // Prefer the editable version; fall back to the newest published one.
    const target = versions.value.find((v) => v.status === 'DRAFT') ?? versions.value[0]
    if (target) {
      await selectVersion(target.id)
    } else {
      versionId.value = null
      items.value = []
      // Master data hangs off the template, not the version, so it loads even with no
      // version to open — which is also why `MasterScope` has no version id in it.
      await master.loadForScope({ kind: 'template', templateId: id })
    }
  }

  async function selectVersion(id: number): Promise<void> {
    loading.value = true
    try {
      const detail = await api.getVersion(id)
      templateId.value = detail.version.template_id
      versionId.value = id
      items.value = detail.items
      flagsStale.value = false
      versions.value = versions.value.map((v) => (v.id === id ? detail.version : v))
      validation.value = null
      dirty.value = false
      await master.loadForScope({ kind: 'template', templateId: detail.version.template_id })
      await loadDocuments()
    } catch (error) {
      report(error, '버전을 불러오지 못했습니다.')
    } finally {
      loading.value = false
    }
  }

  // ── project tier ──

  async function refreshProjects(): Promise<void> {
    const maker = options.makerId()
    projects.value = maker == null ? [] : await api.listProjects(maker)
  }

  async function selectProject(id: number): Promise<void> {
    loading.value = true
    try {
      const detail = await api.getProject(id)
      projectId.value = id
      items.value = detail.items
      flagsStale.value = false
      // Upsert, not map: nothing pre-loads the list any more, so the first open would
      // otherwise leave `project` null and the toolbar blank.
      projects.value = projects.value.some((p) => p.id === id)
        ? projects.value.map((p) => (p.id === id ? detail.project : p))
        : [...projects.value, detail.project]
      validation.value = null
      dirty.value = false
      await master.loadForScope({ kind: 'project', projectId: id })
      await loadDocuments()
    } catch (error) {
      report(error, '프로젝트를 불러오지 못했습니다.')
    } finally {
      loading.value = false
    }
  }

  /**
   * Pulls this scope's documents (`plan.md` §0.5.10).
   *
   * Here rather than in the master store because the endpoint hangs off `itemsBase`, which
   * needs the version id a `MasterScope` does not carry.
   */
  async function loadDocuments(): Promise<void> {
    const current = scope.value
    if (!current) return master.setDocuments([])
    const response = await api.listDocuments(current)
    master.setDocuments(response.documents as never)
  }

  /** Back to the project list. Clears the scope-local master data with it. */
  function closeProject(): void {
    projectId.value = null
    items.value = []
    dirty.value = false
    validation.value = null
    master.clearScope()
  }

  async function createProject(
    name: string,
    sourceTemplateId: number,
    sourceVersionId?: number | null,
  ): Promise<boolean> {
    const maker = options.makerId()
    if (maker == null) return false
    saving.value = true
    try {
      // The create call answers with the whole board, so `selectProject` re-fetching it
      // would be a wasted round trip — but the scope-local master data still has to be
      // loaded, and that is what `selectProject` is for. Cheap enough, and one path.
      const created = await api.createProject({
        maker_id: maker,
        name,
        template_id: sourceTemplateId,
        // 생략하면 서버가 최신 발행본을 고른다. 사용자가 특정 발행 버전을 지정할 수 있다.
        template_version_id: sourceVersionId ?? null,
      })
      await refreshProjects()
      await selectProject(created.project.id)
      return true
    } catch (error) {
      report(error, '프로젝트 생성에 실패했습니다.')
      return false
    } finally {
      saving.value = false
    }
  }

  async function reload(): Promise<void> {
    if (tier === 'template') {
      if (versionId.value != null) await selectVersion(versionId.value)
    } else if (projectId.value != null) {
      await selectProject(projectId.value)
    }
  }

  // ─────────────────────────────────────────────────── local edit

  function patchItem(itemId: number, patch: Partial<WpItem>): void {
    items.value = items.value.map((row) => (row.id === itemId ? { ...row, ...patch } : row))
    dirty.value = true
    clearErrorsFor(itemId)
  }

  /** Once a cell is touched, its stale publish error should stop shouting. */
  function clearErrorsFor(itemId: number): void {
    if (!validation.value) return
    const keep = (list: ValidationIssue[]) => list.filter((e) => e.item_id !== itemId)
    validation.value = {
      ...validation.value,
      errors: keep(validation.value.errors),
      warnings: keep(validation.value.warnings),
    }
  }

  function toSavePayload(): ItemSavePayload[] {
    // No `sort_order`: array position is authoritative (plan.md §4.2).
    return items.value.map((row) => ({
      id: row.id,
      phase_id: row.phase_id,
      milestone_id: row.milestone_id,
      title: row.title,
      deliverable: row.deliverable,
      dash_label: row.dash_label,
      gate_code: row.gate_code,
      /*
       * 사용하지 않는 문서(`no == null`)는 저장에서 뺀다 (`plan.md` §0.5.10 정밀화) — 화면에서
       * 이미 지운 링크를 다시 써넣으면 다음 조회에서 잔재가 되살아난다. 정리는 저장 시점에
       * 확정된다.
       */
      document_ids: row.documents.filter((d) => d.no != null).map((d) => d.id),
      owner_ids: row.owners.map((o) => o.id),
      status: row.status,
      completion_date: row.completion_date,
    }))
  }

  // ───────────────────────────────────────────────────── saving

  /**
   * Persists the whole list, unvalidated.
   *
   * 임시저장 on the template tier, plain 저장 on the project tier — the same bulk replace
   * either way (`plan.md` §2.5 / §0.1). Gray rows survive it on both.
   */
  async function save(silent = false): Promise<boolean> {
    const current = scope.value
    if (!current || readOnly.value) return false
    saving.value = true
    try {
      if (current.kind === 'template') {
        const detail = await api.saveVersionItems(current.versionId, toSavePayload())
        items.value = detail.items
        versions.value = versions.value.map((v) =>
          v.id === detail.version.id ? detail.version : v,
        )
      } else {
        const detail = await api.saveProjectItems(current.projectId, toSavePayload())
        items.value = detail.items
        projects.value = projects.value.map((p) =>
          p.id === detail.project.id ? detail.project : p,
        )
      }
      flagsStale.value = false
      dirty.value = false
      return true
    } catch (error) {
      if (!silent) report(error, '저장에 실패했습니다.')
      return false
    } finally {
      saving.value = false
    }
  }

  /** Row mutations answer with the server's rows, so pending edits must land first. */
  async function flushBeforeMutation(): Promise<boolean> {
    if (!dirty.value) return true
    return save()
  }

  // ────────────────────────────── template-only: validate / publish

  async function validateOnly(): Promise<ValidationResult | null> {
    if (tier !== 'template' || versionId.value == null) return null
    saving.value = true
    try {
      await flushBeforeMutation()
      const result = await api.validate(versionId.value)
      validation.value = result
      return result
    } catch (error) {
      report(error, '검증에 실패했습니다.')
      return null
    } finally {
      saving.value = false
    }
  }

  /** 발행 — full V1–V14 run; on failure the version stays a DRAFT. */
  async function publish(): Promise<ValidationResult | null> {
    if (tier !== 'template' || versionId.value == null) return null
    saving.value = true
    try {
      await flushBeforeMutation()
      const result = await api.publish(versionId.value)
      validation.value = { valid: result.valid, errors: result.errors, warnings: result.warnings }
      if (result.valid) {
        templates.value = await api.listTemplates()
        versions.value = await api.listVersions(templateId.value!)
        await selectVersion(versionId.value)
      }
      return result
    } catch (error) {
      report(error, '발행에 실패했습니다.')
      return null
    } finally {
      saving.value = false
    }
  }

  async function createDraft(): Promise<void> {
    if (tier !== 'template' || templateId.value == null) return
    saving.value = true
    try {
      const draft = await api.createDraft(templateId.value)
      versions.value = await api.listVersions(templateId.value)
      await selectVersion(draft.id)
    } catch (error) {
      report(error, 'draft 발행에 실패했습니다.')
    } finally {
      saving.value = false
    }
  }

  async function discardDraft(): Promise<void> {
    if (tier !== 'template' || versionId.value == null || templateId.value == null) return
    saving.value = true
    try {
      await api.discardDraft(versionId.value)
      dirty.value = false
      await selectTemplate(templateId.value)
    } catch (error) {
      report(error, 'DRAFT 폐기에 실패했습니다.')
    } finally {
      saving.value = false
    }
  }

  // ──────────────────────────────────────────── row mutations

  /**
   * Runs a row mutation and replaces the rows with whatever the server answered.
   *
   * Resolves `true` only when the call actually landed. Most callers ignore that — a failed
   * insert has already reported itself — but the 관리 팝업 needs it: a modal that closes on
   * a 422 would look like it applied.
   */
  async function runMutation(
    call: (scope: BoardScope) => Promise<ItemsResponse>,
    failure: string,
  ): Promise<boolean> {
    const current = scope.value
    if (!current || readOnly.value) return false
    saving.value = true
    try {
      if (!(await flushBeforeMutation())) return false
      const response = await call(current)
      items.value = response.items
      dirty.value = false
      flagsStale.value = false
      return true
    } catch (error) {
      report(error, failure)
      // The optimistic list is now unreliable — pull the server's truth back.
      await reload()
      return false
    } finally {
      saving.value = false
    }
  }

  /**
   * Adds an unassigned (gray) row below `itemId` (`plan.md` §0.2).
   *
   * Nothing is inherited. That is the change that makes "insert between two Phases"
   * reachable at all: an inherited row is born inside a block, and drag cannot leave one.
   */
  const insertBelow = (itemId: number) =>
    runMutation((s) => api.insertBelow(s, itemId), '행 추가에 실패했습니다.')

  /** Same, appended at the end — and the only entry point for a container with no rows. */
  const appendRow = () => runMutation((s) => api.appendRow(s), '행 추가에 실패했습니다.')

  const deleteItem = (itemId: number) =>
    runMutation((s) => api.deleteItem(s, itemId), '행 삭제에 실패했습니다.')

  const renumberContext = () => ({
    phaseStartNo:
      (tier === 'template' ? template.value?.phase_start_no : project.value?.phase_start_no) ?? 0,
    phaseName: (id: number) => master.phases.value.find((p) => p.id === id)?.name ?? '',
    milestoneName: (id: number) => master.milestones.value.find((m) => m.id === id)?.name ?? '',
  })

  /**
   * Commits a new row order after a managed drag — **position only**.
   *
   * The client sends ids and nothing else: not membership, and not which row moved. Every
   * row keeps its own phase/milestone on both sides of the wire, so the local repaint
   * renumbering the `No` column cannot disagree with the response about membership — there
   * is nothing left to disagree about.
   *
   * The caller is expected to have refused anything that crosses a block boundary
   * (`useBlockDrag`); this method does not re-check, because by the time an order reaches
   * it the gesture that produced it is no longer visible.
   */
  async function applyReorder(orderedIds: number[]): Promise<void> {
    const byId = new Map(items.value.map((r) => [r.id, r]))
    const ordered = orderedIds.map((id) => byId.get(id)).filter((r): r is WpItem => !!r)

    items.value = renumberItems(ordered, renumberContext())
    flagsStale.value = true

    await runMutation(
      (s) => api.reorder(s, ordered.map((r) => r.id)),
      '행 이동에 실패했습니다.',
    )
  }

  /**
   * Assigns an existing phase to a row (`plan.md` §2.3).
   *
   * The server relocates the row so the blocks stay contiguous and rejects anything that
   * would not — the client no longer computes a destination. The milestone is cleared
   * because the target block's milestones are not knowable from here; the user picks one
   * next, and publish validation catches it if they do not.
   */
  const assignPhase = (itemId: number, phaseId: number) =>
    runMutation(
      (s) => api.setMembership(s, itemId, { phase_id: phaseId, milestone_id: null }),
      'Phase 변경에 실패했습니다.',
    )

  /**
   * 미배정으로 전환 — the **only** way to reclassify an assigned row (`plan.md` §0.3).
   *
   * Membership goes to null and the row stays exactly where it is. That is always legal:
   * null is transparent to contiguity, so a gray row is valid wherever it stands, and the
   * server therefore never relocates it. The user then reassigns it through the ordinary
   * gray-row flow, which *does* relocate — so there is one mechanism for changing a row's
   * classification instead of two with different placement rules.
   */
  const unassign = (itemId: number) =>
    runMutation(
      (s) => api.setMembership(s, itemId, { phase_id: null, milestone_id: null }),
      '미배정 전환에 실패했습니다.',
    )

  /** Same, one level down. The editor only ever offers milestones of the row's own phase. */
  function assignMilestone(itemId: number, milestoneId: number): Promise<boolean> {
    const milestone = master.milestones.value.find((m) => m.id === milestoneId)
    if (!milestone) return Promise.resolve(false)
    return runMutation(
      (s) =>
        api.setMembership(s, itemId, {
          phase_id: milestone.phase_id,
          milestone_id: milestoneId,
        }),
      'Milestone 변경에 실패했습니다.',
    )
  }

  /**
   * Splits a new Phase off at `itemId` (`plan.md` §2.3, §0.2.5).
   *
   * One atomic call: create + assign + renumber. On a gray row sitting between two blocks
   * this is the whole of "add a new Phase in between" — first-appearance renumbering does
   * the rest. On the project tier the new Phase is project-local and the template is
   * untouched.
   */
  async function createPhaseAt(itemId: number, name: string): Promise<void> {
    const current = scope.value
    await runMutation(
      (s) => api.createPhaseFromRow(s, itemId, { name }),
      'Phase 생성에 실패했습니다.',
    )
    if (current) await master.loadForScope(current)
  }

  async function createMilestoneAt(itemId: number, name: string): Promise<void> {
    const current = scope.value
    await runMutation(
      (s) => api.createMilestoneFromRow(s, itemId, { name }),
      'Milestone 생성에 실패했습니다.',
    )
    if (current) await master.loadForScope(current)
  }

  /**
   * Applies the whole Phase 관리 팝업 in one call (`plan.md` §0.4).
   *
   * The server is the renumbering authority here as everywhere else, and more visibly:
   * reordering the blocks changes every phase number after the moved one *and* every
   * milestone number under them. So nothing is repainted optimistically — the response
   * replaces the rows and the scoped master lists outright.
   */
  /**
   * 관련 문서 apply (`plan.md` §0.5.10) — 템플릿 전용.
   *
   * Deleting a document unlinks it from every row, so the response carries the recomputed
   * items and they replace the board outright; nothing is repainted optimistically.
   */
  async function applyDocumentPlan(payload: {
    documents: { id: number | null; name: string }[]
    deleted_ids: number[]
  }): Promise<boolean> {
    return runMutation(async (s2) => {
      const response = await api.applyTemplateDocuments(s2, payload)
      master.setDocuments(response.documents)
      return response
    }, '문서 목록 적용에 실패했습니다.')
  }

  /** Same, for a project — its documents carry 사용여부·링크·상태 as well. */
  async function applyProjectDocumentPlan(
    payload: ProjectDocumentsApplyPayload,
  ): Promise<boolean> {
    const pid = projectId.value
    if (pid == null) return false
    return runMutation(async () => {
      const response = await api.saveProjectDocuments(pid, payload)
      master.setDocuments(response.documents as never)
      return { items: response.items ?? items.value }
    }, '문서 저장에 실패했습니다.')
  }

  async function applyPhasePlan(payload: PhasesApplyPayload): Promise<boolean> {
    return applyStructure(
      (s) => api.applyPhases(s, payload),
      'Phase 목록 적용에 실패했습니다.',
    )
  }

  /** Same, for the milestones of one phase. */
  async function applyMilestonePlan(
    phaseId: number,
    payload: MilestonesApplyPayload,
  ): Promise<boolean> {
    return applyStructure(
      (s) => api.applyMilestones(s, phaseId, payload),
      'Milestone 목록 적용에 실패했습니다.',
    )
  }

  function applyStructure(
    call: (scope: BoardScope) => Promise<BoardApplyResponse>,
    failure: string,
  ): Promise<boolean> {
    return runMutation(async (s) => {
      const response = await call(s)
      master.absorbScopeData(response)
      return response
    }, failure)
  }

  return {
    tier,
    scope,

    templates,
    templateId,
    template,
    versions,
    versionId,
    version,
    draftVersion,
    publishedVersion,

    projects,
    projectId,
    project,
    sourceTemplateName,

    items,
    loading,
    saving,
    dirty,
    flagsStale,
    validation,
    readOnly,
    hostReadOnly,
    summary,
    unassignedCount,
    errorFields,

    init,
    selectTemplate,
    selectVersion,
    refreshProjects,
    selectProject,
    closeProject,
    createProject,
    reload,
    patchItem,
    save,
    validateOnly,
    publish,
    createDraft,
    discardDraft,
    insertBelow,
    appendRow,
    deleteItem,
    applyReorder,
    assignPhase,
    assignMilestone,
    unassign,
    createPhaseAt,
    createMilestoneAt,
    applyPhasePlan,
    applyMilestonePlan,
    applyDocumentPlan,
    applyProjectDocumentPlan,
    loadDocuments,
  }
}

export type BoardStore = ReturnType<typeof createBoardStore>
