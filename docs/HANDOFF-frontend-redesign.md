# Handoff: Argus front-end rebuild (next agent starts here)

Read this top to bottom; it is meant to be enough on its own. `docs/HANDOFF.md` is the older
project handoff and still describes the pre-redesign UI.

## 1. Where things stand

**PR #26 is merged into `main` (merge commit `1cd91c5`, 2026-11-08, CI green).** It carried the Tiger Cloud backend, the whole
front-end redesign and the slices below. `feat/tiger-cloud` is merged and finished; branch new work off `main`. Rewritten
2026-11-08 after the admin palette, KPI links, cleanup, phone pass and a live check against Tiger.

### Built (front end, all in `src/`)
| Screen | Route | Notes |
|---|---|---|
| Employee Records | `#/` and `#/records/<id>` | Top bar (logo, "Search records ⌘K", Admin link for admins, account menu), tabs Needs a reason / Explained / Resolved with counts, list + detail panel, report form (reason + Keep/Revert/Undecided, Undecided sends `unsure`), collapsed History. `components/Records.tsx` |
| Employee palette | ⌘K / Ctrl+K | Client-side over the loaded records (resource, summary, who explained it; not the reason text) plus the three filters. `components/Palette.tsx`, `palette.ts`, `paletteContext.ts`, `components/PaletteContext.tsx` |
| Admin Overview | `#/admin` | KPIs, "Open without a reason", hourly chart (bars with events open that hour in Events), run outcomes. **KPIs link:** Open records to All records; Last apply and Events to Events; the Unknown outcome row to Events; "All records" in the card head. Last scan is not a link. `components/Overview.tsx`, `overview.ts` |
| Admin All records | `#/admin/records`, `#/admin/events` (`?hour=<ISO>`) | Records view: live client-side filters. Events view: server-side filters via Apply. `components/AllRecords.tsx`, `allRecords.ts`, `events.ts` |
| Admin Record | `#/admin/records/<id>` | Read-only: explained by, intent, linked run, what changed, full history (newest first), gaps, limitations. `components/AdminRecord.tsx` |
| Admin palette | ⌘K in the admin shell; "Search records and events ⌘K" button in the top bar | Records, events, and a "Go to" group (Overview, All records). **Event search is client-side** (the user chose this over a server `q`): records and the first 100 events (`GET /api/admin/log`, default limit) are fetched when the palette opens. "No match" says it only covers what was loaded, and the Events group says how many of how many were searched. Enter on an event opens its record, or the Events view at that hour when it has no record. `components/AdminPalette.tsx`, `PaletteParts.tsx` (Highlight), `paletteRows.ts` (tag and meta text), `palette.ts` (`eventMatches`, `eventHash`, `GO_TO`) |
| Admin shell | wraps the admin pages | ADMIN sidebar (Overview, All records), Admin badge, owns its own `PaletteProvider`. `components/AdminShell.tsx` |

**Who gets what:** `components/TopBar.tsx` and `AdminHome` in `src/App.tsx` call `api.me()` (`GET /api/me`). Only
`role === "admin"` gets the admin shell. Anyone else, **and any `/api/me` failure**, gets the old token-gated admin screen
(`components/Admin.tsx`), so access still fails closed through the server. `me` only picks the layout; the server enforces
access on every route. The same `AdminHome` element serves every admin path so the legacy screen keeps its in-memory
token when you move between `#/admin` and a record timeline (a test guards this).

**Shared admin token (decided 2026-11-08, option 1):** `BG_ADMIN_TOKEN` stays on the server as the offline fallback and is
used only through the old `Admin.tsx` screen. The new shell does not accept it (it cannot read `/api/records`). It is the
only admin path when Firebase is not configured. Removing it would be its own backend slice (`auth.py`, `api.py`,
`config.py`, `demo.py`, tests on SQLite and Postgres, docs) and only makes sense if the demo always has Firebase.

### Test and check commands (repo root)
```
npm test          # vitest: 276 passing when last run (14 files)
npm run lint      # oxlint, clean
npm run build     # tsc -b && vite build, ok
cd backend && .venv/bin/python -m pytest -q     # SQLite only; Postgres cases skip. 486 passed, 39 skipped (not re-run in the 2026-11-08 front-end work)
BG_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:54329/postgres .venv/bin/python -m pytest -q   # 486 passed, 1 skipped
BG_TEST_BACKEND=postgres BG_TEST_DATABASE_URL=... .venv/bin/python -m pytest -q   # whole suite on Postgres
```
The local TimescaleDB is a Docker container, `argus-tsdb-test`, port 54329 (`docker start argus-tsdb-test` if stopped).
`src/docs.test.ts` guards doc wording (for example the product is "Argus", never "Break-Glass", in prose), so run
`npm test` after any doc edit. `src/argusMobile.test.ts` reads `argus.css` as text and guards the phone rules (44px tap
targets, wrapping of long names and hashes, `.top` height, `.tag` wrapping); `src/mobile.test.ts` does the same for `App.css`.

### What is verified, and how
**Live (2026-11-08): real API on Tiger Cloud, Chrome at desktop width, signed in with Google, first as a non-admin and then as an admin.**
- `/api/me` role detection. A non-admin got a real `403 not_admin` and the UI failed closed to the old token screen.
- Employee Records page on real Tiger records, no Admin link.
- Admin Overview, All records, Events, Record page and the admin palette on real data (events from several real actors, with "verified sign-in" vs "self-reported" vs "local user, not verified").
- 375 and 320 px (in iframes in the signed-in tab, not a real phone): no horizontal overflow on Overview, All records, Events, the admin Record page and the employee page.
- Real data found three bugs that fixtures hid (a plan hash and a long resource name that did not wrap, the legacy `header { height: 58px }` in `App.css` clipping the wrapped top bar, a clipped DEMO DATA tag). Fixed and guarded in `argusMobile.test.ts`.

**Stubs and fixtures only:** every unit and component behaviour (vitest stub adapters), and the fixture adapter in Chrome.

**Scratch-stack check (2026-11-08, later): real API on local TimescaleDB (`argus-tsdb-test`, scratch DB dropped afterwards), not Tiger.** A real unfinished run, a real 503 and the employee palette were checked in Chrome. Unknown shows as Unknown (Overview KPI, Run outcomes, Record page gap box), never failed. A 503 shows an error with Retry in the admin Overview and the employee page. The Google gate was bypassed: `BG_NO_DOTENV=1` API on a scratch DB, a tiny proxy adding a throwaway shared-token header, and Vite started with the four `VITE_FIREBASE_*` variables blanked on the command line (real env vars beat `.env.local`).

**NOT verified live:**
- A real unknown run outcome on Tiger (Tiger data has Cancelled and Kept runs only), the shared-token screen, and the 503 on All records, Events and the Record page (only Overview and the employee page were looked at).
- A real phone. Tables use `.scroll-x`; inline resource links in table rows are still about 15px tall.
- Backend side: API analytics and overview over HTTP against Tiger under load, read-only service behaviour, a real Terraform apply (none authorized).

**Gotcha found 2026-11-08:** a stale `uvicorn` from before the main merge was still on port 8000. It had no `/api/me` or
`/api/admin/overview` and served `/api/records` without a token. Check `lsof -nP -iTCP:8000 -sTCP:LISTEN` and
`curl /api/me` before blaming the UI. The first palette load on Tiger took a few seconds (two requests); not measured.

## 2. Rules the user has set (follow these)
- **Never read, grep, cat or source `.env`.** Give the user a command to run instead, for example
  `! set -a && . ./.env && set +a && <command>` from the repo root (ask for output, not secrets). The backend loads
  `BG_*` from the repo-root `.env` itself (`backend/breakglass/config.py`), **including `BG_DATABASE_URL`**, so a
  plain backend start uses Tiger when that line is in `.env` (a terminal value wins).
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
| `AdminPalette.dc.html` | Admin palette | yes |

Look: dark NMC style, Roboto, accent `#2b9cfc`, surface `#101216`, border `#272b32`.

### Decisions already made (do not relitigate)
1. Two role-separated flows. Admin = email in `BG_ADMIN_EMAILS` (Firebase) or the shared `BG_ADMIN_TOKEN`.
2. Employee view: no sidebar; all open records are visible (the open question "all or only theirs?" is still unanswered by the user; the build assumes all).
3. Admin view: sidebar ADMIN with Overview and All records only; read-only; no edit form. The old separate "Activity log" page is gone; Events live under All records.
4. Palette on every screen. Employee: records + the three filters only. Admin (built): records, events, and a "Go to" group (Overview, All records). Large data should eventually search server-side (`q`), client-side first.
5. Copy rules: short; no marketing paragraphs; always say detected time is "when the scanner noticed, not when the change was made"; reports show who *submitted*, never who made the change; "counts events, not incidents"; **unknown outcome is never failure**.
6. Overview chart: selecting a bar opens that hour in the Events view (decided and built; chip clears it).

### Deliberate deviations from the mockups (all noted to the user)
- No sidebar count badge on All records and no "Events · N" in the view switch (each needs an extra request). The Records tab does show its count.
- Records filters apply live (no Apply button); Events filters use Apply.
- Range on the Events view has an "All time" option and is disabled while an hour chip is active.
- (Resolved) Overview KPIs now link as the current `Main.dc.html` draws them.

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
Done 2026-11-08: admin palette, linked KPIs, phone pass (admin and employee, fixtures and real data), shared-token decision,
dead-code cleanup (`RecordDetail.tsx`, `RecordList.tsx` removed; `Freshness` in `components/Freshness.tsx`), `docs/FRONTEND.md`
and `README.md`.
1. **Remaining live checks:** a real phone, the shared-token screen, and the 503 on the other admin pages. The Google sign-in needs the user; do not sign in for them.
2. **Table tap targets:** inline resource links inside table rows are about 15px tall; enlarging them needs a row layout decision (`AllRecords.tsx` sets `minHeight: 0` deliberately).
3. **Apply-run page** (`#/apply/<id>`) still uses the old layout and `App.css`; `Admin.tsx` and the legacy admin styles remain for non-admins. Redesign only if the user asks.
4. **Optional:** server-side `q` on `GET /api/admin/log` if client-side search over 100 events proves too narrow (backend change, tests on SQLite and Postgres, `docs/API.md`). Bounded admin reads, a TimescaleDB CI job, a Tiger runbook and a non-DDL runtime DB role are also still open on the backend side.
5. **Docs:** `docs/API.md` has no UI routes; add only if the user wants them.

## 6. Open questions for the user
- Employee visibility: all open records (built) or only ones they reported? Reports are self-declared, so "mine" is not trustworthy. Still unanswered.
- Should the shared admin token be removed entirely later (backend slice)? Depends on whether the demo always has Firebase.
- Commit, push, PR and merge only when asked. The user has been saying "commit this", "push", "merge" after each slice.

## 7. How to run things
- API against Tiger (user runs it): `cd backend && .venv/bin/uvicorn breakglass.api:app --port 8000` (Windows: `.venv\Scripts\uvicorn.exe`). `BG_DATABASE_URL` and the other `BG_*` settings come from the repo-root `.env`; sourcing it is no longer needed for the API.
- UI: `npm run dev` (Vite proxies `/api` to `127.0.0.1:8000`; `?fixture` for no backend, `?fixture=admin` for the admin persona).
- CLI is `./argus ...` from the repo root. `argus migrate-schema`, `argus import-sqlite --source PATH [--dry-run]`.
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
