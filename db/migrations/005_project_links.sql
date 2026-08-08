-- =============================================================================
-- 005_project_links — 프로젝트 주요 링크 (plan.md §0.5.5)
--
-- 프로젝트마다 관련 Confluence 페이지·클라우드 파일 등 외부 링크를 순서대로
-- 보관한다. `wp_project_documents`(§0.5-4) 와 **다른 것**이다 — 그쪽은 전역 문서
-- 마스터에 매인 정해진 다섯 건의 링크·상태이고, 이쪽은 프로젝트가 자유롭게
-- 늘리고 줄이는 목록이다. 그래서 문서 마스터로의 FK 도, 고정된 행 집합도 없다.
--
-- `sort_order` 가 있는 이유: 화면이 관리형 row drag 로 순서를 바꾸고, 그 순서가
-- 곧 표시 순서다. 저장은 배열 순서를 정본으로 삼는 전량 교체이므로 이 값은
-- 서버가 다시 매긴다 (`wp_items.sort_order` 와 같은 태도 — 클라이언트가 보낸
-- 번호를 그대로 믿지 않는다).
--
-- 스코프가 프로젝트 하나뿐이라 `wp_projects` 로의 CASCADE FK 를 건다. 호스트
-- 테이블을 가리키지 않으므로 이식 DDL 에 문제가 없다.
--
-- 재실행 안전: `CREATE TABLE IF NOT EXISTS` (MySQL 에서도 동일하게 동작한다).
-- =============================================================================

CREATE TABLE IF NOT EXISTS `wp_project_links` (
  `id`          INT NOT NULL AUTO_INCREMENT,
  `project_id`  INT NOT NULL,
  `sort_order`  INT NOT NULL,
  `description` VARCHAR(200)  NOT NULL,
  -- 인터넷 주소만 허용한다 (http:// · https://). 검증은 API 계층에서 하며
  -- DB CHECK 를 걸지 않는 이유는 오류 위치(필드·행)를 함께 돌려주기 위해서다.
  `url`         VARCHAR(1000) NOT NULL,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wppl_project_sort` (`project_id`, `sort_order`),
  CONSTRAINT `fk_wppl_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
