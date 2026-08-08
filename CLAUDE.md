# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Resuming a session? Read `HANDOFF.md` first** — current verified state, open items, and the operating rules that were learned expensively.

## Project status

**Pre-implementation.** The repo contains only `docs/` and `plan.md` — no source code, no package manifests, no git repo yet.

`plan.md` is the authoritative spec. Read it before writing any code; it holds the schema design, API surface, validation rules, and the numbering/boundary algorithms that the rest of this file only summarizes. `INTEGRATION.md` is the authoritative contract for everything that crosses the boundary into a host project. All of `plan.md` §7 is now decided — check that table before re-raising a question.

## What this builds

A web replacement for `docs/Work Package.xlsx` — a DSEP AI project work-package board (35 rows across Phase 0–3). Vue3 + TypeScript + Tailwind + antd + ag-grid Community on the front, FastAPI on the back, MariaDB behind it.

## This code gets transplanted — treat host-coupling as a defect

Neither half of this repo ships as a standalone application. The frontend will be consumed as a **Module Federation remote** by another project; the backend will be **lifted into an already-running FastAPI project**. Both must therefore be host-agnostic modules, and anything that assumes it owns the process is a bug rather than a style issue.

**Backend — a mountable module, not an app.** No `FastAPI()` instance in library code; expose `APIRouter`s behind a single `create_wp_router(...)` factory with a configurable prefix. No engine constructed at import time — the host supplies its own session factory without editing module files. No import side effects at all: no CORS, middleware, logging config, or `create_all()`. Own `Base`, `wp_`-prefixed table names, no foreign keys into host tables. Settings namespaced under a `WP_` env prefix. `backend/app/standalone.py` is the only place an app exists, and it is dev-only.

**Frontend — a well-behaved federated remote.** Expose components, not an app; `src/dev/` is a local harness that never ships. The failure mode that matters most is **global CSS leaking into the host**: Tailwind runs with `corePlugins.preflight: false` plus a `wp-` prefix and `content` scoped to this package, and antd's global reset stays out. No `vue-router` import or assumption — navigation goes through props or injected callbacks so the host owns routing. No reliance on a host-provided active Pinia, and no module-scope mutable state that two mounted instances would share. API base URL and tokens are read at **runtime** via props or `configure()`, never `import.meta.env` at module scope — that bakes the dev value into the federated bundle. Declare `vue`, `ant-design-vue`, `ag-grid-community`, `ag-grid-vue3` as federation singletons. The exposed component must survive repeated mount/unmount, tearing down grid instances, listeners, and timers.

`backend/INTEGRATION.md` and `frontend/INTEGRATION.md` are deliverables, not afterthoughts: exposed surface, dependency versions, wiring steps, env vars, and which files are dev-only. Root `INTEGRATION.md` is the contract they specialize.

**Makers (설비사) belong to the host, not to us.** A maker has many **projects** (templates are central and maker-free, `plan.md` §0.1), but the maker table already exists in the host project — never create one here. `wp_projects.maker_id` is a plain `INT` with an index and **no physical foreign key**, because the target table may live in another schema entirely and a constraint would break the transplant DDL. Never JOIN to a maker table; queries stop at the id. When a maker's name is needed, go through the injectable `MakerResolver` port — and treat "no resolver configured" as a normal state that returns `maker_id` alone rather than an error. Dangling `maker_id` values must not break reads; referential integrity is the host's responsibility. The dev-only `wp_dev_makers` stub lives in `db/dev_seed.sql`, never in `db/schema.sql`.

`document_types` is global across makers, so it is the likely merge point with an equivalent host table — keep its access isolated behind one repository so the swap is cheap.

## Agents

Three subagents divide this work — see `.claude/agents/`:

| Agent | Owns | Notes |
|---|---|---|
| `backend-dev` | `backend/`, `db/` | Does not touch `frontend/` |
| `frontend-dev` | `frontend/` | Does not touch `backend/` or `db/` |
| `plan-reviewer` | — | Read-only audit against `plan.md` + transplantability |

## Environment (verified, not assumed)

| | |
|---|---|
| DB | **MariaDB 11.2.2**, not MySQL. `localhost:3306`, user `user01`, full DDL privileges. The password is **not in this repo** — it comes from `WP_DB_PASSWORD` (ask the user, or read it from your own shell env). |
| Target DB name | `` `iai-test` `` — the hyphen means **every SQL reference needs backticks**. |
| DSN | `mysql+pymysql://user01:<WP_DB_PASSWORD>@localhost:3306/iai-test?charset=utf8mb4`, supplied via `WP_DB_DSN`. The password contains `#`, which **must** be percent-encoded as `%23` or the DSN silently truncates. |
| Python | 3.8.8 is the global Anaconda interpreter — too old for SQLAlchemy 2.x / Pydantic v2. Create a 3.11+ venv for `backend/`. |
| Node | v24.12.0 |
| Tooling | No `mysql` CLI on PATH. Use `pymysql` from Python for all DB work. |

## Working with the source documents

Windows console output mangles Korean (cp949 mojibake). **Never print Korean DB rows or Excel cells straight to stdout** — write UTF-8 to a temp file and `Read` it instead:

```python
import pandas as pd, json, io
df = pd.read_excel('docs/Work Package.xlsx', sheet_name='Project Board', header=None)
io.open('_tmp.json','w',encoding='utf-8').write(
    json.dumps(df.where(pd.notna(df), None).values.tolist(), ensure_ascii=False, indent=1))
```

Same pattern for `SHOW CREATE TABLE` dumps. Delete the temp file when done.

Excel quirks that drive the schema: `관련 문서` and `Owner` are both multi-valued and become N:M tables. `Owner` splits on `+`. **`관련 문서` must NOT be split on `/`** — document ②'s own name is "DSEP Readiness & **I/O** Spec", so a naive split yields `"② DSEP Readiness & I"` / `"O Spec"`. Tokenize on the circled markers ①–⑤ instead. `Phase`/`Milestone` embed their numbers in the name string (`Phase 0. Pre-Infrastructure Setup`, `0.1 DSEP 환경 Gap 및 자원 구성`); splitting those into integer columns is the point of requirement 1.

`docs/dashboard.jpg` is the visual reference for Phase color banding. `docs/~$Work Package.xlsx` is an Excel lock file — ignore it.

## Prior art: the `dsep_iai` database

A previous iteration of this system already exists on the same server as DB `dsep_iai` (`wp_templates` → `wp_template_versions` → `wp_template_items` with 105 rows, plus `wp_phases`, `wp_milestones`, `makers`, `maker_boards`, `document_types`). **Leave it intact** — the new work goes in `iai-test`.

Consult it for naming and structure, but note what it got wrong and this design fixes: `phase`/`milestone` still stored as `varchar` alongside unused nullable `phase_id`/`milestone_id`; `owner` and `doc_code` as single strings despite the source being multi-valued; no publish-time validation.

## Domain invariants

These are the non-obvious rules that most of the code exists to enforce.

**Two tiers** (`plan.md` §0, revised 2026-08-07 — it overrides anything below that conflicts).
*기준 데이터*: central, maker-free WP **templates**, versioned `DRAFT → PUBLISHED → ARCHIVED`,
plus the global document master. *프로젝트*: a maker's board, created by deep-copying one
published template version, with **no versions at all** — creation is the commit and every
later edit saves directly. Phases, milestones and owners are copied per project, not shared,
so their ids differ from the template's; a cross-tier reference is a 400. The grid itself —
renumbering, boundary rules, drag confinement, gray rows — is identical on both, and there is
one implementation of it (`tier` on the board store, `BoardScope` on the API client). Two
federated exposes, one per host menu: `./MasterAdmin` and `./ProjectWorkspace`.

**Contiguity.** Rows sharing a `phase_id` must be adjacent in `sort_order`; milestones must be adjacent within their phase block. Numbering is derived from *first appearance order* while scanning rows top to bottom, so fragmented blocks make numbering undefined.

Unassigned rows are **transparent** to it (`plan.md` §0.2.1): `P0 P0 [gray] P0` is one block, not a violation. The contiguity check, the block flags and the drag rule must all read the list that way — if one of them treats a gray row as opaque, the UI starts offering actions the server rejects.

Row *insertion* used to preserve contiguity structurally, by inheriting the phase/milestone of the row above. **That is gone** (§0.2). Both add paths — toolbar append and the per-row `+` — now create an unassigned *gray* row, because an inherited row is born inside a block and a block-confined drag can never leave one, which left no way at all to open a new Phase between two existing ones. Contiguity now holds because null is transparent, not because the new row was trapped.

Row *drag* never preserved it, and the claim that it did was the bug (`plan.md` §2.2, revised 2026-08-07). Re-inheriting a dragged row's membership from its new predecessor silently reclassified any row dropped past a phase boundary — the user asked to reorder and got a re-classification, and dragging out a phase's last row deleted that phase. So **a dragged row keeps its own membership and only changes position**, and an *assigned* row's drag is confined to the contiguous run of rows sharing its `phase_id` *and* `milestone_id` (`frontend/src/composables/useBlockDrag.ts`). Membership changes only through the Phase/Milestone cell editors.

A **gray row is the exception: it may be dropped anywhere** (§0.2.2) — it has no block to leave and cannot break contiguity. That asymmetry is not a convenience; it is the entire mechanism for "insert a new Phase between two existing ones": add a gray row, drag it to the seam, create the Phase there, and first-appearance renumbering gives it the number in between with no insertion logic anywhere.

Two consequences worth knowing before touching `reorder`:
- Rows carry membership, so a permutation that interleaves two blocks still fragments them. The server's contiguity check on `reorder` is the **primary defence**, not a backstop — do not remove it on the grounds that the endpoint no longer accepts membership.
- Contiguity alone is not the whole rule. `[A/Phase0, B/Phase1]` with `A` dragged to the end stays contiguous, so the server accepts it while Phase 1 silently becomes Phase 0. Only the client can tell a reorder from a reclassification, because only the client saw the gesture.

**Milestone major number is derived, never stored.** Display `1.2` = owning phase's `seq_no` + `.` + `milestones.seq_no`. Storing the major separately lets the two drift when a phase is renumbered.

**Boundary rule for creating phases/milestones.** One question, asked of every row: *would creating here leave the board contiguous?* For an assigned row that means it must sit at an edge of its own block. For a gray row it means its nearest assigned neighbours above and below must differ, or it must have none on one side (§0.2.4) — a gray row parked mid-block may **not** create, even though it is trivially a "boundary". §2.3's original "an unassigned row is always a boundary, so it may always create" was half right and gave the wrong answer for exactly that case. The server computes `is_phase_block_start/end` and `can_create_phase` per row and returns them in the item payload — **keep this judgment server-side** so the rule lives in one place rather than being reimplemented in the cell editors.

**Renumbering authority.** The server recomputes and returns the full item list after every insert/move/delete. The client may renumber optimistically for responsiveness but must overwrite with the response.

**Version state machine — templates only.** `DRAFT → PUBLISHED → ARCHIVED`, at most one DRAFT and one PUBLISHED per template. Creating a draft deep-copies the published version's items and relations. `PUBLISHED`/`ARCHIVED` items are immutable — block writes at the API layer. A **project has none of this**: no draft, no publish, no discard, no history. Do not add a disabled publish button to the project board; the operation does not exist there, and `validate`/`publish` take a version id that a project does not have.

**Two save paths with different contracts.** 임시저장 (template) and 저장 (project) both persist whatever is on screen with **no validation** — `phase_id` and `milestone_id` are nullable precisely to allow this, which is what lets gray rows exist. 발행 (publish) runs the full rule set V1–V14 in `plan.md` §2.5 and returns per-cell error locations so the grid can highlight them. Gray rows are caught there and **only** there; on a project they may persist forever.

**Master data scoping.** `document_types` is global and shared by every template and project — never copied. Owners, phases and milestones are scoped to **one template or one project**, and a project's are copies made at creation, so the same phase name exists twice with different ids. Fetch them through the scoped URL and never filter by an owner id on the client. Never hard-delete master data that is in use — deactivate via `is_active` and have the delete endpoint report the usage count.

## ag-grid Community constraints

The free plan excludes Row Grouping, Excel Export, Context Menu, and Range Selection. Consequences for this codebase:

- Phase grouping is rendered with a cell renderer that shows the label only on the block's first row, plus per-phase color banding — **not** row grouping.
- Avoid `colDef.rowSpan`; it interacts badly with managed row drag. Verify before relying on it.
- Export goes through CSV (Community) or backend-generated openpyxl.

Managed row drag, custom cell editors/renderers, and CSV export are all available in Community.

## Commands

None yet — no build, lint, or test tooling exists. When scaffolding, the planned layout is `backend/` (FastAPI, venv on 3.11+) and `frontend/` (Vite), with SQL artifacts in `db/`. Add the concrete commands to this file once they exist.

Quick DB check:

```bash
# WP_DB_PASSWORD must be set in the environment first.
python -c "import os,pymysql; c=pymysql.connect(host='localhost',port=3306,user='user01',password=os.environ['WP_DB_PASSWORD']); \
cur=c.cursor(); cur.execute('SHOW DATABASES'); print([r[0] for r in cur.fetchall()])"
```

## Language

The user writes in Korean; `plan.md` and user-facing strings are Korean. Match that in documents and UI copy. Code identifiers stay English.
