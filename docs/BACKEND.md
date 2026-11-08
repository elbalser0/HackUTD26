# Backend: Argus

Owner: Samuel. This is a living document; keep it current. HTTP contract: [API.md](API.md). Demo infrastructure: [`break-glass-infra/main.tf`](../break-glass-infra/main.tf) (Daniel's).

## Status (2026-11-07)

| Piece | State |
|---|---|
| API contract (`docs/API.md`) | Written; ready for Daniel |
| Parser/detector/matcher (`rules`, `detector`, `matcher`, `suggest`) | Done, tested on **authored** fixtures |
| SQLite records, dedup, supersede, report/decision | Done, tested |
| HTTP API (FastAPI) | Done, tested |
| CLI (`breakglass …`) | Done, tested offline |
| Guarded apply wrapper | Done, tested with a mocked Terraform runner |
| Verified resolution (`recheck`) | Done, tested on authored fixtures |
| Admin log + record timeline (R9), bearer-token auth | Done, tested on authored data (`tests/test_admin.py`). Reads `events`; see API.md for limits |
| Demo Terraform (`break-glass-infra/`) | Firewall `digitalocean_firewall.demo` ("break-glass-demo") **applied** from Daniel's machine; not attached to the droplet (`attach_firewall = false`) |
| **Real Terraform spike** | **MOSTLY DONE (2026-11-07).** Verified on real Terraform and DigitalOcean: detection of a console edit, direction of `before`/`after`, matcher reversal, wrapper pause (cancel, keep), UI and admin log on live data. A real `recheck` resolved the record (`verified_aligned`) after the null/empty fix. Not yet run for real: a confirmed revert/override apply and the keep-path state sync |

### Evidence: real vs. authored
- Fixtures in `backend/tests/fixtures/authored/` were **hand-written** from Terraform's documented plan JSON format.
- `backend/tests/fixtures/real/` holds sanitized captures from the real spike (see its README): `refresh_noise_only`, `refresh_added_8443`, `plan_reverts_8443`, `plan_no_changes`. `tests/test_real_replay.py` replays them.
- Established on real output: in a refresh-only plan's `resource_drift[]`, `change.before` is the prior **state** and `change.after` is the **live** value, and a refresh-only plan has no `resource_changes` key. In a normal plan, `before` is the refreshed live value and `after` is config; the real plan reverses a console-added rule as an in-place `update`. Every rule carries `action = "allow"`.
- Finding: the provider reports `droplet_ids` and `tags` as `null` in older state and `[]` live. That used to be reported as unsupported drift, which made `recheck` refuse to resolve any record for the resource. Null and empty collections now compare equal (`detector._empty_is_none`); a real change (a tag added, a droplet detached, a string, number or boolean) still counts.
- A real `recheck` closed the record once both fresh plans agreed (R11).
- Still unseen on real output: a drift-free refresh-only plan (so the "missing `resource_drift` means no drift" assumption, I2, is unchecked), the keep-path empty-saved-plan state sync, and a confirmed revert/override apply.

## Architecture

One FastAPI process, one SQLite file, one CLI. No microservices.

```
break-glass-infra (Terraform) ── terraform plan -refresh-only ──► detector ──► service.ingest_refresh_plan ──► SQLite
                        └─ terraform plan (saved)  ──► matcher ──► wrapper (warn + confirm) ──► terraform apply <saved plan>
SQLite ◄── api (GET records/apply-runs, POST report/decision) ◄── Daniel's UI
```

- `config.py`: env settings. `BG_TF_DIR` must resolve inside the repo's `break-glass-infra/` (unless `BG_ALLOW_TF_DIR_OUTSIDE_REPO=1`).
- `tfrunner.py`: the only place that spawns Terraform. Argument arrays, `shell=False`, fixed plan file names, plans deleted after use.
- `detector.py` / `matcher.py` / `rules.py` / `suggest.py`: pure functions over plan JSON. Firewall rules are compared as **sets**, never by index.
- `service.py`: records, dedup, supersede, warnings, re-check.
- `wrapper.py`: the guarded apply flow.
- `api.py`: read + annotate only. No HTTP route runs Terraform or accepts paths or commands.

## Supported coverage

- Rule identity includes `action` (allow/deny), as seen in real provider v2.107 output. A missing action counts as "allow", so older state and newer live output don't create false records. Run `breakglass reset-db --yes` on any database created before this change.
- **Only** `digitalocean_firewall` → `inbound_rule`. Detects added, removed and modified rules, where modified means the same protocol and sources with a different port.
- Drift in other firewall attributes, other resource types, deleted resources, or unknown/sensitive values is reported as **unsupported**. It never becomes a record and is never treated as "no drift".
- Changes inside the OS (anything Terraform doesn't track) are invisible.

## Decisions and rules

- **Dedup:** the fingerprint is sha256(env, address, attribute, kind, baseline, observed). Seeing the same evidence again only refreshes `last_detected_at`.
- **Supersede:** a new observation for the same declared rule with different evidence (for example 8080→8443, then 8080→9443) creates a new record. The old record is resolved as `superseded` with `superseded_by` set. The old reason is **not** copied forward.
- **Not seen anymore:** an open record missing from a later successful scan becomes `stale`, not resolved. State may match live while the config still disagrees.
- **Failed scan:** open records become `failed`, which means unknown, not fine.
- **Warnings:** these require a true reversal. That means the same address **and** the normal plan removes the observed rule, or re-adds a removed one. Address equality alone doesn't count. A missing reason still warns: "Unexplained manual change, no reason recorded". Decisions never suppress warnings.
- **Resolution (`recheck`):** a record resolves (`verified_aligned`) only when a fresh refresh-only plan shows no drift for it **and** a fresh normal plan includes the resource and does not reverse it. Any failure or unknown keeps it open. Keep/revert intents never resolve.
- **Fixture isolation:** authored data goes to environment `<env>-authored` and sanitized replays to `<env>-replay`. They can never merge with, explain, or resolve a live record. `--label` is required for any `--from-json` / `--refresh-json` input.
- **Keep path / state sync:** after "keep" and an IaC edit, the normal plan has no resource changes, but state still holds the old value. `breakglass apply` detects this (drift present, no changes) and offers, with `yes`, to apply the empty saved plan so state records the live value. Then `recheck` can resolve. *Hypothesis to verify in the spike: that applying an empty saved plan persists refreshed state.*
- **History (PRD R6/R10):** the `events` table is append-only. Reports, web/CLI decisions, wrapper reviews and run start/finish are never updated or deleted, except by `reset-db --yes` for demo data. Records keep the latest reason and intent for display only. This is application-level append-only, not a tamper-proof audit log.
- **Self-reported context:** reporter and reason are self-reported, never audited attribution. `first_detected_at` is detection time, not change time.

## Guarded apply (`breakglass apply`)

1. Record the workspace and a hash of the config.
2. Run a refresh-only scan, which is never applied, and ingest it.
3. Run `terraform plan -detailed-exitcode -out=.breakglass-apply.tfplan` (0 = no changes, stop; 2 = changes; else error, stop).
4. Run `terraform show -json`, then match against open records.
5. Branch on the result:
   - **Verification failed** (scan, plan JSON or match error): prints `VERIFICATION UNAVAILABLE. This is NOT a 'no conflicts' result.` Continuing requires typing `unverified-bypass` **and a rationale**.
   - **Warnings:** each shows its reason, record age, and up to 3 prior decisions. Then:
     - keep: requires a rationale, then saves intent and prints a literal-edit suggestion; no apply.
     - defer: requires a rationale; no apply.
     - cancel: asks for a rationale but never requires one (cancelling is the safe default); no apply. Closed input or Ctrl+C also cancels.
     - keep or defer without a valid rationale is **not saved**. The run is recorded as a cancel instead, and nothing is applied.
     - revert: requires typing `revert`, then a rationale. If either is missing, nothing is applied, but the record's intent is saved as `revert` ("revert-not-confirmed").
     - override: requires typing `override`, then a rationale.
   - **No warnings:** requires typing `yes`.
   - Every decision on affected records, including keep, defer and cancel, is appended as a `review` event per record. Earlier history is never overwritten (PRD R6/R10). Runs with no affected records are recorded on the run row and its `run_started` / `run_finished` events.
   - Every decision carries a rationale (PRD §6 step 7). It is required for keep, defer, revert, override and bypass, and optional only for cancel.
6. Before applying, re-hash the plan file, config and workspace. On any change it aborts (`aborted_plan_changed`).
7. **Persist before execution (PRD R7):** in one transaction, save the review events (decision, rationale, reviewer and its assurance, plan fingerprint), set the run to `running` with `started_at`, and add a `run_started` event. If that write fails, nothing is applied and the run is `failed` ("decision could not be persisted").
8. `terraform apply <that exact saved plan>`. A saved-plan apply doesn't prompt, so the wrapper owns confirmation. A `run_finished` event records the outcome.
9. Drift outside coverage is printed as `NOT CHECKED: …` and qualifies the "no reversal" message.
10. Ctrl+C during the apply step is **never** reported as "nothing applied". Terraform is allowed to stop gracefully (never killed), and the run is recorded `failed` with "live state unknown; run scan/recheck". The apply has no timeout.
11. **Unknown outcomes (PRD R8):** a run left `pending`/`running` with no completion (crash, killed terminal) is marked `unknown` when the next `breakglass apply` starts. It is never shown as success.
12. **Single operator assumption:** starting `breakglass apply` marks any other unfinished run in the same environment `unknown`. Two overlapping sessions in one environment would mislabel each other, so run the wrapper from one terminal on the operator machine.
13. Reviewer identity: `--reviewer NAME` is recorded as `self-reported`. Otherwise the OS user name is recorded as `local-os-user (not verified)`.
14. Plan files are deleted in all cases. Each run is stored as an ApplyRun (`GET /api/apply-runs/{id}`).

**Limitations, stated honestly:**
- Running `terraform apply` directly bypasses all of this. A CI gate would be the enforceable version; that's a stretch goal and not built.
- The cloud can still change between plan and apply.
- No automatic apply, revert, HCL patch or policy veto.

## Commands

```sh
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

python -m pytest -q               # all tests, offline; Terraform is mocked
breakglass seed-demo [--with-report]   # AUTHORED demo data for UI work
uvicorn breakglass.api:app --port 8000 # API on http://localhost:8000 (localhost only)

breakglass scan [--from-json FILE --label authored-fixture|real-fixture] [--no-prompt]   # --label required with --from-json
breakglass list [--all|--resolved]
breakglass show <id>
breakglass report <id> [--reporter NAME --reason TEXT --intent keep|revert|unsure|defer]
breakglass decide <id> keep|revert|unsure|defer [--note TEXT]
breakglass apply
breakglass recheck [--refresh-json FILE --plan-json FILE --label authored-fixture|real-fixture]
breakglass reset-db --yes
breakglass demo-reset [--yes] [--skip-cloud-check]   # wipe demo data + read-only preflight (never changes the cloud)
```

Environment: `BG_ALLOWED_HOSTS` (default `localhost,127.0.0.1,[::1]`), `BG_DB_PATH` (default `backend/breakglass.db`), `BG_TF_DIR` (default `break-glass-infra/`; must be inside it unless `BG_ALLOW_TF_DIR_OUTSIDE_REPO=1` is set, an escape hatch for development; it is never read from HTTP input), `BG_ENVIRONMENT` (default `demo`), `BG_CORS_ORIGINS`, `BG_TERRAFORM_BIN`, `BG_DO_TOKEN_FILE` (default `~/.secrets/digitalocean_token`), `BG_ADMIN_TOKEN` (shared admin fallback; secret), `BG_FIREBASE_PROJECT_ID` (public; turns on sign-in for web writes and Firebase admin), `BG_ADMIN_EMAILS` (comma-separated admin Google emails), `BG_API_URL` (default `http://127.0.0.1:8000`; only `breakglass demo-reset` uses it, to check the API is reachable).

**Rollout order for sign-in:** set `BG_FIREBASE_PROJECT_ID` on the operator machine only **after** the UI sends Firebase ID tokens. Until then the UI's report and decision forms would get `401`.

## Infrastructure and operator

- `break-glass-infra/main.tf` manages **one firewall only**: `digitalocean_firewall.demo`, named "break-glass-demo". Its rules are SSH from the admin /32 and outbound open. It is attached to the existing droplet only when `attach_firewall = true`. Terraform does not manage the droplet.
- **Demo story:** the emergency fix is **adding** an inbound rule in the console, such as tcp 8443. The detector records it as `added`, and a normal plan would remove it, which is what triggers the warning.
- **Single operator:** Terraform state is a local file on Daniel's machine, so Terraform, `breakglass` and the API all run there. Never `apply` this config from a second machine; that is what produced the 409 duplicate-name error.
- **Token on the operator machine:** `read -rsp "DigitalOcean API token: " DIGITALOCEAN_TOKEN; export DIGITALOCEAN_TOKEN`. The backend uses the exported variable and falls back to `~/.secrets/digitalocean_token` only if it is unset.

## Credentials

- The DigitalOcean token lives in `~/.secrets/digitalocean_token` (owner-only ACL), outside the repo. `tfrunner` reads it into the Terraform **child process environment only**, and only if `DIGITALOCEAN_TOKEN` isn't already set. It is never printed, logged or stored.
- **Backend settings file:** `load_settings()` also reads the repo-root `.env` (path override `BG_DOTENV_FILE`; `BG_NO_DOTENV=1` disables it). Only keys starting with `BG_` are read; every other line, including `DIGITALOCEAN_TOKEN`, is skipped and never stored. A value already in the real environment wins. `os.environ` is not modified. Tests always opt out (`tests/conftest.py`) so a developer's `.env` cannot change results.
- Never commit: `*.tfstate*`, `*.tfplan`, `*.tfvars`, `.terraform/`, `break-glass-infra/raw/`, `backend/*.db`, `.env`. All of these are gitignored. State and plans can contain sensitive values.

## Security hardening (from the independent review, 2026-11-07)

Fixed and covered by tests:
- **H1:** authored and live records are separated by environment, so authored text can't attach to a real change.
- **H2:** apply is never killed and is never reported as "nothing applied" after an interrupt.
- **M1:** terminal control and bidi characters are rejected at input and neutralized at output.
- **M2:** Host allowlist against DNS rebinding.
- **M3:** fixture labels are required.
- **M4:** unsupported drift is shown as NOT CHECKED.
- **L1:** the SQLite connection is serialized with a lock.
- **L2:** SSH CIDRs must be /24 or narrower for IPv4, /48 or narrower for IPv6.
- **L3:** `TF_CLI_ARGS*` and `TF_LOG*` are stripped from Terraform's environment.
- **L4:** a failed scan marks records `failed`.
- **L5:** the Terraform binary is resolved to an absolute path.
- **L6:** plan-file cleanup warns instead of crashing.
- **L7:** the API no longer echoes `ValueError` text.

Verified OK by the reviewer:
- The token never leaves the child process environment.
- Commands use argument arrays and an allowlisted directory.
- No HTTP route runs Terraform.
- SQL is parameterized.
- Confirmation phrases are required, and the plan hash, config and workspace are re-verified before apply.
- Resolution requires both checks.

Open (by design or pending the spike):
- A missing `resource_drift` key is treated as "no drift" (I2). Still unchecked: the real captures always had `resource_drift` present because of the provider noise.
- The API is unauthenticated, local only.

## Runbooks

### CLI handoff (primary path)
Reasons are captured in the terminal first. The dashboard is for visibility, and the web report form is the fallback.
1. `breakglass scan` shows what Argus detected (resource and change), then asks **"Why was this change needed?"**, **"Your name"** (optional) and keep/revert/unsure. The reason is saved as self-reported (`source=cli`).
2. Pressing Enter at the first question skips it. The record stays open and unexplained, and a later apply warning says "no reason recorded".
3. A later `breakglass apply` that would undo the change shows that exact reason and name in its warning.
4. If stdin is not an interactive terminal, the scan does not ask. It prints, per unexplained record, `breakglass report <id> --reason "..." --reporter "..."` instead of skipping silently. `--no-prompt` turns both off.

Verified offline (`tests/test_cli_handoff.py`, authored fixtures and a fake Terraform runner). Not yet run end to end on real Terraform with the two-question prompt.

### Preflight (before the demo)
1. `[bool](Test-Path $HOME\.secrets\digitalocean_token)` is True. Don't print the file.
2. `cd backend && python -m pytest -q` is all green.
3. `terraform -chdir=break-glass-infra validate`.
4. `breakglass list --all` shows the expected state. Reset if needed (below).
5. The API is up: `curl http://localhost:8000/api/health`.

### Reset between rehearsals
1. Run `breakglass demo-reset` on the operator machine with the token loaded. It does four things:
   - asks you to type `reset`, then deletes local records, history and apply runs;
   - checks the Terraform folder, token presence (never shown), `BG_ADMIN_TOKEN` and the API;
   - runs a **read-only** refresh-only plan, which is never applied and never saved as a record;
   - exits with `0` when the firewall is clean, `2` with a list if drift is left over (e.g. the 8443 rule), and `1` if it could not verify. A failed check is never reported as clean.
2. If it reports drift, remove the leftover rule in the DigitalOcean console (a human action) and run `breakglass demo-reset --yes` again until it says clean.
3. To keep history instead of wiping it, use `breakglass recheck`. It resolves records only when the live firewall, state and config agree.

### Real spike / provisioning — EACH STEP NEEDS TEAM APPROVAL
Runs on **Daniel's machine** (the single operator: it holds the Terraform state, runs the backend and the UI).
1. Baseline: `breakglass scan` should say 0 new (no drift).
2. Console: add inbound tcp 8443 from `0.0.0.0/0, ::/0` to `break-glass-demo` (the "emergency fix").
3. `breakglass scan` should give one `added` record and the "Why was this change needed?" prompt. The refresh-only plan is never applied.
4. Capture: `terraform plan -refresh-only -out=scan.tfplan` and `terraform plan -out=apply.tfplan`, each saved with `terraform show -json scan.tfplan > raw/scan.json` (`raw/` and `*.json` in that folder are gitignored). Send privately to Samuel to sanitize into `backend/tests/fixtures/real/`.
5. `breakglass apply` shows the warning; choose keep or cancel (nothing applied). The apply run appears in the UI.

### Teardown (approved only)
On Daniel's machine: set `attach_firewall = false` (if it was attached), apply, then `terraform -chdir=break-glass-infra destroy`. Both steps need approval. Confirm in the console that the firewall is gone. Delete the unused droplet if it's no longer needed, and revoke the token after the hackathon.

## Verification log

- 2026-11-07: offline suite, see the latest run in the PR or handoff. CLI smoke test against authored fixtures: seed → dedup scan → report → decide → recheck stays open while the plan reverses → malformed scan fails loudly and marks the record `failed`.
- 2026-11-07: 164 tests pass after security hardening.
- 2026-11-07, first real cloud results (Samuel's machine):
  - `terraform plan` on `break-glass-infra` succeeded. The token scopes are sufficient.
  - Real output showed `action = "allow"` on every rule, which is now part of rule identity.
  - `apply` was refused with `409 duplicate name`: Daniel had already applied the same firewall from his machine. That confirmed the one-state-owner rule, so Daniel's machine is the operator. Nothing was created from Samuel's machine.
- 2026-11-07, real spike on Daniel's machine (no `terraform apply` was run; the wrapper only ever took cancel or keep):
  - Baseline `breakglass scan`: 0 new, plus the `droplet_ids`/`tags` null-versus-empty noise reported as NOT CHECKED.
  - After adding tcp/8443 in the console: `scan` recorded one `added` record. The real normal plan removes it; the matcher flags the reversal.
  - `breakglass apply` (stdin closed, so cancel): paused with "No reason recorded", outcome `cancelled`. After a demo reason was added: showed the reason, answered keep, outcome `kept`. The 8443 rule stayed live both times.
  - API and web UI showed the live record and runs; the admin log showed the chain for two actors with the reviewed plan fingerprint.
  - After the rule was deleted in the console, `breakglass recheck` left the record open as `unsupported` because of the noise. Fixed in the detector and covered by `test_recheck_resolves_after_rule_removed_despite_provider_noise`.
  - Re-running `breakglass recheck` with the fix: `resolved (verified aligned)`. The record's history (change, cancelled and kept runs, explanation, keep review, resolution) was still there afterwards, with no gaps in the admin timeline.
