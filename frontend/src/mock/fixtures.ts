/**
 * Seed data transcribed from `docs/Work Package.xlsx` (Project Board 35행 / Doc Status 5건).
 *
 * DEV ONLY. Consumed by `src/mock` so the grid, the boundary editors and the publish flow
 * can be exercised without a live backend. Nothing under `src/mock` or `src/dev` is part
 * of the federated bundle.
 */

export interface SeedPhase {
  key: string
  name: string
}

export interface SeedMilestone {
  key: string
  phaseKey: string
  name: string
}

export interface SeedRow {
  milestoneKey: string
  title: string
  deliverable: string
  docs: string[]
  owners: string[]
  gate?: string
}

export const SEED_PHASES: SeedPhase[] = [
  { key: '0', name: 'Pre-Infrastructure Setup' },
  { key: '1', name: 'Initiation & Readiness' },
  { key: '2', name: 'Development Coordination & Progress Management' },
  { key: '3', name: 'Evaluation, Pilot & Closure Management' },
]

export const SEED_MILESTONES: SeedMilestone[] = [
  { key: '0.1', phaseKey: '0', name: 'DSEP 환경 Gap 및 자원 구성' },
  { key: '0.2', phaseKey: '0', name: '사내 자원 및 I/O 운영 연결' },
  { key: '1.1', phaseKey: '1', name: 'Use Case & Scope Definition' },
  { key: '1.2', phaseKey: '1', name: 'Collaboration & R&R' },
  { key: '1.3', phaseKey: '1', name: 'Integrated Plan & Data Readiness' },
  { key: '2.1', phaseKey: '2', name: 'Development Plan & Coordination' },
  { key: '2.2', phaseKey: '2', name: 'Input, Data & Infra Support' },
  { key: '2.3', phaseKey: '2', name: 'Progress, Issue & Change Management' },
  { key: '2.4', phaseKey: '2', name: 'Interim Review & Candidate Submission' },
  { key: '3.1', phaseKey: '3', name: 'Acceptance Evaluation Management' },
  { key: '3.2', phaseKey: '3', name: 'Pilot & Go/No-Go' },
  { key: '3.3', phaseKey: '3', name: 'Handover & Closure' },
  { key: '3.4', phaseKey: '3', name: 'Standardization & Expansion' },
]

/** `Owner` in the sheet is a `+`-separated multi-value; these are the split atoms. */
export const SEED_OWNERS: string[] = [
  'DSEP 인프라 담당자',
  '사내 개발부서',
  '설비사',
  '사내 IT·보안',
  '보안',
  '법무·보안',
  '공동',
  '공동(구매·법무·보안)',
]

export interface SeedDocumentType {
  code: string
  name: string
  phaseLabel: string
  gateCode: string
  defaultOwner: string
  remark: string
}

export const SEED_DOCUMENT_TYPES: SeedDocumentType[] = [
  {
    code: '①',
    name: 'Project Charter & R&R',
    phaseLabel: 'Phase 1',
    gateCode: 'G1',
    defaultOwner: 'DSEP 인프라 담당자',
    remark: '범위·KPI·역할·협업원칙·통합계획·착수승인',
  },
  {
    code: '②',
    name: 'DSEP Readiness & I/O Spec',
    phaseLabel: 'Phase 0~1',
    gateCode: 'G0·G1',
    defaultOwner: 'DSEP 인프라 담당자+사내 IT·보안',
    remark: '인프라·자원연결·데이터 준비·I/O 규격·반입반출',
  },
  {
    code: '③',
    name: 'PM Management Log',
    phaseLabel: 'Phase 2 (상시)',
    gateCode: 'G2',
    defaultOwner: 'DSEP 인프라 담당자',
    remark: '대장: 본 파일 RAID·Action·Decision 탭',
  },
  {
    code: '④',
    name: 'Model Submission & Evaluation',
    phaseLabel: 'Phase 2~3',
    gateCode: 'G2·G3',
    defaultOwner: '설비사+사내 개발부서',
    remark: 'Candidate 제출·평가·Acceptance 판정·Rework',
  },
  {
    code: '⑤',
    name: 'Pilot, Closure & Expansion',
    phaseLabel: 'Phase 3',
    gateCode: 'G4·G5',
    defaultOwner: '사내 개발부서+공동',
    remark: 'Pilot·Go/No-Go·인계·종료·확대',
  },
]

export const SEED_ROWS: SeedRow[] = [
  {
    milestoneKey: '0.1',
    title:
      '기존 DSEP 환경의 추가 필요사항(서버, Storage, 계정, 보안 등)을 점검하고 반영 계획을 확정',
    deliverable: 'DSEP Gap & Resource Plan',
    docs: ['②'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '0.1',
    title:
      '협력사별 Private Zone, VM/Server, 자원 Quota 및 접근권한을 구성하고 설비사 Onboarding과 접속 검증을 완료',
    deliverable: 'Workspace Provisioning & Onboarding Checklist',
    docs: ['②'],
    owners: ['DSEP 인프라 담당자', '보안'],
  },
  {
    milestoneKey: '0.2',
    title: '사내 데이터·컴퓨팅 자원 연결 필요 여부와 승인, 보안 및 운영 방식을 확정',
    deliverable: 'Internal Resource Connectivity Plan',
    docs: ['②'],
    owners: ['DSEP 인프라 담당자', '사내 IT·보안'],
  },
  {
    milestoneKey: '0.2',
    title:
      'Input 전달→DSEP 처리→Output 회수와 반입·반출·장애지원 절차를 시험하고 인프라 착수를 승인',
    deliverable: 'End-to-End Infra Readiness & G0 Record',
    docs: ['②'],
    owners: ['DSEP 인프라 담당자'],
    gate: 'G0',
  },
  {
    milestoneKey: '1.1',
    title: 'Target 제품·Module·Equipment, 해결할 업무 문제, 적용 범위 및 제외 범위를 확정',
    deliverable: 'Scope & Problem Definition',
    docs: ['①'],
    owners: ['사내 개발부서'],
  },
  {
    milestoneKey: '1.1',
    title: '사내 개발부서가 제공할 Input, DSEP 모델이 반환할 Output 및 업무 활용 방식을 정의',
    deliverable: 'AI Use Case & I/O Definition',
    docs: ['①', '②'],
    owners: ['사내 개발부서', '설비사'],
  },
  {
    milestoneKey: '1.1',
    title: '기술·업무 KPI, Baseline 및 결과 Acceptance 기준을 정의',
    deliverable: 'KPI & Acceptance Criteria',
    docs: ['①'],
    owners: ['사내 개발부서'],
  },
  {
    milestoneKey: '1.2',
    title: 'DSEP 인프라 담당자, 설비사, 사내 개발부서의 역할과 책임 경계를 확정',
    deliverable: 'RACI & Responsibility Boundary',
    docs: ['①'],
    owners: ['공동'],
  },
  {
    milestoneKey: '1.2',
    title: '업무 요청·질의·Feedback, 의사결정, 승인 및 Escalation 경로를 정의',
    deliverable: 'Governance & Communication Workflow',
    docs: ['①'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '1.2',
    title: '데이터·모델·산출물 교환, 보안, IP·사용권 및 성능 미달 시 Rework 원칙을 확정',
    deliverable: 'Collaboration Agreement',
    docs: ['①'],
    owners: ['공동(구매·법무·보안)'],
  },
  {
    milestoneKey: '1.3',
    title: 'Milestone, 주요 산출물, 보고 주기, 담당자 및 Stage Gate를 포함한 통합 계획을 확정',
    deliverable: 'Integrated Project Plan',
    docs: ['①'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '1.3',
    title: '필요 데이터 Source·Owner·승인상태와 제공 일정을 정리',
    deliverable: 'Data Provision Plan',
    docs: ['②'],
    owners: ['사내 개발부서'],
  },
  {
    milestoneKey: '1.3',
    title: 'Input·Output Schema, 전달 방식, Version 및 변경 관리 기준을 확정',
    deliverable: 'I/O Specification',
    docs: ['②'],
    owners: ['사내 개발부서', '설비사'],
  },
  {
    milestoneKey: '1.3',
    title: '범위·역할·데이터·인프라 준비상태를 종합 검토하고 개발 착수를 승인',
    deliverable: 'Kick-off Minutes & G1 Record',
    docs: ['①', '②'],
    owners: ['DSEP 인프라 담당자'],
    gate: 'G1',
  },
  {
    milestoneKey: '2.1',
    title: '설비사가 개발 일정, 주요 Milestone 및 제출 예정 산출물이 포함된 개발계획을 제출',
    deliverable: 'Vendor Development Plan',
    docs: ['③'],
    owners: ['설비사'],
  },
  {
    milestoneKey: '2.1',
    title: '사내 개발부서의 요구사항·우선순위·검토 일정과 설비사 개발계획을 정렬',
    deliverable: 'Integrated Working Schedule',
    docs: ['③'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.2',
    title: '데이터·Input 요청, 제공 일정, DSEP 반입 및 설비사 수신 여부를 통합 추적',
    deliverable: 'Data/Input Request & Delivery Tracker',
    docs: ['③'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.2',
    title: '서버·자원·패키지·접근권한 등 인프라 지원 요청과 처리결과를 관리',
    deliverable: 'Infrastructure Support Log',
    docs: ['③'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.3',
    title: '설비사 정기 진행현황과 계획 대비 Milestone·산출물 완료상태를 확인',
    deliverable: 'Progress Report & Milestone Tracker',
    docs: ['③'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.3',
    title: 'Risk, Assumption, Issue, Dependency 및 Action Item을 통합 관리',
    deliverable: 'RAID & Action Log',
    docs: ['③'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.3',
    title: '주요 의사결정, Escalation 및 범위·일정·요구사항 변경의 영향과 승인상태를 관리',
    deliverable: 'Decision & Change Log',
    docs: ['③'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.4',
    title: '설비사 중간 결과, 사내 개발부서 Feedback 및 보완조치 진행상태를 관리',
    deliverable: 'Interim Review & Rework Record',
    docs: ['③'],
    owners: ['공동'],
  },
  {
    milestoneKey: '2.4',
    title:
      '설비사가 평가 대상 Model Version, 결과, 사용방법 및 Known Limitation을 포함한 Candidate를 제출',
    deliverable: 'Candidate Submission Package',
    docs: ['④'],
    owners: ['설비사'],
  },
  {
    milestoneKey: '2.4',
    title: '제출 Package의 필수항목과 Input→Output 평가 경로의 준비상태를 확인',
    deliverable: 'Submission & Evaluation Readiness Checklist',
    docs: ['④'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '2.4',
    title: 'Candidate 제출 완료와 사내 평가 착수 가능 여부를 검토하고 평가부서에 인계',
    deliverable: 'G2 Record & Evaluation Handover',
    docs: ['④'],
    owners: ['사내 개발부서', 'DSEP 인프라 담당자'],
    gate: 'G2',
  },
  {
    milestoneKey: '3.1',
    title: '평가 대상·Dataset·기간·참여자·증빙 양식 및 판정 절차를 확정',
    deliverable: 'Evaluation Plan',
    docs: ['④'],
    owners: ['사내 개발부서', 'DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '3.1',
    title:
      '설비사 자체 평가와 사내 Acceptance 평가 결과를 수집·비교하고 성능·업무효과·안정성·잔여 Risk를 종합 검토',
    deliverable: 'Evaluation Scorecard & Review Report',
    docs: ['④'],
    owners: ['사내 개발부서', '설비사'],
  },
  {
    milestoneKey: '3.1',
    title: 'Pass, Conditional Pass, Rework 또는 Fail을 판정하고 보완·재평가 일정을 관리',
    deliverable: 'Acceptance Decision & Rework Tracker (G3 Record)',
    docs: ['④'],
    owners: ['사내 개발부서', 'DSEP 인프라 담당자'],
    gate: 'G3',
  },
  {
    milestoneKey: '3.2',
    title: 'Pilot 대상, 기간, 운영조건, 표본 수, 성공기준 및 Input·Output 운영절차를 확정',
    deliverable: 'Pilot Plan',
    docs: ['⑤'],
    owners: ['사내 개발부서'],
  },
  {
    milestoneKey: '3.2',
    title:
      'Pilot 결과와 실제 결과 비교자료, 사용자 VOC, KPI Baseline 대비 효과 및 운영 Risk를 수집·종합 평가',
    deliverable: 'Pilot Result Report (KPI·VOC 종합)',
    docs: ['⑤'],
    owners: ['사내 개발부서'],
  },
  {
    milestoneKey: '3.2',
    title: 'Go, Conditional Go, Rework 또는 Stop을 결정하고 Pilot Acceptance를 승인',
    deliverable: 'Go/No-Go Decision & G4 Record',
    docs: ['⑤'],
    owners: ['사내 개발부서', 'DSEP 인프라 담당자'],
    gate: 'G4',
  },
  {
    milestoneKey: '3.3',
    title: '최종 Asset·Version·사용방법·운영지원 절차와 미해결 이슈를 인계',
    deliverable: 'Final Handover Package',
    docs: ['⑤'],
    owners: ['공동'],
  },
  {
    milestoneKey: '3.3',
    title: '사용권, 보존·삭제 대상, 접근권한 회수 및 프로젝트 종료 승인을 완료',
    deliverable: 'Closure Record',
    docs: ['⑤'],
    owners: ['DSEP 인프라 담당자', '법무·보안'],
  },
  {
    milestoneKey: '3.4',
    title: 'Lessons Learned를 반영해 협력사 Onboarding, 진행관리 및 평가 Template를 개선',
    deliverable: 'Standard Improvement Action List',
    docs: ['⑤'],
    owners: ['DSEP 인프라 담당자'],
  },
  {
    milestoneKey: '3.4',
    title: '확대 후보, 추가 인프라 용량·비용, 추진 Roadmap 및 Scale-out 승인안을 수립',
    deliverable: 'Expansion Roadmap & G5 Record',
    docs: ['⑤'],
    owners: ['공동'],
    gate: 'G5',
  },
]

/**
 * `dash_label` for the 35 seed rows, by position — the card captions of `docs/dashboard.jpg`
 * (`plan.md` §0.5-1).
 *
 * A parallel array rather than a field on {@link SeedRow} because it is a *different*
 * transcription: `SEED_ROWS` comes from the spreadsheet, these come from the deck, and the
 * only thing tying them together is row order. Keeping them apart makes that visible instead
 * of implying the labels were in the sheet all along. The real seeding lives in
 * `db/migrate.py`; this is the mock's copy of the same constant.
 */
export const SEED_DASH_LABELS: string[] = [
  'Gap·자원 계획',
  'Workspace 구성',
  '사내 자원 연결',
  'E2E 검증 · G0',
  '범위·문제 정의',
  'Use Case·I/O',
  'KPI·합격 기준',
  'RACI 책임 경계',
  '소통·승인 체계',
  '협약 체결',
  '통합 계획',
  '데이터 제공 계획',
  'I/O 규격',
  'Kick-off · G1',
  '개발계획 접수',
  '통합 일정 정렬',
  'Input 제공 추적',
  '인프라 지원',
  '진행현황 점검',
  'RAID·Action',
  '결정·변경 관리',
  '중간 Review',
  'Candidate 제출',
  '평가 준비 점검',
  '평가 인계 · G2',
  '평가 계획',
  '평가결과 종합',
  '판정 · G3',
  'Pilot 계획',
  'Pilot 결과 종합',
  'Go/No-Go · G4',
  '최종 인계',
  '종료 처리',
  '표준 개선',
  '확대 승인 · G5',
]

/**
 * What the host's `MakerResolver.list_makers()` would return (`plan.md` §0.6).
 *
 * DEV ONLY, and deliberately **wider than the set that has projects**: 설비사 #4 has none, so
 * the settings screen has a row whose "전체 현황 표시" is off purely by the derived rule, and
 * ticking it produces an empty section with a 추가 button — the flow §0.6 exists to enable.
 */
export const SEED_MAKERS: { id: number; name: string }[] = [
  { id: 1, name: 'A설비 주식회사' },
  { id: 2, name: 'B테크놀로지' },
  { id: 4, name: 'D머시너리' },
  { id: 7, name: 'G정밀' },
]
