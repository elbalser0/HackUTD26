# Handoff: Argus front-end rebuild (next agent starts here)

Written 2026-11-08 by the agent that did the Tiger Cloud integration and the redesign mockups. The previous
context was very long; this file is meant to be enough on its own. `docs/HANDOFF.md` is the older project handoff
and still describes the pre-redesign UI.

## 1. Where things stand

| Area | State |
|---|---|
| Tiger Cloud persistence | **Built, tested, live.** Backend runs on Tiger (service `db-75657`, PostgreSQL 18.6, Oregon, trial). Schema migrated, real history imported, API and CLI verified on it. |
| Analytics endpoint | `GET /api/admin/analytics` exists and is tested (SQLite and TimescaleDB). **No UI uses it yet.** |
| Redesign | Mockups agreed with the user in a Design canvas (section 3). **Not built in React yet. That is your job.** |
| Git | Everything is **uncommitted on branch `feat/tiger-cloud`** (off `main` at `4c72cee`). Do not commit or push until the user asks. |

### Backend work on `feat/tiger-cloud` (uncommitted)
New: `backend/breakglass/{postgres,storage,migrate,analytics}.py`, `backend/breakglass/migrations/postgres/001_initial.sql`,
`002_event_rollups.sql`, tests `test_database_contract.py`, `test_storage_config.py`, `test_storage_wiring.py`,
`test_analytics.py`, `test_migrate.py`, `pg_helpers.py`. Modified: `api.py`, `cli.py`, `config.py`, `db.py`, `models.py`,
`service.py`, `pyproject.toml`, `tests/helpers.py`, `.env.example`.

What it does:
- `BG_DATABASE_URL` set -> PostgreSQL (Tiger) for **both** API and CLI, no fallback; unset -> SQLite at `BG_DB_PATH`.
- Events live in a TimescaleDB hypertable; `activity_hourly` is a real-time continuous aggregate.
- Unreachable/read-only DB -> `StorageUnavailable` -> API **503** `storage_unavailable`; Terraform apply never runs if the review isn't durable.
- CLI: `breakglass migrate-schema`, `breakglass import-sqlite --source PATH [--dry-run]`.
- Connection pool (psycopg_pool), per-environment advisory locks, row locks on report/decide.

### Tests (all green when last run)
```
cd backend
.venv/bin/python -m pytest -q                                   # SQLite only; Postgres cases skip
BG_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:54329/postgres .venv/bin/python -m pytest -q   # 438 passed, 1 skipped
BG_TEST_BACKEND=postgres BG_TEST_DATABASE_URL=... .venv/bin/python -m pytest -q   # whole suite on Postgres (leaves bgtest_* schemas)
```
The local TimescaleDB is a Docker container: `argus-tsdb-test`, port 54329 (`docker start argus-tsdb-test` if stopped).
Frontend: `npm run lint`, `npm test`, `npm run build` (repo root). `src/docs.test.ts` guards doc wording
(for example the product is "Argus", never "Break-Glass" in prose), so keep doc edits honest and run `npm test`.

The same Postgres tests also passed **on the real Tiger service** (54 tests) using
`BG_TEST_DATABASE_URL="$BG_DATABASE_URL"`; they create and drop throwaway `bgtest_*` schemas.

### Still open on the backend (from the Tiger plan)
- Admin history reads still load all history (`admin._View`). Bounded reads not done (plan Task 6).
- No CI job for TimescaleDB and no benchmark (plan Task 8). `docs/BACKEND.md` (the `BG_DATABASE_URL` variable) and `docs/API.md` (the analytics route) are updated because `src/docs.test.ts` requires it; `README.md`, `docs/PROJECT.md`, `docs/HANDOFF.md` and a Tiger runbook (`docs/TIGER-CLOUD.md` in the plan) are not.
- The app uses the admin DB role (`tsdbadmin`); a non-DDL runtime role is not set up.
- Detection/resolution are record-derived, not events, so analytics does not count them.
- Not verified live: API analytics call against Tiger over HTTP, read-only service behaviour, a real Terraform apply (none authorized).

## 2. Rules the user has set (follow these)
- **Never read, grep, cat or source `.env`.** Give the user a command to run instead. Working pattern from the repo root:
  `! set -a && . ./.env && set +a && <command>` (the `!` prefix runs it in the session; ask for output, not secrets).
  Note the CLI is `backend/.venv/bin/python -m breakglass.cli ...` from the repo root.
- **Test first** (failing test, see it fail for the right reason, then implement; mutation-check important logic).
- The PRD (`docs/Break-Glass Handoff — PRD.md`) is the source of truth.
- Commit, push, PR and merge **only when asked**; branch off `main`; `gh pr merge --merge`.
- Report what is verified on real systems vs mocked; do not overclaim.
- Never touch cloud state (Terraform/DigitalOcean) without the user.

## 3. The design (source for the rebuild)

Canvas (private-ish; currently "anyone with the link"): **https://claude.ai/artifact/2VqyQppbv3TyULPiHyv3pe**
Read files with the Artifact tool: `action: "read"`, `url`, `paths: ["project/Employee.dc.html", ...]`.
Files: `project/argus.css` (shared tokens and components), `canvas.json` (layout), and these artboards:

| File | Screen |
|---|---|
| `Employee.dc.html` | Employee: Records (list + selected record in one panel) |
| `Mobile.dc.html` | Employee: records, phone |
| `Palette.dc.html` | Employee: command palette |
| `Main.dc.html` | Admin: Overview |
| `AdminRecords.dc.html` | Admin: All records, **Records** view |
| `AdminLog.dc.html` | Admin: All records, **Events** view (filtered to one hour) |
| `Record.dc.html` | Admin: one record, read-only |
| `AdminPalette.dc.html` | Admin: command palette |

**The user edits the canvas by hand while you work.** Always `read` a file before changing it and build on that copy;
publishing replaces the file. If you touch the canvas at all, expect an overwrite warning if they saved in between.
(Rebuilding the UI in React should not need to change the canvas.) Look and tokens: dark NMC style, Roboto, accent
`#2b9cfc`, surface `#101216`, border `#272b32`; everything is in `argus.css` (read it for exact values).

### Decisions already made (do not relitigate)
1. **Two role-separated flows.** Employees and admins must not see the same thing. Admin = email in `BG_ADMIN_EMAILS` (Firebase) or the shared `BG_ADMIN_TOKEN`; the server already enforces admin on `/api/admin/*`.
2. **Employee view:** no sidebar. Top bar = ARGUS wordmark (left), a "Search records ⌘K" button, avatar. Page = header ("Manual changes") with filter tabs **Needs a reason / Explained / Resolved**, and one connected panel: record list on the left, selected record on the right (change diff, "What did you change and why?" textarea, intent Keep/Revert/Undecided, Save report, collapsed History). Content spans full width with the top bar's 40px edge padding. The optional "your name" field was removed from the form (you are signed in).
3. **Admin view:** left sidebar labelled ADMIN with **Overview** and **All records** only. An "Admin" badge in the top bar.
   - Overview: KPIs (Open records, Last scan, Last apply, Events 24 h; the first, third and fourth are links), "Open without a reason", the hourly activity chart (from `/api/admin/analytics`; selecting a bar opens that hour in the Events view), Run outcomes (Unknown is shown separately and never merged into failed).
   - All records has a **Records | Events** switch. Records table: Resource, Status, Explained by, Intent, Detected, Last activity; filters Search, Explained by (incl. "Nobody yet"), Intent, Status. Events view: filters Engineer, Resource, Outcome, Range, plus a removable chip like "Hour: Nov 8, 02:00-03:00 UTC".
   - The old separate "Activity log" page was deliberately removed. Events stay because some (a run that ended unknown) belong to no record.
   - Record page (admin): read-only; who explained it and how reliable, intent, linked run, diff, full history, "Gaps" box. No edit form.
4. **Command palette (⌘K / Ctrl+K)** on every screen: type to filter, arrow keys to move, Enter to open, Esc to close; matched text highlighted; groups with counts like `RECORDS · 4`. Employee: records + the three filters only (no events, no pages). Admin: records (matching resource, summary or who explained it), events, and a "Go to" group (Overview, All records). For large data the search should be **server-side** (a `q` parameter, debounced).
5. Copy rules: short; no marketing paragraphs; always say the detected time is "when the scanner noticed, not when the change was made"; reports show who *submitted*, never who made the change; "counts events, not incidents"; unknown outcome is not failure.

### What in the mockups is made up
Only `digitalocean_firewall.web` (Paul, "payment webhook blocked, opened 8443", intent keep) and the Tiger totals
(7 events: 4 reports, 1 review, 2 run-finished) are real. The records `.db`, `.cache`, `.api`, the resolved one, and "Sam"
are **sample data** added to show the multi-record case, and the hour distribution of events in the chart is invented.
KPI numbers on Overview follow the sample set (4 open, 2 without a reason). Build against the real API and fixtures, not these numbers.

## 4. Current front end (what you are replacing)
`src/`: `App.tsx`, `api.ts` (adapter + wire mapping; **all wire knowledge lives here**; fixtures with `?fixture`),
`auth.ts`, `components/{Admin,ApplyRunView,AuthProvider,RecordDetail,RecordList,States}.tsx`, `App.css`, `index.css`,
tests `App.test.tsx`, `admin.test.tsx`, `auth.test.tsx`, `mobile.test.ts`, `docs.test.ts`. Admin currently has its own token
lock screen; the redesign folds admin into one role-aware shell. Keep the API-adapter pattern, fixture mode and the existing wire contracts.

Existing endpoints (`backend/breakglass/api.py`): `GET /api/records`, `/api/records/{id}`, `POST /api/records/{id}/report`,
`POST .../decision`, `GET /api/records/{id}/events`, `/api/apply-runs`, `/api/apply-runs/{id}`, `/api/apply-runs/{id}/events`,
`GET /api/health`, admin-only `GET /api/admin/log`, `/api/admin/records/{id}/timeline`, `/api/admin/analytics`.
`GET /api/admin/analytics?environment=&since=&until=` returns hourly buckets (`start`, `total`, `by_kind`), totals by kind/intent/decision/outcome,
`backend` (`timescaledb` or `sqlite`), `freshness`, `limitations`. Window must be tz-aware ISO, at most 31 days; non-aligned windows are widened to whole hours and the used window is returned.

### Gaps the redesign needs (decide with the user, test first)
- A way for the UI to know "am I admin?" without trial and error (for example a small `/api/me` or reuse of the 401/403 codes already produced by the admin API).
- Record search (`q`) and filters (status, explained-by, intent) on a team-wide records list, and event search for the admin palette. The existing `GET /api/records` and `/api/admin/log` need checking against what the screens require; add what is missing.
- "Needs a reason" is derivable from `reason == null` on open records; confirm against the wire model before relying on it.
- Admin log is unbounded on the server (see backend open items); the Events view should paginate or limit.

## 5. Suggested order
1. Read this file, `docs/Break-Glass Handoff — PRD.md` (R6, R9, R10), `docs/API.md`, `docs/FRONTEND.md`, and the canvas (`argus.css` first).
2. Shared shell + role detection + tokens (port `argus.css` into `src/index.css`/`App.css`), with tests (vitest, fixture adapter).
3. Employee Records page (list/detail panel, filters, report form wired to the existing report/decision endpoints).
4. ⌘K palette component (employee scope first; keyboard behaviour tested: open/close, arrows, Enter, focus trap, Esc).
5. Admin: Overview (analytics chart from the real endpoint), All records (Records and Events views), admin Record page, admin palette.
6. Verify in a real browser at desktop and phone widths against the real API on Tiger (401/403/503 included), then update `docs/FRONTEND.md`, `docs/API.md`, `README.md` honestly.

## 6. How to run things
- API against Tiger (from repo root, user runs it): `! set -a && . ./.env && set +a && cd backend && .venv/bin/uvicorn breakglass.api:app --port 8000`
- UI: `npm run dev` (Vite proxies `/api` to `127.0.0.1:8000`; `?fixture` for no backend).
- Check which backend the API is on: save a report in the UI, then `show` the record in the CLI with `.env` sourced (this was done once and proved the API writes to Tiger).
- The user's local `backend/breakglass.db` is the rollback copy of the pre-Tiger history; leave it alone.

## 7. Open questions for the user
- Employee visibility: all open records, or only ones they reported? (Mockup assumes all; reports are self-declared so "mine" is not trustworthy.)
- What exactly does selecting a chart bar do in the Events view (mockup: filter to that hour, chip clears it)?
- Whether admins also get an employee view link (mockup had one briefly; it was removed in a later edit, check the current Main artboard).
