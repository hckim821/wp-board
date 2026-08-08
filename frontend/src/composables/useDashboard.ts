/**
 * Layout maths for the 대시보드 and 전체 현황 screens (`plan.md` §0.5).
 *
 * Pure functions over the ordinary item payload — no Vue, no DOM, no API. Two reasons:
 * `npm run verify` can then exercise the grouping directly (Phase 4개 초과, 회색 행, a
 * fragmented board) without mounting anything, and the same grouping serves both the
 * project dashboard and the overview minimap so the two cannot drift.
 *
 * Nothing here recomputes a rule the server owns. `phase_no` / `milestone_no` arrive already
 * derived from first-appearance order (§2.2); this only decides what goes in which column.
 */
import type { ItemStatus, OverviewItem, StatusCounts, WpItem } from '../api/types'
import { DASH_UNASSIGNED, dashPhaseColor } from '../theme/dashboard'

export interface DashMilestone {
  /** Stable `v-for` key. Milestone id, or `'none'` for the phase's unassigned bucket. */
  key: string
  milestoneId: number | null
  /** `0.1` — number only. Empty for the unassigned bucket. */
  numberLabel: string
  name: string
  items: WpItem[]
}

export interface DashPhase {
  key: string
  phaseId: number
  /** Display number (§2.2), which is also what the colour is keyed on. */
  phaseSeq: number | null
  name: string
  color: string
  milestones: DashMilestone[]
  itemCount: number
}

export interface DashboardLayout {
  phases: DashPhase[]
  /** 회색 행 — rendered as a trailing colourless column (§0.5-2). */
  unassigned: WpItem[]
  counts: StatusCounts
  total: number
}

export const EMPTY_COUNTS = (): StatusCounts => ({
  NOT_STARTED: 0,
  IN_PROGRESS: 0,
  DONE: 0,
  HOLD: 0,
  NA: 0,
})

export function countStatuses(items: readonly { status: ItemStatus }[]): StatusCounts {
  const counts = EMPTY_COUNTS()
  for (const item of items) {
    // A status the client does not know about must not vanish from the total, but it also
    // must not create a key nothing renders — so it is counted as 진행전.
    if (counts[item.status] === undefined) counts.NOT_STARTED++
    else counts[item.status]++
  }
  return counts
}

/**
 * Card text: `dash_label` → `deliverable` → the head of `title` (`plan.md` §0.5-1).
 *
 * The last fallback is truncated rather than clamped in CSS so that a row nobody has
 * labelled still occupies one card's worth of space instead of pushing its column open.
 */
export function dashboardText(
  item: Pick<WpItem, 'dash_label' | 'deliverable' | 'title'>,
  maxTitleChars = 28,
): string {
  const label = (item.dash_label ?? '').trim()
  if (label) return label
  const deliverable = (item.deliverable ?? '').trim()
  if (deliverable) return deliverable
  const title = (item.title ?? '').trim()
  if (!title) return ''
  return title.length > maxTitleChars ? `${title.slice(0, maxTitleChars)}…` : title
}

/**
 * Groups board rows into Phase columns → Milestone cells → item cards.
 *
 * Three decisions worth stating:
 *
 *  1. **Gray rows leave the grid entirely** and collect in {@link DashboardLayout.unassigned}.
 *     They are transparent to contiguity (§0.2.1), so on the board they sit inside whichever
 *     block surrounds them — but a dashboard column is a claim of membership, and a row that
 *     has none belongs in neither.
 *  2. **A phase is one column even if its rows are fragmented.** First appearance fixes the
 *     column order and later runs of the same phase merge into it. A fragmented board is a
 *     defect publish validation reports (V4/V5); rendering it as two identically-labelled
 *     columns would be a second, worse way of saying so.
 *  3. **A row with a phase but no milestone** gets a nameless bucket inside its phase, placed
 *     where it first appears. Legal on both tiers — only 발행 rejects it — so the dashboard
 *     has to show it rather than drop the row.
 */
export function buildDashboardLayout(items: readonly WpItem[]): DashboardLayout {
  const phases: DashPhase[] = []
  const byPhaseId = new Map<number, DashPhase>()
  const unassigned: WpItem[] = []

  for (const item of items) {
    if (item.phase_id == null) {
      unassigned.push(item)
      continue
    }

    let phase = byPhaseId.get(item.phase_id)
    if (!phase) {
      phase = {
        key: `p${item.phase_id}`,
        phaseId: item.phase_id,
        phaseSeq: item.phase_no,
        name: item.phase_name ?? '',
        color: dashPhaseColor(item.phase_no) ?? DASH_UNASSIGNED,
        milestones: [],
        itemCount: 0,
      }
      byPhaseId.set(item.phase_id, phase)
      phases.push(phase)
    }

    const key = item.milestone_id == null ? 'none' : String(item.milestone_id)
    let milestone = phase.milestones.find((m) => m.key === key)
    if (!milestone) {
      milestone = {
        key,
        milestoneId: item.milestone_id,
        numberLabel:
          item.phase_no != null && item.milestone_no != null
            ? `${item.phase_no}.${item.milestone_no}`
            : '',
        name: item.milestone_id == null ? '미지정' : (item.milestone_name ?? ''),
        items: [],
      }
      phase.milestones.push(milestone)
    }
    milestone.items.push(item)
    phase.itemCount++
  }

  return {
    phases,
    unassigned,
    counts: countStatuses(items),
    total: items.length,
  }
}

/** One milestone's worth of cells inside a phase band. Label shows on hover only (§0.5-3). */
export interface OverviewMilestoneGroup {
  key: string
  milestoneSeq: number | null
  /** `0.1`. Empty when the milestone is unset — legal on a live project. */
  label: string
  items: OverviewItem[]
}

/** One `Phase N` band of the mini dashboard. */
export interface OverviewPhaseGroup {
  key: string
  phaseSeq: number | null
  /** `Phase 0`, or `미배정` for the trailing colourless band. */
  label: string
  /** Null for 미배정 — the caller draws a colourless band rather than a grey phase. */
  color: string | null
  milestones: OverviewMilestoneGroup[]
  itemCount: number
}

/**
 * Groups one project's items into the mini dashboard of §0.5-3 (revised 2026-08-08).
 *
 * **This used to band by contiguous runs, and that is deliberately reversed.** While the
 * bands were unlabelled, runs were the honest rendering: the strip was a picture of
 * `sort_order`, and merging a fragmented phase would have moved cells away from where they
 * actually sat. The revision puts a visible `Phase N` label on every band, and two bands
 * carrying the same label is not a faithful picture — it is a confusing one. So this now
 * groups by first appearance, exactly like {@link buildDashboardLayout}, and the two screens
 * read the same way. A fragmented board is still a defect, and publish validation is still
 * where it gets reported.
 *
 * 미배정 is forced last rather than left where it fell, for the same reason it is a trailing
 * column on the full dashboard: it is not a phase and does not belong in the phase sequence.
 */
export function buildOverviewGroups(items: readonly OverviewItem[]): OverviewPhaseGroup[] {
  const groups: OverviewPhaseGroup[] = []
  const byPhase = new Map<number | 'none', OverviewPhaseGroup>()

  for (const item of items) {
    const phaseKey = item.phase_seq ?? 'none'
    let group = byPhase.get(phaseKey)
    if (!group) {
      group = {
        key: `p${phaseKey}`,
        phaseSeq: item.phase_seq,
        label: item.phase_seq == null ? '미배정' : `Phase ${item.phase_seq}`,
        color: dashPhaseColor(item.phase_seq),
        milestones: [],
        itemCount: 0,
      }
      byPhase.set(phaseKey, group)
      groups.push(group)
    }

    const msKey = item.milestone_seq == null ? 'none' : String(item.milestone_seq)
    let milestone = group.milestones.find((m) => m.key === msKey)
    if (!milestone) {
      milestone = {
        key: msKey,
        milestoneSeq: item.milestone_seq,
        label:
          item.phase_seq != null && item.milestone_seq != null
            ? `${item.phase_seq}.${item.milestone_seq}`
            : '',
        items: [],
      }
      group.milestones.push(milestone)
    }
    milestone.items.push(item)
    group.itemCount++
  }

  // 미배정 to the back. `phaseSeq` is the display number, so everything else is already in
  // the order first appearance gave it.
  return [
    ...groups.filter((g) => g.phaseSeq != null),
    ...groups.filter((g) => g.phaseSeq == null),
  ]
}

/*
 * `groupProjectsByMaker()` / `makerLabel()` used to live here.
 *
 * They are gone rather than deprecated: as of `plan.md` §0.6 the **server** groups the
 * overview by maker and applies the display rule, and the response arrives already shaped as
 * `{ makers: [{ maker_id, name, projects }] }`. Leaving a client-side grouper exported would
 * keep a second, quietly divergent copy of a rule that now has one home — and would still be
 * unable to show a maker that has no projects yet, which is the case §0.6 exists to handle.
 *
 * The `설비사 #<id>` fallback survives as a two-line expression at each of its three call
 * sites; it is not a rule, just a label.
 */
