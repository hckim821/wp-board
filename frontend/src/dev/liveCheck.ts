/* eslint-disable no-console */
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHttpApiClient, describeApiError } from '../api/client'
import { resolveConfig } from '../runtime/config'
import type { BoardScope, WpItem } from '../api/types'

/**
 * Contract check against a **running** backend. DEV ONLY — `npm run check:live`.
 *
 * `verify.ts` and `domCheck.ts` run against the in-memory mock, which proves the frontend
 * is self-consistent but nothing about the real API. This drives the real
 * `createHttpApiClient` over HTTP so a field rename or a changed status code surfaces here
 * rather than in a browser.
 *
 * ## Isolation — read this before changing anything
 *
 * `iai-test` is the **delivered artifact**, not a scratch database: the seeded template is
 * the Excel-derived 35-row board the user inspects directly. An earlier version of this
 * script created Phases directly on it and left one behind, which pushed every real Phase
 * up one `seq_no` and made the seeded board fail its own publish validation.
 *
 * So: **the delivered template is read-only here.** Every write goes to a throwaway
 * template this script creates and tears down, plus a throwaway project taken from it. A
 * hard guard aborts the run if the scratch template comes back as the delivered one — it
 * never silently falls back to writing on the delivered board.
 *
 *   WP_API_BASE=http://localhost:8010 npm run check:live
 *
 * ## Why this exists, restated after §0
 *
 * The restructure gave the mock a second tier to imitate, and a stand-in that imitates
 * itself proves nothing. The first run of the project section below found two fields the
 * client had invented outright — `WpTemplate.published_version_id` and
 * `WpProject.template_name` — which the mock supplied happily, so every mock-backed
 * assertion was green while the real create dialog would have listed **zero** formats.
 * That is the class of defect this file is for; keep new server-facing surface covered
 * here, not only in `verify.ts`.
 */

const BASE = (process.env.WP_API_BASE ?? 'http://localhost:8010').replace(/\/+$/, '')
const MAKER_ID = Number(process.env.WP_MAKER_ID ?? 1)
/**
 * The delivered, Excel-seeded board. Never written to.
 *
 * Looked up by `code`, **not by id**. The id is an auto-increment value that changes
 * every time `db/migrate.py` re-seeds — this check used to hardcode `1` and broke with
 * `NOT_FOUND` the first time the board was rebuilt, even though the data was intact.
 */
const DELIVERED_TEMPLATE_CODE = 'DSEP-AI-BOARD'

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
    if (detail !== undefined) console.log(`        ${JSON.stringify(detail).slice(0, 500)}`)
  }
  report.push(`${condition ? 'PASS' : 'FAIL'}  ${name}`)
}

function section(title: string) {
  console.log(`\n${title}`)
  report.push(`\n## ${title}`)
}

/**
 * §0.2 rule: null rows are **transparent** — `P0 P0 [null] P0` is one contiguous block.
 * The first version of this helper let a null row reset `previous`, so the very state
 * 미배정으로 전환 legitimately produces (a gray row mid-block) read as a violation and
 * failed a passing server. Skip null rows entirely; track only the last *assigned* phase.
 */
const isContiguous = (items: WpItem[]) => {
  const seen = new Set<number>()
  let previous: number | null = null
  for (const row of items) {
    if (row.phase_id == null) continue
    if (row.phase_id === previous) continue
    if (seen.has(row.phase_id)) return false
    seen.add(row.phase_id)
    previous = row.phase_id
  }
  return true
}

/**
 * Raw status code for a path the typed client deliberately cannot express.
 *
 * Used to assert that a surface is **absent**. `WpApiClient` has no project-versions
 * method by construction, which is the design — but "we did not write the method" is a
 * fact about this repo, not about the server, so the absence is checked over the wire.
 */
async function statusOf(path: string): Promise<number> {
  const response = await fetch(`${BASE}/api/v1${path}`)
  return response.status
}

async function main() {
  const api = createHttpApiClient(resolveConfig({ apiBaseUrl: BASE }))
  console.log(`  target: ${BASE}  maker_id=${MAKER_ID}`)

  // ─────────────────────────────────────────── delivered board: READ ONLY

  section('1. Delivered template — read-only shape check')
  const deliveredTemplate = (await api.listTemplates()).find(
    (t) => t.code === DELIVERED_TEMPLATE_CODE,
  )
  if (!deliveredTemplate) {
    throw new Error(
      `code=${DELIVERED_TEMPLATE_CODE} 인 템플릿이 없다. db/migrate.py 로 시드했는지 확인할 것.`,
    )
  }
  const DELIVERED_ID = deliveredTemplate.id
  const deliveredVersionId = (await api.listVersions(DELIVERED_ID)).find(
    (v) => v.status === 'PUBLISHED',
  )!.id
  const deliveredScope: BoardScope = {
    kind: 'template',
    templateId: DELIVERED_ID,
    versionId: deliveredVersionId,
  }
  console.log(`  delivered template: ${DELIVERED_TEMPLATE_CODE} (id=${DELIVERED_ID})`)
  const delivered = await api.getVersion(deliveredVersionId)
  /** Snapshot so the end of the run can prove nothing touched it. */
  const deliveredFingerprint = delivered.items
    .map((r) => `${r.id}:${r.phase_id}:${r.milestone_id}:${r.title}`)
    .join('|')

  check('35 items in v1 PUBLISHED', delivered.items.length === 35, delivered.items.length)
  const first = delivered.items[0]!
  check('phase_display composed server-side', first.phase_display === 'Phase 0. Pre-Infrastructure Setup', first.phase_display)
  check('milestone_display carries the derived major number', first.milestone_display?.startsWith('0.1 ') === true, first.milestone_display)
  check('boundary flags present on the row', typeof first.can_create_phase === 'boolean' && typeof first.is_phase_block_start === 'boolean')
  check('documents are objects with id/no/name', typeof first.documents[0]?.no === 'number', first.documents)
  check('owners are objects with id/name', !!first.owners[0]?.name, first.owners)
  check('every field the grid binds is present', ['row_no', 'sort_order', 'title', 'deliverable', 'status', 'origin'].every((k) => k in first))

  const deliveredPhases = await api.listPhases(deliveredScope)
  check('4 phases, seq_no 0..3', deliveredPhases.length === 4 && deliveredPhases.every((p, i) => p.seq_no === i), deliveredPhases.map((p) => p.seq_no))
  check('13 milestones', (await api.listMilestones(deliveredScope)).length === 13)
  // 문서는 이제 스코프 소유다 (`plan.md` §0.5.10) — 전역 목록은 없어졌다.
  const deliveredDocs = (await api.listDocuments(deliveredScope)).documents
  check('5 documents on the delivered format', deliveredDocs.length === 5, deliveredDocs.length)
  check('numbered 1..N by the derived no', deliveredDocs.every((d, i) => d.no === i + 1))
  check(
    'the response carries `no` and NOT the stored sort_order (plan.md 0.5.10 field contract)',
    deliveredDocs.every((d) => 'no' in d && !('sort_order' in d)),
    Object.keys(deliveredDocs[0] ?? {}),
  )

  // ───────────────────────────────────────────── scratch WP: ALL WRITES

  section('2. Scratch template — isolation guard')
  const stamp = Date.now()
  const scratch = await api.createTemplate({
    code: `ZZ-CHECK-${stamp}`,
    name: `[자동검사] 삭제 대상 ${stamp}`,
    description: 'npm run check:live 가 만든 임시 템플릿. 검사 종료 시 정리된다.',
    phase_start_no: 0,
  })
  check('scratch template created', scratch.id > 0, scratch)
  if (scratch.id === DELIVERED_ID) {
    throw new Error('ABORT: scratch template resolved to the delivered one — refusing to write.')
  }
  check('scratch template is not the delivered board', scratch.id !== DELIVERED_ID)
  const scratchMaster = { kind: 'template' as const, templateId: scratch.id }

  const createdVersionIds: number[] = []
  const createdPhaseIds: number[] = []
  const createdMilestoneIds: number[] = []
  const createdOwnerIds: number[] = []
  /** Set as soon as the project exists, so teardown can deactivate it even on failure. */
  let createdProjectId: number | null = null

  try {
    section('3. Empty version — seeding the first row')
    const draft = await api.createDraft(scratch.id)
    createdVersionIds.push(draft.id)
    /** Row scope for the scratch template's current draft; reassigned as drafts change. */
    let scratchScope: BoardScope = { kind: 'template', templateId: scratch.id, versionId: draft.id }
    check('a template with no PUBLISHED version yields an empty v1 DRAFT', draft.version_number === 1)
    check('server marks DRAFT editable', draft.is_editable === true)
    check('it really is empty', (await api.getVersion(draft.id)).items.length === 0)

    // `insert-below` needs an anchor, so this endpoint is the only way in.
    const seeded = await api.appendRow(scratchScope)
    check('append creates the first row', seeded.items.length === 1, seeded.items.length)
    check('it is an unassigned (gray) row — plan.md 0.2', seeded.items[0]!.phase_id === null)
    check('marked ADDED', seeded.items[0]!.origin === 'ADDED')
    check(
      'and the server lets it start a phase — nothing below it to split',
      seeded.items[0]!.can_create_phase === true,
    )

    section('4. Master data on the scratch template')
    const owner = await api.createOwner(scratchMaster, { name: `검사 담당자 ${stamp}` })
    createdOwnerIds.push(owner.id)
    check('owner created', owner.id > 0 && owner.name.includes('검사 담당자'))
    check(
      'and the delivered template does not see it — master data is scope-local',
      !(await api.listOwners(deliveredScope)).some((o) => o.id === owner.id),
    )
    /*
     * 새 포맷은 문서 **0개**로 시작한다 (§0.5.10) — 전역 마스터가 없어졌으므로 상속받을 것이
     * 없다. 이전 판은 여기서 5개가 있다고 가정했고, 뒤(섹션 8)에서 `scratchDocs[0]` 을
     * 참조하다 undefined 로 죽었다.
     */
    const emptyDocs = (await api.listDocuments(scratchScope!)).documents
    check('a new format starts with zero documents', emptyDocs.length === 0, emptyDocs.length)

    // 그래서 여기서 만들어 준다 — 아래 절들이 쓸 문서다.
    const createdDocs = (
      await api.applyTemplateDocuments(scratchScope!, {
        documents: [{ id: null, name: '검사 문서 A' }, { id: null, name: '검사 문서 B' }],
        deleted_ids: [],
      })
    ).documents
    check('documents/apply creates them', createdDocs.length === 2, createdDocs.length)
    check('numbered 1..N', createdDocs.every((d, i) => d.no === i + 1), createdDocs.map((d) => d.no))
    const scratchDocs = createdDocs
    check(
      'documents belong to THIS format, not to a global table (plan.md 0.5.10)',
      scratchDocs.every((d) => !deliveredDocs.some((g) => g.id === d.id)),
      scratchDocs.map((d) => d.id),
    )

    // 이름·순서 변경과 삭제 캐스케이드.
    const docsReordered = (
      await api.applyTemplateDocuments(scratchScope!, {
        documents: [
          { id: scratchDocs[1]!.id, name: scratchDocs[1]!.name },
          { id: scratchDocs[0]!.id, name: '이름 바꾼 A' },
        ],
        deleted_ids: [],
      })
    ).documents
    check('reordering renumbers', docsReordered[0]!.id === scratchDocs[1]!.id && docsReordered[0]!.no === 1)
    check('and renaming lands', docsReordered[1]!.name === '이름 바꾼 A')

    // 집합 불일치는 422 — 빠뜨린 id 가 삭제로 읽히면 안 되기 때문이다 (§0.5.10).
    let setMismatch = 0
    try {
      await api.applyTemplateDocuments(scratchScope!, {
        documents: [{ id: docsReordered[0]!.id, name: docsReordered[0]!.name }],
        deleted_ids: [],
      })
    } catch (error) {
      setMismatch = (error as { response?: { status?: number } })?.response?.status ?? 0
    }
    check('an incomplete document list is a 422', setMismatch === 422, setMismatch)

    section('5. 새 Phase 생성 — atomic, anchor in the path')
    const anchor = seeded.items[0]!
    const withPhase = await api.createPhaseFromRow(scratchScope, anchor.id, { name: `검사 단계 ${stamp}` })
    const anchored = withPhase.items[0]!
    check('row moved into the new phase', anchored.phase_name === `검사 단계 ${stamp}`, anchored.phase_name)
    check('new phase has no milestone yet', anchored.milestone_id === null)
    const scratchPhases = await api.listPhases(scratchMaster)
    createdPhaseIds.push(...scratchPhases.map((p) => p.id))
    check('exactly one phase created', scratchPhases.length === 1, scratchPhases.length)

    const withMilestone = await api.createMilestoneFromRow(scratchScope, anchor.id, { name: `검사 마일스톤 ${stamp}` })
    createdMilestoneIds.push(...(await api.listMilestones(scratchMaster)).map((m) => m.id))
    check('milestone created and assigned', withMilestone.items[0]!.milestone_id != null)
    check('milestone_display derived from the phase number', withMilestone.items[0]!.milestone_display?.startsWith('0.1 ') === true, withMilestone.items[0]!.milestone_display)

    section('6. Row add, drag and membership')
    const grown = await api.insertBelow(scratchScope, anchor.id)
    check(
      'insert-below inherits NOTHING — it makes a gray row (plan.md 0.2)',
      grown.items[1]!.phase_id === null && grown.items[1]!.milestone_id === null,
      [grown.items[1]!.phase_id, grown.items[1]!.milestone_id],
    )
    check(
      'and a gray row below an assigned one does not break contiguity',
      isContiguous(grown.items),
    )
    check('renumbered 1..N', grown.items.every((r, i) => r.row_no === i + 1))

    /*
     * Position only, and position *is all that changes* — the two rows share one
     * Phase·Milestone block, which is the only reorder the grid will send (§2.2). The
     * membership assertion is keyed by item id rather than by slot: after the flip the
     * rows have swapped places, so comparing `items[i]` against its old self would pass
     * even if the server had rewritten both.
     */
    const movedId = grown.items[0]!.id
    const flipped = [grown.items[1]!.id, movedId]
    const membershipBefore = new Map(grown.items.map((r) => [r.id, `${r.phase_id}:${r.milestone_id}`]))
    const reordered = await api.reorder(scratchScope, flipped)
    check('reorder accepted (ids only)', reordered.items.length === 2)
    check('the rows really did swap', reordered.items.map((r) => r.id).join() === flipped.join(), reordered.items.map((r) => r.id))
    check(
      'every row kept its own phase/milestone — reorder does not re-derive membership',
      reordered.items.every((r) => membershipBefore.get(r.id) === `${r.phase_id}:${r.milestone_id}`),
      reordered.items.map((r) => `${r.id}:${r.phase_id}:${r.milestone_id}`),
    )
    check('board still contiguous', isContiguous(reordered.items))

    const second = await api.createPhaseFromRow(scratchScope, reordered.items[0]!.id, { name: `검사 단계2 ${stamp}` })
    createdPhaseIds.push(...(await api.listPhases(scratchMaster)).map((p) => p.id))
    check('a second phase splits off cleanly', new Set(second.items.map((r) => r.phase_id)).size === 2)

    const patched = await api.setMembership(scratchScope, second.items[0]!.id, {
      phase_id: second.items[1]!.phase_id,
      milestone_id: second.items[1]!.milestone_id,
    })
    check('PATCH membership merged the row back', new Set(patched.items.map((r) => r.phase_id)).size === 1)
    check('server kept the board contiguous', isContiguous(patched.items))

    section('7. Error envelope renders as text, not [object Object]')
    const readable = (m: string) => typeof m === 'string' && m.length > 0 && !m.includes('[object') && m !== 'undefined'
    let duplicate = ''
    try {
      await api.createPhaseFromRow(scratchScope, patched.items[0]!.id, { name: `검사 단계 ${stamp}` })
    } catch (error) {
      duplicate = describeApiError(error, 'FALLBACK')
    }
    check('duplicate phase name yields a readable message', readable(duplicate), duplicate)
    check('…and it is server text, not the fallback', duplicate !== 'FALLBACK', duplicate)

    let notFound = ''
    try {
      await api.getVersion(99999999)
    } catch (error) {
      notFound = describeApiError(error, 'FALLBACK')
    }
    check('404 yields a readable message', readable(notFound), notFound)

    section('8. 임시저장 and publish')
    // No `sort_order` — array position is authoritative.
    const savePayload = patched.items.map((row) => ({
      id: row.id,
      phase_id: row.phase_id,
      milestone_id: row.milestone_id,
      title: '검사 항목',
      deliverable: '검사 산출물',
      dash_label: '검사 라벨',
      gate_code: null,
      document_ids: [scratchDocs[0]!.id],
      owner_ids: [owner.id],
      status: row.status,
      completion_date: null,
    }))
    const saved = await api.saveVersionItems(draft.id, savePayload)
    check('PUT items answers with {version, items}', !!saved.version && Array.isArray(saved.items))
    check('the edit round-tripped', saved.items[0]!.title === '검사 항목')
    // `plan.md` §0.5-1 — a column the client invented would be dropped silently by a server
    // that has not added it yet, so it is asserted rather than assumed.
    check('dash_label round-tripped', saved.items[0]!.dash_label === '검사 라벨', saved.items[0]!.dash_label)
    check('documents survived (document_ids is the right field name)', saved.items[0]!.documents.length === 1, saved.items[0]!.documents)
    check('owners survived', saved.items[0]!.owners.length === 1, saved.items[0]!.owners)

    const publishOk = await api.publish(draft.id)
    check('a complete draft publishes', publishOk.valid === true, publishOk.errors.slice(0, 3))

    const draft2 = await api.createDraft(scratch.id)
    createdVersionIds.push(draft2.id)
    scratchScope = { kind: 'template', templateId: scratch.id, versionId: draft2.id }
    check('deep copy carried the rows', (await api.getVersion(draft2.id)).items.length === saved.items.length)

    const blanked = (await api.getVersion(draft2.id)).items.map((row) => ({
      id: row.id,
      phase_id: row.phase_id,
      milestone_id: row.milestone_id,
      title: '',
      deliverable: '',
      dash_label: null,
      gate_code: null,
      document_ids: [],
      owner_ids: [],
      status: row.status,
      completion_date: null,
    }))
    await api.saveVersionItems(draft2.id, blanked)
    const publishFail = await api.publish(draft2.id)
    check('publish rejected and unwrapped to valid:false (not a thrown 422)', publishFail.valid === false)
    check('errors carry item_id + field for cell highlighting', publishFail.errors.some((e) => e.item_id != null && !!e.field), publishFail.errors.slice(0, 3))
    const codes = new Set(publishFail.errors.map((e) => e.code))
    check('blank rows trip TITLE/DELIVERABLE/DOCUMENT/OWNER', ['TITLE_REQUIRED', 'DELIVERABLE_REQUIRED', 'DOCUMENT_REQUIRED', 'OWNER_REQUIRED'].some((c) => codes.has(c)), [...codes])
    // ───────────────────────────────────────── projects: the §0 lower tier

    section('10. Project creation — a real deep copy of a published template')
    /*
     * The end-user flow: 설비사가 발행된 포맷을 골라 프로젝트를 만든다. Everything below runs
     * against the **delivered** template's published version, because that is the one with
     * 35 rows and a full master-data set to copy — but it only ever *reads* it, and the
     * teardown proves so by fingerprint.
     */
    const createdDetail = await api.createProject({
      maker_id: MAKER_ID,
      name: `[자동검사] 프로젝트 ${stamp}`,
      template_id: DELIVERED_ID,
    })
    const project = createdDetail.project

    /*
     * 사용 스위치를 끄면 표시 번호가 사라지고 (§0.5.10 정밀화), 그 문서는 항목 payload 에서도
     * 번호 없이 나온다. 목에서만 맞고 서버에서 어긋나던 자리라 라이브에서도 확인한다.
     */
    section('6b. 문서 used-only 표시 번호')
    {
      const projectDocs = (await api.listProjectDocuments(project.id)).documents
      check('the project copied the format documents', projectDocs.length >= 2, projectDocs.length)
      check('all used, numbered 1..N', projectDocs.every((d, i) => d.no === i + 1), projectDocs.map((d) => d.no))

      const off = await api.saveProjectDocuments(project.id, {
        documents: projectDocs.map((d, i) => ({
          id: d.id,
          name: d.name,
          is_used: i !== 0,
          link_url: d.link_url,
          doc_status: d.doc_status,
        })),
        deleted_ids: [],
      })
      check('switching one off clears its number', off.documents[0]!.no === null, off.documents[0]!.no)
      check('and pulls the rest up', off.documents[1]!.no === 1, off.documents[1]!.no)
      const offId = off.documents[0]!.id
      const rowsAfter = off.items ?? (await api.getProject(project.id)).items
      check(
        'an item linking the off document shows it without a number',
        rowsAfter.every((r) => r.documents.every((d) => (d.id === offId ? d.no === null : d.no != null))),
      )
    }

    createdProjectId = project.id
    const projectScope: BoardScope = { kind: 'project', projectId: project.id }
    check('project created', project.id > 0, project)
    check(
      'POST /projects answers with the whole board, not just the project row',
      Array.isArray(createdDetail.items) && createdDetail.items.length === 35,
      createdDetail.items?.length,
    )
    check('it belongs to the requesting maker', String(project.maker_id) === String(MAKER_ID))
    check(
      'it records where the snapshot came from — source_template_id / source_version_id',
      project.source_template_id === DELIVERED_ID &&
        project.source_version_id === deliveredVersionId,
      [project.source_template_id, project.source_version_id],
    )
    check(
      'phase_start_no was snapshotted from the template',
      project.phase_start_no === deliveredTemplate.phase_start_no,
      [project.phase_start_no, deliveredTemplate.phase_start_no],
    )

    const projectDetail = await api.getProject(project.id)
    check('GET /projects/{id} answers with {project, items}', !!projectDetail.project && Array.isArray(projectDetail.items))
    check('all 35 rows were copied', projectDetail.items.length === 35, projectDetail.items.length)
    check(
      'rows are new records, not the template\'s',
      (() => {
        const templateRowIds = new Set(delivered.items.map((r) => r.id))
        return projectDetail.items.every((r) => !templateRowIds.has(r.id))
      })(),
    )
    check(
      'numbering came out identical to the source',
      projectDetail.items[0]!.phase_display === delivered.items[0]!.phase_display &&
        projectDetail.items[0]!.milestone_display === delivered.items[0]!.milestone_display,
      [projectDetail.items[0]!.phase_display, projectDetail.items[0]!.milestone_display],
    )
    check(
      'boundary flags are computed for project rows too',
      typeof projectDetail.items[0]!.can_create_phase === 'boolean',
    )

    section('10b. Master data was copied, not shared — the core §0 isolation')
    const projectPhases = await api.listPhases(projectScope)
    const projectMilestones = await api.listMilestones(projectScope)
    const projectOwners = await api.listOwners(projectScope)
    check('4 project-local phases, seq_no 0..3', projectPhases.length === 4 && projectPhases.every((p, i) => p.seq_no === i), projectPhases.map((p) => p.seq_no))
    check('13 project-local milestones', projectMilestones.length === 13, projectMilestones.length)
    check('8 project-local owners', projectOwners.length === 8, projectOwners.length)

    const deliveredMilestoneIds = new Set((await api.listMilestones(deliveredScope)).map((m) => m.id))
    const deliveredOwnerIds = new Set((await api.listOwners(deliveredScope)).map((o) => o.id))
    check(
      'phase ids differ from the template\'s — copies, not references',
      projectPhases.every((p) => !deliveredPhases.some((t) => t.id === p.id)),
      [deliveredPhases.map((p) => p.id), projectPhases.map((p) => p.id)],
    )
    check('milestone ids differ too', projectMilestones.every((m) => !deliveredMilestoneIds.has(m.id)))
    check('owner ids differ too', projectOwners.every((o) => !deliveredOwnerIds.has(o.id)))
    check(
      'and the copied rows point at the COPIES',
      (() => {
        const ids = new Set(projectPhases.map((p) => p.id))
        return projectDetail.items.every((r) => r.phase_id == null || ids.has(r.phase_id))
      })(),
    )
    check(
      'owner references were remapped as well',
      (() => {
        const ids = new Set(projectOwners.map((o) => o.id))
        return projectDetail.items.every((r) => r.owners.every((o) => ids.has(o.id)))
      })(),
    )
    /*
     * 문서도 복제된다 (`plan.md` §0.5.10). 이 단언은 한 번 **전제가 틀린 채로** 실패했다:
     * "프로젝트 행의 문서 id 가 포맷의 것과 겹치면 안 된다" 로 적혀 있었는데,
     * `wp_template_documents` 와 `wp_project_documents` 는 **별개 테이블·별개 id 시퀀스**라
     * 숫자가 겹치는 것 자체는 아무 의미가 없다 (실측: 프로젝트 사본 6..10 이 포맷의 8,9 와
     * 겹쳤을 뿐 링크는 전부 정상).
     *
     * 격리의 올바른 정의는 겹치지 않음이 아니라 **자기 네임스페이스 안에서 해석됨**이다.
     *
     * 목에서는 이 오류가 드러날 수 없었다 — 목은 문서를 스코프 키를 가진 한 테이블에 담아
     * id 가 전역 유일하므로 겹침이 아예 발생하지 않는다. 스탠드인이 서버의 *구조*까지
     * 흉내 내지는 않는다는 것을 기억할 것.
     */
    const projectDocs = (await api.listProjectDocuments(project.id)).documents
    const projectDocIds = new Set(projectDocs.map((d) => d.id))
    check(
      'every document link on a project row resolves inside that project’s own document list',
      projectDetail.items.every((r) => r.documents.every((d) => projectDocIds.has(d.id))),
      projectDetail.items.find((r) => r.documents.length > 0)?.documents,
    )

    // 비교 대상은 이 프로젝트의 **실제 원본**이다 — 프로젝트는 delivered 템플릿에서
    // 만들어졌으므로(§10 도입부), scratch 템플릿의 목록과 비교하면 항상 어긋난다.
    const formatDocs = (await api.listDocuments(deliveredScope)).documents
    check(
      'the copy is faithful — same document names as the source format',
      [...projectDocs.map((d) => d.name)].sort().join('|') ===
        [...formatDocs.map((d) => d.name)].sort().join('|'),
      [projectDocs.map((d) => d.name), formatDocs.map((d) => d.name)],
    )

    // 그리고 편집이 원본으로 전파되지 않는다 — 복제의 요점.
    const renamedDocs = (
      await api.saveProjectDocuments(project.id, {
        documents: projectDocs.map((d, i) => ({
          id: d.id,
          name: i === 0 ? '프로젝트에서만 바꾼 이름' : d.name,
          is_used: d.is_used,
          link_url: d.link_url,
          doc_status: d.doc_status,
        })),
        deleted_ids: [],
      })
    ).documents
    check('renaming a project document works', renamedDocs.some((d) => d.name === '프로젝트에서만 바꾼 이름'))
    check(
      '…and does NOT propagate to the format it was copied from',
      !(await api.listDocuments(scratchScope!)).documents.some(
        (d) => d.name === '프로젝트에서만 바꾼 이름',
      ),
    )

    section('10c. Edits round-trip on a project — no draft, no publish')
    const target = projectDetail.items[0]!
    const edited = await api.saveProjectItems(
      project.id,
      projectDetail.items.map((row) => ({
        id: row.id,
        phase_id: row.phase_id,
        milestone_id: row.milestone_id,
        title: row.title,
        deliverable: row.deliverable,
        dash_label: row.dash_label,
        gate_code: row.gate_code,
        document_ids: row.documents.map((d) => d.id),
        owner_ids: row.owners.map((o) => o.id),
        status: row.id === target.id ? 'DONE' : row.status,
        completion_date: row.id === target.id ? '2026-08-08' : row.completion_date,
      })),
    )
    check('PUT items answers with {project, items}', !!edited.project && Array.isArray(edited.items))
    const editedRow = edited.items.find((r) => r.id === target.id)!
    check('status changed in the response', editedRow.status === 'DONE', editedRow.status)
    check('완료일 changed too', String(editedRow.completion_date).startsWith('2026-08-08'), editedRow.completion_date)

    // Re-fetch rather than trust the write's own echo — that is the round trip.
    const refetched = await api.getProject(project.id)
    const persisted = refetched.items.find((r) => r.id === target.id)!
    check('and it survived a re-fetch', persisted.status === 'DONE', persisted.status)
    check('완료일 survived too', String(persisted.completion_date).startsWith('2026-08-08'), persisted.completion_date)
    check('nothing else moved', refetched.items.length === 35 && refetched.items[0]!.id === target.id)

    section('10d. Gray row + project-local create-phase (plan.md 0.2)')
    const grown2 = await api.appendRow(projectScope)
    const grayRow = grown2.items[grown2.items.length - 1]!
    check('append works on a project', grown2.items.length === 36, grown2.items.length)
    check('and it is a gray row', grayRow.phase_id === null && grayRow.milestone_id === null)
    check(
      'appended at the end it may start a phase — nothing below it to split',
      grayRow.can_create_phase === true,
    )

    const projectPhaseCountBefore = projectPhases.length
    const withLocalPhase = await api.createPhaseFromRow(projectScope, grayRow.id, {
      name: `프로젝트 전용 단계 ${stamp}`,
    })
    const localised = withLocalPhase.items.find((r) => r.id === grayRow.id)!
    check('the gray row joined a brand-new phase', localised.phase_name === `프로젝트 전용 단계 ${stamp}`, localised.phase_name)
    check('renumbered 1..N', withLocalPhase.items.every((r, i) => r.row_no === i + 1))
    check(
      'the project now has one more phase',
      (await api.listPhases(projectScope)).length === projectPhaseCountBefore + 1,
    )
    check(
      'the DELIVERED template gained none — project edits do not propagate up',
      (await api.listPhases(deliveredScope)).length === 4,
      (await api.listPhases(deliveredScope)).map((p) => p.name),
    )
    check(
      'a template phase id cannot be used on a project row — different scope',
      await api
        .setMembership(projectScope, refetched.items[0]!.id, {
          phase_id: deliveredPhases[0]!.id,
          milestone_id: null,
        })
        .then(() => false)
        .catch(() => true),
    )

    section('10d-2. 미배정으로 전환 — PATCH membership {null, null} (plan.md 0.3)')
    /*
     * The §0.3 reclassification path, against the real service. Two claims, and the second
     * is the one the whole design leans on: the server must **not** relocate a row whose
     * membership goes null. If it did, every 전환 would jump the row somewhere and the
     * "one mechanism for reclassification" story would be a lie in production while the
     * mock said otherwise.
     */
    const boardNow = (await api.getProject(project.id)).items
    const victimIndex = boardNow.findIndex((r, i) => i > 1 && r.milestone_id != null)
    const victim = boardNow[victimIndex]!
    check('fixture: a fully assigned row partway down the project board', victimIndex > 1)

    const unassigned = await api.setMembership(projectScope, victim.id, {
      phase_id: null,
      milestone_id: null,
    })
    const nowAt = unassigned.items.findIndex((r) => r.id === victim.id)
    const grayedRow = unassigned.items[nowAt]!
    check('the server accepts both-null membership', grayedRow.phase_id === null && grayedRow.milestone_id === null)
    check('and leaves the row exactly where it was', nowAt === victimIndex, { nowAt, victimIndex })
    check('the board is still contiguous — null is transparent server-side too', isContiguous(unassigned.items))
    check('row count unchanged', unassigned.items.length === boardNow.length)

    // …and reassigning lands it at the end of the chosen milestone's block, not the phase's.
    const reassignTarget = unassigned.items.find(
      (r) => r.milestone_id != null && r.milestone_id !== victim.milestone_id,
    )!
    const reassigned = await api.setMembership(projectScope, victim.id, {
      phase_id: reassignTarget.phase_id,
      milestone_id: reassignTarget.milestone_id,
    })
    const landedAt = reassigned.items.findIndex((r) => r.id === victim.id)
    const lastOfBlock = reassigned.items.reduce(
      (last, row, i) => (row.milestone_id === reassignTarget.milestone_id ? i : last),
      -1,
    )
    check(
      'reassigning after 전환 lands at the END of that milestone block',
      landedAt === lastOfBlock && landedAt >= 0,
      { landedAt, lastOfBlock },
    )
    check('still contiguous', isContiguous(reassigned.items))

    section('10e. The project tier has no version surface at all')
    /*
     * Asserted over the wire, not by "the client has no method for it". The claim is about
     * the server: a project is not a thing that can be drafted, validated or published, and
     * these are the paths a host would reach for if it assumed otherwise.
     */
    check('GET /projects/{id}/versions is 404', (await statusOf(`/projects/${project.id}/versions`)) === 404)
    check('POST-shaped publish path is not there either', (await statusOf(`/projects/${project.id}/publish`)) === 404)
    check('nor validate', (await statusOf(`/projects/${project.id}/validate`)) === 404)
    check(
      'CONTROL — the same shape does exist for a template version',
      (await statusOf(`/templates/${DELIVERED_ID}/versions`)) === 200,
    )

  } finally {
    section('11. Teardown — the scratch template and project go away')
    for (const versionId of [...createdVersionIds].reverse()) {
      await api.discardDraft(versionId).catch(() => undefined)
    }
    for (const id of new Set(createdMilestoneIds)) {
      await api.deleteMilestone(scratchMaster, id).catch(() => undefined)
    }
    for (const id of new Set(createdPhaseIds)) {
      await api.deletePhase(scratchMaster, id).catch(() => undefined)
    }
    for (const id of new Set(createdOwnerIds)) {
      await api.deleteOwner(scratchMaster, id).catch(() => undefined)
    }
    /*
     * Swept by name, not only by the id captured above.
     *
     * The first run of this section captured `createdProjectId` off a response shape the
     * client had wrong, so it stayed null and the teardown skipped a project that was very
     * much created — it sat in the maker's real project list until it was removed by hand.
     * The stamp is unique to this run, so this cleans up after *this* run whatever the
     * response looked like, and never touches a concurrent one.
     */
    const strays = await api
      .listProjects(MAKER_ID)
      .then((list) => list.filter((row) => row.name.includes(String(stamp))))
      .catch(() => [])
    for (const stray of strays) {
      createdProjectId = createdProjectId ?? stray.id
      await api.deleteProject(stray.id).catch(() => undefined)
    }
    if (createdProjectId != null) {
      await api.deleteProject(createdProjectId).catch(() => undefined)
    }
    await api.updateTemplate(scratch.id, { is_active: false }).catch(() => undefined)

    // The whole point of the exercise: prove the delivered board is byte-identical.
    const after = await api.getVersion(deliveredVersionId)
    check(
      'the delivered template is untouched — every row identical to the start of the run',
      after.items.map((r) => `${r.id}:${r.phase_id}:${r.milestone_id}:${r.title}`).join('|') ===
        deliveredFingerprint,
    )
    const phasesAfter = await api.listPhases(deliveredScope)
    check(
      'it still has exactly 4 phases with seq_no 0..3',
      phasesAfter.length === 4 && phasesAfter.every((p, i) => p.seq_no === i),
      phasesAfter.map((p) => `${p.seq_no}:${p.name}`),
    )
    /*
     * The §0 invariant, checked last and against the same fingerprint the template section
     * uses: a project was created from this template, edited, given its own phase — and
     * none of it came back up. If deep copy were secretly sharing rows or master data, the
     * fingerprint above and the phase count here are where it would show.
     */
    check(
      'the delivered template survived a project being built on top of it',
      (await api.listMilestones(deliveredScope)).length === 13 &&
        (await api.listOwners(deliveredScope)).length === 8,
    )
    if (createdProjectId != null) {
      check(
        'the scratch project is deactivated and out of the maker\'s list',
        !(await api.listProjects(MAKER_ID)).some((p) => p.id === createdProjectId),
      )
    }

    console.log(
      `\n  NOTE: scratch template #${scratch.id} (${scratch.code})` +
        (createdProjectId != null ? ` and project #${createdProjectId}` : '') +
        ' are deactivated\n        but still present — there is no hard delete. Remove them in SQL if they accumulate.',
    )
    report.push(
      `\nNOTE: scratch template #${scratch.id} (${scratch.code})` +
        (createdProjectId != null ? `, project #${createdProjectId}` : '') +
        ' deactivated, not deleted.',
    )
  }

  console.log(`\n${passed} passed, ${failed} failed`)
  report.push(`\n${passed} passed, ${failed} failed`)
  writeFileSync(resolve(process.cwd(), 'live-check-report.txt'), report.join('\n'), 'utf8')
  if (failed > 0) process.exitCode = 1
}

main().catch((error) => {
  console.error('LIVE CHECK ABORTED:', error?.response?.status ?? '', error?.message)
  if (error?.response?.data) console.error(JSON.stringify(error.response.data).slice(0, 800))
  process.exitCode = 1
})
