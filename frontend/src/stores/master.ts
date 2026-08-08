import { computed, ref, shallowRef } from 'vue'
import type { WpApiClient } from '../api/client'
import type { MasterScope, TemplateDocument, WpMilestone, WpOwner, WpPhase } from '../api/types'

/**
 * Master data — the **scope-local** documents / owners / phases / milestones
 * (`plan.md` §0.1, §2.6, §0.5.10).
 *
 * Documents joined this list in §0.5.10: there is no global document master any more, so
 * they follow the same copy-per-scope rule as everything else here.
 *
 * "Scope-local" is the whole point of the two-tier split: a template owns one set, and
 * every project owns a *copy* made at creation time. The ids differ between them, so a
 * store that cached one scope's list and served it to another would hand the grid phase
 * ids the server refuses (`INVALID_REFERENCE`). Loading is therefore always keyed by
 * {@link MasterScope} and the cache is dropped whenever the scope changes.
 *
 * A factory, not a Pinia store: every mounted board builds its own instance and hands it
 * down through `provide()`. Nothing lives at module scope, so two boards mounted side by
 * side in the same host never see each other's data (INTEGRATION.md §5).
 */
export function createMasterStore(api: WpApiClient) {
  /**
   * 이 스코프의 문서 (`plan.md` §0.5.10). 전역 마스터가 아니라 템플릿/프로젝트 소유다 —
   * Phase·Milestone·Owner 와 같은 규칙이라 `loadForScope` 가 함께 불러온다.
   */
  const documents = shallowRef<TemplateDocument[]>([])
  const owners = shallowRef<WpOwner[]>([])
  const phases = shallowRef<WpPhase[]>([])
  const milestones = shallowRef<WpMilestone[]>([])
  const loading = ref(false)
  /** Which scope the three lists above belong to; null when nothing is loaded. */
  const loadedScope = ref<string | null>(null)

  const activeDocuments = computed(() => documents.value.filter((d) => d.is_active))
  const activeOwners = computed(() => owners.value.filter((o) => o.is_active))
  const activePhases = computed(() =>
    [...phases.value].filter((p) => p.is_active).sort((a, b) => a.seq_no - b.seq_no),
  )

  /** Milestones of one phase, in display order. */
  const milestonesOfPhase = (phaseId: number | null) =>
    phaseId == null
      ? []
      : milestones.value
          .filter((m) => m.phase_id === phaseId && m.is_active)
          .sort((a, b) => a.seq_no - b.seq_no)

  const phaseLabel = (phase: WpPhase) => `Phase ${phase.seq_no}. ${phase.name}`
  const milestoneLabel = (milestone: WpMilestone) => {
    const phase = phases.value.find((p) => p.id === milestone.phase_id)
    return `${phase?.seq_no ?? '?'}.${milestone.seq_no} ${milestone.name}`
  }

  /**
   * Documents are loaded by the **board** store, not here.
   *
   * The endpoint hangs off `itemsBase` (`/versions/{vid}/documents`), and a {@link MasterScope}
   * deliberately has no version id — so this store cannot ask for them. The board store has
   * the full `BoardScope` and hands the answer over.
   */
  function setDocuments(list: TemplateDocument[]): void {
    documents.value = list
  }

  const scopeKey = (scope: MasterScope) =>
    scope.kind === 'template' ? `t${scope.templateId}` : `p${scope.projectId}`

  async function loadForScope(scope: MasterScope): Promise<void> {
    loading.value = true
    try {
      const [o, p, m] = await Promise.all([
        api.listOwners(scope),
        api.listPhases(scope),
        api.listMilestones(scope),
      ])
      owners.value = o
      phases.value = p
      milestones.value = m
      loadedScope.value = scopeKey(scope)
    } finally {
      loading.value = false
    }
  }

  /**
   * Takes the phase/milestone lists straight off a board response (`plan.md` §0.4).
   *
   * The apply endpoints answer with the recomputed master data alongside the rows, so
   * refetching would be a second round trip against a server that already told us — and a
   * window in which the cell editors offer a phase list that disagrees with the board.
   */
  function absorbScopeData(next: { phases: WpPhase[]; milestones: WpMilestone[] }): void {
    phases.value = next.phases
    milestones.value = next.milestones
  }

  /**
   * Empties the scope-local lists.
   *
   * Called when the board leaves a scope with no new one to load — closing a project, say.
   * Leaving the previous scope's phases on screen would offer the user ids that belong to
   * something else entirely.
   */
  function clearScope(): void {
    owners.value = []
    phases.value = []
    milestones.value = []
    loadedScope.value = null
  }

  return {
    documents,
    setDocuments,
    owners,
    phases,
    milestones,
    loading,
    loadedScope,

    activeDocuments,
    activeOwners,
    activePhases,
    milestonesOfPhase,
    phaseLabel,
    milestoneLabel,

    loadForScope,
    absorbScopeData,
    clearScope,
  }
}

export type MasterStore = ReturnType<typeof createMasterStore>
