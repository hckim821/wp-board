-- =============================================================================
-- 002_dash_label — 대시보드 카드 라벨 (plan.md §0.5-1)
--
-- 대시보드 카드에는 `title`(Key Action Item) 전문이 아니라 **key action 요약
-- 단어**가 실린다. 카드 폭이 좁아 장문 제목은 그대로 쓸 수 없고, 요약을
-- 클라이언트가 잘라 만들면 사람마다 다른 문구가 나온다. 그래서 편집 가능한
-- 별도 컬럼으로 둔다.
--
-- 표시 폴백은 서버가 아니라 화면이 정한다 (§0.5-1):
--   dash_label → deliverable → title 앞부분
-- 그래서 이 컬럼은 NULL 이 정상 상태이며, 빈 행/신규 행은 NULL 로 태어난다.
--
-- 두 계층 모두에 붙인다. 프로젝트는 템플릿의 스냅샷이므로 한쪽만 두면
-- deep copy 에서 값이 증발한다.
--
-- ⚠️ MariaDB 확장 문법 `ADD COLUMN IF NOT EXISTS` 를 쓴다 (재실행 안전성 —
--    db/migrations/README.md). MySQL 호스트에서는 지원되지 않으므로, 그쪽에서는
--    IF NOT EXISTS 를 지우고 한 번만 실행하거나 information_schema 를 먼저
--    확인하는 래퍼를 쓸 것:
--      ALTER TABLE `wp_items`         ADD COLUMN `dash_label` VARCHAR(60) NULL AFTER `deliverable`;
--      ALTER TABLE `wp_project_items` ADD COLUMN `dash_label` VARCHAR(60) NULL AFTER `deliverable`;
-- =============================================================================

ALTER TABLE `wp_items`
  ADD COLUMN IF NOT EXISTS `dash_label` VARCHAR(60) NULL AFTER `deliverable`;

ALTER TABLE `wp_project_items`
  ADD COLUMN IF NOT EXISTS `dash_label` VARCHAR(60) NULL AFTER `deliverable`;
