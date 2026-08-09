/* eslint-disable no-console */
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { JSDOM } from 'jsdom'

/**
 * Headless DOM check of the exposed component. DEV ONLY — `npm run check:dom`.
 *
 * `verify.ts` proves the *rules*; this proves they are actually wired to the screen:
 * both exposed modules mount, the Community-only phase banding renders, the boundary
 * editor opens with the right affordances, gray rows look and behave like gray rows, a
 * drag lands through the store, publish errors decorate the right cells, the project
 * workspace really has no version machinery, and mount → unmount → remount leaves nothing
 * behind.
 *
 * Run through vite's SSR build so `.vue` SFCs are compiled, but executed against jsdom so
 * ag-grid really renders.
 */

const dom = new JSDOM('<!doctype html><html><body><div id="app"></div></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
})

const g = globalThis as unknown as Record<string, unknown>
g.window = dom.window
g.document = dom.window.document
// Node 24 defines `navigator` as a getter-only global, so it has to be redefined.
Object.defineProperty(globalThis, 'navigator', {
  value: dom.window.navigator,
  configurable: true,
  writable: true,
})
// Vue, antd and ag-grid all reach for browser constructors during mount; copy across
// everything jsdom offers that Node does not already define.
for (const key of Object.getOwnPropertyNames(dom.window)) {
  if (key in g) continue
  try {
    g[key] = (dom.window as unknown as Record<string, unknown>)[key]
  } catch {
    /* jsdom exposes a few accessor-only globals; skipping them is fine. */
  }
}
g.getComputedStyle = dom.window.getComputedStyle.bind(dom.window)
g.requestAnimationFrame = (cb: FrameRequestCallback) => dom.window.setTimeout(() => cb(0), 0)
g.cancelAnimationFrame = (id: number) => dom.window.clearTimeout(id)
// jsdom ships neither of these and ag-grid/antd both expect them.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
g.ResizeObserver = ResizeObserverStub
dom.window.ResizeObserver = ResizeObserverStub as never
dom.window.matchMedia = ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})) as never

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
    if (detail !== undefined) console.log(`        ${String(detail).slice(0, 400)}`)
  }
  report.push(`${condition ? 'PASS' : 'FAIL'}  ${name}${condition ? '' : ` :: ${String(detail).slice(0, 400)}`}`)
}

function section(title: string) {
  console.log(`\n${title}`)
  report.push(`\n## ${title}`)
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function main() {
  // Imported late so the jsdom globals above are already in place.
  const { mount } = await import('@vue/test-utils')
  const { default: MasterAdmin } = await import('../remote/MasterAdminRemote.vue')
  const { default: ProjectWorkspace } = await import('../remote/ProjectWorkspaceRemote.vue')
  const { default: ProjectsOverview } = await import('../remote/ProjectsOverviewRemote.vue')
  const { default: MakerSettings } = await import('../remote/MakerSettingsRemote.vue')
  const { createMockApiClient } = await import('../mock/client')
  const { nextTick } = await import('vue')

  const client = createMockApiClient({ makerId: 7, latencyMs: 0 })
  const host = dom.window.document.getElementById('app')!

  /*
   * The primary mount is **MasterAdmin** — the 기준 데이터 editor. It is the tier that has
   * versions and publishing, so the sections below can exercise the whole state machine;
   * the project tier gets its own section (I) that asserts precisely what it does *not*
   * have.
   */
  const wrapper = mount(MasterAdmin, {
    attachTo: host,
    props: { dataSource: client, warnOnUnload: false, height: '800px' },
  })

  // Let the store's init() chain and ag-grid's first paint settle.
  for (let i = 0; i < 40; i++) {
    await nextTick()
    await sleep(10)
  }

  const root = wrapper.element as HTMLElement
  const text = () => root.textContent ?? ''
  const rows = () => root.querySelectorAll('.ag-center-cols-container .ag-row')
  const buttonLabels = (el: HTMLElement) =>
    [...el.querySelectorAll('button')].map((b) => (b.textContent ?? '').trim())

  const { OWNER_KINDS, DASH_STATUS_ORDER } = await import('../theme/dashboard')
  const OWNER_KIND_COUNT = OWNER_KINDS.length
  const STATUS_COUNT = DASH_STATUS_ORDER.length

  /**
   * The seed project id of a mock client.
   *
   * `ProjectWorkspace` requires `projectId` as of `plan.md` §0.6-4 — there is no project list
   * inside the module any more, so every mount has to say which project it means.
   */
  const seedProjectId = (
    c: { backend: { listProjects(id: number): { id: number }[] } },
    makerId = 7,
  ) => c.backend.listProjects(makerId)[0]!.id

  /** Labels of the antd tab bar — the project nav of `plan.md` §0.5-2b. */
  const tabLabels = (el: HTMLElement) =>
    [...el.querySelectorAll('.ant-tabs-tab')].map((t) => (t.textContent ?? '').trim())

  /*
   * preflight 가 꺼져 있으므로 `wp-border` 계열(두께만)은 `border-style: solid` 를 얻지 못하고
   * **아무것도 그리지 않는다** (`styles/tailwind.css` 주석). 2026-08-08 진행전 대시보드 셀이
   * 투명했던 것이 정확히 이것이었고, 그때 색만 확인하던 단언은 통과했다 — `borderColor` 는
   * style 이 `none` 이어도 그대로 읽히기 때문이다.
   *
   * 그래서 색이 아니라 **클래스 짝**을 감사한다. 화면이 살아 있는 동안 호출해야 하므로
   * 헬퍼로 두고 각 섹션에서 부른다.
   */
  const BORDER_WIDTH_ONLY = new Set([
    'wp-border', 'wp-border-0', 'wp-border-2', 'wp-border-4', 'wp-border-8',
    'wp-border-t', 'wp-border-b', 'wp-border-l', 'wp-border-r',
    'wp-border-x', 'wp-border-y',
  ])
  const BORDER_STYLE = new Set([
    'wp-border-solid', 'wp-border-dashed', 'wp-border-dotted',
    'wp-border-double', 'wp-border-hidden', 'wp-border-none',
  ])

  const borderOffenders = (scope: HTMLElement | Document) =>
    ([...scope.querySelectorAll('*')] as HTMLElement[])
      .filter((el) => {
        const classes = [...el.classList]
        return classes.some((c) => BORDER_WIDTH_ONLY.has(c)) && !classes.some((c) => BORDER_STYLE.has(c))
      })
      .map((el) => `${el.tagName.toLowerCase()}.${[...el.classList].filter((c) => c.startsWith('wp-border')).join('.')}`)

  const auditBorders = (scope: HTMLElement, label: string) => {
    const offenders = borderOffenders(scope)
    check(
      `${label}: every wp-border width utility is paired with an explicit style`,
      offenders.length === 0,
      [...new Set(offenders)].slice(0, 8),
    )
  }

  /** Clicks a tab by its label and lets the swap settle. */
  const clickTab = async (el: HTMLElement, label: string) => {
    const tab = [...el.querySelectorAll('.ant-tabs-tab')].find(
      (t) => (t.textContent ?? '').trim() === label,
    )
    ;(tab?.querySelector('.ant-tabs-tab-btn') as HTMLElement | undefined)?.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
  }

  /**
   * ag-grid virtualises rows and jsdom reports a zero-height viewport, so only a slice of
   * the 35 rows is ever in the DOM. The toolbar's 전체 counter reflects the full row set,
   * which is what these assertions actually care about.
   */
  const totalRows = (el: HTMLElement = root) =>
    Number(/전체\s*(\d+)/.exec(el.textContent ?? '')?.[1] ?? -1)
  /** The toolbar's 미배정 counter — the gray rows of `plan.md` §0.2, visible to the user. */
  const grayRows = (el: HTMLElement = root) =>
    Number(/미배정\s*(\d+)/.exec(el.textContent ?? '')?.[1] ?? 0)

  section('A. MasterAdmin mounts into the template tier')
  check('root carries the wp-root style anchor', root.classList.contains('wp-root'))
  check('ag-grid mounted', !!root.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
  check('some rows painted (ag-grid virtualises the rest)', rows().length > 0, rows().length)
  check('35 rows loaded', totalRows() === 35, totalRows())
  check('it announces itself as the central 기준 데이터 screen', text().includes('기준 데이터'))
  check('no maker is shown, because a template has none', !/설비사\s*#/.test(text()))
  check('opened on the DRAFT version', text().includes('작성중'))
  check('progress summary replaces the spreadsheet header row', text().includes('전체'))

  section('B. Phase banding — the Community stand-in for Row Grouping')
  {
    const first = rows()[0] as HTMLElement
    const fifth = rows()[4] as HTMLElement
    const phaseCell = first.querySelector('[col-id="phase_id"]')
    check(
      'block first row shows the composed label',
      /Phase 0\./.test(phaseCell?.textContent ?? ''),
      phaseCell?.textContent,
    )
    check(
      'continuation row suppresses the label',
      (rows()[1]?.querySelector('[col-id="phase_id"]')?.textContent ?? '').includes('〃'),
    )
    check(
      'rows are tinted per phase',
      first.style.backgroundColor !== '' &&
        first.style.backgroundColor !== fifth.style.backgroundColor,
      [first.style.backgroundColor, fifth.style.backgroundColor],
    )
    check(
      'milestone display uses the derived major number',
      /0\.1\s/.test(first.querySelector('[col-id="milestone_id"]')?.textContent ?? ''),
    )
    check(
      'multi-value columns render as chips',
      (first.querySelector('[col-id="owners"]')?.textContent ?? '').includes('DSEP 인프라 담당자'),
    )
    check('no ag-grid Enterprise watermark / licence error', !text().includes('License Key'))
  }

  section('C. Membership cells are locked on assigned rows (plan.md 0.3)')
  {
    /*
     * Every row of the seeded board is fully assigned, so on the template tier this is the
     * lock in its normal state: clicking a Phase or Milestone cell must open **no editor**
     * at all, and offer 미배정으로 전환 instead. The gray-row side of the matrix is asserted
     * by mounting the editor directly further down, and the whole 전환 → 재배정 round trip
     * runs on the project tier in D2.
     */
    const clickCell = async (rowIndex: number, colId: string) => {
      const cell = rows()[rowIndex]!.querySelector(`[col-id="${colId}"]`) as HTMLElement
      cell.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
      for (let i = 0; i < 10; i++) {
        await nextTick()
        await sleep(5)
      }
    }
    const dismissModal = async () => {
      const cancel = [...root.querySelectorAll('button')].find(
        (b) => (b.textContent ?? '').trim() === '취소',
      ) as HTMLButtonElement | undefined
      cancel?.click()
      for (let i = 0; i < 25; i++) {
        await nextTick()
        await sleep(10)
      }
      // antd keeps the closed dialog mounted through its leave transition, which jsdom
      // never fires; left in place a second confirm collides with it on the same key.
      root.querySelectorAll('.ant-modal-root').forEach((el) => el.remove())
    }

    check(
      'fixture: row 1 is fully assigned',
      !!rows()[0]!.querySelector('[col-id="phase_id"]') &&
        !(rows()[0] as HTMLElement).classList.contains('wp-row-unassigned'),
    )

    await clickCell(0, 'phase_id')
    check('an assigned row\'s Phase cell opens NO editor', !root.querySelector('.ag-popup-editor'))
    // §0.4 replaced the single 전환 confirm with a three-way choice. Asserted as the two
    // *actions*, not as prose: the whole point of the change is that 수정 exists alongside
    // 재배치, and a dialog offering only one of them would still contain the sentence.
    check(
      'it offers the [수정] / [재배치] / [취소] choice instead',
      ['수정', '재배치', '취소'].every((label) =>
        [...root.querySelectorAll('button')].some((b) => (b.textContent ?? '').trim() === label),
      ),
      buttonLabels(root),
    )
    await dismissModal()
    check('cancelling leaves the board alone', grayRows() === 0, grayRows())

    // The Milestone half of the lock, and the whole 전환 → 재배정 round trip, are asserted
    // on the project tier in D2 — one confirm per mounted board, because antd keeps a
    // cancelled dialog mounted through a leave transition that jsdom never fires.
    check(
      'the locked cells carry the affordance class',
      (rows()[0]!.querySelector('[col-id="phase_id"]')?.className ?? '').includes(
        'wp-cell-locked',
      ),
      rows()[0]!.querySelector('[col-id="phase_id"]')?.className,
    )

    // jsdom cannot position ag-grid popups, so stopEditing never sees an editor that did
    // open and it would otherwise linger and pollute later DOM queries.
    root.querySelectorAll('.ag-popup-editor').forEach((el) => el.remove())

    // ...but ag-grid's popup service needs real layout to position itself, which jsdom
    // cannot provide, so the boundary UX itself is asserted by mounting the editor
    // directly with each kind of row.
    const { default: PhaseCellEditor } = await import('../components/grid/PhaseCellEditor.vue')
    const { App: AntApp } = await import('ant-design-vue')
    const { BOARD_CONTEXT } = await import('../runtime/context')
    const { createMasterStore } = await import('../stores/master')
    const { createBoardStore } = await import('../stores/board')
    const { defineComponent, h, provide, ref } = await import('vue')

    const editorClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const editorMaster = createMasterStore(editorClient)
    const editorReadOnly = ref(false)
    const editorBoard = createBoardStore(editorClient, editorMaster, {
      tier: 'template',
      makerId: () => 7,
      forceReadOnly: () => editorReadOnly.value,
    })
    await editorBoard.init()
    for (let i = 0; i < 10; i++) {
      await nextTick()
      await sleep(5)
    }
    /** Everything the editor asks the shell to open (`plan.md` §0.4). */
    const opened: { kind: string; phaseId?: number | null; anchorItemId?: number | null }[] = []
    const context = {
      api: editorClient,
      board: editorBoard,
      master: editorMaster,
      notify: { info() {}, success() {}, warn() {}, error() {} },
      structure: { open: (request: unknown) => opened.push(request as { kind: string }) },
      // `as never` 캐스팅이 타입 검사를 가리므로, 빠뜨리면 런타임에서만 터진다 (§0.5.9).
      ownerPicker: { open() {} },
      makerId: 7,
      makerName: null,
      navigate: null,
      popupContainer: () => dom.window.document.body,
    }

    const mountEditorWith = (ctx: unknown, item: unknown) =>
      mount(
        defineComponent({
          setup() {
            provide(BOARD_CONTEXT, ctx as never)
            const params = { data: item, value: '', api: { stopEditing() {} } }
            return () => h(AntApp, null, { default: () => h(PhaseCellEditor, { params } as never) })
          },
        }),
        { attachTo: dom.window.document.body },
      )
    const mountEditor = (item: unknown) => mountEditorWith(context, item)
    const createButton = (el: Element) =>
      [...el.querySelectorAll('button')].find((b) =>
        (b.textContent ?? '').includes('새 Phase 생성'),
      ) as HTMLButtonElement | undefined

    /*
     * Every row this editor can now open on is a gray one (§0.3), so the fixtures below are
     * gray rows in different positions rather than the old edge/middle assigned pair.
     */
    await editorBoard.appendRow()
    for (let i = 0; i < 12; i++) {
      await nextTick()
      await sleep(5)
    }
    const trailingGray = editorBoard.items.value[editorBoard.items.value.length - 1]!
    check('fixture: a gray row at the end of the board', trailingGray.phase_id === null)

    const edge = mountEditor(trailingGray)
    await nextTick()
    check('all four phases offered', edge.element.querySelectorAll('button').length >= 5)
    check('a gray row at the end: 새 Phase 생성 is enabled', createButton(edge.element)?.disabled === false)
    opened.length = 0
    createButton(edge.element)!.click()
    await nextTick()
    check(
      '§0.4 — it opens the 관리 팝업 with this row as the anchor, rather than creating anything',
      opened.length === 1 &&
        opened[0]!.kind === 'phase' &&
        opened[0]!.anchorItemId === trailingGray.id,
      opened,
    )
    check(
      'it is labelled 미배정 행 — there is no middle-row case left',
      (edge.element.textContent ?? '').includes('미배정 행') &&
        !(edge.element.textContent ?? '').includes('블록 중간 행'),
    )
    check(
      'the trailing gray row is offered only 위와 같게 — nothing follows it',
      (edge.element.textContent ?? '').includes('위와 같게') &&
        !(edge.element.textContent ?? '').includes('아래와 같게'),
    )
    edge.unmount()

    // ── §0.2.3: a gray row parked at a seam gets the two one-click shortcuts. ──
    const seamClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const seamMaster = createMasterStore(seamClient)
    const seamBoard = createBoardStore(seamClient, seamMaster, {
      tier: 'template',
      makerId: () => 7,
    })
    await seamBoard.init()
    for (let i = 0; i < 10; i++) {
      await nextTick()
      await sleep(5)
    }
    const settle = async () => {
      for (let i = 0; i < 12; i++) {
        await nextTick()
        await sleep(5)
      }
    }
    /** Moves `id` to `index`, through the store, the way a drag does. */
    const moveTo = async (id: number, index: number) => {
      const rest = seamBoard.items.value.filter((r) => r.id !== id).map((r) => r.id)
      await seamBoard.applyReorder([...rest.slice(0, index), id, ...rest.slice(index)])
      await settle()
    }

    await seamBoard.appendRow()
    await settle()
    const grayId = seamBoard.items.value[seamBoard.items.value.length - 1]!.id
    await moveTo(grayId, 4)

    const seamRow = seamBoard.items.value[4]!
    check(
      'fixture: a gray row sits between Phase 0 and Phase 1',
      seamRow.id === grayId &&
        seamRow.phase_id === null &&
        seamBoard.items.value[3]!.phase_no === 0 &&
        seamBoard.items.value[5]!.phase_no === 1,
      [seamRow.phase_id, seamBoard.items.value[3]!.phase_no, seamBoard.items.value[5]!.phase_no],
    )

    const seamContext = { ...context, board: seamBoard, master: seamMaster, api: seamClient }
    const seamEditor = mountEditorWith(seamContext, seamRow)
    await nextTick()
    const seamText = seamEditor.element.textContent ?? ''
    check('the gray row is labelled 미배정 행, not 블록 중간 행', seamText.includes('미배정 행'))
    check('…and the 인접 Phase section appears', seamText.includes('인접 Phase'))
    check(
      'with both one-click shortcuts',
      seamText.includes('위와 같게') && seamText.includes('아래와 같게'),
    )
    check(
      'naming the two different neighbouring phases',
      seamText.includes('Phase 0.') && seamText.includes('Phase 1.'),
    )
    check('새 Phase 생성 is enabled at a seam', createButton(seamEditor.element)?.disabled === false)
    seamEditor.unmount()

    /*
     * The same row parked *inside* a block. Until §0.4 this was the case that disabled
     * creation, because a `create-phase` there would have split the surrounding block in
     * two. The popup states the new phase's position itself, so there is nothing left to
     * split blindly and the precondition is retired — the server still computes
     * `can_create_phase`, and this editor no longer reads it.
     *
     * The fixture is kept precisely because it is the one that used to be refused: if the
     * gating ever comes back, this is where it shows up.
     */
    await moveTo(grayId, 2)
    const parked = seamBoard.items.value[2]!
    check(
      'fixture: the same gray row is now mid-block, where the server says can_create_phase=false',
      parked.id === grayId && parked.can_create_phase === false,
      parked.can_create_phase,
    )
    const parkedEditor = mountEditorWith(seamContext, parked)
    await nextTick()
    check(
      '새 Phase 생성 stays enabled mid-block now — the popup decides the position (§0.4)',
      createButton(parkedEditor.element)?.disabled === false,
    )
    check(
      'the shortcut collapses to one — both neighbours are the same Phase 0',
      (parkedEditor.element.textContent ?? '').includes('위와 같게') &&
        !(parkedEditor.element.textContent ?? '').includes('아래와 같게'),
    )
    parkedEditor.unmount()

    // Optimistic repaints no longer matter to this button either: it opens a screen rather
    // than issuing a mutation, so a stale flag has nothing to be stale about.
    editorBoard.flagsStale.value = true
    const stale = mountEditor(trailingGray)
    await nextTick()
    check(
      '…and stale server flags no longer suppress it',
      createButton(stale.element)?.disabled === false,
    )
    stale.unmount()
    editorBoard.flagsStale.value = false

    // NEGATIVE CONTROL — the one thing that must still withhold it is the host's permission
    // gate. Without this, "enabled" above could pass for a button that is simply never
    // disabled by anything at all.
    editorReadOnly.value = true
    await nextTick()
    const locked = mountEditor(trailingGray)
    await nextTick()
    check(
      'NEGATIVE CONTROL — a read-only board still withholds it',
      createButton(locked.element)?.disabled === true,
      createButton(locked.element)?.disabled,
    )
    locked.unmount()
    editorReadOnly.value = false
    await nextTick()
  }

  section('D. Row add makes a gray row, through the server (plan.md 0.2)')
  {
    const before = totalRows()
    check('no unassigned rows to start with', grayRows() === 0, grayRows())
    const addButton = [...root.querySelectorAll('button')].find((b) =>
      (b.textContent ?? '').includes('행 추가'),
    ) as HTMLButtonElement
    addButton.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('toolbar 행 추가 appended a row', totalRows() === before + 1, totalRows())
    check('and the toolbar reports it as unassigned', grayRows() === 1, grayRows())
    const numbers = [...rows()].map((r) =>
      Number((r.querySelector('[col-id="no"]')?.textContent ?? '').trim()),
    )
    check(
      'painted row numbers are consecutive after the server renumber',
      numbers.every((n, i) => i === 0 || n === numbers[i - 1]! + 1),
      numbers,
    )
  }

  section('D2. Row drag is confined to its own Phase·Milestone block (plan.md 2.2 / 0.2)')
  {
    /*
     * Driven through the real ag-grid instance, not a stubbed one, and on the **project**
     * tier — the grid rules are shared (`plan.md` §0.1) and the project board is where
     * users spend their day, so that is the one worth exercising end to end.
     *
     * A managed drag cannot be synthesised in jsdom — ag-grid's drag service needs real
     * hit-testing — so the *state a drag leaves behind* is produced directly on the grid
     * (`setGridOption('rowData', …)` takes the same immutable-reorder path managed drag
     * does) and then `rowDragEnd` is fired. Everything after that point is the shipped
     * code: WpGrid's handler, the guard, the restore, the store, the mock server.
     *
     * The assertions are on the board itself — full row order and every row's
     * phase_id/milestone_id, on the grid AND in the store AND on the server — because the
     * bug being guarded here leaves the row count, the numbering and the toast all looking
     * exactly right.
     */
    const { default: WpGrid } = await import('../components/grid/WpGrid.vue')
    const { AgGridVue } = await import('ag-grid-vue3')
    const { App: AntApp } = await import('ant-design-vue')
    const { BOARD_CONTEXT } = await import('../runtime/context')
    const { createMasterStore } = await import('../stores/master')
    const { createBoardStore } = await import('../stores/board')
    const { BLOCK_DRAG_REFUSED, BLOCK_DRAG_SOLE_ROW } = await import('../composables/useBlockDrag')
    const { defineComponent, h, provide } = await import('vue')
    type GridApiLike = {
      forEachNodeAfterFilterAndSort(cb: (node: { data?: { id: number } }) => void): void
      setGridOption(key: 'rowData', value: unknown[]): void
      getColumnDef(colId: string): { tooltipValueGetter?: (params: never) => string } | null
    }
    type WpItemLike = { id: number; phase_id: number | null; milestone_id: number | null }

    const dragClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const dragMaster = createMasterStore(dragClient)
    const dragBoard = createBoardStore(dragClient, dragMaster, {
      tier: 'project',
      makerId: () => 7,
      // 0.6-4: the store opens the project it is given, not "the first one".
      projectId: () => dragClient.backend.listProjects(7)[0]!.id,
    })
    await dragBoard.init()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(5)
    }

    const warned: string[] = []
    const dragOpened: { kind: string; phaseId?: number | null }[] = []
    const dragContext = {
      api: dragClient,
      board: dragBoard,
      master: dragMaster,
      notify: {
        info() {},
        success() {},
        warn: (m: string) => warned.push(m),
        error: (m: string) => warned.push(m),
      },
      structure: { open: (request: unknown) => dragOpened.push(request as { kind: string }) },
      ownerPicker: { open() {} },
      makerId: 7,
      makerName: null,
      navigate: null,
      popupContainer: () => dom.window.document.body,
    }

    const gridHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(gridHost)
    const gridWrapper = mount(
      defineComponent({
        setup() {
          provide(BOARD_CONTEXT, dragContext as never)
          return () => h(AntApp, null, { default: () => h(WpGrid) })
        },
      }),
      { attachTo: gridHost },
    )
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }

    // AgGridVue hands its `GridApi` out through `expose()`, which lands on the internal
    // instance rather than on the public proxy.
    const gridComponent = gridWrapper.findComponent(AgGridVue) as unknown as {
      vm: {
        $: { exposed?: Record<string, unknown> }
        $emit: (event: string, payload: unknown) => void
      }
    }
    const handle = gridComponent.vm.$.exposed?.api as
      | GridApiLike
      | { value: GridApiLike }
      | undefined
    const api = (
      handle && typeof handle === 'object' && 'value' in handle ? handle.value : handle
    ) as GridApiLike
    check('the real grid api is reachable', typeof api?.forEachNodeAfterFilterAndSort === 'function')
    check('it opened a project, not a version', dragBoard.scope.value?.kind === 'project')

    /** What the grid itself currently shows, independent of the store. */
    const gridOrder = () => {
      const ids: number[] = []
      api.forEachNodeAfterFilterAndSort((node) => {
        if (node.data) ids.push(node.data.id)
      })
      return ids.join(',')
    }
    const order = (rowsIn: { id: number }[]) => rowsIn.map((r) => r.id).join(',')
    /** Order-independent, so it stays constant across a *legal* reorder. */
    const membership = (rowsIn: WpItemLike[]) =>
      [...rowsIn]
        .sort((a, b) => a.id - b.id)
        .map((r) => `${r.id}:${r.phase_id}:${r.milestone_id}`)
        .join('|')
    const projectScope = dragBoard.scope.value!
    const served = () => dragClient.backend.project(projectScope)

    const before = dragBoard.items.value
    const beforeOrder = order(before)
    const beforeMembership = membership(before)
    check('grid, store and server start in agreement', gridOrder() === beforeOrder, gridOrder())
    check('…on 35 rows', before.length === 35, before.length)

    // ── A drag across a phase boundary: plan.md §2.2's reproduction, exactly. ──
    const dragged = before[1]!
    const rest = before.filter((_, i) => i !== 1)
    const crossing = [...rest.slice(0, 20), dragged, ...rest.slice(20)]
    check(
      'the fixture really is a cross-block move',
      crossing[20]!.id === dragged.id && crossing[19]!.phase_id !== dragged.phase_id,
    )

    api.setGridOption('rowData', crossing)
    await nextTick()
    check(
      'POSITIVE CONTROL — the grid can be put into the state a drag leaves behind',
      gridOrder() === order(crossing) && gridOrder() !== beforeOrder,
    )

    warned.length = 0
    gridComponent.vm.$emit('rowDragEnd', { api })
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }

    check('the drop is refused with an explanation', warned.includes(BLOCK_DRAG_REFUSED), warned)
    check('the grid is put back — full row order restored', gridOrder() === beforeOrder)
    check('the store never moved', order(dragBoard.items.value) === beforeOrder)
    check(
      'every row still holds its own phase_id / milestone_id',
      membership(dragBoard.items.value) === beforeMembership,
    )
    check(
      'and the server was never asked — its rows are byte-identical too',
      order(served()) === beforeOrder && membership(served()) === beforeMembership,
    )

    // ── A drag inside the block still reorders, and still changes no membership. ──
    const swapped = [before[0]!, before[1]!, before[3]!, before[2]!, ...before.slice(4)]
    api.setGridOption('rowData', swapped)
    await nextTick()
    warned.length = 0
    gridComponent.vm.$emit('rowDragEnd', { api })
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }

    check('a within-block drag is not refused', warned.length === 0, warned)
    check('the store took the new order', order(dragBoard.items.value) === order(swapped))
    check('the server took it too', order(served()) === order(swapped))
    check(
      'and it is a pure reorder — no row changed phase or milestone',
      membership(dragBoard.items.value) === beforeMembership &&
        membership(served()) === beforeMembership,
    )
    check(
      'row numbers were recomputed by the server',
      dragBoard.items.value.every((r, i) => r.row_no === i + 1),
    )

    // ── A gray row goes anywhere, including where the assigned row was refused. ──
    await dragBoard.appendRow()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    const withGray = dragBoard.items.value
    const grayRow = withGray[withGray.length - 1]!
    check('fixture: a gray row was appended', grayRow.phase_id === null, withGray.length)

    const grayCrossing = [
      ...withGray.slice(0, 20).map((r) => r),
      grayRow,
      ...withGray.slice(20, -1).map((r) => r),
    ]
    api.setGridOption('rowData', grayCrossing)
    await nextTick()
    warned.length = 0
    gridComponent.vm.$emit('rowDragEnd', { api })
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('a gray row dropped mid-block is NOT refused', warned.length === 0, warned)
    check('it landed where it was dropped', dragBoard.items.value[20]!.id === grayRow.id)
    check('the server accepted it', served()[20]!.id === grayRow.id)
    check(
      'and it reclassified nobody — every assigned row kept its membership',
      membership(dragBoard.items.value.filter((r) => r.phase_id !== null)) === beforeMembership,
    )
    check('the gray row is still gray', dragBoard.items.value[20]!.phase_id === null)

    // ── Gray styling, and the handle rules, on the real grid. ──
    const rowEl = (itemId: number) =>
      gridWrapper.element.querySelector(`.ag-center-cols-container .ag-row[row-id="${itemId}"]`)
    const handleShown = (itemId: number) => {
      const el = rowEl(itemId)?.querySelector('[col-id="drag"] .ag-drag-handle')
      return !!el && !el.classList.contains('ag-invisible')
    }

    // Park the gray row at the top so jsdom's virtualised slice actually paints it.
    const nowIds = dragBoard.items.value.filter((r) => r.id !== grayRow.id).map((r) => r.id)
    await dragBoard.applyReorder([grayRow.id, ...nowIds])
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('fixture: the gray row is now row 1', dragBoard.items.value[0]!.id === grayRow.id)
    const grayEl = rowEl(grayRow.id)
    check('it is painted', !!grayEl)
    check(
      'and carries the gray-row class — visually distinct at a glance',
      grayEl?.classList.contains('wp-row-unassigned') === true,
      grayEl?.className,
    )
    check(
      'its Phase cell reads 미지정 rather than a phase label',
      (grayEl?.querySelector('[col-id="phase_id"]')?.textContent ?? '').includes('미지정'),
    )
    check(
      'NEGATIVE CONTROL — an assigned row does not carry it',
      rowEl(dragBoard.items.value[1]!.id)?.classList.contains('wp-row-unassigned') === false,
    )
    check('a gray row always keeps its drag handle', handleShown(grayRow.id))

    /*
     * A row with nowhere legal to go. "Alone in its milestone block" is not enough on its
     * own any more: under §0.2 it could still slide past a *transparent* neighbour. So the
     * fixture removes the gray row first and gives row 1 a one-row milestone block whose
     * only neighbour is a different milestone of the same phase — no swap, in either
     * direction, that `isWithinBlockOrder` would accept.
     */
    await dragBoard.deleteItem(grayRow.id)
    for (let i = 0; i < 25; i++) {
      await nextTick()
      await sleep(10)
    }
    const soloScope = dragBoard.scope.value!
    const secondMilestone = served()[2]!.milestone_id
    dragClient.backend.saveItems(
      soloScope,
      served().map((row, i) => ({
        id: row.id,
        phase_id: row.phase_id,
        milestone_id: i === 1 ? secondMilestone : row.milestone_id,
        title: row.title,
        deliverable: row.deliverable,
        dash_label: row.dash_label,
        gate_code: row.gate_code,
        document_ids: row.documents.map((d) => d.id),
        owner_ids: row.owners.map((o) => o.id),
        status: row.status,
        completion_date: row.completion_date,
      })),
    )
    await dragBoard.reload()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    const now = dragBoard.items.value
    check(
      'fixture: row 1 is the only row of its milestone, and row 2 is a different one',
      now[0]!.milestone_id !== now[1]!.milestone_id &&
        now[1]!.milestone_id === now[2]!.milestone_id &&
        now[0]!.phase_id === now[1]!.phase_id,
      [now[0]!.milestone_no, now[1]!.milestone_no, now[2]!.milestone_no],
    )
    check('a row alone in its block has no drag handle', !handleShown(now[0]!.id))
    check('a row with a block neighbour still has one', handleShown(now[1]!.id))
    check(
      'the column is still there either way — hiding the icon must not move the grid',
      !!rowEl(now[0]!.id)?.querySelector('[col-id="drag"]'),
    )
    const dragCell = (itemId: number) => rowEl(itemId)?.querySelector('[col-id="drag"]')
    check(
      'the grab cursor is withheld with the handle',
      dragCell(now[0]!.id)?.classList.contains('wp-cursor-grab') === false &&
        dragCell(now[1]!.id)?.classList.contains('wp-cursor-grab') === true,
    )
    // ag-grid renders tooltips on hover through its own service rather than as a `title`
    // attribute, so this reads the shipped column definition back off the live grid.
    const tooltipFor = (row: unknown) =>
      api.getColumnDef('drag')?.tooltipValueGetter?.({ data: row } as never)
    check('and the cell explains itself instead', tooltipFor(now[0]!) === BLOCK_DRAG_SOLE_ROW)
    check('a draggable row has nothing to explain', tooltipFor(now[1]!) === '')

    /*
     * ── §0.3: the membership lock, and the one action it leaves. ──
     *
     * The template tier proved a locked *Phase* cell opens no editor. Here is the other
     * half — a locked Milestone cell — plus the round trip the lock exists to funnel every
     * reclassification through: 전환 grays the row **in place**, and reassigning then puts
     * it at the end of the chosen milestone's block.
     */
    /*
     * Deliberately a row well *below* the gray one parked at index 0. Picking the first
     * assigned row would sit it directly beneath that gray row, and an implementation that
     * wrongly relocated on 전환 would compute the same index back — the assertion would pass
     * against broken code. The verify-side twin of this test had exactly that blind spot
     * until a deliberate-break run exposed it.
     */
    /*
     * A gray row is appended first, at the far end of the board, and that is load-bearing
     * rather than scenery: 전환 must leave the row where it stands, and an implementation
     * that wrongly relocated would look for "the last row whose phase is null". With no
     * such row anywhere it would compute the original index straight back and this
     * assertion would pass against broken code — which is exactly what the deliberate-break
     * run showed before the row was added.
     */
    await dragBoard.appendRow()
    for (let i = 0; i < 25; i++) {
      await nextTick()
      await sleep(10)
    }
    const grayAt = dragBoard.items.value.findIndex((r) => r.phase_id === null)
    /*
     * The 전환 target must be a **milestone block start** with a same-block successor.
     * The first version of this fixture hardcoded index 2, which on this board is a
     * mid-block row — and 전환 on a mid-block row leaves the label correctly sitting on
     * the row above, so the label-moves-down assertion below was simply wrong for that
     * layout (it failed against correct code). The user-visible bug only exists when the
     * *label-bearing* row goes gray: the next row must inherit the label, and ag-grid's
     * value-based change detection cannot see that (`milestone_display` is unchanged;
     * only `is_milestone_block_start` flips). Select by predicate so the fixture is the
     * shape the bug needs — the fixture-can-fail rule, in both directions this time.
     */
    const boardRows = dragBoard.items.value
    const assignedIndex = boardRows.findIndex(
      (r, i) =>
        r.phase_id != null &&
        r.is_milestone_block_start &&
        boardRows[i + 1]?.milestone_id === r.milestone_id,
    )
    const assigned = boardRows[assignedIndex]!
    check(
      'fixture: a gray row at the far end, and a fully assigned row near the top',
      grayAt === dragBoard.items.value.length - 1 &&
        assigned.phase_id != null &&
        assigned.milestone_id != null,
      JSON.stringify({ grayAt, assignedIndex, total: dragBoard.items.value.length }),
    )

    const membershipCell = (itemId: number, colId: string) =>
      gridWrapper.element.querySelector(
        `.ag-center-cols-container .ag-row[row-id="${itemId}"] [col-id="${colId}"]`,
      ) as HTMLElement | null

    /*
     * The row *below* the 전환 target, in the same milestone block. Before 전환 it renders
     * the 〃 ditto mark; afterwards it becomes the block's first row and must repaint to
     * the full label. ag-grid only repaints cells whose **value** changed, and this cell's
     * value (`milestone_display`) does not change — only `is_milestone_block_start` flips —
     * so without an explicit redraw the stale 〃 survives and the block's label vanishes
     * from the board entirely (user-reported, 2026-08-08). The fixture preconditions below
     * are what make this test able to fail: same block, currently a ditto cell.
     */
    const successor = dragBoard.items.value[assignedIndex + 1]!
    check(
      'fixture: the target row carries the block label (it is the block start)',
      assigned.is_milestone_block_start === true,
    )
    check(
      'fixture: the row below shares the milestone block',
      successor.milestone_id === assigned.milestone_id,
      { assigned: assigned.milestone_id, successor: successor.milestone_id },
    )
    check(
      'fixture: and currently renders as 〃 — it could not fail otherwise',
      (membershipCell(successor.id, 'milestone_id')?.textContent ?? '').includes('〃'),
      membershipCell(successor.id, 'milestone_id')?.textContent,
    )
    const successorLabel = assigned.milestone_display!

    const msCell = membershipCell(assigned.id, 'milestone_id')
    check('its Milestone cell is painted and marked locked', msCell?.className.includes('wp-cell-locked') === true, msCell?.className)

    msCell!.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check(
      'clicking it opens NO editor on the project tier either',
      !gridWrapper.element.querySelector('.ag-popup-editor'),
    )
    const choiceButton = (label: string) =>
      [...dom.window.document.body.querySelectorAll('.ant-modal button')].find(
        (b) => (b.textContent ?? '').trim() === label,
      ) as HTMLButtonElement | undefined

    check(
      'and offers all three §0.4 actions',
      !!choiceButton('수정') && !!choiceButton('재배치') && !!choiceButton('취소'),
      [...dom.window.document.body.querySelectorAll('.ant-modal button')].map((b) =>
        (b.textContent ?? '').trim(),
      ),
    )

    // [수정] hands off to the shell's 관리 팝업, naming this row's own phase so the
    // Milestone list that opens is the right one.
    dragOpened.length = 0
    choiceButton('수정')!.click()
    for (let i = 0; i < 15; i++) {
      await nextTick()
      await sleep(5)
    }
    check(
      '[수정] opens the Milestone 관리 팝업 for this row\'s phase',
      dragOpened.length === 1 &&
        dragOpened[0]!.kind === 'milestone' &&
        dragOpened[0]!.phaseId === assigned.phase_id,
      dragOpened,
    )
    check('…and changes nothing on its own', dragBoard.items.value[assignedIndex]!.id === assigned.id)

    /*
     * The dialog is *not* torn out of the DOM here, unlike the one in section C. It is a
     * single `<AModal :open>` instance rather than a fresh `modal.confirm` per call, so
     * reopening reuses it — and ripping out `.ant-modal-root`, which is Vue's teleport
     * target, is what stopped the second click from rendering anything at all.
     */
    // [재배치] is the old 전환 path, unchanged.
    msCell!.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    const relocateButton = choiceButton('재배치')
    check('the choice has the 재배치 action', !!relocateButton)
    relocateButton!.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }

    const afterUnassign = dragBoard.items.value
    const grayed = afterUnassign.find((r) => r.id === assigned.id)!
    check('the row turned gray', grayed.phase_id === null && grayed.milestone_id === null)
    check(
      'IN PLACE — 전환 never moves the row',
      afterUnassign.findIndex((r) => r.id === assigned.id) === assignedIndex,
      [afterUnassign.findIndex((r) => r.id === assigned.id), assignedIndex],
    )
    check(
      'the server agrees',
      served().find((r) => r.id === assigned.id)?.phase_id === null,
    )
    check(
      'and it renders as a gray row now',
      gridWrapper.element
        .querySelector(`.ag-center-cols-container .ag-row[row-id="${assigned.id}"]`)
        ?.classList.contains('wp-row-unassigned') === true,
    )
    check(
      'its Phase cell is no longer locked — it is pickable again',
      membershipCell(assigned.id, 'phase_id')?.className.includes('wp-cell-locked') === false,
    )
    {
      const cellText = membershipCell(successor.id, 'milestone_id')?.textContent ?? ''
      check(
        'the label moved down: the next row of the block now shows it, not 〃',
        cellText.includes(successorLabel) && !cellText.includes('〃'),
        { cellText, expected: successorLabel },
      )
    }

    // …and the ordinary gray-row assignment relocates it to the milestone block's end.
    const targetMilestone = afterUnassign.find(
      (r) => r.milestone_id != null && r.id !== assigned.id,
    )!
    await dragBoard.assignMilestone(assigned.id, targetMilestone.milestone_id!)
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    const reassigned = dragBoard.items.value
    const landedAt = reassigned.findIndex((r) => r.id === assigned.id)
    const lastOfBlock = reassigned.reduce(
      (last, row, i) => (row.milestone_id === targetMilestone.milestone_id ? i : last),
      -1,
    )
    check('reassigning after 전환 works', reassigned[landedAt]!.milestone_id === targetMilestone.milestone_id)
    check(
      'and lands at the END of that milestone block',
      landedAt === lastOfBlock,
      { landedAt, lastOfBlock },
    )
    check(
      'the board is still contiguous after the whole round trip',
      (() => {
        const seen = new Set<number>()
        let prev: number | undefined
        for (const row of reassigned) {
          const value = row.milestone_id
          if (value == null || value === prev) continue
          if (seen.has(value)) return false
          seen.add(value)
          prev = value
        }
        return true
      })(),
    )

    /*
     * ── The case the server cannot catch, which is the only one that isolates this gate. ──
     *
     * Everything above survives the client guard being deleted: the drop reaches the mock,
     * its contiguity check 422s, and the store reloads the server's rows — so "the board is
     * unchanged" passes for the wrong reason. A cross-phase drop that lands *contiguously*
     * has no such backstop. `[A/PhaseX, B…/PhaseY]` with A dragged to the end is a
     * perfectly legal board; the server takes it, and Phase Y silently becomes Phase 0.
     */
    const reshaped = served()
    const phaseA = reshaped.find((r) => r.phase_id != null)!.phase_id!
    const phaseB = reshaped.find((r) => r.phase_id != null && r.phase_id !== phaseA)!.phase_id!
    dragClient.backend.saveItems(
      soloScope,
      reshaped.map((row, i) => ({
        id: row.id,
        phase_id: i === 0 ? phaseA : phaseB,
        milestone_id: null,
        title: row.title,
        deliverable: row.deliverable,
        dash_label: row.dash_label,
        gate_code: row.gate_code,
        document_ids: row.documents.map((d) => d.id),
        owner_ids: row.owners.map((o) => o.id),
        status: row.status,
        completion_date: row.completion_date,
      })),
    )
    await dragBoard.reload()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }

    const solo = dragBoard.items.value
    check(
      'fixture: row 1 is a phase of its own, every other row shares the next phase',
      solo[0]!.phase_id === phaseA &&
        solo[0]!.phase_no === 0 &&
        solo.slice(1).every((r) => r.phase_id === phaseB),
    )
    const rotated = [...solo.slice(1), solo[0]!]

    api.setGridOption('rowData', rotated)
    await nextTick()
    check('POSITIVE CONTROL — the grid holds the rotated order', gridOrder() === order(rotated))
    warned.length = 0
    gridComponent.vm.$emit('rowDragEnd', { api })
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }

    check('a contiguous cross-phase drop is refused as well', warned.includes(BLOCK_DRAG_REFUSED))
    check('the grid is put back', gridOrder() === order(solo))
    check('the store never moved', order(dragBoard.items.value) === order(solo))
    check('the server still holds the original order', order(served()) === order(solo))
    check(
      '…and no Phase was renumbered behind the user',
      dragBoard.items.value[0]!.phase_id === phaseA && dragBoard.items.value[0]!.phase_no === 0,
    )

    // The control that makes the five checks above mean something: the same order, sent
    // straight to the server, is accepted — so nothing but the grid refused it.
    const forced = dragClient.backend.reorder(soloScope, rotated.map((r) => r.id))
    check(
      'NEGATIVE CONTROL — the server accepts that exact order without complaint',
      forced.length === solo.length && order(forced) === order(rotated),
    )
    check(
      '…and it is the silent reclassification: Phase 1 has become Phase 0',
      forced[0]!.phase_id === phaseB && forced[0]!.phase_no === 0,
    )

    gridWrapper.unmount()
    gridHost.remove()
  }

  section('E. Publish surfaces per-cell errors — including the gray row')
  {
    // The appended row from section D is blank and unassigned, so publish must fail and
    // decorate exactly its cells.
    const publishButton = [...root.querySelectorAll('button')].find(
      (b) => (b.textContent ?? '').trim() === '발행',
    ) as HTMLButtonElement
    publishButton.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    const flagged = root.querySelectorAll('.wp-cell-error')
    check('publish blocked with cell highlighting', flagged.length > 0, flagged.length)
    const flaggedCols = new Set([...flagged].map((el) => el.getAttribute('col-id')))
    check(
      'the blank row is flagged on title / deliverable / documents / owners',
      ['title', 'deliverable', 'documents', 'owners'].every((c) => flaggedCols.has(c)),
      [...flaggedCols],
    )
    check('error banner shown', text().includes('발행 검증 오류'))
    check('still a DRAFT', text().includes('작성중'))
    check('the gray row is still there — publish refused, it did not delete anything', grayRows() === 1)
  }

  section('F. Read-only mode')
  {
    await wrapper.setProps({ readOnly: true })
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('read-only banner shown', text().includes('읽기 전용'))
    check('row action column hidden', !root.querySelector('[col-id="actions"]'))
    check('drag handles gone', root.querySelectorAll('.ag-drag-handle').length === 0)
    check(
      'every write action is withdrawn, including draft 발행',
      !buttonLabels(root).some((label) =>
        ['임시저장', '발행', '폐기', '행 추가', 'draft 발행'].includes(label),
      ),
      buttonLabels(root),
    )
    // 내보내기는 읽기 연산이라 readOnly 에서도 남는다 (§0.5.7).
    check('XLSX export still offered under readOnly', buttonLabels(root).includes('XLSX 내보내기'), buttonLabels(root))
    check('and the CSV button is gone for good', !buttonLabels(root).includes('CSV'))
    await wrapper.setProps({ readOnly: false })
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
  }

  section('I. ProjectWorkspace — the same grid with no version machinery (plan.md 0.1)')
  {
    /*
     * The two exposes are different products, and the difference has to be observable, not
     * merely intended. The template editor above has 임시저장 / 검증 / 발행 / 폐기 and a
     * version select; this one must have none of them — asserted as *absence from the
     * button list*, with the template editor's own list right next to it as the control so
     * "no publish button" cannot pass by the page having failed to render.
     */
    const projectClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const projectHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(projectHost)
    const project = mount(ProjectWorkspace, {
      attachTo: projectHost,
      props: {
        makerId: 7,
        projectId: seedProjectId(projectClient),
        makerName: 'A설비 주식회사',
        dataSource: projectClient,
        warnOnUnload: false,
        height: '800px',
      },
    })
    for (let i = 0; i < 60; i++) {
      await nextTick()
      await sleep(10)
    }

    const projectEl = project.element as HTMLElement
    const projectText = () => projectEl.textContent ?? ''

    // §0.5-2b: an open project lands on 대시보드, so the grid is one tab away.
    check('an open project lands on 대시보드, not the grid', !projectEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    await clickTab(projectEl, 'Work Package')
    const labels = buttonLabels(projectEl)

    check('the Work Package tab opens the grid', !!projectEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check('with the copied 35 rows', totalRows(projectEl) === 35, totalRows(projectEl))
    check('the maker is shown here — a project has one', projectText().includes('A설비 주식회사'))
    check('and the format it was copied from is named', projectText().includes('포맷:'))

    // `draft 발행` is listed too: it is absent from the template editor as well while a
    // DRAFT is open, so it is checked for absence here but excluded from the control below.
    const versionActions = ['발행', '폐기', '검증', 'draft 발행', '임시저장']
    check(
      'NONE of the version actions are offered',
      versionActions.every((label) => !labels.includes(label)),
      labels,
    )
    check('but plain 저장 is', labels.includes('저장'))
    check('and 행 추가', labels.includes('행 추가'))
    check('no version status tag', !/작성중|발행됨|보관됨/.test(projectText()))
    check(
      'CONTROL — the template editor next door offers every one of them that applies to a DRAFT',
      ['발행', '폐기', '검증', '임시저장'].every((label) => buttonLabels(root).includes(label)),
      buttonLabels(root),
    )

    // The rows still behave: add a gray row and confirm it lands and persists.
    const addButton = [...projectEl.querySelectorAll('button')].find((b) =>
      (b.textContent ?? '').includes('행 추가'),
    ) as HTMLButtonElement
    addButton.click()
    for (let i = 0; i < 25; i++) {
      await nextTick()
      await sleep(10)
    }
    check('행 추가 works on a project too', totalRows(projectEl) === 36, totalRows(projectEl))
    check('and it made a gray row', grayRows(projectEl) === 1, grayRows(projectEl))
    check(
      'the note tells the user what to do with it',
      projectText().includes('미배정(회색) 행'),
    )

    /*
     * 프로젝트 목록 화면은 사라졌다 (`plan.md` §0.6-4) — 진입은 전체 현황의 [이동] 뿐이다.
     * 그러므로 여기서 확인할 것은 "목록으로 돌아가기" 가 아니라 **그 경로가 정말 없는지**다.
     */
    check(
      'there is no ← 프로젝트 목록 button any more',
      ![...projectEl.querySelectorAll('button')].some((b) => (b.textContent ?? '').includes('프로젝트 목록')),
    )
    check('and no project-list screen behind it', !projectText().includes('프로젝트 생성'))
    check('the added row is still on the board', totalRows(projectEl) === 36, totalRows(projectEl))

    // 포맷 배지에 원본 발행 버전이 함께 나온다 (§0.6).
    check('the format tag names the source format', projectText().includes('포맷:'))
    check(
      '…with its published version number',
      (projectEl.querySelector('[data-wp-format-version]')?.textContent ?? '').trim() === 'v1',
      projectEl.querySelector('[data-wp-format-version]')?.textContent,
    )

    project.unmount()
    projectHost.remove()
  }

  section('I2. projectId 없이 마운트하면 빈 상태다 (plan.md 0.6-4)')
  {
    const emptyHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(emptyHost)
    const empty = mount(ProjectWorkspace, {
      attachTo: emptyHost,
      props: {
        makerId: 7,
        projectId: null,
        dataSource: createMockApiClient({ makerId: 7, latencyMs: 0 }),
        warnOnUnload: false,
        height: '400px',
      },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    const emptyEl = empty.element as HTMLElement
    check('it renders guidance, not a project', (emptyEl.textContent ?? '').includes('전체 현황에서 프로젝트를 선택하세요'))
    check('no grid is mounted', !emptyEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check(
      'and it does NOT quietly open the first project instead',
      !(emptyEl.textContent ?? '').includes('2026 AI 과제 1차'),
    )
    empty.unmount()
    emptyHost.remove()
  }

  section('K. 프로젝트 내부 네비 — 4개 탭, 활성 화면만 마운트 (plan.md 0.5-2b)')
  {
    const dashClient = createMockApiClient({ makerId: 7, latencyMs: 0 })

    /*
     * 마운트 전에 NA 행을 하나 만든다. 팔레트 값 자체는 verify 가 §0.5 표와 대조하지만,
     * **짙은 배경이 카드에 실제로 칠해지는지**는 렌더를 봐야 안다 — 종전 구현은 opacity 로
     * 흐리는 방식이었고, 그 잔재가 남으면 값은 맞는데 화면만 흐린 상태가 된다.
     */
    {
      const naScope = dashClient.backend.projectScope(dashClient.backend.listProjects(7)[0]!.id)
      dashClient.backend.saveItems(
        naScope,
        dashClient.backend.project(naScope).map((row, i) => ({
          id: row.id,
          phase_id: row.phase_id,
          milestone_id: row.milestone_id,
          title: row.title,
          deliverable: row.deliverable,
          dash_label: row.dash_label,
          gate_code: row.gate_code,
          document_ids: row.documents.map((d) => d.id),
          owner_ids: row.owners.map((o) => o.id),
          status: i === 0 ? ('NA' as const) : row.status,
          completion_date: row.completion_date,
        })),
      )
    }

    const dashHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(dashHost)
    const dashWrapper = mount(ProjectWorkspace, {
      attachTo: dashHost,
      props: {
        makerId: 7,
        projectId: seedProjectId(dashClient),
        makerName: 'A설비 주식회사',
        dataSource: dashClient,
        warnOnUnload: false,
        height: '800px',
      },
    })
    for (let i = 0; i < 60; i++) {
      await nextTick()
      await sleep(10)
    }

    const dashEl = dashWrapper.element as HTMLElement
    const dashText = () => dashEl.textContent ?? ''
    const cards = () => dashEl.querySelectorAll('[data-wp-dash-card]')

    check(
      'three tabs on an open project',
      tabLabels(dashEl).join('|') === '대시보드|Work Package|문서 등록',
      tabLabels(dashEl),
    )
    // Owner 탭은 제거됐다 (`plan.md` §0.5.9) — 선택·관리는 보드 Owner 셀 팝업이 한다.
    check('no Owner tab any more', !tabLabels(dashEl).includes('Owner'), tabLabels(dashEl))
    check('대시보드 is the landing tab', !!dashEl.querySelector('[data-wp-dash-phase]'))
    check('…so ag-grid is not mounted yet', !dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check('35 cards, one per row', cards().length === 35, cards().length)
    /*
     * 대시보드에도 '행 추가'·'저장' 버튼이 있다 — 주요 링크 표의 것이다 (§0.5.5). 그래서 보드
     * 툴바가 사라졌는지는 **보드에만 있는** CSV 로 판정한다. 라벨만 보고 판정하면 링크 표가
     * 보드 툴바 행세를 하며 이 검사를 통과시킨다.
     */
    check('the board toolbar is not on screen either', !buttonLabels(dashEl).includes('CSV'), buttonLabels(dashEl))

    await clickTab(dashEl, 'Work Package')
    check('Work Package mounts the grid', !!dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check('and the dashboard is GONE, not hidden', cards().length === 0)
    check('the 대시보드 표시 column is in the grid', dashText().includes('대시보드 표시'))

    /*
     * 세로 가운데 정렬 (§0.5.9). jsdom 은 레이아웃을 계산하지 않으므로, 정렬을 만드는 **클래스**가
     * 실제 셀에 붙었는지를 본다 — 구현이 `.wp-cell-mid` 하나로 정렬을 만들기 때문에 이것이 곧
     * 그 정의다. 클램프가 셀에서 안쪽 span 으로 옮겨간 것도 함께 확인한다: 두 성질은 한 요소에
     * 공존할 수 없어서(‑webkit-box vs flex) 이 이동이 정렬의 전제였다.
     */
    for (const colId of ['title', 'deliverable', 'dash_label']) {
      const cell = dashEl.querySelector(`.ag-cell[col-id="${colId}"]`) as HTMLElement | null
      check(`${colId} cells are vertically centred`, !!cell?.className.includes('wp-cell-mid'), cell?.className)
    }
    const titleCell = dashEl.querySelector('.ag-cell[col-id="title"]') as HTMLElement
    check(
      'the clamp moved off the cell onto an inner span',
      !titleCell.className.includes('wp-clamp-2') && !!titleCell.querySelector('.wp-clamp-2'),
      titleCell.className,
    )

    /*
     * Owner 셀 팝업 (§0.5.9). 인라인 에디터가 아니라 셸의 모달이 열려야 한다 — 셀이 편집
     * 가능한 채로 남아 있으면 ag-grid 편집기가 먼저 뜨고 모달은 그 자리에서 사라진다.
     */
    /*
     * 관련문서 셀도 팝업이다 (`plan.md` §0.5.10) — Owner 와 같은 방식. 표시는 원문자가 아니라
     * 숫자이고, 전역 경고 문구는 모델이 바뀌었으므로 어디에도 없어야 한다.
     */
    const docCell = dashEl.querySelector('.ag-cell[col-id="documents"]') as HTMLElement
    check('a 관련 문서 cell is rendered', !!docCell)
    /*
     * 픽스처의 4번째 문서는 **사용 off** 인데 여러 행이 그것을 링크하고 있다 — 사용자가 신고한
     * 잔재가 정확히 이 상태다. 어느 셀에도 나타나면 안 된다.
     */
    const offDocName = 'Model Submission & Evaluation'
    check(
      'setup: rows still link the switched-off document',
      dashClient.backend
        .getProject(dashClient.backend.listProjects(7)[0]!.id)
        .items.some((r) => r.documents.some((d) => d.name === offDocName && d.no === null)),
    )
    /*
     * 렌더러를 직접 마운트해서 본다. 그리드 셀을 훑는 방식으로 썼다가 **공허하게 통과**했다 —
     * ag-grid 가 행을 가상화하고 jsdom 의 뷰포트 높이가 0 이라, 그 문서를 링크한 행들이 애초에
     * DOM 에 없었다. 필터를 지워도 초록이었다.
     */
    {
      const { default: TagListRenderer } = await import('../components/grid/TagListRenderer.vue')
      const tagHost = dom.window.document.createElement('div')
      dom.window.document.body.appendChild(tagHost)
      const tags = mount(TagListRenderer, {
        attachTo: tagHost,
        props: {
          params: {
            source: 'documents',
            data: {
              documents: [
                { id: 1, no: 1, name: '쓰는 문서' },
                { id: 2, no: null, name: offDocName },
              ],
            },
          } as never,
        },
      })
      await nextTick()
      const tagText = (tags.element as HTMLElement).textContent ?? ''
      check('the renderer draws a used document', tagText.includes('1. 쓰는 문서'))
      check('and omits an off one entirely — no leftover chip', !tagText.includes(offDocName), tagText)
      tags.unmount()
      tagHost.remove()
    }
    check(
      'it shows numbers, not circled codes',
      /\d+\./.test(docCell.textContent ?? '') && !/[①-⑳]/.test(docCell.textContent ?? ''),
      docCell.textContent,
    )
    docCell.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    const docTable = dom.window.document.querySelector('[data-wp-doc-table]') as HTMLElement | null
    check('clicking it opens the 관련 문서 popup', !!docTable)
    check('…and NOT an inline ag-grid editor', !dashEl.querySelector('.ag-cell-inline-editing'))
    const docRows = docTable ? [...docTable.querySelectorAll('[data-wp-doc-row]')] : []
    check('it lists the scope documents', docRows.length === 5, docRows.length)
    /*
     * 순서는 **사용(ON) 문서에만** 1..N (`plan.md` §0.5.10 정밀화). 픽스처의 4번째 문서가
     * 미사용이므로 `1,2,3,—,4` 가 정답이다 — 미사용 행이 번호를 먹고 건너뛰면 사용 문서의
     * 번호에 구멍이 생긴다.
     */
    check(
      'numbered 1..N over the USED documents only, with — for the rest',
      docRows.map((r) => (r.querySelector('[data-wp-doc-no]')?.textContent ?? '').trim()).join(',') === '1,2,3,—,4',
      docRows.map((r) => r.querySelector('[data-wp-doc-no]')?.textContent),
    )
    check('the 사용 column is a switch, not a checkbox', !!docTable?.querySelector('[data-wp-doc-used].ant-switch, .ant-switch[data-wp-doc-used]'))
    check(
      'the columns are labelled 선택 · 사용 · 순서',
      ['선택', '사용', '순서'].every((h) => (docTable?.textContent ?? '').includes(h)),
    )
    check('the project popup carries a 사용 column', !!docTable?.querySelector('[data-wp-doc-used]'))
    check('management controls are offered', !!dom.window.document.querySelector('[data-wp-doc-add]'))
    check(
      'and there is no global-scope warning left anywhere',
      !(dom.window.document.querySelector('.ant-modal')?.textContent ?? '').includes('전역'),
    )
    /*
     * off 문서와 선택의 일관성 (§0.5.10 정밀화) — 사용자 재현 시나리오다. 선택된 문서를 off 로
     * 바꾸면 체크가 즉시 풀리고 다시 고를 수 없어야 한다.
     */
    const pickHook = (row: Element) => {
      const hook = row.querySelector('[data-wp-doc-pick]') as HTMLElement
      return (hook.tagName === 'INPUT' ? hook : hook.querySelector('input')) as HTMLInputElement
    }
    const usedHook = (row: Element) => {
      const hook = row.querySelector('[data-wp-doc-used]') as HTMLElement
      return (hook.tagName === 'BUTTON' ? hook : hook.querySelector('button')) as HTMLElement
    }
    const checkedRow = docRows.find((r) => pickHook(r).checked)
    check('setup: some document is selected on this row', !!checkedRow)
    if (checkedRow) {
      check('…and its 사용 switch is on', !pickHook(checkedRow).disabled)
      usedHook(checkedRow).click()
      for (let i = 0; i < 20; i++) {
        await nextTick()
        await sleep(10)
      }
      check('switching 사용 off clears the selection immediately', !pickHook(checkedRow).checked)
      check('…and the checkbox goes disabled — an off document cannot be picked', pickHook(checkedRow).disabled)
      check(
        '…and it loses its 순서 number in the same gesture',
        (checkedRow.querySelector('[data-wp-doc-no]')?.textContent ?? '').trim() === '—',
      )
      // 원상 복구 — 뒤따르는 검사들이 이 픽스처를 그대로 쓴다.
      usedHook(checkedRow).click()
      for (let i = 0; i < 20; i++) {
        await nextTick()
        await sleep(10)
      }
      check('turning it back on re-enables the checkbox', !pickHook(checkedRow).disabled)
      check('…but does not silently re-select it', !pickHook(checkedRow).checked)
    }

    /*
     * 그리고 **실제 저장 경로**로 정리가 확정되는지. 앞의 검사들은 팝업 안 상태만 보므로,
     * 스토어의 `toSavePayload` 가 off 문서를 빼는지는 저장을 눌러 봐야 안다 — 규칙을 검사
     * 안에서 다시 구현하면 스토어가 망가져도 초록이다 (실제로 그랬다).
     */
    if (checkedRow) {
      usedHook(checkedRow).click()
      for (let i = 0; i < 20; i++) {
        await nextTick()
        await sleep(10)
      }
      const docApply = [...dom.window.document.querySelectorAll('.ant-modal button')].find(
        (b) => (b.textContent ?? '').trim() === '적용',
      ) as HTMLButtonElement
      docApply.click()
      for (let i = 0; i < 40; i++) {
        await nextTick()
        await sleep(10)
      }
      const projectId = dashClient.backend.listProjects(7)[0]!.id
      const turnedOff = dashClient.backend
        .listProjectDocuments(projectId)
        .documents.find((d) => !d.is_used && d.name !== offDocName)
      check('setup: the popup really switched one off', !!turnedOff, turnedOff?.name)

      const saveNow = [...dashEl.querySelectorAll('button')].find(
        (b) => (b.textContent ?? '').trim() === '저장',
      ) as HTMLButtonElement
      saveNow?.click()
      for (let i = 0; i < 40; i++) {
        await nextTick()
        await sleep(10)
      }
      check(
        'saving drops every link to the switched-off document',
        !!turnedOff &&
          dashClient.backend
            .rawDocumentLinks(dashClient.backend.projectScope(projectId))
            .every((ids) => !ids.includes(turnedOff.id)),
      )
    }

    const docCancel = [...dom.window.document.querySelectorAll('.ant-modal button')].find(
      (b) => (b.textContent ?? '').trim() === '취소',
    ) as HTMLButtonElement
    docCancel?.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('취소 closes it without applying', !dom.window.document.querySelector('[data-wp-doc-table]'))

    const ownerCell = dashEl.querySelector('.ag-cell[col-id="owners"]') as HTMLElement
    check('an Owner cell is rendered', !!ownerCell)
    ownerCell.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    const ownerTable = dom.window.document.querySelector('[data-wp-owner-table]') as HTMLElement | null
    check('clicking it opens the Owner 선택·관리 popup', !!ownerTable)
    check('…and NOT an inline ag-grid editor', !dashEl.querySelector('.ag-cell-inline-editing'))
    const ownerRows = ownerTable ? [...ownerTable.querySelectorAll('[data-wp-owner-row]')] : []
    check('it lists the scope owners', ownerRows.length === 8, ownerRows.length)
    check('with a checkbox each', ownerRows.every((r) => !!r.querySelector('[data-wp-owner-pick]')))
    check('and management controls', !!dom.window.document.querySelector('[data-wp-owner-add]'))

    /*
     * Owner 팝업 단순화 (`plan.md` §0.5.10 정밀화): 순서 개념이 없어졌고, 추가는 다른 팝업들과
     * 같은 인라인 행 방식이다. 헤더 라벨까지 보는 이유는 이름을 바꿔도 아무 검사도 빨개지지
     * 않았기 때문이다 — 라벨이 요구사항인 이상 라벨을 봐야 한다.
     */
    check(
      'the columns are 선택 · 이름 only',
      (ownerTable?.querySelector('thead')?.textContent ?? '').replace(/\s+/g, '') === '선택이름',
      ownerTable?.querySelector('thead')?.textContent,
    )
    check('no drag handle column survives', !(ownerTable?.textContent ?? '').includes('⋮⋮'))
    check('and no order number is shown', !ownerTable?.querySelector('[data-wp-owner-no]'))

    const ownerAdd = dom.window.document.querySelector('[data-wp-owner-add]') as HTMLButtonElement
    check('the add control is a button, not a side text field', ownerAdd.tagName === 'BUTTON')
    check('…and no standalone name field exists before it is pressed', !dom.window.document.querySelector('[data-wp-owner-new]'))
    ownerAdd.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    const ownerNewHook = dom.window.document.querySelector('[data-wp-owner-new]') as HTMLElement | null
    check('pressing it appends an inline row with an input', !!ownerNewHook)
    const ownerNewInput = (ownerNewHook?.tagName === 'INPUT'
      ? ownerNewHook
      : ownerNewHook?.querySelector('input')) as HTMLInputElement | null
    check('setup: reached the new-owner input', !!ownerNewInput)
    if (ownerNewInput) {
      ownerNewInput.value = '새로 만든 담당'
      ownerNewInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
      ownerNewInput.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
      ownerNewInput.dispatchEvent(new dom.window.FocusEvent('blur', { bubbles: false }))
    }
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    check(
      'naming it creates the owner through the API',
      (dom.window.document.querySelector('[data-wp-owner-table]')?.textContent ?? '').includes('새로 만든 담당'),
    )
    check(
      'and it lands at the end of the list',
      [...(dom.window.document.querySelectorAll('[data-wp-owner-row]') ?? [])]
        .at(-1)
        ?.textContent?.includes('새로 만든 담당') === true,
    )

    // 체크 후 [적용] → 행이 dirty 해지고, API 는 호출되지 않는다 (저장은 수동 경로).
    const pickBoxes = ownerRows.map((r) => {
      const hook = r.querySelector('[data-wp-owner-pick]') as HTMLElement
      return (hook.tagName === 'INPUT' ? hook : hook.querySelector('input')) as HTMLInputElement
    })
    const initiallyChecked = pickBoxes.filter((b) => b.checked).length
    check('the row\'s current owners come pre-checked', initiallyChecked >= 1, initiallyChecked)
    const toTick = pickBoxes.find((b) => !b.checked)!
    toTick.click()
    for (let i = 0; i < 15; i++) {
      await nextTick()
      await sleep(5)
    }
    const applyBtn = [...dom.window.document.querySelectorAll('.ant-modal button')].find(
      (b) => (b.textContent ?? '').trim() === '적용',
    ) as HTMLButtonElement
    check('the popup offers 적용', !!applyBtn)
    applyBtn.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('applying closes the popup', !dom.window.document.querySelector('[data-wp-owner-table]'))
    check(
      'and marks the board dirty — the save path is the toolbar, not this window',
      dashWrapper.emitted('dirty-change')?.at(-1)?.[0] === true,
      dashWrapper.emitted('dirty-change')?.at(-1),
    )
    check('the owner tag is now on the row', (dashEl.querySelector('.ag-cell[col-id="owners"]')?.textContent ?? '').length > 0)

    /*
     * 저장으로 정리한다. 뒤따르는 탭 전환 검사들이 미저장 확인창에 걸리기 때문인데, 그게
     * 곧 §0.5.8 의 결과다 — 자동저장이 사라졌으므로 dirty 는 사람이 저장을 누를 때까지 남는다.
     * 겸사겸사 그 수동 경로가 실제로 dirty 를 지우는지도 여기서 확인된다.
     */
    const saveBtn = [...dashEl.querySelectorAll('button')].find(
      (b) => (b.textContent ?? '').trim() === '저장',
    ) as HTMLButtonElement
    check('the toolbar offers the manual 저장', !!saveBtn)
    saveBtn.click()
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    check(
      'saving clears the dirty flag — the only way it clears now (plan.md 0.5.8)',
      dashWrapper.emitted('dirty-change')?.at(-1)?.[0] === false,
      dashWrapper.emitted('dirty-change')?.at(-1),
    )

    /*
     * XLSX 내보내기 (§0.5.7) — PPT 와 같은 blob 흐름이다. ag-grid 의 CSV 경로는 없어졌으므로,
     * 여기서 확인할 것은 **서버에서 받은 blob 이 다운로드로 이어지는가** 다.
     */
    const xlsxUrls: unknown[] = []
    const xlsxRevoked: unknown[] = []
    const xlsxNames: string[] = []
    const urlHolder2 = globalThis as unknown as {
      URL: { createObjectURL: unknown; revokeObjectURL: unknown }
    }
    const realCreate2 = urlHolder2.URL.createObjectURL
    const realRevoke2 = urlHolder2.URL.revokeObjectURL
    urlHolder2.URL.createObjectURL = (blob: unknown) => {
      xlsxUrls.push(blob)
      return 'blob:xlsx/1'
    }
    urlHolder2.URL.revokeObjectURL = (url: unknown) => {
      xlsxRevoked.push(url)
    }
    const realClick2 = dom.window.HTMLAnchorElement.prototype.click
    dom.window.HTMLAnchorElement.prototype.click = function patched(this: HTMLAnchorElement) {
      xlsxNames.push(this.getAttribute('download') ?? '')
    }
    const xlsxBtn = [...dashEl.querySelectorAll('button')].find(
      (b) => (b.textContent ?? '').trim() === 'XLSX 내보내기',
    ) as HTMLButtonElement
    check('the board toolbar offers XLSX 내보내기', !!xlsxBtn)
    xlsxBtn.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('it fetches a blob through the api client', xlsxUrls.length === 1, xlsxUrls.length)
    check('…named after the project, with an .xlsx extension', xlsxNames[0] === '2026 AI 과제 1차.xlsx', xlsxNames)
    check('…and revokes the object URL', xlsxRevoked.length === 1, xlsxRevoked)
    dom.window.HTMLAnchorElement.prototype.click = realClick2
    urlHolder2.URL.createObjectURL = realCreate2
    urlHolder2.URL.revokeObjectURL = realRevoke2

    // 그리드가 살아 있는 동안 다른 탭으로 가면 그리드는 언마운트되어야 한다 — 동시 2개 금지.
    /*
     * 프로젝트의 문서 탭은 **전역 편집기가 아니라 이 프로젝트의 설정 화면**이다
     * (`plan.md` §0.5-4). 같은 탭 이름 뒤에 계층별로 다른 화면이 있다는 뜻이라, 두 화면을
     * 구분하는 표지를 양쪽 다 확인한다 — 프로젝트 쪽에 '문서 추가' 가 남아 있으면 한 설비사
     * 화면에서 전역 문서를 만들 수 있다는 뜻이다.
     */
    /*
     * 문서 탭은 이제 **문서 등록** 이고 프로젝트 전용이다 (`plan.md` §0.5.10) — 전역 문서
     * 마스터가 사라졌으므로 WP 포맷 관리에는 이 탭 자체가 없다.
     */
    await clickTab(dashEl, '문서 등록')
    check('문서 등록 unmounts the grid', !dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check('it says the documents belong to this project', dashText().includes('이 프로젝트의 문서 목록'))
    check('…and no longer claims they are global', !dashText().includes('전역'))
    check('the five copied documents are listed', dashEl.querySelectorAll('tbody tr').length >= 5, dashEl.querySelectorAll('tbody tr').length)
    check('the order column is derived, shown 1..N', (dashEl.querySelector('[data-wp-doc-order]')?.textContent ?? '').trim() === '1')
    check('the name is editable here (project-owned)', !!dashEl.querySelector('[data-wp-doc-name]'))
    check('a project-local document can be added', buttonLabels(dashEl).includes('문서 추가'))
    check('and the seeded link round-tripped into the field', dashEl.innerHTML.includes('https://cloud.example.com/wp/charter'))
    // 이름이 이제 입력 칸이라 textContent 에는 없다 — value 로 확인한다.
    check(
      '문서명 came across from the format copy',
      [...dashEl.querySelectorAll('[data-wp-doc-name] input, input[data-wp-doc-name]')].some(
        (i) => (i as HTMLInputElement).value === 'Project Charter & R&R',
      ),
      dashEl.querySelectorAll('[data-wp-doc-name]').length,
    )

    check('still no grid anywhere', !dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))

    await clickTab(dashEl, '대시보드')
    check('and back to the dashboard', cards().length === 35, cards().length)
    check('phase headers carry the composed display name', dashText().includes('Pre-Infrastructure Setup'))
    check('cards show dash_label, not the full title', dashText().includes('Gap·자원 계획'))
    check(
      '…and specifically NOT the Key Action Item sentence it replaces',
      !dashText().includes('추가 필요사항'),
    )
    check('the aggregate chips are there', /전체/.test(dashText()) && /진행률/.test(dashText()))
    check(
      'cards no longer print the owner inline — that moved to the popover',
      !dashText().includes('담당 미정'),
    )
    /*
     * 높이 통일 (§0.5.4b). jsdom 은 레이아웃을 계산하지 않으므로 `offsetHeight` 로는 아무것도
     * 알 수 없다 — 그래서 **인라인 height 값**이 전부 같은지를 본다. 구현이 명시적 높이를
     * 박는 방식이라 이것이 곧 "어긋나 보이지 않는다" 의 정의다.
     */
    const cardHeights = [...dashEl.querySelectorAll('[data-wp-dash-card]')].map(
      (el) => (el as HTMLElement).style.height,
    )
    check('every item card is pinned to a height', cardHeights.every((h) => !!h && h !== 'auto'), cardHeights.slice(0, 3))
    check(
      '…and every one of them is the SAME height',
      new Set(cardHeights).size === 1,
      [...new Set(cardHeights)],
    )
    const headerHeights = [...dashEl.querySelectorAll('[data-wp-milestone-header]')].map(
      (el) => (el as HTMLElement).style.height,
    )
    check('milestone headers are pinned too', headerHeights.length >= 13 && headerHeights.every((h) => !!h), headerHeights.length)
    check(
      '…and agree across every phase column',
      new Set(headerHeights).size === 1,
      [...new Set(headerHeights)],
    )
    /*
     * index 는 가운데, 그 아래 표시 텍스트는 좌측 (사용자 지정, 2026-08-08). 한 카드 안에서
     * 두 줄의 정렬이 다르다는 것이 요구사항이라, 둘을 함께 본다 — index 만 확인하면 라벨이
     * 같이 가운데로 끌려가도 통과한다.
     */
    /* 새 팔레트 (§0.5, 2026-08-08): NA 는 짙은 배경 + 밝은 글자, 흐림 없음. */
    const naCard = [...dashEl.querySelectorAll('[data-wp-dash-card]')].find(
      (el) => (el as HTMLElement).style.backgroundColor === 'rgb(51, 65, 85)',
    ) as HTMLElement | undefined
    check('an NA card is painted with the dark blocked background', !!naCard, naCard?.style.backgroundColor)
    check('…with light text on it', naCard?.style.color === 'rgb(203, 213, 225)', naCard?.style.color)
    check('…and no opacity wash — the dark fill IS the signal now', !naCard?.style.opacity, naCard?.style.opacity)
    check(
      'the index line is not dimmed either, so it stays legible on the dark card',
      !((naCard?.querySelector('div') as HTMLElement | null)?.style.opacity),
    )

    const firstCard = dashEl.querySelector('[data-wp-dash-card]') as HTMLElement
    const cardLines = [...firstCard.querySelectorAll('div')] as HTMLElement[]
    check('the card index line is centred', cardLines[0]!.className.includes('wp-text-center'), cardLines[0]!.className)
    check(
      '…while the label below it stays left-aligned',
      !cardLines[1]!.className.includes('wp-text-center'),
      cardLines[1]!.className,
    )

    check(
      'the unassigned card is held to the same height as the rest',
      new Set([...dashEl.querySelectorAll('[data-wp-dash-unassigned]')].map((el) => (el as HTMLElement).style.height))
        .size <= 1,
    )

    // ── PPT 내보내기 (§0.5.6) ──
    const exportBtn = dashEl.querySelector('[data-wp-export-pptx]') as HTMLButtonElement
    check('the dashboard offers PPT 내보내기', !!exportBtn && (exportBtn.textContent ?? '').includes('PPT'))
    const createdUrls: unknown[] = []
    const revokedUrls: unknown[] = []
    const clickedDownloads: string[] = []
    /*
     * `globalThis.URL`, not `dom.window.URL` — Node already defines `URL`, so the jsdom
     * global copy at the top of this file skipped it (`if (key in g) continue`). The
     * component resolves the bare identifier, which is Node's. Spying on the window copy
     * therefore recorded nothing while the real call sailed past, which is exactly how this
     * first failed.
     */
    const urlHolder = globalThis as unknown as {
      URL: { createObjectURL: unknown; revokeObjectURL: unknown }
    }
    const realCreate = urlHolder.URL.createObjectURL
    const realRevoke = urlHolder.URL.revokeObjectURL
    urlHolder.URL.createObjectURL = (blob: unknown) => {
      createdUrls.push(blob)
      return 'blob:mock/1'
    }
    urlHolder.URL.revokeObjectURL = (url: unknown) => {
      revokedUrls.push(url)
    }
    const realAnchorClick = dom.window.HTMLAnchorElement.prototype.click
    dom.window.HTMLAnchorElement.prototype.click = function patched(this: HTMLAnchorElement) {
      clickedDownloads.push(this.getAttribute('download') ?? '')
    }
    exportBtn.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('clicking it fetches a blob through the api client', createdUrls.length === 1, createdUrls.length)
    check('…and triggers a download named after the project', clickedDownloads[0] === '2026 AI 과제 1차.pptx', clickedDownloads)
    check(
      '…and revokes the object URL rather than pinning the file in memory',
      revokedUrls.length === 1 && revokedUrls[0] === 'blob:mock/1',
      revokedUrls,
    )
    check('no stray anchor is left in the document', dom.window.document.querySelectorAll('a[download]').length === 0)
    dom.window.HTMLAnchorElement.prototype.click = realAnchorClick
    urlHolder.URL.createObjectURL = realCreate
    urlHolder.URL.revokeObjectURL = realRevoke

    check('주요 링크 table is mounted under the dashboard', !!dashEl.querySelector('[data-wp-links]'))
    check('…with the seeded rows', dashText().includes('주요 링크'))
    check(
      '…and its open icon is only offered for a valid url',
      dashEl.querySelectorAll('[data-wp-link-open]').length >= 1,
    )
    /*
     * 범례 (§0.5 범례 개정). 세 가지가 요구사항이고 셋 다 눈으로만 확인되던 것들이라
     * 각각 단언한다: 그룹 순서(주관 먼저), 주관 스와치가 좌측 바를 가진 카드 모양일 것,
     * 상태 스와치가 같은 모양에서 배경만 바뀔 것.
     */
    check('and the two legends', dashText().includes('상태 (배경)') && dashText().includes('주관 (좌측 바)'))
    const legendGroups = [...dashEl.querySelectorAll('[data-wp-legend-group]')].map((g) =>
      g.getAttribute('data-wp-legend-group'),
    )
    check('주관 comes before 상태 in the legend', legendGroups.join(',') === 'owner,status', legendGroups)

    const swatches = [...dashEl.querySelectorAll('[data-wp-legend-swatch]')] as HTMLElement[]
    check('every legend entry uses the same mini-card swatch', swatches.length === OWNER_KIND_COUNT + STATUS_COUNT, swatches.length)
    check('no swatch is a circle any more', swatches.every((el) => !el.className.includes('rounded-full')))

    const ownerSwatches = swatches.slice(0, OWNER_KIND_COUNT)
    const statusSwatches = swatches.slice(OWNER_KIND_COUNT)
    check(
      '주관 swatches all carry a left bar',
      ownerSwatches.every((el) => !!el.querySelector('[data-wp-legend-bar]')),
    )
    check(
      '…and vary ONLY that bar — every background is the same',
      new Set(ownerSwatches.map((el) => el.style.backgroundColor)).size === 1 &&
        new Set(
          ownerSwatches.map(
            (el) => (el.querySelector('[data-wp-legend-bar]') as HTMLElement).style.backgroundColor,
          ),
        ).size === OWNER_KIND_COUNT,
      ownerSwatches.map((el) => el.style.backgroundColor),
    )
    check(
      '상태 swatches use the same card shape, bar included',
      statusSwatches.every((el) => !!el.querySelector('[data-wp-legend-bar]')),
    )
    check(
      '…and vary ONLY the background — every bar is the same neutral',
      new Set(
        statusSwatches.map(
          (el) => (el.querySelector('[data-wp-legend-bar]') as HTMLElement).style.backgroundColor,
        ),
      ).size === 1 &&
        new Set(statusSwatches.map((el) => el.style.backgroundColor)).size === STATUS_COUNT,
      statusSwatches.map((el) => el.style.backgroundColor),
    )

    /*
     * 미저장 변경이 있는 Work Package 를 떠나려 하면 확인을 받는다 (§0.5-2b). 확인 창을
     * 띄운 채로는 탭이 바뀌지 않아야 한다 — 바뀌어 버리면 "확인"이 사후 통보가 된다.
     */
    await clickTab(dashEl, 'Work Package')
    check('setup: back on the grid', !!dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    const addRow = [...dashEl.querySelectorAll('button')].find((b) =>
      (b.textContent ?? '').includes('행 추가'),
    ) as HTMLButtonElement
    addRow.click()
    for (let i = 0; i < 25; i++) {
      await nextTick()
      await sleep(10)
    }
    check('setup: a gray row was added and saved', totalRows(dashEl) === 36, totalRows(dashEl))

    /*
     * 행 추가는 서버를 거쳐 저장되므로 dirty 가 **아니다** — 셀 편집이라야 미저장이 된다.
     *
     * 그래서 진짜로 셀을 편집한다. 스토어를 직접 부르는 편이 쉬웠겠지만, 이 빌드는
     * `<script setup>` 을 inline 모드로 컴파일해서 `setupState` 가 비어 있고 setup 바인딩에
     * 닿을 방법이 없다 (직접 확인함). 결과적으로 이쪽이 더 정직한 검사이기도 하다 —
     * 셀 편집 → valueSetter → patchItem → dirty → 확인창까지가 실제 사용자 경로다.
     */
    const editCell = dashEl.querySelector(
      '.ag-center-cols-container .ag-row[row-index="0"] [col-id="deliverable"]',
    ) as HTMLElement | null
    check('setup: found a text cell to edit', !!editCell)
    ;(editCell as HTMLElement).click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    // Scoped to the cell that is actually editing: a bare `input.ag-input-field-input`
    // matches ag-grid's checkbox inputs elsewhere in the grid, which is what it grabbed first.
    const editor = dashEl.querySelector('.ag-cell-inline-editing input') as HTMLInputElement | null
    check('setup: singleClickEdit opened an inline editor', !!editor)
    if (editor) {
      editor.value = '미저장 편집'
      editor.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
      editor.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
      // ag-grid commits an inline editor on Enter, which it listens for on the *cell*, and
      // on focus loss (`stopEditingWhenCellsLoseFocus`). jsdom delivers neither reliably, so
      // both are driven explicitly and the blur is the one that actually lands.
      editor.closest('.ag-cell')?.dispatchEvent(
        new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      )
      editor.dispatchEvent(new dom.window.Event('blur', { bubbles: false }))
      editor.dispatchEvent(new dom.window.FocusEvent('focusout', { bubbles: true }))
    }
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check(
      'setup: the edit landed and the board is now dirty',
      dashWrapper.emitted('dirty-change')?.some((e) => e[0] === true) === true,
      dashWrapper.emitted('dirty-change'),
    )

    await clickTab(dashEl, '대시보드')
    check(
      'leaving a dirty Work Package asks first — the tab does NOT change yet',
      !!dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper') && cards().length === 0,
    )
    const confirmText = dom.window.document.body.textContent ?? ''
    check('and the confirm names the risk', confirmText.includes('저장하지 않은 변경이 있습니다'), confirmText.slice(0, 120))

    // 확인 창의 [이동] 을 누르면 그때 전환된다.
    const okButton = [...dom.window.document.querySelectorAll('.ant-modal button')].find((b) =>
      (b.textContent ?? '').trim() === '이동',
    ) as HTMLButtonElement | undefined
    okButton?.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('confirming completes the switch', cards().length === 36, cards().length)
    check('and the grid came down with it', !dashEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check(
      'the unsaved edit survived the switch — it was never discarded',
      dashWrapper.emitted('dirty-change')?.at(-1)?.[0] === true,
      dashWrapper.emitted('dirty-change')?.at(-1),
    )

    auditBorders(dashEl, '프로젝트 대시보드')

    dashWrapper.unmount()
    check('unmount leaves no dashboard DOM behind', dashHost.querySelectorAll('[data-wp-dash-card]').length === 0)
    dashHost.remove()
  }

  section('L. ProjectsOverview — 설비사 구획 + 미니 대시보드 (plan.md 0.5-3 개정)')
  {
    const overviewClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    /*
     * Three projects across two makers, one of them with two — the maker sections are the
     * point of the revision, and a one-project-per-maker fixture cannot tell "grouped by
     * maker" apart from "one row each".
     */
    const overviewTemplate = overviewClient.backend.listTemplates()[0]!
    const publishedId = overviewClient.backend
      .listVersions(overviewTemplate.id)
      .find((v) => v.status === 'PUBLISHED')!.id
    overviewClient.backend.createProject({
      maker_id: 9,
      name: '다른 설비사 과제',
      template_id: overviewTemplate.id,
      template_version_id: publishedId,
    })
    overviewClient.backend.createProject({
      maker_id: 7,
      name: '같은 설비사 2차 과제',
      template_id: overviewTemplate.id,
      template_version_id: publishedId,
    })

    const opened: { projectId: number; makerId: number }[] = []
    const overviewHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(overviewHost)
    const overview = mount(ProjectsOverview, {
      attachTo: overviewHost,
      props: {
        dataSource: overviewClient,
        onOpenProject: (projectId: number, makerId: number) =>
          opened.push({ projectId, makerId }),
        height: '600px',
      },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }

    const overviewEl = overview.element as HTMLElement
    const overviewText = () => overviewEl.textContent ?? ''
    const makerSections = () => overviewEl.querySelectorAll('[data-wp-maker-group]')
    const overviewRows = () => overviewEl.querySelectorAll('[data-wp-overview-row]')

    check('root carries the wp-root style anchor', overviewEl.classList.contains('wp-root'))
    check('it announces itself', overviewText().includes('전체 현황'))
    check('three project rows in total', overviewRows().length === 3, overviewRows().length)
    check(
      'grouped into 설비사 구획 by the SERVER (plan.md 0.6)',
      makerSections().length >= 2,
      makerSections().length,
    )
    const sectionOf = (name: string) =>
      [...makerSections()].find((el) => (el.textContent ?? '').includes(name)) as HTMLElement

    // ── 디자인 언어 (§0.6-4): 카드 구획 + 들여쓴 프로젝트 행 ──
    const anySection = makerSections()[0] as HTMLElement
    check(
      'each maker is a rounded card, not a square-bordered strip',
      anySection.className.includes('rounded-xl'),
      anySection.className,
    )
    check('…lifted off the page with a shadow', anySection.style.boxShadow.length > 0, anySection.style.boxShadow)
    check('…on a white surface', anySection.style.background === 'rgb(255, 255, 255)', anySection.style.background)
    check(
      'and the page behind it is tinted, so the cards read as separate',
      (overviewEl.querySelector('[data-wp-maker-group]')!.parentElement as HTMLElement).style.background === 'rgb(248, 250, 252)',
    )
    check(
      'project rows are indented below the maker header',
      [...overviewRows()].every((r) => r.className.includes('wp-ml-6')),
      (overviewRows()[0] as HTMLElement).className,
    )
    const twoRowSection = [...makerSections()].find(
      (el) => el.querySelectorAll('[data-wp-overview-row]').length > 1,
    ) as HTMLElement
    const stacked = [...twoRowSection.querySelectorAll('[data-wp-overview-row]')] as HTMLElement[]
    check(
      'the first row has no divider, later ones do',
      !stacked[0]!.className.includes('border-t') && stacked[1]!.className.includes('border-t'),
      stacked.map((r) => r.className.includes('border-t')),
    )
    check(
      'the maker with two projects holds both under one header',
      sectionOf('G정밀').querySelectorAll('[data-wp-overview-row]').length === 2,
      sectionOf('G정밀').querySelectorAll('[data-wp-overview-row]').length,
    )
    check('a resolved maker shows its name', overviewText().includes('G정밀'))
    check(
      'and one outside the resolver falls back to 설비사 #<id> rather than blank',
      overviewText().includes('설비사 #9'),
    )
    check('every project is named', ['2026 AI 과제 1차', '다른 설비사 과제', '같은 설비사 2차 과제'].every((n) => overviewText().includes(n)))
    check('no ag-grid was loaded — this screen has no grid', !overviewEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))

    const firstRow = overviewRows()[0] as HTMLElement
    const cells = firstRow.querySelectorAll('[data-wp-minimap-cell]')
    check('the mini dashboard draws one cell per item', cells.length === 35, cells.length)
    check('cells are textless — the mini dashboard hides text', [...cells].every((c) => (c.textContent ?? '') === ''))
    check(
      'phase bands are labelled Phase N and visible',
      [...firstRow.querySelectorAll('[data-wp-phase-band]')].map((b) => (b.textContent ?? '').trim()).join('|') === 'Phase 0|Phase 1|Phase 2|Phase 3',
      [...firstRow.querySelectorAll('[data-wp-phase-band]')].map((b) => (b.textContent ?? '').trim()),
    )
    check(
      'cells subgroup by milestone — 13 groups across the 4 bands',
      firstRow.querySelectorAll('[data-wp-milestone-group]').length === 13,
      firstRow.querySelectorAll('[data-wp-milestone-group]').length,
    )
    check(
      'the milestone label is hover-only, not painted',
      (firstRow.querySelector('[data-wp-milestone-group]') as HTMLElement).getAttribute('title') === '0.1' &&
        !(firstRow.querySelector('[data-wp-milestone-group]')?.textContent ?? '').includes('0.1'),
    )
    check(
      'the hover hint carries index · key action · milestone · status',
      (cells[0]!.getAttribute('data-wp-cell-hint') ?? '') === '1. Gap·자원 계획 · 0.1 · 진행전',
      cells[0]!.getAttribute('data-wp-cell-hint'),
    )
    check(
      '진행전 cells are an empty box with a visible border, not a white blur',
      (cells[0] as HTMLElement).style.backgroundColor === 'rgb(255, 255, 255)' &&
        (cells[0] as HTMLElement).style.borderColor === 'rgb(148, 163, 184)',
      [(cells[0] as HTMLElement).style.backgroundColor, (cells[0] as HTMLElement).style.borderColor],
    )

    // ── 4구획 레이아웃 (§0.5-3b) ──
    for (const [hook, label] of [
      ['data-wp-col-name', '① 프로젝트명'],
      ['data-wp-col-counts', '② 집계'],
      ['data-wp-col-minimap', '③ 미니 대시보드'],
      ['data-wp-col-documents', '④ 문서 링크'],
      ['data-wp-col-open', '⑤ 이동'],
    ] as const) {
      check(`${label} column is present on every row`, [...overviewRows()].every((r) => !!r.querySelector(`[${hook}]`)))
    }
    const minimapWidths = [...overviewEl.querySelectorAll('[data-wp-col-minimap]')].map(
      (el) => (el as HTMLElement).style.width,
    )
    check(
      'the minimap is a FIXED width on every row, so ④ lines up',
      new Set(minimapWidths).size === 1 && minimapWidths[0] === '740px',
      minimapWidths,
    )
    check(
      'and it scrolls internally rather than widening the row',
      (overviewEl.querySelector('[data-wp-col-minimap]') as HTMLElement).className.includes('overflow-x-auto'),
    )

    // ── ⑤ 이동 — 마지막 칸의 텍스트 버튼 (§0.5-3b, 2026-08-08 정정) ──
    const openBtn = firstRow.querySelector('[data-wp-open-project]') as HTMLButtonElement
    check('the move control is a button', !!openBtn && openBtn.tagName === 'BUTTON')
    check('…labelled with words, not an icon', (openBtn.textContent ?? '').trim() === '이동', openBtn.textContent)
    check('…and it lives in the last column', !!openBtn.closest('[data-wp-col-open]'))
    check(
      'the name column no longer carries it',
      !firstRow.querySelector('[data-wp-col-name] [data-wp-open-project]'),
    )
    openBtn.click()
    await nextTick()
    check('clicking it calls onOpenProject', opened.length === 1, opened)
    check(
      'with both ids — the host needs the maker to route',
      opened[0]?.makerId === 7 && typeof opened[0]?.projectId === 'number',
      opened[0],
    )
    // 셀을 눌러도 화면이 튀지 않는다 — 툴팁을 읽으려는 클릭이 이동이 되면 안 된다.
    ;(cells[0] as HTMLElement).click()
    await nextTick()
    check('clicking a minimap cell navigates nowhere', opened.length === 1, opened)

    // ── ④ 문서 링크 (§0.5-3b / §0.5-4) ──
    const chips = [...firstRow.querySelectorAll('[data-wp-doc-chip]')] as HTMLButtonElement[]
    check('only the used documents get a chip', chips.length === 4, chips.length)
    const byStatus = (status: string) => chips.filter((c) => c.getAttribute('data-wp-doc-status') === status)
    /*
     * §0.5-3b 정정: **세 상태 모두 같은 아이콘, 색으로만 구분.** 이전 판은 작성전을 "작성 전"
     * 이라는 글자로 그려서 넷째 칸이 글리프와 텍스트가 섞인 들쭉날쭉한 줄이 됐고, 그 칸이
     * 존재하는 이유인 한눈 스캔이 사라졌다.
     */
    check('every chip carries the SAME icon, whatever its state', chips.every((c) => !!c.querySelector('svg')), chips.map((c) => c.getAttribute('data-wp-doc-status')))
    check('no chip falls back to words', chips.every((c) => !(c.textContent ?? '').includes('작성 전')))
    check('작성전 is grey', byStatus('NOT_WRITTEN').every((c) => c.style.color === 'rgb(148, 163, 184)'), byStatus('NOT_WRITTEN').map((c) => c.style.color))
    check('…and still not clickable', byStatus('NOT_WRITTEN').every((c) => c.disabled))
    check('완료 is emerald', byStatus('DONE').every((c) => c.style.color === 'rgb(5, 150, 105)'), byStatus('DONE').map((c) => c.style.color))
    check('작성중 is amber', byStatus('WRITING').every((c) => c.style.color === 'rgb(217, 119, 6)'), byStatus('WRITING').map((c) => c.style.color))
    check(
      'the three colours are actually distinct',
      new Set(chips.map((c) => c.style.color)).size === 3,
      chips.map((c) => c.style.color),
    )

    // 순서는 아이콘 옆 텍스트가 아니라 모서리 배지로 (§0.5-3b, 2026-08-08).
    const badges = chips.map((c) => c.querySelector('[data-wp-doc-badge]') as HTMLElement | null)
    check('every chip carries a corner badge', badges.every((b) => !!b))
    /*
     * 배지도 같은 파생을 쓴다 (§0.5.10 정밀화). overview 는 사용 문서만 싣고 그 안에서 1..N
     * 이므로 `1,2,3,4` 다 — 예전에는 원문자 코드에서 뽑아 `1,2,3,5` 였다.
     */
    check(
      'the badge is the used-only display number',
      badges.map((b) => (b!.textContent ?? '').trim()).join(',') === '1,2,3,4',
      badges.map((b) => (b!.textContent ?? '').trim()),
    )
    check(
      'no circled code is printed anywhere on the chip',
      chips.every((c) => !/[①-⑳]/.test(c.textContent ?? '')),
      chips.map((c) => (c.textContent ?? '').trim()),
    )
    check(
      'the badge stays neutral so it does not fight the status colour',
      badges.every((b) => b!.style.color === 'rgb(71, 85, 105)'),
      badges.map((b) => b!.style.color),
    )
    check(
      'a written document WITHOUT a link is not clickable',
      chips.some((c) => c.getAttribute('data-wp-doc-openable') === 'no' && c.getAttribute('data-wp-doc-status') === 'WRITING' && c.disabled),
    )

    // 링크가 있는 칩만 window.open 을 부른다.
    const openedUrls: unknown[][] = []
    const realOpen = dom.window.open
    ;(dom.window as unknown as { open: unknown }).open = (...args: unknown[]) => {
      openedUrls.push(args)
      return null
    }
    const openable = chips.find((c) => c.getAttribute('data-wp-doc-openable') === 'yes')!
    openable.click()
    await nextTick()
    check('clicking a linked document opens it in a new tab', openedUrls.length === 1, openedUrls)
    check(
      '…with noopener, so the opened page gets no handle on the host',
      openedUrls[0]?.[1] === '_blank' && openedUrls[0]?.[2] === 'noopener',
      openedUrls[0],
    )
    check('…and the URL is the stored link', String(openedUrls[0]?.[0] ?? '').startsWith('https://cloud.example.com/'), openedUrls[0]?.[0])
    byStatus('NOT_WRITTEN')[0]?.click()
    await nextTick()
    check('a 작성 전 chip opens nothing', openedUrls.length === 1, openedUrls.length)
    ;(dom.window as unknown as { open: unknown }).open = realOpen

    // ── §0.6 허브 동작 ──
    const gSection = sectionOf('G정밀')

    // 접기/펼치기 — 기본은 펼침.
    check('sections start expanded', gSection.querySelectorAll('[data-wp-overview-row]').length === 2)
    const toggleBtn = gSection.querySelector('[data-wp-maker-toggle]') as HTMLButtonElement
    check('the header is a toggle', !!toggleBtn && toggleBtn.getAttribute('aria-expanded') === 'true')
    toggleBtn.click()
    await nextTick()
    check('collapsing hides the rows', sectionOf('G정밀').querySelectorAll('[data-wp-overview-row]').length === 0)
    check('…and the header says so', (sectionOf('G정밀').querySelector('[data-wp-maker-toggle]') as HTMLElement).getAttribute('aria-expanded') === 'false')
    ;(sectionOf('G정밀').querySelector('[data-wp-maker-toggle]') as HTMLButtonElement).click()
    await nextTick()
    check('expanding brings them back', sectionOf('G정밀').querySelectorAll('[data-wp-overview-row]').length === 2)

    // 프로젝트가 0개인 설비사도 섹션이 온다 (체크된 경우) — 빈 상태 + 추가 버튼.
    check('every section offers 프로젝트 추가', [...makerSections()].every((el) => !!el.querySelector('[data-wp-add-project]')))

    // 인라인 이름 수정.
    const rowOne = sectionOf('G정밀').querySelector('[data-wp-overview-row]') as HTMLElement
    const nameEl = rowOne.querySelector('[data-wp-rename-project]') as HTMLElement
    check('the project NAME is the rename trigger, not a pencil', !!nameEl && nameEl.tagName === 'SPAN')
    check('…and it advertises itself as clickable', nameEl.className.includes('wp-cursor-pointer'), nameEl.className)
    check('…with a hover underline rather than a permanent one', nameEl.className.includes('wp-border-transparent') && nameEl.className.includes('hover:wp-border-slate-400'))
    check('no pencil button survives', rowOne.querySelectorAll('button[data-wp-rename-project]').length === 0)
    nameEl.click()
    await nextTick()
    const renameInput = rowOne.querySelector('[data-wp-rename-input] input, input[data-wp-rename-input]') as HTMLInputElement
      ?? (sectionOf('G정밀').querySelector('.ant-input') as HTMLInputElement)
    check('clicking it opens an input', !!renameInput)
    renameInput.value = '이름 바꾼 과제'
    renameInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    await nextTick()
    const commit = sectionOf('G정밀').querySelector('[data-wp-rename-commit]') as HTMLButtonElement
    commit.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('committing renames the project through the API', overviewText().includes('이름 바꾼 과제'), overviewText().slice(0, 200))
    check('and the editor closed', !overviewEl.querySelector('[data-wp-rename-commit]'))

    // Esc 는 저장하지 않고 빠져나온다.
    const nameAgain = sectionOf('G정밀').querySelector('[data-wp-rename-project]') as HTMLElement
    nameAgain.click()
    await nextTick()
    const escInput = sectionOf('G정밀').querySelector('.ant-input') as HTMLInputElement
    escInput.value = '버릴 이름'
    escInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    await nextTick()
    escInput.dispatchEvent(new dom.window.KeyboardEvent('keyup', { key: 'Escape', bubbles: true }))
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('Esc leaves rename mode', !overviewEl.querySelector('[data-wp-rename-commit]'))
    check('…and discards the edit', !overviewText().includes('버릴 이름') && overviewText().includes('이름 바꾼 과제'))

    // 4구획 세로 가운데 정렬 (§0.6 가독성).
    const grid = (overviewRows()[0] as HTMLElement).querySelector('[data-wp-col-name]')!.parentElement as HTMLElement
    check('the five columns are vertically centred', grid.className.includes('items-center'), grid.className)

    /*
     * 설비사 설정 은 이제 **네 번째 노출**이다 (`plan.md` §0.6-4) — 전체 현황 안의 버튼이
     * 아니다. 여기서는 그것이 정말 빠졌는지만 확인하고, 화면 자체는 섹션 M 에서 독립
     * 마운트로 검사한다.
     */
    check(
      'the overview no longer carries a 설비사 설정 button',
      ![...overviewEl.querySelectorAll('button')].some((b) => (b.textContent ?? '').trim() === '설비사 설정'),
    )
    check('and no settings table leaked into it', overviewEl.querySelectorAll('[data-wp-maker-show]').length === 0)

    // ── readOnly: 세 가지 쓰기 경로가 전부 사라진다 ──
    const roHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(roHost)
    const readOnly = mount(ProjectsOverview, {
      attachTo: roHost,
      props: {
        dataSource: createMockApiClient({ makerId: 7, latencyMs: 0 }),
        onOpenProject: () => {},
        readOnly: true,
        height: '600px',
      },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    const roEl = readOnly.element as HTMLElement
    check('readOnly still renders the rows', roEl.querySelectorAll('[data-wp-overview-row]').length >= 1)
    check('but offers no 프로젝트 추가', roEl.querySelectorAll('[data-wp-add-project]').length === 0)
    const roName = roEl.querySelector('[data-wp-rename-project]') as HTMLElement
    check('the name still renders under readOnly', !!roName)
    check('…but is not advertised as editable', !roName.className.includes('wp-cursor-pointer'), roName.className)
    roName.click()
    await nextTick()
    check('…and clicking it opens no editor', roEl.querySelectorAll('[data-wp-rename-commit]').length === 0)
    check(
      'and no 설비사 설정 entry point — it is a separate expose the host permissions itself',
      ![...roEl.querySelectorAll('button')].some((b) => (b.textContent ?? '').trim() === '설비사 설정'),
    )
    check('while 이동 still works — read access is not no access', roEl.querySelectorAll('[data-wp-open-project]').length >= 1)
    readOnly.unmount()
    roHost.remove()

    // No callback: the name must go inert rather than invent a destination.
    const inertHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(inertHost)
    const inert = mount(ProjectsOverview, {
      attachTo: inertHost,
      props: { dataSource: createMockApiClient({ makerId: 7, latencyMs: 0 }), height: '600px' },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    const inertEl = inert.element as HTMLElement
    check('CONTROL — it still renders without a callback', !!inertEl.querySelector('[data-wp-col-name]'))
    check(
      'but there is no 이동 button at all',
      inertEl.querySelectorAll('[data-wp-open-project]').length === 0,
    )
    check('though the column itself still holds the layout', inertEl.querySelectorAll('[data-wp-col-open]').length >= 1)
    ;(inertEl.querySelector('[data-wp-col-name]') as HTMLElement).click()
    await nextTick()
    check('and clicking the name reaches nobody', opened.length === 1, opened)
    check('the two instances did not share state', inertEl.querySelectorAll('[data-wp-overview-row]').length === 1)

    auditBorders(overviewEl, '전체 현황')

    // NEGATIVE CONTROL — the audit must be able to see a violation at all.
    const probeEl = dom.window.document.createElement('div')
    probeEl.className = 'wp-border wp-rounded'
    overviewEl.appendChild(probeEl)
    check('NEGATIVE CONTROL — the audit flags a width-only border', borderOffenders(overviewEl).length === 1)
    probeEl.remove()

    inert.unmount()
    inertHost.remove()
    overview.unmount()
    check('unmount removes the whole subtree', overviewHost.children.length === 0)
    overviewHost.remove()
  }

  section('N. 공용 팝오버 (plan.md 0.5-2 / 0.5-3)')
  {
    /*
     * 팝오버 본문은 hover 시에만 렌더되므로, 트리거를 흉내 내는 대신 `open` 을 직접 켜서
     * 마운트한다. 이걸 안 하면 팝오버가 실제로 무엇을 쓰는지는 어디에서도 검사되지 않는다 —
     * 일부러 접두사를 지워봤을 때 아무 검사도 빨개지지 않아서 알게 됐다.
     */
    const { default: ItemPopover } = await import('../components/dashboard/ItemPopover.vue')
    const popHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(popHost)
    const pop = mount(ItemPopover, {
      attachTo: popHost,
      props: {
        index: 7,
        title: '기존 DSEP 환경의 추가 필요사항을 점검',
        deliverable: 'DSEP Gap & Resource Plan',
        owners: ['DSEP 인프라 담당자', '사내 IT·보안'],
        status: 'IN_PROGRESS',
      },
      attrs: { open: true },
    })
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    const popText = dom.window.document.body.textContent ?? ''
    check('the popover renders its title', popText.includes('기존 DSEP 환경의 추가 필요사항'))
    check(
      '…prefixed with the item index',
      popText.includes('7. 기존 DSEP 환경의 추가 필요사항'),
      popText.slice(0, 120),
    )
    check('it shows the owners', popText.includes('DSEP 인프라 담당자'))
    check('…and names two of them as 공동', popText.includes('(공동)'), popText.slice(0, 200))
    check('it shows the status label', popText.includes('진행중'))
    check('and the deliverable', popText.includes('DSEP Gap & Resource Plan'))
    check(
      'but no separate No. line — the index is only the title prefix',
      !popText.includes('No.'),
    )
    pop.unmount()
    popHost.remove()
  }

  section('M. MakerSettings — the fourth expose (plan.md 0.6-4)')
  {
    const settingsClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const settingsHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(settingsHost)
    const settings = mount(MakerSettings, {
      attachTo: settingsHost,
      props: { dataSource: settingsClient, height: '600px' },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }

    const settingsEl = settings.element as HTMLElement
    const settingsText = () => settingsEl.textContent ?? ''
    const checkboxes = () => settingsEl.querySelectorAll('[data-wp-maker-show]')

    check('root carries the wp-root style anchor', settingsEl.classList.contains('wp-root'))
    check('it announces itself with the host menu label', settingsText().includes('Integrated AI 참여 설비사 관리'))
    check('no back button — the host owns navigation now', settingsEl.querySelectorAll('[data-wp-settings-back]').length === 0)
    check('it lists every maker the resolver knows', checkboxes().length >= 4, checkboxes().length)
    check(
      'and distinguishes an explicit setting from the derived rule',
      [...settingsEl.querySelectorAll('[data-wp-maker-origin]')].some((el) => el.getAttribute('data-wp-maker-origin') === 'auto'),
    )
    check('no ag-grid was loaded — this screen has no grid', !settingsEl.querySelector('[data-wp-board-grid] .ag-root-wrapper'))
    check('nothing is dirty on arrival', (settings.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === false)

    /*
     * 카드 형태 (2026-08-09 개편) — 전체 현황과 같은 언어다 (`plan.md` §0.6-4).
     * 표 한 장이던 시절로 되돌아가면 여기서 깨진다.
     */
    const makerCards = () => settingsEl.querySelectorAll('[data-wp-maker-card]')
    check('each maker is a card, not a table row', makerCards().length >= 4, makerCards().length)
    check('…and every card can collapse', settingsEl.querySelectorAll('[data-wp-maker-toggle]').length === makerCards().length)

    /*
     * 접기 판정은 **그 카드 안에서** 센다. 픽스처의 설비사 넷 중 프로젝트를 가진 것은
     * 하나뿐이고 카드 순서는 이름순이라, 전체 행 수로 재면 프로젝트 0개짜리 카드를
     * 접고는 "아무 일도 안 일어났다" 며 실패한다 — 실제로 그렇게 한 번 틀렸다.
     */
    const populatedCard = [...makerCards()].find(
      (card) => card.querySelectorAll('[data-wp-project-row]').length > 0,
    ) as HTMLElement | undefined
    check('setup: some maker card has projects under it', !!populatedCard)
    const cardToggle = populatedCard!.querySelector('[data-wp-maker-toggle]') as HTMLElement
    const cardRows = () => populatedCard!.querySelectorAll('[data-wp-project-row]').length

    const expandedRows = cardRows()
    check('cards start expanded, so project rows are on screen', expandedRows >= 1, expandedRows)
    check('setup: the toggle says so', cardToggle?.getAttribute('aria-expanded') === 'true')
    cardToggle.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('collapsing hides that card’s projects', cardRows() === 0, cardRows())
    check('…and the toggle reports it', cardToggle.getAttribute('aria-expanded') === 'false')
    cardToggle.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('expanding brings them back', cardRows() === expandedRows, cardRows())

    /*
     * Flipping the maker switch makes it dirty, which is what a host route guard reads.
     *
     * It is an antd `Switch` now, not a `Checkbox` — fall-through attrs land on the outer
     * `<button role="switch">`, so the hook *is* the click target. (The old code reached for
     * an inner `<input>`, which a Switch does not have.)
     */
    const makerSwitch = checkboxes()[0] as HTMLElement
    check('setup: the maker control is a switch', makerSwitch?.getAttribute('role') === 'switch', makerSwitch?.tagName)
    makerSwitch.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('flipping a maker switch reports unsaved changes', (settings.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === true)
    const saveBtn = [...settingsEl.querySelectorAll('button')].find((b) => (b.textContent ?? '').trim() === '저장') as HTMLButtonElement
    check('and enables 저장', !!saveBtn && !saveBtn.disabled)
    saveBtn.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('saving clears the dirty flag', (settings.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === false)

    /*
     * 프로젝트 사용 여부 스위치.
     *
     * off 는 **전체 현황에서 감추기**이지 삭제가 아니다. 그래서 두 가지를 함께 본다:
     * 전체 현황에서 빠질 것, 그리고 이 화면에는 **여전히 남아 있을 것** — 남지 않으면
     * 다시 켤 방법이 없어져 스위치가 편도가 된다. antd Switch 는 fall-through 속성을
     * 바깥 `<button role="switch">` 에 실으므로 훅이 곧 클릭 대상이다.
     */
    const projectSwitches = () => [...settingsEl.querySelectorAll('[data-wp-project-active]')] as HTMLElement[]
    check('each maker lists its projects with an on/off switch', projectSwitches().length >= 1, projectSwitches().length)

    const firstSwitch = projectSwitches()[0]
    const switchedId = Number(firstSwitch?.getAttribute('data-wp-project-active'))
    check('setup: the switch names the project it belongs to', Number.isFinite(switchedId) && switchedId > 0, switchedId)
    check('setup: it starts on', firstSwitch?.getAttribute('aria-checked') !== 'false', firstSwitch?.getAttribute('aria-checked'))
    check(
      'setup: the project is in the overview to begin with',
      (await settingsClient.getProjectsOverview()).makers.some((m) =>
        m.projects.some((p) => p.id === switchedId),
      ),
    )

    firstSwitch.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('flipping it reports unsaved changes', (settings.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === true)

    const saveAgain = [...settingsEl.querySelectorAll('button')].find((b) => (b.textContent ?? '').trim() === '저장') as HTMLButtonElement
    saveAgain.click()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(10)
    }
    check('saving it clears the dirty flag too', (settings.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === false)
    check(
      'the switched-off project is gone from 전체 현황',
      !(await settingsClient.getProjectsOverview()).makers.some((m) =>
        m.projects.some((p) => p.id === switchedId),
      ),
    )
    const savedRows = (await settingsClient.listMakers()).makers
    check(
      '…but it is still listed here, off — otherwise it could never be turned back on',
      savedRows.some((m) => m.projects.some((p) => p.id === switchedId && !p.is_active)),
    )
    check(
      '…and the board itself survived — this hid a project, it did not delete one',
      (await settingsClient.getProject(switchedId)).items.length > 0,
    )
    check(
      'no 삭제 button is offered anywhere on this screen',
      ![...settingsEl.querySelectorAll('button')].some((b) => (b.textContent ?? '').includes('삭제')),
    )

    settings.unmount()
    check('unmount removes the whole subtree', settingsHost.children.length === 0)

    // readOnly: the table renders, the controls do not.
    const roSettingsHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(roSettingsHost)
    const roSettings = mount(MakerSettings, {
      attachTo: roSettingsHost,
      props: { dataSource: createMockApiClient({ makerId: 7, latencyMs: 0 }), readOnly: true, height: '600px' },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    const roSettingsEl = roSettings.element as HTMLElement
    check('readOnly still lists the makers', roSettingsEl.querySelectorAll('[data-wp-maker-show]').length >= 4)
    const roBoxes = [...roSettingsEl.querySelectorAll('[data-wp-maker-show]')] as HTMLElement[]
    check(
      'but every maker switch is disabled',
      roBoxes.length >= 4 && roBoxes.every((s) => s.hasAttribute('disabled')),
      roBoxes.map((s) => s.hasAttribute('disabled')),
    )
    const roSwitches = [...roSettingsEl.querySelectorAll('[data-wp-project-active]')] as HTMLElement[]
    check(
      'and every project switch is disabled too',
      roSwitches.length >= 1 && roSwitches.every((s) => s.hasAttribute('disabled')),
      roSwitches.map((s) => s.hasAttribute('disabled')),
    )
    check(
      'and 저장 is not offered',
      ![...roSettingsEl.querySelectorAll('button')].some((b) => (b.textContent ?? '').trim() === '저장'),
    )
    roSettings.unmount()
    roSettingsHost.remove()

    // 두 인스턴스 동시 마운트 — 상태가 섞이지 않는다.
    const twinA = dom.window.document.createElement('div')
    const twinB = dom.window.document.createElement('div')
    dom.window.document.body.append(twinA, twinB)
    const a = mount(MakerSettings, { attachTo: twinA, props: { dataSource: createMockApiClient({ makerId: 7, latencyMs: 0 }), height: '400px' } })
    const b = mount(MakerSettings, { attachTo: twinB, props: { dataSource: createMockApiClient({ makerId: 7, latencyMs: 0 }), height: '400px' } })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    // Switch 이므로 훅이 곧 클릭 대상이다 (안쪽 `<input>` 을 찾던 옛 코드는 null 을 집었다).
    const aHook = (a.element as HTMLElement).querySelectorAll('[data-wp-maker-show]')[0] as HTMLElement
    aHook.click()
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(10)
    }
    check('editing one instance leaves the other clean', (a.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === true && (b.vm as unknown as { hasUnsavedChanges(): boolean }).hasUnsavedChanges() === false)
    auditBorders(a.element as HTMLElement, 'MakerSettings')
    a.unmount()
    b.unmount()
    twinA.remove()
    twinB.remove()
    settingsHost.remove()
  }

  section('J. Phase 관리 팝업 — the table order is what the server renumbers from (plan.md 0.4)')
  {
    /*
     * Mounted directly rather than driven through a cell, for the same reason the cell
     * editors are: ag-grid's popup service needs real layout to open one. Everything below
     * the modal is the shipped path though — the store, the client, the mock server — so
     * "[적용] reordered the board" is an end-to-end claim, not a claim about a local array.
     */
    const { default: StructureManagerModal } = await import(
      '../components/StructureManagerModal.vue'
    )
    const { App: AntApp } = await import('ant-design-vue')
    const { BOARD_CONTEXT } = await import('../runtime/context')
    const { createMasterStore } = await import('../stores/master')
    const { createBoardStore } = await import('../stores/board')
    const { defineComponent, h, provide } = await import('vue')

    const popClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const popMaster = createMasterStore(popClient)
    const popBoard = createBoardStore(popClient, popMaster, {
      tier: 'project',
      makerId: () => 7,
      projectId: () => popClient.backend.listProjects(7)[0]!.id,
    })
    await popBoard.init()
    for (let i = 0; i < 30; i++) {
      await nextTick()
      await sleep(5)
    }

    const popHost = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(popHost)
    let closes = 0
    const popContext = {
      api: popClient,
      board: popBoard,
      master: popMaster,
      notify: { info() {}, success() {}, warn() {}, error() {} },
      structure: { open() {} },
      ownerPicker: { open() {} },
      makerId: 7,
      makerName: null,
      navigate: null,
      popupContainer: () => popHost,
    }
    const popup = mount(
      defineComponent({
        setup() {
          provide(BOARD_CONTEXT, popContext as never)
          return () =>
            h(AntApp, null, {
              default: () =>
                h(StructureManagerModal, {
                  request: { kind: 'phase' },
                  onClose: () => closes++,
                } as never),
            })
        },
      }),
      { attachTo: popHost },
    )
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(5)
    }

    const bodyRows = () => [...popHost.querySelectorAll('tbody tr')]
    const previews = () =>
      bodyRows().map((tr) => (tr.querySelectorAll('td')[1]?.textContent ?? '').trim())
    const names = () =>
      bodyRows().map((tr) => (tr.querySelector('input') as HTMLInputElement | null)?.value ?? '')
    const counts = () =>
      bodyRows().map((tr) => (tr.querySelectorAll('td')[3]?.textContent ?? '').trim())

    const boardPhaseOrder = () => {
      const seen: number[] = []
      for (const row of popBoard.items.value) {
        if (row.phase_id != null && !seen.includes(row.phase_id)) seen.push(row.phase_id)
      }
      return seen
    }
    const startOrder = boardPhaseOrder()

    check('it lists every phase of the board', bodyRows().length === 4, bodyRows().length)
    check(
      'numbered as the server will number them, from phase_start_no',
      previews().join(',') === 'Phase 0,Phase 1,Phase 2,Phase 3',
      previews(),
    )
    check(
      'in board order, with the names editable inline',
      names().every((n) => n.length > 0) && names().length === 4,
      names(),
    )
    check(
      'each row says how many board rows hang off it — the N in the delete warning',
      counts().reduce((sum, n) => sum + Number(n), 0) === 35,
      counts(),
    )

    const namesBefore = names()
    const downButton = (index: number) =>
      [...bodyRows()[index]!.querySelectorAll('button')].find(
        (b) => (b.textContent ?? '').trim() === '↓',
      ) as HTMLButtonElement

    downButton(0).click()
    await nextTick()
    check(
      'moving a row down swaps the two names…',
      names()[0] === namesBefore[1] && names()[1] === namesBefore[0],
      names(),
    )
    check(
      '…and the numbers stay with the POSITION, not the phase — that is the preview',
      previews().join(',') === 'Phase 0,Phase 1,Phase 2,Phase 3',
      previews(),
    )
    check('the board itself has not moved yet — [적용] is what sends it', boardPhaseOrder().join(',') === startOrder.join(','))

    const applyButton = [...popHost.querySelectorAll('button')].find(
      (b) => (b.textContent ?? '').trim() === '적용',
    ) as HTMLButtonElement
    check('the popup offers 적용 and 취소', !!applyButton && [...popHost.querySelectorAll('button')].some((b) => (b.textContent ?? '').trim() === '취소'))

    applyButton.click()
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }

    const endOrder = boardPhaseOrder()
    check(
      '[적용] reordered the real board through the store and the server',
      endOrder[0] === startOrder[1] && endOrder[1] === startOrder[0],
      [startOrder, endOrder],
    )
    check(
      'and the server renumbered from the new order',
      popBoard.items.value[0]!.phase_id === startOrder[1] && popBoard.items.value[0]!.phase_no === 0,
      [popBoard.items.value[0]!.phase_id, popBoard.items.value[0]!.phase_no],
    )
    check('rows are still 1..N', popBoard.items.value.every((r, i) => r.row_no === i + 1))
    check('no row was lost', popBoard.items.value.length === 35, popBoard.items.value.length)
    check('the popup closed itself on success', closes === 1, closes)
    check(
      'the scoped master data was refreshed with it, so the cell editors agree',
      popMaster.phases.value.length === 4 &&
        popMaster.activePhases.value[0]!.id === startOrder[1],
      popMaster.activePhases.value.map((p) => `${p.seq_no}:${p.id}`),
    )

    popup.unmount()
    popHost.remove()
  }

  section('G. Teardown — the vectors that actually leak')
  {
    /*
     * Asserting the DOM subtree disappears mostly tests Vue, not our teardown: Vue removes
     * the tree whether or not we cleaned up. What genuinely outlives an unmount is the
     * `beforeunload` listener, and it is not visible in the DOM — so it is observed directly,
     * with a positive control proving the fixture can see it at all.
     *
     * The interval instrumentation stays, **inverted**: 자동저장이 제거됐으므로 (`plan.md`
     * §0.5.8) 이제 확인할 것은 "타이머가 정리되는가" 가 아니라 "애초에 만들어지지 않는가" 다.
     * 그런 부정 단언은 계측이 고장 나도 통과하므로, 직접 만든 인터벌로 계측이 살아 있음을
     * 먼저 증명한다.
     */
    const listeners = new Map<string, number>()
    const realAdd = dom.window.addEventListener.bind(dom.window)
    const realRemove = dom.window.removeEventListener.bind(dom.window)
    dom.window.addEventListener = ((type: string, ...rest: unknown[]) => {
      listeners.set(type, (listeners.get(type) ?? 0) + 1)
      return (realAdd as unknown as (...a: unknown[]) => void)(type, ...rest)
    }) as never
    dom.window.removeEventListener = ((type: string, ...rest: unknown[]) => {
      listeners.set(type, (listeners.get(type) ?? 0) - 1)
      return (realRemove as unknown as (...a: unknown[]) => void)(type, ...rest)
    }) as never

    const liveIntervals = new Set<number>()
    // The component calls `window.setInterval`, which in jsdom is NOT the same function
    // object as `globalThis.setInterval` — patching only the latter silently observed
    // nothing, which is how the first version of this check reported a leak-free zero.
    const realSetInterval = dom.window.setInterval.bind(dom.window)
    const realClearInterval = dom.window.clearInterval.bind(dom.window)
    const patchedSet = ((fn: () => void, ms?: number) => {
      const id = (realSetInterval as unknown as (f: () => void, m?: number) => number)(fn, ms)
      liveIntervals.add(id)
      return id
    }) as never
    const patchedClear = ((id: number) => {
      liveIntervals.delete(id)
      ;(realClearInterval as unknown as (i: number) => void)(id)
    }) as never
    dom.window.setInterval = patchedSet
    dom.window.clearInterval = patchedClear
    g.setInterval = patchedSet
    g.clearInterval = patchedClear

    // Retire the board mounted at the top of this run *before* counting, so its teardown
    // does not show up as an unmatched removeEventListener.
    wrapper.unmount()
    await sleep(20)
    listeners.clear()
    liveIntervals.clear()

    const guardClient = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const guarded = mount(ProjectWorkspace, {
      attachTo: dom.window.document.getElementById('app')!,
      props: {
        makerId: 7,
        projectId: seedProjectId(guardClient),
        dataSource: guardClient,
        warnOnUnload: true,
      },
    })
    for (let i = 0; i < 40; i++) {
      await nextTick()
      await sleep(10)
    }
    // Positive control: the fixture can observe the registration in the first place.
    check(
      'mounting with warnOnUnload registers a beforeunload listener',
      (listeners.get('beforeunload') ?? 0) === 1,
      listeners.get('beforeunload'),
    )

    // 보드 화면을 실제로 띄우고 잠시 둔다 — 자동저장이 남아 있었다면 여기서 타이머가 걸렸다.
    await clickTab(guarded.element as HTMLElement, 'Work Package')
    for (let i = 0; i < 20; i++) {
      await nextTick()
      await sleep(5)
    }
    check(
      'the board offers no 자동저장 switch any more (plan.md 0.5.8)',
      ![...guarded.element.querySelectorAll('button')].some((b) => b.getAttribute('role') === 'switch'),
    )
    check(
      '…and the toolbar text no longer mentions it',
      !(guarded.element.textContent ?? '').includes('자동저장'),
    )
    check('opening the board starts NO periodic timer', liveIntervals.size === 0, liveIntervals.size)

    // POSITIVE CONTROL — 계측이 실제로 인터벌을 볼 수 있음을 증명한다. 이게 없으면 위의
    // "0개" 단언은 계측이 죽어 있어도 통과한다.
    const controlId = dom.window.setInterval(() => {}, 10_000)
    check('CONTROL — the fixture can see an interval when one exists', liveIntervals.size === 1, liveIntervals.size)
    dom.window.clearInterval(controlId)
    check('…and sees it cleared again', liveIntervals.size === 0, liveIntervals.size)

    guarded.unmount()
    await sleep(30)
    check(
      'unmount removes the beforeunload listener',
      (listeners.get('beforeunload') ?? 0) === 0,
      listeners.get('beforeunload'),
    )
    check('unmount leaves no periodic timer behind', liveIntervals.size === 0, liveIntervals.size)
    check('unmount removes the whole subtree', !dom.window.document.querySelector('.wp-root'))
    check('no ag-grid DOM left behind', !dom.window.document.querySelector('[data-wp-board-grid] .ag-root-wrapper'))

    dom.window.addEventListener = realAdd as never
    dom.window.removeEventListener = realRemove as never
    dom.window.setInterval = realSetInterval as never
    dom.window.clearInterval = realClearInterval as never
    g.setInterval = realSetInterval as never
    g.clearInterval = realClearInterval as never
  }

  auditBorders(root, 'MasterAdmin')

  section('G2. Two concurrent instances — fixtures that can tell them apart')
  {
    /*
     * The previous version mounted two boards that both had 35 rows and asserted both
     * showed 35. Module-scoped state would have made them show the *same* board — still 35
     * — so that check could never have failed. These two fixtures differ in row count and
     * in maker name, which is what makes bleed-through observable.
     */
    const clientA = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const clientB = createMockApiClient({ makerId: 9, latencyMs: 0 })

    const projectB = clientB.backend.listProjects(9)[0]!
    const scopeB = clientB.backend.projectScope(projectB.id)
    for (const row of clientB.backend.project(scopeB).slice(0, 3)) {
      clientB.backend.deleteItem(scopeB, row.id)
    }
    check(
      'the two fixtures are genuinely distinguishable',
      clientB.backend.project(scopeB).length === 32,
      clientB.backend.project(scopeB).length,
    )

    const a = mount(ProjectWorkspace, {
      attachTo: dom.window.document.getElementById('app')!,
      props: { makerId: 7, projectId: seedProjectId(clientA), makerName: '가나설비', dataSource: clientA, warnOnUnload: false },
    })
    const b = mount(ProjectWorkspace, {
      attachTo: dom.window.document.getElementById('app')!,
      props: { makerId: 9, projectId: seedProjectId(clientB, 9), makerName: '다라테크', dataSource: clientB, warnOnUnload: false },
    })
    for (let i = 0; i < 60; i++) {
      await nextTick()
      await sleep(10)
    }

    const aEl = a.element as HTMLElement
    const bEl = b.element as HTMLElement
    const aText = aEl.textContent ?? ''
    const bText = bEl.textContent ?? ''
    check('instance A shows its own 35 rows', totalRows(aEl) === 35, totalRows(aEl))
    check('instance B shows its own 32 rows', totalRows(bEl) === 32, totalRows(bEl))
    check('the counts differ, so shared state would be visible', totalRows(aEl) !== totalRows(bEl))
    check('instance A shows only its own maker', aText.includes('가나설비') && !aText.includes('다라테크'))
    check('instance B shows only its own maker', bText.includes('다라테크') && !bText.includes('가나설비'))

    // ── Negative control: what shared state would actually look like. ──
    // Two boards backed by one client is the observable signature of module-scoped state.
    // If the row-count assertion above cannot tell that apart from the real pair, it is not
    // establishing isolation — it is just counting to 35 twice.
    const shared = createMockApiClient({ makerId: 7, latencyMs: 0 })
    const c = mount(ProjectWorkspace, {
      attachTo: dom.window.document.getElementById('app')!,
      props: { makerId: 7, projectId: seedProjectId(shared), makerName: '동일소스1', dataSource: shared, warnOnUnload: false },
    })
    const d = mount(ProjectWorkspace, {
      attachTo: dom.window.document.getElementById('app')!,
      props: { makerId: 7, projectId: seedProjectId(shared), makerName: '동일소스2', dataSource: shared, warnOnUnload: false },
    })
    for (let i = 0; i < 60; i++) {
      await nextTick()
      await sleep(10)
    }
    check(
      'NEGATIVE CONTROL — boards sharing one backend report identical counts',
      totalRows(c.element as HTMLElement) === totalRows(d.element as HTMLElement),
      [totalRows(c.element as HTMLElement), totalRows(d.element as HTMLElement)],
    )
    check(
      '…so "counts differ" is a real signal, not an artefact of counting to 35 twice',
      totalRows(aEl) !== totalRows(bEl) &&
        totalRows(c.element as HTMLElement) === totalRows(d.element as HTMLElement),
    )
    c.unmount()
    d.unmount()

    a.unmount()
    b.unmount()
  }

  section('H. CSS containment — against the real shipped stylesheet')
  {
    /*
     * The previous version scanned `document.querySelectorAll('style')`, which in this
     * build holds only antd's cssinjs and ag-grid's runtime rules. **Our own CSS is emitted
     * to a separate file and never enters the document**, so that check could not fail no
     * matter what Tailwind was configured to do — switching preflight back on would not
     * have tripped it.
     *
     * This reads the actual built stylesheet off disk, checks it two ways, and then runs
     * both checks against a known-bad sheet to prove they are capable of failing.
     */
    const shipped = readFileSync(resolve(process.cwd(), 'dist-check/wp-board-remote.css'), 'utf8')
    check('the shipped stylesheet was found and is non-trivial', shipped.length > 1000, shipped.length)

    /*
     * preflight 가 꺼져 있다는 사실의 **비용**을 스타일시트 수준에서 못 박는다: 두께만 주는
     * `wp-border` 는 아무것도 그리지 않고, `wp-border-solid` 를 같이 줘야 그려진다. 이것이
     * 2026-08-08 진행전 셀을 투명하게 만든 원인이고, 색만 보던 단언은 그때 통과했다.
     *
     * 개별 요소가 아니라 두 클래스의 조합을 직접 재는 이유는, 이 성질이 우리가 켜고 끄는
     * 설정(preflight)의 직접적 결과이기 때문이다 — 누가 preflight 를 되켜면 여기서 잡힌다.
     */
    const styleProbe = dom.window.document.createElement('style')
    styleProbe.textContent = shipped
    dom.window.document.head.appendChild(styleProbe)

    const widthOnly = dom.window.document.createElement('div')
    widthOnly.className = 'wp-border'
    const withStyle = dom.window.document.createElement('div')
    withStyle.className = 'wp-border wp-border-solid'
    dom.window.document.body.append(widthOnly, withStyle)

    check(
      'wp-border ALONE draws nothing — preflight is off, so there is no default style',
      dom.window.getComputedStyle(widthOnly).borderStyle === 'none',
      dom.window.getComputedStyle(widthOnly).borderStyle,
    )
    check(
      '…and wp-border-solid is what makes it visible',
      dom.window.getComputedStyle(withStyle).borderStyle === 'solid' &&
        dom.window.getComputedStyle(withStyle).borderTopWidth === '1px',
      [
        dom.window.getComputedStyle(withStyle).borderStyle,
        dom.window.getComputedStyle(withStyle).borderTopWidth,
      ],
    )
    widthOnly.remove()
    withStyle.remove()
    styleProbe.remove()

    /** Selectors that would match something the host owns, outside our subtree. */
    const escapingSelectors = (css: string) =>
      css
        // Comments first: the unminified build keeps them, and one of ours contains a
        // literal `*, ::before, ::after { … }` as prose, which a naive split reads as a
        // rule and reports as a leak.
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/@[a-z-]+[^{]*\{/gi, '{')
        .split('}')
        .map((rule) => rule.split('{')[0] ?? '')
        .flatMap((group) => group.split(','))
        .map((sel) => sel.trim())
        .filter((sel) => sel.length > 0 && !/^\d+%$/.test(sel) && sel !== 'from' && sel !== 'to')
        // A selector is contained if it requires one of our classes. Class tokens are
        // read out and unescaped rather than substring-matched: Tailwind writes variants
        // as `.hover\:wp-bg-slate-50`, where the escaped colon means a naive search for
        // `.wp-` misses a perfectly namespaced selector.
        .filter((sel) => {
          const classes = [...sel.matchAll(/\.((?:[\w-]|\\.)+)/g)].map((m) =>
            m[1]!.replace(/\\(.)/g, '$1'),
          )
          return !classes.some((name) => name.startsWith('wp-') || name.includes(':wp-'))
        })

    const offenders = escapingSelectors(shipped)
    check('every selector in the shipped CSS is namespaced', offenders.length === 0, offenders.slice(0, 8))

    // Dynamic half: real host elements outside .wp-root, with the real stylesheet applied.
    const host = dom.window.document.createElement('div')
    host.innerHTML =
      '<h1 id="hh">t</h1><button id="hb">b</button><table id="ht"><tr><td>c</td></tr></table>'
    dom.window.document.body.appendChild(host)

    const styleOf = (id: string, prop: string) =>
      dom.window.getComputedStyle(dom.window.document.getElementById(id)!).getPropertyValue(prop)

    /*
     * These three properties, and not the obvious ones. jsdom reports `border-box` for a
     * button with no stylesheet at all, so a box-sizing assertion can never fail; and
     * `margin-top` merely reformats `0` to `0px` under preflight, so it "detects" the
     * change by string luck rather than by meaning. Each property below was checked to
     * move semantically between a bare document and a preflighted one — the same
     * "can this fixture fail?" question, asked of this fixture.
     */
    const probes: [string, string, string][] = [
      ['hh', 'font-size', 'h1 keeps its user-agent font-size'],
      ['hb', 'border-top-width', 'button keeps its user-agent border'],
      ['ht', 'border-collapse', 'table keeps its user-agent border-collapse'],
    ]
    // Baseline is captured BEFORE the stylesheet goes in. Capturing it afterwards — which
    // this check did at first — compares a corrupted document against itself, and every
    // per-probe assertion passes even with preflight switched back on.
    const baseline = probes.map(([id, prop]) => styleOf(id, prop))
    check(
      'baseline is the untouched UA default (fixture sanity)',
      baseline[0] === '2em' && baseline[1] === 'medium' && baseline[2] === 'separate',
      baseline,
    )

    const styleEl = dom.window.document.createElement('style')
    styleEl.textContent = shipped
    dom.window.document.head.appendChild(styleEl)

    for (const [i, probe] of probes.entries()) {
      const [id, prop, label] = probe
      check(`host ${label}`, styleOf(id, prop) === baseline[i], `${prop}=${styleOf(id, prop)} (was ${baseline[i]})`)
    }

    // ── Negative controls: prove both halves are capable of failing. ──
    const PREFLIGHT =
      '*,::before,::after{box-sizing:border-box}h1{margin:0;font-size:inherit}' +
      'button{background:none;border:0}table{border-collapse:collapse}'
    check(
      'NEGATIVE CONTROL — selector audit flags a preflight stylesheet',
      escapingSelectors(PREFLIGHT).length >= 4,
      escapingSelectors(PREFLIGHT),
    )

    const badStyle = dom.window.document.createElement('style')
    badStyle.textContent = PREFLIGHT
    dom.window.document.head.appendChild(badStyle)
    const moved = probes.filter(([id, prop], i) => styleOf(id, prop) !== baseline[i])
    check(
      'NEGATIVE CONTROL — every computed-style probe moves under preflight',
      moved.length === probes.length,
      { moved: moved.length, of: probes.length },
    )
    badStyle.remove()
    check(
      '…and the host returns to its defaults once the bad sheet is removed',
      probes.every(([id, prop], i) => styleOf(id, prop) === baseline[i]),
    )

    styleEl.remove()
    host.remove()
  }

  console.log(`\n${passed} passed, ${failed} failed`)
  report.push(`\n${passed} passed, ${failed} failed`)
  // Relative to the package root, not to the built bundle — the two live at different
  // depths and a URL-relative path escaped `frontend/` entirely.
  writeFileSync(resolve(process.cwd(), 'dom-check-report.txt'), report.join('\n'), 'utf8')

  // Exit explicitly. A leaked `setInterval` keeps Node's event loop alive forever, so
  // without this the suite *hangs* rather than reporting — which is exactly how the
  // teardown proof behaved the first time it was run against deliberately broken cleanup.
  // A gate that hangs on failure is barely better than one that cannot fail: the
  // assertions above are what report the leak, and this makes sure they get to.
  process.exit(failed > 0 ? 1 : 0)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
