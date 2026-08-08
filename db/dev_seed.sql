-- =============================================================================
-- 개발 전용 시드 — 이식 시 **적용하지 않는다**
--
-- INTEGRATION.md §2.3 / §6 체크리스트:
--   [ ] db/dev_seed.sql 과 wp_dev_makers 미적용
--
-- 설비사(Maker) 테이블은 호스트 프로젝트 소유다. 이 저장소는 설비사 테이블을
-- 만들지 않으며, wp_projects.maker_id 로 값만 참조한다 (plan.md §0.1 —
-- 템플릿에는 maker 개념이 없다).
-- 아래 wp_dev_makers 는 **로컬 단독 실행용 스텁**일 뿐이고,
-- 이 테이블을 읽는 코드는 backend/app/ports/stub_maker_resolver.py 의
-- StubMakerResolver 한 곳뿐이어야 한다.
--
-- 운영 스키마(db/schema.sql)에는 이 테이블이 없다. 서로 섞지 말 것.
--
-- **데모 프로젝트도 여기에만 있다.** db/seed.sql 은 템플릿(기준 데이터)만 담는다 —
-- 중앙 기준 데이터에 특정 설비사의 흔적을 남기지 않기 위해서다.
-- =============================================================================

USE `iai-test`;

-- [DEV ONLY] 호스트 설비사 테이블의 로컬 대역(stand-in).
DROP TABLE IF EXISTS `wp_dev_makers`;
CREATE TABLE `wp_dev_makers` (
  `id`         INT          NOT NULL AUTO_INCREMENT,
  `name`       VARCHAR(200) NOT NULL,
  `code`       VARCHAR(50)  NULL,
  `is_active`  TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpdm_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='DEV ONLY — 호스트 설비사 테이블 스텁. 이식 시 삭제.';

INSERT INTO `wp_dev_makers` (`id`, `name`, `code`) VALUES
  (1, '설비사 A (개발 스텁)', 'MAKER-A'),
  (2, '설비사 B (개발 스텁)', 'MAKER-B'),
  (3, '설비사 C (개발 스텁)', 'MAKER-C');


-- =============================================================================
-- [DEV ONLY] 데모 프로젝트 — 시드 템플릿의 발행본을 복제한 것
--
-- 화면을 열자마자 프로젝트 계층을 볼 수 있도록 하나 만들어 둔다. 백엔드의
-- `POST /api/v1/projects` 가 하는 deep copy 와 **같은 결과**를 SQL 로 재현한다:
--   phase/milestone/owner 는 로컬 사본, 문서는 전역 행을 그대로 참조,
--   phase_start_no 는 원본 버전의 값을 스냅샷.
--
-- 재실행 안전: 같은 이름의 데모 프로젝트를 먼저 지운다.
-- =============================================================================

DELETE FROM `wp_projects` WHERE `name` = '[개발] 설비사 A 데모 프로젝트';

INSERT INTO `wp_projects`
  (maker_id, name, description, source_template_id, source_version_id, phase_start_no, created_by)
SELECT 1,
       '[개발] 설비사 A 데모 프로젝트',
       'dev_seed.sql 이 만든 데모. 이식 시 적용하지 않는다.',
       t.id, v.id, v.phase_start_no, 'dev_seed.sql'
  FROM `wp_templates` t
  JOIN `wp_versions`  v ON v.template_id = t.id AND v.status = 'PUBLISHED'
 WHERE t.code = 'DSEP-AI-BOARD';

SET @pid := LAST_INSERT_ID();
SET @vid := (SELECT source_version_id FROM `wp_projects` WHERE id = @pid);
SET @tid := (SELECT source_template_id FROM `wp_projects` WHERE id = @pid);

-- 기준정보 사본. `source_*_id` 가 원본을 가리키므로 아래 행 복사에서 매핑에 쓴다.
INSERT INTO `wp_project_phases` (project_id, name, seq_no, is_active, source_phase_id)
SELECT @pid, p.name, p.seq_no, p.is_active, p.id
  FROM `wp_phases` p WHERE p.template_id = @tid ORDER BY p.seq_no, p.id;

INSERT INTO `wp_project_milestones`
  (project_id, phase_id, name, seq_no, is_active, source_milestone_id)
SELECT @pid, pp.id, m.name, m.seq_no, m.is_active, m.id
  FROM `wp_milestones` m
  JOIN `wp_project_phases` pp ON pp.project_id = @pid AND pp.source_phase_id = m.phase_id
 WHERE m.template_id = @tid ORDER BY m.phase_id, m.seq_no, m.id;

INSERT INTO `wp_project_owners` (project_id, name, sort_order, is_active, source_owner_id)
SELECT @pid, o.name, o.sort_order, o.is_active, o.id
  FROM `wp_owners` o WHERE o.template_id = @tid ORDER BY o.sort_order, o.id;

INSERT INTO `wp_project_items`
  (project_id, sort_order, phase_id, milestone_id, title, deliverable, gate_code,
   status, completion_date, origin, source_item_id)
SELECT @pid, i.sort_order, pp.id, pm.id, i.title, i.deliverable, i.gate_code,
       i.status, i.completion_date, 'INHERITED', i.id
  FROM `wp_items` i
  LEFT JOIN `wp_project_phases`     pp ON pp.project_id = @pid AND pp.source_phase_id = i.phase_id
  LEFT JOIN `wp_project_milestones` pm ON pm.project_id = @pid AND pm.source_milestone_id = i.milestone_id
 WHERE i.version_id = @vid ORDER BY i.sort_order, i.id;

-- 문서는 **전역**이라 복제하지 않는다 — 같은 document_type_id 를 그대로 가리킨다.
INSERT INTO `wp_project_item_documents` (item_id, document_type_id, sort_order)
SELECT ppi.id, d.document_type_id, d.sort_order
  FROM `wp_item_documents` d
  JOIN `wp_project_items` ppi ON ppi.project_id = @pid AND ppi.source_item_id = d.item_id;

-- Owner 는 로컬 사본으로 다시 매핑한다.
INSERT INTO `wp_project_item_owners` (item_id, owner_id, sort_order)
SELECT ppi.id, po.id, io.sort_order
  FROM `wp_item_owners` io
  JOIN `wp_project_items` ppi ON ppi.project_id = @pid AND ppi.source_item_id = io.item_id
  JOIN `wp_project_owners` po ON po.project_id = @pid AND po.source_owner_id = io.owner_id;
