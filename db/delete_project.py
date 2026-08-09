"""프로젝트 **완전 삭제** — 관리자 전용 수동 스크립트.

UI 에는 이 동작이 없다. 설비사 관리 화면의 프로젝트 스위치는
`wp_projects.is_active` 만 끄고 (전체 현황에서 감춰질 뿐 행은 그대로 남는다),
데이터베이스에서 실제로 지우는 경로는 이 파일 하나뿐이다.

**되돌릴 수 없다.** 항목·상태·완료일·문서·링크가 전부 사라지며 백업이 없으면
복구 수단이 없다. 그래서 API 로 열지 않았다 — 잘못 누른 버튼 하나로 실행 이력이
통째로 없어지는 일을 막는 가장 확실한 방법은 그 버튼을 만들지 않는 것이다.

사용법::

    python db/delete_project.py 12                 # 12번 프로젝트 삭제 (확인 프롬프트)
    python db/delete_project.py 12 13 14           # 여러 개
    python db/delete_project.py 12 --dry-run       # 지워질 건수만 세고 아무것도 안 함
    python db/delete_project.py 12 --yes           # 확인 프롬프트 생략 (배치용)
    python db/delete_project.py 12 --report r.json # 삭제 대상 상세를 UTF-8 JSON 으로

접속 정보는 **환경변수**로 받는다. 저장소에 비밀번호를 두지 않기 위해서다::

    WP_DB_HOST      기본 localhost
    WP_DB_PORT      기본 3306
    WP_DB_USER      기본 user01
    WP_DB_PASSWORD  **필수** — 없으면 실행을 거부한다
    WP_DB_NAME      기본 iai-test   (하이픈 때문에 raw SQL 에서는 항상 백틱)

값은 `backend/.env` 에서 읽는다 (`backend/.env.example` 참고). 셸에 이미 설정된
환경변수가 항상 우선하므로, 한 번만 다른 DB 를 겨누고 싶으면 이렇게 덮어쓴다::

    $env:WP_DB_NAME = 'iai-staging'; python db/delete_project.py 12

## 왜 CASCADE 에 맡기지 않는가

`wp_projects` 를 지우면 자식들이 `ON DELETE CASCADE` 로 따라오지만, 그 중
`wp_project_items` 는 `wp_project_phases` / `wp_project_milestones` 를
**`ON DELETE RESTRICT`** 로 참조하고 `wp_project_item_owners` 는
`wp_project_owners` 를 같은 방식으로 참조한다 (`db/schema.sql` 13·15).
캐스케이드 전파 순서가 그 제약을 먼저 건드리면 삭제 전체가 FK 오류로 실패한다.
그래서 **FK 역순으로 직접** 지운다 — 순서를 우리가 정하면 실패할 여지가 없고,
표별 건수를 세어 보고할 수 있다는 부수 효과도 얻는다.

## cp949 콘솔

프로젝트명은 한글이라 Windows 콘솔에 그대로 찍으면 깨진다 (CLAUDE.md). stdout 에는
id 와 건수만 내보내고, 이름이 필요하면 ``--report`` 로 UTF-8 JSON 을 받는다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

import pymysql

# `backend/.env` (`backend/.env.example` 참고) — 접속 정보 파일은 저장소에 하나다.
# 아래 상수를 읽기 **전에** 올려야 한다. python-dotenv 가 없으면 건너뛰고 셸
# 환경변수만 쓴다. 기존 환경변수는 덮어쓰지 않는다.
try:  # pragma: no cover - 설치 여부에 따른 분기
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")
except ImportError:  # pragma: no cover
    pass

# --- 접속 정보 (환경변수) -------------------------------------------------------
DB_HOST = os.environ.get("WP_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("WP_DB_PORT", "3306"))
DB_USER = os.environ.get("WP_DB_USER", "user01")
DB_NAME = os.environ.get("WP_DB_NAME", "iai-test")

#: 삭제 순서 — **FK 역순**. `(테이블, WHERE 절)` 이며 `%s` 하나에 project_id 가 들어간다.
#:
#: 위 두 줄이 서브쿼리인 이유: 행↔Owner / 행↔문서 연결표에는 `project_id` 가 없다.
#: 프로젝트를 아는 것은 `wp_project_items` 뿐이므로 거기를 거쳐 고른다.
DELETE_ORDER: list[tuple[str, str]] = [
    (
        "wp_project_item_owners",
        "item_id IN (SELECT id FROM `wp_project_items` WHERE project_id = %s)",
    ),
    (
        "wp_project_item_documents",
        "item_id IN (SELECT id FROM `wp_project_items` WHERE project_id = %s)",
    ),
    ("wp_project_items", "project_id = %s"),
    ("wp_project_owners", "project_id = %s"),
    ("wp_project_documents", "project_id = %s"),
    ("wp_project_links", "project_id = %s"),
    ("wp_project_milestones", "project_id = %s"),
    ("wp_project_phases", "project_id = %s"),
    ("wp_projects", "id = %s"),
]


def connect() -> pymysql.connections.Connection:
    """접속. 비밀번호는 환경변수에서만 받는다 — 기본값을 두지 않는다."""
    password = os.environ.get("WP_DB_PASSWORD")
    if not password:
        sys.exit(
            "WP_DB_PASSWORD 환경변수가 필요합니다.\n"
            "  PowerShell: $env:WP_DB_PASSWORD = 'xxxx'\n"
            "  bash      : export WP_DB_PASSWORD=xxxx"
        )
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=password,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )


def safe(text: str) -> str:
    """cp949 콘솔에서도 죽지 않는 표현. 깨질 글자는 이스케이프로 남긴다."""
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, "backslashreplace").decode(encoding, "replace")


def survey(cursor, project_id: int) -> dict | None:
    """지워질 것을 **미리 센다.** 없는 프로젝트면 `None`."""
    cursor.execute(
        "SELECT id, maker_id, name, is_active FROM `wp_projects` WHERE id = %s",
        (project_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    counts: dict[str, int] = {}
    for table, where in DELETE_ORDER:
        cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE {where}", (project_id,))
        counts[table] = cursor.fetchone()[0]

    return {
        "id": row[0],
        "maker_id": row[1],
        "name": row[2],
        "is_active": bool(row[3]),
        "counts": counts,
        "total_rows": sum(counts.values()),
    }


def delete(cursor, project_id: int) -> dict[str, int]:
    """FK 역순 삭제. 커밋은 호출자가 한다 — 여러 프로젝트를 한 트랜잭션으로 묶는다."""
    deleted: dict[str, int] = {}
    for table, where in DELETE_ORDER:
        cursor.execute(f"DELETE FROM `{table}` WHERE {where}", (project_id,))
        deleted[table] = cursor.rowcount
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="프로젝트를 데이터베이스에서 완전히 삭제한다 (되돌릴 수 없음).",
    )
    parser.add_argument("project_ids", nargs="+", type=int, help="wp_projects.id")
    parser.add_argument(
        "--dry-run", action="store_true", help="건수만 세고 아무것도 지우지 않는다"
    )
    parser.add_argument("--yes", action="store_true", help="확인 프롬프트를 생략한다")
    parser.add_argument("--report", metavar="PATH", help="삭제 대상 상세를 UTF-8 JSON 으로 기록")
    args = parser.parse_args()

    # 같은 id 를 두 번 받으면 두 번째는 "없는 프로젝트" 로 보여 혼란만 준다.
    project_ids = list(dict.fromkeys(args.project_ids))

    connection = connect()
    try:
        with connection.cursor() as cursor:
            surveys = [(pid, survey(cursor, pid)) for pid in project_ids]

        missing = [pid for pid, found in surveys if found is None]
        found = [entry for _, entry in surveys if entry is not None]

        for pid in missing:
            print(f"  [건너뜀] project_id={pid} — 그런 프로젝트가 없습니다.")
        for entry in found:
            state = "사용" if entry["is_active"] else "미사용"
            print(
                f"  [대상  ] project_id={entry['id']} maker_id={entry['maker_id']} "
                f"({state}) name={safe(entry['name'])}"
            )
            for table, count in entry["counts"].items():
                if count:
                    print(f"             {table:<28} {count:>6}")
            print(f"             {'합계':<28} {entry['total_rows']:>6}")

        if args.report:
            with io.open(args.report, "w", encoding="utf-8") as handle:
                json.dump(
                    {"missing": missing, "targets": found}, handle, ensure_ascii=False, indent=1
                )
            print(f"  보고서: {args.report}")

        if not found:
            print("지울 것이 없습니다.")
            return 1 if missing else 0

        if args.dry_run:
            print("--dry-run 이므로 아무것도 지우지 않았습니다.")
            return 0

        if not args.yes:
            # 되돌릴 수 없는 조작이므로 id 를 **다시 입력**받는다. y/N 는 습관적으로
            # 눌리지만, 지울 id 를 직접 쓰는 것은 손이 먼저 움직이지 않는다.
            expected = ",".join(str(entry["id"]) for entry in found)
            print(
                "\n되돌릴 수 없습니다. 진행하려면 삭제할 id 를 그대로 입력하세요 "
                f"(예: {expected})"
            )
            try:
                answer = input("> ").strip().replace(" ", "")
            except EOFError:
                print("입력을 받을 수 없습니다. 배치 실행이라면 --yes 를 쓰세요.")
                return 1
            if answer != expected:
                print("입력이 일치하지 않아 취소했습니다.")
                return 1

        with connection.cursor() as cursor:
            total = 0
            for entry in found:
                deleted = delete(cursor, entry["id"])
                total += sum(deleted.values())
                print(f"  [삭제  ] project_id={entry['id']} — {sum(deleted.values())} 행")
        connection.commit()
        print(f"완료. {len(found)}개 프로젝트, 총 {total} 행을 삭제했습니다.")
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
