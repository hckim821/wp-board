-- =============================================================================
-- 003_project_documents — 프로젝트별 문서 링크·상태 (plan.md §0.5-4)
--
-- 전역 `wp_document_types` 는 문서의 **정의**(코드·이름)만 갖는다. 그 문서를
-- 프로젝트에서 쓰는지, 클라우드 링크가 어디인지, 작성이 어디까지 됐는지는
-- 프로젝트마다 다르므로 여기에 따로 둔다.
--
-- **행이 없는 것이 정상이다.** 없으면 기본값(사용=1 · 작성전 · 링크 없음)으로
-- 읽는다. 그래서 기존 프로젝트를 위한 데이터 백필이 필요 없다 — 사용자가 그
-- 프로젝트의 문서 설정을 처음 저장할 때 행이 생긴다(lazy upsert).
--
-- `UNIQUE(project_id, document_type_id)` 이 그 lazy upsert 의 정확성을 떠받친다.
-- 없으면 저장을 두 번 눌렀을 때 같은 문서가 두 줄이 되고, 어느 줄이 정본인지
-- 알 수 없게 된다.
--
-- ⚠️ `document_type_id` 는 전역 문서 마스터를 가리키는 **세 번째** FK 다
--    (`wp_item_documents`, `wp_project_item_documents` 에 이어). 호스트 문서
--    마스터로 병합할 때 재지정할 곳이 셋이라는 뜻이다 — INTEGRATION.md §4.
--
-- 재실행 안전: `CREATE TABLE IF NOT EXISTS` (MySQL 에서도 동일하게 동작한다).
-- =============================================================================

CREATE TABLE IF NOT EXISTS `wp_project_documents` (
  `id`               INT NOT NULL AUTO_INCREMENT,
  `project_id`       INT NOT NULL,
  `document_type_id` INT NOT NULL,
  -- 이 프로젝트에서 이 문서를 쓰는가. 기본 1 — 안 쓰는 것이 예외다.
  `is_used`          TINYINT(1)   NOT NULL DEFAULT 1,
  -- 클라우드 문서 링크. **작성 상태와 무관하게 NULL 이 허용된다** (§0.5-4).
  `link_url`         VARCHAR(500) NULL,
  `doc_status`       ENUM('NOT_WRITTEN','WRITING','DONE') NOT NULL DEFAULT 'NOT_WRITTEN',
  `created_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wppd_project_document` (`project_id`, `document_type_id`),
  KEY `idx_wppd_document` (`document_type_id`),
  CONSTRAINT `fk_wppd_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE,
  -- RESTRICT: 쓰이고 있는 전역 문서의 hard delete 를 DB 레벨에서도 막는다.
  CONSTRAINT `fk_wppd_document_type`
    FOREIGN KEY (`document_type_id`) REFERENCES `wp_document_types` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
