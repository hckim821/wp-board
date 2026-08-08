/**
 * Phase colour system, lifted from `docs/dashboard.jpg` (PROJECT BOARD · STATUS MAP).
 *
 * ag-grid Community has no Row Grouping, so Phase/Milestone blocks are conveyed
 * purely visually: a saturated accent bar on the block's left edge plus a very light
 * row tint. Colours cycle once a board has more phases than the source deck had.
 */
export interface PhaseColor {
  /** Saturated colour — left bar, block label, chips. */
  accent: string
  /** Very light row background tint. */
  tint: string
  /** Slightly stronger tint used for the block's first row. */
  tintStrong: string
  /** Readable text colour on `tint`. */
  text: string
}

export const PHASE_COLORS: PhaseColor[] = [
  // Phase 0 — lavender
  { accent: '#8B7BC0', tint: '#F6F3FB', tintStrong: '#EDE7F7', text: '#5B4B8A' },
  // Phase 1 — deep navy
  { accent: '#3D4A8C', tint: '#F1F3FA', tintStrong: '#E4E8F5', text: '#2E3A73' },
  // Phase 2 — blue
  { accent: '#3B82C4', tint: '#F0F6FC', tintStrong: '#E0EDF8', text: '#25638F' },
  // Phase 3 — teal
  { accent: '#17A085', tint: '#EFF9F6', tintStrong: '#DDF1EB', text: '#12775F' },
  // overflow palette
  { accent: '#E8A33D', tint: '#FDF7EC', tintStrong: '#FAEDD6', text: '#9A6811' },
  { accent: '#C2557A', tint: '#FCF1F5', tintStrong: '#F7E1E9', text: '#8E3757' },
]

/** Colour for a phase, keyed by its *display number* so it stays stable while dragging. */
export function phaseColor(phaseNo: number | null | undefined): PhaseColor {
  if (phaseNo == null || phaseNo < 0) return UNASSIGNED_COLOR
  return PHASE_COLORS[phaseNo % PHASE_COLORS.length]!
}

/** Rows with no phase yet — legal in a DRAFT, flagged only at publish time. */
export const UNASSIGNED_COLOR: PhaseColor = {
  accent: '#BFBFBF',
  tint: '#FAFAFA',
  tintStrong: '#F0F0F0',
  text: '#8C8C8C',
}

/*
 * `STATUS_COLORS` used to live here, with its own hexes for the grid's status chip.
 *
 * It is gone, and that is the point: `plan.md` §0.5 now says one table governs **every**
 * place a status colour appears, and two tables that must agree are exactly how they come to
 * disagree — this pair already had five different values for the same five statuses. The
 * grid chip reads `DASH_STATUS_STYLE` from `theme/dashboard.ts` directly.
 *
 * `PHASE_COLORS` above stays here, because it is a genuinely different job: tinting 35 rows
 * of grid text, where the dashboard's saturated header colours would be unreadable.
 */
