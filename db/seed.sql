-- =============================================================================
-- 초기 시드 — docs/Work Package.xlsx 원본 데이터
--
-- **자동 생성 파일이다. 직접 편집하지 말고 `python db/migrate.py --emit-sql` 로
-- 재생성한다.** (생성기: db/migrate.py)
--
-- 내용: 템플릿 1건 / v1 PUBLISHED 버전 1건 /
--       Phase 4건 / Milestone 13건 / Owner 8건 /
--       문서 5건 / 행 35건
--
-- 전제: db/schema.sql 이 먼저 적용되어 있을 것.
-- 템플릿은 **중앙 기준 데이터**라 maker 개념이 없다 (plan.md §0.1).
-- 설비사별 인스턴스(프로젝트)는 이 파일에 없다 — db/dev_seed.sql 참고.
-- =============================================================================

USE `iai-test`;

SET NAMES utf8mb4;

-- 재실행 가능하도록 기존 시드 제거 (FK 역순)
DELETE wio FROM `wp_item_owners` wio JOIN `wp_items` i ON i.id=wio.item_id
  JOIN `wp_versions` v ON v.id=i.version_id WHERE v.template_id=1;
DELETE wid FROM `wp_item_documents` wid JOIN `wp_items` i ON i.id=wid.item_id
  JOIN `wp_versions` v ON v.id=i.version_id WHERE v.template_id=1;
DELETE i FROM `wp_items` i JOIN `wp_versions` v ON v.id=i.version_id WHERE v.template_id=1;
DELETE FROM `wp_versions`      WHERE template_id=1;
DELETE FROM `wp_milestones`    WHERE template_id=1;
DELETE FROM `wp_phases`        WHERE template_id=1;
DELETE FROM `wp_owners`        WHERE template_id=1;
DELETE FROM `wp_template_documents` WHERE template_id=1;
DELETE FROM `wp_templates` WHERE id=1;

-- --- 템플릿 --------------------------------------------------------------------
INSERT INTO `wp_templates` (id, code, name, description, phase_start_no, is_active)
VALUES (1, 'DSEP-AI-BOARD', 'DSEP AI Project Board', 'docs/Work Package.xlsx 의 Project Board 시트를 웹으로 이관한 초기 보드', 0, 1);

-- --- 문서 (템플릿 스코프 — plan.md §0.5.10) ---------------------------------
INSERT INTO `wp_template_documents` (id, template_id, name, sort_order, is_active) VALUES
  (1, 1, 'Project Charter & R&R', 1, 1),
  (2, 1, 'DSEP Readiness & I/O Spec', 2, 1),
  (3, 1, 'PM Management Log', 3, 1),
  (4, 1, 'Model Submission & Evaluation', 4, 1),
  (5, 1, 'Pilot, Closure & Expansion', 5, 1);

-- --- Phase (번호를 이름에서 분리 — plan.md §2.1) --------------------------------
INSERT INTO `wp_phases` (id, template_id, name, seq_no, is_active) VALUES
  (1, 1, 'Pre-Infrastructure Setup', 0, 1),
  (2, 1, 'Initiation & Readiness', 1, 1),
  (3, 1, 'Development Coordination & Progress Management', 2, 1),
  (4, 1, 'Evaluation, Pilot & Closure Management', 3, 1);

-- --- Milestone (seq_no 는 뒷자리만. 앞자리는 Phase 에서 파생) --------------------
INSERT INTO `wp_milestones` (id, template_id, phase_id, name, seq_no, is_active) VALUES
  (1, 1, 1, 'DSEP 환경 Gap 및 자원 구성', 1, 1),
  (2, 1, 1, '사내 자원 및 I/O 운영 연결', 2, 1),
  (3, 1, 2, 'Use Case & Scope Definition', 1, 1),
  (4, 1, 2, 'Collaboration & R&R', 2, 1),
  (5, 1, 2, 'Integrated Plan & Data Readiness', 3, 1),
  (6, 1, 3, 'Development Plan & Coordination', 1, 1),
  (7, 1, 3, 'Input, Data & Infra Support', 2, 1),
  (8, 1, 3, 'Progress, Issue & Change Management', 3, 1),
  (9, 1, 3, 'Interim Review & Candidate Submission', 4, 1),
  (10, 1, 4, 'Acceptance Evaluation Management', 1, 1),
  (11, 1, 4, 'Pilot & Go/No-Go', 2, 1),
  (12, 1, 4, 'Handover & Closure', 3, 1),
  (13, 1, 4, 'Standardization & Expansion', 4, 1);

-- --- Owner 기준정보 (`Owner` 컬럼의 `+` 분리 결과) -------------------------------
INSERT INTO `wp_owners` (id, template_id, name, sort_order, is_active) VALUES
  (1, 1, 'DSEP 인프라 담당자', 1, 1),
  (2, 1, '보안', 2, 1),
  (3, 1, '사내 IT·보안', 3, 1),
  (4, 1, '사내 개발부서', 4, 1),
  (5, 1, '설비사', 5, 1),
  (6, 1, '공동', 6, 1),
  (7, 1, '공동(구매·법무·보안)', 7, 1),
  (8, 1, '법무·보안', 8, 1);

-- --- v1 PUBLISHED 버전 ---------------------------------------------------------
INSERT INTO `wp_versions`
  (id, template_id, version_number, status, notes, phase_start_no,
   published_at, created_by, published_by)
VALUES (1, 1, 1, 'PUBLISHED', 'docs/Work Package.xlsx 최초 임포트', 0,
        NOW(), 'seed.sql', 'seed.sql');

-- --- 행 35건 --------------------------------------------------------------------
INSERT INTO `wp_items`
  (id, version_id, sort_order, phase_id, milestone_id, title, deliverable, dash_label,
   gate_code, status, completion_date, origin)
VALUES
  (1, 1, 1, 1, 1, '기존 DSEP 환경의 추가 필요사항(서버, Storage, 계정, 보안 등)을 점검하고 반영 계획을 확정', 'DSEP Gap & Resource Plan', 'Gap·자원 계획', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (2, 1, 2, 1, 1, '협력사별 Private Zone, VM/Server, 자원 Quota 및 접근권한을 구성하고 설비사 Onboarding과 접속 검증을 완료', 'Workspace Provisioning & Onboarding Checklist', 'Workspace 구성', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (3, 1, 3, 1, 2, '사내 데이터·컴퓨팅 자원 연결 필요 여부와 승인, 보안 및 운영 방식을 확정', 'Internal Resource Connectivity Plan', '사내 자원 연결', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (4, 1, 4, 1, 2, 'Input 전달→DSEP 처리→Output 회수와 반입·반출·장애지원 절차를 시험하고 인프라 착수를 승인', 'End-to-End Infra Readiness & G0 Record', 'E2E 검증 · G0', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (5, 1, 5, 2, 3, 'Target 제품·Module·Equipment, 해결할 업무 문제, 적용 범위 및 제외 범위를 확정', 'Scope & Problem Definition', '범위·문제 정의', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (6, 1, 6, 2, 3, '사내 개발부서가 제공할 Input, DSEP 모델이 반환할 Output 및 업무 활용 방식을 정의', 'AI Use Case & I/O Definition', 'Use Case·I/O', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (7, 1, 7, 2, 3, '기술·업무 KPI, Baseline 및 결과 Acceptance 기준을 정의', 'KPI & Acceptance Criteria', 'KPI·합격 기준', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (8, 1, 8, 2, 4, 'DSEP 인프라 담당자, 설비사, 사내 개발부서의 역할과 책임 경계를 확정', 'RACI & Responsibility Boundary', 'RACI 책임 경계', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (9, 1, 9, 2, 4, '업무 요청·질의·Feedback, 의사결정, 승인 및 Escalation 경로를 정의', 'Governance & Communication Workflow', '소통·승인 체계', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (10, 1, 10, 2, 4, '데이터·모델·산출물 교환, 보안, IP·사용권 및 성능 미달 시 Rework 원칙을 확정', 'Collaboration Agreement', '협약 체결', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (11, 1, 11, 2, 5, 'Milestone, 주요 산출물, 보고 주기, 담당자 및 Stage Gate를 포함한 통합 계획을 확정', 'Integrated Project Plan', '통합 계획', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (12, 1, 12, 2, 5, '필요 데이터 Source·Owner·승인상태와 제공 일정을 정리', 'Data Provision Plan', '데이터 제공 계획', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (13, 1, 13, 2, 5, 'Input·Output Schema, 전달 방식, Version 및 변경 관리 기준을 확정', 'I/O Specification', 'I/O 규격', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (14, 1, 14, 2, 5, '범위·역할·데이터·인프라 준비상태를 종합 검토하고 개발 착수를 승인', 'Kick-off Minutes & G1 Record', 'Kick-off · G1', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (15, 1, 15, 3, 6, '설비사가 개발 일정, 주요 Milestone 및 제출 예정 산출물이 포함된 개발계획을 제출', 'Vendor Development Plan', '개발계획 접수', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (16, 1, 16, 3, 6, '사내 개발부서의 요구사항·우선순위·검토 일정과 설비사 개발계획을 정렬', 'Integrated Working Schedule', '통합 일정 정렬', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (17, 1, 17, 3, 7, '데이터·Input 요청, 제공 일정, DSEP 반입 및 설비사 수신 여부를 통합 추적', 'Data/Input Request & Delivery Tracker', 'Input 제공 추적', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (18, 1, 18, 3, 7, '서버·자원·패키지·접근권한 등 인프라 지원 요청과 처리결과를 관리', 'Infrastructure Support Log', '인프라 지원', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (19, 1, 19, 3, 8, '설비사 정기 진행현황과 계획 대비 Milestone·산출물 완료상태를 확인', 'Progress Report & Milestone Tracker', '진행현황 점검', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (20, 1, 20, 3, 8, 'Risk, Assumption, Issue, Dependency 및 Action Item을 통합 관리', 'RAID & Action Log', 'RAID·Action', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (21, 1, 21, 3, 8, '주요 의사결정, Escalation 및 범위·일정·요구사항 변경의 영향과 승인상태를 관리', 'Decision & Change Log', '결정·변경 관리', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (22, 1, 22, 3, 9, '설비사 중간 결과, 사내 개발부서 Feedback 및 보완조치 진행상태를 관리', 'Interim Review & Rework Record', '중간 Review', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (23, 1, 23, 3, 9, '설비사가 평가 대상 Model Version, 결과, 사용방법 및 Known Limitation을 포함한 Candidate를 제출', 'Candidate Submission Package', 'Candidate 제출', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (24, 1, 24, 3, 9, '제출 Package의 필수항목과 Input→Output 평가 경로의 준비상태를 확인', 'Submission & Evaluation Readiness Checklist', '평가 준비 점검', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (25, 1, 25, 3, 9, 'Candidate 제출 완료와 사내 평가 착수 가능 여부를 검토하고 평가부서에 인계', 'G2 Record & Evaluation Handover', '평가 인계 · G2', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (26, 1, 26, 4, 10, '평가 대상·Dataset·기간·참여자·증빙 양식 및 판정 절차를 확정', 'Evaluation Plan', '평가 계획', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (27, 1, 27, 4, 10, '설비사 자체 평가와 사내 Acceptance 평가 결과를 수집·비교하고 성능·업무효과·안정성·잔여 Risk를 종합 검토', 'Evaluation Scorecard & Review Report', '평가결과 종합', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (28, 1, 28, 4, 10, 'Pass, Conditional Pass, Rework 또는 Fail을 판정하고 보완·재평가 일정을 관리', 'Acceptance Decision & Rework Tracker (G3 Record)', '판정 · G3', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (29, 1, 29, 4, 11, 'Pilot 대상, 기간, 운영조건, 표본 수, 성공기준 및 Input·Output 운영절차를 확정', 'Pilot Plan', 'Pilot 계획', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (30, 1, 30, 4, 11, 'Pilot 결과와 실제 결과 비교자료, 사용자 VOC, KPI Baseline 대비 효과 및 운영 Risk를 수집·종합 평가', 'Pilot Result Report (KPI·VOC 종합)', 'Pilot 결과 종합', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (31, 1, 31, 4, 11, 'Go, Conditional Go, Rework 또는 Stop을 결정하고 Pilot Acceptance를 승인', 'Go/No-Go Decision & G4 Record', 'Go/No-Go · G4', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (32, 1, 32, 4, 12, '최종 Asset·Version·사용방법·운영지원 절차와 미해결 이슈를 인계', 'Final Handover Package', '최종 인계', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (33, 1, 33, 4, 12, '사용권, 보존·삭제 대상, 접근권한 회수 및 프로젝트 종료 승인을 완료', 'Closure Record', '종료 처리', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (34, 1, 34, 4, 13, 'Lessons Learned를 반영해 협력사 Onboarding, 진행관리 및 평가 Template를 개선', 'Standard Improvement Action List', '표준 개선', NULL, 'NOT_STARTED', NULL, 'INHERITED'),
  (35, 1, 35, 4, 13, '확대 후보, 추가 인프라 용량·비용, 추진 Roadmap 및 Scale-out 승인안을 수립', 'Expansion Roadmap & G5 Record', '확대 승인 · G5', NULL, 'NOT_STARTED', NULL, 'INHERITED');

-- --- 행 ↔ 문서 (N:M) ------------------------------------------------------------
INSERT INTO `wp_item_documents` (item_id, template_document_id, sort_order) VALUES
  (1, 2, 1),
  (2, 2, 1),
  (3, 2, 1),
  (4, 2, 1),
  (5, 1, 1),
  (6, 1, 1),
  (6, 2, 2),
  (7, 1, 1),
  (8, 1, 1),
  (9, 1, 1),
  (10, 1, 1),
  (11, 1, 1),
  (12, 2, 1),
  (13, 2, 1),
  (14, 1, 1),
  (14, 2, 2),
  (15, 3, 1),
  (16, 3, 1),
  (17, 3, 1),
  (18, 3, 1),
  (19, 3, 1),
  (20, 3, 1),
  (21, 3, 1),
  (22, 3, 1),
  (23, 4, 1),
  (24, 4, 1),
  (25, 4, 1),
  (26, 4, 1),
  (27, 4, 1),
  (28, 4, 1),
  (29, 5, 1),
  (30, 5, 1),
  (31, 5, 1),
  (32, 5, 1),
  (33, 5, 1),
  (34, 5, 1),
  (35, 5, 1);

-- --- 행 ↔ Owner (N:M) -----------------------------------------------------------
INSERT INTO `wp_item_owners` (item_id, owner_id, sort_order) VALUES
  (1, 1, 1),
  (2, 1, 1),
  (2, 2, 2),
  (3, 1, 1),
  (3, 3, 2),
  (4, 1, 1),
  (5, 4, 1),
  (6, 4, 1),
  (6, 5, 2),
  (7, 4, 1),
  (8, 6, 1),
  (9, 1, 1),
  (10, 7, 1),
  (11, 1, 1),
  (12, 4, 1),
  (13, 4, 1),
  (13, 5, 2),
  (14, 1, 1),
  (15, 5, 1),
  (16, 1, 1),
  (17, 1, 1),
  (18, 1, 1),
  (19, 1, 1),
  (20, 1, 1),
  (21, 1, 1),
  (22, 6, 1),
  (23, 5, 1),
  (24, 1, 1),
  (25, 4, 1),
  (25, 1, 2),
  (26, 4, 1),
  (26, 1, 2),
  (27, 4, 1),
  (27, 5, 2),
  (28, 4, 1),
  (28, 1, 2),
  (29, 4, 1),
  (30, 4, 1),
  (31, 4, 1),
  (31, 1, 2),
  (32, 6, 1),
  (33, 1, 1),
  (33, 8, 2),
  (34, 1, 1),
  (35, 6, 1);
