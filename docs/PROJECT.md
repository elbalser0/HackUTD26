# HackUTD26 — Living project document

## Goal

Build **Argus** for the NMC² challenge at HackUTD 2026: capture an emergency manual infrastructure change with its explanation, pause a later Terraform apply that would undo it, and keep a shared decision history.

**Source of truth: `docs/Break-Glass Handoff — PRD.md`.** This file tracks decisions and status against it. If they conflict, the PRD wins. Daniel also wants to explore product work and employment at NMC².

## Team

- Daniel: product and frontend.
- Samuel: backend.
- Andrew: infrastructure; has home business-grade servers (hardware access and suitability not validated, and the PRD forbids using his network or production systems).
- Roles are starting strengths, not fixed assignments.
- An NMC² booth representative mentioned "infrastructure as code". That is an unconfirmed hint, not a requirement.

## Decisions

- Private GitHub repository: `elbalser0/HackUTD26` (preserve exact name).
- Frontend: React + TypeScript + Vite in the repo root; npm lockfile committed. Read-only: it never runs Terraform and holds no secrets.
- Backend: one Python FastAPI process, one SQLite file, one CLI (`backend/`). No microservices. Contract in `docs/API.md`.
- Detector: Terraform refresh-only plan JSON; normal plan JSON supplies proposed actions. Coverage is only `digitalocean_firewall` → `inbound_rule`.
- Provider and demo scenario: DigitalOcean firewall `digitalocean_firewall.demo` in `break-glass-infra/` (applied; not attached to the droplet). Terraform manages only the firewall; the droplet already existed. Proposed staged change, still to confirm as a team (PRD §10): **adding** an inbound rule (e.g. tcp 8443) in the console.
- Single operator: Daniel's machine holds the Terraform state and runs Terraform, `breakglass` and the API. Never apply this config from a second machine (a second apply was already refused with `409 duplicate name`).
- Authored (hand-written) data lives in environment `<env>-authored` and can never merge with or resolve live records.
- Persistence: `BG_DATABASE_URL` set (in `.env` or the terminal) → Tiger Cloud PostgreSQL with TimescaleDB (events are a hypertable, hourly continuous aggregate) for both the API and the CLI, with no fallback if it is unreachable. Unset → one local SQLite file (`backend/breakglass.db`, override with `BG_DB_PATH`, WAL mode). Either holds records, runs, scans and the append-only `events` table the admin log reads.
- Identity: Firebase (Google) sign-in. When `BG_FIREBASE_PROJECT_ID` is set, web writes (report, decision) require a verified-email Firebase ID token and record the account email as `google-account (verified sign-in)`. Reads (records, events, apply runs) also need a verified sign-in or the shared token; `/api/health` stays open. The admin log accepts a signed-in email from `BG_ADMIN_EMAILS` or the shared token `BG_ADMIN_TOKEN` as an offline fallback. Unset, behavior is unchanged. Wrapper (CLI) actors are still self-reported or the OS user.
- Two personas for the web UI: **employee** (find a record, explain it) and **admin** (overview, all records, read-only record, ⌘K). `GET /api/me` decides the role server-side with the same allowlist that guards `/api/admin/*`. Admins are read-only in the UI only; the server still accepts their explanations. **No per-person counts, rankings or scores** anywhere (PRD non-goal: employee blame scores); people appear only as an investigation filter.
- Keep and defer require a short rationale in the wrapper; without one the decision is not saved and the run is recorded as a cancel. Cancel never requires one.
- Palette from https://nmc2.com/: black/white, blue `#2b9cfc`, Roboto. Our artwork is original CSS. Independent project, not an official NMC² product.

## Architecture and integration seam

```
break-glass-infra (Terraform) → refresh-only plan → detector → SQLite ← FastAPI ← web UI
                       → normal plan      → matcher  → guarded apply wrapper (CLI)
```

`src/api.ts` is the single wire-mapping seam (snake_case → camelCase) with a real adapter and a dev-only fixture adapter. Vite proxies `/api`, so there is no absolute base URL and no CORS dependence. Privileged operations stay server-side. Provider keys never go in `VITE_*` variables.

## Status against the PRD (not executed acceptance)

| PRD item | Status |
|---|---|
| R1 detect via refresh-only JSON | Verified on real Terraform output (2026-11-07): a console-added rule is `added`, baseline empty, observed `allow tcp 8443`, so `before` is the prior state and `after` the live value. Replayed from sanitized captures in `backend/tests/fixtures/real/`. Finding: the provider reports `droplet_ids`/`tags` as null in state and `[]` live; null and empty collections now compare equal so this is not reported as drift. Only `digitalocean_firewall` `inbound_rule` is interpreted. |
| R2, R3 persist and show records, web explanation | Done in backend and UI. Verified once in Chrome against a seeded local backend. |
| R4, R5 match and pause | Verified on real Terraform: the real normal plan's reversal is matched and the wrapper pauses before any apply, with and without a recorded reason. Cancel and keep applied nothing (the rule stayed live). Not yet run for real: a confirmed revert or override apply (reviewed-plan execution, changed-plan abort). |
| R6 decision history without overwriting | Append-only `events` table (reports, decisions, wrapper reviews, run start/finish). Keep and defer require a rationale. Tested offline. Web actors are verified Google accounts when Firebase is configured; wrapper actors are self-reported or the local OS user, not verified. |
| R7 decision persisted before execution | The review, reviewer, rationale and exact plan fingerprint are saved in one transaction with the run marked `running` before Terraform runs; a failed write means nothing is applied. Tested with a mocked Terraform runner only. |
| R8 outcomes, unknown when missing | Runs with no recorded completion become `unknown` (never success). Tested offline; not exercised against a real interrupted apply. |
| R9 admin dashboard | Backend done: `/api/admin/log` and `/api/admin/records/{id}/timeline` read the events, with server-side authorization that fails closed: a Firebase sign-in whose email is in `BG_ADMIN_EMAILS` (per-admin identity), or the shared token `BG_ADMIN_TOKEN` as a fallback; signed-in non-admins get 403. Tested on authored data. Dashboard UI built (`#/admin`, "Continue as <email>" or the shared token), tested with stub adapters, checked at 375px on fixture data, and run in a real browser against the real backend with a throwaway shared token (2026-11-07: 401, 403, filters, timeline, 404, token forgotten on reload). Not yet run live: the Google-admin path, an `unknown` outcome and the gaps box (the data has no unfinished run). Google sign-in UI run by the team against a real Firebase project and reported working (2026-11-07); improvements planned. Redesign backend: `/api/me` (persona), `/api/admin/overview` (open/needs-reason counts, last scan, last run with `unknown` kept as unknown, events and run outcomes by type, hourly activity; events, not incidents or downtime), `type` filter on the log, and `reporter_assurance`/`last_activity` on records. Tested on authored data; the redesigned UI is not built yet. Reads need sign-in when Firebase is configured. |
| R10 history preserved | Append-style history in SQLite. Not audit-grade. |
| R11 verified closure | Verified on real Terraform (2026-11-07): after the console rule was deleted, `argus recheck` resolved the real record as `verified_aligned` and its history stayed intact (change, runs, explanation, review, resolution). The first real recheck had stayed open because the provider reports `droplet_ids`/`tags` as null in state and `[]` live; fixed (null and empty collections compare equal) and covered by a replay test. |
| R12 suggested manual edit | Done for a single literal value. Never auto-patches. |
| Agent analytics (PRD §7) | Proposed post-core. Not started. |

## Next decision gate

1. Remaining spike work on `break-glass-infra/` (Daniel's machine; each cloud step needs team approval), optional: a confirmed revert/override apply (reviewed plan executed, changed plan aborted) and the keep-path state sync. Real findings so far are recorded above and in `backend/tests/fixtures/real/README.md`.
2. Not yet seen: a drift-free refresh-only plan (the provider noise kept `resource_drift` present). Re-check that a missing `resource_drift` key is still treated safely once one is captured.
3. Check the 409 and 422 UI cases against the real backend.
4. Improve the Google sign-in UI (team is working on it). Build the two-persona UI on `/api/me` and `/api/admin/overview`. Decide whether the shared admin token fallback stays.
5. Decide whether the local SQLite file is enough for the demo or the history needs a shared store (only one machine sees it today).
6. Decide whether analytics fits the hackathon release or follows the core demo.

## Provenance

Team, role and hardware context and the booth hint: Daniel's kickoff message. Requirements: the PRD. Visual reference: https://nmc2.com/ inspected during kickoff. Do not treat marketing copy as challenge requirements.
