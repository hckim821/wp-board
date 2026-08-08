-- =============================================================================
-- 006_document_ownership — 문서 모델 개편 (plan.md §0.5.10)
--
-- 전역 문서(`wp_document_types`)를 폐기하고, 문서를 Phase/Milestone/Owner 와 같은
-- 스코프 규칙 위로 옮긴다: **포맷(템플릿)이 소유**하고 **프로젝트 생성 시 복제**된다.
--
--   wp_template_documents            (신규 — 템플릿 스코프)
--   wp_project_documents             (개편 — document_type_id 제거, name/sort_order 추가)
--   wp_item_documents.document_type_id         → template_document_id
--   wp_project_item_documents.document_type_id → project_document_id
--   wp_document_types                (이행 후 DROP)
--
-- ⚠️ **데이터 이행이 들어 있다. 손실 금지.** 전역 문서를 각 템플릿·프로젝트로
--    복제하고 링크를 재매핑한 뒤에야 원본을 지운다. 이행 전후로 링크 수가 같아야
--    한다 — 검증 쿼리는 파일 맨 아래 주석에 있다.
--
-- ## 재실행 안전성
--
-- 이 마이그레이션은 **자기 입력을 파괴한다** (`wp_document_types` 를 지운다). 그래서
-- 맨 위에서 그 테이블을 `IF NOT EXISTS` 로 되살린다 — 두 번째 실행에서는 빈 테이블이
-- 생기고, 복제 INSERT 는 0행을 넣고, 재매핑 UPDATE 는 0행을 고치고, 마지막에 다시
-- 지워진다. 즉 **두 번째 실행은 아무 일도 하지 않는다.**
-- 나머지 문장은 MariaDB 의 `IF (NOT) EXISTS` 확장으로 전부 멱등하다.
--
-- ⚠️ MySQL 호스트에는 `ALTER TABLE … DROP FOREIGN KEY IF EXISTS` / `DROP COLUMN IF
--    EXISTS` 가 없다. 그 경우 IF EXISTS 를 지우고 **한 번만** 실행하거나,
--    information_schema 를 먼저 확인하는 래퍼를 쓸 것.
-- =============================================================================

-- 두 번째 실행을 위한 빈 껍데기. 첫 실행에서는 이미 있으므로 아무 일도 안 한다.
CREATE TABLE IF NOT EXISTS `wp_document_types` (
  `id`        INT NOT NULL AUTO_INCREMENT,
  `code`      VARCHAR(20)  NOT NULL,
  `name`      VARCHAR(255) NOT NULL,
  `phase_label`   VARCHAR(100) NULL,
  `gate_code`     VARCHAR(50)  NULL,
  `default_owner` VARCHAR(200) NULL,
  `status`    ENUM('NOT_STARTED','IN_PROGRESS','DONE','HOLD','NA') NOT NULL DEFAULT 'NOT_STARTED',
  `remark`    TEXT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpdt_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 1. wp_template_documents — 템플릿이 소유하는 문서
--
-- `source_document_type_id` 는 **이행 전용** 열이다. 링크를 재매핑할 짝을 찾는 데만
-- 쓰고 파일 끝에서 지운다. 이름으로 짝을 지으면 동명이인 문서에서 어긋난다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_template_documents` (
  `id`          INT NOT NULL AUTO_INCREMENT,
  `template_id` INT NOT NULL,
  `name`        VARCHAR(200) NOT NULL,
  `sort_order`  INT NOT NULL,
  `is_active`   TINYINT(1) NOT NULL DEFAULT 1,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wptd_template_sort` (`template_id`, `sort_order`),
  CONSTRAINT `fk_wptd_template`
    FOREIGN KEY (`template_id`) REFERENCES `wp_templates` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 이행 전용 열은 **CREATE 밖에서** 붙인다. 파일 끝에서 지우므로, 두 번째 실행에는
-- 테이블만 남고 열이 없다 — CREATE 안에 두면 그때 아래 INSERT 의 guard 가
-- `Unknown column` 으로 죽는다 (예행 연습에서 실제로 그랬다).
ALTER TABLE `wp_template_documents`
  ADD COLUMN IF NOT EXISTS `source_document_type_id` INT NULL;

-- 전역 문서를 **템플릿마다 한 벌씩** 복제한다.
INSERT INTO `wp_template_documents`
  (`template_id`, `name`, `sort_order`, `is_active`, `source_document_type_id`)
SELECT t.`id`, d.`name`, d.`sort_order`, d.`is_active`, d.`id`
FROM `wp_templates` t
CROSS JOIN `wp_document_types` d
WHERE NOT EXISTS (
  SELECT 1 FROM `wp_template_documents` x
  WHERE x.`template_id` = t.`id` AND x.`source_document_type_id` = d.`id`
);

-- 표시 번호는 1..N 연속이어야 한다 (§0.5.10). 전역 sort_order 가 어떤 값이었든
-- 템플릿 안에서 다시 촘촘하게 매긴다.
UPDATE `wp_template_documents` td
JOIN (
  SELECT `id`, ROW_NUMBER() OVER (PARTITION BY `template_id` ORDER BY `sort_order`, `id`) AS rn
  FROM `wp_template_documents`
) r ON r.`id` = td.`id`
SET td.`sort_order` = r.rn;


-- -----------------------------------------------------------------------------
-- 2. wp_item_documents — 전역 문서 → 템플릿 문서로 재매핑
--
-- 행 → 버전 → 템플릿 을 거슬러 올라가 그 템플릿의 사본을 찾는다.
-- -----------------------------------------------------------------------------
-- 두 번째 실행 대비: 구 열은 아래에서 지워지므로 없을 수 있다. 다시 붙여 두면
-- 재매핑 UPDATE 가 파싱되고, 이행할 데이터가 없으므로 0행을 고치고 끝난다.
ALTER TABLE `wp_item_documents`
  ADD COLUMN IF NOT EXISTS `document_type_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `template_document_id` INT NULL AFTER `item_id`;

UPDATE `wp_item_documents` link
JOIN `wp_items` i    ON i.`id` = link.`item_id`
JOIN `wp_versions` v ON v.`id` = i.`version_id`
JOIN `wp_template_documents` td
  ON td.`template_id` = v.`template_id`
 AND td.`source_document_type_id` = link.`document_type_id`
SET link.`template_document_id` = td.`id`
WHERE link.`template_document_id` IS NULL;

-- 짝을 못 찾은 링크가 있으면 여기서 죽는다 (NOT NULL 이 지켜 준다) — 조용히
-- 버리는 것보다 낫다.
-- 새 FK 도 함께 떨군다. 두 번째 실행에서는 이미 걸려 있고, 그 FK 가
-- `idx_wpid_doc` 를 쓰고 있어 인덱스를 못 지운다 (예행 연습에서 실제로 그랬다).
ALTER TABLE `wp_item_documents`
  DROP FOREIGN KEY IF EXISTS `fk_wpid_document_type`;
ALTER TABLE `wp_item_documents`
  DROP FOREIGN KEY IF EXISTS `fk_wpid_template_document`;
ALTER TABLE `wp_item_documents`
  DROP INDEX IF EXISTS `idx_wpid_doc`;
ALTER TABLE `wp_item_documents`
  MODIFY COLUMN `template_document_id` INT NOT NULL;
ALTER TABLE `wp_item_documents`
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (`item_id`, `template_document_id`);
ALTER TABLE `wp_item_documents`
  DROP COLUMN IF EXISTS `document_type_id`;
ALTER TABLE `wp_item_documents`
  ADD KEY IF NOT EXISTS `idx_wpid_doc` (`template_document_id`);
ALTER TABLE `wp_item_documents`
  ADD CONSTRAINT `fk_wpid_template_document`
    FOREIGN KEY (`template_document_id`) REFERENCES `wp_template_documents` (`id`)
    ON DELETE CASCADE;


-- -----------------------------------------------------------------------------
-- 3. wp_project_documents — 개편
--
-- 기존 행의 **사용 여부·링크·작성 상태를 그대로 보존**한다. 행이 없던 (프로젝트,
-- 문서) 조합은 기본값으로 채운다 — 그 조합도 지금까지는 "행 없음 = 기본값" 으로
-- 읽히고 있었으므로(§0.5-4 lazy 규칙), 이행 후에도 같은 것을 보아야 한다.
-- -----------------------------------------------------------------------------
-- 두 번째 실행 대비: 구 열은 아래에서 지워지므로 없을 수 있다. 다시 붙여 두면
-- 재매핑 UPDATE 가 파싱되고, 이행할 데이터가 없으므로 0행을 고치고 끝난다.
ALTER TABLE `wp_project_documents`
  ADD COLUMN IF NOT EXISTS `document_type_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `name` VARCHAR(200) NULL AFTER `project_id`,
  ADD COLUMN IF NOT EXISTS `sort_order` INT NULL AFTER `name`,
  ADD COLUMN IF NOT EXISTS `source_document_type_id` INT NULL;

-- 이미 있던 행: 이름·순서·출처를 채운다 (설정 컬럼은 건드리지 않는다).
UPDATE `wp_project_documents` pd
JOIN `wp_document_types` d ON d.`id` = pd.`document_type_id`
SET pd.`name` = d.`name`,
    pd.`sort_order` = d.`sort_order`,
    pd.`source_document_type_id` = d.`id`
WHERE pd.`name` IS NULL;

-- 없던 조합: 기본값으로 생성 (사용=1 · 링크 없음 · 작성 전).
INSERT INTO `wp_project_documents`
  (`project_id`, `document_type_id`, `name`, `sort_order`, `is_used`, `link_url`,
   `doc_status`, `source_document_type_id`)
SELECT p.`id`, d.`id`, d.`name`, d.`sort_order`, 1, NULL, 'NOT_WRITTEN', d.`id`
FROM `wp_projects` p
CROSS JOIN `wp_document_types` d
WHERE NOT EXISTS (
  SELECT 1 FROM `wp_project_documents` x
  WHERE x.`project_id` = p.`id` AND x.`document_type_id` = d.`id`
);

UPDATE `wp_project_documents` pd
JOIN (
  SELECT `id`, ROW_NUMBER() OVER (PARTITION BY `project_id` ORDER BY `sort_order`, `id`) AS rn
  FROM `wp_project_documents`
) r ON r.`id` = pd.`id`
SET pd.`sort_order` = r.rn;

ALTER TABLE `wp_project_documents`
  MODIFY COLUMN `name` VARCHAR(200) NOT NULL,
  MODIFY COLUMN `sort_order` INT NOT NULL;


-- -----------------------------------------------------------------------------
-- 4. wp_project_item_documents — 프로젝트 문서로 재매핑
-- -----------------------------------------------------------------------------
-- 두 번째 실행 대비: 구 열은 아래에서 지워지므로 없을 수 있다. 다시 붙여 두면
-- 재매핑 UPDATE 가 파싱되고, 이행할 데이터가 없으므로 0행을 고치고 끝난다.
ALTER TABLE `wp_project_item_documents`
  ADD COLUMN IF NOT EXISTS `document_type_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `project_document_id` INT NULL AFTER `item_id`;

UPDATE `wp_project_item_documents` link
JOIN `wp_project_items` pi ON pi.`id` = link.`item_id`
JOIN `wp_project_documents` pd
  ON pd.`project_id` = pi.`project_id`
 AND pd.`source_document_type_id` = link.`document_type_id`
SET link.`project_document_id` = pd.`id`
WHERE link.`project_document_id` IS NULL;

ALTER TABLE `wp_project_item_documents`
  DROP FOREIGN KEY IF EXISTS `fk_wppid_document_type`;
ALTER TABLE `wp_project_item_documents`
  DROP FOREIGN KEY IF EXISTS `fk_wppid_project_document`;
ALTER TABLE `wp_project_item_documents`
  DROP INDEX IF EXISTS `idx_wppid_doc`;
ALTER TABLE `wp_project_item_documents`
  MODIFY COLUMN `project_document_id` INT NOT NULL;
ALTER TABLE `wp_project_item_documents`
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (`item_id`, `project_document_id`);
ALTER TABLE `wp_project_item_documents`
  DROP COLUMN IF EXISTS `document_type_id`;
ALTER TABLE `wp_project_item_documents`
  ADD KEY IF NOT EXISTS `idx_wppid_doc` (`project_document_id`);
ALTER TABLE `wp_project_item_documents`
  ADD CONSTRAINT `fk_wppid_project_document`
    FOREIGN KEY (`project_document_id`) REFERENCES `wp_project_documents` (`id`)
    ON DELETE CASCADE;


-- -----------------------------------------------------------------------------
-- 5. 전역 문서 폐기 — 이행이 끝난 뒤에만
-- -----------------------------------------------------------------------------
ALTER TABLE `wp_project_documents`
  DROP FOREIGN KEY IF EXISTS `fk_wppd_document_type`;

-- ⚠️ **대체 인덱스를 먼저 만든다.** `uq_wppd_project_document(project_id,
--    document_type_id)` 는 `project_id` 가 선두 열이라 `fk_wppd_project` 가 그것을
--    쓰고 있다. 대체 없이 지우면 "needed in a foreign key constraint" 로 죽는다
--    (라이브 적용에서 실제로 여기서 멈췄다).
ALTER TABLE `wp_project_documents`
  ADD KEY IF NOT EXISTS `idx_wppd_project_sort` (`project_id`, `sort_order`);
ALTER TABLE `wp_project_documents`
  DROP INDEX IF EXISTS `uq_wppd_project_document`;
ALTER TABLE `wp_project_documents`
  DROP INDEX IF EXISTS `idx_wppd_document`;
ALTER TABLE `wp_project_documents`
  DROP COLUMN IF EXISTS `document_type_id`;

-- 이행 전용 열 정리.
ALTER TABLE `wp_template_documents` DROP COLUMN IF EXISTS `source_document_type_id`;
ALTER TABLE `wp_project_documents`  DROP COLUMN IF EXISTS `source_document_type_id`;

DROP TABLE IF EXISTS `wp_document_types`;


-- =============================================================================
-- 이행 검증 — 적용 **직후** 아래를 돌려 링크 수가 보존됐는지 확인한다.
-- 세 쿼리 모두 0 을 돌려주어야 한다.
--
--   -- (a) 템플릿 링크 중 짝을 못 찾은 것 (NOT NULL 때문에 실은 적용이 실패한다)
--   SELECT COUNT(*) FROM `wp_item_documents` WHERE `template_document_id` IS NULL;
--
--   -- (b) 프로젝트 링크 중 짝을 못 찾은 것
--   SELECT COUNT(*) FROM `wp_project_item_documents` WHERE `project_document_id` IS NULL;
--
--   -- (c) 스코프를 벗어난 링크 — 행의 템플릿과 문서의 템플릿이 다른 경우
--   SELECT COUNT(*) FROM `wp_item_documents` l
--     JOIN `wp_items` i ON i.`id` = l.`item_id`
--     JOIN `wp_versions` v ON v.`id` = i.`version_id`
--     JOIN `wp_template_documents` td ON td.`id` = l.`template_document_id`
--    WHERE td.`template_id` <> v.`template_id`;
--
-- 링크 **총수**는 적용 전후가 같아야 한다. 적용 전에 미리 세어 둘 것:
--   SELECT (SELECT COUNT(*) FROM `wp_item_documents`) AS template_links,
--          (SELECT COUNT(*) FROM `wp_project_item_documents`) AS project_links;
-- =============================================================================
