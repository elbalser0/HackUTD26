# Break-Glass Handoff

HackUTD 2026 project for the NMC² challenge. During an incident an engineer may change infrastructure by hand without updating Terraform, and a later `terraform apply` can silently undo that fix. Break-Glass Handoff records the emergency change and its explanation, then pauses a later apply that would reverse it. The engineer must acknowledge or cancel with the context in front of them.

The [PRD](<docs/Break-Glass Handoff — PRD.md>) is the source of truth for scope and acceptance. It records requirements, **not** implemented or verified results. This is an independent hackathon project, not affiliated with or endorsed by NMC².

## What exists

| Piece | Where | State |
|---|---|---|
| Detector, matcher, SQLite records, report and decision history, FastAPI, CLI, guarded apply wrapper, `recheck` | `backend/` | Written and tested offline. Terraform is mocked, and every fixture is hand-written (authored). |
| Web UI: open records, record detail and report form, apply-warning view | `src/` | Built. Read-only: it **never runs Terraform**. The CLI owns execution and approval. |
| Demo Terraform (firewall `digitalocean_firewall.demo`) | `break-glass-infra/` | Firewall **applied** from Daniel's machine. It is not attached to the droplet (`attach_firewall = false`). |
| Real Terraform spike | n/a | **Partial.** A real `plan` succeeded. Detecting a console edit, the detector direction, the apply-run view and keep-path behavior are not yet verified against real Terraform output. |
| Admin dashboard (PRD R9: team-wide log, filters, timeline, server-side authorization) | n/a | **Not built yet.** |
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
breakglass seed-demo --with-report
uvicorn breakglass.api:app --port 8000
```

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
- [docs/PROJECT.md](docs/PROJECT.md): living decisions and next gate

## Safety and honesty

- Never commit secrets, `*.tfstate*`, `*.tfplan`, `*.tfvars`, or `.env`. Anything prefixed `VITE_` is public in the bundle.
- The DigitalOcean token lives outside the repo and is read only by the backend's Terraform child process.
- No cloud operation runs without explicit team approval.
- Reasons and reporters are self-reported, not verified authorship. Detected-at is not changed-at.
- Running `terraform apply` directly bypasses the wrapper. Enforcement through CI is a stretch goal, not built.
- Visual reference: https://nmc2.com/ (black and white, blue `#2b9cfc`). The geometric artwork and B² mark are original CSS.
