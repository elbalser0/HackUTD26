# Handoff for the next agent

Written 2026-11-07 after PR #11; updated after PR #21 (admin dashboard UI, keep/defer rationale and `demo-reset`, Firebase Google sign-in, rename to Argus, logo, consolidated account menu). Read this first, then the [PRD](<Break-Glass Handoff — PRD.md>) (source of truth for scope and acceptance; it records requirements, not results). This file is a status snapshot, not a spec: when it disagrees with the code or the PRD, trust those.

## What this is

**Argus** (HackUTD26, NMC² challenge). When an engineer changes infrastructure by hand during an incident, a later `terraform apply` can silently undo it. The backend detects the manual change from a Terraform refresh-only plan, stores the explanation, and the guarded `breakglass apply` wrapper pauses an apply that would reverse it, requiring an explicit decision. History is append-only. The web UI is read-only and never runs Terraform. Demo target: one DigitalOcean firewall (`digitalocean_firewall.demo`, "break-glass-demo") in `break-glass-infra/`.

Team: Daniel (product, frontend; the only machine that holds the Terraform state), Samuel (backend), Andrew (infrastructure). Either Daniel or Samuel may be the user you are working with; check the git user. Real Terraform steps run only on Daniel's machine.

## How the user wants you to work

These came from corrections and approvals in earlier sessions. Follow them.

- **Test-first.** Write the failing test, watch it fail for the *right* reason, then implement. Mutation-check important logic (break the code on purpose; a surviving mutant means a weak test). Docs have tests too (`src/docs.test.ts`) so wording can't drift into overclaiming.
- **Never read, open, grep or source `.env`.** It holds `DIGITALOCEAN_TOKEN`. The backend reads only its `BG_*` lines (settings such as `BG_FIREBASE_PROJECT_ID`, `BG_ADMIN_EMAILS`) and ignores every other line; to change a `BG_` setting, tell the user which line to add rather than editing the file. When a step needs the token, give the user a command to run themselves (see "Running real Terraform steps"). Never ask for or print token values.
- **No cloud operation without explicit team approval.** Console edits, applies and state changes are the user's call. Never run `terraform apply`. At wrapper prompts only keep or cancel unless the user has approved a real apply.
- **Commit, push, open a PR and merge only when the user asks.** They have said "yes" per task so far: branch off `main`, commit, push, open the PR, wait for both CI jobs, then `gh pr merge --merge` and pull `main`. Don't work on `main` directly.
- **Be honest about verification.** Say what ran on real Terraform, what ran only against authored fixtures or a mocked runner, and what has not run. Don't report acceptance criteria as done unless they were verified.
- Keep answers short. Recommend, don't survey. Refer to people with they/them unless told otherwise.

## State of the code (main, after PR #21)

| Piece | Where | Notes |
|---|---|---|
| Detector, matcher, rules | `backend/breakglass/{detector,matcher,rules,suggest}.py` | Only `digitalocean_firewall` `inbound_rule` is interpreted; anything else is reported as unsupported, never as "no drift". Null and empty collections compare equal (`detector._empty_is_none`). |
| Records, append-only events, runs | `db.py`, `service.py`, SQLite | Reports, decisions, wrapper reviews and run start/finish are never overwritten. |
| Guarded apply wrapper | `wrapper.py`, CLI `breakglass apply` | Review (decision, rationale, reviewer, plan fingerprint) is saved in one transaction with the run marked `running` before Terraform runs. Runs with no recorded completion become `unknown`. Keep and defer require a rationale (otherwise the run is recorded as a cancel); cancel never does. |
| Demo reset | `demo.py`, CLI `breakglass demo-reset` | Typed confirmation, wipes local demo data, checks the Terraform dir, token presence, admin auth and API, then runs a read-only refresh-only plan (never applied, never ingested). Leftover drift exits 2; a failed check is "could not verify", never clean. |
| Database | `backend/breakglass.db` (SQLite, WAL; `BG_DB_PATH` overrides) | Tables `records`, `apply_runs`, `events` (append-only), `scans`. Persists across restarts; local to one machine, no shared store. |
| Google sign-in | `auth.py`, `src/auth.ts`, `src/components/AuthProvider.tsx` | Off unless `BG_FIREBASE_PROJECT_ID` is set. Then web writes need a verified-email Firebase ID token (401/403 with distinct codes) and record the email as `google-account (verified sign-in)`; reads stay open. Full-page sign-in, header account menu (photo, name and email; Sign out in a dropdown), session ends when the tab closes; a fresh ID token per write, none stored. The Firebase web config (`VITE_FIREBASE_*`) is public. |
| HTTP API | `api.py`, `docs/API.md` | Read plus annotate only; no route runs Terraform. |
| Admin log (PRD R9 backend) | `admin.py`, `/api/admin/log`, `/api/admin/records/{id}/timeline` | Fails closed. Accepts a Firebase sign-in whose email is in `BG_ADMIN_EMAILS` (signed-in non-admins get 403), or the shared fallback token `BG_ADMIN_TOKEN`. Reads events, records and runs. |
| Web UI | `src/` | Records list and detail, report form, apply-warning view; phone layout checked at 375 and 320px. Read-only. Argus logo: the lockup `public/argus-logo.svg` (sidebar and sign-in page) and the eye-only `public/argus-mark.svg` (favicon); the old B² mark is gone and a test fails if it returns. Header account menu: one button (photo, name, email) whose dropdown holds Sign out; closes on a second click, Escape or an outside click; no "Verified Google account" badge (the report form still names the verified account that saves an explanation). Admin dashboard UI at `#/admin` ("Continue as <email>" or the shared token; run against the real backend with a throwaway token; see "What is verified"). |
| Real captures and replay tests | `backend/tests/fixtures/real/`, `tests/test_real_replay.py` | Sanitized (fake firewall id, `203.0.113.10`, fake droplet id). Its README lists what was replaced. |
| CI | `.github/workflows/ci.yml` | Two jobs: frontend (`lint`, `test`, `build`) and `backend` (`pytest`, offline). |

The older `/api/records` and `/api/apply-runs` endpoints are still unauthenticated (open decision).

## What is verified, and what is not

**Verified on real Terraform and DigitalOcean** (2026-11-07, run from the user's machine; no `terraform apply` was ever run):
- A console-added rule is detected as `added`: in a refresh-only plan `change.before` is the prior state and `change.after` is the live value; `resource_changes` is absent from a refresh-only plan; every rule carries `action = "allow"`.
- The real normal plan reverses that rule as an in-place `update`, and the matcher flags it. A plan from the clean state flags nothing.
- The wrapper pauses before any apply, with "No reason recorded" and with a reason; cancel and keep applied nothing.
- The UI (LIVE API badge) and the admin log over HTTP showed the real record and runs for two actors, with the reviewed plan fingerprint; the admin API returns 401 without a token.
- The admin dashboard UI against the real backend with a throwaway `BG_ADMIN_TOKEN` (2026-11-07, real browser, no Terraform or cloud access): wrong token shows "Token rejected" (401), no server token shows "not configured" (403), the real spike record and the authored record appear with actor assurance labels, engineer and outcome filters work, a record timeline shows the real history through `verified_aligned`, an unknown record id shows "not found", and the token is forgotten on reload. Re-checked on `main` after the Google sign-in UI merged (shared-token path): each finished run shows its outcome once.
- Not yet seen live in the admin dashboard: an `unknown` outcome and the timeline gaps box (the data has no unfinished run, and creating one needs a real interrupted apply), and the Google-admin path (needs a Firebase project; the team ran the sign-in itself).
- After the rule was deleted, `breakglass recheck` resolved the record as `verified_aligned` with its history intact (R11).
- One real bug was found and fixed: the provider reports `droplet_ids` and `tags` as `null` in older state and `[]` live, which made recheck refuse to resolve any record.

**Not yet run for real** (mocked or authored tests only), starting with a confirmed revert or override apply:
- That apply: execution of the reviewed plan, abort when the plan changed, a failed decision write blocking the apply, an interrupt mid-apply.
- The keep-path state sync (H5): after a keep and a config edit, does applying the empty saved plan record the live value? It changes Terraform state, so it needs approval.
- A drift-free refresh-only plan. The provider noise kept `resource_drift` present in every capture, so the assumption that a missing key means no drift (open issue I2) is unchecked.
- The 409 and 422 UI cases against the real backend.

**Run by the team, not by an agent:** the Google sign-in UI against a real Firebase project (2026-11-07), reported working. The team plans to improve it. Real Google sign-in was not re-run after the account menu change: an agent only saw the menu in a real browser on a temporary preview page with a fake signed-in user (since deleted), so check one real sign-in and sign-out.

Wrapper actors are self-reported or the local OS user (labelled "not verified"). Nothing here proves service health.

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
5. `breakglass scan --no-prompt` skips the reason questions (a non-interactive scan prints the `report` command instead); add the reason with `breakglass report <id> --reporter "Name (demo)" --reason "..."`. Use fake demo names.
6. Capture plans into `break-glass-infra/raw/` (gitignored): `terraform plan -refresh-only -out=scan.tfplan`, `terraform show -json scan.tfplan > raw/scan.json`, and the same for a normal `plan`. Never apply those plans. Delete them and `raw/` afterwards; they hold the real IP and firewall id.
7. To make a fixture: replace every IPv4, UUID and long number with fakes, keep the structure byte-for-byte, and prove programmatically that no original value remains. See `backend/tests/fixtures/real/README.md`.

Local state (`break-glass-infra/terraform.tfstate`, `terraform.tfvars`, `.terraform/`) is gitignored. Don't print it.

## Gotchas

- **Naming:** the product is **Argus**. Only user-facing text and the docs were renamed. Deliberately unchanged: the Python package and CLI (`breakglass`), `BG_*` env vars, the `break-glass-infra/` directory, the real cloud firewall name `break-glass-demo` (renaming it would change a cloud resource), and the PRD filename (links and tests point at it). Don't rename those without the user asking.

- One machine owns the Terraform state (the user's). Starting `breakglass apply` marks any other unfinished run in the same environment `unknown`, so run it from one terminal.
- The firewall is not attached to the droplet (`attach_firewall = false`), so console edits to it affect no live traffic. The user's DigitalOcean console edits are theirs to make; don't do them through the browser unless told.
- Authored and replayed data go to `<env>-authored` and `<env>-replay` and can never merge with or resolve live records. `--label` is required for `--from-json`.
- **macOS:** `sed -i` needs an empty suffix argument (`sed -i '' ...`); the Linux form fails silently. Python edits were more reliable. zsh also errors on unmatched globs such as `--include=*.tsx`; quote them.
- **Ports:** another project's dev server can already hold port 5173 (check what owns a port with `lsof` before assuming it is this repo's, and don't kill things you did not start). Vite then picks 5174.
- **Stale venv:** after pulling backend changes, run `pip install -e ".[dev]"` in `backend/.venv`, or tests fail to import new dependencies such as the Firebase packages. Pillow and numpy are not in the project venv; use a throwaway venv for image work.
- **Visual check of signed-in UI without Firebase:** make a temporary preview page (a second HTML entry plus a small `.tsx`) that calls `setAuthClient` with a fake client and renders `<App />`, view it on a spare Vite port, then delete both files. Never commit it.
- **Docs-vs-code guards:** `src/docs.test.ts` reads the backend source, so a new `BG_*` env var must appear in `docs/BACKEND.md`, a new route needs its own heading in `docs/API.md`, and the `API.md` limitations must match `admin.py`. Don't put test counts in docs; they go stale on every PR.
- `docs/PROJECT.md` carries the status table against R1-R12 and the next decision gate. Keep it, `docs/BACKEND.md` and the README in step with the code. The docs tests will fail on stale claims.
- The demo record and its history are in the local `backend/breakglass.db` (gitignored). `breakglass reset-db --yes` clears it.

## Next steps

0. **CLI handoff real run (Daniel's machine):** the scan → "Why was this change needed?" → apply-warning flow is verified offline (`tests/test_cli_handoff.py`) but not yet run on real Terraform with the new prompt. Checklist: console-add tcp 8443, `breakglass scan` and answer, `breakglass list`, `breakglass apply < /dev/null` shows the exact reason; repeat skipping the reason (warning says "no reason recorded"); delete the console rules and `breakglass recheck`. No apply. Then Tiger Cloud (shared Postgres) is planned next.
1. **Google sign-in UI improvements**: the team ran it and it works; they plan to improve it. Wait for their direction. Then run the admin dashboard with a signed-in admin email (the shared-token path already ran against the real backend; see "What is verified"). Bearer header only, never in a URL.
2. **Optional real spike items, each needing approval:** a confirmed revert or override apply (reviewed-plan execution, changed-plan abort), the keep-path state sync (H5), and capturing a drift-free refresh-only plan (likely needs `terraform apply` of a refresh-only plan to clear the provider noise in state; that changes state only).
3. **Decisions for the user:** whether the shared `BG_ADMIN_TOKEN` fallback stays now that per-admin sign-in exists, whether the local SQLite file is enough or the history needs a shared store, whether `/api/records` and `/api/apply-runs` should also require authorization, retention, and the 409/422 UI states.
4. **Later, only after the core demo works:** analytics and the classifier (PRD §7, proposed). The user asked to skip the demo script, fallback video and sponsor conversations for now; don't start them unprompted.

## Key files

- `docs/Break-Glass Handoff — PRD.md`: requirements and acceptance checklist
- `docs/PROJECT.md`, `docs/BACKEND.md`, `docs/API.md`, `docs/FRONTEND.md`: status, rules, contract, UI evidence
- `backend/breakglass/`: the backend; `backend/tests/`: tests and fixtures (`authored/`, `real/`)
- `break-glass-infra/main.tf`: the demo firewall
- `src/api.ts`: the single wire-mapping seam between the API and the UI
- `src/docs.test.ts`, `src/mobile.test.ts`: contract tests for the docs, CI and phone layout
