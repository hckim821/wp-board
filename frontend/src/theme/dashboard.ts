/**
 * Visual vocabulary of the 대시보드 / 전체 현황 screens (`plan.md` §0.5).
 *
 * `docs/dashboard.jpg` is the source of truth, and §0.5 pins the exact hex values, so they
 * are written out here rather than derived from `theme/palette.ts`. The two palettes are
 * close but not identical on purpose: `palette.ts` tints **grid rows**, where a saturated
 * band behind 35 lines of text is unreadable, while these are **headers and cards**, where
 * the deck's saturated colours are the whole point. Sharing one table would force one of the
 * two to compromise.
 *
 * Plain objects with literal colours, never Tailwind classes: the card background is chosen
 * at runtime from a status, and a `wp-bg-[…]` string assembled in JS is not something
 * Tailwind's content scanner can see, so the class would simply not exist in the stylesheet.
 */
import type { ItemStatus, OwnerRef } from '../api/types'

/** Phase 헤더 팔레트, §0.5. Cycles once a board has more phases than the deck had. */
export const DASH_PHASE_COLORS = ['#8f7cc3', '#40539b', '#337fb9', '#15958a'] as const

/** Bands a phase by its **display** number, so the colour survives a renumber. */
export function dashPhaseColor(phaseSeq: number | null | undefined): string | null {
  if (phaseSeq == null || phaseSeq < 0) return null
  return DASH_PHASE_COLORS[phaseSeq % DASH_PHASE_COLORS.length]!
}

/** 미배정 — a colourless band rather than a sixth colour (§0.5). */
export const DASH_UNASSIGNED = '#cbd5e1'

export interface StatusStyle {
  bg: string
  border: string
  text: string
}

/**
 * 상태 팔레트 — **`plan.md` §0.5 의 표가 정본**이고, 상태색이 나오는 곳은 전부 여기를 쓴다
 * (카드·미니맵 셀·범례·팝오버·그리드 상태 칩). 백엔드 PPT 상수도 같은 값을 복제한다.
 *
 * 2026-08-08 사용자 결정으로 세 가지가 바뀌었다:
 *
 *  - **진행중이 초록**이 됐다. 종전 amber 는 "주의" 로 읽혔는데, 주의가 필요한 상태는 보류다.
 *  - **완료가 짙은 회색**이다. 완료는 더 볼 일이 없는 항목이라 시선을 끌 이유가 없다 — 종전
 *    emerald 는 진행중보다 눈에 띄어 순서가 거꾸로였다.
 *  - **NA 는 짙은 배경 + 밝은 글자**로 '차단됨' 을 표현하고, 종전의 `opacity: 0.6` 흐림은
 *    없앴다. 흐림은 요소 전체를 반투명하게 만들어 좌측 주관 바와 테두리까지 같이 죽였고,
 *    무엇보다 "비활성" 과 "해당 없음" 이 같은 모양이 됐다.
 *
 * 진행전은 흰 배경에 **slate-400** 테두리다. 나머지는 채움색이 상태를 말하지만 진행전은
 * 윤곽선밖에 없어서, 15px 미니맵 셀에서 옅은 테두리는 그냥 사라진다 (§0.5-3).
 */
export const DASH_STATUS_STYLE: Record<ItemStatus, StatusStyle> = {
  NOT_STARTED: { bg: '#ffffff', border: '#94a3b8', text: '#334155' },
  IN_PROGRESS: { bg: '#d1fae5', border: '#34d399', text: '#065f46' },
  DONE: { bg: '#cbd5e1', border: '#94a3b8', text: '#1e293b' },
  HOLD: { bg: '#fee2e2', border: '#fca5a5', text: '#991b1b' },
  NA: { bg: '#334155', border: '#1e293b', text: '#cbd5e1' },
}

/** 주관 (카드 좌측 세로 바). Keys are for the legend; values are §0.5's hexes. */
export const OWNER_KINDS = [
  { key: 'INTERNAL_DEV', label: '사내 개발부서', color: '#337fb9' },
  { key: 'DSEP', label: 'DSEP 인프라 담당자', color: '#202d72' },
  { key: 'MAKER', label: '설비사', color: '#15958a' },
  { key: 'JOINT', label: '공동', color: '#f4a72d' },
  { key: 'NONE', label: '미지정', color: '#cbd5e1' },
] as const

export type OwnerKind = (typeof OWNER_KINDS)[number]['key']

const OWNER_COLOR: Record<OwnerKind, string> = Object.fromEntries(
  OWNER_KINDS.map((k) => [k.key, k.color]),
) as Record<OwnerKind, string>

/**
 * Which 주관 a row belongs to, from its Owner list.
 *
 * Two owners or more is 공동 outright — that is a structural fact, not a guess. A *single*
 * owner is classified by a name heuristic, carried over from the previous iteration's
 * `ownerStyle`, because Owner is free-form scoped master data with no type column: the same
 * board can hold '설비사' and '설비사 PM' and nothing distinguishes them but the string.
 *
 * The heuristic is display-only. Nothing is written back from it and no rule depends on it,
 * so a miss costs a wrong bar colour and nothing else.
 */
export function ownerKind(owners: readonly OwnerRef[] | null | undefined): OwnerKind {
  return ownerKindFromNames((owners ?? []).map((o) => o.name))
}

/**
 * Same rule over bare names.
 *
 * The overview payload carries owner **names** and no ids — its projects each own a separate
 * copy of the owner table (`plan.md` §0.1), so an id would mean nothing across them. This is
 * the primitive and {@link ownerKind} adapts to it, rather than two copies of the heuristic.
 */
export function ownerKindFromNames(names: readonly (string | null | undefined)[]): OwnerKind {
  const list = names.filter((n): n is string => !!n)
  if (list.length === 0) return 'NONE'
  if (list.length > 1) return 'JOINT'
  const name = list[0]!
  if (name.includes('공동') || name.includes('+')) return 'JOINT'
  if (name.includes('DSEP')) return 'DSEP'
  if (name.includes('설비사')) return 'MAKER'
  return 'INTERNAL_DEV'
}

export const ownerColor = (owners: readonly OwnerRef[] | null | undefined): string =>
  OWNER_COLOR[ownerKind(owners)]

/**
 * 미지정 주관 slate. Also the fixed bar colour of the **상태** legend swatches, so that
 * group varies its background and nothing else (§0.5 범례 개정).
 */
export const UNASSIGNED_OWNER_COLOR = OWNER_COLOR.NONE

/** Legend order for the status swatches — 진행전 · 진행중 · 완료 · 보류 · 해당없음. */
export const DASH_STATUS_ORDER: ItemStatus[] = [
  'NOT_STARTED',
  'IN_PROGRESS',
  'DONE',
  'HOLD',
  'NA',
]
