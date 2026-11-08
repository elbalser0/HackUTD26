# Handoff for the next agent

Written 2026-11-07 after PR #11. Read this first, then the [PRD](<Break-Glass Handoff — PRD.md>) (source of truth for scope and acceptance; it records requirements, not results). This file is a status snapshot, not a spec: when it disagrees with the code or the PRD, trust those.

## What this is

**Break-Glass Handoff** (HackUTD26, NMC² challenge). When an engineer changes infrastructure by hand during an incident, a later `terraform apply` can silently undo it. The backend detects the manual change from a Terraform refresh-only plan, stores the explanation, and the guarded `breakglass apply` wrapper pauses an apply that would reverse it, requiring an explicit decision. History is append-only. The web UI is read-only and never runs Terraform. Demo target: one DigitalOcean firewall (`digitalocean_firewall.demo`, "break-glass-demo") in `break-glass-infra/`.

Team: Daniel (product, frontend; the user you are working with and the only machine that holds the Terraform state), Samuel (backend), Andrew (infrastructure).

## How the user wants you to work

These came from corrections and approvals in earlier sessions. Follow them.

- **Test-first.** Write the failing test, watch it fail for the *right* reason, then implement. Mutation-check important logic (break the code on purpose; a surviving mutant means a weak test). Docs have tests too (`src/docs.test.ts`) so wording can't drift into overclaiming.
- **Never read, open, grep or source `.env`.** It holds `DIGITALOCEAN_TOKEN`. Nothing in the backend loads it by itself. When a step needs the token, give the user a command to run themselves (see "Running real Terraform steps"). Never ask for or print token values.
- **No cloud operation without explicit team approval.** Console edits, applies and state changes are the user's call. Never run `terraform apply`. At wrapper prompts only keep or cancel unless the user has approved a real apply.
- **Commit, push, open a PR and merge only when the user asks.** They have said "yes" per task so far: branch off `main`, commit, push, open the PR, wait for both CI jobs, then `gh pr merge --merge` and pull `main`. Don't work on `main` directly.
- **Be honest about verification.** Say what ran on real Terraform, what ran only against authored fixtures or a mocked runner, and what has not run. Don't report acceptance criteria as done unless they were verified.
- Keep answers short. Recommend, don't survey. Refer to people with they/them unless told otherwise.

## State of the code (main, after PR #11)

| Piece | Where | Notes |
|---|---|---|
| Detector, matcher, rules | `backend/breakglass/{detector,matcher,rules,suggest}.py` | Only `digitalocean_firewall` `inbound_rule` is interpreted; anything else is reported as unsupported, never as "no drift". Null and empty collections compare equal (`detector._empty_is_none`). |
| Records, append-only events, runs | `db.py`, `service.py`, SQLite | Reports, decisions, wrapper reviews and run start/finish are never overwritten. |
| Guarded apply wrapper | `wrapper.py`, CLI `breakglass apply` | Review (decision, rationale, reviewer, plan fingerprint) is saved in one transaction with the run marked `running` before Terraform runs. Runs with no recorded completion become `unknown`. |
| HTTP API | `api.py`, `docs/API.md` | Read plus annotate only; no route runs Terraform. |
| Admin log (PRD R9 backend) | `admin.py`, `/api/admin/log`, `/api/admin/records/{id}/timeline` | Bearer token from `BG_ADMIN_TOKEN`, fails closed, one shared token (no per-admin identity). Reads events, records and runs. |
| Web UI | `src/` | Records list and detail, report form, apply-warning view; phone layout checked at 375 and 320px. Read-only. **No admin dashboard UI yet.** |
| Real captures and replay tests | `backend/tests/fixtures/real/`, `tests/test_real_replay.py` | Sanitized (fake firewall id, `203.0.113.10`, fake droplet id). Its README lists what was replaced. |
| CI | `.github/workflows/ci.yml` | Two jobs: frontend (`lint`, `test`, `build`) and `backend` (`pytest`, offline). |

The older `/api/records` and `/api/apply-runs` endpoints are still unauthenticated (open decision).

## What is verified, and what is not

**Verified on real Terraform and DigitalOcean** (2026-11-07, run from the user's machine; no `terraform apply` was ever run):
- A console-added rule is detected as `added`: in a refresh-only plan `change.before` is the prior state and `change.after` is the live value; `resource_changes` is absent from a refresh-only plan; every rule carries `action = "allow"`.
- The real normal plan reverses that rule as an in-place `update`, and the matcher flags it. A plan from the clean state flags nothing.
- The wrapper pauses before any apply, with "No reason recorded" and with a reason; cancel and keep applied nothing.
- The UI (LIVE API badge) and the admin log over HTTP showed the real record and runs for two actors, with the reviewed plan fingerprint; the admin API returns 401 without a token.
- After the rule was deleted, `breakglass recheck` resolved the record as `verified_aligned` with its history intact (R11).
- One real bug was found and fixed: the provider reports `droplet_ids` and `tags` as `null` in older state and `[]` live, which made recheck refuse to resolve any record.

**Not yet run for real** (mocked or authored tests only), starting with a confirmed revert or override apply:
- That apply: execution of the reviewed plan, abort when the plan changed, a failed decision write blocking the apply, an interrupt mid-apply.
- The keep-path state sync (H5): after a keep and a config edit, does applying the empty saved plan record the live value? It changes Terraform state, so it needs approval.
- A drift-free refresh-only plan. The provider noise kept `resource_drift` present in every capture, so the assumption that a missing key means no drift (open issue I2) is unchecked.
- The 409 and 422 UI cases against the real backend.

Actors are self-reported or the local OS user (labelled "not verified"). Nothing here proves service health.

## Running things

**Python:** use `python3.12` (matches `pyproject.toml`, `>=3.12`). The system `python3` may be newer. `backend/.venv/` is gitignored, so a venv there is safe.

```sh
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q                       # offline; Terraform is mocked
breakglass seed-demo --with-report        # AUTHORED data, environment "demo-authored"
uvicorn breakglass.api:app --port 8000
```

```sh
npm ci
npm test && npm run lint && npm run build
npm run dev                               # Vite proxies /api to 127.0.0.1:8000; picks another port if 5173 is taken
# no backend needed for UI work: open the app with ?fixture (also ?fixture=empty|error|stale|failed)
```

Admin API: start the server with `BG_ADMIN_TOKEN` set to a throwaway value, then `curl -H "Authorization: Bearer $BG_ADMIN_TOKEN" localhost:8000/api/admin/log`.

## Running real Terraform steps

The user's token lives in `.env` and you must not touch it. Pattern that worked:

1. Write the commands into a small script (no secrets in it) that does `set -a; . ./.env; set +a` itself, and have the user run `! bash /path/to/script.sh`.
2. The `!` must be the **first character** of the line, with no leading space, and the input box in shell mode. A pasted line that wraps splits the command (this once ran `terraform show -json` with no file and printed state to the screen). A script file avoids both problems. If the reply comes back as plain text with no `<bash-input>` block, it did not run.
3. `!` commands run in the session's working directory. Don't leave the session `cd`'d into a subfolder, or `./.env` won't be found.
4. For `breakglass apply`, close stdin (`< /dev/null`) so every prompt hits end-of-input, which the wrapper treats as cancel. That shows the warning screen and can never apply. `printf 'k\nreason here\n' | breakglass apply` answers keep (keep and defer require a rationale; without one the run is cancelled). Never supply `r` or `o` without approval.
5. `breakglass scan --no-prompt` skips the "name: reason" question; add the reason with `breakglass report <id> --reporter "Name (demo)" --reason "..."`. Use fake demo names.
6. Capture plans into `break-glass-infra/raw/` (gitignored): `terraform plan -refresh-only -out=scan.tfplan`, `terraform show -json scan.tfplan > raw/scan.json`, and the same for a normal `plan`. Never apply those plans. Delete them and `raw/` afterwards; they hold the real IP and firewall id.
7. To make a fixture: replace every IPv4, UUID and long number with fakes, keep the structure byte-for-byte, and prove programmatically that no original value remains. See `backend/tests/fixtures/real/README.md`.

Local state (`break-glass-infra/terraform.tfstate`, `terraform.tfvars`, `.terraform/`) is gitignored. Don't print it.

## Gotchas

- One machine owns the Terraform state (the user's). Starting `breakglass apply` marks any other unfinished run in the same environment `unknown`, so run it from one terminal.
- The firewall is not attached to the droplet (`attach_firewall = false`), so console edits to it affect no live traffic. The user's DigitalOcean console edits are theirs to make; don't do them through the browser unless told.
- Authored and replayed data go to `<env>-authored` and `<env>-replay` and can never merge with or resolve live records. `--label` is required for `--from-json`.
- `docs/PROJECT.md` carries the status table against R1-R12 and the next decision gate. Keep it, `docs/BACKEND.md` and the README in step with the code. The docs tests will fail on stale claims.
- The demo record and its history are in the local `backend/breakglass.db` (gitignored). `breakglass reset-db --yes` clears it.

## Next steps

1. **Admin dashboard UI (PRD R9 UI)**, the largest core piece not started. Build it test-first over `/api/admin/log` and `/api/admin/records/{id}/timeline`. It needs a design for supplying `BG_ADMIN_TOKEN` (bearer header only; don't put it in a URL; think about where it is held in the browser). Show actors with their assurance label, `unknown` outcomes plainly, and the `gaps` and `limitations` the API returns. Filters are engineer, resource, time and outcome.
2. **Optional real spike items, each needing approval:** a confirmed revert or override apply (reviewed-plan execution, changed-plan abort), the keep-path state sync (H5), and capturing a drift-free refresh-only plan (likely needs `terraform apply` of a refresh-only plan to clear the provider noise in state; that changes state only).
3. **Decisions for the user:** per-admin identity (the token is shared), whether `/api/records` and `/api/apply-runs` should also require authorization, retention, and the 409/422 UI states.
4. **Later, only after the core demo works:** analytics and the classifier (PRD §7, proposed). The user asked to skip the demo script, fallback video and sponsor conversations for now; don't start them unprompted.

## Key files

- `docs/Break-Glass Handoff — PRD.md`: requirements and acceptance checklist
- `docs/PROJECT.md`, `docs/BACKEND.md`, `docs/API.md`, `docs/FRONTEND.md`: status, rules, contract, UI evidence
- `backend/breakglass/`: the backend; `backend/tests/`: tests and fixtures (`authored/`, `real/`)
- `break-glass-infra/main.tf`: the demo firewall
- `src/api.ts`: the single wire-mapping seam between the API and the UI
- `src/docs.test.ts`, `src/mobile.test.ts`: contract tests for the docs, CI and phone layout
