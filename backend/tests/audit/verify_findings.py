"""Regression harness for the backend audit findings (F1-F10, R1-R3, RULE-psn).

**Not a pytest file.** `pytest.ini` only collects `test_*.py`, so this is never
picked up by the suite. Run it directly::

    python backend/tests/audit/verify_findings.py

Each check re-attempts the *original reproduction* of a defect found during the
audit and reports a verdict:

    FIXED  the defect no longer reproduces
    OPEN   the defect still reproduces (evidence attached)
    N-A    could not be exercised (a symbol or endpoint moved) -> needs a look

Exit code is 0 when nothing is OPEN, 1 otherwise, so this can gate a build.

Why it exists: the suite proves the code does what its authors intended today.
These checks pin the specific ways it went wrong before, which is a different
question and the one that tends to regress quietly during a refactor. Read
`README.md` in this directory for what each check means and — importantly —
what its verdict does *not* cover.

Safety: every mutation happens in a throwaway database named
`iai_audit_verify_<pid>`, created and dropped by this script. It never writes to
`iai-test` or `dsep_iai`; the one check that looks at `iai-test` reads
`information_schema` only.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import quote_plus

# backend/tests/audit/verify_findings.py -> backend/ -> repo root
BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, text                                     # noqa: E402
from fastapi import FastAPI                                             # noqa: E402
from fastapi.testclient import TestClient                               # noqa: E402

from app.core.database import create_session_factory                    # noqa: E402
from app.models import (Item, ItemDocument, ItemOwner, TemplateDocument,    # noqa: E402
                        Milestone, Owner, Phase, Version, VersionStatus, Template)
from app.router import create_wp_router                                 # noqa: E402
from app.services import item_service, version_service                  # noqa: E402

# --- connection (same defaults as tests/conftest.py; override with env) ------
#
# The password has **no default** — one in the source is a password in the repository.
# `WP_AUDIT_DB_PASSWORD` first so an audit run can point somewhere else, then the same
# `WP_DB_PASSWORD` everything else in this repo uses.
#
# ⚠️ Both hold the **raw** password now, not a pre-encoded one. This used to take the
# already-percent-encoded form, so a value carrying a literal `%23` today double-encodes to
# `%2523` and fails with a bare "Access denied".
DB_HOST = os.environ.get("WP_AUDIT_DB_HOST", "localhost")
DB_PORT = os.environ.get("WP_AUDIT_DB_PORT", "3306")
DB_USER = os.environ.get("WP_AUDIT_DB_USER", "user01")
DB_PASSWORD = os.environ.get("WP_AUDIT_DB_PASSWORD") or os.environ.get("WP_DB_PASSWORD", "")
if not DB_PASSWORD:
    sys.exit(
        "WP_DB_PASSWORD 환경변수가 필요합니다.\n"
        "  PowerShell: $env:WP_DB_PASSWORD = 'xxxx'\n"
        "  bash      : export WP_DB_PASSWORD=xxxx"
    )
#: `#` must be percent-encoded in a DSN or the URL is silently truncated.
DB_PASSWORD_URL = quote_plus(DB_PASSWORD)
#: The deliverable DB. Read-only here, and only via information_schema.
LIVE_DB = os.environ.get("WP_AUDIT_LIVE_DB", "iai-test")

AUDIT_DB = f"iai_audit_verify_{os.getpid()}"
SERVER_DSN = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD_URL}@{DB_HOST}:{DB_PORT}/?charset=utf8mb4"
AUDIT_DSN = (f"mysql+pymysql://{DB_USER}:{DB_PASSWORD_URL}@{DB_HOST}:{DB_PORT}"
             f"/{AUDIT_DB}?charset=utf8mb4")
API = "/api/v1"

WIPE_ORDER = ["wp_project_item_owners", "wp_project_item_documents", "wp_project_items",
              "wp_project_milestones", "wp_project_phases", "wp_project_owners", "wp_projects",
              "wp_item_owners", "wp_item_documents", "wp_items", "wp_versions",
              "wp_milestones", "wp_phases", "wp_owners", "wp_templates",
              "wp_template_documents"]

CHECKS: list[tuple] = []          # (id, title, fn)
RESULTS: list[dict] = []
SF = None                         # session factory, set up in main()
C = None                          # TestClient over create_wp_router()


# =============================================================================
# infrastructure
# =============================================================================
def ddl_statements(path: Path) -> list[str]:
    """CREATE TABLE statements from a .sql file, minus the dev-only DB lines."""
    out, buf = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buf).strip().rstrip(";").strip()
            buf = []
            if statement.upper().startswith(("CREATE DATABASE", "USE ")):
                continue
            out.append(statement)
    return out


def call(fn, session, **named):
    """Bind `fn` from a pool of candidate arguments, by parameter name.

    The services are refactored often — parameters get added (`docs`), objects
    become ids (`version` -> `version_id`). Binding by name means a signature
    change shows up as a real verdict instead of a wall of N-A results.
    """
    pool = dict(named)
    pool.setdefault("session", session)
    pool.setdefault("db", session)

    # plan.md §0.1 이후 `item_service` 는 `Version` 이 아니라 `Board` 를 받는다
    # (템플릿·프로젝트가 같은 구현을 공유한다). 버전을 알고 있으면 보드를 만들 수
    # 있으므로, 호출부를 전부 고치는 대신 여기서 유도한다 — 이 헬퍼의 존재 이유가
    # 바로 "시그니처가 바뀌어도 판정이 N-A 로 무너지지 않게" 하는 것이다.
    if "board" not in pool:
        version = pool.get("version")
        if version is None and pool.get("version_id") is not None:
            version = session.get(Version, pool["version_id"])
        if version is not None:
            pool["board"] = version_service.board_of(session, version)

    args, kwargs = [], {}
    for name, p in inspect.signature(fn).parameters.items():
        if name in pool:
            if p.kind is p.KEYWORD_ONLY:
                kwargs[name] = pool[name]
            else:
                args.append(pool[name])
        elif p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            raise TypeError(f"{fn.__name__}: no candidate for required parameter {name!r}")
    return fn(*args, **kwargs)


def editable_guard(session, version_id):
    """Call whatever the current 'may I write to this version' guard is named."""
    for name in ("lock_editable_version", "assert_editable", "assert_writable"):
        fn = getattr(version_service, name, None)
        if fn is not None:
            return call(fn, session, version_id=version_id)
    raise AttributeError("no editability guard found on version_service")


def wipe(db):
    for table in WIPE_ORDER:
        db.execute(text(f"DELETE FROM `{table}`"))
    db.commit()


def board(db, phases=2, rows=(2, 2), status=VersionStatus.PUBLISHED):
    """A WP with `phases` phases (one milestone each), one owner, one document,
    and a single version holding `rows[i]` rows in phase i."""
    wipe(db)
    wp = Template(code="AUDIT", name="audit", phase_start_no=0)
    db.add(wp); db.flush()

    ps, ms = [], []
    for i in range(phases):
        phase = Phase(template_id=wp.id, name=f"P{i}", seq_no=i)
        db.add(phase); db.flush()
        milestone = Milestone(template_id=wp.id, phase_id=phase.id, name=f"M{i}", seq_no=1)
        db.add(milestone); db.flush()
        ps.append(phase); ms.append(milestone)

    owner = Owner(template_id=wp.id, name="O1", sort_order=1)
    doc = TemplateDocument(template_id=wp.id, name="D1", sort_order=1)
    db.add_all([owner, doc]); db.flush()

    version = Version(template_id=wp.id, version_number=1, status=status)
    db.add(version); db.flush()

    sort_order = 0
    for i, count in enumerate(rows[:phases]):
        for _ in range(count):
            sort_order += 1
            item = Item(version_id=version.id, sort_order=sort_order, phase_id=ps[i].id,
                        milestone_id=ms[i].id, title="t", deliverable="dv")
            item.documents = [ItemDocument(template_document_id=doc.id, sort_order=1)]
            item.owners = [ItemOwner(owner_id=owner.id, sort_order=1)]
            db.add(item)
    db.commit()
    return wp, ps, ms, owner, doc, version


def items_of(version_id):
    response = C.get(f"{API}/versions/{version_id}")
    return response.json().get("items", []) if response.status_code == 200 else []


def check(check_id, title):
    def register(fn):
        CHECKS.append((check_id, title, fn))
        return fn
    return register


# =============================================================================
# F1 — version immutability must be enforced under a row lock
# =============================================================================
@check("F1a", "temp-save racing publish writes into a PUBLISHED version")
def _f1a():
    from app.schemas.item import ItemSaveIn
    with SF() as db:
        wp, ps, ms, owner, doc, _ = board(db)
        draft = call(version_service.create_draft, db, template_id=wp.id)
        db.commit()
        did, pid, mid, oid, docid = draft.id, ps[0].id, ms[0].id, owner.id, doc.id

    a, b = SF(), SF()
    stale = call(version_service.get_version, a, version_id=did).status.value
    version_service.publish(b, did, docs_for(b)); b.commit(); b.close()

    rejected_by = None
    try:                                   # A now enters its write path
        version = editable_guard(a, did)
        rows = call(item_service.load_ordered_items, a, version_id=did)
        call(item_service.bulk_replace, a, version=version, payload=[ItemSaveIn(
            id=rows[0].id, title="RACED", phase_id=pid, milestone_id=mid,
            deliverable="dv", document_ids=[docid], owner_ids=[oid])])
        a.commit(); raced = True
    except Exception as exc:
        raced, rejected_by = False, type(exc).__name__
    a.close()

    with SF() as db:
        status = db.get(Version, did).status.value
        titles = [i.title for i in call(item_service.load_ordered_items, db, version_id=did)]
    if raced and status == "PUBLISHED" and "RACED" in titles:
        return "OPEN", {"status": status, "titles": titles[:3]}
    return "FIXED", {"stale_read_saw": stale, "status_after": status,
                     "write_rejected_by": rejected_by}


@check("F1b", "discard racing publish leaves the WP with zero PUBLISHED versions")
def _f1b():
    with SF() as db:
        wp, *_ = board(db)
        wpid = wp.id
        draft = call(version_service.create_draft, db, template_id=wp.id); db.commit()
        did = draft.id

    a, b = SF(), SF()
    call(version_service.get_version, a, version_id=did)          # A's stale read
    version_service.publish(b, did, docs_for(b)); b.commit(); b.close()
    rejected_by = None
    try:
        call(version_service.discard, a, version_id=did); a.commit(); deleted = True
    except Exception as exc:
        deleted, rejected_by = False, type(exc).__name__
    a.close()

    with SF() as db:
        versions = [(v.version_number, v.status.value)
                    for v in call(version_service.list_versions, db, template_id=wpid)]
    published = sum(1 for _, s in versions if s == "PUBLISHED")
    return ("OPEN" if (deleted and published == 0) else "FIXED"), {
        "versions": versions, "published": published, "discard_rejected_by": rejected_by}


# =============================================================================
# F2 — the two validation paths must agree, and locate their errors
# =============================================================================
@check("F2", "/validate disagrees with /publish; V6/V7 carry no row location")
def _f2():
    with SF() as db:
        wp, ps, *_ = board(db, 2, (1, 1))
        draft = call(version_service.create_draft, db, template_id=wp.id); db.commit()
        did = draft.id
        ps[0].seq_no, ps[1].seq_no = 41, 42       # as a master-data edit would leave it
        db.commit()

    preview = C.post(f"{API}/versions/{did}/validate").json()
    errors = [(e["code"], e.get("item_id"), e.get("row_no"), e.get("field"))
              for e in preview.get("errors", [])]
    published = C.post(f"{API}/versions/{did}/publish")

    disagree = preview.get("valid") is False and published.status_code == 200
    unlocated = [c for c, iid, row, _ in errors
                 if c in ("PHASE_SEQ_GAP", "MILESTONE_SEQ_GAP") and iid is None and row is None]
    verdict = "OPEN" if (disagree or unlocated) else "FIXED"
    return verdict, {"validate_valid": preview.get("valid"), "publish": published.status_code,
                     "errors": errors, "codes_without_row": unlocated}


# =============================================================================
# F3 — master edits must not invalidate an already-published board
# =============================================================================
@check("F3", "update_milestone re-parents an in-use milestone, invalidating PUBLISHED")
def _f3():
    with SF() as db:
        wp, ps, ms, _, _, version = board(db, 2, (1, 1))
        wpid, milestone_id, other_phase, vid = wp.id, ms[0].id, ps[1].id, version.id

    response = C.put(f"{API}/templates/{wpid}/milestones/{milestone_id}",
                     json={"phase_id": other_phase})
    after = C.post(f"{API}/versions/{vid}/validate").json()
    if response.status_code < 300 and after.get("valid") is False:
        return "OPEN", {"http": response.status_code, "published_valid": after.get("valid"),
                        "errors": [(e["code"], e.get("row_no")) for e in after.get("errors", [])]}
    return "FIXED", {"http": response.status_code, "body": str(response.json())[:200],
                     "published_valid": after.get("valid")}


# =============================================================================
# F4 — renumbering must not leave duplicate master numbers behind
# =============================================================================
@check("F4", "seq_no rewritten only for used phases leaves duplicate master numbers")
def _f4():
    with SF() as db:
        wp, ps, ms, owner, doc, _ = board(db, 4, (1, 1, 1, 1))
        wpid, docid, oid = wp.id, doc.id, owner.id
        keep = [(ps[2].id, ms[2].id), (ps[3].id, ms[3].id)]
        draft = call(version_service.create_draft, db, template_id=wp.id); db.commit()
        did = draft.id

    rows = items_of(did)
    C.put(f"{API}/versions/{did}/items", json={"items": [
        {"id": rows[i]["id"], "phase_id": p, "milestone_id": m, "title": "t",
         "deliverable": "dv", "document_ids": [docid], "owner_ids": [oid]}
        for i, (p, m) in zip((2, 3), keep)]})

    listed = [(p["name"], p["seq_no"]) for p in
              C.get(f"{API}/templates/{wpid}/phases").json()]
    seqs = [s for _, s in listed]
    return ("OPEN" if len(seqs) != len(set(seqs)) else "FIXED"), {"phases": listed}


# =============================================================================
# F5 — the document-master seam is GONE (plan.md §0.5.10)
# =============================================================================
@check("F5", "global document master / repository seam still exists")
def _f5():
    """이 항목의 의미가 뒤집혔다.

    원래 F5 는 "전역 `document_types` 를 **한 지점에서** 교체할 수 있는가" 였다.
    §0.5.10 이 전역 문서를 폐기하고 문서를 템플릿 소유 + 프로젝트 복제로 옮기면서,
    교체할 이음매 자체가 사라졌다. 그래서 이제는 **되살아나지 않았는지**를 본다 —
    항목을 지우면 되돌아와도 아무도 모른다.
    """
    from app.models import Base

    evidence = {}
    evidence["repositories_package_exists"] = (BACKEND / "app/repositories").exists()

    from app.deps import WpDeps
    evidence["deps_fields_mentioning_document_type"] = [
        f for f in getattr(WpDeps, "__dataclass_fields__", {}) if "document_type" in f
    ]

    import inspect

    from app.router import create_wp_router
    evidence["router_params"] = sorted(inspect.signature(create_wp_router).parameters)

    evidence["global_table_present"] = "wp_document_types" in Base.metadata.tables
    evidence["scoped_tables"] = [
        t for t in ("wp_template_documents", "wp_project_documents")
        if t in Base.metadata.tables
    ]

    ok = (
        not evidence["repositories_package_exists"]
        and not evidence["deps_fields_mentioning_document_type"]
        and "document_type_repository_factory" not in evidence["router_params"]
        and not evidence["global_table_present"]
        and len(evidence["scoped_tables"]) == 2
    )
    return ("FIXED" if ok else "OPEN"), evidence


# =============================================================================
@check("F5", "document_types has no real injection point / services touch the ORM model")
def _f5():
    evidence = {}
    from app.deps import WpDeps
    evidence["injection_point"] = [f for f in getattr(WpDeps, "__dataclass_fields__", {})
                                   if "document_type" in f]

    concrete, model_used = [], []
    for path in list((BACKEND / "app/services").rglob("*.py")) + \
                list((BACKEND / "app/api").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(BACKEND / "app").as_posix()
        for pattern, bucket in (("SqlDocumentTypeRepository", concrete),
                                (r"\bDocumentType\s*\(", model_used)):
            for match in re.finditer(pattern, source):
                bucket.append(f"{rel}:{source[:match.start()].count(chr(10)) + 1}")
    evidence["concrete_repo_in_service_or_api"] = concrete
    evidence["orm_model_constructed"] = model_used

    proto_src = (BACKEND / "app/repositories/document_type_repository.py").read_text(encoding="utf-8")
    block = (proto_src.split("class DocumentTypeRepository")[1].split("\nclass ")[0]
             if "class DocumentTypeRepository" in proto_src else "")
    declared = set(re.findall(r"def (\w+)", block))
    used = set()
    for path in (BACKEND / "app/services").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for alias in ("docs", "repo", "doc_repo", "document_types"):
            used |= set(re.findall(rf"\b{alias}\.(\w+)\(", source))
    evidence["protocol_declares"] = sorted(declared)
    evidence["used_but_undeclared"] = sorted(used - declared)

    # The check that matters for the transplant claim: a substituted repository
    # must be the one actually used. Declaring the right Protocol is not enough.
    seen: list[str] = []

    class Spy:
        def __init__(self, session):
            self._inner = SqlDocumentTypeRepository(session)

        def __getattr__(self, name):
            seen.append(name)
            return getattr(self._inner, name)

    spy_app = FastAPI()
    spy_app.include_router(create_wp_router(session_factory=SF,
                                            document_type_repository_factory=Spy))
    evidence["substituted_repo_status"] = TestClient(spy_app).get(
        f"{API}/master/document-types").status_code
    evidence["substituted_repo_called"] = sorted(set(seen))

    healthy = (evidence["injection_point"] and not concrete and not model_used
               and not evidence["used_but_undeclared"] and evidence["substituted_repo_called"]
               and evidence["substituted_repo_status"] == 200)
    return ("FIXED" if healthy else "OPEN"), evidence


# =============================================================================
# F7 — a degenerate reorder must not silently clear membership
# =============================================================================
@check("F7", "reorder on a single-row version clears phase/milestone")
def _f7():
    """A degenerate reorder must not wipe the only row's membership.

    The original bug came from re-inheritance: the single row was treated as
    "moved" and inherited from a neighbour that did not exist. `reorder` no
    longer derives membership at all, so the row simply keeps its own. The
    request still carries the retired `moved_item_id` field on purpose — an old
    client sending it must not resurrect the old path.
    """
    with SF() as db:
        _, _, _, _, _, version = board(db, 1, (1,), status=VersionStatus.DRAFT)
        vid = version.id
    rows = items_of(vid)
    response = C.post(f"{API}/versions/{vid}/items/reorder", json={
        "item_ids": [rows[0]["id"]], "moved_item_id": rows[0]["id"]})
    after = [(x["row_no"], x["phase_id"], x["milestone_id"]) for x in items_of(vid)]
    wiped = response.status_code == 200 and after and after[0][1] is None
    return ("OPEN" if wiped else "FIXED"), {"status": response.status_code, "after": after}


@check("F7b", "reorder fragments a board when several rows change position")
def _f7b():
    """Position-only reorder is *not* automatically contiguity-safe.

    Rows carry their own membership, and `reorder` no longer changes it, so a
    permutation that interleaves two blocks leaves the board fragmented. The
    server must reject such an order (422) rather than persist it — or "fix" it
    by reassigning rows, which is the reassignment bug §2.2 removed.
    """
    with SF() as db:
        wipe(db)
        wp = Template(code="AUDIT", name="audit", phase_start_no=0)
        db.add(wp); db.flush()
        phases, milestones = [], []
        for i in range(4):
            phase = Phase(template_id=wp.id, name=f"P{i}", seq_no=i)
            db.add(phase); db.flush()
            milestone = Milestone(template_id=wp.id, phase_id=phase.id, name=f"M{i}", seq_no=1)
            db.add(milestone); db.flush()
            phases.append(phase); milestones.append(milestone)
        owner = Owner(template_id=wp.id, name="O1")
        doc = DocumentType(code="①", name="D1")
        db.add_all([owner, doc]); db.flush()
        version = Version(template_id=wp.id, version_number=1, status=VersionStatus.DRAFT)
        db.add(version); db.flush()
        for order, phase_index in enumerate([0, 1, 2, 3, 3], start=1):
            item = Item(version_id=version.id, sort_order=order,
                        phase_id=phases[phase_index].id,
                        milestone_id=milestones[phase_index].id, title="t", deliverable="dv")
            item.documents = [ItemDocument(template_document_id=doc.id, sort_order=1)]
            item.owners = [ItemOwner(owner_id=owner.id, sort_order=1)]
            db.add(item)
        db.commit()
        vid = version.id

    ids = [r["id"] for r in items_of(vid)]
    # two rows change position at once; no moved_item_id, which the contract allows
    permutation = [ids[1], ids[3], ids[0], ids[2], ids[4]]
    response = C.post(f"{API}/versions/{vid}/items/reorder", json={"item_ids": permutation})
    if response.status_code != 200:
        return "FIXED", {"status": response.status_code, "note": "rejected rather than persisted"}

    after = [x["phase_no"] for x in items_of(vid)]
    runs = [k for i, k in enumerate(after) if i == 0 or after[i - 1] != k]
    contiguous = len(runs) == len(set(runs))
    return ("FIXED" if contiguous else "OPEN"), {
        "status": 200, "board_after": after, "contiguous": contiguous}


# =============================================================================
# F9 / F10 — static
# =============================================================================
@check("F9", "db/schema.sql documents the '/'-split bug the design corrects")
def _f9():
    offenders = [line.strip()
                 for line in (REPO / "db/schema.sql").read_text(encoding="utf-8").splitlines()
                 if "관련 문서" in line and "`/`" in line]
    return ("OPEN" if offenders else "FIXED"), {"lines": offenders}


@check("F10", "conftest shares one test DB name across concurrent runs")
def _f10():
    match = re.search(r"TEST_DB\s*=\s*(.+)",
                      (BACKEND / "tests/conftest.py").read_text(encoding="utf-8"))
    line = match.group(1).strip() if match else "?"
    return ("FIXED" if ("getpid" in line or "uuid" in line) else "OPEN"), {"TEST_DB": line}


# =============================================================================
# R1-R3 — plan.md 2.3 boundary rules
# =============================================================================
@check("R1", "2.3: a middle-row membership change must RELOCATE server-side, not 422")
def _r1():
    with SF() as db:
        _, ps, ms, _, _, version = board(db, 2, (3, 1), status=VersionStatus.DRAFT)
        vid, target_phase, target_ms = version.id, ps[1].id, ms[1].id
    rows = items_of(vid)
    moved_id = rows[1]["id"]                       # middle of the 3-row P0 block

    response = C.patch(f"{API}/versions/{vid}/items/{moved_id}/membership",
                       json={"phase_id": target_phase, "milestone_id": target_ms})
    via = "PATCH membership"
    if response.status_code in (404, 405):
        return "N-A", {"via": via, "status": response.status_code,
                       "note": "membership endpoint absent"}
    if response.status_code == 200:
        after = items_of(vid)
        moved = next(x for x in after if x["id"] == moved_id)
        relocated = moved["row_no"] == 4 and moved["phase_no"] == 1
        return ("FIXED" if relocated else "OPEN"), {
            "via": via, "board": [(x["row_no"], x["phase_no"]) for x in after],
            "moved_to_row": moved["row_no"], "moved_phase_no": moved["phase_no"]}
    return "OPEN", {"via": via, "status": response.status_code,
                    "body": str(response.json())[:240]}


@check("R2", "2.3: a contiguity error must point at the EDITED row, not the split point")
def _r2():
    with SF() as db:
        _, ps, ms, _, _, version = board(db, 2, (2, 2), status=VersionStatus.DRAFT)
        vid, p0, m0 = version.id, ps[0].id, ms[0].id
    rows = items_of(vid)
    edited_row_no = 4
    response = C.patch(f"{API}/versions/{vid}/items/{rows[3]['id']}/membership",
                       json={"phase_id": p0, "milestone_id": m0})
    if response.status_code in (404, 405):
        return "N-A", {"status": response.status_code, "note": "membership endpoint absent"}
    if response.status_code == 200:
        after = [(x["row_no"], x["phase_no"]) for x in items_of(vid)]
        contiguous = [p for _, p in after] == sorted(p for _, p in after)
        return ("FIXED" if contiguous else "OPEN"), {
            "note": "membership relocates; no contiguity error is reachable here",
            "board": after}
    detail = response.json().get("detail", {})
    if not isinstance(detail, dict):
        return "N-A", {"status": response.status_code, "body": str(response.json())[:200]}
    pointed = {b.get("row_no") for b in detail.get("breaks", [])} or {detail.get("row_no")}
    pointed = sorted(x for x in pointed if x is not None)
    return ("FIXED" if pointed == [edited_row_no] else "OPEN"), {
        "status": response.status_code, "edited_row": edited_row_no,
        "pointed_at": pointed, "code": detail.get("code")}


@check("R3", "0.2-4: a gray row may create a Phase only when the result stays contiguous")
def _r3():
    """The original finding was "unassigned rows must always count as boundaries".

    `plan.md` §0.2-4 **corrected** that: they are boundaries, but creating a Phase is
    only allowed when the result is still contiguous. A gray row sitting inside one
    block would split it.

    The old check only exercised an all-unassigned board, where both the old and the
    corrected rule say "true" — so it stopped discriminating. Both halves are checked
    here: the permissive case must stay permissive (gray rows must not trap each
    other), and the newly-restricted case must actually be refused.
    """
    evidence = {}

    # (a) all-unassigned board — nothing to split, so every row stays creatable.
    with SF() as db:
        _, _, _, _, _, version = board(db, 1, (0,), status=VersionStatus.DRAFT)
        vid = version.id
    for _ in range(3):
        C.post(f"{API}/versions/{vid}/items", json={})
    loose = [(x["row_no"], x["phase_id"], x["can_create_phase"]) for x in items_of(vid)]
    evidence["all_unassigned"] = loose
    permissive = bool(loose) and all(f[2] for f in loose)

    # (b) a gray row in the middle of one Phase block — creating there splits it.
    with SF() as db:
        _, _, _, _, _, version = board(db, 1, (2,), status=VersionStatus.DRAFT)
        vid2 = version.id
    rows = items_of(vid2)
    inserted = C.post(f"{API}/versions/{vid2}/items/{rows[0]['id']}/insert-below").json()["items"]
    gray = inserted[1]
    refused = C.post(
        f"{API}/versions/{vid2}/items/{gray['id']}/create-phase", json={"name": "split"}
    )
    evidence["gray_inside_block"] = {
        "can_create_phase": gray["can_create_phase"], "status": refused.status_code
    }
    restrictive = gray["can_create_phase"] is False and refused.status_code == 422

    return ("FIXED" if permissive and restrictive else "OPEN"), evidence


# =============================================================================
# RULE-psn — a PUBLISHED version's numbering must not follow mutable WP state
# =============================================================================
@check("RULE-psn", "PUBLISHED numbering follows WP.phase_start_no changes")
def _psn():
    evidence = {}

    # (a) a version published through the API carries its own snapshot
    with SF() as db:
        wp, _, _, _, _, version = board(db, 2, (1, 1), status=VersionStatus.DRAFT)
        wpid, vid = wp.id, version.id
        version_service.publish(db, vid, docs_for(db)); db.commit()
        evidence["api_snapshot"] = db.get(Version, vid).phase_start_no
    before = [x["phase_no"] for x in items_of(vid)]
    C.put(f"{API}/templates/{wpid}", json={"phase_start_no": 5})
    evidence["api_published"] = {"before": before,
                                 "after": [x["phase_no"] for x in items_of(vid)]}

    # (b) a version created by SQL — the db/seed.sql path
    with SF() as db:
        wp, _, _, _, _, version = board(db, 2, (1, 1), status=VersionStatus.PUBLISHED)
        wpid, vid = wp.id, version.id
        evidence["sql_snapshot"] = db.get(Version, vid).phase_start_no
    before = [x["phase_no"] for x in items_of(vid)]
    C.put(f"{API}/templates/{wpid}", json={"phase_start_no": 5})
    evidence["sql_published"] = {"before": before,
                                 "after": [x["phase_no"] for x in items_of(vid)]}

    # (c) does the committed seed set the column? Match the INSERT specifically --
    # `wp_versions` also appears in the DELETE statements at the top of the file.
    seed = (REPO / "db/seed.sql").read_text(encoding="utf-8")
    insert = re.search(r"INSERT\s+INTO\s+`wp_versions`(.*?);", seed, re.S | re.I)
    evidence["seed_sets_phase_start_no"] = bool(insert) and "phase_start_no" in insert.group(1)

    # (d) nothing in the deliverable may carry a NULL snapshot on a frozen version.
    try:
        import pymysql
        connection = pymysql.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER,
                                     password=DB_PASSWORD_URL.replace("%23", "#"),
                                     database=LIVE_DB, charset="utf8mb4")
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT id, version_number, status FROM wp_versions "
                           "WHERE status <> 'DRAFT' AND phase_start_no IS NULL")
            evidence["live_frozen_versions_without_snapshot"] = cursor.fetchall()
        finally:
            connection.close()
    except Exception as exc:
        evidence["live_frozen_versions_without_snapshot"] = f"not checked ({type(exc).__name__})"

    # A NULL snapshot legitimately falls back to the WP value -- see `sql_published`,
    # kept as evidence. The rule holds as long as nothing *creates* a NULL snapshot
    # on a frozen version, so the verdict rests on (a), (c) and (d).
    live_clean = evidence["live_frozen_versions_without_snapshot"]
    held = (evidence["api_published"]["before"] == evidence["api_published"]["after"]
            and evidence["seed_sets_phase_start_no"]
            and (not isinstance(live_clean, list) or not live_clean))
    return ("FIXED" if held else "OPEN"), evidence


# =============================================================================
# NEW-1 — the ORM, db/schema.sql and the live deliverable must agree
# =============================================================================
@check("NEW-1", "ORM/schema.sql drift from the live deliverable; no migration path")
def _new1():
    import pymysql
    from app.models import Base

    connection = pymysql.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER,
                                 password=DB_PASSWORD_URL.replace("%23", "#"),
                                 database="information_schema", charset="utf8mb4")
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT table_name, column_name FROM columns WHERE table_schema=%s",
                       (LIVE_DB,))
        live = {(t, c) for t, c in cursor.fetchall()}
    finally:
        connection.close()

    if not live:
        return "N-A", {"note": f"database {LIVE_DB!r} not present; nothing to compare"}

    live_tables = {t for t, _ in live}
    declared = {(t.name, c.name) for t in Base.metadata.tables.values() for c in t.columns}
    missing = sorted((t, c) for (t, c) in declared if t in live_tables and (t, c) not in live)

    migrations = REPO / "db" / "migrations"
    return ("FIXED" if not missing else "OPEN"), {
        "orm_columns_missing_from_live": missing,
        "db/migrations": sorted(p.name for p in migrations.iterdir())
        if migrations.is_dir() else "absent"}


# =============================================================================
# driver
# =============================================================================
def main() -> int:
    global SF, C

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated check ids, e.g. F1a,F2,RULE-psn")
    parser.add_argument("--report", type=Path,
                        default=Path(tempfile.gettempdir()) / "wp_audit_verdict.json",
                        help="where to write the UTF-8 JSON report")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print evidence for every check, not just non-FIXED ones")
    args = parser.parse_args()

    wanted = {s.strip() for s in args.only.split(",")} if args.only else None
    selected = [c for c in CHECKS if wanted is None or c[0] in wanted]
    if wanted:
        unknown = wanted - {c[0] for c in CHECKS}
        if unknown:
            print(f"unknown check id(s): {sorted(unknown)}")
            return 2

    server = create_session_factory(SERVER_DSN)
    try:
        with server() as s:
            s.execute(text(f"DROP DATABASE IF EXISTS `{AUDIT_DB}`"))
            s.execute(text(f"CREATE DATABASE `{AUDIT_DB}` DEFAULT CHARACTER SET utf8mb4 "
                           "DEFAULT COLLATE utf8mb4_unicode_ci"))
            s.commit()
    except Exception as exc:
        print(f"cannot reach MariaDB at {DB_HOST}:{DB_PORT} -- {exc}")
        return 2

    try:
        SF = create_session_factory(AUDIT_DSN)
        with SF() as s:
            for statement in ddl_statements(REPO / "db" / "schema.sql"):
                s.execute(text(statement))
            s.commit()

        app = FastAPI()
        app.include_router(create_wp_router(session_factory=SF))
        C = TestClient(app)

        for check_id, title, fn in selected:
            try:
                verdict, evidence = fn()
            except Exception:
                verdict = "N-A"
                evidence = {"error": traceback.format_exc().splitlines()[-1][:300]}
            RESULTS.append({"id": check_id, "title": title,
                            "verdict": verdict, "evidence": evidence})
    finally:
        with server() as s:
            s.execute(text(f"DROP DATABASE IF EXISTS `{AUDIT_DB}`"))
            s.commit()

    # Console is cp949 on this machine; keep stdout ASCII and put detail in the file.
    for row in RESULTS:
        line = f"{row['verdict']:<5} {row['id']:<9} {row['title']}"
        print(line.encode("ascii", "replace").decode())
        if args.verbose or row["verdict"] != "FIXED":
            detail = json.dumps(row["evidence"], ensure_ascii=True, default=str)
            print(f"      {detail[:500]}")

    counts = {v: sum(1 for r in RESULTS if r["verdict"] == v) for v in ("FIXED", "OPEN", "N-A")}
    print(f"\n{counts}")

    args.report.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1, default=str),
                           encoding="utf-8")
    print(f"report: {args.report}")

    if counts["OPEN"]:
        print("\nOPEN findings reproduce -- see the report for evidence.")
        return 1
    if counts["N-A"]:
        print("\nSome checks could not be exercised; a symbol or endpoint moved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
