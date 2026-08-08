# db/migrations

**번호순 평문 SQL 마이그레이션.** 호스트 프로젝트가 자기 러너로 적용한다.

## 왜 Alembic 이 아닌가

이 코드는 **이미 가동 중인 다른 FastAPI 프로젝트**에 이식된다. 그 프로젝트에는
이미 자기 마이그레이션 도구와 자기 버전 테이블이 있다. 우리 도구를 강요하는 것은
이 저장소가 피하려는 host coupling 그 자체다. 그래서 산출물은 **아무 러너로나
실행할 수 있는 평문 SQL** 이다.

## 신규 설치 vs 업그레이드

| 상황 | 쓸 것 |
|---|---|
| 빈 DB 에 처음 설치 | `db/schema.sql` **하나만** |
| 이미 적용된 DB 를 올림 | `db/migrations/` 를 번호순으로, 아직 적용 안 한 것부터 |

`db/schema.sql` 은 **설치 전용**이다. `CREATE TABLE IF NOT EXISTS` 를 쓰므로
기존 DB 에 다시 돌려도 **아무것도 바뀌지 않는다** — 컬럼이 추가되지 않는다.
업그레이드에 schema.sql 을 쓰면 조용히 실패한다.

`schema.sql` 은 항상 "001 부터 마지막 마이그레이션까지 전부 적용한 상태" 와
같아야 하며, `backend/tests/test_schema_migrations.py` 가 두 경로로 DB 를 만들어
`information_schema` 를 비교해 이를 강제한다.

## 규칙

- 파일명은 `NNN_snake_case.sql`. 번호는 재사용하지 않는다.
- 가능하면 재실행 안전하게 (`IF NOT EXISTS` 등). MariaDB 확장 문법을 쓸 때는
  MySQL 호스트를 위한 대안을 주석으로 남긴다.
- `CREATE DATABASE` / `USE` 를 넣지 않는다. 호스트가 자기 DB 를 선택한 상태에서
  실행한다.
- 컬럼을 추가하면 **같은 커밋에서** `db/schema.sql` 과 ORM 모델도 함께 고친다.
  셋이 어긋나면 위 테스트가 깨진다.

## 목록

| # | 파일 | 내용 |
|---|---|---|
| 001 | `001_initial.sql` | 최초 스키마 — plan.md §0 의 2계층 (전역 문서 1 + 템플릿 8 + 프로젝트 7, 총 16개 테이블) |
| 002 | `002_dash_label.sql` | `wp_items.dash_label` / `wp_project_items.dash_label` (VARCHAR(60) NULL) — 대시보드 카드 라벨, plan.md §0.5-1 |
| 003 | `003_project_documents.sql` | `wp_project_documents` 신규 — 프로젝트별 문서 사용 여부·링크·작성 상태, plan.md §0.5-4 |
| 004 | `004_maker_settings.sql` | `wp_maker_settings` 신규 — 설비사별 전체현황 표시 설정. `maker_id` 에 **물리 FK 없음**(호스트 테이블), plan.md §0.6-1 |
| 005 | `005_project_links.sql` | `wp_project_links` 신규 — 프로젝트 주요 링크(설명·URL·순서), plan.md §0.5.5 |
| 006 | `006_document_ownership.sql` | **문서 모델 개편** — 전역 `wp_document_types` 폐기, `wp_template_documents` 신설 + 프로젝트 복제, 링크 재매핑. **데이터 이행 포함**, plan.md §0.5.10 |

### 006 은 다른 마이그레이션과 다르다 — 데이터를 옮긴다

지금까지의 마이그레이션은 DDL 만 바꿨다. 006 은 **전역 문서를 각 템플릿·프로젝트로
복제하고 링크를 재매핑한 뒤에야** 원본을 지운다. 적용 직후 파일 끝 주석의 검증
쿼리 3종이 전부 0 인지, 링크 총수가 적용 전과 같은지 확인할 것.

재실행 안전성을 위해 파일 맨 위에서 `wp_document_types` 를 빈 껍데기로 되살린다 —
두 번째 실행은 0행을 복제하고 아무것도 바꾸지 않는다. 구 열(`document_type_id`)도
같은 이유로 `ADD COLUMN IF NOT EXISTS` 로 되살렸다가 다시 지운다.

### 재기준선 (2026-08-07)

`plan.md` §0 이 컨테이너의 이름과 소유 관계를 바꾸고(`wp_work_packages` →
`wp_templates`, `maker_id` 제거) 프로젝트 계층을 새로 들이면서, **001 을 새 스키마로
다시 쓰고 002(`wp_versions.phase_start_no`)를 접어 넣었다.** 이름 변경과 테이블
추가가 뒤섞인 거대한 003 을 만드는 대신 그렇게 한 이유는 하나다 — **아직 이 스키마를
채택한 호스트가 없다.** 올릴 기존 설치가 없는 마이그레이션에 복잡도를 지불할 이유가
없다.

이 판단은 그 전제에만 의존한다. 한 곳이라도 채택한 뒤에는 번호를 이어 붙이는 수밖에
없다.

## 개발용 적용

```bash
python db/migrate.py --apply-migrations      # iai-test 에 미적용분을 번호순 적용
python db/verify.py                          # 스키마 + 데이터 드리프트 검사
```
