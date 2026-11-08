# Handoff: real Terraform spike

> **Update 2026-11-07, after running the spike:** H1, H2 and H4 held on real output; H3 and H5 were not run. No code assumption was wrong. One real finding (provider `null` versus `[]` noise blocking `recheck`) was fixed in the detector. Results are in `docs/BACKEND.md` (Evidence and Verification log) and the captures are in `backend/tests/fixtures/real/`. What remains is listed under "Where things stand" in `docs/PROJECT.md`. The rest of this file is the original plan and is kept for reference.

Written 2026-11-07 against `main` @ `b613b29`. Source of truth for scope: [Break-Glass Handoff — PRD](<Break-Glass Handoff — PRD.md>). This handoff records state and a plan; it is **not** a record of executed results.

## Goal

Find out whether the detector works on **real** Terraform output. Everything so far was tested on hand-written ("authored") fixtures and a mocked Terraform runner. The spike should answer, in order:

| # | Question | Why it matters |
|---|---|---|
| H1 | In `terraform plan -refresh-only -json`, under `resource_drift[]`, is `change.before` the prior **state** and `change.after` the **live** value? | The detector assumes yes. If not, every record's baseline/observed is swapped. |
| H2 | In a normal plan's `resource_changes[]`, is `before` the refreshed current value and `after` the config? Does the matcher flag the console-added rule as reversed? | R4: the wrapper warning depends on it. |
| H3 | What does a refresh-only plan with **no** drift look like? Is `resource_drift` absent or empty? | Backend treats a missing key as "no drift" (open issue I2). Wrong guess = false "all clear". |
| H4 | Are rule values complete (no unknown or sensitive values)? Is `action = "allow"` present on every rule? | Unknown values become `unsupported`, never "no drift". |
| H5 (needs separate approval) | After a **keep** and a config edit, does applying the empty saved plan make state record the live value so `recheck` can resolve? | Hypothesis behind the keep path (R11). |

Acceptance items this unblocks (PRD §9): staged change detected and shown in the web app; matching reversion pauses with the explanation; reconciliation verified before closure.

## Where things stand

- `main` has: detector, matcher, SQLite records, append-only events (R6/R10), review persisted before apply (R7), unknown outcomes (R8), FastAPI, CLI, guarded `breakglass apply`, `recheck`, the web UI (records, report form, apply-warning view, phone layout), and the admin log API (R9 backend: bearer token, filters, record timeline).
- CI runs frontend checks and the backend pytest suite (273 backend, 50 frontend tests at last run).
- **Not built:** admin dashboard UI, analytics/agent. Older `/api/records` and `/api/apply-runs` endpoints are unauthenticated. Admin auth is one shared token.
- Everything the backend knows about Terraform output comes from `backend/tests/fixtures/authored/`. `backend/tests/fixtures/real/` does not exist yet.
- Earlier real results (Samuel's machine, 2026-11-07): a real `plan` on `break-glass-infra` succeeded and showed `action = "allow"` on every rule. An `apply` from his machine was refused (`409 duplicate name`) because the firewall was already applied from yours. **One machine owns the state: yours.**

## Infrastructure (`break-glass-infra/`)

- One resource: `digitalocean_firewall.demo`, named `break-glass-demo`. Inbound: tcp/22 from your `/32`. Outbound: all tcp/udp/icmp.
- Variables: `droplet_id`, `admin_ipv4_cidr`, `attach_firewall` (default `false`). Values live in your local `terraform.tfvars` (gitignored; not read for this handoff).
- If `attach_firewall` is `false`, the firewall is not attached to the droplet, so a console edit to it affects no live traffic. Check your tfvars before the console edit and don't paste its contents anywhere.
- Local, gitignored, may contain secrets: `terraform.tfstate`, `terraform.tfstate.backup`, `terraform.tfvars`, `*.tfplan`, `break-glass-infra/raw/`.

## Preconditions on this machine (checked 2026-11-07)

| Item | State |
|---|---|
| Terraform | v1.17.1 at `~/.local/bin/terraform` |
| `break-glass-infra/.terraform` (init done) | present |
| `terraform.tfstate` / `terraform.tfvars` | present locally (contents not inspected) |
| DigitalOcean token | **Not visible to the assistant's shell** (no `~/.secrets/digitalocean_token`, no `DIGITALOCEAN_TOKEN` in that environment). Daniel reports a working token and a firewall already applied from this machine, so it is probably exported in an interactive shell profile. Confirm in your own terminal (below) |
| Backend DB | none yet (`backend/breakglass.db` is created on first use) |

### Make sure the backend can see your token

The backend (`tfrunner.py`) uses `DIGITALOCEAN_TOKEN` if it is already set in the environment of the process that starts it. Otherwise it reads the file at `BG_DO_TOKEN_FILE` (default `~/.secrets/digitalocean_token`) into the **Terraform child process only**. Either works. Check from the terminal where you will run `breakglass` (prints nothing secret):

```sh
[ -n "$DIGITALOCEAN_TOKEN" ] && echo "env token: set" || echo "env token: not set"
[ -f ~/.secrets/digitalocean_token ] && echo "token file: present" || echo "token file: absent"
```

If the token is exported from `~/.zshrc`, start the backend and the `breakglass` CLI from that same terminal and it will be picked up. If you'd rather use a file, put it at the default path with `chmod 600`, or point `BG_DO_TOKEN_FILE` at wherever it is. Never paste the token into chat, a commit or a log. Revoke it after the hackathon.

## Rules for the spike

- **Each cloud step needs team approval** (BACKEND.md runbook, PRD §9). Read-only `plan`/`scan` are the low-risk ones; the console edit changes cloud state.
- Never run `terraform apply` on `scan.tfplan` or `apply.tfplan` by hand. At the `breakglass apply` prompt choose **keep** or **cancel** only. Do not choose revert or override unless the team approved a real apply.
- Raw plan JSON can contain secrets or account details. Keep it under `break-glass-infra/raw/` (gitignored), don't paste it into chat, and sanitize before it becomes a fixture.
- Run the wrapper from **one terminal**. Starting `breakglass apply` marks any other unfinished run in the same environment `unknown`.

## Procedure

Set up the backend once:

```sh
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q                       # expect all green, offline
export BG_ADMIN_TOKEN="$(openssl rand -hex 24)"   # optional, for the admin log; keep it local
```

1. **Preflight (read-only).** `terraform -chdir=../break-glass-infra validate`, then `breakglass list --all` (expect nothing).
2. **Baseline.** `breakglass scan --no-prompt`. Expect "0 new". If Terraform wants to **create** the firewall, the local state doesn't match the cloud. Stop and sort that out first.
3. **Capture the no-drift JSON (answers H3).** From `break-glass-infra/`:
   ```sh
   mkdir -p raw
   terraform plan -refresh-only -input=false -out=scan0.tfplan
   terraform show -json scan0.tfplan > raw/scan_nodrift.json
   rm -f scan0.tfplan
   ```
4. **Console edit (the "emergency fix").** In the DigitalOcean console add inbound tcp `8443` from `0.0.0.0/0, ::/0` to `break-glass-demo`.
5. **Detect.** `breakglass scan`. Expect one `added` record and the one-line "name: reason" prompt. Answer it (this also exercises the explanation path).
6. **Capture the drifted JSON (answers H1, H2, H4).** From `break-glass-infra/`:
   ```sh
   terraform plan -refresh-only -input=false -out=scan.tfplan
   terraform show -json scan.tfplan > raw/scan.json
   terraform plan -input=false -out=apply.tfplan
   terraform show -json apply.tfplan > raw/apply.json
   rm -f scan.tfplan apply.tfplan
   ```
   Inspect (stays local):
   ```sh
   jq '.resource_drift[] | {address, before: .change.before.inbound_rule, after: .change.after.inbound_rule}' raw/scan.json
   jq '.resource_changes[] | {address, actions: .change.actions, before: .change.before.inbound_rule, after: .change.after.inbound_rule}' raw/apply.json
   jq 'keys, (.resource_drift // "ABSENT" | type)' raw/scan_nodrift.json
   ```
   - **H1 holds** if the 8443 rule appears in `after` and not `before` of the drift entry.
   - **H2 holds** if the normal plan's `before` contains 8443 and `after` does not (the plan would remove it).
7. **Wrapper review (answers R4/R5 for real).** `breakglass apply`. Expect the warning naming the 8443 rule with your reason. Choose **k** (keep) or **c** (cancel); nothing is applied. Then check:
   - `curl localhost:8000/api/apply-runs` shows the run with outcome `kept` or `cancelled`.
   - Admin log: `curl -H "Authorization: Bearer $BG_ADMIN_TOKEN" localhost:8000/api/admin/log` shows change, explanation, review and run events.
8. **Look at it in the UI.** `uvicorn breakglass.api:app --port 8000` in one terminal, `npm run dev` at the repo root in another (Vite may pick 5174 if 5173 is busy). Confirm the record, reason, and the apply-warning view render real data.
9. **H5 (separate approval).** Keep path: edit `main.tf` to add the 8443 rule, run `breakglass apply` (it offers to apply the empty saved plan), then `breakglass recheck`. This changes Terraform state, so get approval first.
10. **Clean up.** Remove the 8443 rule in the console, `breakglass recheck`, delete `raw/` and any `*.tfplan`. Teardown (`destroy`) is separate and needs approval (BACKEND.md "Teardown").

## If a hypothesis fails

- H1/H2 fail: flip the detector and the authored fixtures **together**, test-first (`backend/breakglass/detector.py`, `matcher.py`, `backend/tests/test_detector.py`, `test_matcher.py`). BACKEND.md names `test_authored_fixture_direction_baseline_8080_observed_8443` as the test that encodes the assumption.
- H3 fails: change how a missing or empty `resource_drift` is handled so unknown never reads as "no drift", and add a test with the real shape.
- Anything unexpected: save the sanitized JSON under `backend/tests/fixtures/real/` and add a test that replays it; don't hand-edit it to fit the code.

## Sanitizing a capture into a fixture

Replace account IDs, droplet IDs, your public IP/CIDR and the firewall ID with obvious fakes, keep the **structure and key names exactly**, and note the replacements in a README beside the file. Fixtures are labelled `real-fixture`; they live in environment `<env>-replay` so they can never merge with live records.

## What to report back

For each of H1–H5: held / failed / not run, plus the sanitized snippet. Do not send the token, tfvars, state, or unsanitized JSON. With that I can update the detector and fixtures test-first and refresh the acceptance table.

## Key files

- `break-glass-infra/main.tf`: the demo firewall
- `backend/breakglass/{detector,matcher,rules,service,wrapper,tfrunner,admin,api}.py`
- `backend/tests/fixtures/authored/`: hand-written fixtures to compare against real output
- `docs/BACKEND.md` (runbooks, guarded apply), `docs/API.md`, `docs/FRONTEND.md`, `docs/PROJECT.md`
