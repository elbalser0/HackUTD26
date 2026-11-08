# HackUTD26 — Living project document

## Goal

Build **Break-Glass Handoff** for the NMC² challenge at HackUTD 2026: capture an emergency manual infrastructure change with its explanation, pause a later Terraform apply that would undo it, and keep a shared decision history.

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
| R1 detect via refresh-only JSON | Written, tested on authored fixtures only. Direction of `before`/`after` unverified. |
| R2, R3 persist and show records, web explanation | Done in backend and UI. Verified once in Chrome against a seeded local backend. |
| R4, R5 match and pause | Written in the CLI wrapper, tested with a mocked Terraform runner. Never run against real Terraform. |
| R6 decision history without overwriting | **Gap.** Reason and intent are overwritten on the record ("last report wins"). Append-only events in progress. |
| R7 decision persisted before execution | **Gap.** The wrapper verifies the exact plan, but writes the final decision after the apply. Fix in progress. |
| R8 outcomes, unknown when missing | **Partial.** Outcomes are recorded; a crashed run stays `pending` instead of `unknown`. Fix in progress. |
| R9 admin dashboard | Not built. No server-side admin authorization yet. |
| R10 history preserved | Append-style history in SQLite. Not audit-grade. |
| R11 verified closure | `recheck` written, tested on authored fixtures. |
| R12 suggested manual edit | Done for a single literal value. Never auto-patches. |
| Agent analytics (PRD §7) | Proposed post-core. Not started. |

## Next decision gate

1. Finish the **real Terraform spike** on `break-glass-infra/` from Daniel's machine (partial: a real plan succeeded). Run a baseline `breakglass scan`, make the console edit, run `scan` again, then `breakglass apply`, and capture sanitized plan JSON into `backend/tests/fixtures/real/`. Needs explicit team approval for any cloud operation.
2. Verify the detector direction against the capture and flip detector and fixtures together if wrong. Also verify the empty-saved-plan state-sync hypothesis.
3. Run the apply-run view against a real `breakglass apply`, and check the 409 and 422 cases.
4. Decide the admin log view scope (R9) and identity and authorization mechanism.
5. Decide whether analytics fits the hackathon release or follows the core demo.

## Provenance

Team, role and hardware context and the booth hint: Daniel's kickoff message. Requirements: the PRD. Visual reference: https://nmc2.com/ inspected during kickoff. Do not treat marketing copy as challenge requirements.
