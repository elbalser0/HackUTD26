# Handoff: Argus front-end rebuild (next agent starts here)

Rewritten 2026-11-08 after the employee flow, role detection, palette, admin Overview, All records and the admin
Record page were built. Read this top to bottom; it is meant to be enough on its own. `docs/HANDOFF.md` is the older
project handoff and still describes the pre-redesign UI.

## 1. Where things stand

Branch `feat/tiger-cloud`, **pushed, and open as one PR: https://github.com/elbalser0/HackUTD26/pull/26 (into `main`)**. Tree clean when this was written. Main (PRs #23 to #25: CLI
polish, dotenv, personas backend) is already merged in.

| Commit | What |
|---|---|
| `1b41f56` | Tiger Cloud (TimescaleDB) persistence, `GET /api/admin/analytics`, migrations, this handoff |
| `0f625e3` | Employee Records page |
| `b4532d8` | Merge of `origin/main` |
| `27e29f1` | Role detection via `/api/me`, employee command palette |
| `c5739a3` | Admin shell and Overview |
| `8c0463a` | Admin All records (Records and Events views) |
| `15da602` | Admin Record page (read-only) |

### Built (front end, all in `src/`)
| Screen | Route | Notes |
|---|---|---|
| Employee Records | `#/` and `#/records/<id>` | Top bar (logo, "Search records ⌘K", Admin link for admins, account menu), tabs Needs a reason / Explained / Resolved with counts, list + detail panel, report form (reason + Keep/Revert/Undecided, Undecided sends `unsure`), collapsed History. `components/Records.tsx` |
| Employee palette | ⌘K / Ctrl+K anywhere on the employee page | Client-side search over the loaded records (resource, summary, who explained it; not the reason text) plus the three filters. `components/Palette.tsx`, `palette.ts`, `paletteContext.ts`, `components/PaletteContext.tsx` |
| Admin Overview | `#/admin` | KPIs, "Open without a reason", hourly chart (bars with events link to the Events view), run outcomes. From `/api/admin/overview`. `components/Overview.tsx`, `overview.ts` |
| Admin All records | `#/admin/records`, `#/admin/events` (`?hour=<ISO>`) | Records view: live client-side filters. Events view: server-side filters via Apply; hour chip comes from the URL. `components/AllRecords.tsx`, `allRecords.ts`, `events.ts` |
| Admin Record | `#/admin/records/<id>` | Read-only: Explained by + reliability, Intent + when set, Linked run, What changed, Full history (newest first), Gaps, limitations. `components/AdminRecord.tsx` |
| Admin shell | wraps the three admin pages | ADMIN sidebar (Overview, All records), Admin badge. `components/AdminShell.tsx` |

**Who gets what:** `components/TopBar.tsx` and `AdminHome` in `src/App.tsx` call `api.me()` (`GET /api/me`). Only
`role === "admin"` gets the admin shell. Anyone else, **and any `/api/me` failure**, gets the old token-gated admin screen
(`components/Admin.tsx`), so access still fails closed through the server. `me` only picks the layout; the server enforces
access on every route. The same `AdminHome` element serves every admin path so the legacy screen keeps its in-memory
token when you move between `#/admin` and a record timeline (a test guards this).

### Test and check commands (repo root)
```
npm test          # vitest: 245 passing when last run (11 files)
npm run lint      # oxlint, clean
npm run build     # tsc -b && vite build, ok
cd backend && .venv/bin/python -m pytest -q     # SQLite only; Postgres cases skip. 486 passed, 39 skipped
BG_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:54329/postgres .venv/bin/python -m pytest -q   # 486 passed, 1 skipped
BG_TEST_BACKEND=postgres BG_TEST_DATABASE_URL=... .venv/bin/python -m pytest -q   # whole suite on Postgres
```
The local TimescaleDB is a Docker container, `argus-tsdb-test`, port 54329 (`docker start argus-tsdb-test` if stopped).
`src/docs.test.ts` guards doc wording (for example the product is "Argus", never "Break-Glass", in prose), so run
`npm test` after any doc edit.

**What has NOT been verified:** nothing front-end has run against the real API on Tiger. Everything was checked with stub
adapters (vitest) and the fixture adapter in Chrome at desktop width (`?fixture` = employee, `?fixture=admin` = admin).
**Phone width was only checked for the employee Records page**, not for the palette, Overview, All records or Record page.
Not verified live: the Google-admin path, 401/403/503 in the new screens, the real `/api/me` and `/api/admin/overview`.

## 2. Rules the user has set (follow these)
- **Never read, grep, cat or source `.env`.** Give the user a command to run instead, for example
  `! set -a && . ./.env && set +a && <command>` from the repo root (ask for output, not secrets). Main now also loads
  `BG_*` from the repo-root `.env` itself (`backend/breakglass/config.py`); check how that interacts with
  `BG_DATABASE_URL` without reading the file.
- **Test first**: write the failing test, see it fail for the right reason, implement, then **mutation-check** the
  important logic (break it on purpose, confirm a test fails, restore). This session found real gaps that way; keep doing it.
- The PRD (`docs/Break-Glass Handoff — PRD.md`) is the source of truth.
- **Commit, push, PR and merge only when asked.** Branch off `main`; `gh pr merge --merge`. The user has been saying
  "commit this" after each slice.
- Report what is verified on real systems versus mocked. Do not overclaim.
- Never touch cloud state (Terraform/DigitalOcean) without the user.

## 3. The design (source for the rebuild)

Canvas: **https://claude.ai/artifact/2VqyQppbv3TyULPiHyv3pe** (Design artifact). Read files with the Artifact tool:
`action: "read"`, `url`, `paths: ["project/Palette.dc.html", ...]`. **The user edits the canvas by hand**, so always
`read` before relying on it, and do not publish to it (it overwrites their edits). Files: `project/argus.css`
(tokens + components, already ported to `src/argus.css`, nested under `.ar`), `canvas.json`, and the artboards:

| File | Screen | Built? |
|---|---|---|
| `Employee.dc.html` | Employee Records | yes |
| `Mobile.dc.html` | Employee records, phone | layout is responsive; only desktop and 375 px were eyeballed |
| `Palette.dc.html` | Employee palette | yes |
| `Main.dc.html` | Admin Overview | yes |
| `AdminRecords.dc.html` | Admin All records, Records view | yes |
| `AdminLog.dc.html` | Admin All records, Events view | yes |
| `Record.dc.html` | Admin record | yes |
| `AdminPalette.dc.html` | Admin palette | **no, next** |

Look: dark NMC style, Roboto, accent `#2b9cfc`, surface `#101216`, border `#272b32`.

### Decisions already made (do not relitigate)
1. Two role-separated flows. Admin = email in `BG_ADMIN_EMAILS` (Firebase) or the shared `BG_ADMIN_TOKEN`.
2. Employee view: no sidebar; all open records are visible (the open question "all or only theirs?" is still unanswered by the user; the build assumes all).
3. Admin view: sidebar ADMIN with Overview and All records only; read-only; no edit form. The old separate "Activity log" page is gone; Events live under All records.
4. Palette on every screen. Employee: records + the three filters only. **Admin (not built): records, events, and a "Go to" group (Overview, All records).** Large data should eventually search server-side (`q`), client-side first.
5. Copy rules: short; no marketing paragraphs; always say detected time is "when the scanner noticed, not when the change was made"; reports show who *submitted*, never who made the change; "counts events, not incidents"; **unknown outcome is never failure**.
6. Overview chart: selecting a bar opens that hour in the Events view (decided and built; chip clears it).

### Deliberate deviations from the mockups (all noted to the user)
- No sidebar count badge on All records and no "Events · N" in the view switch (each needs an extra request). The Records tab does show its count.
- Records filters apply live (no Apply button); Events filters use Apply.
- Range on the Events view has an "All time" option and is disabled while an hour chip is active.
- Overview KPIs are not links (their targets did not exist when it was built). **They can be linked now:** Open records -> `#/admin/records`, Last apply and Events -> `#/admin/events`. Check the current `Main.dc.html` first.
- The admin shell has no search button yet (palette not built).

### Fixture data is made up
`?fixture` data in `src/fixtures.ts` is fake, including `adminOverview`, `adminEvents`, `adminRecordTimeline` (the fixture
chart hours do not line up with the fixture events, so clicking a bar shows 0 matching there). Build against the real API.

## 4. API facts the front end relies on (`docs/API.md` is the contract)
- `GET /api/me` -> `{signed_in, email, display_name, role: admin|employee|null, auth_mode}`. Shared token -> admin with `signed_in:false`.
- With Firebase configured, **every read needs the ID token** (`/api/health` stays open). `src/api.ts` `signedInHeaders()` sends it; every new adapter method must too.
- `GET /api/records` (all) returns `reporter_assurance` and `last_activity {at,type}`. `GET /api/records/{id}/events` is the record history for employees.
- `GET /api/admin/overview?window=24h|7d`, `GET /api/admin/log` (filters `engineer, resource, outcome, type, since, until, limit<=500`, **no paging**), `GET /api/admin/records/{id}/timeline` (oldest first, with `gaps`), `GET /api/admin/analytics` (our branch; **unused by the UI**, kept for later).
- All wire knowledge lives in `src/api.ts` (snake_case in, camelCase out; `fromWire*`). Adapters: real, fixture (`?fixture`), and a `setAdapter` test hook. `Adapter` methods are all required, so any new one must also be added to every test stub (five test files build full adapters; most spread `fixtureAdapter` now).

## 5. What to do next (suggested order)
1. **Admin ⌘K palette** (`AdminPalette.dc.html`; read it first). Records (matching resource, summary or who explained it), events, and a "Go to" group (Overview, All records). Reuse `Palette.tsx` / `paletteContext.ts`; the employee palette is client-side over `listRecords`. Events need the admin log (`adminEvents`), so decide with the user: search the already-loaded page of events client-side first, or add a server `q`. Add the "Search records and events ⌘K" button to the admin top bar in `AdminShell.tsx`. Tests: open/close, arrows, Enter, focus trap, Esc, groups with counts, and that an employee never gets the admin groups.
2. **Link the Overview KPIs** (see deviations) once the user confirms against the current canvas.
3. **Phone-width pass** (375 and 320 px) for the palette, Overview, All records (tables use `.scroll-x`), and the admin Record page; `src/mobile.test.ts` only reads `App.css` as text and guards nothing in `argus.css`. Consider tap targets >= 44 px.
4. **Shared-token admin:** the offline fallback still works only through the old `Admin.tsx` screen (token held in React state, never URL or storage). Decide with the user whether the new admin shell should accept it (it cannot read `/api/records`; `/api/me` reports admin only if a Bearer shared token is sent).
5. **Cleanup:** `components/RecordDetail.tsx` is now unused (dead code); `RecordList.tsx` is only used for its `Freshness` export (move it); `Admin.tsx` is still used by non-admins. Remove only with the user's OK and keep `src/App.test.tsx` / `admin.test.tsx` meaningful. `App.css` still styles the apply-run page and legacy admin screens (`/#/apply/<id>` still uses the old layout, not redesigned).
6. **Verify live** (user runs the API; see section 7): desktop and phone widths, 401/403/503 in the new screens, a real unknown run outcome, the Google-admin path.
7. **Docs:** update `docs/FRONTEND.md` (still describes the pre-redesign UI and a different branch), `docs/API.md` (UI routes if any), `README.md`, honestly, then run `npm test` (`src/docs.test.ts`). Also open on the backend side (not front-end work): bounded admin reads, a TimescaleDB CI job, a Tiger runbook, a non-DDL runtime DB role; see git history of this file for the old list.

## 6. Open questions for the user
- Employee visibility: all open records (built) or only ones they reported? Reports are self-declared, so "mine" is not trustworthy.
- Admin palette: is client-side search over the first 100 loaded events acceptable, or do they want server-side `q` now?
- Should the Overview KPIs link to All records / Events (targets exist now)?
- Push and PR: **done, one PR (#26)** for the whole branch (Tiger backend + UI redesign). Do not split it. Further commits on `feat/tiger-cloud` go into that PR; push only when the user asks. Merge only when asked (`gh pr merge --merge`).

## 7. How to run things
- API against Tiger (user runs it, from repo root): `! set -a && . ./.env && set +a && cd backend && .venv/bin/uvicorn breakglass.api:app --port 8000`
- UI: `npm run dev` (Vite proxies `/api` to `127.0.0.1:8000`; `?fixture` for no backend, `?fixture=admin` for the admin persona).
- CLI is `backend/.venv/bin/python -m breakglass.cli ...` from the repo root. `breakglass migrate-schema`, `breakglass import-sqlite --source PATH [--dry-run]`.
- Check which backend the API is on: save a report in the UI, then `show` the record in the CLI with `.env` sourced.
- The user's local `backend/breakglass.db` is the rollback copy of the pre-Tiger history; leave it alone.
- Browser checks: use the Chrome tools (load them with ToolSearch, call `tabs_context_mcp` first, create your own tab, close it when done). Start Vite on a spare port (`npm run dev -- --port 5199`) and kill it after.

## 8. Backend state (unchanged by the UI work)
Tiger Cloud service `db-75657` (PostgreSQL 18.6, trial) is live; history imported; API and CLI verified on it.
`BG_DATABASE_URL` set -> PostgreSQL for both API and CLI with no fallback; unset -> SQLite at `BG_DB_PATH`. Events are a
TimescaleDB hypertable; `activity_hourly` is a real-time continuous aggregate. An unreachable or read-only DB gives API
**503** `storage_unavailable`. The merged main code (`admin.overview`, `records_out`, `/api/me`) passes the whole backend
suite on SQLite and on Postgres. Not verified live: API analytics/overview over HTTP against Tiger, read-only service
behaviour, a real Terraform apply (none authorized).
