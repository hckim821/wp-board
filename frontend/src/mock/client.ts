import { unwrapValidationFailure, type DeleteResult, type WpApiClient } from '../api/client'
import { MockBackend } from './engine'

/**
 * `WpApiClient` backed by {@link MockBackend}. DEV ONLY.
 *
 * Injected into the exposed components through their `dataSource` prop by `src/dev`, which
 * is also the escape hatch a host can use to front them with its own transport.
 */
export interface MockClientOptions {
  /** The maker whose projects this client can see. Templates are central and maker-free. */
  makerId?: number
  /** Artificial latency, so optimistic rendering and pending states are actually visible. */
  latencyMs?: number
}

export function createMockApiClient(options: MockClientOptions = {}): WpApiClient & {
  backend: MockBackend
} {
  const backend = new MockBackend(options.makerId ?? 1)
  const latency = options.latencyMs ?? 140

  const delay = <T>(produce: () => T): Promise<T> =>
    new Promise((resolve, reject) => {
      setTimeout(() => {
        try {
          resolve(produce())
        } catch (error) {
          reject(error)
        }
      }, latency)
    })

  return {
    backend,

    listTemplates: () => delay(() => backend.listTemplates()),
    createTemplate: (body) => delay(() => backend.upsertTemplate(body)),
    updateTemplate: (id, body) => delay(() => backend.upsertTemplate(body, id)),
    listVersions: (templateId) => delay(() => backend.listVersions(templateId)),
    getVersion: (vid) => delay(() => backend.getVersion(vid)),

    createDraft: (templateId) => delay(() => backend.deepCopyToDraft(templateId)),
    discardDraft: (vid) => delay(() => backend.discardDraft(vid)),
    saveVersionItems: (vid, payload) =>
      delay(() => {
        const items = backend.saveItems(backend.versionScope(vid), payload)
        return { version: backend.getVersion(vid).version, items }
      }),
    validate: (vid) => delay(() => backend.validate(vid)),
    // Deliberately routed through the *real* `unwrapValidationFailure`. The backend throws
    // a 422 for a failed publish, so this is the only way the suite ever executes the
    // client's unwrapping — previously it resolved `{valid:false}` directly and that code
    // was dead under `npm run check`.
    publish: (vid) =>
      delay(() => {
        const { result, version } = backend.publish(vid)
        return { ...result, version }
      }).catch((error) => {
        const unwrapped = unwrapValidationFailure(error)
        if (unwrapped) return unwrapped
        throw error
      }),

    listProjects: (makerId) => delay(() => backend.listProjects(makerId)),
    // The server answers `POST /projects` with `{project, items}`, not a bare project.
    // The stand-in has to as well, or the store's `created.project.id` reads `undefined`
    // only in production.
    createProject: (body) =>
      delay(() => {
        const created = backend.createProject(body)
        return backend.getProject(created.id)
      }),
    getProject: (pid) => delay(() => backend.getProject(pid)),
    getProjectsOverview: () => delay(() => backend.projectsOverview()),
    renameProject: (pid, name) => delay(() => backend.renameProject(pid, name)),
    listMakers: () => delay(() => backend.listMakers()),
    saveMakerSettings: (settings, projects) =>
      delay(() => backend.saveMakerSettings(settings, projects)),
    exportBoardXlsx: (scope) => delay(() => backend.exportBoardXlsx(scope)),
    exportDashboardPptx: (pid) => delay(() => backend.exportDashboardPptx(pid)),
    listProjectLinks: (pid) => delay(() => backend.listProjectLinks(pid)),
    saveProjectLinks: (pid, links) => delay(() => backend.saveProjectLinks(pid, links)),
    listProjectDocuments: (pid) => delay(() => backend.listProjectDocuments(pid)),
    saveProjectDocuments: (pid, payload) => delay(() => backend.saveProjectDocuments(pid, payload)),
    saveProjectItems: (pid, payload) =>
      delay(() => {
        const items = backend.saveItems(backend.projectScope(pid), payload)
        return { project: backend.getProject(pid).project, items }
      }),
    deleteProject: (pid) => delay(() => backend.deleteProject(pid)),

    appendRow: (scope) => delay(() => ({ items: backend.appendRow(scope) })),
    insertBelow: (scope, iid) => delay(() => ({ items: backend.insertBelow(scope, iid) })),
    deleteItem: (scope, iid) => delay(() => ({ items: backend.deleteItem(scope, iid) })),

    reorder: (scope, itemIds) => delay(() => ({ items: backend.reorder(scope, itemIds) })),
    setMembership: (scope, iid, payload) =>
      delay(() => ({ items: backend.setMembership(scope, iid, payload) })),
    createPhaseFromRow: (scope, iid, payload) =>
      delay(() => ({ items: backend.createPhaseFromRow(scope, iid, payload) })),
    createMilestoneFromRow: (scope, iid, payload) =>
      delay(() => ({ items: backend.createMilestoneFromRow(scope, iid, payload) })),

    applyPhases: (scope, payload) => delay(() => backend.applyPhases(scope, payload)),
    applyMilestones: (scope, phaseId, payload) =>
      delay(() => backend.applyMilestones(scope, phaseId, payload)),

    listDocuments: (scope) => delay(() => backend.listDocuments(scope)),
    applyTemplateDocuments: (scope, payload) =>
      delay(() => backend.applyTemplateDocuments(scope, payload)),

    listOwners: (scope) => delay(() => backend.listOwners(scope)),
    createOwner: (scope, body) => delay(() => backend.upsertOwner(scope, body)),
    updateOwner: (scope, id, body) => delay(() => backend.upsertOwner(scope, body, id)),
    deleteOwner: (scope, id) => delay<DeleteResult>(() => backend.deleteOwner(scope, id)),

    listPhases: (scope) => delay(() => backend.listPhases(scope)),
    createPhase: (scope, body) => delay(() => backend.upsertPhase(scope, body)),
    updatePhase: (scope, id, body) => delay(() => backend.upsertPhase(scope, body, id)),
    deletePhase: (scope, id) => delay<DeleteResult>(() => backend.deletePhase(scope, id)),

    listMilestones: (scope) => delay(() => backend.listMilestones(scope)),
    createMilestone: (scope, body) => delay(() => backend.upsertMilestone(scope, body)),
    updateMilestone: (scope, id, body) => delay(() => backend.upsertMilestone(scope, body, id)),
    deleteMilestone: (scope, id) => delay<DeleteResult>(() => backend.deleteMilestone(scope, id)),
  }
}
