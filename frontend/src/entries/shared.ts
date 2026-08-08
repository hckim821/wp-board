/**
 * Everything both exposed modules publish besides the component itself.
 *
 * Re-exported from each entry rather than from a third shared expose: a host that mounts
 * only `ProjectWorkspace` should not have to load a second remote module to get
 * `configure()` or the wire types.
 */
export { configure, resetConfiguration } from '../runtime/config'
export type { WpRuntimeConfig } from '../runtime/config'

export type { WpApiClient, DeleteResult } from '../api/client'
export { createHttpApiClient, itemsBase, masterBase } from '../api/client'

export type {
  BoardScope,
  DocumentRef,
  ProjectDocument,
  TemplateDocument,
  ItemStatus,
  MasterScope,
  OverviewItem,
  OwnerRef,
  ProjectCreatePayload,
  ProjectDetail,
  ProjectOverview,
  ProjectsOverviewResponse,
  StatusCounts,
  ValidationIssue,
  ValidationResult,
  VersionStatus,
  WpItem,
  WpMilestone,
  WpOwner,
  WpPhase,
  WpProject,
  WpTemplate,
  WpVersion,
} from '../api/types'
