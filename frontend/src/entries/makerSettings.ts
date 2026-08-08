/**
 * Federation entry for `./MakerSettings` — Integrated AI 참여 설비사 관리
 * (`plan.md` §0.6-4).
 *
 * The host's fourth menu item, and an admin screen in its own right: which 설비사 appear on
 * the 전체 현황. Takes no `makerId` and owns no maker table — it edits our own
 * `wp_maker_settings`, keyed by an id this module never dereferences.
 */
import MakerSettings from '../remote/MakerSettingsRemote.vue'

export default MakerSettings
export { MakerSettings }
export * from './shared'
