import type { WpItem } from '../api/types'

/**
 * Optimistic **display** renumbering — `plan.md` §2.2.
 *
 * Scope is deliberately narrow. This computes the things that are cosmetic and
 * self-correcting: `sort_order` / `row_no`, the derived phase and milestone numbers, and
 * which rows start or end a block (which is only used to decide where to draw a label).
 * It exists so the `No` column does not flash stale values for a round trip.
 *
 * It does **not** compute `can_create_phase` / `can_create_milestone`. Those are
 * authorization for §2.3, the server owns them, and a second implementation here would be
 * free to drift from the first. The optimistic pass carries whatever the server last sent
 * through untouched, and the UI treats those values as unknown while a mutation is in
 * flight (`BoardStore.flagsStale`) rather than guessing at them.
 *
 * Nor does it touch **membership**, and after `plan.md` §2.2 was corrected there is
 * nothing to touch: a drag no longer changes anyone's phase or milestone, so the
 * optimistic pass and the server's response cannot disagree about it. Membership changes
 * only through the §2.3 cell editors, which go to the server and come back.
 */

export interface RenumberContext {
  phaseStartNo: number
  phaseName: (phaseId: number) => string
  milestoneName: (milestoneId: number) => string
}

/** Assigns sort_order / phase_no / milestone_no and the display-only block flags. */
export function renumberItems(items: WpItem[], ctx: RenumberContext): WpItem[] {
  const phaseNo = new Map<number, number>()
  const milestoneNo = new Map<number, number>()
  const nextMilestone = new Map<number, number>()
  let nextPhase = ctx.phaseStartNo

  const numbered = items.map((item, index) => {
    let pNo: number | null = null
    if (item.phase_id != null) {
      if (!phaseNo.has(item.phase_id)) {
        phaseNo.set(item.phase_id, nextPhase++)
        nextMilestone.set(item.phase_id, 1)
      }
      pNo = phaseNo.get(item.phase_id)!
    }

    let mNo: number | null = null
    if (item.phase_id != null && item.milestone_id != null) {
      if (!milestoneNo.has(item.milestone_id)) {
        const next = nextMilestone.get(item.phase_id) ?? 1
        milestoneNo.set(item.milestone_id, next)
        nextMilestone.set(item.phase_id, next + 1)
      }
      mNo = milestoneNo.get(item.milestone_id)!
    }

    const phaseName = item.phase_id != null ? ctx.phaseName(item.phase_id) : null
    const milestoneName = item.milestone_id != null ? ctx.milestoneName(item.milestone_id) : null

    return {
      ...item,
      sort_order: index + 1,
      row_no: index + 1,
      phase_no: pNo,
      phase_name: phaseName,
      phase_display: pNo != null ? `Phase ${pNo}. ${phaseName ?? ''}`.trimEnd() : null,
      milestone_no: mNo,
      milestone_name: milestoneName,
      milestone_display:
        pNo != null && mNo != null ? `${pNo}.${mNo} ${milestoneName ?? ''}`.trimEnd() : null,
    } satisfies WpItem
  })

  return applyBlockFlags(numbered)
}

/**
 * Marks the first and last row of each phase / milestone block, **reading past
 * unassigned rows** (`plan.md` §0.2).
 *
 * An unassigned (gray) row is *transparent*: `P0 P0 [gray] P0` is one Phase 0 block with a
 * gray row parked inside it, not two blocks. That is the whole point of the gray row — it
 * can be dropped anywhere, including mid-block, without breaking anything.
 *
 * Transparency is per level. A row with a phase but no milestone is opaque to the phase
 * scan and transparent to the milestone scan, which is exactly what `create-phase` leaves
 * behind.
 *
 * Getting this wrong is not cosmetic. If the row *above* a mid-block gray row were marked
 * `is_phase_block_end`, `can_create_phase` would go true there, and creating a phase would
 * split the surrounding block into two runs of the same phase — a board the server refuses
 * to save. Contiguity, the block flags and the drag rule have to read the list the same
 * way or the UI offers actions the server rejects.
 */
export function applyBlockFlags(items: WpItem[]): WpItem[] {
  /** Nearest row in `direction` whose `key` is set, skipping transparent rows. */
  const seek = (from: number, step: -1 | 1, key: 'phase_id' | 'milestone_id') => {
    for (let i = from + step; i >= 0 && i < items.length; i += step) {
      if (items[i]![key] != null) return items[i]
    }
    return undefined
  }

  return items.map((item, i) => {
    const prevPhase = seek(i, -1, 'phase_id')
    const nextPhase = seek(i, 1, 'phase_id')
    const prevMs = seek(i, -1, 'milestone_id')
    const nextMs = seek(i, 1, 'milestone_id')

    /*
     * An unassigned row is still both edges of its own zero-width block: it starts and
     * ends nothing, and the renderers use these flags only to decide where to draw a
     * label, which a gray row does for itself.
     */
    const phaseStart = item.phase_id == null || prevPhase?.phase_id !== item.phase_id
    const phaseEnd = item.phase_id == null || nextPhase?.phase_id !== item.phase_id
    // Milestone blocks are judged *inside* the phase block, so a phase edge is also a
    // milestone edge.
    const msStart =
      item.milestone_id == null || phaseStart || prevMs?.milestone_id !== item.milestone_id
    const msEnd =
      item.milestone_id == null || phaseEnd || nextMs?.milestone_id !== item.milestone_id

    return {
      ...item,
      is_phase_block_start: phaseStart,
      is_phase_block_end: phaseEnd,
      is_milestone_block_start: msStart,
      is_milestone_block_end: msEnd,
    } satisfies WpItem
  })
}

/**
 * `can_create_phase` / `can_create_milestone` — §2.3 as corrected by §0.2.4.
 *
 * One rule covers both kinds of row: **creating here must leave the board contiguous.**
 *
 *  - assigned row → it must sit at an edge of its own block, or the block tears in two;
 *  - gray row → its nearest assigned neighbours above and below must differ, or it must
 *    have none on one side. Dropping a new phase into the middle of one block splits it.
 *
 * §2.3 originally said "an unassigned row is always a boundary, so it may always create".
 * That is half right — it *is* a boundary — but boundary-ness was only ever a proxy for
 * the contiguity question, and for a gray row parked mid-block the proxy gives the wrong
 * answer. This function asks the real question directly.
 *
 * Lives with the renumbering rules because `src/mock` — the server stand-in — is its only
 * caller. The shipped client consumes the flags off the row payload and has no copy.
 */
/**
 * Why `can_create_*` is false, in one sentence each.
 *
 * Shipped rather than mock-local on purpose: the cell editors show these in the disabled
 * button's tooltip *before* the request, and the server stand-in raises the same strings
 * in its 422. The client does not decide the rule — the flag off the row payload does —
 * but explaining the refusal differently than the server would is its own small lie.
 */
export const PHASE_CREATE_REFUSED =
  '여기서 새 Phase 를 만들면 기존 블록이 둘로 쪼개집니다. 블록의 경계 행이나, 서로 다른 Phase 사이의 회색 행에서 만드세요.'

export const MILESTONE_CREATE_REFUSED =
  '여기서 새 Milestone 을 만들면 기존 블록이 둘로 쪼개집니다. 블록의 경계 행이나, 서로 다른 Milestone 사이의 회색 행에서 만드세요.'

export function applyCreateFlags(items: WpItem[]): WpItem[] {
  const seek = (from: number, step: -1 | 1, key: 'phase_id' | 'milestone_id') => {
    for (let i = from + step; i >= 0 && i < items.length; i += step) {
      if (items[i]![key] != null) return items[i]
    }
    return undefined
  }

  return items.map((item, i) => {
    let canCreatePhase: boolean
    if (item.phase_id != null) {
      canCreatePhase = item.is_phase_block_start || item.is_phase_block_end
    } else {
      const above = seek(i, -1, 'phase_id')
      const below = seek(i, 1, 'phase_id')
      canCreatePhase = !above || !below || above.phase_id !== below.phase_id
    }

    let canCreateMilestone: boolean
    if (item.phase_id == null) {
      // Nothing to create a milestone *in* yet — assign the phase first.
      canCreateMilestone = false
    } else if (item.milestone_id != null) {
      canCreateMilestone = item.is_milestone_block_start || item.is_milestone_block_end
    } else {
      // Same question one level down, and confined to this row's phase block: a milestone
      // may not span two phases, so an assigned neighbour in a *different* phase counts as
      // no neighbour at all.
      const above = seek(i, -1, 'milestone_id')
      const below = seek(i, 1, 'milestone_id')
      const inPhase = (row: WpItem | undefined) =>
        row && row.phase_id === item.phase_id ? row : undefined
      const a = inPhase(above)
      const b = inPhase(below)
      canCreateMilestone = !a || !b || a.milestone_id !== b.milestone_id
    }

    return { ...item, can_create_phase: canCreatePhase, can_create_milestone: canCreateMilestone }
  })
}
