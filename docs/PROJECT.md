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
- Provider and demo scenario: DigitalOcean droplet and firewall in `infra/demo`, pending team confirmation (PRD §10).
- Authored (hand-written) data lives in environment `<env>-authored` and can never merge with or resolve live records.
- Palette from https://nmc2.com/: black/white, blue `#2b9cfc`, Roboto. Our artwork is original CSS. Independent project, not an official NMC² product.

## Architecture and integration seam

```
infra/demo (Terraform) → refresh-only plan → detector → SQLite ← FastAPI ← web UI
                       → normal plan      → matcher  → guarded apply wrapper (CLI)
```

`src/api.ts` is the single wire-mapping seam (snake_case → camelCase) with a real adapter and a dev-only fixture adapter. Vite proxies `/api`, so there is no absolute base URL and no CORS dependence. Privileged operations stay server-side. Provider keys never go in `VITE_*` variables.

## Status against the PRD (not executed acceptance)

| PRD item | Status |
|---|---|
| R1 detect via refresh-only JSON | Written, tested on authored fixtures only. Direction of `before`/`after` unverified. |
| R2, R3 persist and show records, web explanation | Done in backend and UI. Verified once in Chrome against a seeded local backend. |
| R4–R8 match, pause, acknowledge/cancel, persist decisions and outcomes | Written in the CLI wrapper, tested with a mocked Terraform runner. Never run against real Terraform. |
| R9 admin dashboard | Not built. No server-side admin authorization yet. |
| R10 history preserved | Append-style history in SQLite. Not audit-grade. |
| R11 verified closure | `recheck` written, tested on authored fixtures. |
| R12 suggested manual edit | Done for a single literal value. Never auto-patches. |
| Agent analytics (PRD §7) | Proposed post-core. Not started. |

## Next decision gate

1. Run the **real Terraform spike** on `infra/demo`. It needs an SSH key name, an allowed IP and explicit team approval before any plan or apply. Capture sanitized real plan JSON into `backend/tests/fixtures/real/`.
2. Verify the detector direction against the capture and flip detector and fixtures together if wrong. Also verify the empty-saved-plan state-sync hypothesis.
3. Run the apply-run view against a real `breakglass apply`, and check the 409 and 422 cases.
4. Decide the admin log view scope (R9) and identity and authorization mechanism.
5. Decide whether analytics fits the hackathon release or follows the core demo.

## Provenance

Team, role and hardware context and the booth hint: Daniel's kickoff message. Requirements: the PRD. Visual reference: https://nmc2.com/ inspected during kickoff. Do not treat marketing copy as challenge requirements.
