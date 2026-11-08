# Frontend status (Daniel)

Branch: `feat/break-glass-ui`. Stack: React + TS + Vite + Vitest. Contract: `docs/API.md` on `origin/feat/break-glass-backend`.

## Checklist

- [x] Open-record list (baseline → observed rule, detected-at UTC, per-record check status, health banner)
- [x] Record detail + report form (name optional, reason ≤500, optional intent); failure keeps text
- [x] Keep/revert/defer intent (never resolves); manual Terraform edit suggestion on keep
- [x] Apply-run view: proposed changes, per-record warnings, missing-reason fallback, check status/coverage, terminal outcome, bypass note
- [x] Loading / empty / error / stale / failed / unsupported / resolved / demo-data states
- [x] Wire mapping against the real contract (`src/api.ts`)
- [ ] Apply-run view against a REAL run (none exists; runs are created only by `breakglass apply` in the terminal, which needs real infra)
- [x] Mobile layout check at 375px and 320px (fixture data): no horizontal overflow; tap targets >= 44px; breadcrumb shows the current page; back link spaced from the eyebrow
- [ ] Remaining visual polish (e.g. tight spacing between tag badges and the `inbound_rule · added` line); admin dashboard (PRD R9) built at `#/admin`: token held in memory only, never in URL or storage; verified with stub adapters and fixture data (`?fixture`, token `demo`), not against the real backend

## Google sign-in (Firebase)

- **Where the code lives:**
  - `src/auth.ts` is the only module that talks to Firebase. It's loaded lazily, as its own build chunk.
  - `src/components/AuthProvider.tsx` holds the provider and the sidebar control.
  - `src/api.ts` `setTokenProvider` adds `Authorization: Bearer <ID token>` to **writes only** (report, decision). Reads never send it.
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

Backend: see docs/API.md (`breakglass seed-demo --with-report`, `uvicorn breakglass.api:app --port 8000`).
Frontend: `npm run dev` — Vite proxies `/api` to `http://127.0.0.1:8000` (override `API_TARGET`). No absolute base URL, so no CORS dependence.
Fixtures only with `?fixture[=empty|error|stale|failed]` (shows a "DEV FIXTURE DATA" badge).

## Verification evidence (2026-11-07)

- `npm test`: 12 passed (stub adapter + wire-mapping; not backend integration)
- `npm run lint`: clean; `npm run build`: ok
- REAL backend (branch `feat/break-glass-backend` @41280dd, seeded demo record) in Chrome via the Vite proxy:
  - list/detail render live data with "LIVE API" badge and demo-data tag (`demo-authored · authored-fixture`)
  - report saved through the UI; `GET /api/records/{id}` afterwards showed new reporter/reason and `intent: defer`, `resolution: open`; values survived a page reload
  - reason containing `<b>edit</b>` rendered as plain text
  - backend stopped → proxy 502 → UI shows "Backend unavailable" error, not an empty list
- Mobile pass (2026-11-07): measured in Chrome via 375px/320px iframes on `?fixture` data. `src/mobile.test.ts` guards the stylesheet rules only; it does not prove layout.
- NOT verified against the real backend: apply-run view (only stub/fixture tests), 409 on resolved record, 422 messages.

## Notes for Samuel

- Records list has no scan timestamp; freshness is derived from per-record `last_check_status/at` plus `/api/health`. An empty list therefore cannot show scan age.
- Warning `message` is shown as-is (plain text) under the structured reason quote.
