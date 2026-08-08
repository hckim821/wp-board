import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'

/**
 * ag-grid v33 Theming API — the theme is a JS object handed to the grid, so there is no
 * `ag-grid.css` / `ag-theme-*.css` import. That matters here: a global stylesheet import
 * in a federated remote is exactly the kind of thing that leaks into the host.
 *
 * Community modules only. Row Grouping / Excel Export / Context Menu / Range Selection
 * are Enterprise and are not used anywhere in this package (`plan.md` §5.3).
 */
export const wpGridTheme = themeQuartz.withParams({
  fontFamily: 'inherit',
  fontSize: 13,
  headerFontWeight: 600,
  headerHeight: 38,
  rowHeight: 46,
  borderColor: '#E8E8E8',
  headerBackgroundColor: '#FAFAFA',
  headerTextColor: '#434343',
  oddRowBackgroundColor: 'transparent',
  rowHoverColor: 'rgba(0, 0, 0, 0.025)',
  selectedRowBackgroundColor: 'rgba(24, 144, 255, 0.08)',
  cellHorizontalPadding: 10,
  wrapperBorderRadius: 6,
})

let registered = false

/**
 * Registers the Community module set exactly once.
 *
 * Called from `onMounted`, never at import time: INTEGRATION.md §4/§5 forbid import-time
 * side effects, and the exposed component may be mounted and unmounted repeatedly.
 */
export function ensureAgGridModules(): void {
  if (registered) return
  ModuleRegistry.registerModules([AllCommunityModule])
  registered = true
}
