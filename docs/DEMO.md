# Live demo runbook (Argus on Tiger Cloud + Terraform + DigitalOcean)

Written 2026-11-08 from the code and `docs/BACKEND.md`. Commands are macOS/zsh, run from the repo root. The CLI is `./argus` (the repo-root launcher; also the `argus` command once installed). The old `breakglass` command and `python -m breakglass.cli` still work. **Not yet
rehearsed end to end as one script:** each piece was verified on its own (see `docs/FRONTEND.md`, `docs/BACKEND.md`);
do one full dry run the day before.

## The story (about 3 minutes)
Someone fixes an outage by hand in the DigitalOcean console (opens a port). Terraform does not know. The next
`terraform apply` would silently undo the fix and re-break production. Argus notices the manual change, asks the person
why, and when the next apply would reverse it, stops and shows that reason so a human decides.

## One-time setup: a week of history (your call; writes to Tiger)
The live flow only creates a few records, so the admin Overview, chart and All records would look empty. This adds a
week of **authored** history so they have something to show. It is labelled (`DEMO DATA · demo-history-authored ·
authored-fixture` in the UI), lives in its own `demo-history-authored` environment, and never mixes with live records.

```
set -a && . ./.env && set +a
./argus seed-history          # dry: prints where it would write, writes nothing
./argus seed-history --yes    # writes: 7 records, 6 runs, 14 scans
```
- It refuses to run twice, so it cannot duplicate history.
- It contains no run with an unknown outcome (every run has a recorded completion).
- People in it are made up (`priya@example.com` is the only verified account).

**Never run `demo-reset` or `reset-db` against Tiger.** They delete all records, history and runs in whatever database
is configured, including this seeded history and your real records.

## Before the demo (30 minutes ahead)
1. **Token present** (do not print it): `test -s ~/.secrets/digitalocean_token && echo ok`
2. **Stale processes:** `lsof -nP -iTCP:8000 -sTCP:LISTEN` and `lsof -nP -iTCP:5173 -sTCP:LISTEN` should print nothing. Kill old ones (`kill <pid>`). A stale API once served the wrong code.
3. **API** (terminal 1): `set -a && . ./.env && set +a && cd backend && .venv/bin/uvicorn breakglass.api:app --port 8000`. Wait for "Application startup complete", then `curl -s http://127.0.0.1:8000/api/health` should show `"db":"ok"`.
4. **UI** (terminal 2): `npm run dev`, open http://localhost:5173, sign in with Google using an admin account (an email in `BG_ADMIN_EMAILS`). Check you land on Overview with the Admin badge.
5. **Clean baseline scan** (terminal 3): `set -a && . ./.env && set +a && ./argus scan --no-prompt` should say `Scan ok: 0 new`. This also refreshes **Last scan**, which shows its age ("4 min ago") and turns amber only if there has never been a scan or the last one failed. If it says 1 new, the firewall already has a leftover manual rule: remove it in the console (see "Reset" below) and scan again.
6. **Look at the Overview.** Nothing amber except what you expect. Last apply should be a clean outcome, not "Unknown".
7. Terraform config valid: `terraform -chdir=break-glass-infra validate`.

## The live flow
**1. Show the week (Overview, then the palette).** Overview: open records, hourly chart, run outcomes. Press ⌘K and type a name (`priya`) to show records and events found by person. Say: admins review, they do not edit; "unknown" is never shown as failure.

**2. Make the manual change in DigitalOcean.** Console → Networking → Firewalls → `break-glass-demo` → Inbound Rules → add a **Custom TCP** rule, port **8443**, sources **All IPv4, All IPv6** → Save. (Menu names may differ slightly.) This is the "emergency fix". Terraform does not know about it.

**3. Argus notices.** Terminal 3: `set -a && . ./.env && set +a && ./argus scan`
- It shows `1 new` (an `added` rule on `digitalocean_firewall.demo`) and asks **"Why was this change needed?"**, **"Your name"** (optional) and keep/revert/unsure. Answer something like: "payment webhook blocked, opened 8443", your name, keep.
- This was a read-only refresh plan. Nothing was applied.

**4. Show it in the UI.** Refresh the Overview: Open records goes up, Events up. Open All records, then the new record: explained by your name (self-reported, not verified), detected time with the note "when the scanner noticed, not when the change was made", full history. Say: reports show who submitted, never who made the change.

**5. Show the danger: what a normal apply would do.** `terraform -chdir=break-glass-infra plan` (read-only) shows the 8443 rule would be removed. Say: this is what an engineer's routine apply would do.

**6. The guard.** `set -a && . ./.env && set +a && ./argus apply`
- It plans, then prints `WARNING: this apply would reverse manual emergency change(s)` with **your reason and name** and how long ago it was detected.
- Choose **`k`** (keep, nothing applied). It asks for a **required short rationale** (type one, for example "webhook provider only supports 8443"), saves the intent, prints the Terraform edit that would make the change permanent, and applies nothing. Recommended for the demo.
- `c` cancels (also applies nothing). **Do not choose `r` (revert) or `o` (override) live** unless the team approved a real `terraform apply` in advance: they apply to real infrastructure.

**7. Show the trail.** UI: Overview Last apply = Kept; Events / the Record page show change, report, decision, run, with who and how trustworthy each identity is. Say: unknown outcomes are flagged, never assumed successful.

## Reset after the demo (keeps history)
1. Remove the 8443 rule in the console (a human action).
2. `set -a && . ./.env && set +a && ./argus recheck` should say `resolved (verified aligned)`. The record's history stays.
3. Do not use `demo-reset` (see the warning above).

## If something goes wrong
| Symptom | What it means / do |
|---|---|
| UI says "Backend unavailable" | API down or Tiger unreachable (the API returns 503). Check terminal 1 and `curl /api/health`. It is an error, never "no changes". |
| `scan` prints `SCAN FAILED` | Terraform or the token failed. Open records are marked failed; this is **not** "no drift". Check the token file and `terraform -chdir=break-glass-infra validate`. |
| Sign-in fails | The admin screens need a Google admin sign-in; there is no offline fallback page any more. |
| You land on the employee records page instead of Overview | That account is not in `BG_ADMIN_EMAILS` (server says not an admin). Sign in with an admin account. |
| Last scan is amber | There has never been a scan, or the last one failed. Run the baseline scan again. (An old but successful scan is not amber; it just shows its age.) Last apply amber means an unknown or failed outcome. |
| "address already in use" on 8000 | An old API is running: `lsof -nP -iTCP:8000 -sTCP:LISTEN`, then `kill <pid>`. |
| Need to restore the week | Do not re-seed over existing data (it refuses). The seeded records are in `demo-history-authored`. |

## Rules for the team
- Terraform, `argus` and the API all run on **one operator machine** (it holds the Terraform state). Never apply this config from a second machine.
- No `terraform apply`, `destroy` or other infrastructure change without explicit team approval.
- Never read or paste `.env` or the DigitalOcean token into chat or screenshots.
