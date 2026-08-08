import type {
  BoardApplyResponse,
  BoardScope,
  CreateFromRowPayload,
  ItemSavePayload,
  ItemStatus,
  MasterScope,
  MembershipPayload,
  MilestonesApplyPayload,
  PhasesApplyPayload,
  DocWriteStatus,
  MakerProjectVisibilityPayload,
  MakerSettingPayload,
  MakersResponse,
  ProjectCreatePayload,
  ProjectDocumentsApplyPayload,
  ProjectDocumentsResponse,
  TemplateDocumentsResponse,
  ProjectLink,
  ProjectLinkSavePayload,
  ProjectLinksResponse,
  ProjectsOverviewResponse,
  StatusCounts,
  StructureEntry,
  ValidationIssue,
  ValidationResult,
  WpItem,
  WpMilestone,
  WpOwner,
  WpPhase,
  WpProject,
  WpTemplate,
  WpVersion,
} from '../api/types'
import {
  applyBlockFlags,
  applyCreateFlags,
  MILESTONE_CREATE_REFUSED,
  PHASE_CREATE_REFUSED,
} from '../composables/useRenumber'
import { dashboardText } from '../composables/useDashboard'
import { isValidLinkUrl } from '../api/types'
import type { DocumentsApplyResponse } from '../api/client'
import {
  SEED_DASH_LABELS,
  SEED_DOCUMENT_TYPES,
  SEED_MAKERS,
  SEED_MILESTONES,
  SEED_OWNERS,
  SEED_PHASES,
  SEED_ROWS,
} from './fixtures'

/**
 * In-memory stand-in for the FastAPI backend. DEV ONLY — never bundled into the remote.
 *
 * It implements the rules `plan.md` puts on the server side (§2.2 renumbering, §2.3 /
 * §0.2 boundary judgement, §2.5 publish validation) so the grid interactions can be
 * exercised end to end before the real API exists. The application code still *consumes*
 * the flags this produces rather than computing them itself, exactly as it will against
 * the real server.
 *
 * It carries both tiers of `plan.md` §0 — central templates with versions, and per-maker
 * projects without — through **one** row-operation implementation keyed by
 * {@link BoardScope}. A stand-in that only implemented one tier would let the project
 * board ship untested; one that implemented each tier separately would let the two drift,
 * which is the thing this file exists to prevent.
 */

interface StoredItem {
  id: number
  sort_order: number
  phase_id: number | null
  milestone_id: number | null
  // 서버와 동일하게 nullable — 회색 행 추가가 null 인 행을 만든다 (types.ts WpItem 주석 참조).
  title: string | null
  deliverable: string | null
  /** `plan.md` §0.5-1. Copied by both deep-copy paths — draft creation and project creation. */
  dash_label: string | null
  gate_code: string | null
  document_ids: number[]
  owner_ids: number[]
  status: ItemStatus
  completion_date: string | null
  origin: 'INHERITED' | 'ADDED'
  source_item_id: number | null
}

/**
 * Master rows carry the scope they belong to; the wire types deliberately do not
 * (`api/types.ts`). A project's phases are *copies*, so `t3` and `p9` are different owners
 * and no row ever belongs to both.
 */
type ScopeKey = string

interface StoredPhase extends WpPhase {
  scope: ScopeKey
}
interface StoredMilestone extends WpMilestone {
  scope: ScopeKey
}
interface StoredOwner extends WpOwner {
  scope: ScopeKey
}

/**
 * A document, owned by a **scope** (`plan.md` §0.5.10) — exactly like a phase or an owner.
 *
 * One row shape serves both tiers: `is_used` / `link_url` / `doc_status` are the project's
 * extra columns and stay at their defaults on a template. Splitting it in two would mean two
 * copy paths and two apply implementations for one concept.
 */
interface StoredDocument {
  id: number
  scope: ScopeKey
  name: string
  sort_order: number
  is_active: boolean
  is_used: boolean
  link_url: string | null
  doc_status: DocWriteStatus
}

/** Resolved container for a row operation: where the rows live and whether they may move. */
interface Container {
  /** Key into {@link MockBackend.items} — a version id or a project id. */
  rowsId: number
  scope: ScopeKey
  phaseStartNo: number
}

export class MockBackend {
  private seq = 1000
  private documents: StoredDocument[] = []
  private templates: WpTemplate[] = []
  private versions: WpVersion[] = []
  private projects: WpProject[] = []
  /**
   * template id → its newest PUBLISHED version.
   *
   * Kept **private** because the server does not put it on `TemplateOut`. The mock knowing
   * something the wire does not is fine; the mock *emitting* something the wire does not is
   * how a client comes to depend on a field that will be `undefined` in production.
   */
  private publishedVersionOf = new Map<number, number>()
  private phases: StoredPhase[] = []
  private milestones: StoredMilestone[] = []
  private owners: StoredOwner[] = []
  private items = new Map<number, StoredItem[]>()
  /** project id → 주요 링크, in order (`plan.md` §0.5.5). Array position *is* `sort_order`. */
  private projectLinks = new Map<number, ProjectLink[]>()
  /**
   * maker id → 전체 현황 표시 설정 (`wp_maker_settings`, `plan.md` §0.6).
   *
   * Sparse, and that sparseness is the feature: **absence means "표시 = active 프로젝트 유무"**.
   * A fresh install therefore shows a populated overview without anyone configuring anything,
   * while a tick still overrides it in either direction.
   */
  private makerSettings = new Map<number, boolean>()
  /**
   * Stand-in for the host's `MakerResolver.list_makers()`.
   *
   * Empty simulates "resolver 미주입", which is a **normal** state (root §2.2): the settings
   * screen shows guidance and the overview falls back to `설비사 #id`.
   */
  private resolverMakers: { id: number; name: string }[] = []

  constructor(
    private readonly makerId: number = 1,
    options: { resolver?: boolean } = {},
  ) {
    // `resolver: false` 로 만들면 이름 해석기가 없는 설치를 재현한다.
    this.resolverMakers = options.resolver === false ? [] : SEED_MAKERS.map((m) => ({ ...m }))
    this.seed()
  }

  private nextId(): number {
    return ++this.seq
  }

  // ───────────────────────────────────────────────────────── scoping

  private static key(scope: MasterScope): ScopeKey {
    return scope.kind === 'template' ? `t${scope.templateId}` : `p${scope.projectId}`
  }

  /**
   * Resolves a scope and enforces writability.
   *
   * The tiers differ on exactly one thing here: a template's rows may only be edited
   * through a DRAFT version (409 otherwise, §2.4), while a project has no versions and is
   * always editable (§0.1). Everything downstream is shared.
   */
  private resolve(scope: BoardScope, write: boolean): Container {
    if (scope.kind === 'template') {
      const version = this.mustVersion(scope.versionId)
      if (version.template_id !== scope.templateId) {
        throw new MockHttpError(400, `버전 ${scope.versionId} 은 이 템플릿의 것이 아닙니다.`)
      }
      if (write && version.status !== 'DRAFT') {
        throw new MockHttpError(409, '발행되었거나 보관된 버전은 수정할 수 없습니다.')
      }
      const template = this.mustTemplate(version.template_id)
      return {
        rowsId: version.id,
        scope: MockBackend.key(scope),
        phaseStartNo: template.phase_start_no,
      }
    }
    const project = this.mustProject(scope.projectId)
    return {
      rowsId: project.id,
      scope: MockBackend.key(scope),
      phaseStartNo: project.phase_start_no,
    }
  }

  /** Scope of a template version, for callers holding only the version id. */
  versionScope(versionId: number): BoardScope {
    return { kind: 'template', templateId: this.mustVersion(versionId).template_id, versionId }
  }

  projectScope(projectId: number): BoardScope {
    return { kind: 'project', projectId }
  }

  // ─────────────────────────────────────────────────────────── seed

  private seed(): void {
    const template: WpTemplate = {
      id: this.nextId(),
      code: 'DSEP-AI-BOARD',
      name: 'DSEP AI Project Board 표준 포맷',
      description: '설비사 AI 과제 표준 Work Package (엑셀 Project Board 대체)',
      phase_start_no: 0,
      is_active: true,
    }
    // A second template proves the template switcher works *and* that a template with no
    // published version cannot be picked when creating a project.
    const draftOnly: WpTemplate = {
      id: this.nextId(),
      code: 'DSEP-AI-PILOT2',
      name: '2차 확대 과제 포맷 (미발행)',
      description: '아직 발행되지 않은 포맷 — 프로젝트 생성 후보에서 빠져야 한다',
      phase_start_no: 1,
      is_active: true,
    }
    this.templates = [template, draftOnly]
    const scope: ScopeKey = `t${template.id}`

    const phaseByKey = new Map<string, StoredPhase>()
    SEED_PHASES.forEach((p, i) => {
      const row: StoredPhase = {
        id: this.nextId(),
        scope,
        name: p.name,
        seq_no: i,
        is_active: true,
      }
      phaseByKey.set(p.key, row)
      this.phases.push(row)
    })

    const msByKey = new Map<string, StoredMilestone>()
    const perPhase = new Map<string, number>()
    for (const m of SEED_MILESTONES) {
      const next = (perPhase.get(m.phaseKey) ?? 0) + 1
      perPhase.set(m.phaseKey, next)
      const row: StoredMilestone = {
        id: this.nextId(),
        scope,
        phase_id: phaseByKey.get(m.phaseKey)!.id,
        name: m.name,
        seq_no: next,
        is_active: true,
      }
      msByKey.set(m.key, row)
      this.milestones.push(row)
    }

    /*
     * 문서는 이제 **템플릿 소유**다 (§0.5.10). 원문자 코드는 없어졌고 표시 번호는
     * `sort_order` 다 — 원본 엑셀의 ①~⑤ 는 순서 1~5 에 그대로 대응한다.
     */
    const docByCode = new Map<string, StoredDocument>()
    SEED_DOCUMENT_TYPES.forEach((d, i) => {
      const row: StoredDocument = {
        id: this.nextId(),
        scope,
        name: d.name,
        sort_order: i + 1,
        is_active: true,
        is_used: true,
        link_url: null,
        doc_status: 'NOT_WRITTEN',
      }
      docByCode.set(d.code, row)
      this.documents.push(row)
    })

    const ownerByName = new Map<string, StoredOwner>()
    SEED_OWNERS.forEach((name, i) => {
      const row: StoredOwner = {
        id: this.nextId(),
        scope,
        name,
        sort_order: i + 1,
        is_active: true,
      }
      ownerByName.set(name, row)
      this.owners.push(row)
    })

    // v1 PUBLISHED holds the 35 rows imported from the spreadsheet.
    const v1: WpVersion = {
      id: this.nextId(),
      template_id: template.id,
      version_number: 1,
      status: 'PUBLISHED',
      source_version_id: null,
      notes: '엑셀 원본 임포트',
      published_at: '2026-07-01T09:00:00',
      archived_at: null,
      created_by: null,
      published_by: null,
      created_at: '2026-07-01T08:00:00',
      updated_at: '2026-07-01T09:00:00',
      is_editable: false,
    }
    this.versions.push(v1)
    this.publishedVersionOf.set(template.id, v1.id)
    this.items.set(
      v1.id,
      SEED_ROWS.map((r, i) => {
        const ms = msByKey.get(r.milestoneKey)!
        return {
          id: this.nextId(),
          sort_order: i + 1,
          phase_id: ms.phase_id,
          milestone_id: ms.id,
          title: r.title,
          deliverable: r.deliverable,
          dash_label: SEED_DASH_LABELS[i] ?? null,
          gate_code: r.gate ?? null,
          document_ids: r.docs.map((c) => docByCode.get(c)!.id),
          owner_ids: r.owners.map((n) => ownerByName.get(n)!.id),
          status: 'NOT_STARTED' as ItemStatus,
          completion_date: null,
          origin: 'INHERITED' as const,
          source_item_id: null,
        }
      }),
    )

    // …and a v2 DRAFT copied from it, so the admin harness opens straight into edit mode.
    this.deepCopyToDraft(template.id)

    // The unpublished template gets an empty DRAFT and nothing else.
    this.deepCopyToDraft(draftOnly.id)

    // One existing project for the harness maker, taken from v1. The project tier has to
    // have something to open; a workspace that is only ever exercised empty would never
    // execute the grid at all.
    const seedProject = this.createProject({
      maker_id: this.makerId,
      name: '2026 AI 과제 1차',
      template_id: template.id,
      template_version_id: v1.id,
    })

    /*
     * A deliberately mixed document fixture (`plan.md` §0.5-4).
     *
     * The overview's ④ area branches five ways — 완료/작성중 × 링크 있음/없음, 작성전, and
     * 미사용 — and a fixture where every document looked the same would render one of those
     * branches and prove nothing about the other four. ⑤ is left **unsaved** on purpose so
     * the LEFT JOIN default path is exercised by a real row rather than only by a test.
     */
    /*
     * 주요 링크 픽스처 (§0.5.5). Two rows so reordering has something to reorder, and one of
     * them carries the `edm` cloud-file shape the spec names.
     */
    this.saveProjectLinks(seedProject.id, [
      { id: null, description: '프로젝트 Confluence 홈', url: 'https://confluence.example.com/wp/home' },
      { id: null, description: 'EDM 산출물 폴더', url: 'https://edm.example.com/folder/2026-ai-1' },
    ])

    const copied = this.scopeDocuments(`p${seedProject.id}`)
    this.saveProjectDocuments(seedProject.id, {
      documents: copied.map((doc, i) => ({
        id: doc.id,
        name: doc.name,
        is_used: i !== 3,
        link_url:
          i === 0
            ? 'https://cloud.example.com/wp/charter'
            : i === 1
              ? 'https://cloud.example.com/wp/readiness'
              : null,
        doc_status: i === 0 ? 'DONE' : i === 1 || i === 2 ? 'WRITING' : 'NOT_WRITTEN',
      })),
      deleted_ids: [],
    })
  }

  // ────────────────────────────────────────────────────── projection

  /**
   * Turns stored rows into the `WpItem` payload of `plan.md` §4.3 and, as a side effect,
   * writes the recomputed `seq_no` back onto the phase/milestone master rows — the same
   * thing `renumber_service` does server-side.
   */
  project(scope: BoardScope): WpItem[] {
    const container = this.resolve(scope, false)
    // Array order is authoritative, not the stored `sort_order`: mutations splice the
    // array directly and `sort_order` is only rewritten at the end of this method.
    // Re-sorting by the stale value here would quietly undo every reorder.
    const stored = this.items.get(container.rowsId) ?? []
    const displayNo = this.displayNumbers(container.scope)

    const phaseNo = new Map<number, number>()
    const msNo = new Map<number, number>()
    const nextMs = new Map<number, number>()
    let nextPhase = container.phaseStartNo

    const projected: WpItem[] = stored.map((row, index) => {
      let pNo: number | null = null
      if (row.phase_id != null) {
        if (!phaseNo.has(row.phase_id)) {
          phaseNo.set(row.phase_id, nextPhase++)
          nextMs.set(row.phase_id, 1)
        }
        pNo = phaseNo.get(row.phase_id)!
      }

      let mNo: number | null = null
      if (row.phase_id != null && row.milestone_id != null) {
        if (!msNo.has(row.milestone_id)) {
          const n = nextMs.get(row.phase_id) ?? 1
          msNo.set(row.milestone_id, n)
          nextMs.set(row.phase_id, n + 1)
        }
        mNo = msNo.get(row.milestone_id)!
      }

      const phase = row.phase_id != null ? this.phases.find((p) => p.id === row.phase_id) : null
      const ms =
        row.milestone_id != null ? this.milestones.find((m) => m.id === row.milestone_id) : null

      return {
        id: row.id,
        sort_order: index + 1,
        row_no: index + 1,
        phase_id: row.phase_id,
        phase_no: pNo,
        phase_name: phase?.name ?? null,
        phase_display: pNo != null ? `Phase ${pNo}. ${phase?.name ?? ''}`.trimEnd() : null,
        milestone_id: row.milestone_id,
        milestone_no: mNo,
        milestone_name: ms?.name ?? null,
        milestone_display:
          pNo != null && mNo != null ? `${pNo}.${mNo} ${ms?.name ?? ''}`.trimEnd() : null,
        is_phase_block_start: false,
        is_phase_block_end: false,
        is_milestone_block_start: false,
        is_milestone_block_end: false,
        can_create_phase: false,
        can_create_milestone: false,
        title: row.title,
        deliverable: row.deliverable,
        dash_label: row.dash_label,
        gate_code: row.gate_code,
        // 표시 번호는 저장 코드가 아니라 **사용 문서 기준 1..N** 파생값이다 (§0.5.10 정밀화).
        documents: row.document_ids
          .map((id) => this.documents.find((d) => d.id === id))
          .filter((d): d is StoredDocument => !!d)
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((d) => ({ id: d.id, no: displayNo.get(d.id) ?? null, name: d.name })),
        owners: row.owner_ids
          .map((id) => this.owners.find((o) => o.id === id))
          .filter((o): o is StoredOwner => !!o)
          .map((o) => ({ id: o.id, name: o.name })),
        status: row.status,
        completion_date: row.completion_date,
        origin: row.origin,
      }
    })

    stored.forEach((row, i) => (row.sort_order = i + 1))
    for (const [id, no] of phaseNo) {
      const p = this.phases.find((x) => x.id === id)
      if (p) p.seq_no = no
    }
    for (const [id, no] of msNo) {
      const m = this.milestones.find((x) => x.id === id)
      if (m) m.seq_no = no
    }

    // Block flags first, then the create gate — the latter reads the former for assigned
    // rows. Both live in `useRenumber`, on the server side of the client/server line.
    return applyCreateFlags(applyBlockFlags(projected))
  }

  // ─────────────────────────────────────────────────────── templates

  listTemplates(): WpTemplate[] {
    return this.templates.map((t) => ({ ...t }))
  }

  upsertTemplate(body: Partial<WpTemplate>, id?: number): WpTemplate {
    if (id != null) {
      const found = this.mustTemplate(id)
      Object.assign(found, body)
      return { ...found }
    }
    const created: WpTemplate = {
      id: this.nextId(),
      code: body.code ?? '',
      name: body.name ?? '',
      description: body.description ?? null,
      phase_start_no: body.phase_start_no ?? 0,
      is_active: body.is_active ?? true,
    }
    this.templates.push(created)
    return { ...created }
  }

  listVersions(templateId: number): WpVersion[] {
    return this.versions
      .filter((v) => v.template_id === templateId)
      .sort((a, b) => b.version_number - a.version_number)
      .map((v) => ({ ...v }))
  }

  getVersion(versionId: number): { version: WpVersion; items: WpItem[] } {
    return {
      version: { ...this.mustVersion(versionId) },
      items: this.project(this.versionScope(versionId)),
    }
  }

  private mustTemplate(id: number): WpTemplate {
    const t = this.templates.find((x) => x.id === id)
    if (!t) throw new MockHttpError(404, `템플릿 ${id} 을(를) 찾을 수 없습니다.`)
    return t
  }

  private mustVersion(id: number): WpVersion {
    const v = this.versions.find((x) => x.id === id)
    if (!v) throw new MockHttpError(404, `버전 ${id} 을(를) 찾을 수 없습니다.`)
    return v
  }

  private mustProject(id: number): WpProject {
    const p = this.projects.find((x) => x.id === id)
    if (!p) throw new MockHttpError(404, `프로젝트 ${id} 을(를) 찾을 수 없습니다.`)
    return p
  }

  // ────────────────────────────────────────────────────── versioning

  deepCopyToDraft(templateId: number): WpVersion {
    this.mustTemplate(templateId)
    if (this.versions.some((v) => v.template_id === templateId && v.status === 'DRAFT')) {
      throw new MockHttpError(409, '이미 작성중인 DRAFT 버전이 있습니다.')
    }
    const published = this.versions.find(
      (v) => v.template_id === templateId && v.status === 'PUBLISHED',
    )
    const maxNo = this.versions
      .filter((v) => v.template_id === templateId)
      .reduce((m, v) => Math.max(m, v.version_number), 0)

    const draft: WpVersion = {
      id: this.nextId(),
      template_id: templateId,
      version_number: maxNo + 1,
      status: 'DRAFT',
      source_version_id: published?.id ?? null,
      notes: null,
      published_at: null,
      archived_at: null,
      created_by: null,
      published_by: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      is_editable: true,
    }
    this.versions.push(draft)

    const source = published ? (this.items.get(published.id) ?? []) : []
    this.items.set(
      draft.id,
      source.map((row) => ({
        ...row,
        id: this.nextId(),
        document_ids: [...row.document_ids],
        owner_ids: [...row.owner_ids],
        origin: 'INHERITED' as const,
        source_item_id: row.id,
      })),
    )
    return { ...draft }
  }

  discardDraft(versionId: number): void {
    const version = this.mustVersion(versionId)
    if (version.status !== 'DRAFT') {
      throw new MockHttpError(409, '발행되었거나 보관된 버전은 수정할 수 없습니다.')
    }
    this.versions = this.versions.filter((v) => v.id !== versionId)
    this.items.delete(versionId)
  }

  /**
   * Throws a 422 on validation failure rather than returning a result object — the real
   * service does, and the client's unwrapping code only runs if this one does too.
   */
  publish(versionId: number): { result: ValidationResult; version: WpVersion } {
    const draft = this.mustVersion(versionId)
    if (draft.status !== 'DRAFT') {
      throw new MockHttpError(409, '발행되었거나 보관된 버전은 수정할 수 없습니다.')
    }
    const result = this.validate(versionId)
    if (!result.valid) {
      throw new MockHttpError(422, '발행 검증에 실패했습니다.', {
        code: 'VALIDATION_FAILED',
        valid: false,
        errors: result.errors,
        warnings: result.warnings,
      })
    }

    const current = this.versions.find(
      (v) => v.template_id === draft.template_id && v.status === 'PUBLISHED',
    )
    if (current) {
      current.status = 'ARCHIVED'
      current.archived_at = new Date().toISOString()
      current.is_editable = false
    }
    draft.status = 'PUBLISHED'
    draft.published_at = new Date().toISOString()
    draft.is_editable = false
    this.publishedVersionOf.set(draft.template_id, draft.id)
    return { result, version: { ...draft } }
  }

  // ───────────────────────────────────────────────────────── projects

  listProjects(makerId: number | string): WpProject[] {
    return this.projects
      .filter((p) => String(p.maker_id) === String(makerId) && p.is_active)
      .map((p) => ({ ...p }))
  }

  getProject(projectId: number): { project: WpProject; items: WpItem[] } {
    return {
      project: { ...this.mustProject(projectId) },
      items: this.project(this.projectScope(projectId)),
    }
  }

  /**
   * Creates a project by deep-copying one **published** template version (`plan.md` §0.1).
   *
   * Everything scoped to the template is copied, not referenced: phases, milestones,
   * owners and rows all get fresh ids under the project's own scope, and the ids inside
   * the rows are remapped to the copies. Document types are the one exception — they are
   * global and shared by design.
   *
   * A project taken from an unpublished template would be a snapshot of something nobody
   * agreed to, so that is a 422 rather than a convenience.
   */
  createProject(payload: ProjectCreatePayload): WpProject {
    const template = this.mustTemplate(payload.template_id)
    const versionId = payload.template_version_id ?? this.publishedVersionOf.get(template.id)
    if (versionId == null) {
      throw new MockHttpError(422, '발행된 버전이 없는 템플릿으로는 프로젝트를 만들 수 없습니다.', {
        code: 'TEMPLATE_NOT_PUBLISHED',
      })
    }
    const version = this.mustVersion(versionId)
    if (version.template_id !== template.id) {
      throw new MockHttpError(400, '이 템플릿의 버전이 아닙니다.')
    }
    if (version.status === 'DRAFT') {
      throw new MockHttpError(422, '작성중인 DRAFT 버전으로는 프로젝트를 만들 수 없습니다.', {
        code: 'TEMPLATE_NOT_PUBLISHED',
      })
    }
    if (!(payload.name ?? '').trim()) {
      throw new MockHttpError(400, '프로젝트 이름은 필수입니다.')
    }

    const project: WpProject = {
      id: this.nextId(),
      maker_id: Number(payload.maker_id),
      name: payload.name.trim(),
      description: payload.description ?? null,
      source_template_id: template.id,
      source_version_id: version.id,
      source_version_number: version.version_number,
      // Snapshotted: renumbering a live project because the template's start number moved
      // later would be exactly the silent reclassification this design keeps refusing.
      phase_start_no: template.phase_start_no,
      is_active: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    this.projects.push(project)

    const from: ScopeKey = `t${template.id}`
    const to: ScopeKey = `p${project.id}`

    const phaseMap = new Map<number, number>()
    for (const phase of this.phases.filter((p) => p.scope === from)) {
      const copy: StoredPhase = { ...phase, id: this.nextId(), scope: to }
      phaseMap.set(phase.id, copy.id)
      this.phases.push(copy)
    }
    const msMap = new Map<number, number>()
    for (const milestone of this.milestones.filter((m) => m.scope === from)) {
      const copy: StoredMilestone = {
        ...milestone,
        id: this.nextId(),
        scope: to,
        phase_id: phaseMap.get(milestone.phase_id) ?? milestone.phase_id,
      }
      msMap.set(milestone.id, copy.id)
      this.milestones.push(copy)
    }
    /*
     * 문서도 복제한다 (`plan.md` §0.5.10) — Phase·Milestone·Owner 와 같은 규칙이다. 전역
     * 마스터였던 시절에는 공유가 정답이었지만, 이제 포맷이 소유하므로 프로젝트는 자기 사본을
     * 갖고 이후 서로 무관하다.
     */
    const docMap = new Map<number, number>()
    for (const doc of this.scopeDocuments(from)) {
      const copy: StoredDocument = { ...doc, id: this.nextId(), scope: to }
      docMap.set(doc.id, copy.id)
      this.documents.push(copy)
    }

    const ownerMap = new Map<number, number>()
    for (const owner of this.owners.filter((o) => o.scope === from)) {
      const copy: StoredOwner = { ...owner, id: this.nextId(), scope: to }
      ownerMap.set(owner.id, copy.id)
      this.owners.push(copy)
    }

    this.items.set(
      project.id,
      (this.items.get(version.id) ?? []).map((row) => ({
        ...row,
        id: this.nextId(),
        phase_id: row.phase_id != null ? (phaseMap.get(row.phase_id) ?? null) : null,
        milestone_id: row.milestone_id != null ? (msMap.get(row.milestone_id) ?? null) : null,
        document_ids: row.document_ids.map((id) => docMap.get(id) ?? id),
        owner_ids: row.owner_ids.map((id) => ownerMap.get(id) ?? id),
        origin: 'INHERITED' as const,
        source_item_id: row.id,
      })),
    )

    return { ...project }
  }

  deleteProject(projectId: number): void {
    this.mustProject(projectId).is_active = false
  }

  /**
   * XLSX 내보내기 스텁 (`plan.md` §0.5.7).
   *
   * 같은 이유로 비어 있다 — 원본 양식 재현과 `parse_workbook` round-trip 은 openpyxl 쪽
   * 계약이고, 그 검증은 백엔드 테스트의 몫이다. 여기서 확인할 것은 scope 해석과 다운로드
   * 흐름뿐이다.
   */
  exportBoardXlsx(scope: BoardScope): Blob {
    // 존재하지 않는 버전·프로젝트는 여기서 404 가 된다.
    this.resolve(scope, false)
    return new Blob([], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
  }

  /**
   * PPTX 내보내기 스텁 (`plan.md` §0.5.6).
   *
   * Deliberately **not** a real presentation: generation is python-pptx's job on the server,
   * and a JS stand-in would be a second implementation of a format nobody here owns. What the
   * front end must get right is the *flow* — request, blob, object URL, anchor, revoke — and
   * an empty blob of the right MIME type exercises all of it. Its correctness is the
   * backend's test to write.
   */
  exportDashboardPptx(projectId: number): Blob {
    this.mustProject(projectId)
    return new Blob([], {
      type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    })
  }

  // ─────────────────────────── 프로젝트 주요 링크 (`plan.md` §0.5.5)

  /** `sort_order` 순. The stored array order is the answer; nothing re-sorts. */
  listProjectLinks(projectId: number): ProjectLinksResponse {
    this.mustProject(projectId)
    return {
      links: (this.projectLinks.get(projectId) ?? []).map((link, i) => ({
        ...link,
        sort_order: i + 1,
      })),
    }
  }

  /**
   * Whole-list replace (`plan.md` §0.5.5): **array position becomes `sort_order`**, and an
   * existing id absent from the payload is deleted.
   *
   * Validation runs over the **entire** payload before anything is written, so a bad row in
   * the middle cannot leave the first half saved and the rest not. Both rules are the
   * server's — the grid checks them too, but only so the user learns while typing.
   */
  saveProjectLinks(projectId: number, payload: ProjectLinkSavePayload[]): ProjectLinksResponse {
    this.mustProject(projectId)
    const existing = this.projectLinks.get(projectId) ?? []
    const byId = new Map(existing.map((l) => [l.id, l]))

    payload.forEach((row, index) => {
      if (!(row.description ?? '').trim()) {
        throw new MockHttpError(422, `${index + 1}번째 링크: 설명은 비울 수 없습니다.`, {
          code: 'LINK_DESCRIPTION_REQUIRED',
          index,
        })
      }
      if (!isValidLinkUrl(row.url)) {
        throw new MockHttpError(
          422,
          `${index + 1}번째 링크: http:// 또는 https:// 로 시작하는 주소여야 합니다.`,
          { code: 'LINK_URL_INVALID', index },
        )
      }
      if (row.id != null && !byId.has(row.id)) {
        throw new MockHttpError(422, `이 프로젝트의 링크가 아닙니다: ${row.id}`, {
          code: 'LINK_OUT_OF_SCOPE',
        })
      }
    })

    this.projectLinks.set(
      projectId,
      payload.map((row, index) => ({
        id: row.id ?? this.nextId(),
        description: row.description.trim(),
        url: row.url.trim(),
        sort_order: index + 1,
      })),
    )
    return this.listProjectLinks(projectId)
  }

  // ──────────────────────── 프로젝트 문서 링크·상태 (`plan.md` §0.5-4)

  /**
   * id → 표시 번호, **사용(ON) 문서에만 1..N** (`plan.md` §0.5.10 정밀화).
   *
   * `sort_order` is the stored position and stays contiguous over *all* documents; the
   * display number is derived from it over the used subset only. Keeping them separate is
   * what lets a document be switched off and back on without disturbing anyone else's
   * position — the alternative, renumbering `sort_order` on every toggle, would rewrite rows
   * nobody touched.
   *
   * A template has no 사용 concept, so every document is used and the two coincide there.
   */
  private displayNumbers(scope: ScopeKey): Map<number, number> {
    const map = new Map<number, number>()
    let next = 1
    for (const doc of this.scopeDocuments(scope)) {
      if (doc.is_used) map.set(doc.id, next++)
    }
    return map
  }

  /** Documents owned by one scope, in `sort_order` (`plan.md` §0.5.10). */
  private scopeDocuments(scope: ScopeKey): StoredDocument[] {
    return this.documents
      .filter((d) => d.scope === scope)
      .sort((a, b) => a.sort_order - b.sort_order)
  }

  /**
   * Read for both the cell popup and the 문서 등록 탭.
   *
   * **Emits `no`, not `sort_order`** — the stored position stays inside the engine, exactly
   * as it does server-side (`plan.md` §0.5.10 필드 확정). Leaking the storage field is what
   * made the mock and the server disagree while `npm run check` stayed green.
   */
  listDocuments(scope: BoardScope): TemplateDocumentsResponse | ProjectDocumentsResponse {
    /*
     * **The two tiers answer with different shapes**, exactly as the server does: a project
     * adds 사용·링크·상태. Returning the template shape for both is what left `is_used`
     * undefined in the popup, so every document looked used and the 순서 column numbered all
     * of them — green in the mock, wrong on the wire.
     */
    if (scope.kind === 'project') return this.listProjectDocuments(scope.projectId)
    const container = this.resolve(scope, false)
    const displayNo = this.displayNumbers(container.scope)
    return {
      documents: this.scopeDocuments(container.scope).map((d) => ({
        id: d.id,
        name: d.name,
        no: displayNo.get(d.id) ?? null,
        is_active: d.is_active,
      })),
    }
  }

  listProjectDocuments(projectId: number): ProjectDocumentsResponse {
    this.mustProject(projectId)
    const displayNo = this.displayNumbers(`p${projectId}`)
    return {
      documents: this.scopeDocuments(`p${projectId}`).map((d) => ({
        id: d.id,
        name: d.name,
        no: displayNo.get(d.id) ?? null,
        is_used: d.is_used,
        link_url: d.link_url,
        doc_status: d.doc_status,
      })),
    }
  }

  /**
   * Shared validation for both applies (`plan.md` §0.5.10).
   *
   * Same final-state contract as `phases/apply`: the kept and deleted ids must add up to
   * exactly the scope's current set, or a forgotten id silently reads as a deletion.
   */
  private assertDocumentSet(
    entries: { id: number | null; name: string }[],
    deletedIds: number[],
    existing: StoredDocument[],
  ): void {
    const fail = (code: string, message: string, extra: Record<string, unknown> = {}) => {
      throw new MockHttpError(422, message, { code, ...extra })
    }
    if (entries.some((e) => !(e.name ?? '').trim())) {
      fail('DOCUMENT_EMPTY_NAME', '문서 이름은 비울 수 없습니다.')
    }
    const names = entries.map((e) => e.name.trim())
    if (new Set(names).size !== names.length) {
      fail('DOCUMENT_DUPLICATE_NAME', '문서 이름이 중복되었습니다.')
    }
    const keptIds = entries.filter((e) => e.id != null).map((e) => e.id!)
    const overlap = keptIds.filter((id) => deletedIds.includes(id))
    if (
      new Set(keptIds).size !== keptIds.length ||
      new Set(deletedIds).size !== deletedIds.length ||
      overlap.length > 0
    ) {
      fail('DOCUMENT_DUPLICATE_ID', '문서 id 가 두 번 이상 지정되었습니다.')
    }
    const known = new Set(existing.map((d) => d.id))
    const unknown = [...keptIds, ...deletedIds].filter((id) => !known.has(id))
    if (unknown.length > 0) {
      fail('DOCUMENT_OUT_OF_SCOPE', `이 스코프의 문서가 아닙니다: ${unknown.join(', ')}`, { unknown })
    }
    const accounted = new Set([...keptIds, ...deletedIds])
    const missing = existing.map((d) => d.id).filter((id) => !accounted.has(id))
    if (missing.length > 0) {
      fail(
        'DOCUMENT_SET_MISMATCH',
        `문서 목록이 현재 전체 집합과 일치하지 않습니다. 누락: ${missing.join(', ')}`,
        { missing },
      )
    }
  }

  /**
   * Raw stored `document_ids`, per row — **test support only**.
   *
   * `project()` resolves ids against the document table and silently drops any that no longer
   * resolve, so a stale link is invisible through the ordinary payload. That made the cascade
   * assertion pass even with the unlink removed, which is exactly the kind of check that
   * looks like a guarantee and is not. This is the only way to see the stored truth.
   */
  rawDocumentLinks(scope: BoardScope): number[][] {
    const container = this.resolve(scope, false)
    return (this.items.get(container.rowsId) ?? []).map((row) => [...row.document_ids])
  }

  /** Removes deleted documents from every row of the scope — the §0.5.10 cascade. */
  private unlinkDocuments(scope: ScopeKey, removed: Set<number>): void {
    if (removed.size === 0) return
    for (const rows of this.items.values()) {
      for (const row of rows) {
        row.document_ids = row.document_ids.filter((id) => !removed.has(id))
      }
    }
    this.documents = this.documents.filter((d) => !(d.scope === scope && removed.has(d.id)))
  }

  /**
   * 템플릿 문서 apply — `phases/apply` 동형 (`plan.md` §0.5.10).
   *
   * Array order becomes `sort_order` 1..N, so the display numbers are recomputed rather than
   * typed. Deletion cascades to the rows, which is why the answer carries `items`.
   */
  applyTemplateDocuments(
    scope: BoardScope,
    payload: { documents: { id: number | null; name: string }[]; deleted_ids: number[] },
  ): DocumentsApplyResponse {
    const container = this.resolve(scope, true)
    const existing = this.scopeDocuments(container.scope)
    const entries = payload.documents ?? []
    const deletedIds = payload.deleted_ids ?? []
    this.assertDocumentSet(entries, deletedIds, existing)

    this.unlinkDocuments(container.scope, new Set(deletedIds))

    const ordered: StoredDocument[] = []
    entries.forEach((entry, index) => {
      if (entry.id != null) {
        const found = this.documents.find((d) => d.id === entry.id)!
        found.name = entry.name.trim()
        found.sort_order = index + 1
        ordered.push(found)
        return
      }
      const created: StoredDocument = {
        id: this.nextId(),
        scope: container.scope,
        name: entry.name.trim(),
        sort_order: index + 1,
        is_active: true,
        is_used: true,
        link_url: null,
        doc_status: 'NOT_WRITTEN',
      }
      this.documents.push(created)
      ordered.push(created)
    })

    const displayNo = this.displayNumbers(container.scope)
    return {
      documents: ordered.map((d) => ({
        id: d.id,
        name: d.name,
        no: displayNo.get(d.id) ?? null,
        is_active: d.is_active,
      })),
      items: this.project(scope),
    }
  }

  /**
   * 프로젝트 문서 전량 교체 (`plan.md` §0.5.10).
   *
   * Same final-state shape as the template apply, plus the project's own columns. The cell
   * popup's management half and the 문서 등록 탭 both come through here — one path, so the two
   * screens cannot show different lists.
   */
  saveProjectDocuments(
    projectId: number,
    payload: ProjectDocumentsApplyPayload,
  ): ProjectDocumentsResponse {
    this.mustProject(projectId)
    const scopeKey: ScopeKey = `p${projectId}`
    const existing = this.scopeDocuments(scopeKey)
    const entries = payload.documents ?? []
    const deletedIds = payload.deleted_ids ?? []
    this.assertDocumentSet(entries, deletedIds, existing)

    this.unlinkDocuments(scopeKey, new Set(deletedIds))

    entries.forEach((entry, index) => {
      const link = (entry.link_url ?? '').trim() || null
      if (entry.id != null) {
        const found = this.documents.find((d) => d.id === entry.id)!
        found.name = entry.name.trim()
        found.sort_order = index + 1
        found.is_used = !!entry.is_used
        found.link_url = link
        found.doc_status = entry.doc_status
        return
      }
      this.documents.push({
        id: this.nextId(),
        scope: scopeKey,
        name: entry.name.trim(),
        sort_order: index + 1,
        is_active: true,
        is_used: !!entry.is_used,
        link_url: link,
        doc_status: entry.doc_status,
      })
    })

    return {
      ...this.listProjectDocuments(projectId),
      items: this.project(this.projectScope(projectId)),
    }
  }

  /**
   * 프로젝트명 수정 (`plan.md` §0.6). Only the name — nothing else about a project is
   * editable from the overview, and `maker_id` in particular is not.
   */
  renameProject(projectId: number, name: string): WpProject {
    const project = this.mustProject(projectId)
    const trimmed = (name ?? '').trim()
    if (!trimmed) {
      throw new MockHttpError(422, '프로젝트 이름은 비울 수 없습니다.', { code: 'EMPTY_NAME' })
    }
    project.name = trimmed
    project.updated_at = new Date().toISOString()
    return { ...project }
  }

  /** Makers that have at least one **active** project. */
  private makersWithProjects(): Set<number> {
    return new Set(this.projects.filter((p) => p.is_active).map((p) => p.maker_id))
  }

  /**
   * §0.6 표시 규칙, in one place:
   *
   *   설정행이 있으면 → 그 값
   *   없으면          → active 프로젝트가 있으면 표시
   *
   * Three branches, and the third is the one that matters: an unconfigured install still
   * shows a populated overview, so nobody has to discover a settings screen before the
   * feature works at all.
   */
  private showsInOverview(makerId: number, hasProjects: boolean): boolean {
    const explicit = this.makerSettings.get(makerId)
    return explicit ?? hasProjects
  }

  /**
   * 설비사 목록 + 설정 (`plan.md` §0.6).
   *
   * The universe is the resolver's list **unioned with** makers that already own projects —
   * a project whose maker the resolver no longer returns must not vanish from the settings
   * screen, or its section could never be turned off. Dangling maker ids are the host's
   * problem to fix, not ours to hide (root §2.2).
   *
   * "owns projects" here counts **inactive ones too**, unlike `makersWithProjects()`. A maker
   * whose every project is switched off would otherwise drop out of the only screen that can
   * switch them back on, which would make off a one-way door.
   */
  listMakers(): MakersResponse {
    const withProjects = this.makersWithProjects()
    const ids = [
      ...new Set([
        ...this.resolverMakers.map((m) => m.id),
        ...this.projects.map((p) => p.maker_id),
      ]),
    ]
    const nameOf = new Map(this.resolverMakers.map((m) => [m.id, m.name]))

    const rows = ids.map((id) => {
      const hasProjects = withProjects.has(id)
      return {
        maker_id: id,
        name: nameOf.get(id) ?? null,
        show_in_overview: this.showsInOverview(id, hasProjects),
        explicit: this.makerSettings.has(id),
        has_projects: hasProjects,
        // 비활성 포함 — 이 목록이 곧 스위치 목록이다.
        projects: this.projects
          .filter((p) => p.maker_id === id)
          .map((p) => ({ id: p.id, name: p.name, is_active: !!p.is_active })),
      }
    })
    return { makers: MockBackend.sortMakers(rows) }
  }

  /**
   * Upsert. An id outside the known universe is a 422 rather than a silent orphan row.
   *
   * `projects` rides along so the settings screen's single 저장 is a single write. Unknown
   * **project** ids are a 422 too, and for a firmer reason than makers: projects are ours, so
   * "the host might know it" is no excuse for accepting an id that lands nowhere.
   */
  saveMakerSettings(
    settings: MakerSettingPayload[],
    projects: MakerProjectVisibilityPayload[] = [],
  ): MakersResponse {
    const known = new Set(this.listMakers().makers.map((m) => m.maker_id))
    const unknown = settings.map((s) => s.maker_id).filter((id) => !known.has(id))
    if (unknown.length > 0) {
      throw new MockHttpError(422, `알 수 없는 설비사입니다: ${unknown.join(', ')}`, {
        code: 'UNKNOWN_MAKER',
        maker_ids: unknown,
      })
    }
    const missing = projects.map((p) => p.id).filter((id) => !this.projects.some((p) => p.id === id))
    if (missing.length > 0) {
      throw new MockHttpError(422, `없는 프로젝트입니다: ${missing.join(', ')}`, {
        code: 'PROJECT_NOT_FOUND',
        project_ids: missing,
      })
    }

    for (const row of settings) this.makerSettings.set(row.maker_id, !!row.show_in_overview)
    // 표시만 끈다 — 행은 그대로 남는다 (실제 삭제는 `db/delete_project.py` 뿐).
    for (const row of projects) this.mustProject(row.id).is_active = !!row.is_active
    return this.listMakers()
  }

  /**
   * Named makers by name, then unnamed by id — the ordering the client used to do and the
   * server now owns (`plan.md` §0.6). Mixing them would let `설비사 #12` sort as though the
   * placeholder were a name.
   */
  private static sortMakers<T extends { maker_id: number; name: string | null }>(rows: T[]): T[] {
    const named = rows.filter((m) => !!m.name?.trim())
    const unnamed = rows.filter((m) => !m.name?.trim())
    named.sort((a, b) => a.name!.localeCompare(b.name!, 'ko'))
    unnamed.sort((a, b) => a.maker_id - b.maker_id)
    return [...named, ...unnamed]
  }

  /**
   * 전체 현황 (`plan.md` §0.5-3, **grouped by maker as of §0.6**).
   *
   * Only makers the display rule admits, and a ticked maker with no projects still gets a
   * section — that empty section is where its first project gets created.
   *
   * `maker_name` is null throughout when no resolver is configured, which is the normal
   * unconfigured state the screen must render (root `INTEGRATION.md` §2).
   */
  projectsOverview(): ProjectsOverviewResponse {
    const withProjects = this.makersWithProjects()
    const nameOf = new Map(this.resolverMakers.map((m) => [m.id, m.name]))
    const ids = [...new Set([...this.resolverMakers.map((m) => m.id), ...withProjects])].filter(
      (id) => this.showsInOverview(id, withProjects.has(id)),
    )

    const makers = ids.map((id) => ({
      maker_id: id,
      name: nameOf.get(id) ?? null,
      projects: this.projects
        .filter((p) => p.is_active && p.maker_id === id)
        .map((p) => this.overviewProject(p)),
    }))
    return { makers: MockBackend.sortMakers(makers) }
  }

  /** One project's overview payload — the §0.5-3 shape, unchanged by §0.6. */
  private overviewProject(p: WpProject) {
    const items = this.project(this.projectScope(p.id))
    const counts: StatusCounts = { NOT_STARTED: 0, IN_PROGRESS: 0, DONE: 0, HOLD: 0, NA: 0 }
    for (const row of items) counts[row.status]++
    return {
      id: p.id,
      name: p.name,
      maker_id: p.maker_id,
      maker_name: this.resolverMakers.find((m) => m.id === p.maker_id)?.name ?? null,
      counts,
      /*
       * `dash_label` goes out **already resolved** through the §0.5-1 fallback chain
       * (`dash_label` → `deliverable` → title head).
       *
       * The overview payload carries no `deliverable` and no `title`, so the client
       * physically cannot run that chain — it would show `(내용 없음)` for every row nobody
       * had labelled, which on a freshly created project is all 35 of them. Resolving here
       * keeps the wire narrow; INTEGRATION.md §7.6 states it so the real service matches.
       */
      items: items.map((row) => ({
        no: row.row_no,
        status: row.status,
        phase_seq: row.phase_no,
        milestone_seq: row.milestone_no,
        dash_label: dashboardText(row) || null,
        // The shared popover's three remaining fields (§0.5-3, 2026-08-08). `owners` is
        // names because nothing on this screen can resolve an id across projects.
        title: row.title,
        deliverable: row.deliverable,
        owners: row.owners.map((o) => o.name),
      })),
      // 사용 체크된 것만 (§0.5-4). `is_used` 자체는 싣지 않는다 — 실려 있다는 사실이 곧 그 값이다.
      documents: this.listProjectDocuments(p.id)
        .documents.filter((doc) => doc.is_used)
        .map((doc, index) => ({
          id: doc.id,
          // 사용 문서만 실리므로 여기서는 그 안의 순번이 곧 표시 번호다.
          no: index + 1,
          name: doc.name,
          doc_status: doc.doc_status,
          link_url: doc.link_url,
        })),
    }
  }

  // ────────────────────────────────────────────────────── row edits

  saveItems(scope: BoardScope, payload: ItemSavePayload[]): WpItem[] {
    const container = this.resolve(scope, true)
    /*
     * 임시저장 (template) / 직접 저장 (project) are both unvalidated whole-list replaces
     * (§2.5, §0.1). Only referential integrity is enforced, which is why nulls — and gray
     * rows — survive the round trip.
     *
     * `sort_order` is not part of the payload: array position is authoritative. The server
     * still *accepts* it and 400s when some rows carry it and others do not, because a
     * half-populated ordering has no defensible interpretation. A host driving this
     * through the `dataSource` escape hatch would otherwise see the stand-in silently
     * accept what the real service refuses.
     */
    const withOrder = payload.filter((p) => (p as { sort_order?: number }).sort_order != null)
    if (withOrder.length > 0 && withOrder.length !== payload.length) {
      throw new MockHttpError(
        400,
        'sort_order 는 전체 행에 있거나 전혀 없어야 합니다. 섞어 보낼 수 없습니다.',
        { code: 'MIXED_SORT_ORDER' },
      )
    }

    const existing = this.items.get(container.rowsId) ?? []
    const next: StoredItem[] = payload.map((p, i) => {
      const found = p.id != null ? existing.find((r) => r.id === p.id) : null
      this.assertRef(p.phase_id, this.phases, 'phase_id', container.scope)
      this.assertRef(p.milestone_id, this.milestones, 'milestone_id', container.scope)
      for (const ownerId of p.owner_ids) {
        this.assertRef(ownerId, this.owners, 'owner_id', container.scope)
      }
      return {
        id: found?.id ?? this.nextId(),
        sort_order: i + 1,
        phase_id: p.phase_id,
        milestone_id: p.milestone_id,
        title: p.title,
        deliverable: p.deliverable,
        dash_label: p.dash_label,
        gate_code: p.gate_code,
        document_ids: [...p.document_ids],
        owner_ids: [...p.owner_ids],
        status: p.status,
        completion_date: p.completion_date,
        origin: found?.origin ?? 'ADDED',
        source_item_id: found?.source_item_id ?? null,
      }
    })
    this.items.set(container.rowsId, next)
    return this.project(scope)
  }

  /**
   * Existence is not enough — the row must belong to *this* scope.
   *
   * The server's `_check_references` 400s on a well-formed id that points into another
   * template or project. This matters far more under §0 than it did with one work
   * package: a project's phases are copies with their own ids, so a client holding the
   * template's ids would otherwise write cross-tier references that look valid.
   */
  private assertRef(
    id: number | null,
    table: { id: number; scope: ScopeKey }[],
    field: string,
    scope: ScopeKey,
  ): void {
    if (id == null) return
    const row = table.find((r) => r.id === id)
    if (!row) {
      throw new MockHttpError(400, `존재하지 않는 ${field} 참조입니다: ${id}`, {
        code: 'INVALID_REFERENCE',
      })
    }
    if (row.scope !== scope) {
      throw new MockHttpError(400, `다른 스코프의 ${field} 를 참조할 수 없습니다: ${id}`, {
        code: 'INVALID_REFERENCE',
      })
    }
  }

  /**
   * Adds an **unassigned (gray) row** at the end (`plan.md` §0.2).
   *
   * Membership starts null on purpose: legal everywhere, invisible to contiguity,
   * draggable anywhere, and flagged by V1/V2 only when a *template* is published.
   */
  appendRow(scope: BoardScope): WpItem[] {
    const container = this.resolve(scope, true)
    const rows = this.items.get(container.rowsId) ?? []
    rows.push(this.blankRow(rows.length + 1))
    this.items.set(container.rowsId, rows)
    return this.project(scope)
  }

  /**
   * Adds an unassigned (gray) row directly below the anchor.
   *
   * It used to inherit the anchor's phase/milestone, which kept every block contiguous by
   * construction — and made it impossible to open a new Phase between two existing ones,
   * because the new row was born inside a block and a drag cannot leave one. §0.2 trades
   * that construction for the gray row: contiguity now holds because null is transparent.
   */
  insertBelow(scope: BoardScope, itemId: number): WpItem[] {
    const container = this.resolve(scope, true)
    const rows = this.items.get(container.rowsId) ?? []
    const index = rows.findIndex((r) => r.id === itemId)
    if (index < 0) throw new MockHttpError(404, `행 ${itemId} 을(를) 찾을 수 없습니다.`)

    rows.splice(index + 1, 0, this.blankRow(0))
    return this.project(scope)
  }

  private blankRow(sortOrder: number): StoredItem {
    return {
      id: this.nextId(),
      sort_order: sortOrder,
      phase_id: null,
      milestone_id: null,
      title: '',
      deliverable: '',
      dash_label: null,
      gate_code: null,
      document_ids: [],
      owner_ids: [],
      status: 'NOT_STARTED',
      completion_date: null,
      origin: 'ADDED',
      source_item_id: null,
    }
  }

  deleteItem(scope: BoardScope, itemId: number): WpItem[] {
    const container = this.resolve(scope, true)
    const rows = (this.items.get(container.rowsId) ?? []).filter((r) => r.id !== itemId)
    this.items.set(container.rowsId, rows)
    return this.project(scope)
  }

  /**
   * Position only. Membership is neither accepted nor re-derived: every row keeps the
   * `phase_id` / `milestone_id` it already had and only its slot changes (`plan.md` §2.2).
   *
   * The old behaviour — re-inheriting the moved row's membership from its new predecessor
   * — is what silently reclassified a row dragged across a phase boundary, and it is gone
   * from the real service too. `moved_item_id` went with it; it was never sent.
   */
  reorder(scope: BoardScope, itemIds: number[]): WpItem[] {
    const container = this.resolve(scope, true)
    const rows = this.items.get(container.rowsId) ?? []
    const byId = new Map(rows.map((r) => [r.id, r]))

    if (itemIds.length !== rows.length || new Set(itemIds).size !== rows.length) {
      throw new MockHttpError(
        400,
        'reorder 목록은 이 스코프의 전체 행을 정확히 한 번씩 포함해야 합니다.',
      )
    }

    const ordered: StoredItem[] = []
    for (const id of itemIds) {
      const row = byId.get(id)
      if (!row) throw new MockHttpError(400, `이 스코프에 없는 item_id: ${id}`)
      row.sort_order = ordered.length + 1
      ordered.push(row)
    }

    const previous = rows.map((r) => ({ ...r }))
    this.items.set(container.rowsId, ordered)
    try {
      /*
       * "Membership is preserved, therefore contiguity is preserved" is false, and the
       * guard is the primary defence, not a backstop. Rows carry their own membership, so
       * any permutation that interleaves two blocks fragments both — `[A/0, B/1, A/0]` is
       * one call away from any two-row board. The UI never sends such a permutation (see
       * `useBlockDrag.isWithinBlockOrder`), but this is a server stand-in and the host's
       * other clients are not bound by our grid.
       */
      const projected = this.project(scope)
      const broken = this.contiguityErrors(projected)[0]
      if (broken) {
        throw new MockHttpError(422, broken.message, {
          code: broken.code,
          breaks: [{ row_no: broken.row_no, item_id: broken.item_id }],
        })
      }
      return projected
    } catch (error) {
      this.items.set(container.rowsId, previous)
      throw error
    }
  }

    /**
   * §2.3 / §0.3 cell edit — the server relocates the row so blocks stay contiguous.
   *
   * **Placement is milestone-granular.** Naming a milestone lands the row at the end of
   * *that milestone's block*; naming only a phase lands it at the end of the phase block;
   * naming neither (미배정으로 전환) moves it nowhere at all, because null is transparent to
   * contiguity and a gray row is legal wherever it stands.
   *
   * This mirrors the real service, which was verified by reproduction on 2026-08-08. The
   * previous version of this method got it wrong twice over and the divergence reached
   * users through `npm run dev`, which defaults to this stand-in:
   *
   *  1. it relocated to the end of the **phase**, so choosing 2.2 parked the row after 2.4;
   *  2. it skipped relocation entirely whenever a (gray-transparent) neighbour already had
   *     the target *phase* — so the follow-up "now set the milestone" call decided it was
   *     already adjacent and left an M2.2 row stranded after 2.3, which first-appearance
   *     renumbering then rendered as scrambled labels, or which the contiguity check
   *     rejected outright with a 422.
   *
   * There is no adjacency shortcut any more. Remove-then-reinsert is idempotent by
   * construction: a row already at the end of its target block computes the same index
   * back, so "already in the right place" needs no special case — and a special case is
   * exactly what bug 2 was.
   */
  setMembership(scope: BoardScope, itemId: number, payload: MembershipPayload): WpItem[] {
    const container = this.resolve(scope, true)
    this.assertRef(payload.phase_id, this.phases, 'phase_id', container.scope)
    this.assertRef(payload.milestone_id, this.milestones, 'milestone_id', container.scope)

    const rows = this.items.get(container.rowsId) ?? []
    const index = rows.findIndex((r) => r.id === itemId)
    if (index < 0) throw new MockHttpError(404, `행 ${itemId} 을(를) 찾을 수 없습니다.`)

    const previous = rows.map((r) => ({ ...r }))
    const target = rows[index]!
    target.phase_id = payload.phase_id
    target.milestone_id = payload.milestone_id

    if (payload.phase_id != null) {
      // Pull it out first, so the row never counts as its own block's last member.
      rows.splice(index, 1)

      /** Index of the last row matching `key`, or -1. */
      const lastIndexOf = (match: (row: StoredItem) => boolean) => {
        let found = -1
        for (let i = 0; i < rows.length; i++) if (match(rows[i]!)) found = i
        return found
      }

      /*
       * Milestone first, phase as the fallback. The fallback covers a milestone that
       * currently has no rows — its block is empty, so the row belongs at the end of the
       * phase that owns it — and a phase that has no rows either, where -1 + 1 = 0 would
       * be wrong, so the row simply goes back where it was.
       */
      let at = -1
      if (payload.milestone_id != null) {
        at = lastIndexOf((row) => row.milestone_id === payload.milestone_id)
      }
      if (at < 0) at = lastIndexOf((row) => row.phase_id === payload.phase_id)
      rows.splice(at < 0 ? index : at + 1, 0, target)
    }

    this.items.set(container.rowsId, rows)
    try {
      const projected = this.project(scope)
      const broken = this.contiguityErrors(projected)[0]
      if (broken) throw new MockHttpError(422, broken.message, { code: broken.code })
      return projected
    } catch (error) {
      this.items.set(container.rowsId, previous)
      throw error
    }
  }

  /**
   * §2.3 / §0.2 creation — create + assign + renumber in one step, so nothing can be
   * orphaned.
   *
   * The anchor keeps its slot and only its `phase_id` changes, so where the new block
   * lands follows from where the anchor sat. On a gray row parked between two blocks that
   * is precisely "between them", and first-appearance renumbering hands it the number in
   * between with no insertion logic at all (§0.2.5).
   */
  createPhaseFromRow(scope: BoardScope, itemId: number, payload: CreateFromRowPayload): WpItem[] {
    const container = this.resolve(scope, true)
    const anchor = this.project(scope).find((r) => r.id === itemId)
    if (!anchor) throw new MockHttpError(404, `행 ${itemId} 을(를) 찾을 수 없습니다.`)
    if (!anchor.can_create_phase) {
      throw new MockHttpError(422, PHASE_CREATE_REFUSED, { code: 'PHASE_CREATE_NOT_ALLOWED' })
    }
    if (this.phases.some((p) => p.scope === container.scope && p.name === payload.name)) {
      throw new MockHttpError(400, `이미 존재하는 Phase 이름입니다: ${payload.name}`)
    }

    const phase: StoredPhase = {
      id: this.nextId(),
      scope: container.scope,
      name: payload.name,
      seq_no: 0,
      is_active: true,
    }
    this.phases.push(phase)

    const row = (this.items.get(container.rowsId) ?? []).find((r) => r.id === itemId)!
    row.phase_id = phase.id
    row.milestone_id = null
    return this.project(scope)
  }

  createMilestoneFromRow(
    scope: BoardScope,
    itemId: number,
    payload: CreateFromRowPayload,
  ): WpItem[] {
    const container = this.resolve(scope, true)
    const anchor = this.project(scope).find((r) => r.id === itemId)
    if (!anchor) throw new MockHttpError(404, `행 ${itemId} 을(를) 찾을 수 없습니다.`)
    if (anchor.phase_id == null) {
      throw new MockHttpError(422, 'Phase 를 먼저 지정해야 Milestone 을 만들 수 있습니다.')
    }
    if (!anchor.can_create_milestone) {
      throw new MockHttpError(422, MILESTONE_CREATE_REFUSED, {
        code: 'MILESTONE_CREATE_NOT_ALLOWED',
      })
    }

    const milestone: StoredMilestone = {
      id: this.nextId(),
      scope: container.scope,
      phase_id: anchor.phase_id,
      name: payload.name,
      seq_no: 0,
      is_active: true,
    }
    this.milestones.push(milestone)

    const row = (this.items.get(container.rowsId) ?? []).find((r) => r.id === itemId)!
    row.milestone_id = milestone.id
    return this.project(scope)
  }

  // ──────────────────────────────────── §0.4 관리 팝업 — atomic apply

  /**
   * The Phase 관리 팝업, applied whole (`plan.md` §0.4).
   *
   * Four things happen in this order, and the order matters:
   *
   *  1. **cascade delete** — a phase named in `deleted_ids` takes its rows and its
   *     milestones with it. §2.6's "deactivate what is in use" rule is explicitly lifted for
   *     board-scoped phases: they are board *structure*, and the popup already warned the
   *     user how many rows go with them.
   *  2. **rename** the survivors.
   *  3. **create** the new ones — each with the row it cannot exist without. With an anchor
   *     that row is the caller's gray row; without one it is a fresh blank row.
   *  4. **rearrange blocks** into the popup's order.
   *
   * There is no numbering step. `project()` derives every number from first-appearance
   * order, so putting the blocks in the right order *is* the renumbering — which is why
   * dropping a new phase between 0 and 1 pushes the old 1 to 2, along with every milestone
   * number under it, without anything here knowing that happened.
   */
  applyPhases(scope: BoardScope, payload: PhasesApplyPayload): BoardApplyResponse {
    const container = this.resolve(scope, true)
    const rows = this.items.get(container.rowsId) ?? []

    /*
     * The set the payload must account for is **the phases that have rows on this board**,
     * in first-appearance order — not every phase in the master table.
     *
     * That is the same set the popup shows, and it has to be: a phase with no rows has no
     * first appearance, so it has no number, no block and no position in a list whose whole
     * meaning is order. Including one would ask the user to place something that cannot be
     * placed. Master rows that no board row uses are simply outside this operation.
     */
    const existingIds: number[] = []
    for (const row of rows) {
      if (row.phase_id != null && !existingIds.includes(row.phase_id)) existingIds.push(row.phase_id)
    }

    const entries = payload.phases ?? []
    const deletedIds = payload.deleted_ids ?? []
    this.assertApplySet(entries, deletedIds, existingIds, 'Phase')

    const anchor = this.resolveAnchor(rows, payload.anchor_item_id ?? null, entries, (row) =>
      row.phase_id == null && row.milestone_id == null
        ? null
        : '앵커로 지정할 수 있는 것은 미배정(회색) 행뿐입니다.',
    )

    const restore = this.snapshot(container)
    try {
      const removing = new Set(deletedIds)
      let next = rows.filter((r) => r.phase_id == null || !removing.has(r.phase_id))
      this.milestones = this.milestones.filter(
        (m) => !(m.scope === container.scope && removing.has(m.phase_id)),
      )
      this.phases = this.phases.filter(
        (p) => !(p.scope === container.scope && removing.has(p.id)),
      )

      const order: number[] = []
      for (const entry of entries) {
        if (entry.id != null) {
          const found = this.phases.find((p) => p.id === entry.id)!
          found.name = entry.name.trim()
          order.push(found.id)
          continue
        }
        const created: StoredPhase = {
          id: this.nextId(),
          scope: container.scope,
          name: entry.name.trim(),
          seq_no: 0,
          is_active: true,
        }
        this.phases.push(created)
        order.push(created.id)

        if (anchor) {
          anchor.phase_id = created.id
          anchor.milestone_id = null
        } else {
          // "행 없는 Phase 는 존재할 수 없다" — a phase with no rows has no first
          // appearance and therefore no number at all.
          const blank = this.blankRow(0)
          blank.phase_id = created.id
          next = [...next, blank]
        }
      }

      this.items.set(container.rowsId, MockBackend.regroup(next, (r) => r.phase_id, order))
      return this.assertContiguous(scope)
    } catch (error) {
      restore()
      throw error
    }
  }

  /**
   * Same, one level down: the milestones of a single phase.
   *
   * Only that phase's block is touched. Rows of other phases keep their positions, which is
   * what makes this safe to run while the rest of the board is arbitrary.
   */
  applyMilestones(
    scope: BoardScope,
    phaseId: number,
    payload: MilestonesApplyPayload,
  ): BoardApplyResponse {
    const container = this.resolve(scope, true)
    const phase = this.phases.find((p) => p.id === phaseId && p.scope === container.scope)
    if (!phase) {
      throw new MockHttpError(422, `이 보드의 Phase 가 아닙니다: ${phaseId}`, {
        code: 'APPLY_OUT_OF_SCOPE',
      })
    }

    const rows = this.items.get(container.rowsId) ?? []
    // Same rule as `applyPhases`: the milestones of this phase that actually have rows.
    const existingIds: number[] = []
    for (const row of rows) {
      if (row.phase_id !== phaseId) continue
      if (row.milestone_id != null && !existingIds.includes(row.milestone_id)) {
        existingIds.push(row.milestone_id)
      }
    }

    const entries = payload.milestones ?? []
    const deletedIds = payload.deleted_ids ?? []
    this.assertApplySet(entries, deletedIds, existingIds, 'Milestone')

    /*
     * The anchor is any row with no milestone whose phase is either this one or nothing at
     * all. Both are 'gray' at the milestone level, and admitting the fully gray row is what
     * keeps §0.3's flow alive: a row that has just been given a phase, and now needs a
     * milestone that does not exist yet, is exactly the second case.
     */
    const anchor = this.resolveAnchor(rows, payload.anchor_item_id ?? null, entries, (row) =>
      row.milestone_id == null && (row.phase_id == null || row.phase_id === phaseId)
        ? null
        : '앵커 행은 Milestone 이 미지정이고, 미배정이거나 이 Phase 에 속한 행이어야 합니다.',
    )
    /** A fully gray anchor joins this phase, so it has to be moved into the phase's block. */
    const anchorJoinsPhase = anchor != null && anchor.phase_id == null

    const restore = this.snapshot(container)
    try {
      const removing = new Set(deletedIds)
      let next = rows.filter((r) => r.milestone_id == null || !removing.has(r.milestone_id))
      this.milestones = this.milestones.filter(
        (m) => !(m.scope === container.scope && removing.has(m.id)),
      )

      const order: number[] = []
      for (const entry of entries) {
        if (entry.id != null) {
          const found = this.milestones.find((m) => m.id === entry.id)!
          found.name = entry.name.trim()
          order.push(found.id)
          continue
        }
        const created: StoredMilestone = {
          id: this.nextId(),
          scope: container.scope,
          phase_id: phaseId,
          name: entry.name.trim(),
          seq_no: 0,
          is_active: true,
        }
        this.milestones.push(created)
        order.push(created.id)

        if (anchor) {
          anchor.phase_id = phaseId
          anchor.milestone_id = created.id
        } else {
          /*
           * §0.4 describes this blank row as "해당 phase 배정·milestone null". Taken
           * literally the new milestone would own no rows, which contradicts the very
           * invariant the blank row exists to satisfy — and would leave it unnumbered and
           * invisible on the board it was just created for. It is assigned to the new
           * milestone instead; noted here because the server may read that sentence the
           * other way.
           */
          const blank = this.blankRow(0)
          blank.phase_id = phaseId
          blank.milestone_id = created.id
          next = [...next, blank]
        }
      }

      /*
       * A fully gray anchor was standing somewhere else on the board and has just joined
       * this phase. Left where it was it would put a second, disjoint run of this phase on
       * the board — so it is relocated to the end of the phase block first, exactly as
       * `setMembership` does. The regroup below then moves it to wherever the popup put its
       * milestone.
       */
      if (anchorJoinsPhase && anchor) {
        next = next.filter((r) => r !== anchor)
        let last = -1
        next.forEach((r, i) => {
          if (r.phase_id === phaseId) last = i
        })
        next.splice(last < 0 ? next.length : last + 1, 0, anchor)
      }

      // Confine the rearrangement to this phase's span, gray rows included: rows outside it
      // are none of this call's business.
      const first = next.findIndex((r) => r.phase_id === phaseId)
      if (first >= 0) {
        let last = first
        next.forEach((r, i) => {
          if (r.phase_id === phaseId) last = i
        })
        const span = MockBackend.regroup(
          next.slice(first, last + 1),
          (r) => r.milestone_id,
          order,
        )
        next = [...next.slice(0, first), ...span, ...next.slice(last + 1)]
      }

      this.items.set(container.rowsId, next)
      return this.assertContiguous(scope)
    } catch (error) {
      restore()
      throw error
    }
  }

  /**
   * Reorders whole blocks into `order`, **carrying unassigned rows with the assigned row
   * they follow** (`plan.md` §0.4).
   *
   * A gray row parked inside or at the end of a block is part of that block as far as
   * movement goes — it was put there deliberately, and leaving it behind while its block
   * moves elsewhere would scatter the user's placement. Gray rows *leading* the list have no
   * block above them to belong to, so they stay at the top.
   */
  private static regroup(
    rows: StoredItem[],
    keyOf: (row: StoredItem) => number | null,
    order: number[],
  ): StoredItem[] {
    const head: StoredItem[] = []
    let i = 0
    while (i < rows.length && keyOf(rows[i]!) == null) head.push(rows[i++]!)

    const chunks: { key: number; rows: StoredItem[] }[] = []
    while (i < rows.length) {
      const key = keyOf(rows[i]!)!
      const chunk = [rows[i++]!]
      while (i < rows.length && keyOf(rows[i]!) == null) chunk.push(rows[i++]!)
      chunks.push({ key, rows: chunk })
    }

    const out = [...head]
    for (const key of order) {
      for (const chunk of chunks) if (chunk.key === key) out.push(...chunk.rows)
    }
    // Unreachable after `assertApplySet`, but dropping rows silently is the one failure mode
    // that must not be possible here.
    for (const chunk of chunks) if (!order.includes(chunk.key)) out.push(...chunk.rows)
    return out
  }

  /**
   * The popup's list must account for **every** existing entry (`plan.md` §0.4).
   *
   * Not pedantry: the payload is a final state, so an id the client simply forgot to send
   * would otherwise read as "delete it". Refusing the whole call turns a client bug into a
   * 422 instead of into silent data loss.
   */
  private assertApplySet(
    entries: StructureEntry[],
    deletedIds: number[],
    /** Ids that have rows on this board, first-appearance order. */
    existingIds: number[],
    label: string,
  ): void {
    const fail = (code: string, message: string, extra: Record<string, unknown> = {}) => {
      throw new MockHttpError(422, message, { code, ...extra })
    }

    if (entries.some((e) => !(e.name ?? '').trim())) {
      fail('APPLY_EMPTY_NAME', `${label} 이름은 비울 수 없습니다.`)
    }

    const names = entries.map((e) => e.name.trim())
    if (new Set(names).size !== names.length) {
      fail('APPLY_DUPLICATE_NAME', `${label} 이름이 중복되었습니다.`)
    }

    const keptIds = entries.filter((e) => e.id != null).map((e) => e.id!)
    const overlap = keptIds.filter((id) => deletedIds.includes(id))
    if (
      new Set(keptIds).size !== keptIds.length ||
      new Set(deletedIds).size !== deletedIds.length ||
      overlap.length > 0
    ) {
      fail('APPLY_DUPLICATE_ID', `${label} id 가 두 번 이상 지정되었습니다.`)
    }

    const known = new Set(existingIds)
    const unknown = [...keptIds, ...deletedIds].filter((id) => !known.has(id))
    if (unknown.length > 0) {
      fail(
        'APPLY_OUT_OF_SCOPE',
        `이 보드에 행이 있는 ${label} 가 아닙니다: ${unknown.join(', ')}`,
        { unknown },
      )
    }

    const accounted = new Set([...keptIds, ...deletedIds])
    const missing = existingIds.filter((id) => !accounted.has(id))
    if (missing.length > 0) {
      fail(
        'APPLY_SET_MISMATCH',
        `${label} 목록이 현재 전체 집합과 일치하지 않습니다. 누락: ${missing.join(', ')}`,
        { missing, unknown: [], expected: existingIds },
      )
    }
  }

  /** Validates `anchor_item_id` and hands back the row it names, or null when absent. */
  private resolveAnchor(
    rows: StoredItem[],
    anchorItemId: number | null,
    entries: StructureEntry[],
    reject: (row: StoredItem) => string | null,
  ): StoredItem | null {
    if (anchorItemId == null) return null
    const row = rows.find((r) => r.id === anchorItemId)
    if (!row) throw new MockHttpError(404, `행 ${anchorItemId} 을(를) 찾을 수 없습니다.`)
    const refusal = reject(row)
    if (refusal) throw new MockHttpError(422, refusal, { code: 'APPLY_ANCHOR_INVALID' })
    if (entries.filter((e) => e.id == null).length !== 1) {
      throw new MockHttpError(422, '앵커 행을 지정할 때는 신규 항목이 정확히 1개여야 합니다.', {
        code: 'APPLY_ANCHOR_INVALID',
      })
    }
    return row
  }

  /** Deep copy of everything an apply touches, and the closure that puts it back. */
  private snapshot(container: Container): () => void {
    const rows = (this.items.get(container.rowsId) ?? []).map((r) => ({ ...r }))
    const phases = this.phases.map((p) => ({ ...p }))
    const milestones = this.milestones.map((m) => ({ ...m }))
    return () => {
      this.items.set(container.rowsId, rows)
      this.phases = phases
      this.milestones = milestones
    }
  }

  /**
   * The apply's answer, refused if the board it produced is fragmented.
   *
   * Regrouping cannot fragment a board that arrived contiguous, so this fires only for one
   * that did not — a milestone apply run over a phase whose rows were already interleaved
   * with another phase's, which `regroup` would shuffle further. The caller rolls back, so
   * an already-broken board is left exactly as broken as it was rather than differently so.
   */
  private assertContiguous(scope: BoardScope): BoardApplyResponse {
    const payload = this.boardPayload(scope)
    const broken = this.contiguityErrors(payload.items)[0]
    if (broken) {
      throw new MockHttpError(422, broken.message, {
        code: 'APPLY_BOARD_NOT_CONTIGUOUS',
        breaks: [{ row_no: broken.row_no, item_id: broken.item_id }],
      })
    }
    return payload
  }

  /** Rows + the scoped master lists — the response shape of every apply (`plan.md` §0.4). */
  private boardPayload(scope: BoardScope): BoardApplyResponse {
    const items = this.project(scope)
    const masterScope: MasterScope =
      scope.kind === 'template'
        ? { kind: 'template', templateId: scope.templateId }
        : { kind: 'project', projectId: scope.projectId }
    return {
      items,
      phases: this.listPhases(masterScope),
      milestones: this.listMilestones(masterScope),
    }
  }

  // ────────────────────────────────────────────────────── validation

  /**
   * `plan.md` §2.5 — V1 … V14. **Template publishing only.**
   *
   * A project has no publish step (§0.1), so nothing calls this on that tier and gray rows
   * simply persist there.
   */
  validate(versionId: number): ValidationResult {
    const scope = this.versionScope(versionId)
    const container = this.resolve(scope, false)
    const items = this.project(scope)
    const errors: ValidationIssue[] = []
    const warnings: ValidationIssue[] = []

    if (items.length === 0) {
      errors.push({
        code: 'EMPTY_VERSION',
        level: 'error',
        message: '행이 없는 버전은 발행할 수 없습니다.',
      })
      return { valid: false, errors, warnings }
    }

    for (const row of items) {
      const at = (field: ValidationIssue['field'], code: string, message: string) =>
        errors.push({ code, level: 'error', item_id: row.id, row_no: row.row_no, field, message })

      if (row.phase_id == null) {
        at('phase_id', 'PHASE_REQUIRED', `${row.row_no}행: Phase가 지정되지 않았습니다.`)
      }
      if (row.milestone_id == null) {
        at(
          'milestone_id',
          'MILESTONE_REQUIRED',
          `${row.row_no}행: Milestone이 지정되지 않았습니다.`,
        )
      }
      if (row.phase_id != null && row.milestone_id != null) {
        const ms = this.milestones.find((m) => m.id === row.milestone_id)
        if (ms && ms.phase_id !== row.phase_id) {
          at(
            'milestone_id',
            'MILESTONE_PHASE_MISMATCH',
            `${row.row_no}행: Milestone이 해당 Phase 소속이 아닙니다.`,
          )
        }
      }
      // `?? ''` 는 필수다 — 회색 행 추가(`POST .../items`)가 title/deliverable 이 null 인
      // 행을 만드는 정상 진입점이고, 검증은 바로 그런 행을 잡으라고 있는 것이다.
      // `row.title.trim()` 로 두면 갓 추가한 행에서 TITLE_REQUIRED 대신 크래시가 난다.
      if (!(row.title ?? '').trim()) {
        at('title', 'TITLE_REQUIRED', `${row.row_no}행: Key Action Item이 비어 있습니다.`)
      }
      if (!(row.deliverable ?? '').trim()) {
        at('deliverable', 'DELIVERABLE_REQUIRED', `${row.row_no}행: Deliverable이 비어 있습니다.`)
      }
      if (row.documents.length === 0) {
        at('documents', 'DOCUMENT_REQUIRED', `${row.row_no}행: 관련 문서가 1개 이상 필요합니다.`)
      }
      if (row.owners.length === 0) {
        at('owners', 'OWNER_REQUIRED', `${row.row_no}행: Owner가 지정되지 않았습니다.`)
      }

      const inactiveDoc = row.documents.find(
        (d) => !this.documents.find((t) => t.id === d.id)?.is_active,
      )
      if (inactiveDoc) {
        at(
          'documents',
          'INACTIVE_REFERENCE',
          `${row.row_no}행: 비활성 문서 '${inactiveDoc.name}'를 참조하고 있습니다.`,
        )
      }
      const inactiveOwner = row.owners.find(
        (o) => !this.owners.find((t) => t.id === o.id)?.is_active,
      )
      if (inactiveOwner) {
        at(
          'owners',
          'INACTIVE_REFERENCE',
          `${row.row_no}행: 비활성 Owner '${inactiveOwner.name}'를 참조하고 있습니다.`,
        )
      }
    }

    errors.push(...this.contiguityErrors(items))
    errors.push(...this.sequenceGapErrors(items))

    const used = new Set(items.map((r) => r.phase_id).filter((id): id is number => id != null))
    for (const phase of this.phases) {
      if (phase.scope === container.scope && phase.is_active && !used.has(phase.id)) {
        warnings.push({
          code: 'ORPHAN_PHASE',
          level: 'warning',
          phase_id: phase.id,
          message: `Phase '${phase.name}'에 속한 항목이 없습니다.`,
        })
      }
    }

    return { valid: errors.length === 0, errors, warnings }
  }

  /**
   * V4 / V5 — a block that reappears after another block has intervened.
   *
   * **Unassigned rows are transparent** (`plan.md` §0.2.1): `P0 P0 [gray] P0` is one block
   * with a gray row parked inside it, not a violation. Skipping them without touching
   * `prev` is the whole of that rule, and it is what makes a gray row droppable anywhere.
   * The two levels are scanned independently, so a row with a phase but no milestone is
   * opaque above and transparent below.
   */
  contiguityErrors(items: WpItem[]): ValidationIssue[] {
    const out: ValidationIssue[] = []
    const seenPhase = new Set<number>()
    const seenMs = new Set<number>()
    let prevPhase: number | undefined
    let prevMs: number | undefined

    for (const row of items) {
      if (row.phase_id != null && row.phase_id !== prevPhase) {
        if (seenPhase.has(row.phase_id)) {
          out.push({
            code: 'PHASE_NOT_CONTIGUOUS',
            level: 'error',
            item_id: row.id,
            row_no: row.row_no,
            field: 'phase_id',
            message: `Phase ${row.phase_no} 블록이 연속되지 않습니다. (${row.row_no}행)`,
          })
        }
        seenPhase.add(row.phase_id)
        prevPhase = row.phase_id
      }
      if (row.milestone_id != null && row.milestone_id !== prevMs) {
        if (seenMs.has(row.milestone_id)) {
          out.push({
            code: 'MILESTONE_NOT_CONTIGUOUS',
            level: 'error',
            item_id: row.id,
            row_no: row.row_no,
            field: 'milestone_id',
            message: `Milestone ${row.milestone_display ?? ''} 블록이 연속되지 않습니다. (${row.row_no}행)`,
          })
        }
        seenMs.add(row.milestone_id)
        prevMs = row.milestone_id
      }
    }
    return out
  }

  /**
   * V6 / V7 — gaps in the derived numbering.
   *
   * Cannot fire while numbering is derived from first-appearance order, but it is cheap
   * insurance against a future change that starts persisting seq_no independently.
   */
  private sequenceGapErrors(items: WpItem[]): ValidationIssue[] {
    const out: ValidationIssue[] = []
    const phaseNos = [
      ...new Set(items.map((r) => r.phase_no).filter((n): n is number => n != null)),
    ]
    phaseNos.sort((a, b) => a - b)
    for (let i = 1; i < phaseNos.length; i++) {
      if (phaseNos[i]! !== phaseNos[i - 1]! + 1) {
        out.push({
          code: 'PHASE_SEQ_GAP',
          level: 'error',
          field: 'phase_id',
          message: `Phase 번호가 연속되지 않습니다: ${phaseNos.join(', ')}`,
        })
        break
      }
    }
    return out
  }

  // ─────────────────────────────────────────────────── master data

  /** Every row belonging to a scope, across all of a template's versions. */
  private rowsOfScope(scope: MasterScope): StoredItem[] {
    if (scope.kind === 'project') return this.items.get(scope.projectId) ?? []
    return this.versions
      .filter((v) => v.template_id === scope.templateId)
      .flatMap((v) => this.items.get(v.id) ?? [])
  }

  private strip<T extends { scope: ScopeKey }>(row: T): Omit<T, 'scope'> {
    const { scope: _scope, ...rest } = row
    return rest
  }

  listOwners(scope: MasterScope): WpOwner[] {
    const key = MockBackend.key(scope)
    return this.owners
      .filter((o) => o.scope === key)
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((o) => this.strip(o))
  }

  upsertOwner(scope: MasterScope, body: Partial<WpOwner>, id?: number): WpOwner {
    const key = MockBackend.key(scope)
    if (id != null) {
      const found = this.owners.find((o) => o.id === id && o.scope === key)
      if (!found) throw new MockHttpError(404, 'Owner를 찾을 수 없습니다.')
      Object.assign(found, body)
      return this.strip(found)
    }
    const created: StoredOwner = {
      id: this.nextId(),
      scope: key,
      name: body.name ?? '',
      sort_order: body.sort_order ?? this.listOwners(scope).length + 1,
      is_active: body.is_active ?? true,
    }
    this.owners.push(created)
    return this.strip(created)
  }

  deleteOwner(scope: MasterScope, id: number) {
    const usage = this.rowsOfScope(scope).filter((r) => r.owner_ids.includes(id)).length
    if (usage > 0) {
      const found = this.owners.find((o) => o.id === id)
      if (found) found.is_active = false
      return {
        deleted: false,
        deactivated: true,
        usage_count: usage,
        message: `${usage}개 항목에서 사용 중이라 비활성 처리했습니다.`,
      }
    }
    this.owners = this.owners.filter((o) => o.id !== id)
    return { deleted: true, deactivated: false, usage_count: 0 }
  }

  listPhases(scope: MasterScope): WpPhase[] {
    const key = MockBackend.key(scope)
    return this.phases
      .filter((p) => p.scope === key)
      .sort((a, b) => a.seq_no - b.seq_no)
      .map((p) => this.strip(p))
  }

  upsertPhase(scope: MasterScope, body: Partial<WpPhase>, id?: number): WpPhase {
    const key = MockBackend.key(scope)
    if (id != null) {
      const found = this.phases.find((p) => p.id === id && p.scope === key)
      if (!found) throw new MockHttpError(404, 'Phase를 찾을 수 없습니다.')
      Object.assign(found, body)
      return this.strip(found)
    }
    const created: StoredPhase = {
      id: this.nextId(),
      scope: key,
      name: body.name ?? '',
      seq_no: body.seq_no ?? this.listPhases(scope).length,
      is_active: body.is_active ?? true,
    }
    this.phases.push(created)
    return this.strip(created)
  }

  deletePhase(scope: MasterScope, id: number) {
    const usage = this.rowsOfScope(scope).filter((r) => r.phase_id === id).length
    if (usage > 0) {
      const found = this.phases.find((p) => p.id === id)
      if (found) found.is_active = false
      return {
        deleted: false,
        deactivated: true,
        usage_count: usage,
        message: `${usage}개 항목에서 사용 중이라 비활성 처리했습니다.`,
      }
    }
    this.phases = this.phases.filter((p) => p.id !== id)
    this.milestones = this.milestones.filter((m) => m.phase_id !== id)
    return { deleted: true, deactivated: false, usage_count: 0 }
  }

  listMilestones(scope: MasterScope): WpMilestone[] {
    const key = MockBackend.key(scope)
    return this.milestones.filter((m) => m.scope === key).map((m) => this.strip(m))
  }

  upsertMilestone(scope: MasterScope, body: Partial<WpMilestone>, id?: number): WpMilestone {
    const key = MockBackend.key(scope)
    if (id != null) {
      const found = this.milestones.find((m) => m.id === id && m.scope === key)
      if (!found) throw new MockHttpError(404, 'Milestone을 찾을 수 없습니다.')

      /*
       * Re-parenting an in-use milestone is a 409, not an edit.
       *
       * Rows in an already-PUBLISHED version point at this milestone; moving it under a
       * different phase would make those rows fail V3 (`MILESTONE_PHASE_MISMATCH`)
       * retroactively — corrupting immutable data through a master-data screen. The server
       * refuses with the usage count, and the master screen exposes exactly this edit, so
       * without the same guard here the mock green-lights a UI action that 409s live.
       */
      if (body.phase_id != null && body.phase_id !== found.phase_id) {
        const usage = this.rowsOfScope(scope).filter((r) => r.milestone_id === id).length
        if (usage > 0) {
          throw new MockHttpError(
            409,
            `${usage}개 항목에서 사용 중인 Milestone 은 다른 Phase 로 옮길 수 없습니다.`,
            { code: 'MILESTONE_IN_USE', usage_count: usage },
          )
        }
      }

      Object.assign(found, body)
      return this.strip(found)
    }
    const created: StoredMilestone = {
      id: this.nextId(),
      scope: key,
      phase_id: body.phase_id!,
      name: body.name ?? '',
      seq_no: body.seq_no ?? 0,
      is_active: body.is_active ?? true,
    }
    this.milestones.push(created)
    return this.strip(created)
  }

  deleteMilestone(scope: MasterScope, id: number) {
    const usage = this.rowsOfScope(scope).filter((r) => r.milestone_id === id).length
    if (usage > 0) {
      const found = this.milestones.find((m) => m.id === id)
      if (found) found.is_active = false
      return {
        deleted: false,
        deactivated: true,
        usage_count: usage,
        message: `${usage}개 항목에서 사용 중이라 비활성 처리했습니다.`,
      }
    }
    this.milestones = this.milestones.filter((m) => m.id !== id)
    return { deleted: true, deactivated: false, usage_count: 0 }
  }
}

/**
 * An error shaped like the one axios throws, not a bare `Error`.
 *
 * The mock implements `WpApiClient` directly and so never goes through axios. That left
 * `unwrapValidationFailure()` and `describeApiError()` — the two functions that exist
 * *because* domain errors arrive as `{ detail: { code, message } }` and publish failure is
 * a 422 — completely unexercised by the suite. The envelope has already changed shape once
 * during this project (`detail.detail` → flat `detail`); a repeat would break publish
 * failure UX with the gate green. So the stand-in reproduces the transport, including the
 * `response.data.detail` envelope.
 */
export class MockHttpError extends Error {
  readonly response: { status: number; data: { detail: Record<string, unknown> } }

  constructor(
    readonly status: number,
    message: string,
    detail: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'MockHttpError'
    this.response = {
      status,
      data: { detail: { code: 'ERROR', ...detail, message } },
    }
  }
}
