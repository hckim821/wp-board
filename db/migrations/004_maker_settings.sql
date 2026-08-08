-- =============================================================================
-- 004_maker_settings — 설비사별 우리 쪽 부가 상태 (plan.md §0.6-1)
--
-- **호스트의 설비사 테이블은 손댈 수 없다.** 이식 대상 호스트의 모델은
-- `makers(id, maker, maker_ko, maker_en, maker_alias)` 이고 컬럼을 더할 수 없다.
-- 그래서 "전체 현황에 이 설비사를 표시할까" 같은 우리 쪽 상태는 여기에 따로 둔다.
--
-- ⚠️ `maker_id` 에 **물리 FK 를 걸지 않는다** (INTEGRATION.md §2.1). 대상 테이블이
--    이 스키마에 없고 별도 DB 에 있을 수도 있어, 제약을 걸면 이식 DDL 이 실패한다.
--    `wp_projects.maker_id` 와 정확히 같은 규칙이다 — 인덱스(여기서는 UNIQUE)는
--    걸되 참조 무결성은 호스트 책임으로 남긴다.
--
-- **행이 없는 것이 정상 상태다.** 없으면 "active 프로젝트가 있으면 표시" 로 읽는다
-- (§0.6-1). 그래서 설정을 한 번도 만지지 않은 설치에서도 전체 현황이 비지 않고,
-- 그러면서 체크 한 번으로 양방향(강제 표시 / 강제 숨김) 제어가 된다. 행을 미리
-- 깔아 두면 그 두 성질 중 앞의 것을 잃는다.
--
-- `UNIQUE(maker_id)` 가 업서트의 정확성을 떠받친다 — 설비사 하나에 설정은 하나다.
--
-- 재실행 안전: `CREATE TABLE IF NOT EXISTS` (MySQL 에서도 동일하게 동작한다).
-- =============================================================================

CREATE TABLE IF NOT EXISTS `wp_maker_settings` (
  `id`               INT NOT NULL AUTO_INCREMENT,
  -- 호스트 설비사 테이블의 PK (논리적 참조). 물리 FK 없음.
  `maker_id`         INT NOT NULL,
  `show_in_overview` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpms_maker` (`maker_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
