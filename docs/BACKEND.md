# Backend: Break-Glass Handoff

Owner: Samuel. This is a living document; keep it current. HTTP contract: [API.md](API.md). Demo infrastructure: [../infra/demo/README.md](../infra/demo/README.md).

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
| Demo Terraform (`infra/demo`) | Written; `terraform validate` passes; **not provisioned** |
| **Real Terraform spike** | **PENDING.** Token present; waiting for SSH key name, allowed IP, and team approval to plan/apply |

### Evidence: real vs. authored
- Every fixture in `backend/tests/fixtures/authored/` was **hand-written**. Its shape follows Terraform's documented plan JSON format but has not been checked against real output.
- Key hypothesis still unverified: in a refresh-only plan's `resource_drift[]`, `change.before` is the prior **state** and `change.after` is the **refreshed live** value. In a normal plan's `resource_changes[]`, `change.before` is current (refreshed) and `change.after` is config. The test `test_authored_fixture_direction_baseline_8080_observed_8443` encodes this. If the real capture shows otherwise, flip the detector and the fixtures together.
- `backend/tests/fixtures/real/` will hold sanitized real captures after the spike. Until then it is empty.

## Architecture

One FastAPI process, one SQLite file, one CLI. No microservices.

```
infra/demo (Terraform) ── terraform plan -refresh-only ──► detector ──► service.ingest_refresh_plan ──► SQLite
                        └─ terraform plan (saved)  ──► matcher ──► wrapper (warn + confirm) ──► terraform apply <saved plan>
SQLite ◄── api (GET records/apply-runs, POST report/decision) ◄── Daniel's UI
```

- `config.py`: env settings. `BG_TF_DIR` must resolve inside the repo's `infra/`.
- `tfrunner.py`: the only place that spawns Terraform. Argument arrays, `shell=False`, fixed plan file names, plans deleted after use.
- `detector.py` / `matcher.py` / `rules.py` / `suggest.py`: pure functions over plan JSON. Firewall rules are compared as **sets**, never by index.
- `service.py`: records, dedup, supersede, warnings, re-check.
- `wrapper.py`: the guarded apply flow.
- `api.py`: read + annotate only. No HTTP route runs Terraform or accepts paths or commands.

## Supported coverage

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
- **Self-reported context:** reporter and reason are self-reported, never audited attribution. `first_detected_at` is detection time, not change time.

## Guarded apply (`breakglass apply`)

1. Record the workspace and a hash of the config.
2. Run a refresh-only scan, which is never applied, and ingest it.
3. Run `terraform plan -detailed-exitcode -out=.breakglass-apply.tfplan` (0 = no changes, stop; 2 = changes; else error, stop).
4. Run `terraform show -json`, then match against open records.
5. Branch on the result:
   - **Verification failed** (scan, plan JSON or match error): prints `VERIFICATION UNAVAILABLE. This is NOT a 'no conflicts' result.` Continuing requires typing `unverified-bypass`, and that is recorded.
   - **Warnings:** keep (saves intent, prints a literal-edit suggestion, no apply) / defer (no apply) / cancel (no apply) / revert (requires typing `revert`) / override (requires typing `override`; recorded).
   - **No warnings:** requires typing `yes`.
6. Before applying, re-hash the plan file, config and workspace. On any change it aborts (`aborted_plan_changed`).
7. `terraform apply <that exact saved plan>`. A saved-plan apply doesn't prompt, so the wrapper owns confirmation.
8. Drift outside coverage is printed as `NOT CHECKED: …` and qualifies the "no reversal" message.
9. Ctrl+C during the apply step is **never** reported as "nothing applied". Terraform is allowed to stop gracefully (never killed), and the run is recorded `failed` with "live state unknown; run scan/recheck". The apply has no timeout.
10. Plan files are deleted in all cases. Each run is stored as an ApplyRun (`GET /api/apply-runs/{id}`).

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
```

Environment: `BG_ALLOWED_HOSTS` (default `localhost,127.0.0.1,[::1]`), `BG_DB_PATH` (default `backend/breakglass.db`), `BG_TF_DIR` (default `infra/demo`), `BG_ENVIRONMENT` (default `demo`), `BG_CORS_ORIGINS`, `BG_TERRAFORM_BIN`, `BG_DO_TOKEN_FILE` (default `~/.secrets/digitalocean_token`).

## Credentials

- The DigitalOcean token lives in `~/.secrets/digitalocean_token` (owner-only ACL), outside the repo. `tfrunner` reads it into the Terraform **child process environment only**, and only if `DIGITALOCEAN_TOKEN` isn't already set. It is never printed, logged or stored.
- Never commit: `*.tfstate*`, `*.tfplan`, `*.tfvars`, `.terraform/`, `infra/demo/raw/`, `backend/*.db`, `.env`. All of these are gitignored. State and plans can contain sensitive values.

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
- A missing `resource_drift` key is treated as "no drift" (I2). Revisit once the real plan JSON is captured.
- The API is unauthenticated, local only.

## Runbooks

### Preflight (before the demo)
1. `[bool](Test-Path $HOME\.secrets\digitalocean_token)` is True. Don't print the file.
2. `cd backend && python -m pytest -q` is all green.
3. `terraform -chdir=infra/demo validate`.
4. `breakglass list --all` shows the expected state. Reset if needed (below).
5. The API is up: `curl http://localhost:8000/api/health`.

### Reset between rehearsals
1. In the DigitalOcean console, set the firewall app rule back to 8080, or let a confirmed `breakglass apply` → revert do it.
2. `breakglass recheck` resolves or keeps records honestly, or `breakglass reset-db --yes` wipes demo data.

### Real spike / provisioning — EACH STEP NEEDS TEAM APPROVAL
See `infra/demo/README.md`. In short: `init` → `plan` → `apply` → console edit 8080→8443 → `breakglass scan` (the refresh-only plan is never applied) → `breakglass apply` (shows the warning) → capture sanitized fixtures into `backend/tests/fixtures/real/`.

### Teardown (approved only)
`terraform -chdir=infra/demo destroy` with the token loaded per command, then confirm in the console that the droplet and firewall are gone. Revoke the token after the hackathon.

## Verification log

- 2026-11-07: offline suite, see the latest run in the PR or handoff. CLI smoke test against authored fixtures: seed → dedup scan → report → decide → recheck stays open while the plan reverses → malformed scan fails loudly and marks the record `failed`.
- 2026-11-07: 164 tests pass after security hardening.
- Real Terraform workflow: **not yet exercised.**
