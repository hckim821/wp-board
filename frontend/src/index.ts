/**
 * Convenience barrel for local development and for hosts that consume this package
 * directly rather than over Module Federation.
 *
 * The **federated** surface is two separate entries — `src/entries/masterAdmin.ts` and
 * `src/entries/projectWorkspace.ts` — because a host mounting only one of the two screens
 * should not pull in the other (INTEGRATION.md §5). This file is not exposed.
 */
export { default as MasterAdmin, MasterAdmin as MasterAdminComponent } from './entries/masterAdmin'
export {
  default as ProjectWorkspace,
  ProjectWorkspace as ProjectWorkspaceComponent,
} from './entries/projectWorkspace'
export {
  default as ProjectsOverview,
  ProjectsOverview as ProjectsOverviewComponent,
} from './entries/projectsOverview'
export {
  default as MakerSettings,
  MakerSettings as MakerSettingsComponent,
} from './entries/makerSettings'
export * from './entries/shared'
