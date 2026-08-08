/**
 * Federation entry for `./ProjectsOverview` — 전체 현황 (`plan.md` §0.5-3).
 *
 * The host's third menu item. Read-only, maker-free, one row per active project. Takes no
 * `makerId` and owns no maker table; navigation into a project is the `onOpenProject`
 * callback, since routing belongs to the host.
 */
import ProjectsOverview from '../remote/ProjectsOverviewRemote.vue'

export default ProjectsOverview
export { ProjectsOverview }
export * from './shared'
