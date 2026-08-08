-- =============================================================================
-- Work Package 웹 관리 시스템 — 운영 스키마 (MariaDB 11.2.2)
-- plan.md §0 (2계층) / §3.2 / INTEGRATION.md §2·§4 기준
--
-- 2계층 구조 (plan.md §0.1)
--   [기준 데이터]  wp_templates ─▶ wp_versions ─▶ wp_items
--                  + wp_phases / wp_milestones / wp_owners  (템플릿 스코프)
--                  버전 관리(DRAFT→PUBLISHED→ARCHIVED)는 **여기에만** 있다.
--   [프로젝트]     wp_projects ─▶ wp_project_items
--                  + wp_project_phases / _milestones / _owners  (프로젝트 로컬)
--                  버전 없음. 생성 시 템플릿 발행본을 통째로 복제한 스냅샷이며
--                  이후 자유 편집. 템플릿 재발행이 기존 프로젝트를 바꾸지 않는다.
--   문서는 §0.5.10 부터 템플릿이 소유하고 프로젝트가 복제한다 (전역 없음).
--
-- 이식(transplant) 시 주의
--   * 아래 CREATE DATABASE / USE 두 줄은 **개발용**이다. 호스트 스키마에 적용할
--     때는 두 줄을 제거하고 호스트 DB 위에서 CREATE TABLE 만 실행한다.
--   * 모든 테이블은 `wp_` 접두를 갖는다 → 호스트 테이블과 충돌하지 않는다.
--   * 호스트 테이블로 향하는 FOREIGN KEY 는 **하나도 없다.**
--     설비사(maker) 참조는 이제 `wp_projects.maker_id` **한 곳뿐**이며 논리적
--     참조다 (INTEGRATION.md §2.1). 템플릿에는 maker 개념이 없다 — 중앙 관리다.
--   * 개발 전용 설비사 스텁 wp_dev_makers 는 db/dev_seed.sql 에만 있다.
--     이 파일에는 **절대 포함하지 않는다.**
-- =============================================================================

-- [DEV ONLY — 이식 시 제거] ---------------------------------------------------
CREATE DATABASE IF NOT EXISTS `iai-test`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
USE `iai-test`;
-- [/DEV ONLY] -----------------------------------------------------------------


-- -----------------------------------------------------------------------------
-- 1. wp_templates — WP 템플릿 컨테이너
--
-- 이전 이름은 `wp_work_packages` 였고 `maker_id` 를 가졌다. plan.md §0 이
-- 시나리오를 정정하면서 **템플릿은 중앙 기준 데이터**가 되었다 — 설비사에 매이지
-- 않는다. 그래서 `maker_id` 를 뺐고, `code` 는 전역 유일이다.
-- 설비사별 인스턴스는 `wp_projects` 다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_templates` (
  `id`             INT           NOT NULL AUTO_INCREMENT,
  `code`           VARCHAR(50)   NOT NULL,
  `name`           VARCHAR(200)  NOT NULL,
  `description`    TEXT          NULL,
  -- Phase 표시번호 시작값 (원본 엑셀이 `Phase 0` 부터 시작)
  `phase_start_no` INT           NOT NULL DEFAULT 0,
  `is_active`      TINYINT(1)    NOT NULL DEFAULT 1,
  `created_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpt_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 2. wp_versions — 템플릿 버전 (DRAFT / PUBLISHED / ARCHIVED)
--
-- "템플릿 당 DRAFT 1개 / PUBLISHED 1개" 불변식은 plan.md §2.4 결정에 따라
-- 서비스 레이어(version_service) + 트랜잭션 락으로 보장한다.
-- MariaDB 에 부분 유니크 인덱스가 없어 DDL 로는 표현하지 못한다.
--
-- **프로젝트에는 이 테이블에 해당하는 것이 없다.** 프로젝트는 생성이 곧 확정이고
-- 이후 직접 편집한다 (plan.md §0.1).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_versions` (
  `id`                INT NOT NULL AUTO_INCREMENT,
  `template_id`       INT NOT NULL,
  `version_number`    INT NOT NULL,
  `status`            ENUM('DRAFT','PUBLISHED','ARCHIVED') NOT NULL DEFAULT 'DRAFT',
  -- deep copy 원본 버전
  `source_version_id` INT           NULL,
  -- 발행 시점의 `phase_start_no` 스냅샷 (plan.md §2.4 원칙).
  -- 발행된 버전의 표시 번호는 **이 값**에서 산출한다. 템플릿의 `phase_start_no` 를
  -- 나중에 바꿔도 이미 발행된 버전의 번호가 흔들리지 않아야 하기 때문이다.
  -- DRAFT 는 NULL 이며, 그동안은 템플릿의 현재 값을 따른다.
  `phase_start_no`    INT           NULL,
  `notes`             TEXT          NULL,
  `published_at`      DATETIME      NULL,
  `archived_at`       DATETIME      NULL,
  -- 인증/권한은 호스트 책임. 컬럼만 예약한다 (plan.md §7-3).
  `created_by`        VARCHAR(100)  NULL,
  `published_by`      VARCHAR(100)  NULL,
  `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpv_number` (`template_id`, `version_number`),
  KEY `idx_wpv_template_status` (`template_id`, `status`),
  CONSTRAINT `fk_wpv_template`
    FOREIGN KEY (`template_id`) REFERENCES `wp_templates` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wpv_source_version`
    FOREIGN KEY (`source_version_id`) REFERENCES `wp_versions` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 3. wp_phases — Phase 기준정보 (템플릿 스코프)
--
-- name 은 번호를 뺀 순수 이름이다. 표시 문자열은 `Phase {seq_no}. {name}` 으로
-- 조합한다 (plan.md §2.1).
-- seq_no 는 renumber_service 가 재계산해 반영하는 "기본 표시순서"이며,
-- 특정 버전을 조회할 때의 번호는 그 버전의 행 순서에서 파생한다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_phases` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `template_id` INT          NOT NULL,
  `name`        VARCHAR(200) NOT NULL,
  `seq_no`      INT          NOT NULL DEFAULT 0,
  `is_active`   TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpp_name` (`template_id`, `name`),
  KEY `idx_wpp_template_seq` (`template_id`, `seq_no`),
  CONSTRAINT `fk_wpp_template`
    FOREIGN KEY (`template_id`) REFERENCES `wp_templates` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 4. wp_milestones — Milestone 기준정보 (Phase 하위, 템플릿 스코프)
--
-- 표시번호 `1.2` 의 앞자리(major)는 **저장하지 않는다.** 소속 Phase 의 seq_no 에서
-- 파생한다 (plan.md §2.1). seq_no 는 뒷자리(minor)만 담는다.
-- template_id 는 조회 편의를 위한 비정규화 컬럼이다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_milestones` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `template_id` INT          NOT NULL,
  `phase_id`    INT          NOT NULL,
  `name`        VARCHAR(255) NOT NULL,
  `seq_no`      INT          NOT NULL DEFAULT 0,
  `is_active`   TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpm_name` (`phase_id`, `name`),
  KEY `idx_wpm_template` (`template_id`),
  KEY `idx_wpm_phase_seq` (`phase_id`, `seq_no`),
  CONSTRAINT `fk_wpm_template`
    FOREIGN KEY (`template_id`) REFERENCES `wp_templates` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wpm_phase`
    FOREIGN KEY (`phase_id`) REFERENCES `wp_phases` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 5. wp_owners — Owner 기준정보 (템플릿 스코프)
-- 원본 엑셀 `Owner` 컬럼의 `+` 구분 다중값을 정규화한 결과.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_owners` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `template_id` INT          NOT NULL,
  `name`        VARCHAR(200) NOT NULL,
  `sort_order`  INT          NOT NULL DEFAULT 0,
  `is_active`   TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpo_name` (`template_id`, `name`),
  KEY `idx_wpo_template_sort` (`template_id`, `sort_order`),
  CONSTRAINT `fk_wpo_template`
    FOREIGN KEY (`template_id`) REFERENCES `wp_templates` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 5b. wp_template_documents — 문서 (템플릿 스코프, plan.md §0.5.10)
--
-- 전 설비사 공통이라 호스트 문서 마스터와의 **가장 유력한 병합 지점**이다
-- (INTEGRATION.md §3). 애플리케이션 접근은 DocumentTypeRepository 한 곳으로
-- 격리되어 있으므로, 병합 시 교체 지점은 그 리포지토리와 아래 두 링크 테이블
-- (wp_item_documents / wp_project_item_documents) 의 FK 뿐이다.
--
-- **프로젝트 생성 시 복제하지 않는다.** 문서 기준정보는 전역이므로 프로젝트는
-- 템플릿과 같은 행을 그대로 가리킨다 (plan.md §0.1 표).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_template_documents` (
  `id`          INT NOT NULL AUTO_INCREMENT,
  `template_id` INT NOT NULL,
  `name`        VARCHAR(200) NOT NULL,
  -- 표시 번호. 1..N 연속을 apply 가 보장한다 (원문자 코드는 §0.5.10 에서 폐기).
  `sort_order`  INT NOT NULL,
  `is_active`   TINYINT(1) NOT NULL DEFAULT 1,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wptd_template_sort` (`template_id`, `sort_order`),
  CONSTRAINT `fk_wptd_template`
    FOREIGN KEY (`template_id`) REFERENCES `wp_templates` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =============================================================================
-- 계층 1 — 기준 데이터 (템플릿). 중앙 관리, 설비사 개념 없음.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 6. wp_items — 템플릿 버전의 행
--
-- phase_id / milestone_id 가 NULL 허용인 것은 **의도된 설계**다.
-- 임시저장(§2.5)은 검증 없이 화면 상태를 그대로 저장하고, 행 추가는 §0.2 에 따라
-- **항상 미배정(회색) 행을 만든다.** 발행 시 V1/V2 가 이를 막는다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_items` (
  `id`              INT NOT NULL AUTO_INCREMENT,
  `version_id`      INT NOT NULL,
  `sort_order`      INT NOT NULL,                 -- 표시 순서 = 엑셀 No 컬럼
  `phase_id`        INT NULL,
  `milestone_id`    INT NULL,
  `title`           TEXT NULL,                    -- Key Action Item
  `deliverable`     TEXT NULL,                    -- Deliverable (Check Point)
  -- 대시보드 카드에 실리는 key action 요약 단어 (plan.md §0.5-1).
  -- NULL 이 정상 상태다 — 화면이 dash_label → deliverable → title 앞부분 순으로 폴백한다.
  `dash_label`      VARCHAR(60) NULL,
  `gate_code`       VARCHAR(20) NULL,             -- 선택 입력, 발행 필수값 아님
  `status`          ENUM('NOT_STARTED','IN_PROGRESS','DONE','HOLD','NA') NOT NULL DEFAULT 'NOT_STARTED',
  `completion_date` DATE NULL,
  -- DRAFT 에서 신규 추가된 행 표시
  `origin`          ENUM('INHERITED','ADDED') NOT NULL DEFAULT 'INHERITED',
  `source_item_id`  INT NULL,                     -- deep copy 추적용 (물리 FK 없음: 원본 삭제와 무관하게 이력 보존)
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wpi_version_sort` (`version_id`, `sort_order`),
  KEY `idx_wpi_phase` (`phase_id`),
  KEY `idx_wpi_milestone` (`milestone_id`),
  CONSTRAINT `fk_wpi_version`
    FOREIGN KEY (`version_id`) REFERENCES `wp_versions` (`id`) ON DELETE CASCADE,
  -- RESTRICT: 사용 중인 기준정보의 hard delete 를 DB 레벨에서도 막는다 (plan.md §2.6)
  CONSTRAINT `fk_wpi_phase`
    FOREIGN KEY (`phase_id`) REFERENCES `wp_phases` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_wpi_milestone`
    FOREIGN KEY (`milestone_id`) REFERENCES `wp_milestones` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 7. wp_item_documents — 템플릿 행 ↔ 문서 (N:M)
-- 원본 엑셀 `관련 문서` 의 다중값을 정규화한 결과.
-- ⚠️ 그 컬럼은 `/` 로 분리하면 안 된다 — 문서명 `DSEP Readiness & I/O Spec` 자체에
--    `/` 가 들어 있어 깨진다. 원문자 마커(①~⑤)를 토큰 경계로 삼는다
--    (plan.md §1.1, db/migrate.py `parse_documents`).
-- 문서는 템플릿 스코프이므로 링크도 같은 템플릿 안에서만 성립한다 (§0.5.10).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_item_documents` (
  `item_id`          INT NOT NULL,
  `template_document_id` INT NOT NULL,
  `sort_order`       INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`item_id`, `template_document_id`),
  KEY `idx_wpid_doc` (`template_document_id`),
  CONSTRAINT `fk_wpid_item`
    FOREIGN KEY (`item_id`) REFERENCES `wp_items` (`id`) ON DELETE CASCADE,
  -- CASCADE: 문서를 지우면 링크도 함께 사라진다 (§0.5.10 삭제 캐스케이드)
  CONSTRAINT `fk_wpid_template_document`
    FOREIGN KEY (`template_document_id`) REFERENCES `wp_template_documents` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 8. wp_item_owners — 템플릿 행 ↔ Owner (N:M)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_item_owners` (
  `item_id`    INT NOT NULL,
  `owner_id`   INT NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`item_id`, `owner_id`),
  KEY `idx_wpio_owner` (`owner_id`),
  CONSTRAINT `fk_wpio_item`
    FOREIGN KEY (`item_id`) REFERENCES `wp_items` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wpio_owner`
    FOREIGN KEY (`owner_id`) REFERENCES `wp_owners` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =============================================================================
-- 계층 2 — 프로젝트 (설비사별). 버전 없음, 생성 시 스냅샷, 이후 자유 편집.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 9. wp_projects — 프로젝트 컨테이너
--
-- **호스트 설비사 참조는 이 테이블의 `maker_id` 하나뿐이다** (INTEGRATION.md §2.1).
-- 논리적 참조이며 물리 FK 를 걸지 않는다. 호스트가 BIGINT/UUID 를 쓴다면
-- **이 컬럼 하나만** 바꾸면 되도록 다른 테이블에 maker_id 가정을 퍼뜨리지 않았다.
--
-- source_template_id / source_version_id 에 물리 FK 를 걸지 않는 이유는
-- wp_items.source_item_id 와 같다 — **원본이 사라져도 출처 이력은 남아야** 한다.
-- 프로젝트는 스냅샷이므로 원본 삭제가 내용에 영향을 주지 않는다.
--
-- phase_start_no 는 생성 시점의 스냅샷이다 (plan.md §0.1). 템플릿 값이 나중에
-- 바뀌어도 이미 만들어진 프로젝트의 표시 번호는 흔들리지 않는다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_projects` (
  `id`                 INT           NOT NULL AUTO_INCREMENT,
  `maker_id`           INT           NOT NULL,
  `name`               VARCHAR(200)  NOT NULL,
  `description`        TEXT          NULL,
  `source_template_id` INT           NULL,
  `source_version_id`  INT           NULL,
  `phase_start_no`     INT           NOT NULL DEFAULT 0,
  `is_active`          TINYINT(1)    NOT NULL DEFAULT 1,
  `created_by`         VARCHAR(100)  NULL,
  `created_at`         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wppj_maker` (`maker_id`),
  KEY `idx_wppj_source` (`source_template_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 10. wp_project_phases — Phase (프로젝트 로컬 사본)
--
-- 템플릿의 wp_phases 와 같은 모양이되 스코프가 프로젝트다. 여기를 고쳐도
-- 템플릿에 영향이 없고, 템플릿이 재발행되어도 여기가 바뀌지 않는다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_phases` (
  `id`              INT          NOT NULL AUTO_INCREMENT,
  `project_id`      INT          NOT NULL,
  `name`            VARCHAR(200) NOT NULL,
  `seq_no`          INT          NOT NULL DEFAULT 0,
  `is_active`       TINYINT(1)   NOT NULL DEFAULT 1,
  `source_phase_id` INT          NULL,            -- 복제 추적용 (물리 FK 없음)
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wppp_name` (`project_id`, `name`),
  KEY `idx_wppp_project_seq` (`project_id`, `seq_no`),
  CONSTRAINT `fk_wppp_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 11. wp_project_milestones — Milestone (프로젝트 로컬 사본)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_milestones` (
  `id`                  INT          NOT NULL AUTO_INCREMENT,
  `project_id`          INT          NOT NULL,
  `phase_id`            INT          NOT NULL,
  `name`                VARCHAR(255) NOT NULL,
  `seq_no`              INT          NOT NULL DEFAULT 0,
  `is_active`           TINYINT(1)   NOT NULL DEFAULT 1,
  `source_milestone_id` INT          NULL,
  `created_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wppm_name` (`phase_id`, `name`),
  KEY `idx_wppm_project` (`project_id`),
  KEY `idx_wppm_phase_seq` (`phase_id`, `seq_no`),
  CONSTRAINT `fk_wppm_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wppm_phase`
    FOREIGN KEY (`phase_id`) REFERENCES `wp_project_phases` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 12. wp_project_owners — Owner (프로젝트 로컬 사본)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_owners` (
  `id`              INT          NOT NULL AUTO_INCREMENT,
  `project_id`      INT          NOT NULL,
  `name`            VARCHAR(200) NOT NULL,
  `sort_order`      INT          NOT NULL DEFAULT 0,
  `is_active`       TINYINT(1)   NOT NULL DEFAULT 1,
  `source_owner_id` INT          NULL,
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wppo_name` (`project_id`, `name`),
  KEY `idx_wppo_project_sort` (`project_id`, `sort_order`),
  CONSTRAINT `fk_wppo_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 13. wp_project_items — 프로젝트의 행
--
-- wp_items 와 같은 모양이며, 다른 점은 스코프가 버전이 아니라 **프로젝트**라는
-- 것뿐이다. 그래서 그리드 동작(재계산 §2.2, 경계 §2.3, 회색 행 §0.2)이 양쪽에서
-- 똑같이 성립하고, 백엔드도 같은 순수 서비스를 공유한다.
--
-- Status / 완료일이 실제로 쓰이는 곳이 여기다 (plan.md §0.1) — 실행 정보는
-- 템플릿이 아니라 프로젝트에 쌓인다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_items` (
  `id`              INT NOT NULL AUTO_INCREMENT,
  `project_id`      INT NOT NULL,
  `sort_order`      INT NOT NULL,
  `phase_id`        INT NULL,
  `milestone_id`    INT NULL,
  `title`           TEXT NULL,
  `deliverable`     TEXT NULL,
  -- plan.md §0.5-1. 프로젝트 생성(deep copy)이 템플릿의 값을 그대로 가져온다.
  `dash_label`      VARCHAR(60) NULL,
  `gate_code`       VARCHAR(20) NULL,
  `status`          ENUM('NOT_STARTED','IN_PROGRESS','DONE','HOLD','NA') NOT NULL DEFAULT 'NOT_STARTED',
  `completion_date` DATE NULL,
  `origin`          ENUM('INHERITED','ADDED') NOT NULL DEFAULT 'INHERITED',
  `source_item_id`  INT NULL,
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wppi_project_sort` (`project_id`, `sort_order`),
  KEY `idx_wppi_phase` (`phase_id`),
  KEY `idx_wppi_milestone` (`milestone_id`),
  CONSTRAINT `fk_wppi_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wppi_phase`
    FOREIGN KEY (`phase_id`) REFERENCES `wp_project_phases` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_wppi_milestone`
    FOREIGN KEY (`milestone_id`) REFERENCES `wp_project_milestones` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 13b. wp_project_documents — 프로젝트 문서 (plan.md §0.5.10)
--
-- **문서 그 자체다** (§0.5.10 개편). 프로젝트 생성 시 템플릿 문서에서 복제되고,
-- 이후 이름 변경·행 추가·삭제가 자유롭다. 예전의 "행이 없으면 기본값" lazy 규칙은
-- 문서가 복제 대상이 되면서 사라졌다 — **있는 행이 전부다.**
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_documents` (
  `id`               INT NOT NULL AUTO_INCREMENT,
  `project_id`       INT NOT NULL,
  `name`             VARCHAR(200) NOT NULL,
  -- 표시 번호 (1..N). 저장이 배열 순서로 재부여한다.
  `sort_order`       INT NOT NULL,
  `is_used`          TINYINT(1)   NOT NULL DEFAULT 1,
  -- 작성 상태와 무관하게 NULL 허용 (§0.5-4)
  `link_url`         VARCHAR(500) NULL,
  `doc_status`       ENUM('NOT_WRITTEN','WRITING','DONE') NOT NULL DEFAULT 'NOT_WRITTEN',
  `created_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wppd_project_sort` (`project_id`, `sort_order`),
  CONSTRAINT `fk_wppd_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 14. wp_project_item_documents — 프로젝트 행 ↔ 문서 (N:M)
--
-- **프로젝트 로컬 문서를 가리킨다** (§0.5.10). 문서가 포맷 종속이 되면서 프로젝트도
-- 자기 사본을 갖는다 — Owner/Phase 와 같은 규칙이다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_item_documents` (
  `item_id`          INT NOT NULL,
  `project_document_id` INT NOT NULL,
  `sort_order`       INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`item_id`, `project_document_id`),
  KEY `idx_wppid_doc` (`project_document_id`),
  CONSTRAINT `fk_wppid_item`
    FOREIGN KEY (`item_id`) REFERENCES `wp_project_items` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wppid_project_document`
    FOREIGN KEY (`project_document_id`) REFERENCES `wp_project_documents` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 15. wp_project_item_owners — 프로젝트 행 ↔ Owner (N:M, 프로젝트 로컬 Owner)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_item_owners` (
  `item_id`    INT NOT NULL,
  `owner_id`   INT NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`item_id`, `owner_id`),
  KEY `idx_wppio_owner` (`owner_id`),
  CONSTRAINT `fk_wppio_item`
    FOREIGN KEY (`item_id`) REFERENCES `wp_project_items` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wppio_owner`
    FOREIGN KEY (`owner_id`) REFERENCES `wp_project_owners` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 17. wp_project_links — 프로젝트 주요 링크 (plan.md §0.5.5)
--
-- Confluence 페이지·클라우드 파일 등 프로젝트가 자유롭게 늘리고 줄이는 링크 목록.
-- `wp_project_documents`(16) 와 다른 것이다 — 그쪽은 전역 문서 마스터에 매인
-- 정해진 집합이고, 이쪽은 문서 마스터와 무관한 자유 목록이다.
--
-- `sort_order` 는 화면의 drag 순서다. 저장이 배열 순서를 정본으로 삼는 전량
-- 교체이므로 서버가 다시 매긴다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_project_links` (
  `id`          INT NOT NULL AUTO_INCREMENT,
  `project_id`  INT NOT NULL,
  `sort_order`  INT NOT NULL,
  `description` VARCHAR(200)  NOT NULL,
  -- http:// · https:// 만 허용. 검증은 API 계층에서 (오류 위치를 함께 돌려주려고).
  `url`         VARCHAR(1000) NOT NULL,
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wppl_project_sort` (`project_id`, `sort_order`),
  CONSTRAINT `fk_wppl_project`
    FOREIGN KEY (`project_id`) REFERENCES `wp_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 18. wp_maker_settings — 설비사별 우리 쪽 부가 상태 (plan.md §0.6-1)
--
-- 호스트의 설비사 테이블(`makers`)은 손댈 수 없다 — 컬럼을 더할 수 없으므로,
-- "전체 현황에 표시할까" 같은 우리 쪽 상태를 여기에 따로 둔다.
--
-- ⚠️ `maker_id` 에 **물리 FK 를 걸지 않는다** (INTEGRATION.md §2.1). 대상 테이블이
--    이 스키마에 없을 수 있어 제약을 걸면 이식 DDL 이 실패한다.
--
-- **행이 없는 것이 정상이다.** 없으면 "active 프로젝트가 있으면 표시" 로 읽는다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wp_maker_settings` (
  `id`               INT NOT NULL AUTO_INCREMENT,
  `maker_id`         INT NOT NULL,
  `show_in_overview` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wpms_maker` (`maker_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
