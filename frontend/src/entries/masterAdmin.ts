/**
 * Federation entry for `./MasterAdmin` — 기준 데이터 관리 (`plan.md` §0.1).
 *
 * Central, maker-free: WP 템플릿 편집 with the full version flow, plus the global document
 * master. Anything not re-exported here is internal — in particular `src/dev` and
 * `src/mock`, which are dev-only and unreachable from this entry.
 */
import MasterAdmin from '../remote/MasterAdminRemote.vue'

export default MasterAdmin
export { MasterAdmin }
export * from './shared'
