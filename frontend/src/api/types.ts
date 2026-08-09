/**
 * Wire types for the Work Package API (`plan.md` §4.2–4.3).
 *
 * Field names are snake_case because they mirror the server payload verbatim — no
 * camelCase remapping layer, so a payload change surfaces as a type error rather than
 * as a silently-undefined field.
 */

export type VersionStatus = 'DRAFT' | 'PUBLISHED' | 'ARCHIVED'

export type ItemStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'DONE' | 'HOLD' | 'NA'

export const ITEM_STATUS_LABEL: Record<ItemStatus, string> = {
  NOT_STARTED: '진행전',
  IN_PROGRESS: '진행중',
  DONE: '완료',
  HOLD: '보류',
  NA: '해당없음',
}

export const VERSION_STATUS_LABEL: Record<VersionStatus, string> = {
  DRAFT: '작성중',
  PUBLISHED: '발행됨',
  ARCHIVED: '보관됨',
}

/**
 * Which container a row operation addresses — `plan.md` §0 / §4.2.
 *
 * The two tiers run the *same* grid over different containers: a template's DRAFT version,
 * or a project (which has no versions at all). Every row endpoint therefore takes a scope
 * rather than a bare id, and the two URL families fall out of it:
 *
 *   rows    `/versions/{versionId}/items…`  │  `/projects/{projectId}/items…`
 *   masters `/templates/{templateId}/…`     │  `/projects/{projectId}/…`
 *
 * A template scope carries **both** ids because those two bases diverge: rows belong to
 * one version, but phases/milestones/owners belong to the template across all of them.
 */
export type BoardScope =
  | { kind: 'template'; templateId: number; versionId: number }
  | { kind: 'project'; projectId: number }

/**
 * Who owns a set of phases / milestones / owners.
 *
 * Deliberately *narrower* than {@link BoardScope}: master data belongs to a template
 * across all of its versions, so naming a version here would be meaningless — and a caller
 * that only has a template id (one with no version yet) would have to invent one. Any
 * `BoardScope` is assignable to this, so the row layer can pass its scope straight through.
 */
export type MasterScope =
  | { kind: 'template'; templateId: number }
  | { kind: 'project'; projectId: number }

/**
 * A central WP template — the 기준 데이터 tier (`plan.md` §0.1).
 *
 * No `maker_id`: templates are central and maker-agnostic. Makers only ever appear on
 * {@link WpProject}.
 */
export interface WpTemplate {
  id: number
  code: string
  name: string
  description: string | null
  phase_start_no: number
  is_active: boolean
  created_at?: string | null
  updated_at?: string | null
}

/*
 * There is deliberately **no `published_version_id`** here.
 *
 * The obvious denormalisation, and the server does not send it — `check:live` caught the
 * client inventing it, which made the project-create dialog filter every template out and
 * report "발행된 기준 포맷이 없습니다" against a perfectly well-stocked server. Whether a
 * template can seed a project is answered by asking `listVersions` for a PUBLISHED one.
 */

/**
 * A maker's project — a snapshot of one published template version (`plan.md` §0.1).
 *
 * There is no version chain here on purpose: creation *is* the commit, and everything
 * afterwards is direct editing. Re-publishing the source template does not propagate;
 * `template_version_id` records which snapshot this was taken from and nothing more.
 */
export interface WpProject {
  id: number
  maker_id: number
  /**
   * Filled in only when the host injected a `MakerResolver` (root `INTEGRATION.md` §2).
   *
   * Never required. It is the **second** display source, behind the `makerName` prop —
   * naming makers is the host's job either way, and this is the host's own resolver
   * answering through the API instead of through a prop. Falling back to it before
   * `설비사 #{id}` is what keeps a host that passes no prop (or passes it late) from
   * showing a raw id next to a perfectly well-named maker.
   */
  maker_name?: string | null
  name: string
  description: string | null
  /**
   * Which template version this project was copied from. **`source_*`, not `template_*`** —
   * the names the server actually uses, and the past tense is the point: this records the
   * snapshot's origin and creates no live link. Re-publishing that template changes nothing
   * here.
   *
   * Nullable because a project can outlive the template it came from.
   */
  source_template_id: number | null
  source_version_id: number | null
  /**
   * Version number of the published format this project was copied from (`plan.md` §0.6).
   *
   * Display only, and **null-safe**: a project can outlive the version it came from, and the
   * header simply omits the badge rather than inventing a `v?`.
   */
  source_version_number?: number | null
  /** Snapshotted at creation — a later template edit must not renumber a live project. */
  phase_start_no: number
  is_active: boolean
  created_by?: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ProjectDetail {
  project: WpProject
  items: WpItem[]
}

/**
 * Body of `POST /api/v1/projects`.
 *
 * Note the asymmetry with {@link WpProject}: the *request* names the template
 * (`template_id`), the *response* records where the copy came from
 * (`source_template_id`). Both are the server's own names.
 */
export interface ProjectCreatePayload {
  maker_id: number | string
  name: string
  description?: string | null
  template_id: number
  /** Defaults to the template's newest PUBLISHED version. */
  template_version_id?: number | null
}

export interface WpVersion {
  id: number
  template_id: number
  version_number: number
  status: VersionStatus
  source_version_id: number | null
  notes: string | null
  published_at: string | null
  archived_at: string | null
  created_by: string | null
  published_by: string | null
  created_at: string | null
  updated_at: string | null
  /** Server's own verdict on editability. DRAFT only. */
  is_editable: boolean
}

/**
 * A document as it appears on a board row (`plan.md` §0.5.10).
 *
 * `no` is the **derived display number**, renumbered by every apply the same way phase and
 * milestone numbers are. The circled-marker `code` (①~⑤) is gone along with the global
 * document table: a code that had to be typed by hand could disagree with position, and
 * position is what the user actually reorders.
 */
/**
 * The documents a row should actually show — the off ones are dropped (`plan.md` §0.5.10).
 *
 * One predicate, used by both the cell renderer and the cell's `valueGetter`. They had the
 * filter written out twice; deleting it from the value copy failed nothing, because the value
 * has had no visible consumer since CSV export was removed (§0.5.7). Two copies of a rule
 * where only one is covered is how the covered one ends up alone.
 */
export const visibleDocuments = <T extends { no: number | null }>(documents: readonly T[]): T[] =>
  documents.filter((d) => d.no != null)

export interface DocumentRef {
  id: number
  /**
   * Display number — **1..N over the *used* documents only** (`plan.md` §0.5.10 정밀화).
   *
   * `null` when the document is switched off: an unused document keeps its place in the list
   * and its links, but takes no number, so turning one off renumbers everything after it
   * without leaving a hole. That is why this is nullable rather than 0 — there is no
   * "document zero", and a sentinel would eventually get printed.
   */
  no: number | null
  name: string
}

export interface OwnerRef {
  id: number
  name: string
}

/**
 * One board row.
 *
 * `is_*_block_start/end` and `can_create_*` are **computed by the server** and consumed
 * as-is (`plan.md` §4.3). The cell editors must never re-derive them: the contiguity
 * rule has to live in exactly one place.
 */
export interface WpItem {
  id: number
  sort_order: number
  row_no: number

  phase_id: number | null
  phase_no: number | null
  phase_name: string | null
  phase_display: string | null

  milestone_id: number | null
  milestone_no: number | null
  milestone_name?: string | null
  /** `0.1` — the number alone, without the name. */
  milestone_no_display?: string | null
  milestone_display: string | null

  is_phase_block_start: boolean
  is_phase_block_end: boolean
  is_milestone_block_start: boolean
  is_milestone_block_end: boolean
  can_create_phase: boolean
  can_create_milestone: boolean

  /**
   * 서버는 **null 을 보낼 수 있다** (`ItemOut.title: str | None`). `wp_items.title` 이
   * `TEXT NULL` 이고, 빈 행 추가(`POST .../items`)가 title/deliverable 이 비어 있는
   * 행을 만드는 것이 정상 진입점이기 때문이다.
   *
   * 문자열 메서드를 바로 부르지 말 것 — `row.title.trim()` 은 갓 추가한 행에서
   * 터진다. 표시·편집 경로는 `String(x ?? '')` 를 거친다.
   */
  title: string | null
  deliverable: string | null
  /**
   * 대시보드 카드에 실리는 key action 요약 (`plan.md` §0.5). `VARCHAR(60) NULL`.
   *
   * Distinct from `title` on purpose: the card is a few words wide, and truncating a
   * sentence produced labels nobody could scan. Falls back to `deliverable`, then to the
   * head of `title` — see `dashboardText()`.
   */
  dash_label: string | null
  gate_code: string | null

  documents: DocumentRef[]
  owners: OwnerRef[]

  status: ItemStatus
  completion_date: string | null
  origin: 'INHERITED' | 'ADDED'
}

export interface VersionDetail {
  version: WpVersion
  items: WpItem[]
}

/**
 * `POST .../insert-below`, `.../reorder` and `DELETE .../items/{id}` answer with the
 * fully recomputed list. `PUT .../items` and `POST .../publish` answer with
 * {@link VersionDetail} instead — the version row can change on those paths.
 */
export interface ItemsResponse {
  items: WpItem[]
}

/*
 * Master rows carry no owning-scope id.
 *
 * They are always fetched through a scoped URL (`/templates/{id}/phases` or
 * `/projects/{id}/phases`), so the scope is already known to whoever asked, and a project's
 * phases are *copies* rather than references to the template's. Declaring an owner id here
 * would invite client-side filtering that duplicates what the URL already decided — and
 * would have to guess whether the server calls it `template_id` or `project_id`.
 */
export interface WpPhase {
  id: number
  name: string
  seq_no: number
  is_active: boolean
  /** `Phase 0. Pre-Infrastructure Setup`, composed server-side. */
  display?: string | null
}

export interface WpMilestone {
  id: number
  phase_id: number
  name: string
  seq_no: number
  is_active: boolean
}

export interface WpOwner {
  id: number
  name: string
  sort_order: number
  is_active: boolean
}

/**
 * A **template-owned** document (`plan.md` §0.5.10).
 *
 * `wp_document_types` — the global master — is gone. Documents now follow the same scope
 * rule as Phase, Milestone and Owner: the format owns them, a project gets copies at
 * creation, and the two are unrelated afterwards. That is why there is no global-scope
 * warning banner anywhere any more: there is no global scope left to warn about.
 */
export interface TemplateDocument {
  id: number
  name: string
  /**
   * **The only order field on the wire** (`plan.md` §0.5.10 "문서 목록 GET 필드 확정").
   *
   * The derived display number, not the stored position — the server does not send
   * `sort_order` at all. On a template every document is used, so this is 1..N contiguous;
   * on a project it is 1..N over the **used** subset and `null` for the rest.
   *
   * The mock used to emit `sort_order` here. `npm run check` stayed green because both sides
   * of it agreed with each other, and only the live run disagreed — the same failure shape
   * `plan.md` §0.3 records, where a stand-in that is *nearly* the server is worse than none.
   */
  no: number | null
  is_active: boolean
}

export interface TemplateDocumentsResponse {
  documents: TemplateDocument[]
}

/**
 * Body of `POST /versions/{vid}/documents/apply` — the **final state**, like `phases/apply`.
 *
 * Same contract as §0.4's: `documents` lists everything that should survive in the order it
 * should appear, `deleted_ids` names the rest, and a payload whose two lists do not add up to
 * exactly what the server has is a 422. A forgotten id must not read as a deletion.
 */
export interface TemplateDocumentsApplyPayload {
  documents: { id: number | null; name: string }[]
  deleted_ids: number[]
}

export type ValidationField =
  | 'phase_id'
  | 'milestone_id'
  | 'title'
  | 'deliverable'
  | 'documents'
  | 'owners'
  | null

/**
 * One validation finding (`plan.md` §2.5).
 *
 * `code` is intentionally a plain `string`, not a union: the server may add codes — it
 * already added `ORPHAN_MILESTONE` beyond §2.5's table — and warnings never block a
 * publish, so an unrecognised code must render, not throw.
 */
export interface ValidationIssue {
  code: string
  level: 'error' | 'warning'
  item_id?: number | null
  row_no?: number | null
  phase_id?: number | null
  milestone_id?: number | null
  field?: ValidationField
  message: string
}

export interface ValidationResult {
  valid: boolean
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface PublishResult extends ValidationResult {
  version?: WpVersion
}

/**
 * Payload for 임시저장 — a whole-list replace (`plan.md` §4.2, bulk replace).
 *
 * **No `sort_order`.** Array position is authoritative; sending both invites the two to
 * disagree and the server answers 400.
 */
export interface ItemSavePayload {
  id: number | null
  phase_id: number | null
  milestone_id: number | null
  /** 백엔드 `ItemSaveIn.title: str | None` — 임시저장은 §2.5 에 따라 무검증이므로 null 이 정상이다. */
  title: string | null
  deliverable: string | null
  /** `plan.md` §0.5. Never validated — an empty dashboard label is legal on both tiers. */
  dash_label: string | null
  gate_code: string | null
  document_ids: number[]
  owner_ids: number[]
  status: ItemStatus
  completion_date: string | null
}

/**
 * One row of the Phase/Milestone 관리 팝업 (`plan.md` §0.4).
 *
 * `id` is null for a row the user added in the popup. Order is the payload's array order,
 * and that array order *is* the board's block order — the server rearranges blocks to match
 * and first-appearance renumbering (§2.2) derives the numbers from there. Nothing anywhere
 * assigns a number directly.
 */
export interface StructureEntry {
  id: number | null
  name: string
}

/**
 * Body of `POST .../phases/apply` — the popup's **final state**, not a diff.
 *
 * `phases` lists every phase that should survive, existing and new, in the order they
 * should appear. `deleted_ids` names the rest explicitly, and the server rejects (422) a
 * payload whose two lists do not add up to exactly the phases it already has: a partial
 * list would otherwise read as "delete everything I forgot to mention".
 *
 * `anchor_item_id` is the 회색 행 that opened the popup from its Phase cell. It becomes the
 * new phase's first row, which is why exactly one entry may be new when it is present —
 * a phase with no rows has no first-appearance and therefore no number (§0.4).
 */
export interface PhasesApplyPayload {
  phases: StructureEntry[]
  deleted_ids: number[]
  anchor_item_id?: number | null
}

/** Same shape one level down; the owning phase is in the URL. */
export interface MilestonesApplyPayload {
  milestones: StructureEntry[]
  deleted_ids: number[]
  anchor_item_id?: number | null
}

/**
 * Answer to either `apply` — the **whole board**, recomputed (`plan.md` §0.4).
 *
 * All three lists are required. `items` is the ordinary row payload, numbering and boundary
 * flags included; the two master lists come with it so the caller can read back the id of a
 * phase or milestone it just created without a second round trip, and so the cell editors
 * never offer a list that disagrees with the board next to them.
 */
export interface BoardApplyResponse extends ItemsResponse {
  phases: WpPhase[]
  milestones: WpMilestone[]
}

/**
 * Payload for `POST /versions/{vid}/items/reorder` — **position only**.
 *
 * Membership is not accepted here, and neither is `moved_item_id`; the server no longer
 * accepts the latter at all. Rows keep the phase/milestone they already have and only
 * change slots, which is the whole of the operation (`plan.md` §2.2, §4.2).
 *
 * The re-inheritance this endpoint used to perform is what made a drag across a phase
 * boundary silently reclassify the row. Removing it also removed the machinery that
 * decided *which* row to re-inherit — an LIS over the two orderings whose minimal answer
 * left other rows holding stale membership, fragmenting 12.86% of arbitrary permutations
 * on a six-row board. Neither the server nor this client has to identify the moved row any
 * more, so neither can get it wrong.
 */
export interface ReorderRequest {
  item_ids: number[]
}

/**
 * Payload for `PATCH /versions/{vid}/items/{iid}/membership` — the §2.3 cell edit.
 *
 * The server relocates the row to keep blocks contiguous and validates the result; a 422
 * saves nothing. The client does not compute the destination.
 */
export interface MembershipPayload {
  phase_id: number | null
  milestone_id: number | null
}

/**
 * Payload for `POST /versions/{vid}/items/{iid}/create-phase` (and `create-milestone`).
 *
 * The anchor row is in the path, not the body, and there is no insert position: the
 * anchor holds its slot and only its `phase_id` changes, so which side the new block
 * lands on follows from which edge the anchor sat on. Create + assign + renumber happen
 * in one transaction, so a failure cannot orphan a Phase in master data.
 */
export interface CreateFromRowPayload {
  name: string
}

/* ──────────────────── 프로젝트별 문서 링크·상태 (`plan.md` §0.5-4) ──────────────────── */

/**
 * 작성 상태 — the *document's* own progress, unrelated to {@link ItemStatus}.
 *
 * Deliberately a separate union with its own labels: a board row's 진행중 and a document's
 * 작성중 mean different things, and merging them would let a status meant for one leak into
 * the other's selector.
 */
export type DocWriteStatus = 'NOT_WRITTEN' | 'WRITING' | 'DONE'

export const DOC_WRITE_STATUS_LABEL: Record<DocWriteStatus, string> = {
  NOT_WRITTEN: '작성전',
  WRITING: '작성중',
  DONE: '완료',
}

/**
 * One row of the project's 문서 설정 screen (`plan.md` §0.5-4).
 *
 * `code` and `name` come from the **global** definition and are read-only here; only
 * `is_used`, `link_url` and `doc_status` belong to the project. The server LEFT JOINs, so a
 * project with no stored row still gets one of these with the defaults (사용=true, 작성전,
 * link null) — absence of a row is not absence of a document.
 */
export interface ProjectDocument {
  id: number
  name: string
  /**
   * Derived display number — 1..N over the **used** documents, `null` when 사용 is off.
   * As on {@link TemplateDocument}, `sort_order` is not on the wire.
   */
  no: number | null
  is_used: boolean
  /** 문서 링크. Nullable **regardless of `doc_status`** — 완료 without a link is legal. */
  link_url: string | null
  doc_status: DocWriteStatus
}

export interface ProjectDocumentsResponse {
  documents: ProjectDocument[]
  /**
   * The recomputed rows, present on **writes**.
   *
   * Deleting a document unlinks it from every item that referenced it (§0.5.10 cascade), so
   * the grid would otherwise keep rendering a document that no longer exists. Absent on a
   * plain read, where nothing changed.
   */
  items?: WpItem[]
}

/**
 * Body of `PUT /projects/{pid}/documents` (`plan.md` §0.5.10).
 *
 * **Array order becomes `sort_order`**, and `deleted_ids` names what goes — the same
 * final-state shape as the template apply, so the 문서 등록 탭 and the cell popup's management
 * half can share one path. `id: null` is a new project-local document.
 */
export interface ProjectDocumentSavePayload {
  id: number | null
  name: string
  is_used: boolean
  link_url: string | null
  doc_status: DocWriteStatus
}

export interface ProjectDocumentsApplyPayload {
  documents: ProjectDocumentSavePayload[]
  deleted_ids: number[]
}

/* ─────────────────── 프로젝트 주요 링크 (`plan.md` §0.5.5) ─────────────────── */

/**
 * One row of the 주요 링크 table — a Confluence page, a cloud file, anything with a URL.
 *
 * `sort_order` is **server-assigned from array position** on save, exactly like the board's
 * rows (§4.2): sending both an order field and an array order invites the two to disagree.
 * It comes back on read so the client can render in order without re-sorting.
 */
export interface ProjectLink {
  id: number
  description: string
  url: string
  sort_order: number
}

export interface ProjectLinksResponse {
  links: ProjectLink[]
}

/** Body row of `PUT /projects/{pid}/links`. `id: null` is a new row; array order is the order. */
export interface ProjectLinkSavePayload {
  id: number | null
  description: string
  url: string
}

/**
 * The one URL rule, shared by the grid's cell validation and its save guard (`plan.md`
 * §0.5.5). The server enforces the same thing with a 422 — this exists so the user learns it
 * while typing rather than on submit.
 */
export const LINK_URL_PATTERN = /^https?:\/\/\S+$/i

export const isValidLinkUrl = (url: string | null | undefined): boolean =>
  LINK_URL_PATTERN.test((url ?? '').trim())

/* ───────────────────────────── 전체 현황 (`plan.md` §0.5-3) ───────────────────────────── */

/** Status tallies of one project. Every key is present, zero included. */
export type StatusCounts = Record<ItemStatus, number>

/**
 * One minimap cell — a board row stripped to what a 10px square can show.
 *
 * Deliberately *not* a {@link WpItem}: the overview loads every active project at once, and
 * shipping full rows would mean tens of thousands of documents/owners nobody renders.
 *
 * `phase_seq` is the **display** number (§2.2 first-appearance), not `phases.seq_no`, so the
 * colour banding here matches what the project board shows. Null on an unassigned (gray)
 * row, which gets a colourless band.
 */
export interface OverviewItem {
  no: number
  status: ItemStatus
  phase_seq: number | null
  milestone_seq: number | null
  dash_label: string | null
  /**
   * The three fields the shared hover popover needs (`plan.md` §0.5-3, 2026-08-08).
   *
   * They were deliberately absent while the hover was a one-line tooltip; the popover shows
   * the same four facts the project dashboard's does, and a minimap that could only show a
   * caption would have been a second, poorer version of it.
   *
   * `owners` is **names**, not ids: nothing on this screen resolves an owner id, and the
   * overview spans projects whose owner tables are separate copies (`plan.md` §0.1).
   */
  title: string | null
  deliverable: string | null
  owners: string[]
}

/**
 * A document chip in the overview's ④ 문서 링크 area (`plan.md` §0.5-3b / §0.5-4).
 *
 * **Only `is_used` documents are sent**, which is why the flag itself is absent here: a
 * chip's presence *is* the flag, and carrying a `false` the client would have to filter out
 * invites one caller to forget.
 */
export interface OverviewDocument {
  id: number
  /** Derived display number over the used documents (§0.5.10). Replaces the circled `code`. */
  no: number
  name: string
  doc_status: DocWriteStatus
  link_url: string | null
}

export interface ProjectOverview {
  id: number
  name: string
  maker_id: number
  /**
   * Null whenever the host injected no `MakerResolver` — a **normal** state, not an error
   * (root `INTEGRATION.md` §2). The screen falls back to `설비사 #<id>`.
   */
  maker_name: string | null
  counts: StatusCounts
  /** `sort_order` 순. */
  items: OverviewItem[]
  /** 사용 체크된 문서만 (`plan.md` §0.5-4). */
  documents: OverviewDocument[]
}

/**
 * One 설비사 section of the overview (`plan.md` §0.6).
 *
 * **The server groups now.** This used to be a flat `projects` array that the client bucketed
 * by `maker_id`, and that could only ever show makers that already had a project — so a maker
 * ticked for display but not yet started was invisible, and there was nowhere to put the
 * "+ 프로젝트 추가" button that creates its first one. Grouping server-side also puts the
 * §0.6 display rule (설정행이 있으면 그 값, 없으면 active 프로젝트 유무) in one place instead
 * of splitting it across two.
 *
 * `projects` may legitimately be **empty**: a maker explicitly ticked for the overview gets a
 * section with an empty state rather than being dropped.
 */
export interface MakerOverviewGroup {
  maker_id: number
  /** Null when the host wired no `MakerResolver` — render `설비사 #<id>` (root §2.2). */
  name: string | null
  projects: ProjectOverview[]
}

export interface ProjectsOverviewResponse {
  makers: MakerOverviewGroup[]
}

/* ─────────────────────── 설비사 설정 (`plan.md` §0.6) ─────────────────────── */

/**
 * One row of the 설비사 설정 screen.
 *
 * `show_in_overview` is the **effective** value and `explicit` says where it came from:
 * `false` means no `wp_maker_settings` row exists and the value was derived from
 * `has_projects`. The screen shows both, because "checked" and "checked because it happens
 * to have projects" behave differently the moment the last project is archived.
 */
/**
 * A project as the 설비사 관리 screen sees it — **including the switched-off ones**.
 *
 * `is_active` is a display flag, not existence. The 전체 현황 draws only active projects, so
 * this list is the one place a project turned off can be found and turned back on. Nothing in
 * the UI deletes rows; that is an admin running `db/delete_project.py` by hand.
 */
export interface MakerProject {
  id: number
  name: string
  is_active: boolean
}

export interface MakerSetting {
  maker_id: number
  name: string | null
  show_in_overview: boolean
  explicit: boolean
  /** Whether it has any **active** project — the input to the auto display rule (§0.6-1). */
  has_projects: boolean
  /** Every project of this maker, active or not. Empty is normal. */
  projects: MakerProject[]
}

export interface MakersResponse {
  makers: MakerSetting[]
}

/** Body row of `PUT /api/v1/makers/settings` — an upsert. */
export interface MakerSettingPayload {
  maker_id: number
  show_in_overview: boolean
}

/** Body row of the same call's `projects` array — sets `wp_projects.is_active`. */
export interface MakerProjectVisibilityPayload {
  id: number
  is_active: boolean
}
