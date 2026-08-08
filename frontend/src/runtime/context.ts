import { inject, type InjectionKey } from 'vue'
import type { WpApiClient } from '../api/client'
import type { BoardStore } from '../stores/board'
import type { MasterStore } from '../stores/master'

/** Toast/notification surface, taken from ant-design-vue's `App.useApp()` at the root. */
export interface Notifier {
  info(message: string): void
  success(message: string): void
  warn(message: string): void
  error(message: string, description?: string): void
}

/**
 * A request to open the Phase/Milestone 관리 팝업 (`plan.md` §0.4).
 *
 * The popup is a single instance owned by the shell rather than something each cell editor
 * renders: an ag-grid popup editor is torn down the moment the cell stops editing, and a
 * modal mounted inside one would vanish with it.
 */
export interface StructureManagerRequest {
  kind: 'phase' | 'milestone'
  /** Milestone popup only — whose milestones are listed. */
  phaseId?: number | null
  /**
   * The 회색 행 that opened this from its Phase/Milestone cell. The popup starts with one
   * new row already added, and that anchor becomes its first board row — which is what makes
   * "a Phase with no rows" impossible (§0.4).
   */
  anchorItemId?: number | null
}

export interface StructureManager {
  open(request: StructureManagerRequest): void
}

/** A request to open the Owner 선택·관리 팝업 from a board cell (`plan.md` §0.5.9). */
export interface OwnerPickerRequest {
  /** The row whose owners are being chosen. */
  itemId: number
}

export interface OwnerPicker {
  open(request: OwnerPickerRequest): void
}

/** A request to open the 관련 문서 선택·관리 팝업 from a board cell (`plan.md` §0.5.10). */
export interface DocumentPickerRequest {
  itemId: number
}

export interface DocumentPicker {
  open(request: DocumentPickerRequest): void
}

export interface BoardContext {
  api: WpApiClient
  board: BoardStore
  master: MasterStore
  notify: Notifier
  /** Opens the Phase/Milestone 관리 팝업 (`plan.md` §0.4). */
  structure: StructureManager
  /**
   * Opens the Owner 선택·관리 팝업 (`plan.md` §0.5.9).
   *
   * Hosted at the shell for the same reason `structure` is: an ag-grid popup editor is torn
   * down the instant editing stops, taking any modal rendered inside it along.
   */
  ownerPicker: OwnerPicker
  /** Opens the 관련 문서 선택·관리 팝업 (`plan.md` §0.5.10). Same hosting rule as the others. */
  documentPicker: DocumentPicker
  /**
   * Opaque to this module — only ever passed through to the API (INTEGRATION.md §2.4).
   *
   * **Null on the template tier**, where there is no maker at all (`plan.md` §0.1). Not a
   * placeholder id: a template belongs to nobody, and inventing a `0` here would be the
   * kind of fake value that later reads as real.
   */
  makerId: number | string | null
  makerName: string | null
  /** Host-owned navigation. There is no `vue-router` dependency anywhere in this package. */
  navigate: ((target: string, params?: Record<string, unknown>) => void) | null
  /** The element antd popups are portalled into, so they stay inside our styled subtree. */
  popupContainer: () => HTMLElement
}

export const BOARD_CONTEXT: InjectionKey<BoardContext> = Symbol('wp-board-context')

export function useBoardContext(): BoardContext {
  const context = inject(BOARD_CONTEXT, null)
  if (!context) {
    throw new Error('[wp-board] 컴포넌트가 MasterAdmin / ProjectWorkspace 외부에서 사용되었습니다.')
  }
  return context
}
