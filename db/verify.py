"""`iai-test` 가 엑셀 원본과 일치하는지 검사한다.

**왜 필요한가.** `iai-test` 는 사용자가 직접 들여다볼 **산출물**인데, 동시에
`backend/app/standalone.py` 가 바라보는 개발 DB 이기도 하다. 그래서 누구든
개발 서버에 붙어 행을 만들거나 Phase 를 추가하면 그 흔적이 산출물에 남는다.
실제로 그런 일이 있었다 — 통합 확인용으로 만든 Phase 하나가 `seq_no` 0 을
차지하는 바람에 실제 Phase 4개가 전부 1칸씩 밀렸다.

"확인했다" 를 **말이 아니라 명령의 출력**으로 만들기 위한 스크립트다.

사용법::

    python db/verify.py             # 검사만. 드리프트가 있으면 exit 1
    python db/verify.py --repair    # 고아 기준정보 제거 + seq_no 재계산 후 재검사

`--repair` 가 고치는 범위는 **행을 잃지 않는 것들뿐**이다.
  * 어떤 행도 참조하지 않는 Phase/Milestone 삭제 (기준정보 잔재)
  * `seq_no` 를 v1 PUBLISHED 의 행 순서에서 다시 유도

행 자체가 어긋났다면(35행이 아니거나 내용이 다르면) 고치지 않고 보고만 한다.
그건 재적재(`db/migrate.py`) 판단이 필요한 상황이고, 재적재는 id 가 바뀐다.

한글은 콘솔(cp949)에서 깨지므로 요약만 ASCII 로 출력하고, 상세 내역은
`db/_verify_report.json` 에 UTF-8 로 쓴다.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from pathlib import Path

import pymysql

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "db" / "_verify_report.json"


def _load_migrate():
    spec = importlib.util.spec_from_file_location("wp_migrate", REPO_ROOT / "db" / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migrate = _load_migrate()


def connect():
    return pymysql.connect(
        host=migrate.DB_HOST,
        port=migrate.DB_PORT,
        user=migrate.DB_USER,
        password=migrate.DB_PASSWORD,
        database=migrate.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )


def check_schema(cur) -> list[dict]:
    """**스키마 드리프트** — ORM 이 기대하는 테이블/컬럼이 실제로 있는가.

    이게 없어서 사고가 났다. `wp_versions.phase_start_no` 를 모델과 `schema.sql`
    에만 추가하고 live DB 에 반영하지 않은 적이 있는데, 테스트 스위트는
    **매번 schema.sql 로 새 DB 를 만들기 때문에** 그 어긋남을 구조적으로 볼 수
    없었다. 데이터 검사(`check`)도 컬럼 존재는 보지 않는다.

    호스트 DB 가 추가로 갖고 있는 컬럼은 문제 삼지 않는다 — 호스트의 자유다.
    우리가 기대하는 것이 **없는** 경우만 드리프트다.
    """
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.models import Base  # noqa: E402  (경로 설정 후 import)

    problems: list[dict] = []

    cur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s",
        (migrate.DB_NAME,),
    )
    live: dict[str, set[str]] = {}
    for table, column in cur.fetchall():
        live.setdefault(table, set()).add(column)

    for table_name, table in Base.metadata.tables.items():
        if table_name not in live:
            problems.append({"kind": "missing_table", "table": table_name})
            continue
        missing = [c.name for c in table.columns if c.name not in live[table_name]]
        if missing:
            problems.append(
                {
                    "kind": "missing_column",
                    "table": table_name,
                    "columns": missing,
                    "hint": "db/migrations/ 를 적용했는지 확인 "
                            "(python db/migrate.py --apply-migrations)",
                }
            )
    return problems


def check(cur, book) -> list[dict]:
    """엑셀 원본과 DB 를 대조해 드리프트 목록을 돌려준다."""
    problems: list[dict] = []

    def bad(kind: str, **detail):
        problems.append({"kind": kind, **detail})

    # --- 템플릿 / 버전 ------------------------------------------------------
    #
    # 대조 대상은 **템플릿**이다 (plan.md §0.1). 프로젝트는 사용자가 만드는
    # 사본이므로 개수도 내용도 엑셀과 대조할 대상이 아니다 — 여기서 세면
    # 데모 프로젝트 하나만 있어도 드리프트로 오인된다.
    cur.execute("SELECT id, code, phase_start_no FROM `wp_templates` ORDER BY id")
    templates = cur.fetchall()
    if len(templates) != 1:
        bad("template_count", expected=1, actual=len(templates))
    cur.execute("SELECT version_number, status FROM `wp_versions` ORDER BY version_number")
    versions = cur.fetchall()
    if versions != ((1, "PUBLISHED"),):
        bad("versions", expected="[(1, PUBLISHED)]", actual=str(versions))

    # 발행된 버전은 표시 파라미터를 스스로 들고 있어야 한다 (plan.md §2.4).
    # NULL 이면 템플릿 값으로 폴백하므로, 나중에 템플릿을 고치면 발행 보드의 번호가
    # 따라 움직인다 — 규칙이 금지하는 상황이다. 사람이 추론하지 않아도
    # 잡히도록 검사로 둔다.
    cur.execute(
        "SELECT version_number, status FROM `wp_versions` "
        "WHERE status <> 'DRAFT' AND phase_start_no IS NULL"
    )
    for version_number, status in cur.fetchall():
        bad(
            "missing_phase_start_no_snapshot",
            version_number=version_number,
            status=status,
            note="비-DRAFT 버전은 phase_start_no 스냅샷을 가져야 한다",
        )

    # --- 행 ---------------------------------------------------------------
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT sort_order), MIN(sort_order), MAX(sort_order) "
        "FROM `wp_items`"
    )
    count, distinct, lo, hi = cur.fetchone()
    if (count, distinct, lo, hi) != (len(book.rows), len(book.rows), 1, len(book.rows)):
        bad("item_shape", expected=f"{len(book.rows)} rows, sort_order 1..{len(book.rows)}",
            actual=f"count={count} distinct={distinct} min={lo} max={hi}")

    cur.execute("SELECT COUNT(*) FROM `wp_items` WHERE origin <> 'INHERITED'")
    added = cur.fetchone()[0]
    if added:
        bad("unexpected_added_items", actual=added,
            note="seed rows should all be INHERITED; ADDED rows come from live edits")

    cur.execute(
        "SELECT i.sort_order, i.title, i.deliverable, p.name, ms.name, i.status "
        "FROM `wp_items` i LEFT JOIN `wp_phases` p ON p.id = i.phase_id "
        "LEFT JOIN `wp_milestones` ms ON ms.id = i.milestone_id ORDER BY i.sort_order"
    )
    for excel, db in zip(book.rows, cur.fetchall()):
        expected = (excel.no, excel.title, excel.deliverable, excel.phase_name,
                    excel.milestone_name, excel.status)
        if expected != tuple(db):
            bad("row_mismatch", no=excel.no, expected=list(expected), actual=list(db))

    # --- N:M 링크 ----------------------------------------------------------
    # 문서는 §0.5.10 부터 템플릿 스코프이고, 표시 번호는 sort_order 다 (원문자 폐기).
    cur.execute(
        "SELECT i.sort_order, t.sort_order FROM `wp_items` i "
        "JOIN `wp_item_documents` d ON d.item_id = i.id "
        "JOIN `wp_template_documents` t ON t.id = d.template_document_id "
        "ORDER BY i.sort_order, d.sort_order"
    )
    db_docs: dict[int, list[int]] = {}
    for so, number in cur.fetchall():
        db_docs.setdefault(so, []).append(number)
    for row in book.rows:
        if row.doc_numbers != db_docs.get(row.no, []):
            bad("document_links", no=row.no, expected=row.doc_numbers,
                actual=db_docs.get(row.no, []))

    cur.execute(
        "SELECT i.sort_order, o.name FROM `wp_items` i "
        "JOIN `wp_item_owners` io ON io.item_id = i.id "
        "JOIN `wp_owners` o ON o.id = io.owner_id ORDER BY i.sort_order, io.sort_order"
    )
    db_owners: dict[int, list[str]] = {}
    for so, name in cur.fetchall():
        db_owners.setdefault(so, []).append(name)
    for row in book.rows:
        if row.owner_names != db_owners.get(row.no, []):
            bad("owner_links", no=row.no, expected=row.owner_names,
                actual=db_owners.get(row.no, []))

    # --- 기준정보: 개수 · 이름 · seq_no ------------------------------------
    expected_phases: list[str] = []
    for row in book.rows:
        if row.phase_name not in expected_phases:
            expected_phases.append(row.phase_name)

    cur.execute("SELECT id, seq_no, name FROM `wp_phases` ORDER BY seq_no, id")
    phases = cur.fetchall()
    if [p[2] for p in phases] != expected_phases:
        bad("phase_set", expected=expected_phases, actual=[p[2] for p in phases])
    if [p[1] for p in phases] != list(range(len(expected_phases))):
        bad("phase_seq_no", expected=list(range(len(expected_phases))),
            actual=[p[1] for p in phases],
            note="phase_start_no=0 이므로 0부터 빈틈없이 이어져야 한다")

    expected_ms: dict[str, list[str]] = {}
    for row in book.rows:
        bucket = expected_ms.setdefault(row.phase_name, [])
        if row.milestone_name not in bucket:
            bucket.append(row.milestone_name)

    cur.execute(
        "SELECT p.name, ms.name, ms.seq_no FROM `wp_milestones` ms "
        "JOIN `wp_phases` p ON p.id = ms.phase_id ORDER BY p.seq_no, ms.seq_no, ms.id"
    )
    actual_ms: dict[str, list[tuple[str, int]]] = {}
    for phase_name, ms_name, seq in cur.fetchall():
        actual_ms.setdefault(phase_name, []).append((ms_name, seq))
    for phase_name, names in expected_ms.items():
        got = actual_ms.get(phase_name, [])
        if [g[0] for g in got] != names:
            bad("milestone_set", phase=phase_name, expected=names, actual=[g[0] for g in got])
        if [g[1] for g in got] != list(range(1, len(names) + 1)):
            bad("milestone_seq_no", phase=phase_name,
                expected=list(range(1, len(names) + 1)), actual=[g[1] for g in got])
    for phase_name in actual_ms:
        if phase_name not in expected_ms:
            bad("unexpected_milestone_phase", phase=phase_name)

    # --- 고아 기준정보 (행이 참조하지 않는 것) ------------------------------
    cur.execute(
        "SELECT p.id, p.name FROM `wp_phases` p "
        "WHERE NOT EXISTS (SELECT 1 FROM `wp_items` i WHERE i.phase_id = p.id)"
    )
    for pid, name in cur.fetchall():
        bad("orphan_phase", id=pid, name=name, repairable=True)
    cur.execute(
        "SELECT ms.id, ms.name FROM `wp_milestones` ms "
        "WHERE NOT EXISTS (SELECT 1 FROM `wp_items` i WHERE i.milestone_id = ms.id)"
    )
    for mid, name in cur.fetchall():
        bad("orphan_milestone", id=mid, name=name, repairable=True)

    # --- Owner / 문서 기준정보 --------------------------------------------
    expected_owners: list[str] = []
    for row in book.rows:
        for name in row.owner_names:
            if name not in expected_owners:
                expected_owners.append(name)
    cur.execute("SELECT name, is_active FROM `wp_owners` ORDER BY sort_order, id")
    owners = cur.fetchall()
    if [o[0] for o in owners] != expected_owners:
        bad("owner_set", expected=expected_owners, actual=[o[0] for o in owners])
    if any(not o[1] for o in owners):
        bad("inactive_owner", actual=[o[0] for o in owners if not o[1]])

    # Owner 와 같은 스코프 규칙이라 필터도 같은 방식으로 둔다 (시드 템플릿 하나뿐).
    cur.execute(
        "SELECT sort_order, name, is_active FROM `wp_template_documents` "
        "ORDER BY sort_order, id"
    )
    docs = cur.fetchall()
    if [d[1] for d in docs] != [d.name for d in book.doc_types]:
        bad("document_set", expected=[d.name for d in book.doc_types],
            actual=[d[1] for d in docs])
    if any(not d[2] for d in docs):
        bad("inactive_document", actual=[d[1] for d in docs if not d[2]])

    return problems


def repair(cur) -> list[str]:
    """행을 잃지 않는 범위에서만 고친다: 고아 기준정보 제거 + seq_no 재유도."""
    actions: list[str] = []

    cur.execute(
        "DELETE ms FROM `wp_milestones` ms "
        "WHERE NOT EXISTS (SELECT 1 FROM `wp_items` i WHERE i.milestone_id = ms.id)"
    )
    if cur.rowcount:
        actions.append(f"deleted {cur.rowcount} orphan milestone(s)")
    cur.execute(
        "DELETE p FROM `wp_phases` p "
        "WHERE NOT EXISTS (SELECT 1 FROM `wp_items` i WHERE i.phase_id = p.id)"
    )
    if cur.rowcount:
        actions.append(f"deleted {cur.rowcount} orphan phase(s)")

    # seq_no 는 v1 PUBLISHED 의 행 순서에서 다시 유도한다 (§2.2 최초 등장 순서).
    cur.execute(
        "SELECT DISTINCT i.phase_id FROM `wp_items` i "
        "JOIN `wp_versions` v ON v.id = i.version_id "
        "WHERE v.version_number = 1 AND i.phase_id IS NOT NULL "
        "ORDER BY MIN(i.sort_order) OVER (PARTITION BY i.phase_id)"
    )
    phase_ids = [r[0] for r in cur.fetchall()]
    for seq, phase_id in enumerate(phase_ids):
        cur.execute("UPDATE `wp_phases` SET seq_no=%s WHERE id=%s AND seq_no<>%s",
                    (seq, phase_id, seq))
        if cur.rowcount:
            actions.append(f"phase {phase_id} seq_no -> {seq}")

    for phase_id in phase_ids:
        cur.execute(
            "SELECT DISTINCT i.milestone_id FROM `wp_items` i "
            "JOIN `wp_versions` v ON v.id = i.version_id "
            "WHERE v.version_number = 1 AND i.phase_id = %s AND i.milestone_id IS NOT NULL "
            "ORDER BY MIN(i.sort_order) OVER (PARTITION BY i.milestone_id)",
            (phase_id,),
        )
        for seq, ms_id in enumerate([r[0] for r in cur.fetchall()], start=1):
            cur.execute("UPDATE `wp_milestones` SET seq_no=%s WHERE id=%s AND seq_no<>%s",
                        (seq, ms_id, seq))
            if cur.rowcount:
                actions.append(f"milestone {ms_id} seq_no -> {seq}")

    return actions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="iai-test 를 엑셀 원본과 대조 검사")
    ap.add_argument("--repair", action="store_true",
                    help="고아 기준정보 제거 + seq_no 재유도 후 재검사")
    args = ap.parse_args(argv)

    book = migrate.parse_workbook(migrate.EXCEL_PATH)
    conn = connect()
    report: dict = {"excel_rows": len(book.rows), "actions": []}
    try:
        with conn.cursor() as cur:
            # 스키마 드리프트를 먼저 본다. 컬럼이 없으면 데이터 검사 쿼리 자체가
            # 터지므로, 원인을 정확히 보고하고 거기서 멈춘다.
            schema_problems = check_schema(cur)
            if schema_problems:
                problems = schema_problems
            else:
                if args.repair:
                    report["actions"] = repair(cur)
                    conn.commit()
                problems = check(cur, book)
        conn.commit()
    finally:
        conn.close()

    report["problems"] = problems
    # 깨끗할 때는 파일을 남기지 않는다 — db/ 에 생성물이 쌓이지 않도록.
    if problems or report["actions"]:
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    elif REPORT_PATH.exists():
        REPORT_PATH.unlink()

    for action in report["actions"]:
        print(f"repaired: {action}")
    if problems:
        counts: dict[str, int] = {}
        for p in problems:
            counts[p["kind"]] = counts.get(p["kind"], 0) + 1
        print("DRIFT: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        print(f"detail -> {REPORT_PATH}")
        return 1

    print(f"OK: iai-test matches the Excel source ({len(book.rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
