/* eslint-disable no-console */
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { MockBackend, MockHttpError } from '../mock/engine'
import { describeApiError, unwrapValidationFailure } from '../api/client'
import { canDragRow, isWithinBlockOrder } from '../composables/useBlockDrag'
import {
  buildDashboardLayout,
  buildOverviewGroups,
  dashboardText,
} from '../composables/useDashboard'
import { DASH_PHASE_COLORS, DASH_STATUS_STYLE, dashPhaseColor, ownerKind } from '../theme/dashboard'
import type {
  BoardScope,
  ItemSavePayload,
  ItemStatus,
  MasterScope,
  StructureEntry,
  WpItem,
} from '../api/types'

/**
 * Headless check of the grid's *behavioural* contract — the parts that are easy to get
 * wrong and impossible to eyeball: renumbering, block contiguity, the §2.3/§0.2 boundary
 * rules, the gray-row flow, the version state machine, publish validation, and the
 * template/project split of §0.1.
 *
 * DEV ONLY. Runs against {@link MockBackend}, which implements the same rules the FastAPI
 * service will. `npm run verify`.
 *
 * Output is ASCII on stdout (the Windows console mangles Korean) with the Korean
 * validation messages written to a UTF-8 report file instead.
 */

let passed = 0
let failed = 0
const report: string[] = []

function check(name: string, condition: boolean, detail?: unknown) {
  if (condition) {
    passed++
    console.log(`  PASS  ${name}`)
  } else {
    failed++
    console.log(`  FAIL  ${name}`)
    if (detail !== undefined) console.log(`        ${JSON.stringify(detail)}`)
  }
  report.push(`${condition ? 'PASS' : 'FAIL'}  ${name}`)
}

function section(title: string) {
  console.log(`\n${title}`)
  report.push(`\n## ${title}`)
}

/**
 * Runs one section's body and turns an **unexpected** throw into a reported failure.
 *
 * Without this, one `MockHttpError` escaping from a place the section did not expect it
 * kills the whole run: node prints a stack trace and every assertion after that point —
 * often the majority of the suite — silently never executes. That is exactly what three of
 * the six deliberate-break runs did before this was added, and a gate that dies instead of
 * reporting is barely better than one that cannot fail.
 */
function guard(body: () => void): void {
  try {
    body()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    check(`section did not throw unexpectedly :: ${message}`, false)
  }
}

/**
 * No block may reappear after another block has intervened — the invariant everything
 * protects.
 *
 * **Unassigned rows are skipped, not treated as a boundary** (`plan.md` §0.2.1). Reading
 * them as opaque would make `P0 P0 [gray] P0` look broken, which is precisely the
 * arrangement the gray row exists to allow.
 */
function isContiguous(items: WpItem[], key: 'phase_id' | 'milestone_id'): boolean {
  const seen = new Set<number>()
  let previous: number | undefined
  for (const row of items) {
    const value = row[key]
    if (value == null || value === previous) continue
    if (seen.has(value)) return false
    seen.add(value)
    previous = value
  }
  return true
}

const sequential = (items: WpItem[]) => items.every((row, i) => row.row_no === i + 1)

/**
 * "The board did not change" — asserted as two orthogonal facts, never as a row count and
 * never as "a toast appeared".
 *
 * {@link orderOf} is the full row order; {@link membershipOf} is every row's phase and
 * milestone, keyed by id and sorted so it is *independent* of order. A legal reorder moves
 * the first and leaves the second identical; the bug this file guards against — a drag
 * that silently reclassifies a row — moves both, while leaving the row count, the
 * numbering and the error handling all looking perfectly normal.
 */
const orderOf = (items: WpItem[]) => items.map((r) => r.id).join(',')
const membershipOf = (items: WpItem[]) =>
  [...items]
    .sort((a, b) => a.id - b.id)
    .map((r) => `${r.id}:${r.phase_id}:${r.milestone_id}`)
    .join('|')

/** A gray row: no phase, no milestone, droppable anywhere (`plan.md` §0.2). */
const isGray = (row: WpItem) => row.phase_id == null && row.milestone_id == null

function toPayload(items: WpItem[]): ItemSavePayload[] {
  // No `sort_order` — array position is authoritative (plan.md §4.2).
  return items.map((row) => ({
    id: row.id,
    phase_id: row.phase_id,
    milestone_id: row.milestone_id,
    title: row.title,
    deliverable: row.deliverable,
    dash_label: row.dash_label,
    gate_code: row.gate_code,
    document_ids: row.documents.map((d) => d.id),
    owner_ids: row.owners.map((o) => o.id),
    status: row.status,
    completion_date: row.completion_date,
  }))
}

/**
 * Mirrors the whole drag path, guard included — `WpGrid.onRowDragEnd` followed by
 * `createBoardStore.applyReorder`.
 *
 * Going through {@link isWithinBlockOrder} rather than straight to `backend.reorder` is
 * the point: it is the shipped rule, and a test that skipped it would be checking the
 * server's contiguity guard while claiming to check the drag.
 */
function dragRow(
  backend: MockBackend,
  scope: BoardScope,
  fromIndex: number,
  toIndex: number,
): { refused: boolean; refusedBy: 'grid' | 'server' | null; items: WpItem[] } {
  const items = backend.project(scope)
  const moved = items[fromIndex]!
  const rest = items.filter((_, i) => i !== fromIndex)
  rest.splice(toIndex, 0, moved)
  const orderedIds = rest.map((row) => row.id)

  // Refused in the grid: no request is made at all, so the board is untouched by
  // construction rather than by a rollback.
  if (!isWithinBlockOrder(items, orderedIds)) return { refused: true, refusedBy: 'grid', items }

  /*
   * A 422 here is caught and reported, not rethrown. Remove the guard above and the mock's
   * contiguity check starts throwing on the very first cross-block drag; letting that
   * escape would abort the whole run with a stack trace and skip every assertion after it.
   * A gate that dies instead of reporting is barely better than one that cannot fail —
   * these two lines are what make the deliberate-break check readable.
   */
  try {
    return { refused: false, refusedBy: null, items: backend.reorder(scope, orderedIds) }
  } catch (error) {
    if (!(error instanceof MockHttpError)) throw error
    return { refused: true, refusedBy: 'server', items: backend.project(scope) }
  }
}

/**
 * A fresh backend trimmed to `layout.length` rows, row `i` stamped with phase `layout[i]`
 * (`null` for a gray row).
 *
 * Small boards with hand-chosen block shapes, because the seed's 35 rows can only exhibit
 * the shapes the spreadsheet happened to contain.
 */
function makeBench(layout: (number | null)[]) {
  const backend = new MockBackend(1)
  const template = backend.listTemplates()[0]!
  const version = backend.listVersions(template.id).find((v) => v.status === 'DRAFT')!
  const scope = backend.versionScope(version.id)
  const phases = backend.listPhases({ kind: 'template', templateId: template.id })

  for (const extra of backend.project(scope).slice(layout.length)) {
    backend.deleteItem(scope, extra.id)
  }
  backend.saveItems(
    scope,
    backend.project(scope).map((row, i) => ({
      id: row.id,
      phase_id: layout[i] == null ? null : phases[layout[i]!]!.id,
      milestone_id: null,
      title: row.title,
      deliverable: row.deliverable,
      dash_label: row.dash_label,
      gate_code: null,
      document_ids: [],
      owner_ids: [],
      status: row.status,
      completion_date: null,
    })),
  )
  return { backend, scope, ids: backend.project(scope).map((r) => r.id) }
}

/**
 * The template's newest PUBLISHED version, asked of `listVersions`.
 *
 * Deliberately not read off the template row: `TemplateOut` has no `published_version_id`
 * and the client used to invent one. Resolving it the way the shipped code now does keeps
 * this suite from re-introducing the assumption `check:live` just caught.
 */
function publishedVersionId(backend: MockBackend, templateId: number): number | null {
  return backend.listVersions(templateId).find((v) => v.status === 'PUBLISHED')?.id ?? null
}

/**
 * A fresh backend whose rows are stamped with explicit `(phase, milestone)` pairs.
 *
 * {@link makeBench} leaves every milestone null, which is fine for phase-level questions
 * and useless for §0.3 placement — the bug it exists to catch is *milestone*-granular, and
 * a fixture with one milestone per phase cannot see it. `spec` is a list of
 * `[phaseIndex, milestoneIndexWithinThatPhase]`, or `null` for a gray row.
 */
function makeMilestoneBench(spec: ([number, number] | null)[]) {
  const backend = new MockBackend(1)
  const template = backend.listTemplates()[0]!
  const master = { kind: 'template' as const, templateId: template.id }
  const version = backend.listVersions(template.id).find((v) => v.status === 'DRAFT')!
  const scope = backend.versionScope(version.id)

  const phases = backend.listPhases(master)
  const milestonesOf = (phaseIndex: number) =>
    backend.listMilestones(master).filter((m) => m.phase_id === phases[phaseIndex]!.id)

  for (const extra of backend.project(scope).slice(spec.length)) {
    backend.deleteItem(scope, extra.id)
  }
  backend.saveItems(
    scope,
    backend.project(scope).map((row, i) => {
      const cell = spec[i]
      const phase = cell == null ? null : phases[cell[0]]!
      const milestone = cell == null ? null : milestonesOf(cell[0])[cell[1]]!
      return {
        id: row.id,
        phase_id: phase?.id ?? null,
        milestone_id: milestone?.id ?? null,
        title: row.title,
        deliverable: row.deliverable,
        dash_label: row.dash_label,
        gate_code: null,
        document_ids: [],
        owner_ids: [],
        status: row.status,
        completion_date: null,
      }
    }),
  )
  return {
    backend,
    scope,
    master,
    phases,
    milestonesOf,
    ids: backend.project(scope).map((r) => r.id),
  }
}

const masterScopeOf = (scope: BoardScope): MasterScope =>
  scope.kind === 'template'
    ? { kind: 'template', templateId: scope.templateId }
    : { kind: 'project', projectId: scope.projectId }

/**
 * The list the 관리 팝업 shows when it opens: the phases **with rows on this board**, in
 * first-appearance order.
 *
 * Deliberately the same construction `StructureManagerModal` uses, because that is what the
 * apply contract is fed in practice, and it is the set the server checks the payload
 * against. Two things it is *not*: not sorted by `seq_no` (that is the output of the last
 * renumber, and a phase no row uses carries a stale one), and not every phase in master data
 * (one with no rows has no first appearance, so no number and no place in an ordered list).
 */
function phasePlan(backend: MockBackend, scope: BoardScope): StructureEntry[] {
  const byId = new Map(backend.listPhases(masterScopeOf(scope)).map((p) => [p.id, p]))
  const order: number[] = []
  for (const row of backend.project(scope)) {
    if (row.phase_id != null && !order.includes(row.phase_id) && byId.has(row.phase_id)) {
      order.push(row.phase_id)
    }
  }
  return order.map((id) => ({ id, name: byId.get(id)!.name }))
}

/** Same, for the milestones of one phase. */
function milestonePlan(
  backend: MockBackend,
  scope: BoardScope,
  phaseId: number,
): StructureEntry[] {
  const byId = new Map(
    backend
      .listMilestones(masterScopeOf(scope))
      .filter((m) => m.phase_id === phaseId)
      .map((m) => [m.id, m]),
  )
  const order: number[] = []
  for (const row of backend.project(scope)) {
    if (row.phase_id !== phaseId) continue
    if (row.milestone_id != null && !order.includes(row.milestone_id) && byId.has(row.milestone_id)) {
      order.push(row.milestone_id)
    }
  }
  return order.map((id) => ({ id, name: byId.get(id)!.name }))
}

/** The 422 code a refused apply carried, or null. */
const codeOf = (error: MockHttpError | null) =>
  error == null ? null : String(error.response.data.detail.code ?? '')

/** Phase display numbers in board order, e.g. `0,0,1,1,2` — the thing apply rewrites. */
const phaseNos = (items: WpItem[]) => items.map((r) => r.phase_no).join(',')
/** `1.2`-style milestone labels, number only. */
const msNos = (items: WpItem[]) =>
  items.map((r) => (r.phase_no == null || r.milestone_no == null ? '-' : `${r.phase_no}.${r.milestone_no}`)).join(',')

function expectThrows(fn: () => unknown): MockHttpError | null {
  try {
    fn()
    return null
  } catch (error) {
    return error instanceof MockHttpError ? error : null
  }
}

// ─────────────────────────────────────────────────────────────── run

const backend = new MockBackend(1)
const template = backend.listTemplates()[0]!
const templateScope = { kind: 'template' as const, templateId: template.id }
const versions = backend.listVersions(template.id)
const draft = versions.find((v) => v.status === 'DRAFT')!
const scope = backend.versionScope(draft.id)

section('1. Seed / projection (plan.md 2.1)')
guard(() => {
  const items = backend.project(scope)
  check('35 rows imported from the spreadsheet', items.length === 35, items.length)
  check('row_no is 1..N', sequential(items))
  check(
    'phase display is composed, not stored',
    items[0]!.phase_display === 'Phase 0. Pre-Infrastructure Setup',
    items[0]!.phase_display,
  )
  check(
    'milestone major number is derived from the owning phase',
    items[0]!.milestone_display?.startsWith('0.1 ') === true &&
      items[34]!.milestone_display?.startsWith('3.4 ') === true,
    [items[0]!.milestone_display, items[34]!.milestone_display],
  )
  check('phases start at phase_start_no = 0', items[0]!.phase_no === 0)
  check('4 distinct phases', new Set(items.map((r) => r.phase_no)).size === 4)
  check('13 distinct milestones', new Set(items.map((r) => r.milestone_id)).size === 13)
})

section('2. Boundary flags (plan.md 2.3) — server-computed, consumed as-is')
guard(() => {
  const items = backend.project(scope)
  check('row 1 is a phase block start', items[0]!.is_phase_block_start)
  check('row 4 is a phase block end (Phase 0 has 4 rows)', items[3]!.is_phase_block_end)
  check('row 5 starts Phase 1', items[4]!.is_phase_block_start && items[4]!.phase_no === 1)
  check(
    'middle rows cannot create a phase',
    !items[1]!.can_create_phase && !items[2]!.can_create_phase,
  )
  check('edge rows can create a phase', items[0]!.can_create_phase && items[3]!.can_create_phase)
  check(
    'milestone edges are also phase edges',
    items[0]!.is_milestone_block_start && items[3]!.is_milestone_block_end,
  )
  check(
    'row 2 ends milestone 0.1 and so may create a milestone',
    items[1]!.is_milestone_block_end && items[1]!.can_create_milestone,
  )
})

section('3. Row add — both paths make an unassigned (gray) row (plan.md 0.2)')
guard(() => {
  const before = backend.project(scope)
  const anchor = before[1]! // middle of Phase 0 / milestone 0.1

  const afterInsert = backend.insertBelow(scope, anchor.id)
  const inserted = afterInsert[2]!
  check('one row added', afterInsert.length === before.length + 1)
  check('inserted directly below the anchor', afterInsert[1]!.id === anchor.id)
  check(
    'it inherits NOTHING — this is the §0.2 change',
    inserted.phase_id === null && inserted.milestone_id === null,
    [inserted.phase_id, inserted.milestone_id],
  )
  check('new row is marked ADDED', inserted.origin === 'ADDED')
  check('renumbered 1..N', sequential(afterInsert))

  /*
   * The gray row is sitting in the *middle* of Phase 0's first milestone block, which
   * under the old inheritance rule was the only place a new row could ever be. It must not
   * break anything, and the rows around it must not start looking like block edges — if
   * they did, `can_create_phase` would go true there and creating a phase would tear the
   * block in two.
   */
  check('a gray row mid-block does not break contiguity', isContiguous(afterInsert, 'phase_id'))
  check('…nor milestone contiguity', isContiguous(afterInsert, 'milestone_id'))
  check(
    'the row above it is still not a block end — gray rows are transparent',
    !afterInsert[1]!.is_phase_block_end && !afterInsert[1]!.can_create_phase,
  )
  check(
    'the row below it is still not a block start',
    !afterInsert[3]!.is_phase_block_start && !afterInsert[3]!.can_create_phase,
  )
  check(
    'and the gray row itself may NOT create a phase — both neighbours are Phase 0',
    !inserted.can_create_phase,
  )

  const afterAppend = backend.appendRow(scope)
  const appended = afterAppend[afterAppend.length - 1]!
  check('toolbar append also makes a gray row', appended.phase_id === null)
  check(
    'a gray row at the very end MAY create a phase — nothing below it to split',
    appended.can_create_phase,
  )

  backend.deleteItem(scope, inserted.id)
  backend.deleteItem(scope, appended.id)
  check('board restored for the sections below', backend.project(scope).length === 35)
})

section('4. Row drag — assigned rows stay in their block (plan.md 2.2)')
guard(() => {
  const before = backend.project(scope)
  const beforeOrder = orderOf(before)
  const beforeMembership = membershipOf(before)

  /*
   * The exact reproduction from plan.md §2.2: a Phase 0 row dropped deep inside Phase 2.
   * This used to succeed and silently rewrite the row's Phase.
   */
  const crossing = dragRow(backend, scope, 1, 20)
  const afterCrossing = backend.project(scope)
  check('a drag across a phase boundary is refused', crossing.refused)
  check(
    '…in the grid, before any request — not by the server afterwards',
    crossing.refusedBy === 'grid',
    crossing.refusedBy,
  )
  check('row order is unchanged', orderOf(afterCrossing) === beforeOrder)
  check(
    'every row still holds its own phase_id / milestone_id',
    membershipOf(afterCrossing) === beforeMembership,
  )

  const acrossMilestone = dragRow(backend, scope, 0, 3)
  check('a drag across a milestone boundary is refused too', acrossMilestone.refusedBy === 'grid')
  check('board still untouched', membershipOf(backend.project(scope)) === beforeMembership)

  // Phase 0 rows 3 and 4 share milestone 0.2 — swapping them is the legal gesture.
  const pair = before.filter((r) => r.phase_no === 0 && r.milestone_no === 2)
  check('setup: milestone 0.2 has two rows to swap', pair.length === 2, pair.length)
  const within = dragRow(backend, scope, 3, 2)
  check('a drag inside the block is accepted', !within.refused)
  check(
    'the swap is exactly the two adjacent ids, nothing else moved',
    orderOf(within.items) ===
      orderOf([before[0]!, before[1]!, before[3]!, before[2]!, ...before.slice(4)]),
  )
  check('and no row changed membership', membershipOf(within.items) === beforeMembership)
  check('renumbered 1..N', sequential(within.items))
  check('phase blocks still contiguous', isContiguous(within.items, 'phase_id'))
  check(
    'phase / milestone numbers are untouched — only positions moved',
    within.items.every(
      (row) => row.milestone_display === before.find((b) => b.id === row.id)!.milestone_display,
    ),
  )

  // Put the seed order back for the sections below.
  dragRow(backend, scope, 3, 2)
})

section('4b. Gray rows are the exception — droppable anywhere (plan.md 0.2.2)')
guard(() => {
  const seeded = backend.appendRow(scope)
  const gray = seeded[seeded.length - 1]!
  const assignedMembership = membershipOf(seeded.filter((r) => !isGray(r)))

  check('setup: one gray row at the end of a 4-phase board', isGray(gray) && seeded.length === 36)

  /*
   * The same drop that is refused for an assigned row — deep inside another phase's block
   * — is *accepted* for a gray row. That asymmetry is the whole of §0.2.2, and it is what
   * lets a user park a row at the exact seam they want before classifying it.
   */
  const intoPhase2 = dragRow(backend, scope, 35, 20)
  check('a gray row may be dropped in the middle of another phase block', !intoPhase2.refused)
  check('it went where it was dropped', intoPhase2.items[20]!.id === gray.id)
  check('the board is still contiguous — null is transparent', isContiguous(intoPhase2.items, 'phase_id'))
  check('…at the milestone level too', isContiguous(intoPhase2.items, 'milestone_id'))
  check(
    'and no assigned row was reclassified by the gray row passing through',
    membershipOf(intoPhase2.items.filter((r) => !isGray(r))) === assignedMembership,
  )
  check('the gray row is still gray', isGray(intoPhase2.items[20]!))

  // …and it can leave again, to a completely different block.
  const backToTop = dragRow(backend, scope, 20, 2)
  check('it can be moved again, anywhere', !backToTop.refused && backToTop.items[2]!.id === gray.id)
  check(
    'still contiguous, still nobody reclassified',
    isContiguous(backToTop.items, 'phase_id') &&
      membershipOf(backToTop.items.filter((r) => !isGray(r))) === assignedMembership,
  )

  check(
    'NEGATIVE CONTROL — the same drop of an ASSIGNED row is still refused',
    dragRow(backend, scope, 1, 21).refusedBy === 'grid',
  )

  backend.deleteItem(scope, gray.id)
})

section('4c. The drag handle is withheld only where dragging could do nothing')
guard(() => {
  const items = backend.project(scope)
  check(
    'a row with a neighbour in its own block keeps the handle',
    canDragRow(items, items[0]!) && canDragRow(items, items[1]!),
  )
  check('a row missing from the list never gets one', !canDragRow(items, undefined))

  const { backend: solo, scope: soloScope } = makeBench([0, 1, 1])
  const soloItems = solo.project(soloScope)
  check('the lone row of a block has no handle', !canDragRow(soloItems, soloItems[0]!))
  check(
    'its two-row neighbour block still does',
    canDragRow(soloItems, soloItems[1]!) && canDragRow(soloItems, soloItems[2]!),
  )

  /*
   * A gray row always has a handle, even when it is the only row of "its" block — it has
   * no block, so every position is legal for it. The handle rule is derived from the drop
   * rule (`canDragRow` asks `isWithinBlockOrder`), so the two cannot disagree; this checks
   * that the derivation actually produces the §0.2 answer.
   */
  const { backend: mixed, scope: mixedScope } = makeBench([0, null, 1, 1])
  const mixedItems = mixed.project(mixedScope)
  check('a gray row is draggable even though it is alone', canDragRow(mixedItems, mixedItems[1]!))
  check(
    'and the lone Phase 0 row above it is draggable too — it can slide past the gray row',
    canDragRow(mixedItems, mixedItems[0]!),
  )
  check(
    'NEGATIVE CONTROL — with no gray row, that same lone row has no handle',
    !canDragRow(solo.project(soloScope), solo.project(soloScope)[0]!),
  )
})

section('5. The seam scenario — a new Phase BETWEEN two existing ones (plan.md 0.2.5)')
guard(() => {
  /*
   * The thing the user actually asked for, end to end, exactly as the UI does it:
   *
   *   1. add a row              → it is gray
   *   2. drag it to the seam    → allowed, because gray rows go anywhere
   *   3. 새 Phase 생성           → allowed, because its neighbours are different phases
   *   4. renumbering            → the new phase lands *between* them, with no insert logic
   *
   * Every step is a separate assertion, so a regression says which one broke rather than
   * just "the scenario failed".
   */
  const { backend: seam, scope: seamScope } = makeBench([0, 0, 1, 1])
  const startNumbers = seam.project(seamScope).map((r) => r.phase_no)
  check('setup: two blocks, Phase 0 then Phase 1', startNumbers.join() === '0,0,1,1')

  const added = seam.appendRow(seamScope)
  const gray = added[added.length - 1]!
  check('step 1 — the added row is gray', isGray(gray))
  check(
    'appended at the end it could already create a phase — nothing below it to split',
    added[4]!.can_create_phase,
  )

  const moved = dragRow(seam, seamScope, 4, 2)
  check('step 2 — it may be dragged to the seam between the blocks', !moved.refused)
  check('it is sitting at the seam', moved.items[2]!.id === gray.id)

  const atSeam = moved.items[2]!
  check(
    'step 3 — 새 Phase 생성 is offered there, because the neighbours differ',
    atSeam.can_create_phase,
  )

  const created = seam.createPhaseFromRow(seamScope, gray.id, { name: '중간 신규 단계' })
  check('step 4 — the phase was created and assigned', created[2]!.phase_name === '중간 신규 단계')
  check(
    'and renumbering put it BETWEEN — 0, 0, 1, 2, 2',
    created.map((r) => r.phase_no).join() === '0,0,1,2,2',
    created.map((r) => r.phase_no),
  )
  check('the board is contiguous', isContiguous(created, 'phase_id'))
  check('phase numbers are gapless', new Set(created.map((r) => r.phase_no)).size === 3)
  check(
    'the two original blocks kept their own rows',
    created[0]!.phase_id === created[1]!.phase_id && created[3]!.phase_id === created[4]!.phase_id,
  )
  check('the new row has no milestone yet', created[2]!.milestone_id === null)
})

section('5b. …and the same creation is refused mid-block (plan.md 0.2.4)')
guard(() => {
  /*
   * The other half of the rule, and the one that makes it a rule rather than a permission:
   * a gray row parked *inside* one block may not start a phase there, because the block
   * would come out in two pieces. §2.3 used to say an unassigned row is always a boundary
   * and may therefore always create — true about boundaries, wrong about creation.
   */
  const { backend: mid, scope: midScope } = makeBench([0, 0, 0, 1])
  const added = mid.appendRow(midScope)
  const gray = added[added.length - 1]!
  const parked = dragRow(mid, midScope, 4, 1)
  check('setup: a gray row parked inside Phase 0', parked.items[1]!.id === gray.id)

  const anchor = parked.items[1]!
  check('the server refuses to offer creation there', !anchor.can_create_phase)

  const before = mid.project(midScope)
  const refusal = expectThrows(() => mid.createPhaseFromRow(midScope, gray.id, { name: '쪼개기' }))
  check('and refuses the call itself with a 422', refusal?.status === 422, refusal?.status)
  check(
    'the refusal names the reason, not just the rule',
    (refusal?.message ?? '').includes('쪼개집니다'),
    refusal?.message,
  )
  check(
    'nothing was created — a failure cannot orphan a Phase in master data',
    mid.listPhases(midScope).every((p) => p.name !== '쪼개기'),
  )
  const after = mid.project(midScope)
  check(
    'the board is untouched',
    orderOf(after) === orderOf(before) && membershipOf(after) === membershipOf(before),
  )

  // Move it one row down, to the seam, and the same call now succeeds — so the refusal was
  // about the position, not about gray rows.
  const atSeam = dragRow(mid, midScope, 1, 3)
  check('NEGATIVE CONTROL — moved to the seam, the very same call is allowed', !atSeam.refused)
  check('…and can_create_phase flips to true', atSeam.items[3]!.can_create_phase)
  const ok = mid.createPhaseFromRow(midScope, gray.id, { name: '쪼개기' })
  check('…and it really creates', ok[3]!.phase_name === '쪼개기')
})

section('6. Phase cell edit — the server relocates the row')
guard(() => {
  const items = backend.project(scope)
  const middle = items.find((r) => !r.is_phase_block_start && !r.is_phase_block_end)!
  const targetPhaseId = items.find((r) => r.phase_no === 3)!.phase_id!

  // The client sends membership only; it does not compute a destination.
  const after = backend.setMembership(scope, middle.id, {
    phase_id: targetPhaseId,
    milestone_id: null,
  })
  const moved = after.find((r) => r.id === middle.id)!
  const lastOfTarget = [...after].reverse().find((r) => r.phase_id === targetPhaseId)!
  check('row joined the target phase', moved.phase_id === targetPhaseId)
  check('server placed it at the end of that block', lastOfTarget.id === moved.id)
  check('source block stayed contiguous', isContiguous(after, 'phase_id'))
  check('renumbered 1..N', sequential(after))
})

section('6b. Assignment places the row at the end of the MILESTONE block (plan.md 0.3)')
guard(() => {
  /*
   * The exact board the user hit, and the exact fixture detail that makes the bug visible:
   * **2.3 exists after 2.2.** With 2.2 last in its phase, "end of the milestone block" and
   * "end of the phase block" are the same index and a phase-granular implementation looks
   * correct. This is the fixture-can-fail rule applied to placement.
   *
   *   before: z1(0.1) z2(0.1) a1(1.1) a2(1.1) [G] b1(2.1) c1(2.2) c2(2.2) d1(2.3) d2(2.3)
   *
   * The leading Phase 0 rows are not decoration: displayed numbers are derived from
   * *first-appearance order*, so a board that skips Phase 0 renders its blocks as 0.x/1.x
   * and the assertions below would be checking different strings than the ones the user
   * reported.
   */
  const bench = makeMilestoneBench([
    [0, 0],
    [0, 0],
    [1, 0],
    [1, 0],
    null,
    [2, 0],
    [2, 1],
    [2, 1],
    [2, 2],
    [2, 2],
  ])
  const rows = bench.backend.project(bench.scope)
  const gray = rows[4]!
  const phase2 = bench.phases[2]!
  const [m21, m22, m23] = bench.milestonesOf(2)
  check(
    'setup: a gray row after 1.1, then 2.1 / 2.2 x2 / 2.3 x2',
    gray.phase_id === null &&
      rows.map((r) => r.milestone_display?.split(' ')[0] ?? 'G').join(',') ===
        '0.1,0.1,1.1,1.1,G,2.1,2.2,2.2,2.3,2.3',
    rows.map((r) => r.milestone_display?.split(' ')[0] ?? 'G'),
  )

  // ── the user's scenario, end to end ──
  const assigned = bench.backend.setMembership(bench.scope, gray.id, {
    phase_id: phase2.id,
    milestone_id: m22!.id,
  })
  const at = assigned.findIndex((r) => r.id === gray.id)
  check('the row moved into the 2.2 block', assigned[at]!.milestone_id === m22!.id)
  check(
    'at the END of 2.2 and BEFORE 2.3 — not after 2.3, and not left where it stood',
    at === 7,
    { at, order: assigned.map((r) => r.milestone_display?.split(' ')[0]) },
  )
  check(
    'the whole board reads exactly as the server produces it',
    assigned.map((r) => r.milestone_display?.split(' ')[0]).join(',') ===
      '0.1,0.1,1.1,1.1,2.1,2.2,2.2,2.2,2.3,2.3',
    assigned.map((r) => r.milestone_display?.split(' ')[0]),
  )
  check('still contiguous at both levels', isContiguous(assigned, 'phase_id') && isContiguous(assigned, 'milestone_id'))
  check('renumbered 1..N', sequential(assigned))

  /*
   * "each label renders exactly once per block" — the visible symptom the user reported was
   * labels appearing in the wrong place, which is what block-start flags drive. One start
   * and one end per distinct milestone, or the Phase column paints a heading mid-block.
   */
  const startsPerMilestone = new Map<number, number>()
  for (const row of assigned) {
    if (row.milestone_id == null || !row.is_milestone_block_start) continue
    startsPerMilestone.set(row.milestone_id, (startsPerMilestone.get(row.milestone_id) ?? 0) + 1)
  }
  check(
    'every milestone block starts exactly once',
    [...startsPerMilestone.values()].every((n) => n === 1) && startsPerMilestone.size === 5,
    [...startsPerMilestone.values()],
  )
  check(
    'numbering did not scramble — 2.1 / 2.2 / 2.3 are still in that order',
    [...new Set(assigned.map((r) => r.milestone_display?.split(' ')[0]).filter(Boolean))].join(
      ',',
    ) === '0.1,1.1,2.1,2.2,2.3',
  )

  // ── phase only lands at the end of the PHASE block ──
  const bench2 = makeMilestoneBench([
    [0, 0], [0, 0], [1, 0], [1, 0], null, [2, 0], [2, 1], [2, 1], [2, 2], [2, 2],
  ])
  const gray2 = bench2.backend.project(bench2.scope)[4]!
  const phaseOnly = bench2.backend.setMembership(bench2.scope, gray2.id, {
    phase_id: bench2.phases[2]!.id,
    milestone_id: null,
  })
  check(
    'naming only a phase lands at the end of the PHASE block — after 2.3',
    phaseOnly.findIndex((r) => r.id === gray2.id) === 9,
    phaseOnly.map((r) => r.milestone_display?.split(' ')[0] ?? 'G'),
  )
  check('and the row is still milestone-unassigned', phaseOnly[9]!.milestone_id === null)
  check('board stays contiguous', isContiguous(phaseOnly, 'milestone_id'))

  check(
    'CONTROL — the two placements really differ, so the milestone case is not passing by luck',
    at !== phaseOnly.findIndex((r) => r.id === gray2.id),
    [at, phaseOnly.findIndex((r) => r.id === gray2.id)],
  )
  check('m21 / m23 exist in the fixture', !!m21 && !!m23)
})

section('6c. Placement by enumeration — every milestone of a board, against a computed expectation')
guard(() => {
  /*
   * Rather than a handful of hand-checked cases: for each board shape, assign the gray row
   * to **every** milestone in turn and compare against an expectation computed
   * independently — "the index just past the last row already carrying that milestone".
   * A phase-granular implementation disagrees with that for every milestone except the
   * last of its phase, which is precisely the set of cases a hand-written fixture tends to
   * miss.
   */
  const shapes: ([number, number] | null)[][] = [
    [[1, 0], [1, 0], null, [2, 0], [2, 1], [2, 1], [2, 2], [2, 2]],
    [null, [2, 0], [2, 1], [2, 2], [2, 3]],
    [[0, 0], [0, 1], null, [1, 0], [1, 1], [1, 2], [2, 0]],
    [[3, 0], [3, 1], [3, 2], [3, 3], null],
  ]

  let cases = 0
  let placedAsExpected = 0
  let wouldDifferFromPhaseEnd = 0
  const mismatches: unknown[] = []

  for (const shape of shapes) {
    const grayAt = shape.indexOf(null)
    for (let phaseIndex = 0; phaseIndex < 4; phaseIndex++) {
      const probe = makeMilestoneBench(shape)
      const milestones = probe.milestonesOf(phaseIndex)
      for (const milestone of milestones) {
        const bench = makeMilestoneBench(shape)
        const before = bench.backend.project(bench.scope)
        const gray = before[grayAt]!
        if (gray.phase_id !== null) continue

        // Expectation, computed from the *pre-move* board and nothing else.
        const withoutGray = before.filter((r) => r.id !== gray.id)
        let expected = withoutGray.map((r) => r.milestone_id).lastIndexOf(milestone.id)
        const phaseEnd = withoutGray.map((r) => r.phase_id).lastIndexOf(probe.phases[phaseIndex]!.id)
        if (expected < 0) expected = phaseEnd
        if (expected < 0) continue // this phase has no rows on this board — nothing to assert
        if (expected !== phaseEnd) wouldDifferFromPhaseEnd++
        expected += 1

        cases++
        try {
          const after = bench.backend.setMembership(bench.scope, gray.id, {
            phase_id: probe.phases[phaseIndex]!.id,
            milestone_id: milestone.id,
          })
          const landed = after.findIndex((r) => r.id === gray.id)
          if (landed === expected) placedAsExpected++
          else mismatches.push({ shape: shape.map((c) => c?.join('.') ?? 'G'), expected, landed })
        } catch (error) {
          mismatches.push({ threw: (error as Error).message })
        }
      }
    }
  }

  check(`enumerated ${cases} assignments across ${shapes.length} board shapes`, cases > 20, cases)
  check('every one landed exactly where the rule says', placedAsExpected === cases, mismatches.slice(0, 4))
  check(
    'and most of them are cases a phase-granular implementation gets WRONG',
    wouldDifferFromPhaseEnd > cases / 3,
    { differing: wouldDifferFromPhaseEnd, of: cases },
  )
})

section('6d. 미배정으로 전환 — the single reclassification path (plan.md 0.3)')
guard(() => {
  /*
   * The trailing gray row is load-bearing, not scenery.
   *
   * 전환 must leave the row where it stands. Without another gray row on the board, an
   * implementation that *did* relocate would search for "the last row whose phase is null",
   * find none, and put the row back at its original index — so the test would pass against
   * broken code. The deliberate-break run caught exactly that: B9 stayed green until this
   * row was added. A fixture has to be able to see the failure it is written for.
   */
  const bench = makeMilestoneBench([
    [1, 0], [1, 0], [2, 0], [2, 1], [2, 1], [2, 2], [2, 2], null,
  ])
  const before = bench.backend.project(bench.scope)
  const victim = before[3]! // first row of the 2.2 block — a middle row of its phase
  check('setup: a fully assigned row inside a phase', victim.phase_id != null && victim.milestone_id != null)
  check('setup: and another gray row further down, so a relocation would be visible', before[7]!.phase_id === null)

  const grayed = bench.backend.setMembership(bench.scope, victim.id, {
    phase_id: null,
    milestone_id: null,
  })
  const nowAt = grayed.findIndex((r) => r.id === victim.id)
  check('it turned gray', grayed[nowAt]!.phase_id === null && grayed[nowAt]!.milestone_id === null)
  check('IN PLACE — the row did not move at all', nowAt === 3, nowAt)
  check(
    'and the board is still contiguous, because null is transparent',
    isContiguous(grayed, 'phase_id') && isContiguous(grayed, 'milestone_id'),
  )
  check('every other row kept its membership', membershipOf(grayed.filter((r) => r.id !== victim.id)) === membershipOf(before.filter((r) => r.id !== victim.id)))
  check('renumbered 1..N', sequential(grayed))

  // …and then the ordinary gray-row flow relocates it properly.
  const [, , m23] = bench.milestonesOf(2)
  const reassigned = bench.backend.setMembership(bench.scope, victim.id, {
    phase_id: bench.phases[2]!.id,
    milestone_id: m23!.id,
  })
  const landed = reassigned.findIndex((r) => r.id === victim.id)
  const lastOfBlock = reassigned.reduce(
    (last, row, i) => (row.milestone_id === m23!.id ? i : last),
    -1,
  )
  check(
    'reassigning after 전환 relocates to the end of the chosen milestone block',
    landed === lastOfBlock && reassigned[landed]!.milestone_id === m23!.id,
    { landed, lastOfBlock, order: reassigned.map((r) => r.milestone_display?.split(' ')[0]) },
  )
  check(
    '…which is NOT simply the end of the board — the trailing gray row is still last',
    landed < reassigned.length - 1 && reassigned[reassigned.length - 1]!.phase_id === null,
    reassigned.map((r) => r.milestone_display?.split(' ')[0] ?? 'G'),
  )
  check('still contiguous', isContiguous(reassigned, 'milestone_id'))
  check('so 전환 → 재배정 is a complete reclassification path', reassigned.length === before.length)
})

section('7. New phase creation — atomic, and refused off a block edge')
guard(() => {
  const items = backend.project(scope)
  const middle = items.find((r) => !r.can_create_phase)!
  const phasesBefore = backend.listPhases(templateScope).length

  const error = expectThrows(() => backend.createPhaseFromRow(scope, middle.id, { name: '보류' }))
  check('a middle row is refused with 422', error?.status === 422, error?.message)
  check(
    'nothing was created — a failure cannot orphan a Phase in master data',
    backend.listPhases(templateScope).length === phasesBefore,
  )

  const untouched = backend.project(scope)
  check(
    'the board is untouched',
    orderOf(untouched) === orderOf(items) && membershipOf(untouched) === membershipOf(items),
  )

  const edge = items.find((r) => r.can_create_phase && r.is_phase_block_start)!
  const after = backend.createPhaseFromRow(scope, edge.id, { name: '신규 준비 단계' })
  const created = after.find((r) => r.id === edge.id)!
  check('an edge row is accepted', created.phase_name === '신규 준비 단계')
  check('the new phase has no milestone yet', created.milestone_id === null)
  check('numbering re-derived, still contiguous', isContiguous(after, 'phase_id'))
  check(
    'phase numbers are gapless',
    (() => {
      const numbers = [...new Set(after.map((r) => r.phase_no))].sort((a, b) => a! - b!)
      return numbers.every((n, i) => n === i)
    })(),
  )
  check(
    'duplicate phase name is refused',
    expectThrows(() => backend.createPhaseFromRow(scope, edge.id, { name: '신규 준비 단계' }))
      ?.status === 400,
  )
})

section('7b. Appending to an empty version')
guard(() => {
  // A template with no PUBLISHED version gets an empty DRAFT and V13 forbids publishing it,
  // so seeding the first row must be possible. `insert-below` needs an anchor, so this
  // endpoint is that entry point.
  const fresh = new MockBackend(1)
  const unpublished = fresh.listTemplates()[1]!
  const emptyDraft = fresh.listVersions(unpublished.id).find((v) => v.status === 'DRAFT')!
  const emptyScope = fresh.versionScope(emptyDraft.id)
  check('a template with no PUBLISHED version has an empty draft', fresh.project(emptyScope).length === 0)

  const seeded = fresh.appendRow(emptyScope)
  check('append creates the first row', seeded.length === 1, seeded.length)
  check('it is numbered 1', seeded[0]!.row_no === 1)
  check('membership starts unset, which is legal', seeded[0]!.phase_id === null)
  check('and it is marked ADDED', seeded[0]!.origin === 'ADDED')
  check('the only row on the board may create a phase', seeded[0]!.can_create_phase)
})

section('7d. Consecutive gray rows')
guard(() => {
  /*
   * Routine, not exotic: `appendRow` produces exactly these, and a fresh template starts
   * with nothing else. They must be reorderable among themselves (otherwise a new board
   * can never be arranged) and each must be able to start a phase (otherwise it can never
   * be classified).
   */
  const fresh = new MockBackend(1)
  const unpublished = fresh.listTemplates()[1]!
  const emptyDraft = fresh.listVersions(unpublished.id).find((v) => v.status === 'DRAFT')!
  const emptyScope = fresh.versionScope(emptyDraft.id)
  fresh.appendRow(emptyScope)
  fresh.appendRow(emptyScope)
  const rows = fresh.appendRow(emptyScope)

  check('three consecutive gray rows', rows.length === 3 && rows.every((r) => r.phase_id === null))
  check('every one of them may create a phase', rows.every((r) => r.can_create_phase))
  check('none of them may create a milestone yet', rows.every((r) => !r.can_create_milestone))
  check('all three are draggable', rows.every((r) => canDragRow(rows, r)))
  check(
    'and any permutation of them is allowed',
    isWithinBlockOrder(rows, [rows[2]!.id, rows[0]!.id, rows[1]!.id]),
  )
  check(
    'reordering them really works',
    orderOf(fresh.reorder(emptyScope, [rows[2]!.id, rows[0]!.id, rows[1]!.id])) ===
      [rows[2]!.id, rows[0]!.id, rows[1]!.id].join(','),
  )
})

section('7c. reorder — exhaustive, because sampling cannot find this')
guard(() => {
  /*
   * Every permutation of several board layouts, not a sample, run through both defences:
   * the grid's block guard and the server's contiguity check.
   *
   * "Membership is preserved, so contiguity is preserved" is false — `[A/0, B/1, A/0]` is
   * one permutation away from any two-block board — so the server keeps its guard for the
   * host's other clients. What this establishes is the division of labour: everything the
   * grid lets through is accepted *and* leaves membership untouched, while the grid
   * refuses strictly more than the server does. Both halves are counted, and a run where
   * either count collapsed to zero fails.
   *
   * Two of the layouts carry gray rows, so §0.2.2's freedom is exercised over the whole
   * permutation space rather than in one hand-written case.
   */
  const permutations = <T,>(list: T[]): T[][] =>
    list.length <= 1
      ? [list]
      : list.flatMap((item, i) =>
          permutations([...list.slice(0, i), ...list.slice(i + 1)]).map((rest) => [item, ...rest]),
        )

  const layouts: (number | null)[][] = [
    [0, 0, 1, 2, 0],
    [0, 1, 1, 2, 2],
    [0, 0, 0, 1, 2],
    [0, 1, 2, 2, 2],
    [0, 0, 1, 1, 2],
    [0, null, 1, 1, 2],
    [0, 0, null, null, 1],
  ]

  let cases = 0
  let allowedByGrid = 0
  let rejected = 0
  let fragmentsAccepted = 0
  let allowedThenRejected = 0
  let membershipDrifted = 0
  let refusedThoughLegal = 0
  let guardGapOnBrokenBoard = 0
  let grayMovesAllowed = 0

  for (const layout of layouts) {
    for (const order of permutations([0, 1, 2, 3, 4])) {
      const { backend: bench, scope: benchScope, ids } = makeBench(layout)
      const items = bench.project(benchScope)
      const orderedIds = order.map((i) => ids[i]!)
      const gridAllows = isWithinBlockOrder(items, orderedIds)
      /*
       * `[0, 0, 1, 2, 0]` is fragmented *before* anything is dragged — a state the UI
       * cannot reach, kept because the guard has to survive being handed one.
       *
       * Contiguity is the grid rule's precondition, not a bonus: it reads membership per
       * slot, and on a fragmented board the two runs of Phase 0 are indistinguishable by
       * membership, so it will wave through a swap between them. The board stays broken
       * and the server refuses it — which is why the counters are split rather than the
       * layout dropped. Deleting the layout would make the headline claim look
       * unconditional when it is not.
       */
      const startsContiguous = isContiguous(items, 'phase_id')
      if (gridAllows) allowedByGrid++
      if (gridAllows && layout.includes(null) && order.join() !== '0,1,2,3,4') grayMovesAllowed++
      cases++

      try {
        const result = bench.reorder(benchScope, orderedIds)
        if (!isContiguous(result, 'phase_id')) fragmentsAccepted++
        if (membershipOf(result) !== membershipOf(items)) membershipDrifted++
        if (!gridAllows) refusedThoughLegal++
      } catch (error) {
        if (!(error instanceof MockHttpError) || error.status !== 422) throw error
        rejected++
        if (gridAllows && startsContiguous) allowedThenRejected++
        if (gridAllows && !startsContiguous) guardGapOnBrokenBoard++
        if (membershipOf(bench.project(benchScope)) !== membershipOf(items)) membershipDrifted++
      }
    }
  }

  check(`exhaustive: ${cases} permutations across ${layouts.length} layouts`, cases === 840, cases)
  check('no fragmented board is ever accepted with a 200', fragmentsAccepted === 0, fragmentsAccepted)
  check(
    'the fixture can actually exhibit the failure — some permutations ARE rejected',
    rejected > 0,
    rejected,
  )
  check(
    'reorder never moves a row between blocks, accepted or refused',
    membershipDrifted === 0,
    membershipDrifted,
  )
  check(
    'the grid can express real reorders — not everything is refused',
    allowedByGrid > layouts.length,
    allowedByGrid,
  )
  check(
    'every order the grid allows on a contiguous board is accepted by the server',
    allowedThenRejected === 0,
    allowedThenRejected,
  )
  check(
    'and the grid refuses more than contiguity alone would — the two guards are not one guard',
    refusedThoughLegal > 0,
    refusedThoughLegal,
  )
  check(
    'the "contiguous board" qualifier above is load-bearing — hand the grid a broken board and the server is the only guard left',
    guardGapOnBrokenBoard > 0,
    guardGapOnBrokenBoard,
  )
  check(
    'gray-row layouts admit orders the all-assigned ones would refuse',
    grayMovesAllowed > 0,
    grayMovesAllowed,
  )
})

section('8. Publish validation (plan.md 2.5) — gray rows are caught here and only here')
guard(() => {
  const result = backend.validate(draft.id)
  check('draft with an unassigned milestone fails', !result.valid)
  check(
    'MILESTONE_REQUIRED reported with cell coordinates',
    result.errors.some(
      (e) => e.code === 'MILESTONE_REQUIRED' && e.item_id != null && e.field === 'milestone_id',
    ),
  )

  // A gray row is legal right up until publish, and then V1/V2 name it by cell.
  const withGray = backend.appendRow(scope)
  const gray = withGray[withGray.length - 1]!
  const grayResult = backend.validate(draft.id)
  const grayIssues = grayResult.errors.filter((e) => e.item_id === gray.id)
  check(
    'a gray row is flagged on BOTH phase_id and milestone_id',
    grayIssues.some((e) => e.code === 'PHASE_REQUIRED' && e.field === 'phase_id') &&
      grayIssues.some((e) => e.code === 'MILESTONE_REQUIRED' && e.field === 'milestone_id'),
    grayIssues.map((e) => e.code),
  )
  check(
    'with a row number the grid can jump to',
    grayIssues.every((e) => e.row_no === gray.row_no),
  )

  // Publish failure is a thrown 422 carrying the §2.5 payload, exactly as over HTTP.
  const publishAttempt = expectThrows(() => backend.publish(draft.id))
  check('publish is blocked with a 422', publishAttempt?.status === 422)
  check(
    'the 422 carries the transport envelope the client unwraps',
    publishAttempt?.response.data.detail.code === 'VALIDATION_FAILED' &&
      Array.isArray(publishAttempt?.response.data.detail.errors),
  )
  check(
    'version really is still DRAFT',
    backend.listVersions(template.id).find((v) => v.id === draft.id)!.status === 'DRAFT',
  )
  backend.deleteItem(scope, gray.id)

  // Empty out one row and confirm every per-cell rule fires with a location.
  const items = backend.project(scope)
  const payload = toPayload(items)
  payload[0] = { ...payload[0]!, title: '', deliverable: '', document_ids: [], owner_ids: [] }
  backend.saveItems(scope, payload)
  const strict = backend.validate(draft.id)
  const codes = new Set(strict.errors.filter((e) => e.item_id === items[0]!.id).map((e) => e.code))
  check(
    'TITLE / DELIVERABLE / DOCUMENT / OWNER all reported for the blanked row',
    ['TITLE_REQUIRED', 'DELIVERABLE_REQUIRED', 'DOCUMENT_REQUIRED', 'OWNER_REQUIRED'].every((c) =>
      codes.has(c),
    ),
    [...codes],
  )
  report.push('\nSample Korean messages:')
  for (const issue of strict.errors.slice(0, 4)) report.push(`  - [${issue.code}] ${issue.message}`)
})

section('8b. The client error path runs against transport-shaped errors')
guard(() => {
  /*
   * `describeApiError` and `unwrapValidationFailure` exist because domain errors arrive as
   * `{detail:{code,message}}` and publish failure is a 422. While the mock threw bare
   * `Error`s, neither function was ever reached under `npm run check`. The envelope has
   * already changed shape once in this project.
   */
  const conflict = expectThrows(() => backend.saveItems({ kind: 'project', projectId: 1 }, []))!
  check('a mock error carries an axios-shaped response', typeof conflict.response?.status === 'number')
  check(
    'describeApiError yields readable text, never [object Object]',
    (() => {
      const text = describeApiError(conflict, 'FALLBACK')
      return typeof text === 'string' && !text.includes('[object') && text !== 'FALLBACK'
    })(),
    describeApiError(conflict, 'FALLBACK'),
  )
  // The check above passes even from the `.message` fallback, so it cannot tell whether the
  // envelope was read at all. This one can: the two strings deliberately differ.
  const divergent = {
    response: { status: 409, data: { detail: { code: 'X', message: 'FROM_DETAIL' } } },
    message: 'FROM_ERROR',
  }
  check(
    'describeApiError prefers detail.message over error.message',
    describeApiError(divergent, 'FALLBACK') === 'FROM_DETAIL',
  )
  check(
    'and handles FastAPI request-validation arrays too',
    describeApiError(
      { response: { data: { detail: [{ loc: ['body'], msg: 'field required' }] } } },
      'FALLBACK',
    ) === 'field required',
  )

  const failedPublish = expectThrows(() => backend.publish(draft.id))!
  const unwrapped = unwrapValidationFailure(failedPublish)
  check('unwrapValidationFailure recognises the 422 envelope', unwrapped !== null)
  check('…and yields the §2.5 issue list', (unwrapped?.errors.length ?? 0) > 0)
  check(
    '…with per-cell coordinates the grid can highlight',
    unwrapped?.errors.some((e) => e.item_id != null && !!e.field) === true,
  )
  check(
    'a non-validation error is left to propagate, not swallowed',
    unwrapValidationFailure(conflict) === null,
  )
})

section('9. Unvalidated save accepts anything, 발행 does not')
guard(() => {
  const items = backend.project(scope)
  const payload = toPayload(items).map((row, i) =>
    i === 0 ? { ...row, phase_id: null, milestone_id: null } : row,
  )
  const saved = backend.saveItems(scope, payload)
  check('null phase/milestone survive a save', saved[0]!.phase_id === null)
  check('publish rejects it', !backend.validate(draft.id).valid)
  check(
    'a nonexistent phase_id is still refused',
    expectThrows(() =>
      backend.saveItems(
        scope,
        toPayload(saved).map((r, i) => (i === 0 ? { ...r, phase_id: 999999 } : r)),
      ),
    )?.status === 400,
  )
})

section('10. Version state machine (plan.md 2.4) — template tier only')
// A pristine backend: the sections above deliberately left `backend` in a broken state.
const clean = new MockBackend(1)
const cleanTemplate = clean.listTemplates()[0]!
const cleanDraft = clean.listVersions(cleanTemplate.id).find((v) => v.status === 'DRAFT')!
const cleanPublished = clean.listVersions(cleanTemplate.id).find((v) => v.status === 'PUBLISHED')!
const cleanScope = clean.versionScope(cleanDraft.id)
guard(() => {
  check(
    'PUBLISHED items are immutable',
    expectThrows(() => clean.saveItems(clean.versionScope(cleanPublished.id), []))?.status === 409,
  )
  check(
    'a second DRAFT is refused',
    expectThrows(() => clean.deepCopyToDraft(cleanTemplate.id))?.status === 409,
  )
  check('the untouched deep copy validates', clean.validate(cleanDraft.id).valid)

  const publishResult = clean.publish(cleanDraft.id)
  check('publish succeeds', publishResult.result.valid, publishResult.result.errors.slice(0, 3))
  check('and returns the transitioned version', publishResult.version.status === 'PUBLISHED')
  const after = clean.listVersions(cleanTemplate.id)
  check('v2 became PUBLISHED', after.find((v) => v.id === cleanDraft.id)?.status === 'PUBLISHED')
  check('v1 was archived', after.find((v) => v.id === cleanPublished.id)?.status === 'ARCHIVED')
  check('exactly one PUBLISHED', after.filter((v) => v.status === 'PUBLISHED').length === 1)
  check(
    'the newly published version is the template\'s current PUBLISHED one',
    publishedVersionId(clean, cleanTemplate.id) === cleanDraft.id,
  )
  check(
    'the freshly published version is now immutable too',
    expectThrows(() => clean.insertBelow(cleanScope, clean.project(cleanScope)[0]!.id))?.status ===
      409,
  )
})

section('11. Deep copy leaves the source version alone')
guard(() => {
  const before = clean.project(cleanScope)
  const newDraft = clean.deepCopyToDraft(cleanTemplate.id)
  const newScope = clean.versionScope(newDraft.id)
  const copied = clean.project(newScope)
  check('same row count', copied.length === before.length)
  check('rows are new records', copied.every((r, i) => r.id !== before[i]!.id))
  check(
    'content came across',
    copied.every((r, i) => r.title === before[i]!.title),
  )

  clean.deleteItem(newScope, copied[0]!.id)
  check(
    'editing the draft did not touch the published version',
    clean.project(cleanScope).length === before.length,
  )
})

section('12. Master data is deactivated, never hard-deleted, while in use')
guard(() => {
  const cleanTemplateScope = { kind: 'template' as const, templateId: cleanTemplate.id }

  const owner = clean.listOwners(cleanTemplateScope)[0]!
  const ownerResult = clean.deleteOwner(cleanTemplateScope, owner.id)
  check('a template Owner in use is deactivated too', !ownerResult.deleted && ownerResult.usage_count > 0)
})

// ══════════════════════════════════════════════ plan.md §0 — the two tiers

section('13. Project creation deep-copies a published template (plan.md 0.1)')
const tiered = new MockBackend(7)
const tieredTemplate = tiered.listTemplates()[0]!
const tieredTemplateScope = { kind: 'template' as const, templateId: tieredTemplate.id }
const seededProject = tiered.listProjects(7)[0]!
const seededScope = tiered.projectScope(seededProject.id)
guard(() => {
  check('the maker already has a project', !!seededProject, tiered.listProjects(7).length)
  /*
   * The stand-in must not be *richer* than the server. `check:live` found the client
   * reading `published_version_id` off a template and `template_name` off a project —
   * neither exists on the wire — and the mock happily supplied both, so every mock-backed
   * assertion passed while the real screens came up empty. These two checks pin the
   * payloads to what the server actually sends.
   */
  check(
    'TemplateOut carries no published_version_id',
    !('published_version_id' in tieredTemplate),
    Object.keys(tieredTemplate),
  )
  check(
    'it records the format and the exact snapshot it came from',
    seededProject.source_template_id === tieredTemplate.id &&
      seededProject.source_version_id === publishedVersionId(tiered, tieredTemplate.id),
    [seededProject.source_template_id, seededProject.source_version_id],
  )
  check(
    'and it carries no denormalised template name — the server sends none',
    !('template_name' in seededProject),
    Object.keys(seededProject),
  )
  check('35 rows were copied', tiered.project(seededScope).length === 35)
  check(
    'rows are new records, not shared with the template',
    (() => {
      const templateIds = new Set(
        tiered
          .project(tiered.versionScope(publishedVersionId(tiered, tieredTemplate.id)!))
          .map((r) => r.id),
      )
      return tiered.project(seededScope).every((r) => !templateIds.has(r.id))
    })(),
  )

  /*
   * Phases, milestones and owners are copies with their own ids — the single most
   * load-bearing fact of the two-tier split. If they were shared, a project-local rename
   * would rewrite the central standard for every maker.
   */
  const templatePhases = tiered.listPhases(tieredTemplateScope)
  const projectPhases = tiered.listPhases(seededScope)
  check('the project has its own phase set', projectPhases.length === templatePhases.length)
  check(
    '…with entirely different ids',
    projectPhases.every((p) => !templatePhases.some((t) => t.id === p.id)),
    [templatePhases[0]?.id, projectPhases[0]?.id],
  )
  check(
    'the copied rows point at the COPIES, not at the template rows',
    (() => {
      const ids = new Set(projectPhases.map((p) => p.id))
      return tiered.project(seededScope).every((r) => r.phase_id == null || ids.has(r.phase_id))
    })(),
  )
  check(
    'owners were remapped the same way',
    (() => {
      const ids = new Set(tiered.listOwners(seededScope).map((o) => o.id))
      return tiered.project(seededScope).every((r) => r.owners.every((o) => ids.has(o.id)))
    })(),
  )
  /*
   * 문서도 복제된다 (`plan.md` §0.5.10). 이 단언은 예전과 **정반대**다 — 전역 마스터였을 때는
   * "복사되지 않는 유일한 것" 이었고, 지금은 Phase·Milestone·Owner 와 같은 규칙을 따른다.
   */
  const templateDocIds = new Set(
    tiered.listDocuments(
      tiered.versionScope(tiered.listVersions(tieredTemplate.id)[0]!.id),
    ).documents.map((d) => d.id),
  )
  check(
    'documents WERE copied — the project rows point at its own copies',
    tiered
      .project(seededScope)
      .every((r) => r.documents.every((d) => !templateDocIds.has(d.id))),
  )
  check('numbering came out identical', tiered.project(seededScope)[0]!.phase_display === 'Phase 0. Pre-Infrastructure Setup')

  check(
    'a template with no published version cannot seed a project',
    expectThrows(() =>
      tiered.createProject({
        maker_id: 7,
        name: '불가',
        template_id: tiered.listTemplates()[1]!.id,
      }),
    )?.status === 422,
  )
  check(
    'neither can a DRAFT version, named explicitly',
    expectThrows(() =>
      tiered.createProject({
        maker_id: 7,
        name: '불가2',
        template_id: tieredTemplate.id,
        template_version_id: tiered
          .listVersions(tieredTemplate.id)
          .find((v) => v.status === 'DRAFT')!.id,
      }),
    )?.status === 422,
  )
  check(
    'and a nameless project is a 400',
    expectThrows(() =>
      tiered.createProject({ maker_id: 7, name: '  ', template_id: tieredTemplate.id }),
    )?.status === 400,
  )
})

section('14. A project is isolated from the template it came from')
guard(() => {
  const templateVersionScope = tiered.versionScope(publishedVersionId(tiered, tieredTemplate.id)!)
  const templateBefore = membershipOf(tiered.project(templateVersionScope))
  const templatePhasesBefore = tiered.listPhases(tieredTemplateScope).length

  // A project-local phase, created from the project board.
  const rows = tiered.project(seededScope)
  const edge = rows.find((r) => r.can_create_phase)!
  tiered.createPhaseFromRow(seededScope, edge.id, { name: '이 프로젝트만의 단계' })

  check(
    'the project gained a phase',
    tiered.listPhases(seededScope).some((p) => p.name === '이 프로젝트만의 단계'),
  )
  check(
    'the central template did NOT',
    tiered.listPhases(tieredTemplateScope).length === templatePhasesBefore,
    templatePhasesBefore,
  )
  check(
    'and the template version rows are byte-identical',
    membershipOf(tiered.project(templateVersionScope)) === templateBefore,
  )

  check(
    'a project cannot reference a template phase id — different scope, 400',
    expectThrows(() =>
      tiered.setMembership(seededScope, rows[0]!.id, {
        phase_id: tiered.listPhases(tieredTemplateScope)[0]!.id,
        milestone_id: null,
      }),
    )?.status === 400,
  )
  check(
    'NEGATIVE CONTROL — its own phase id is accepted',
    tiered.setMembership(seededScope, rows[0]!.id, {
      phase_id: tiered.listPhases(seededScope)[0]!.id,
      milestone_id: null,
    }).length === 35,
  )
})

section('15. The project tier has no versions and no publish gate')
guard(() => {
  const rows = tiered.project(seededScope)

  // Gray rows are legal here forever: nothing ever validates them away.
  const withGray = tiered.appendRow(seededScope)
  const gray = withGray[withGray.length - 1]!
  check('a project accepts a gray row', isGray(gray))

  const saved = tiered.saveItems(seededScope, toPayload(withGray))
  check('and it survives a save', saved.some((r) => r.id === gray.id && isGray(r)))
  check('board still contiguous with it in place', isContiguous(saved, 'phase_id'))

  /*
   * There is no publish endpoint for a project at all — not a disabled one, not one that
   * returns valid. `validate` takes a *version* id, and a project id is not one. That is
   * the assertion: the operation does not exist rather than being suppressed in the UI.
   */
  check(
    'validate() cannot even be addressed with a project id',
    expectThrows(() => tiered.validate(seededProject.id))?.status === 404,
  )
  check('a project is never read-only for version reasons — edits just land', tiered.project(seededScope).length === 36)

  // The grid behaves identically: same drag rule, same seam flow.
  const dragged = dragRow(tiered, seededScope, 35, 2)
  check('the gray row drags anywhere on a project too', !dragged.refused)
  check(
    'and an assigned row is still block-confined here',
    dragRow(tiered, seededScope, 1, 25).refusedBy === 'grid',
  )
  check('rows renumbered by the server', sequential(tiered.project(seededScope)))

  tiered.deleteItem(seededScope, gray.id)
  check('deleting works too', tiered.project(seededScope).length === 35)
  check('project rows unchanged in count after all that', rows.length === 35)
})

section('16. Projects are scoped to their maker')
guard(() => {
  const other = tiered.createProject({
    maker_id: 9,
    name: '다른 설비사 프로젝트',
    template_id: tieredTemplate.id,
  })
  check('maker 7 does not see maker 9 project', !tiered.listProjects(7).some((p) => p.id === other.id))
  check('maker 9 sees exactly one', tiered.listProjects(9).length === 1)
  check(
    'NEGATIVE CONTROL — maker 7 still sees its own',
    tiered.listProjects(7).some((p) => p.id === seededProject.id),
  )
  check(
    'the two projects do not share master data either',
    (() => {
      const a = new Set(tiered.listPhases(seededScope).map((p) => p.id))
      return tiered.listPhases(tiered.projectScope(other.id)).every((p) => !a.has(p.id))
    })(),
  )

  tiered.deleteProject(other.id)
  check('deleting deactivates it out of the list', tiered.listProjects(9).length === 0)
})

section('17. phases/apply — the popup order IS the numbering (plan.md 0.4)')
guard(() => {
  // 6 rows, three phases of two, each with its own two milestones. Small enough to read,
  // wide enough that a phase moving pushes *other* phases and their milestones.
  const bench = makeMilestoneBench([
    [0, 0],
    [0, 1],
    [1, 0],
    [1, 1],
    [2, 0],
    [2, 1],
  ])
  const { backend: be, scope: sc } = bench
  const before = be.project(sc)
  check('setup: phases 0,0,1,1,2,2', phaseNos(before) === '0,0,1,1,2,2', phaseNos(before))
  check('setup: milestones 0.1,0.2,1.1,1.2,2.1,2.2', msNos(before) === '0.1,0.2,1.1,1.2,2.1,2.2', msNos(before))

  const plan = phasePlan(be, sc)
  check('the popup lists every phase of the scope, board order first', plan.length >= 3, plan.length)
  const [p0, p1, p2] = [plan[0]!.id!, plan[1]!.id!, plan[2]!.id!]

  // ── Insert a brand-new phase between 0 and 1. ──
  const inserted = be.applyPhases(sc, {
    phases: [plan[0]!, { id: null, name: '중간 신규 단계' }, ...plan.slice(1)],
    deleted_ids: [],
  })
  const rowsAfter = inserted.items
  check('a blank row was created for the new phase — a phase with no rows has no number', rowsAfter.length === 7, rowsAfter.length)
  check(
    'the new phase landed between them and took number 1',
    rowsAfter[2]!.phase_name === '중간 신규 단계' && rowsAfter[2]!.phase_no === 1,
    [rowsAfter[2]!.phase_name, rowsAfter[2]!.phase_no],
  )
  check(
    'THE POINT — the old Phase 1 was pushed to 2, and Phase 2 to 3',
    phaseNos(rowsAfter) === '0,0,1,2,2,3,3',
    phaseNos(rowsAfter),
  )
  check(
    '…and every milestone number under them followed',
    msNos(rowsAfter) === '0.1,0.2,-,2.1,2.2,3.1,3.2',
    msNos(rowsAfter),
  )
  check('rows renumbered 1..N', sequential(rowsAfter))
  check('board still contiguous', isContiguous(rowsAfter, 'phase_id') && isContiguous(rowsAfter, 'milestone_id'))
  check('the blank row really is blank and ADDED', rowsAfter[2]!.origin === 'ADDED' && !(rowsAfter[2]!.title ?? '').trim())
  check(
    'the response carries the recomputed master lists, not just rows',
    inserted.phases.length > 0 && inserted.milestones.length > 0,
  )
  check(
    '…so the popup can read back the id of the phase it just created',
    inserted.phases.some(
      (p) => p.name === '중간 신규 단계' && p.id === rowsAfter[2]!.phase_id,
    ),
  )

  // ── Rename + pure reorder, no structural change. ──
  const plan2 = phasePlan(be, sc)
  const renamed = plan2.map((e) => (e.id === p0 ? { ...e, name: '이름 바꾼 첫 단계' } : e))
  const moved = be.applyPhases(sc, {
    phases: [renamed[1]!, renamed[0]!, ...renamed.slice(2)],
    deleted_ids: [],
  })
  /*
   * Labels must stay on the rows they belong to, not merely still exist somewhere.
   *
   * Section 20 counts how many rows still carry a `dash_label` after an apply, which catches
   * a wholesale drop but not a shuffle — and a shuffle is the failure this operation can
   * actually produce, since apply moves whole blocks around. Keyed by id, so it is
   * independent of the reordering being tested.
   */
  const labelsOf = (list: WpItem[]) =>
    [...list].sort((a, b) => a.id - b.id).map((r) => `${r.id}:${r.dash_label}`).join('|')
  check(
    'every dash_label stayed on the row it belongs to across a block reorder',
    labelsOf(moved.items) === labelsOf(rowsAfter),
    [labelsOf(rowsAfter).slice(0, 80), labelsOf(moved.items).slice(0, 80)],
  )
  check('setup: those labels are not all null, so the check can fail', rowsAfter.some((r) => !!r.dash_label))

  check('rename landed', moved.items.find((r) => r.phase_id === p0)?.phase_name === '이름 바꾼 첫 단계')
  check(
    'swapping the top two blocks swaps their numbers',
    moved.items[0]!.phase_name === '중간 신규 단계' && moved.items[0]!.phase_no === 0,
    [moved.items[0]!.phase_name, moved.items[0]!.phase_no],
  )
  check('and moved the rows with them', moved.items[1]!.phase_id === p0 && moved.items[1]!.phase_no === 1)
  check('still 1..N', sequential(moved.items))

  // ── Cascade delete. ──
  const plan3 = phasePlan(be, sc)
  const doomedRows = moved.items.filter((r) => r.phase_id === p1).length
  const doomedMilestones = be.listMilestones(masterScopeOf(sc)).filter((m) => m.phase_id === p1).length
  check('setup: the phase about to go has rows and milestones', doomedRows === 2 && doomedMilestones > 0, [doomedRows, doomedMilestones])
  const afterDelete = be.applyPhases(sc, {
    phases: plan3.filter((e) => e.id !== p1),
    deleted_ids: [p1],
  })
  check('its rows went with it', afterDelete.items.length === moved.items.length - doomedRows, afterDelete.items.length)
  check('no row references it any more', !afterDelete.items.some((r) => r.phase_id === p1))
  /*
   * Asserted as "not offered any more", not as "gone from the table". The server deletes it
   * only when nothing else uses it and **deactivates** it when another version's rows still
   * do; the stand-in just drops it. Both land in the same place from the board's point of
   * view, and asserting the stand-in's stronger behaviour would be asserting something the
   * real server contradicts.
   */
  check(
    'and it is no longer an active phase of the scope',
    !afterDelete.phases.some((p) => p.id === p1 && p.is_active),
  )
  check('nor are its milestones', !afterDelete.milestones.some((m) => m.phase_id === p1 && m.is_active))
  check('sort_order is contiguous 1..N after the cascade', sequential(afterDelete.items) && afterDelete.items.every((r, i) => r.sort_order === i + 1))
  check('the survivors renumbered with no gap', phaseNos(afterDelete.items) === '0,1,1,2,2', phaseNos(afterDelete.items))
  check('board still contiguous', isContiguous(afterDelete.items, 'phase_id'))
  check('NEGATIVE CONTROL — the untouched phase kept its rows', afterDelete.items.filter((r) => r.phase_id === p2).length === 2)
})

section('17b. Gray rows travel with the block above them (plan.md 0.4)')
guard(() => {
  const bench = makeBench([0, 1, null, 2])
  const { backend: be, scope: sc } = bench
  const rows = be.project(sc)
  check('setup: P0, P1, gray, P2', phaseNos(rows) === '0,1,,2', phaseNos(rows))
  const grayId = rows[2]!.id
  const plan = phasePlan(be, sc)
  const [a, b, c] = [plan[0]!, plan[1]!, plan[2]!]

  const flipped = be.applyPhases(sc, { phases: [c, b, a, ...plan.slice(3)], deleted_ids: [] })
  check(
    'the gray row stayed attached to the block it followed',
    flipped.items[1]!.phase_id === b.id && flipped.items[2]!.id === grayId,
    flipped.items.map((r) => `${r.id}:${r.phase_no}`),
  )
  check('it is still gray', isGray(flipped.items[2]!))
  check('the blocks really did reorder', phaseNos(flipped.items) === '0,1,,2' && flipped.items[0]!.phase_id === c.id)
  check('still contiguous, still 1..N', isContiguous(flipped.items, 'phase_id') && sequential(flipped.items))

  // A gray row *leading* the board has no block above it to belong to.
  const lead = makeBench([null, 0, 1])
  const leadRows = lead.backend.project(lead.scope)
  const leadGray = leadRows[0]!.id
  const leadPlan = phasePlan(lead.backend, lead.scope)
  const swapped = lead.backend.applyPhases(lead.scope, {
    phases: [leadPlan[1]!, leadPlan[0]!, ...leadPlan.slice(2)],
    deleted_ids: [],
  })
  check('a leading gray row stays at the top', swapped.items[0]!.id === leadGray && isGray(swapped.items[0]!))
  check('the two blocks below it swapped', swapped.items[1]!.phase_id === leadPlan[1]!.id)
})

section('17c. Anchor mode — the gray row becomes the new phase\'s first row')
guard(() => {
  const bench = makeBench([0, 0, null, 1, 1])
  const { backend: be, scope: sc } = bench
  const rows = be.project(sc)
  const gray = rows[2]!
  check('setup: a gray row at the seam between two phases', isGray(gray))
  const plan = phasePlan(be, sc)

  const created = be.applyPhases(sc, {
    phases: [plan[0]!, { id: null, name: '앵커로 만든 단계' }, ...plan.slice(1)],
    deleted_ids: [],
    anchor_item_id: gray.id,
  })
  check('no extra row was invented — the anchor IS the row', created.items.length === rows.length, created.items.length)
  check(
    'the anchor row joined the new phase, in place',
    created.items[2]!.id === gray.id && created.items[2]!.phase_name === '앵커로 만든 단계',
    [created.items[2]!.id, gray.id, created.items[2]!.phase_name],
  )
  check('and got the number in between', phaseNos(created.items) === '0,0,1,2,2', phaseNos(created.items))
  check('contiguous and renumbered', isContiguous(created.items, 'phase_id') && sequential(created.items))

  // ── The anchor rules, as refusals. ──
  const fresh = makeBench([0, 0, null, 1, 1])
  const freshRows = fresh.backend.project(fresh.scope)
  const freshPlan = phasePlan(fresh.backend, fresh.scope)
  const assignedRow = freshRows[0]!
  const freshGray = freshRows[2]!

  const notGray = expectThrows(() =>
    fresh.backend.applyPhases(fresh.scope, {
      phases: [...freshPlan, { id: null, name: 'x' }],
      deleted_ids: [],
      anchor_item_id: assignedRow.id,
    }),
  )
  check('an assigned row cannot be the anchor', codeOf(notGray) === 'APPLY_ANCHOR_INVALID', codeOf(notGray))

  const twoNew = expectThrows(() =>
    fresh.backend.applyPhases(fresh.scope, {
      phases: [...freshPlan, { id: null, name: 'x' }, { id: null, name: 'y' }],
      deleted_ids: [],
      anchor_item_id: freshGray.id,
    }),
  )
  check(
    'an anchor with two new entries is refused — one of them would have no row',
    codeOf(twoNew) === 'APPLY_ANCHOR_INVALID',
    codeOf(twoNew),
  )
  check(
    'NEGATIVE CONTROL — the same call with exactly one new entry is accepted',
    fresh.backend.applyPhases(fresh.scope, {
      phases: [...freshPlan, { id: null, name: 'x' }],
      deleted_ids: [],
      anchor_item_id: freshGray.id,
    }).items.length === freshRows.length,
  )
})

section('17d. The payload is a final state, so it must add up (422)')
guard(() => {
  const bench = makeBench([0, 0, 1, 1])
  const { backend: be, scope: sc } = bench
  const plan = phasePlan(be, sc)
  check('setup: the scope has more than one phase to forget', plan.length >= 2, plan.length)
  const untouched = orderOf(be.project(sc))

  const short = expectThrows(() => be.applyPhases(sc, { phases: plan.slice(1), deleted_ids: [] }))
  check('omitting an id is refused rather than read as "delete it"', short?.status === 422, short?.status)
  check('and the code says which rule it broke', codeOf(short) === 'APPLY_SET_MISMATCH', codeOf(short))
  check(
    'the detail names what was missing, so a client can say so',
    (short?.response.data.detail.missing as number[])?.join(',') === String(plan[0]!.id) &&
      (short?.response.data.detail.expected as number[])?.length === plan.length,
    short?.response.data.detail,
  )
  check('the board was not touched', orderOf(be.project(sc)) === untouched)

  const foreign = expectThrows(() =>
    be.applyPhases(sc, { phases: [...plan, { id: 999_999, name: '남의 것' }], deleted_ids: [] }),
  )
  check('an id from outside the board is refused', codeOf(foreign) === 'APPLY_OUT_OF_SCOPE', codeOf(foreign))

  const blank = expectThrows(() =>
    be.applyPhases(sc, { phases: plan.map((e, i) => (i === 0 ? { ...e, name: '  ' } : e)), deleted_ids: [] }),
  )
  check('an empty name is refused', codeOf(blank) === 'APPLY_EMPTY_NAME', codeOf(blank))

  const dupName = expectThrows(() =>
    be.applyPhases(sc, { phases: plan.map((e) => ({ ...e, name: '같은 이름' })), deleted_ids: [] }),
  )
  check('duplicate names are refused', codeOf(dupName) === 'APPLY_DUPLICATE_NAME', codeOf(dupName))

  // The id repeats, the name does **not**. Repeating the whole entry trips the
  // duplicate-*name* rule first, so this check passed on the wrong code until the
  // assertions started naming the code they expect.
  const dupId = expectThrows(() =>
    be.applyPhases(sc, {
      phases: [...plan, { id: plan[0]!.id, name: '이름은 다르지만 같은 id' }],
      deleted_ids: [],
    }),
  )
  check('the same id twice is refused', codeOf(dupId) === 'APPLY_DUPLICATE_ID', codeOf(dupId))

  const both = expectThrows(() =>
    be.applyPhases(sc, { phases: plan, deleted_ids: [plan[0]!.id!] }),
  )
  check('keeping and deleting the same id is refused', codeOf(both) === 'APPLY_DUPLICATE_ID', codeOf(both))

  check('after six refusals the board is byte-identical', orderOf(be.project(sc)) === untouched)
  check(
    'NEGATIVE CONTROL — the well-formed payload those were derived from is accepted',
    be.applyPhases(sc, { phases: plan, deleted_ids: [] }).items.length === 4,
  )

  // A PUBLISHED version is not editable through this path either (`plan.md` §2.4).
  const published = publishedVersionId(be, be.listTemplates()[0]!.id)
  const onPublished = expectThrows(() =>
    be.applyPhases(be.versionScope(published!), { phases: [], deleted_ids: [] }),
  )
  check('a PUBLISHED version refuses the call', onPublished?.status === 409, onPublished?.status)
})

section('18. milestones/apply — same rules, confined to one phase')
guard(() => {
  const bench = makeMilestoneBench([
    [0, 0],
    [0, 1],
    [1, 0],
    [1, 1],
    [1, 2],
    [2, 0],
  ])
  const { backend: be, scope: sc, phases } = bench
  const target = phases[1]!.id
  const before = be.project(sc)
  check('setup: phase 1 owns three milestone blocks', msNos(before) === '0.1,0.2,1.1,1.2,1.3,2.1', msNos(before))
  const outsideOrder = before.filter((r) => r.phase_id !== target).map((r) => r.id).join(',')

  const plan = milestonePlan(be, sc, target)
  check('the popup lists only that phase\'s milestones', plan.length === 3, plan.length)

  // ── Move the third milestone to the front of the phase. ──
  const reordered = be.applyMilestones(sc, target, {
    milestones: [plan[2]!, plan[0]!, plan[1]!],
    deleted_ids: [],
  })
  check(
    'the milestone blocks reordered inside the phase',
    reordered.items.slice(2, 5).map((r) => r.milestone_id).join(',') ===
      [plan[2]!.id, plan[0]!.id, plan[1]!.id].join(','),
    reordered.items.slice(2, 5).map((r) => r.milestone_no),
  )
  check('numbering followed the new order', msNos(reordered.items) === '0.1,0.2,1.1,1.2,1.3,2.1', msNos(reordered.items))
  check(
    'and it really moved — the row that was 1.3 is now 1.1',
    reordered.items[2]!.id === before[4]!.id,
    [reordered.items[2]!.id, before[4]!.id],
  )
  check(
    'rows of other phases did not move',
    reordered.items.filter((r) => r.phase_id !== target).map((r) => r.id).join(',') === outsideOrder,
  )
  check('contiguous at both levels', isContiguous(reordered.items, 'phase_id') && isContiguous(reordered.items, 'milestone_id'))

  // ── A new milestone with no anchor brings its own row. ──
  const plan2 = milestonePlan(be, sc, target)
  const added = be.applyMilestones(sc, target, {
    milestones: [...plan2, { id: null, name: '새 마일스톤' }],
    deleted_ids: [],
  })
  check('one row was created for it', added.items.length === before.length + 1, added.items.length)
  const newRow = added.items.find((r) => r.milestone_name === '새 마일스톤')
  check('the row belongs to the right phase and the new milestone', newRow?.phase_id === target && newRow?.milestone_id != null)
  check('it is numbered 1.4, at the end of the phase block', newRow?.milestone_no === 4 && newRow?.phase_no === 1, [newRow?.phase_no, newRow?.milestone_no])
  check('still contiguous', isContiguous(added.items, 'milestone_id'))

  // ── Cascade delete of a milestone. ──
  const plan3 = milestonePlan(be, sc, target)
  const doomed = plan3[0]!.id!
  const doomedRows = added.items.filter((r) => r.milestone_id === doomed).length
  check('setup: the milestone about to go owns rows', doomedRows > 0, doomedRows)
  const cut = be.applyMilestones(sc, target, {
    milestones: plan3.filter((e) => e.id !== doomed),
    deleted_ids: [doomed],
  })
  check('its rows went with it', cut.items.length === added.items.length - doomedRows)
  check('nothing references it', !cut.items.some((r) => r.milestone_id === doomed))
  check('sort_order contiguous after the cascade', cut.items.every((r, i) => r.sort_order === i + 1))
  check('the surviving milestones renumbered from 1 with no gap', msNos(cut.items) === '0.1,0.2,1.1,1.2,1.3,2.1', msNos(cut.items))
  check('the phase itself survived', cut.items.some((r) => r.phase_id === target))

  const mismatch = expectThrows(() =>
    be.applyMilestones(sc, target, { milestones: milestonePlan(be, sc, target).slice(1), deleted_ids: [] }),
  )
  check('the set-match rule applies here too', codeOf(mismatch) === 'APPLY_SET_MISMATCH', codeOf(mismatch))

  const foreignPhase = expectThrows(() =>
    be.applyMilestones(sc, 999_999, { milestones: [], deleted_ids: [] }),
  )
  check('an unknown phase id is refused', codeOf(foreignPhase) === 'APPLY_OUT_OF_SCOPE', codeOf(foreignPhase))

  const crossPhase = expectThrows(() =>
    be.applyMilestones(sc, phases[0]!.id, {
      milestones: milestonePlan(be, sc, target),
      deleted_ids: [],
    }),
  )
  check(
    'a milestone of another phase cannot be listed under this one',
    codeOf(crossPhase) === 'APPLY_OUT_OF_SCOPE',
    codeOf(crossPhase),
  )
})

section('18b. The milestone anchor also takes a fully gray row (plan.md 0.4, lead 2026-08-08)')
guard(() => {
  const bench = makeMilestoneBench([
    [0, 0],
    [0, 1],
    null,
    [1, 0],
    [1, 1],
  ])
  const { backend: be, scope: sc, phases } = bench
  const target = phases[0]!.id
  const rows = be.project(sc)
  const gray = rows[2]!
  check('setup: a fully gray row sitting between the two phase blocks', isGray(gray))

  const plan = milestonePlan(be, sc, target)
  const created = be.applyMilestones(sc, target, {
    milestones: [...plan, { id: null, name: '회색 앵커 마일스톤' }],
    deleted_ids: [],
    anchor_item_id: gray.id,
  })
  check('no row was invented — the gray row became the new milestone\'s row', created.items.length === rows.length, created.items.length)
  const landed = created.items.find((r) => r.id === gray.id)!
  check('it picked up BOTH the phase and the new milestone', landed.phase_id === target && landed.milestone_name === '회색 앵커 마일스톤')
  check('numbered 0.3, at the end of its phase block', landed.phase_no === 0 && landed.milestone_no === 3, [landed.phase_no, landed.milestone_no])
  check(
    'and it was pulled inside the phase block rather than left where it stood',
    created.items.findIndex((r) => r.id === gray.id) === 2,
    created.items.map((r) => `${r.phase_no}.${r.milestone_no ?? '-'}`),
  )
  check('board contiguous at both levels', isContiguous(created.items, 'phase_id') && isContiguous(created.items, 'milestone_id'))
  check('renumbered 1..N', sequential(created.items))

  // A row already carrying a *different* phase is still refused: its milestone would then
  // belong to a phase the row does not.
  const other = makeMilestoneBench([
    [0, 0],
    [1, 0],
  ])
  const otherRows = other.backend.project(other.scope)
  const wrongPhase = expectThrows(() =>
    other.backend.applyMilestones(other.scope, other.phases[0]!.id, {
      milestones: [...milestonePlan(other.backend, other.scope, other.phases[0]!.id), { id: null, name: 'x' }],
      deleted_ids: [],
      anchor_item_id: otherRows[1]!.id,
    }),
  )
  check(
    'NEGATIVE CONTROL — a row belonging to another phase is still refused',
    codeOf(wrongPhase) === 'APPLY_ANCHOR_INVALID',
    codeOf(wrongPhase),
  )
})

section('18c. A gray row survives the block it was attached to (lead 2026-08-08)')
guard(() => {
  const bench = makeBench([0, 0, null, 1, 1])
  const { backend: be, scope: sc } = bench
  const rows = be.project(sc)
  const grayId = rows[2]!.id
  const plan = phasePlan(be, sc)
  check('setup: a gray row at the tail of Phase 0\'s block', isGray(rows[2]!) && plan.length === 2)

  const afterDelete = be.applyPhases(sc, {
    phases: plan.filter((e) => e.id !== plan[0]!.id),
    deleted_ids: [plan[0]!.id!],
  })
  check('the deleted phase took its two assigned rows', afterDelete.items.length === 3, afterDelete.items.length)
  check('but NOT the gray row — it is still on the board', afterDelete.items.some((r) => r.id === grayId))
  check('it kept its position at the top, with no block above it to follow', afterDelete.items[0]!.id === grayId)
  check('it is still gray', isGray(afterDelete.items.find((r) => r.id === grayId)!))
  check('sort_order contiguous', afterDelete.items.every((r, i) => r.sort_order === i + 1))
  check('the survivors renumbered from the start number', phaseNos(afterDelete.items) === ',0,0', phaseNos(afterDelete.items))

  // …and one that had a surviving block above it reattaches to that block instead.
  const mid = makeBench([0, 1, null, 2])
  const midRows = mid.backend.project(mid.scope)
  const midGray = midRows[2]!.id
  const midPlan = phasePlan(mid.backend, mid.scope)
  const cut = mid.backend.applyPhases(mid.scope, {
    phases: midPlan.filter((e) => e.id !== midPlan[1]!.id),
    deleted_ids: [midPlan[1]!.id!],
  })
  check('the gray row survived here too', cut.items.some((r) => r.id === midGray))
  check(
    'and reattached to the surviving block above it',
    cut.items[0]!.phase_id === midPlan[0]!.id && cut.items[1]!.id === midGray,
    cut.items.map((r) => `${r.id}:${r.phase_no}`),
  )
  check('contiguous, renumbered', isContiguous(cut.items, 'phase_id') && sequential(cut.items))
})

section('19. Both applies work identically on a project (plan.md 0.1)')
guard(() => {
  const be = new MockBackend(7)
  const projectId = be.listProjects(7)[0]!.id
  const sc = be.projectScope(projectId)
  const rows = be.project(sc)
  check('setup: the maker project opened with the copied board', rows.length === 35, rows.length)

  const plan = phasePlan(be, sc)
  check('a project has its own phase copies', plan.length === 4, plan.length)
  const before = phaseNos(rows)

  const applied = be.applyPhases(sc, {
    phases: [plan[1]!, plan[0]!, ...plan.slice(2)],
    deleted_ids: [],
  })
  check('swapping the first two blocks works on a project', applied.items[0]!.phase_id === plan[1]!.id)
  check('numbers recomputed', applied.items[0]!.phase_no === 0 && phaseNos(applied.items) !== before)
  check('rows renumbered 1..N', sequential(applied.items))
  check('contiguous', isContiguous(applied.items, 'phase_id'))

  const phaseId = applied.items[0]!.phase_id!
  const msPlan = milestonePlan(be, sc, phaseId)
  check('setup: that phase has at least two milestones', msPlan.length >= 2, msPlan.length)
  const msApplied = be.applyMilestones(sc, phaseId, {
    milestones: [msPlan[msPlan.length - 1]!, ...msPlan.slice(0, -1)],
    deleted_ids: [],
  })
  check('milestone apply works on a project too', msApplied.items[0]!.milestone_id === msPlan[msPlan.length - 1]!.id)
  check('contiguous at both levels', isContiguous(msApplied.items, 'phase_id') && isContiguous(msApplied.items, 'milestone_id'))

  // The tiers are separate sets; the template it was copied from must be untouched.
  const templateId = be.listTemplates()[0]!.id
  const templatePhases = be.listPhases({ kind: 'template', templateId })
  check(
    'the central template kept its own phase order',
    templatePhases.map((p) => p.name).join(',') !== applied.phases.map((p) => p.name).join(','),
    [templatePhases.map((p) => p.seq_no), applied.phases.map((p) => p.seq_no)],
  )
  const draftId = be.listVersions(templateId).find((v) => v.status === 'DRAFT')!.id
  check(
    'and the template board itself never moved',
    phaseNos(be.project(be.versionScope(draftId))) === before,
  )

  const crossTier = expectThrows(() =>
    be.applyPhases(be.versionScope(draftId), { phases: plan, deleted_ids: [] }),
  )
  check('project phase ids cannot be applied to the template', crossTier?.status === 422, crossTier?.status)
})

section('20. dash_label — the dashboard caption column (plan.md 0.5-1)')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const draftId = be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id
  const sc = be.versionScope(draftId)

  const seeded = be.project(sc)
  check('every seed row carries a label', seeded.every((r) => !!r.dash_label), seeded.filter((r) => !r.dash_label).length)
  check('the first is the deck caption, not the deliverable', seeded[0]!.dash_label === 'Gap·자원 계획', seeded[0]!.dash_label)
  check('and it is NOT the title', seeded[0]!.dash_label !== seeded[0]!.title)

  // Round trip through the unvalidated save — the path 임시저장 and 저장 both take.
  const payload = toPayload(seeded)
  payload[2] = { ...payload[2]!, dash_label: '바꿈 라벨' }
  payload[3] = { ...payload[3]!, dash_label: null }
  const saved = be.saveItems(sc, payload)
  check('an edited label round-trips', saved[2]!.dash_label === '바꿈 라벨', saved[2]!.dash_label)
  check('clearing one is legal — no validation on this path', saved[3]!.dash_label === null)
  check('the others are untouched', saved[0]!.dash_label === seeded[0]!.dash_label)

  // 발행 must not care about it: a blank caption is never an error (§0.5-1 adds no rule).
  const result = be.validate(draftId)
  check(
    'a null dash_label does not block publish',
    result.valid && !result.errors.some((e) => String(e.code).includes('DASH')),
    result.errors.slice(0, 3),
  )

  const grayItems = be.appendRow(sc)
  check('a new gray row starts with no label', grayItems[grayItems.length - 1]!.dash_label === null)

  // Both deep-copy paths carry it (§0.5-1): draft creation…
  const fresh = new MockBackend(1)
  const ft = fresh.listTemplates()[0]!
  fresh.discardDraft(fresh.listVersions(ft.id).find((v) => v.status === 'DRAFT')!.id)
  const recopied = fresh.project(fresh.versionScope(fresh.deepCopyToDraft(ft.id).id))
  check('draft deep copy keeps labels', recopied[0]!.dash_label === seeded[0]!.dash_label, recopied[0]!.dash_label)

  // …and project creation, which copies from the PUBLISHED version.
  const projectItems = fresh.getProject(fresh.listProjects(1)[0]!.id).items
  check('project deep copy keeps labels', projectItems[0]!.dash_label === seeded[0]!.dash_label, projectItems[0]!.dash_label)
  check('all 35 of them', projectItems.filter((r) => !!r.dash_label).length === 35, projectItems.filter((r) => !!r.dash_label).length)

  /*
   * The §0.4 apply paths are the third way a row comes into existence: a phase created with
   * no anchor gets a blank row, because "행 없는 Phase 는 존재할 수 없다". That row goes
   * through `blankRow()` and the apply response goes through `project()`, so both have to
   * carry the column — flagged by fe-apply, and worth an assertion rather than a reading of
   * the code, since an apply response that silently dropped the labels would look exactly
   * like a successful renumber.
   */
  const applied = be.applyPhases(sc, {
    phases: [...phasePlan(be, sc), { id: null, name: '라벨 검증용 Phase' }],
    deleted_ids: [],
  })
  const born = applied.items[applied.items.length - 1]!
  check('a phase created by apply brings a blank row', born.phase_id != null && !born.title)
  check('…whose label is null, not undefined', born.dash_label === null, born.dash_label)
  check(
    'and every pre-existing row kept its label through the apply',
    applied.items.filter((r) => !!r.dash_label).length === 34,
    applied.items.filter((r) => !!r.dash_label).length,
  )

  const msApplied = be.applyMilestones(sc, applied.items[0]!.phase_id!, {
    milestones: [...milestonePlan(be, sc, applied.items[0]!.phase_id!), { id: null, name: '라벨 검증용 MS' }],
    deleted_ids: [],
  })
  check(
    'the milestone apply does not lose them either',
    msApplied.items.filter((r) => !!r.dash_label).length === 34,
    msApplied.items.filter((r) => !!r.dash_label).length,
  )
})

section('21. 전체 현황 payload (plan.md 0.5-3)')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const v1 = be.listVersions(t.id).find((v) => v.status === 'PUBLISHED')!

  // A second maker, so the overview is proven to cross makers rather than filter to one.
  const second = { project: be.createProject({
    maker_id: 2,
    name: '2026 AI 과제 2차',
    template_id: t.id,
    template_version_id: v1.id,
  }) }

  const first = be.listProjects(1)[0]!
  const sc = be.projectScope(first.id)

  // Give it a status mix plus one gray row, so the tally and the null band both have
  // something to be wrong about.
  const rows = be.project(sc)
  const payload = toPayload(rows)
  payload[0] = { ...payload[0]!, status: 'DONE' }
  payload[1] = { ...payload[1]!, status: 'DONE' }
  payload[2] = { ...payload[2]!, status: 'IN_PROGRESS' }
  payload[3] = { ...payload[3]!, status: 'HOLD' }
  payload[4] = { ...payload[4]!, status: 'NA' }
  payload[10] = { ...payload[10]!, phase_id: null, milestone_id: null }
  const savedRows = be.saveItems(sc, payload)

  const overview = be.projectsOverview()
  const flat = overview.makers.flatMap((m) => m.projects)
  check('the response is grouped by maker (plan.md 0.6)', Array.isArray(overview.makers) && overview.makers.length === 2, overview.makers.length)
  check('both makers are present — the screen is maker-free', flat.length === 2, flat.length)
  check('and they are different makers', new Set(overview.makers.map((m) => m.maker_id)).size === 2)

  const one = flat.find((p) => p.id === first.id)!
  /*
   * The fixture now has a resolver stand-in (`plan.md` §0.6), so names come through here.
   * The **null** case — a host that wired no resolver — is a normal state and is asserted in
   * §22c against a backend built with `{ resolver: false }`.
   */
  check('a resolved maker name comes through', one.maker_name === 'A설비 주식회사', one.maker_name)
  check('maker_id is carried through', one.maker_id === 1)
  check(
    'and the section carries the same name the projects do',
    overview.makers.find((m) => m.maker_id === 1)!.name === one.maker_name,
  )

  const total = Object.values(one.counts).reduce((sum, n) => sum + n, 0)
  check('counts add up to the item count', total === one.items.length, [total, one.items.length])
  check('counts are the real tally', one.counts.DONE === 2 && one.counts.IN_PROGRESS === 1 && one.counts.HOLD === 1 && one.counts.NA === 1, one.counts)
  check(
    'counts agree with the board itself',
    one.counts.DONE === savedRows.filter((r) => r.status === 'DONE').length,
  )

  check('items are in sort_order — no is 1..N', one.items.every((item, i) => item.no === i + 1), one.items.slice(0, 3))
  check(
    'phase_seq is the display number, matching the board',
    one.items.every((item, i) => item.phase_seq === savedRows[i]!.phase_no),
  )
  check(
    'the gray row carries nulls at both levels',
    one.items[10]!.phase_seq === null && one.items[10]!.milestone_seq === null,
    one.items[10],
  )
  check('and no other row does', one.items.filter((i) => i.phase_seq === null).length === 1)
  check('dash_label rides along for the tooltip', one.items[0]!.dash_label === savedRows[0]!.dash_label)

  /*
   * The overview payload carries no `deliverable` and no `title`, so the §0.5-1 fallback
   * chain cannot run on the client — it is resolved server-side and this field arrives
   * already display-ready (INTEGRATION.md §7.6). Without that, every unlabelled row would
   * render as "(내용 없음)", which on a fresh project is all 35 of them.
   */
  const stripped = toPayload(savedRows)
  stripped[6] = { ...stripped[6]!, dash_label: null }
  stripped[7] = { ...stripped[7]!, dash_label: null, deliverable: null }
  be.saveItems(sc, stripped)
  const resolved = be.projectsOverview().makers.flatMap((m) => m.projects).find((p) => p.id === first.id)!
  check(
    'a row with no label falls back to its deliverable',
    resolved.items[6]!.dash_label === savedRows[6]!.deliverable,
    resolved.items[6]!.dash_label,
  )
  check(
    'and with neither, to the head of the title',
    !!resolved.items[7]!.dash_label && savedRows[7]!.title!.startsWith(resolved.items[7]!.dash_label!.replace('…', '')),
    resolved.items[7]!.dash_label,
  )
  check('the raw row itself still reads null — only the overview resolves it', be.project(sc)[6]!.dash_label === null)

  // Only active projects (§0.5-3). Deletion is a deactivation everywhere in this codebase.
  be.deleteProject(second.project.id)
  const afterFlat = be.projectsOverview().makers.flatMap((m) => m.projects)
  check('a deactivated project drops out', afterFlat.length === 1 && afterFlat[0]!.id === first.id, afterFlat.map((p) => p.id))
})

section('22. Dashboard grouping (plan.md 0.5-2) — Phase 4개 초과, 회색 행, 조각난 보드')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const draftId = be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id
  const sc = be.versionScope(draftId)

  const base = buildDashboardLayout(be.project(sc))
  check('4 phase columns from the seed board', base.phases.length === 4, base.phases.length)
  check('13 milestone cells in total', base.phases.reduce((n, p) => n + p.milestones.length, 0) === 13)
  check('items per phase 4/10/11/10', base.phases.map((p) => p.itemCount).join(',') === '4,10,11,10', base.phases.map((p) => p.itemCount))
  check('every row landed in exactly one cell', base.phases.reduce((n, p) => n + p.milestones.reduce((m, ms) => m + ms.items.length, 0), 0) === 35)
  check('nothing unassigned yet', base.unassigned.length === 0)
  check('column order is first-appearance', base.phases.map((p) => p.phaseSeq).join(',') === '0,1,2,3')
  check('counts come out of the same pass', base.counts.NOT_STARTED === 35 && base.total === 35, base.counts)

  // ── 회색 행: it leaves the grid for the trailing 미배정 column, wherever it stands.
  const withGray = be.insertBelow(sc, be.project(sc)[2]!.id)
  const grayLayout = buildDashboardLayout(withGray)
  check('a gray row does not join a phase column', grayLayout.phases.reduce((n, p) => n + p.itemCount, 0) === 35)
  check('it goes to 미배정 instead', grayLayout.unassigned.length === 1)
  check('even though it sits mid-board', withGray[3]!.phase_id === null && withGray[3]!.row_no === 4)
  check('still 4 phase columns', grayLayout.phases.length === 4)

  // ── Phase 4개 초과: the palette cycles instead of running out.
  const grayId = withGray[3]!.id
  be.setMembership(sc, grayId, { phase_id: null, milestone_id: null })
  const tail = be.appendRow(sc)
  be.createPhaseFromRow(sc, tail[tail.length - 1]!.id, { name: 'Phase 4 검증' })
  const tail2 = be.appendRow(sc)
  be.createPhaseFromRow(sc, tail2[tail2.length - 1]!.id, { name: 'Phase 5 검증' })

  const wide = buildDashboardLayout(be.project(sc))
  check('6 phase columns render', wide.phases.length === 6, wide.phases.length)
  check('numbers keep going', wide.phases.map((p) => p.phaseSeq).join(',') === '0,1,2,3,4,5')
  check(
    'the palette cycles at 4 rather than returning undefined',
    wide.phases[4]!.color === DASH_PHASE_COLORS[0] && wide.phases[5]!.color === DASH_PHASE_COLORS[1],
    [wide.phases[4]!.color, wide.phases[5]!.color],
  )
  check('every column still has a colour', wide.phases.every((p) => !!p.color))
  check('the mid-board gray row is still in 미배정', wide.unassigned.some((r) => r.id === grayId))

  // A phase whose row has no milestone yet — legal until 발행, so it must render.
  const noMilestone = wide.phases[4]!.milestones
  check('a phase with no milestone gets one nameless bucket', noMilestone.length === 1 && noMilestone[0]!.milestoneId === null, noMilestone.length)
  check('labelled 미지정 with no number', noMilestone[0]!.name === '미지정' && noMilestone[0]!.numberLabel === '')

  // ── A fragmented board is one column, not two identically-labelled ones.
  const fresh = new MockBackend(1)
  const fsc = fresh.versionScope(
    fresh.listVersions(fresh.listTemplates()[0]!.id).find((v) => v.status === 'DRAFT')!.id,
  )
  const fRows = fresh.project(fsc)
  const interleaved = toPayload([fRows[0]!, fRows[4]!, fRows[1]!, ...fRows.slice(5), fRows[2]!, fRows[3]!])
  const broken = fresh.saveItems(fsc, interleaved)
  check('setup: the board really is fragmented', fresh.contiguityErrors(broken).length > 0)
  const merged = buildDashboardLayout(broken)
  check('a fragmented phase is still one column', merged.phases.filter((p) => p.phaseSeq === 0).length === 1)
  check('no phase id appears twice', new Set(merged.phases.map((p) => p.phaseId)).size === merged.phases.length)
  check('and no row was dropped', merged.phases.reduce((n, p) => n + p.itemCount, 0) + merged.unassigned.length === 35)

  // ── Card text fallback chain (§0.5-1).
  check('dash_label wins', dashboardText({ dash_label: 'A', deliverable: 'B', title: 'C' }) === 'A')
  check('then deliverable', dashboardText({ dash_label: null, deliverable: 'B', title: 'C' }) === 'B')
  check('blank counts as absent', dashboardText({ dash_label: '   ', deliverable: 'B', title: 'C' }) === 'B')
  check('then a truncated title', dashboardText({ dash_label: null, deliverable: null, title: 'x'.repeat(40) }, 10) === `${'x'.repeat(10)}…`)
  check('a short title is not truncated', dashboardText({ dash_label: null, deliverable: null, title: 'abc' }, 10) === 'abc')
  check('and an empty row yields an empty string, not a crash', dashboardText({ dash_label: null, deliverable: null, title: null }) === '')

  // ── 주관 (좌측 바) classification.
  check('two owners is 공동 outright', ownerKind([{ id: 1, name: 'DSEP 인프라' }, { id: 2, name: '설비사' }]) === 'JOINT')
  check('a single DSEP owner', ownerKind([{ id: 1, name: 'DSEP 인프라 담당자' }]) === 'DSEP')
  check('a single 설비사 owner', ownerKind([{ id: 1, name: '설비사' }]) === 'MAKER')
  check('a named 공동 owner', ownerKind([{ id: 1, name: '공동(구매·법무)' }]) === 'JOINT')
  check('anything else is 사내 개발부서', ownerKind([{ id: 1, name: '사내 개발부서' }]) === 'INTERNAL_DEV')
  check('no owner at all', ownerKind([]) === 'NONE' && ownerKind(null) === 'NONE')
})

section('22b. 미니 대시보드 밴딩 (plan.md 0.5-3 개정) — 라벨이 붙었으므로 run 이 아니라 group')
guard(() => {
  const cell = (no: number, phase: number | null, ms: number | null = null) => ({
    no,
    status: 'NOT_STARTED' as ItemStatus,
    phase_seq: phase,
    milestone_seq: ms,
    dash_label: null,
    title: null,
    deliverable: null,
    owners: [] as string[],
  })

  /*
   * The reversal, asserted directly. While the bands were unlabelled this input produced
   * FOUR bands (P0, gray, P0, P1) because banding followed contiguous runs. §0.5-3's revision
   * puts a visible `Phase N` on each band, and two bands reading `Phase 0` is not a picture
   * of anything — so the same input must now produce three groups with 미배정 at the back.
   */
  const groups = buildOverviewGroups([cell(1, 0), cell(2, 0), cell(3, null), cell(4, 0), cell(5, 1)])
  check('a fragmented phase is ONE labelled band, not two', groups.length === 3, groups.map((g) => g.label))
  check('…and it holds all three of its cells', groups[0]!.itemCount === 3, groups[0]!.itemCount)
  check('bands are labelled Phase N', groups[0]!.label === 'Phase 0' && groups[1]!.label === 'Phase 1')
  check('미배정 is forced to the back regardless of where it fell', groups[2]!.label === '미배정')
  check('and has no colour', groups[2]!.color === null && groups[0]!.color === DASH_PHASE_COLORS[0])
  check('no cell is lost', groups.reduce((n, g) => n + g.itemCount, 0) === 5)

  // 마일스톤 소그룹 (§0.5-3): cells cluster by milestone inside the band.
  const withMs = buildOverviewGroups([
    cell(1, 0, 1),
    cell(2, 0, 1),
    cell(3, 0, 2),
    cell(4, 0, null),
    cell(5, 1, 1),
  ])
  check('cells subgroup by milestone inside a band', withMs[0]!.milestones.length === 3, withMs[0]!.milestones.map((m) => m.label))
  check('the first subgroup keeps both of its cells', withMs[0]!.milestones[0]!.items.length === 2)
  check('subgroup labels are the derived display number', withMs[0]!.milestones[0]!.label === '0.1' && withMs[0]!.milestones[1]!.label === '0.2')
  check('a milestone-less cell gets its own unlabelled subgroup', withMs[0]!.milestones[2]!.milestoneSeq === null && withMs[0]!.milestones[2]!.label === '')
  check('subgroup order is first appearance', withMs[0]!.milestones.map((m) => m.key).join(',') === '1,2,none')

  check('the palette wraps for the 5th phase', dashPhaseColor(4) === DASH_PHASE_COLORS[0])
  check('and a null seq has no colour', dashPhaseColor(null) === null)
  check('an empty project yields no bands', buildOverviewGroups([]).length === 0)
})

section('22c. 설비사 표시 규칙 - three branches (plan.md 0.6)')
guard(() => {
  const be = new MockBackend(1)
  const rows = be.listMakers().makers
  const byId = new Map(rows.map((m) => [m.maker_id, m]))

  /*
   * The rule has exactly three outcomes and each has to be reachable:
   *   설정행 있음 -> 그 값 (on or off, overriding reality)
   *   설정행 없음 -> active 프로젝트가 있으면 표시
   * The third branch is what makes an unconfigured install useful, so it is the default.
   */
  check('the fixture resolver lists 4 makers', rows.length >= 4, rows.length)
  check('maker 1 has the seed project', byId.get(1)!.has_projects === true)
  check('...so it shows without any setting', byId.get(1)!.show_in_overview === true && byId.get(1)!.explicit === false)
  check('maker 4 has no projects', byId.get(4)!.has_projects === false)
  check('...so it is hidden by the derived rule', byId.get(4)!.show_in_overview === false && byId.get(4)!.explicit === false)

  // Explicit ON for a maker with no projects - the empty-section flow of 0.6.
  const afterOn = be.saveMakerSettings([{ maker_id: 4, show_in_overview: true }]).makers
  const four = afterOn.find((m) => m.maker_id === 4)!
  check('ticking a project-less maker turns it on', four.show_in_overview === true)
  check('...and it is now marked explicit', four.explicit === true)
  const sections = be.projectsOverview().makers
  check('it gets an overview section', sections.some((m) => m.maker_id === 4), sections.map((m) => m.maker_id))
  check('...with an empty project list, not a missing one', sections.find((m) => m.maker_id === 4)!.projects.length === 0)

  // Explicit OFF for a maker that DOES have projects - the override in the other direction.
  be.saveMakerSettings([{ maker_id: 1, show_in_overview: false }])
  const hidden = be.projectsOverview().makers
  check('unticking a maker with projects hides it', !hidden.some((m) => m.maker_id === 1), hidden.map((m) => m.maker_id))
  check('but the projects still exist', be.listProjects(1).length === 1)
  check('and the settings row still reports has_projects', be.listMakers().makers.find((m) => m.maker_id === 1)!.has_projects === true)

  // Ordering is the server's now: named by name, unnamed by id.
  const ordered = be.listMakers().makers
  const named = ordered.filter((m) => !!m.name).map((m) => m.name!)
  check('named makers are sorted by name', named.join(',') === [...named].sort((a, b) => a.localeCompare(b, 'ko')).join(','), named)

  const unknown = expectThrows(() => be.saveMakerSettings([{ maker_id: 99999, show_in_overview: true }]))
  check('an unknown maker id is a 422', unknown?.status === 422, unknown?.status)

  // No resolver at all - a normal state, not an error (root INTEGRATION 2.2).
  const bare = new MockBackend(1, { resolver: false })
  const bareRows = bare.listMakers().makers
  check('with no resolver, only makers that own projects appear', bareRows.length === 1 && bareRows[0]!.maker_id === 1, bareRows.map((m) => m.maker_id))
  check('...and their name is null, not a fabricated one', bareRows[0]!.name === null)
  check('...and the overview still renders that section', bare.projectsOverview().makers.length === 1)
})

section('22c-2. 프로젝트 사용 여부 스위치 (설비사 관리)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id

  const listed = be.listMakers().makers.find((m) => m.maker_id === 1)!
  check('a maker row carries its projects', listed.projects.some((p) => p.id === pid), listed.projects.length)
  check('...and they start on', listed.projects.find((p) => p.id === pid)!.is_active === true)

  // off = 전체 현황에서 감추기. 삭제가 아니다.
  const afterOff = be.saveMakerSettings([], [{ id: pid, is_active: false }]).makers
  check('switching one off is reported back immediately', afterOff.find((m) => m.maker_id === 1)!.projects.find((p) => p.id === pid)!.is_active === false)
  check('it leaves 전체 현황', !be.projectsOverview().makers.flatMap((m) => m.projects).some((p) => p.id === pid))
  check('...and drops out of the active list', be.listProjects(1).length === 0)
  /*
   * The one that matters: it has to stay *here*. `listProjects` filters to active, so if the
   * settings screen used that list the switch would erase its own control and off would be a
   * one-way door.
   */
  check('but the settings screen still lists it', be.listMakers().makers.find((m) => m.maker_id === 1)!.projects.some((p) => p.id === pid && !p.is_active))
  check('and the board is untouched', be.getProject(pid).items.length > 0)

  const backOn = be.saveMakerSettings([], [{ id: pid, is_active: true }]).makers
  check('switching it back on restores it', backOn.find((m) => m.maker_id === 1)!.projects.find((p) => p.id === pid)!.is_active === true)
  check('...into 전체 현황 as well', be.projectsOverview().makers.flatMap((m) => m.projects).some((p) => p.id === pid))

  const missing = expectThrows(() => be.saveMakerSettings([], [{ id: 999999, is_active: false }]))
  check('an unknown project id is a 422', missing?.status === 422, missing?.status)
  check('...and nothing was written', be.listMakers().makers.find((m) => m.maker_id === 1)!.projects.find((p) => p.id === pid)!.is_active === true)

  // 부분 목록 규칙: 빈 배열은 "건드리지 말라" 이지 "전부 끄라" 가 아니다.
  be.saveMakerSettings([{ maker_id: 1, show_in_overview: true }])
  check('an omitted projects list leaves projects alone', be.listMakers().makers.find((m) => m.maker_id === 1)!.projects.every((p) => p.is_active))
})

section('22d. 프로젝트명 수정 (plan.md 0.6)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id

  const renamed = be.renameProject(pid, '  이름 바꾼 과제  ')
  check('the name is trimmed and saved', renamed.name === '이름 바꾼 과제', renamed.name)
  check('it survives a re-read', be.listProjects(1)[0]!.name === '이름 바꾼 과제')
  check('and the overview shows the new name', be.projectsOverview().makers.flatMap((m) => m.projects)[0]!.name === '이름 바꾼 과제')

  const empty = expectThrows(() => be.renameProject(pid, '   '))
  check('an empty name is a 422', empty?.status === 422, empty?.status)
  check('and nothing changed', be.listProjects(1)[0]!.name === '이름 바꾼 과제')

  const missing = expectThrows(() => be.renameProject(999999, 'x'))
  check('an unknown project is a 404', missing?.status === 404, missing?.status)

  // Renaming touches the name and nothing else - the board is not reloaded or renumbered.
  const before = be.getProject(pid).items.map((r) => r.id).join(',')
  be.renameProject(pid, '또 바꿈')
  check('the rows are untouched by a rename', be.getProject(pid).items.map((r) => r.id).join(',') === before)
})

section('23. \ubb38\uc11c \ubaa8\ub378 — \uc2a4\ucf54\ud504 \uc18c\uc720 + \ubcf5\uc81c (plan.md 0.5.10)')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const draftId = be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id
  const tScope = be.versionScope(draftId)
  const pid = be.listProjects(1)[0]!.id

  const templateDocs = be.listDocuments(tScope).documents
  check('the format owns 5 documents', templateDocs.length === 5, templateDocs.length)
  check('numbered 1..N by the derived no', templateDocs.every((d, i) => d.no === i + 1))
  /*
   * 응답에 `sort_order` 는 없다 (`plan.md` §0.5.10 필드 확정). 목이 저장 필드를 그대로 내보내는
   * 바람에 `npm run check` 는 초록인데 라이브가 깨졌다 — 목과 서버가 서로만 일치하면 검사는
   * 아무것도 지키지 못한다. 이 단언이 그 재발을 막는다.
   */
  check('and the stored sort_order is NOT on the wire', templateDocs.every((d) => !('sort_order' in d)))
  check('with no circled code anywhere', templateDocs.every((d) => !('code' in d)))

  const rowDocs = be.project(tScope)[0]!.documents
  check('a row exposes its documents as {id, no, name}', rowDocs.every((d) => typeof d.no === 'number' && !!d.name))
  check('and `no` matches the document list', rowDocs[0]!.no === templateDocs.find((d) => d.id === rowDocs[0]!.id)!.no)

  // 복제 독립성.
  const projectDocs = be.listProjectDocuments(pid).documents
  check('a project got its own copies', projectDocs.length === 5)
  check(
    'the copy is faithful — same names as the format',
    [...projectDocs.map((d) => d.name)].sort().join('|') === [...templateDocs.map((d) => d.name)].sort().join('|'),
  )
  /*
   * 격리는 **자기 네임스페이스 안에서 해석됨**이지 id 가 겹치지 않음이 아니다. 서버에서는
   * 템플릿 문서와 프로젝트 문서가 별개 테이블·별개 시퀀스라 숫자가 겹칠 수 있고, 실제로
   * liveCheck 가 "겹치면 안 된다" 로 적었다가 멀쩡한 데이터에서 실패했다. 목은 스코프 키를
   * 가진 한 테이블이라 그 상황이 재현되지 않으므로, 단언만이라도 옮겨갈 수 있는 형태로 쓴다.
   */
  check(
    'and every row link resolves inside the project own document list',
    be.getProject(pid).items.every((r) => r.documents.every((d) => projectDocs.some((p) => p.id === d.id))),
  )
  be.saveProjectDocuments(pid, {
    documents: projectDocs.map((d, i) => ({ id: d.id, name: i === 0 ? '프로젝트에서 개명' : d.name, is_used: d.is_used, link_url: d.link_url, doc_status: d.doc_status })),
    deleted_ids: [],
  })
  check('renaming in the project leaves the format alone', be.listDocuments(tScope).documents[0]!.name === templateDocs[0]!.name)

  // apply: 순서가 곧 번호, 추가·삭제·캐스케이드.
  const applied = be.applyTemplateDocuments(tScope, {
    documents: [
      { id: templateDocs[1]!.id, name: templateDocs[1]!.name },
      { id: templateDocs[0]!.id, name: '이름도 바꿈' },
      ...templateDocs.slice(2).map((d) => ({ id: d.id, name: d.name })),
      { id: null, name: '새 문서' },
    ],
    deleted_ids: [],
  })
  check('array order becomes the display number', applied.documents.every((d, i) => d.no === i + 1))
  check('reordering really reordered', applied.documents[0]!.id === templateDocs[1]!.id)
  check('rename applied', applied.documents[1]!.name === '이름도 바꿈')
  check('a new document got a real id', applied.documents.at(-1)!.id > 0 && applied.documents.at(-1)!.name === '새 문서')
  check('the response carries the recomputed rows', Array.isArray(applied.items) && applied.items.length === 35)
  check('and the row numbers followed the reorder', applied.items.find((r) => r.documents.some((d) => d.id === templateDocs[1]!.id))!.documents.find((d) => d.id === templateDocs[1]!.id)!.no === 1)

  // 삭제 캐스케이드 — 링크가 끊어진 행이 응답에 실려 온다.
  const doomed = applied.documents[0]!
  const usersBefore = applied.items.filter((r) => r.documents.some((d) => d.id === doomed.id)).length
  check('setup: some rows link the doomed document', usersBefore > 0, usersBefore)
  const afterDelete = be.applyTemplateDocuments(tScope, {
    documents: applied.documents.filter((d) => d.id !== doomed.id).map((d) => ({ id: d.id, name: d.name })),
    deleted_ids: [doomed.id],
  })
  check('the document is gone', !afterDelete.documents.some((d) => d.id === doomed.id))
  check('and every row link to it went with it', afterDelete.items.every((r) => !r.documents.some((d) => d.id === doomed.id)))
  /*
   * 위 단언만으로는 부족하다 — `project()` 가 해석되지 않는 id 를 조용히 버리므로, 저장된
   * 링크가 그대로 남아 있어도 통과한다 (일부러 unlink 를 지워보고 확인했다). 저장된 상태를
   * 직접 본다.
   */
  check(
    'and the STORED links are gone too, not merely hidden by the projection',
    be.rawDocumentLinks(tScope).every((ids) => !ids.includes(doomed.id)),
  )
  check('the survivors were renumbered 1..N', afterDelete.documents.every((d, i) => d.no === i + 1))

  // 집합 불일치 / 빈 이름 / 중복 / 스코프 밖 id — 전부 422.
  const missing = expectThrows(() =>
    be.applyTemplateDocuments(tScope, { documents: [{ id: afterDelete.documents[0]!.id, name: 'x' }], deleted_ids: [] }),
  )
  check('an incomplete list is a 422', missing?.status === 422 && codeOf(missing) === 'DOCUMENT_SET_MISMATCH', codeOf(missing))
  const blank = expectThrows(() =>
    be.applyTemplateDocuments(tScope, { documents: afterDelete.documents.map((d, i) => ({ id: d.id, name: i === 0 ? '  ' : d.name })), deleted_ids: [] }),
  )
  check('a blank name is a 422', codeOf(blank) === 'DOCUMENT_EMPTY_NAME', codeOf(blank))
  const dup = expectThrows(() =>
    be.applyTemplateDocuments(tScope, { documents: afterDelete.documents.map((d) => ({ id: d.id, name: '같은 이름' })), deleted_ids: [] }),
  )
  check('duplicate names are a 422', codeOf(dup) === 'DOCUMENT_DUPLICATE_NAME', codeOf(dup))
  const foreign = expectThrows(() =>
    be.applyTemplateDocuments(tScope, { documents: [...afterDelete.documents.map((d) => ({ id: d.id, name: d.name })), { id: 999999, name: 'x' }], deleted_ids: [] }),
  )
  check('an id from another scope is a 422', codeOf(foreign) === 'DOCUMENT_OUT_OF_SCOPE', codeOf(foreign))
})

section('23b. \ud504\ub85c\uc81d\ud2b8 \ubb38\uc11c \ub4f1\ub85d (plan.md 0.5.10)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id
  const docs = be.listProjectDocuments(pid).documents

  check('the seeded mix survived the copy', new Set(docs.map((d) => d.doc_status)).size === 3, docs.map((d) => d.doc_status))
  check('one is unused', docs.filter((d) => !d.is_used).length === 1)
  check('links came across', docs.some((d) => !!d.link_url))

  // 프로젝트 로컬 문서 추가 (사용자 확정 2).
  const withNew = be.saveProjectDocuments(pid, {
    documents: [
      ...docs.map((d) => ({ id: d.id, name: d.name, is_used: d.is_used, link_url: d.link_url, doc_status: d.doc_status })),
      { id: null, name: '프로젝트 로컬 문서', is_used: true, link_url: 'https://x.example.com', doc_status: 'WRITING' as const },
    ],
    deleted_ids: [],
  })
  check('a project-local document can be added', withNew.documents.length === 6)
  /*
   * 6개 중 하나(픽스처의 4번째)가 미사용이므로 표시 번호는 **5** 다 — 저장 위치가 6번째라는
   * 것과 표시 번호가 6이라는 것은 다른 이야기다 (§0.5.10 정밀화).
   */
  check('numbered at the end of the USED documents', withNew.documents.at(-1)!.no === 5, withNew.documents.map((d) => d.no))
  check('and the unused one still has none', withNew.documents.filter((d) => d.no == null).length === 1)
  check('and the format never saw it', be.listDocuments(be.versionScope(be.listVersions(be.listTemplates()[0]!.id).find((v) => v.status === 'DRAFT')!.id)).documents.length === 5)

  // 삭제 캐스케이드 + 응답의 items.
  const doomed = withNew.documents[0]!
  const removed = be.saveProjectDocuments(pid, {
    documents: withNew.documents.filter((d) => d.id !== doomed.id).map((d) => ({ id: d.id, name: d.name, is_used: d.is_used, link_url: d.link_url, doc_status: d.doc_status })),
    deleted_ids: [doomed.id],
  })
  check('deleting unlinks it from the rows', (removed.items ?? []).every((r) => !r.documents.some((d) => d.id === doomed.id)))
  check(
    'and renumbers the remaining USED documents 1..N',
    removed.documents.filter((d) => d.is_used).every((d, i) => d.no === i + 1),
    removed.documents.map((d) => d.no),
  )

  // overview 는 사용 체크된 것만, 숫자 표기로.
  const overview = be.projectsOverview().makers.flatMap((m) => m.projects).find((p) => p.id === pid)!
  check('overview sends only the used documents', overview.documents.every((d) => d.no > 0))
  check('…with a numeric display order, not a code', overview.documents.every((d) => typeof d.no === 'number'))
  check('…and the unused one is absent', overview.documents.length === removed.documents.filter((d) => d.is_used).length)
})

section('24. overview item carries what the shared popover needs (plan.md 0.5-3)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id
  const item = be.projectsOverview().makers.flatMap((m) => m.projects).find((p) => p.id === pid)!.items[0]!
  const row = be.getProject(pid).items[0]!

  check('title comes through in full', item.title === row.title, item.title)
  check('deliverable too', item.deliverable === row.deliverable)
  check('owners arrive as NAMES, not ids', Array.isArray(item.owners) && item.owners.every((o) => typeof o === 'string'), item.owners)
  check('and they match the board row', item.owners.join('|') === row.owners.map((o) => o.name).join('|'))
  check('dash_label still carries the resolved fallback', item.dash_label === row.dash_label)

  // The popover shows a joint owner explicitly, so a multi-owner row has to survive.
  const joint = be.projectsOverview().makers.flatMap((m) => m.projects)[0]!.items.find((i) => i.owners.length > 1)
  check('a multi-owner row keeps every name', !!joint && joint.owners.length >= 2, joint?.owners)
})

section('25. \uc8fc\uc694 \ub9c1\ud06c (plan.md 0.5.5)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id

  const seeded = be.listProjectLinks(pid).links
  check('the fixture seeded two links', seeded.length === 2, seeded.length)
  /*
   * `sort_order` cannot disagree with array position — the read derives it from the index,
   * which is the point of "배열 순서 = sort_order". So this asserts the *property*, and the
   * ordering itself is checked by id below, where a regression can actually show up. An
   * earlier version only checked this field and passed even when the stored order was
   * scrambled, because nothing reads the stored value.
   */
  check('sort_order is derived from array position', seeded.every((l, i) => l.sort_order === i + 1))
  const seededOrder = seeded.map((l) => l.id).join(',')
  check('and one of them is the edm cloud file the spec names', seeded.some((l) => l.url.includes('edm')))

  // Round trip: edit one, add one, drop one.
  const saved = be.saveProjectLinks(pid, [
    { id: seeded[1]!.id, description: '순서 바뀐 EDM', url: seeded[1]!.url },
    { id: null, description: '새 링크', url: 'https://new.example.com/a' },
  ]).links
  check('array order becomes sort_order', saved.map((l) => l.sort_order).join(',') === '1,2')
  check('reordering really reordered', saved[0]!.description === '순서 바뀐 EDM')
  check(
    '…by id, not merely by a renumbered field',
    saved[0]!.id === seeded[1]!.id && seededOrder !== saved.map((l) => l.id).join(','),
    [seededOrder, saved.map((l) => l.id).join(',')],
  )
  check('a new row got a real id', saved[1]!.id > 0 && saved[1]!.description === '새 링크')
  check('an id left out of the payload is deleted', saved.length === 2 && !saved.some((l) => l.id === seeded[0]!.id))
  check('the edit round-trips', be.listProjectLinks(pid).links[0]!.description === '순서 바뀐 EDM')

  // Validation — both rules, and nothing is written when either fails.
  const before = be.listProjectLinks(pid).links.map((l) => l.description).join('|')
  const blank = expectThrows(() =>
    be.saveProjectLinks(pid, [{ id: null, description: '   ', url: 'https://x.example.com' }]),
  )
  check('a blank description is a 422', blank?.status === 422, blank?.status)
  check('and it says which row', codeOf(blank) === 'LINK_DESCRIPTION_REQUIRED', codeOf(blank))

  for (const bad of ['ftp://x.example.com', 'example.com', 'javascript:alert(1)', '', '   ']) {
    const rejected = expectThrows(() =>
      be.saveProjectLinks(pid, [{ id: null, description: 'ok', url: bad }]),
    )
    check(`a non-http(s) url is refused: ${bad || '(empty)'}`, rejected?.status === 422, rejected?.status)
  }
  for (const good of ['http://a.example.com', 'https://a.example.com/x?y=1']) {
    const accepted = be.saveProjectLinks(pid, [{ id: null, description: 'ok', url: good }]).links
    check(`an http(s) url is accepted: ${good}`, accepted[0]!.url === good)
  }

  // The failed saves must not have written anything.
  be.saveProjectLinks(pid, [
    { id: null, description: '순서 바뀐 EDM', url: 'https://edm.example.com/folder/2026-ai-1' },
    { id: null, description: '새 링크', url: 'https://new.example.com/a' },
  ])
  check('setup: restored a two-row list', be.listProjectLinks(pid).links.length === 2)
  const mixed = expectThrows(() =>
    be.saveProjectLinks(pid, [
      { id: null, description: '괜찮은 행', url: 'https://ok.example.com' },
      { id: null, description: '나쁜 행', url: 'not-a-url' },
    ]),
  )
  check('a bad row anywhere refuses the WHOLE save', mixed?.status === 422)
  check(
    '...leaving the previous list untouched, not half-written',
    be.listProjectLinks(pid).links.map((l) => l.description).join('|') === '순서 바뀐 EDM|새 링크',
    be.listProjectLinks(pid).links.map((l) => l.description),
  )
  void before

  const foreign = expectThrows(() =>
    be.saveProjectLinks(pid, [{ id: 999999, description: 'x', url: 'https://x.example.com' }]),
  )
  check('an id from another project is a 422', foreign?.status === 422, foreign?.status)

  check('an empty payload clears the list', be.saveProjectLinks(pid, []).links.length === 0)
})

section('26. \ud504\ub85c\uc81d\ud2b8 \ubc84\uc804 \ubc88\ud638 (plan.md 0.6)')
guard(() => {
  const be = new MockBackend(1)
  const project = be.listProjects(1)[0]!
  const version = be.listVersions(be.listTemplates()[0]!.id).find((v) => v.status === 'PUBLISHED')!
  check('the project records which published version it came from', project.source_version_id === version.id)
  check('...and its NUMBER, for the header badge', project.source_version_number === version.version_number, project.source_version_number)
  check('the number is not the id', project.source_version_number !== project.source_version_id)
})

section('27. PPTX 내보내기 스텁 (plan.md 0.5.6)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id
  const blob = be.exportDashboardPptx(pid)
  check('it answers with a Blob, not a string or a path', blob instanceof Blob)
  check(
    'carrying the pptx MIME type the browser needs to name the download',
    blob.type === 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    blob.type,
  )
  const missing = expectThrows(() => be.exportDashboardPptx(999999))
  check('an unknown project is a 404, not an empty file', missing?.status === 404, missing?.status)
})

section('28. 상태 팔레트 (plan.md 0.5 표)')
guard(() => {
  // plan.md 0.5 의 표를 그대로 옮긴 것. 표가 정본이므로, 코드가 표에서 벗어나면 여기서 깨진다.
  const expected: Record<string, [string, string, string]> = {
    NOT_STARTED: ['#ffffff', '#94a3b8', '#334155'],
    IN_PROGRESS: ['#d1fae5', '#34d399', '#065f46'],
    DONE: ['#cbd5e1', '#94a3b8', '#1e293b'],
    HOLD: ['#fee2e2', '#fca5a5', '#991b1b'],
    NA: ['#334155', '#1e293b', '#cbd5e1'],
  }
  for (const [status, [bg, border, text]] of Object.entries(expected)) {
    const style = DASH_STATUS_STYLE[status as ItemStatus]
    check(`${status} matches the spec table`, style.bg === bg && style.border === border && style.text === text, style)
  }
  check(
    'no status carries an opacity wash any more',
    Object.values(DASH_STATUS_STYLE).every((s2) => !('opacity' in s2)),
  )

  /*
   * 대비 — NA 가 짙은 배경 + 밝은 글자로 바뀌었으므로, 배경 위 글자가 실제로 읽히는지는
   * 눈이 아니라 수치로 확인한다. WCAG AA 본문 기준 4.5:1.
   */
  const channel = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
  const luminance = (hex: string) => {
    const n = parseInt(hex.slice(1), 16)
    const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => channel(c / 255)) as [number, number, number]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const contrast = (a: string, b: string) => {
    const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p) as [number, number]
    return (x + 0.05) / (y + 0.05)
  }
  for (const [status, style] of Object.entries(DASH_STATUS_STYLE)) {
    const ratio = contrast(style.bg, style.text)
    check(`${status} text is readable on its own background (>= 4.5:1)`, ratio >= 4.5, ratio.toFixed(2))
  }
})

section('29. XLSX 내보내기 스텁 (plan.md 0.5.7)')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const draftId = be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id
  const pid = be.listProjects(1)[0]!.id

  const fromTemplate = be.exportBoardXlsx(be.versionScope(draftId))
  const fromProject = be.exportBoardXlsx(be.projectScope(pid))
  check('a template version exports', fromTemplate instanceof Blob)
  check('a project exports too — same operation, two scopes', fromProject instanceof Blob)
  check(
    'carrying the xlsx MIME type',
    fromTemplate.type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    fromTemplate.type,
  )

  const missing = expectThrows(() => be.exportBoardXlsx({ kind: 'project', projectId: 999999 }))
  check('an unknown project is a 404, not an empty file', missing?.status === 404, missing?.status)
  const badVersion = expectThrows(() =>
    be.exportBoardXlsx({ kind: 'template', templateId: t.id, versionId: 999999 }),
  )
  check('an unknown version likewise', badVersion?.status === 404, badVersion?.status)
})

section('30. Owner \uae30\uc900\uc815\ubcf4 — \uc140 \ud31d\uc5c5\uc774 \uae30\ub300\ub294 \uac83 (plan.md 0.5.9)')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const scope: MasterScope = { kind: 'template', templateId: t.id }

  const seeded = be.listOwners(scope)
  check('the scope has its seeded owners', seeded.length === 8, seeded.length)
  check('listed in sort_order', seeded.every((o, i) => o.sort_order === i + 1), seeded.map((o) => o.sort_order))

  // 추가 — 팝업의 '추가' 는 목록 끝에 붙인다.
  const added = be.upsertOwner(scope, { name: '신규 담당', sort_order: seeded.length + 1 })
  check('a new owner lands at the end', be.listOwners(scope).at(-1)!.id === added.id)
  check('…with the name it was given', added.name === '신규 담당')

  // 이름 변경.
  be.upsertOwner(scope, { name: '이름 바꿈' }, added.id)
  check('rename round-trips', be.listOwners(scope).find((o) => o.id === added.id)!.name === '이름 바꿈')

  /*
   * 순서 변경. 벌크 엔드포인트는 없고 `sort_order` 가 쓰기 가능한 필드다 — 팝업은 옮겨진
   * 행마다 PUT 을 한 번씩 보낸다. 여기서 확인할 것은 그 방식이 실제로 순서를 바꾸는가다.
   */
  const before = be.listOwners(scope).map((o) => o.id)
  const moved = [before.at(-1)!, ...before.slice(0, -1)]
  moved.forEach((id, i) => be.upsertOwner(scope, { sort_order: i + 1 }, id))
  check('writing sort_order reorders the list', be.listOwners(scope).map((o) => o.id).join(',') === moved.join(','))
  check('no owner was lost or duplicated', new Set(be.listOwners(scope).map((o) => o.id)).size === moved.length)

  // 삭제 — 미사용은 진짜 삭제, 사용 중은 비활성 (2.6).
  const unusedId = be.listOwners(scope).find((o) => o.name === '이름 바꿈')!.id
  const removed = be.deleteOwner(scope, unusedId)
  check('an unused owner is deleted outright', removed.deleted && removed.usage_count === 0)
  check('…and leaves the list', !be.listOwners(scope).some((o) => o.id === unusedId))

  const inUse = be.getVersion(be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id).items
    .flatMap((row) => row.owners)[0]!
  const kept = be.deleteOwner(scope, inUse.id)
  check('an owner in use is NOT deleted', kept.deleted === false && kept.deactivated === true)
  check('…and the response says how many rows use it', kept.usage_count > 0, kept.usage_count)
  check('…and it survives as an inactive row', be.listOwners(scope).some((o) => o.id === inUse.id && !o.is_active))

  // 프로젝트 스코프도 같은 규칙이고, 템플릿과 별개의 복사본이다 (0.1).
  const pid = be.listProjects(1)[0]!.id
  const projectScope: MasterScope = { kind: 'project', projectId: pid }
  const projectOwners = be.listOwners(projectScope)
  check('a project owns a separate copy of the owner list', projectOwners.length === 8)
  check(
    '…with different ids from the template',
    !projectOwners.some((o) => seeded.some((t2) => t2.id === o.id)),
  )
  be.upsertOwner(projectScope, { name: '프로젝트 전용' , sort_order: 9 })
  check('adding there does not touch the template', be.listOwners(scope).every((o) => o.name !== '프로젝트 전용'))
})

section('23c. 문서 표시 순서 — 사용 문서만 1..N (plan.md 0.5.10 정밀화)')
guard(() => {
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id
  const docs = be.listProjectDocuments(pid).documents

  check('setup: the fixture has one unused document', docs.filter((d) => !d.is_used).length === 1)
  check(
    'the response exposes only `no`, never the stored sort_order',
    docs.every((d) => !('sort_order' in d)),
    Object.keys(docs[0] ?? {}),
  )

  const rows = be.getProject(pid).items
  const linked = new Map<number, number | null>()
  for (const row of rows) for (const d of row.documents) linked.set(d.id, d.no)

  const usedIds = docs.filter((d) => d.is_used).map((d) => d.id)
  const unusedId = docs.find((d) => !d.is_used)!.id
  check('an unused document takes NO number on a row', linked.get(unusedId) === null || !linked.has(unusedId))
  check(
    'used documents are numbered 1..N in stored order, with no gap',
    usedIds.map((id) => linked.get(id)).filter((n) => n != null).join(',') === usedIds.map((_, i) => i + 1).join(','),
    usedIds.map((id) => linked.get(id)),
  )

  // 스위치를 끄면 뒤 번호가 당겨진다.
  const off = be.saveProjectDocuments(pid, {
    documents: docs.map((d, i) => ({ id: d.id, name: d.name, is_used: i === 0 ? false : d.is_used, link_url: d.link_url, doc_status: d.doc_status })),
    deleted_ids: [],
  })
  const afterRows = off.items ?? []
  const afterNos = new Map<number, number | null>()
  for (const row of afterRows) for (const d of row.documents) afterNos.set(d.id, d.no)
  check('turning one off drops its number', afterNos.get(docs[0]!.id) === null)
  check('and pulls the rest up', afterNos.get(docs[1]!.id) === 1, afterNos.get(docs[1]!.id))
  check(
    'the untouched documents keep their relative order',
    off.documents.map((d) => d.id).join(',') === docs.map((d) => d.id).join(','),
  )
  check('so turning it back on restores the original numbering', (() => {
    const back = be.saveProjectDocuments(pid, {
      documents: off.documents.map((d) => ({ id: d.id, name: d.name, is_used: d.id === docs[3]!.id ? false : true, link_url: d.link_url, doc_status: d.doc_status })),
      deleted_ids: [],
    })
    const nos = new Map<number, number | null>()
    for (const row of back.items ?? []) for (const d of row.documents) nos.set(d.id, d.no)
    return nos.get(docs[0]!.id) === 1 && nos.get(docs[1]!.id) === 2
  })())

  // 템플릿에는 사용 개념이 없으므로 두 값이 일치한다.
  const t = be.listTemplates()[0]!
  const tScope = be.versionScope(be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id)
  const tDocs = be.listDocuments(tScope).documents
  const tRow = be.project(tScope).find((r) => r.documents.length > 0)!
  check(
    'on a template every document is used, so every one is numbered',
    tRow.documents.every((d) => d.no != null) && tDocs.every((d, i) => d.no === i + 1),
  )
})

section('23d. 문서 응답 필드 계약 (plan.md 0.5.10 필드 확정)')
guard(() => {
  const be = new MockBackend(1)
  const t = be.listTemplates()[0]!
  const tScope = be.versionScope(be.listVersions(t.id).find((v) => v.status === 'DRAFT')!.id)
  const pid = be.listProjects(1)[0]!.id

  /*
   * 라이브에서만 깨졌던 자리다: 목이 저장 필드 `sort_order` 를 그대로 내보내는 바람에
   * `npm run check` 는 초록인데 서버 응답과 어긋났다. 목이 서버와 다른 규칙을 쓰면 검사는
   * 자기 자신하고만 일치한다 — 그 재발을 필드 단위로 못박는다.
   */
  const templateDocs = be.listDocuments(tScope).documents
  const templateKeys = Object.keys(templateDocs[0]!).sort().join(',')
  check('a template document is {id, is_active, name, no}', templateKeys === 'id,is_active,name,no', templateKeys)

  const projectDocs = be.listProjectDocuments(pid).documents
  const projectKeys = Object.keys(projectDocs[0]!).sort().join(',')
  check(
    'a project document adds doc_status, is_used, link_url',
    projectKeys === 'doc_status,id,is_used,link_url,name,no',
    projectKeys,
  )
  check('neither carries sort_order', ![...templateDocs, ...projectDocs].some((d) => 'sort_order' in d))

  // GET 이 계층에 따라 다른 형태를 준다는 것 자체가 계약이다.
  // scope 로 부른 GET 도 같은 형태여야 한다 — 팝업이 쓰는 경로가 그쪽이다.
  const viaScope = be.listDocuments(be.projectScope(pid)).documents
  check('the project GET really is the project shape', 'is_used' in viaScope[0]!)
  check('and the template GET is not', !('is_used' in templateDocs[0]!))

  // 쓰기 응답도 같은 형태여야 한다 — 팝업이 그 응답으로 목록을 다시 그린다.
  const applied = be.applyTemplateDocuments(tScope, {
    documents: templateDocs.map((d) => ({ id: d.id, name: d.name })),
    deleted_ids: [],
  })
  check('the apply answer uses the same fields', Object.keys(applied.documents[0]!).sort().join(',') === 'id,is_active,name,no')
  const saved = be.saveProjectDocuments(pid, {
    documents: projectDocs.map((d) => ({ id: d.id, name: d.name, is_used: d.is_used, link_url: d.link_url, doc_status: d.doc_status })),
    deleted_ids: [],
  })
  check('and so does the project save', Object.keys(saved.documents[0]!).sort().join(',') === 'doc_status,id,is_used,link_url,name,no')
})

section('23e. off 문서와 선택의 일관성 (plan.md 0.5.10 정밀화)')
guard(() => {
  /*
   * 사용자 재현 시나리오: 선택돼 있던 문서를 off 로 바꾸고 적용하면 선택이 살아남아, 그 문서를
   * 갖던 **모든 행**의 관련문서 셀에 잔재가 남았다. 정리 지점이 셋이라 셋 다 확인한다 —
   * 항목 payload(`no`), 저장 payload(`document_ids`), 그리고 표시.
   */
  const be = new MockBackend(1)
  const pid = be.listProjects(1)[0]!.id
  const docs = be.listProjectDocuments(pid).documents
  const target = docs.find((d) => d.is_used)!

  const usersBefore = be.getProject(pid).items.filter((r) => r.documents.some((d) => d.id === target.id))
  check('setup: several rows link the document', usersBefore.length > 1, usersBefore.length)
  check('setup: and it is numbered while used', usersBefore[0]!.documents.find((d) => d.id === target.id)!.no != null)

  const off = be.saveProjectDocuments(pid, {
    documents: docs.map((d) => ({
      id: d.id,
      name: d.name,
      is_used: d.id === target.id ? false : d.is_used,
      link_url: d.link_url,
      doc_status: d.doc_status,
    })),
    deleted_ids: [],
  })
  check('the document is now off', off.documents.find((d) => d.id === target.id)!.is_used === false)
  check('…and carries no display number', off.documents.find((d) => d.id === target.id)!.no === null)

  const rows = off.items ?? be.getProject(pid).items
  check(
    'EVERY row that linked it now reports it unnumbered — not just the edited one',
    rows
      .filter((r) => r.documents.some((d) => d.id === target.id))
      .every((r) => r.documents.find((d) => d.id === target.id)!.no === null),
  )

  /*
   * 저장 payload 정리. 스토어의 `toSavePayload` 와 같은 규칙(`no != null`)을 여기서 재현해,
   * 그 규칙이 실제로 링크를 떨어뜨리는지 본다.
   */
  const payload = rows.map((row) => ({
    id: row.id,
    phase_id: row.phase_id,
    milestone_id: row.milestone_id,
    title: row.title,
    deliverable: row.deliverable,
    dash_label: row.dash_label,
    gate_code: row.gate_code,
    document_ids: row.documents.filter((d) => d.no != null).map((d) => d.id),
    owner_ids: row.owners.map((o) => o.id),
    status: row.status,
    completion_date: row.completion_date,
  }))
  check('the save payload drops the off document', payload.every((r) => !r.document_ids.includes(target.id)))
  const saved = be.saveItems(be.projectScope(pid), payload)
  check('so after a save no row references it at all', saved.every((r) => !r.documents.some((d) => d.id === target.id)))
  check('and the other documents survived', saved.some((r) => r.documents.length > 0))

  // 다시 켜도 예전 선택이 되살아나지는 않는다 — 링크는 이미 저장에서 정리됐다.
  const backOn = be.saveProjectDocuments(pid, {
    documents: off.documents.map((d) => ({ id: d.id, name: d.name, is_used: true, link_url: d.link_url, doc_status: d.doc_status })),
    deleted_ids: [],
  })
  check('turning it back on gives it a number again', backOn.documents.find((d) => d.id === target.id)!.no != null)
  check(
    '…but does not resurrect the links a save had already cleared',
    (backOn.items ?? []).every((r) => !r.documents.some((d) => d.id === target.id)),
  )
})

console.log(`\n${passed} passed, ${failed} failed`)
report.push(`\n${passed} passed, ${failed} failed`)
writeFileSync(resolve(process.cwd(), 'verify-report.txt'), report.join('\n'), 'utf8')
if (failed > 0) process.exitCode = 1
