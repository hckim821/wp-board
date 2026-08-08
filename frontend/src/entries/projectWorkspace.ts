/**
 * Federation entry for `./ProjectWorkspace` — 설비사 프로젝트 (`plan.md` §0.1).
 *
 * Project list, create-from-published-format, and the board with no version UI. Requires a
 * `makerId`; owns no maker table and no maker API.
 */
import ProjectWorkspace from '../remote/ProjectWorkspaceRemote.vue'

export default ProjectWorkspace
export { ProjectWorkspace }
export * from './shared'
