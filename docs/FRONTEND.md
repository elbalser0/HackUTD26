# Frontend status

Branch: `feat/tiger-cloud` (PR #26). Stack: React + TS + Vite + Vitest. Contract: `docs/API.md`. The redesign follows the Argus design canvas (dark, Roboto, accent `#2b9cfc`); tokens live in `src/argus.css`, nested under `.ar`.

## Screens

Two role-separated flows. `GET /api/me` only picks the layout; the server enforces access on every route. Anyone who is not `role: "admin"`, and any `/api/me` failure, gets the old token-gated admin screen (`components/Admin.tsx`), so access fails closed.

| Screen | Route | Notes |
|---|---|---|
| Employee Records | `#/`, `#/records/<id>` | Tabs Needs a reason / Explained / Resolved, list and detail, report form, collapsed history. No sidebar; all open records are visible. |
| Employee palette | ⌘K or Ctrl+K | Client-side over the loaded records, plus the three filters. |
| Admin Overview | `#/admin` | KPIs (Open records, Last apply and Events link to All records / Events), open without a reason, hourly chart (a bar opens that hour in Events), run outcomes (Unknown links to Events). From `/api/admin/overview`. |
| Admin All records | `#/admin/records`, `#/admin/events` | Records view filters live; Events view uses server-side filters with Apply and an optional `?hour=` chip. |
| Admin Record | `#/admin/records/<id>` | Read-only: explained by, intent, linked run, what changed, full history, gaps and limitations. |
| Admin palette | ⌘K or Ctrl+K in the admin shell | Records, events and a "Go to" group. Records and the first 100 events are fetched when it opens and searched in the browser, so "no match" only covers what was loaded. |
| Apply run | `#/apply/<id>` | Still the old layout, not redesigned. |

Admin is read-only: no report form. Copy rules: detected time is when the scanner noticed, not when the change was made; reports show who submitted, never who made the change; counts are events, not incidents; an unknown run outcome is never shown as failure.

### Shared admin token (decision 2026-11-08)
`BG_ADMIN_TOKEN` stays as the server-side offline fallback and is entered only on the old `Admin.tsx` screen (held in memory, never in the URL or storage). The new admin shell does not accept it: the token cannot read `/api/records`. Removing it would be a separate backend slice.

## Checklist

- [x] Employee and admin screens above, with stub-adapter tests (`npm test`) and fixture checks in Chrome
- [x] Wire mapping against the real contract (`src/api.ts`)
- [x] Phone width (2026-11-08): admin Overview, All records, Events and the employee page at 375 and 320 px in iframes on fixture data: no horizontal overflow; breadcrumbs, top-bar chips, logo, list rows and nav links are at least 44px (`src/argusMobile.test.ts` guards the stylesheet rules). Inline resource links inside table rows are still about 15px. Real data then exposed three more bugs fixtures did not (a long resource name and a plan hash that did not wrap, and a legacy fixed header height clipping the top bar at 320); fixed and guarded in the same test file.
- [x] Live check (2026-11-08): real API on Tiger Cloud, Chrome, signed in with Google as a non-admin and then as an admin. Verified: `/api/me` role detection, a real `403 not_admin` that fails closed to the old screen, the employee Records page, the admin Overview, All records, Events, Record page and admin palette on real data, and no horizontal overflow at 375 and 320 px.
- [x] Scratch-stack check (2026-11-08): real API on a local TimescaleDB (not Tiger), a real unfinished run, and the UI in Chrome. Verified: Overview shows Last apply "Unknown" with "no completion recorded" and Run outcomes "Unknown 1" (never failed); the admin Record page shows the unfinished run and the "Run outcome unknown" gap; the employee palette on real data; a real `503 storage_unavailable` shows an error with Retry in the admin Overview and the employee page, never zeros. The sign-in gate was bypassed with a throwaway shared token behind a local header-adding proxy and the Firebase variables blanked, so this did not exercise Google sign-in.
- [ ] Not yet verified: a real phone, the shared-token screen, and a real unknown outcome on Tiger Cloud (the check above used local Postgres with an authored run)
- [ ] Apply-run view against a REAL run (none exists; runs are created only by `argus apply` in the terminal, which needs real infra)
- [x] Dead code removed (2026-11-08): `RecordDetail.tsx` and `RecordList.tsx`; `Freshness` now lives in `components/Freshness.tsx`

## Google sign-in (Firebase)

- **Where the code lives:**
  - `src/auth.ts` is the only module that talks to Firebase. It's loaded lazily, as its own build chunk.
  - `src/components/AuthProvider.tsx` holds the provider and the sidebar control.
  - `src/api.ts` `setTokenProvider` adds `Authorization: Bearer <ID token>` to writes, and `signedInHeaders()` adds it to reads too, because with Firebase configured every read needs sign-in (`/api/health` stays open).
- **Enabled only when** all four `VITE_FIREBASE_*` values are set, in a gitignored `.env.local`; see `.env.example`. These are public identifiers. Without them, or with `?fixture`, no sign-in UI renders and requests are unchanged.
- **Session:** lasts until the tab closes (`browserSessionPersistence`), and the Firebase SDK holds it. The app never stores an ID token. It fetches a fresh one before **each** request, which handles the hourly expiry.
- **Admin page:**
  - **Continue as <email>:** a fresh token per call. It's tied to that account, so signing out or switching accounts locks the view.
  - **Offline fallback:** the shared admin token.
  - The view's lock button is labeled "Lock admin view" so it can't be mistaken for "Sign out".
- **Errors shown:**
  - `401`: "sign in again". The typed text is kept.
  - `403 email_unverified`: "email isn't verified".
  - `403 not_admin`: "not an admin".
  - `403 admin_not_configured`: "not configured".
- **Honesty:** a signed-in save shows "Saving as <email> (verified Google sign-in; not proof of who made the change)".
- **Rollout:** set `BG_FIREBASE_PROJECT_ID` (and `BG_ADMIN_EMAILS`) on the operator machine only after this UI is merged, so the forms never get `401`.
- **Tests:** `src/auth.test.tsx` uses a fake auth client (no real Google). Mutation checks cover the Bearer header, a fresh token per write, and `not_admin` vs `not configured`.

## Running

Backend: see docs/API.md (`argus seed-demo --with-report`, `uvicorn breakglass.api:app --port 8000`).
Frontend: `npm run dev` — Vite proxies `/api` to `http://127.0.0.1:8000` (override `API_TARGET`). No absolute base URL, so no CORS dependence.
Fixtures only with `?fixture[=empty|error|stale|failed]` (shows a "DEV FIXTURE DATA" badge).

## Verification evidence (2026-11-07, before the redesign)

The items below were run against the old UI. The redesigned screens have only stub-adapter and fixture checks.


- `npm test`: all passing on 2026-11-07, run it for the current count (stub adapters and wire mapping, docs and CSS contracts; not backend integration)
- `npm run lint`: clean; `npm run build`: ok
- REAL backend (branch `feat/break-glass-backend` @41280dd, seeded demo record) in Chrome via the Vite proxy:
  - list/detail render live data with "LIVE API" badge and demo-data tag (`demo-authored · authored-fixture`)
  - report saved through the UI; `GET /api/records/{id}` afterwards showed new reporter/reason and `intent: defer`, `resolution: open`; values survived a page reload
  - reason containing `<b>edit</b>` rendered as plain text
  - backend stopped → proxy 502 → UI shows "Backend unavailable" error, not an empty list
- Mobile pass (2026-11-07): measured in Chrome via 375px/320px iframes on `?fixture` data. `src/mobile.test.ts` guards the stylesheet rules only; it does not prove layout.
- Admin dashboard, real backend, throwaway shared token (2026-11-07): 401 and 403 states, live log with actor labels, filters, record timeline, 404, token forgotten on reload; each finished run shows its outcome once.
- NOT verified against the real backend: apply-run view (only stub/fixture tests), 409 on resolved record, 422 messages.

## Notes for Samuel

- Records list has no scan timestamp; freshness is derived from per-record `last_check_status/at` plus `/api/health`. An empty list therefore cannot show scan age.
- Warning `message` is shown as-is (plain text) under the structured reason quote.
