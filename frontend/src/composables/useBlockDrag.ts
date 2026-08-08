import type { WpItem } from '../api/types'

/**
 * Where a row may be dropped — `plan.md` §2.2 as amended by §0.2.
 *
 * The rule the user sees: **a row carries its membership and only its position changes.**
 * An assigned row may only be reordered inside the contiguous run of rows sharing its
 * `phase_id` and `milestone_id`; membership changes go through the Phase/Milestone cell
 * editors. An **unassigned (gray) row may be dropped anywhere** — it has no block to leave,
 * and it is transparent to contiguity, so no arrangement of gray rows can produce an
 * invalid board. That freedom is the mechanism for "insert between two Phases": add a gray
 * row, drag it to the seam, create the Phase there (§0.2.5).
 *
 * Why the constraint is not simply the server's job: the server still owns contiguity and
 * still answers 422 for a reorder that would fragment a block. What it cannot do is tell a
 * *reordering* intent from a *reclassification* one — a cross-block drag that happens to
 * land contiguously (dragging the whole of Phase 0's single row below Phase 1, say) is a
 * perfectly legal board, so the server accepts it and the user's Phase numbers silently
 * change. That judgement only exists where the gesture does, so it lives here, in front of
 * the request, where it can also explain itself.
 */

/** Shown when a drag is refused. Names the path that does work, rather than only refusing. */
export const BLOCK_DRAG_REFUSED =
  '같은 Phase·Milestone 안에서만 순서를 바꿀 수 있습니다. 다른 Phase 로 옮기려면 Phase 셀에서 변경하세요.'

/** Shown on the (handle-less) drag cell of a row that has nowhere legal to go. */
export const BLOCK_DRAG_SOLE_ROW =
  '이 행은 자기 Phase·Milestone 블록에 혼자 있어 이동할 수 없습니다. 소속은 Phase/Milestone 셀에서 변경하세요.'

type Level = 'phase_id' | 'milestone_id'

const LEVELS: readonly Level[] = ['phase_id', 'milestone_id']

/**
 * Is `orderedIds` a permutation of `items` that never moves a row out of its own block?
 *
 * Checked one level at a time, and **only over the rows that are assigned at that level**:
 * drop the nulls, then read down the before and after lists together — every remaining
 * slot must still hold the same id it held before.
 *
 * Three things fall out of that single test, which is why it is written this way rather
 * than as three rules:
 *
 *  - a fully gray row vanishes from both scans, so it may be dropped anywhere (§0.2.2);
 *  - a row with a phase but no milestone stays in the phase scan and vanishes from the
 *    milestone scan, so it is free *within its phase block* and pinned to that phase —
 *    which is exactly what it means for a milestone to be unassigned;
 *  - a fully assigned row is pinned by both scans, i.e. to its Phase·Milestone block.
 *
 * It also needs no opinion about which row the user grabbed — a fact this client has
 * repeatedly been wrong about.
 *
 * **Contiguity is a precondition, not a bonus.** Hand this a board where one phase already
 * appears in two runs and it will allow a swap between them, because two runs of the same
 * phase are indistinguishable by membership alone. Such a board cannot be produced through
 * this UI and the server refuses to persist one, but the exhaustive pass in `verify.ts`
 * counts those cases rather than hiding them: the guarantee here is conditional and the
 * suite says so out loud.
 */
export function isWithinBlockOrder(
  items: readonly WpItem[],
  orderedIds: readonly number[],
): boolean {
  if (orderedIds.length !== items.length) return false
  // A list that is not a permutation cannot be a within-block reorder either. ag-grid
  // never produces one, but the verdict below would read `undefined` as a mismatch only by
  // luck, and "refused for the right reason" is cheaper than reasoning about that.
  if (new Set(orderedIds).size !== orderedIds.length) return false

  const byId = new Map(items.map((row) => [row.id, row]))
  const after = orderedIds.map((id) => byId.get(id))
  if (after.some((row) => !row)) return false

  return LEVELS.every((level) => {
    const before = items.filter((row) => row[level] != null)
    const moved = (after as WpItem[]).filter((row) => row[level] != null)
    // Same rows either way, so the lengths always match; compared positionally.
    return before.every((row, index) => row[level] === moved[index]![level])
  })
}

/**
 * Can this row be dragged at all?
 *
 * Answered by *asking the drop rule* — would swapping with the row above, or the row
 * below, be allowed? — rather than by a second description of what a block is. The handle
 * therefore cannot disagree with the refusal: a row gets one exactly when at least one
 * move exists that {@link isWithinBlockOrder} would accept.
 *
 * A gray row always qualifies (on a board with more than one row); an assigned row
 * qualifies when it has a block neighbour, or a gray neighbour it can slide past.
 */
export function canDragRow(items: readonly WpItem[], row: WpItem | null | undefined): boolean {
  if (!row) return false
  const index = items.findIndex((r) => r.id === row.id)
  if (index < 0) return false

  const ids = items.map((r) => r.id)
  const swapWith = (other: number) => {
    const next = [...ids]
    next[index] = ids[other]!
    next[other] = ids[index]!
    return isWithinBlockOrder(items, next)
  }

  return (index > 0 && swapWith(index - 1)) || (index < items.length - 1 && swapWith(index + 1))
}
