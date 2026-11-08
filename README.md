# Argus

HackUTD 2026 project for the NMC² challenge. During an incident an engineer may change infrastructure by hand without updating Terraform, and a later `terraform apply` can silently undo that fix. Argus records the emergency change and its explanation, then pauses a later apply that would reverse it. The engineer must acknowledge or cancel with the context in front of them.

The [PRD](<docs/Break-Glass Handoff — PRD.md>) is the source of truth for scope and acceptance. It records requirements, **not** implemented or verified results. This is an independent hackathon project, not affiliated with or endorsed by NMC².

## What exists

| Piece | Where | State |
|---|---|---|
| Detector, matcher, SQLite records, report and decision history, FastAPI, CLI, guarded apply wrapper, `recheck` | `backend/` | Tested offline against hand-written (authored) fixtures and a mocked Terraform runner, and replayed against sanitized **real** captures in `backend/tests/fixtures/real/`. |
| CLI handoff | `argus scan` → later `argus apply` | Primary way to capture reasons: the scan shows what was detected and asks "Why was this change needed?" and a name; the apply warning shows that reason, or "no reason recorded". Verified offline; not yet run on real Terraform with this prompt. |
| Web UI: employee Records page and palette, admin shell (Overview, All records, Record, palette), apply-warning view | `src/` | Built (redesign, stub and fixture checked; not yet run against the real API). Read-only: it **never runs Terraform**. The CLI owns execution and approval. |
| Demo Terraform (firewall `digitalocean_firewall.demo`) | `break-glass-infra/` | Firewall **applied** from Daniel's machine, the single operator that holds the Terraform state. It is not attached to the droplet (`attach_firewall = false`). The droplet already existed; Terraform manages only the firewall. |
| Real Terraform spike | `backend/tests/fixtures/real/` | **Mostly done (2026-11-07).** Verified on real Terraform and DigitalOcean: a console-added rule is detected (`before` is state, `after` is live), the normal plan's reversal is matched, the wrapper pauses (cancel and keep, nothing applied) with and without a reason, the UI and admin log show the live records and runs, and `recheck` resolved the real record as `verified_aligned` after the rule was deleted, with its history intact. Real findings: the provider reports `droplet_ids`/`tags` as `null` in state and `[]` live, which used to block `recheck`; null and empty collections now compare equal. **Not yet run for real:** a confirmed revert/override apply (reviewed-plan execution, changed-plan abort), the keep-path state sync, and a drift-free refresh-only plan. |
| Persistence | `backend/breakglass.db` (SQLite, `BG_DB_PATH` to move it) | Records, runs, scans and the append-only `events` history survive restarts. Local to one machine; no shared database. |
| Google sign-in (Firebase) | `backend/breakglass/auth.py`, `src/auth.ts`, `src/components/AuthProvider.tsx` | Built. With `BG_FIREBASE_PROJECT_ID` set, web writes need a verified-email sign-in and record the account email. Run by the team against a real Firebase project and reported working; UI improvements planned. Off when not configured. |
| Admin log API (PRD R9): team-wide event log, engineer/resource/time/outcome filters, per-record timeline, server-side authorization (signed-in email in `BG_ADMIN_EMAILS`, or the shared fallback token `BG_ADMIN_TOKEN`) | `backend/breakglass/admin.py` | Built and tested on authored data. Reads the append-only events; see its limitations in [docs/API.md](docs/API.md). |
| Admin dashboard UI (PRD R9) | `src/components/AdminShell.tsx` and the admin pages (signed-in Google admins only) | **Built and run in a real browser against the real backend with a throwaway shared token (2026-11-07), on the real spike record and authored data.** Not yet run live: the Google-admin path (needs a Firebase project), an `unknown` outcome, and the gaps box (the data has no unfinished run). Log with engineer/resource/outcome/time filters and a per-record timeline, opened as a signed-in admin or with the shared token (held in memory only, sent as a bearer header). |
| Agent classification and downtime analytics (PRD §7) | n/a | Proposed post-core phase. Not built. |

Coverage is only `digitalocean_firewall` → `inbound_rule`. Anything else is reported as unsupported, never as "no drift". See [docs/BACKEND.md](docs/BACKEND.md).

## Run it locally

Requires Node 22.12+ and Python 3.12+. You need repository access to clone.

```sh
git clone https://github.com/elbalser0/HackUTD26.git
cd HackUTD26
npm ci
```

**Backend** (authored demo data, no cloud account needed):

```sh
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
argus seed-demo --with-report
uvicorn breakglass.api:app --port 8000
```

**CLI name.** The command is `argus` (installed by `pip install -e`). From a checkout, `./argus <command>` runs it without installing anything. If your virtualenv predates the rename, re-run `pip install -e ".[dev]"` to get the `argus` command. Nothing broke: the original `breakglass` command, `python -m breakglass.cli`, the `breakglass` Python package, the `BG_*` settings and `uvicorn breakglass.api:app` all still work.

**Frontend**, in a second terminal at the repo root:

```sh
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000` (override with `API_TARGET`). Data tagged `demo-authored` is hand-written, not real detection. To work on the UI without a backend, open the app with `?fixture` (also `?fixture=empty|error|stale|failed`). It shows a "DEV FIXTURE DATA" badge.

## Checks

```sh
npm run lint
npm test            # frontend and docs/CSS contract tests; adapter stubs, not backend integration
npm run build
cd backend && python -m pytest -q
```

GitHub Actions runs the frontend checks on pushes and pull requests.

## Docs

- [Product requirements](<docs/Break-Glass Handoff — PRD.md>): source of truth
- [docs/API.md](docs/API.md): HTTP contract between backend and UI
- [docs/BACKEND.md](docs/BACKEND.md): backend status, rules, guarded apply, runbooks
- [docs/FRONTEND.md](docs/FRONTEND.md): UI status and verification evidence
- [docs/DEMO.md](docs/DEMO.md): live demo runbook (Tiger, Terraform, DigitalOcean), including the week of authored history
- [docs/PROJECT.md](docs/PROJECT.md): living decisions and next gate
- [docs/HANDOFF.md](docs/HANDOFF.md): current state, working rules, verified versus unverified, and next steps for the next agent

## Safety and honesty

- Never commit secrets, `*.tfstate*`, `*.tfplan`, `*.tfvars`, or `.env`. Anything prefixed `VITE_` is public in the bundle.
- The DigitalOcean token lives outside the repo and is read only by the backend's Terraform child process.
- No cloud operation runs without explicit team approval.
- Reasons and reporters are self-reported, not verified authorship. A Google sign-in verifies who submitted a web report or decision, not who made the console change. Detected-at is not changed-at.
- Running `terraform apply` directly bypasses the wrapper. Enforcement through CI is a stretch goal, not built.
- Visual reference: https://nmc2.com/ (black and white, blue `#2b9cfc`). The geometric artwork is original CSS. The Argus logo files in `public/` were supplied by the team.
