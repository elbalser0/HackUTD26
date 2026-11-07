# Break-Glass Handoff API — v0.1 contract

Owner: Samuel (backend). Consumer: Daniel (frontend). Source of truth for types: `backend/breakglass/models.py`.

## Running it

```sh
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
breakglass seed-demo --with-report  # AUTHORED demo record: environment "demo-authored", evidence_source "authored-fixture"
uvicorn breakglass.api:app --port 8000
```

- **Base URL:** `http://localhost:8000` (frontend: `VITE_API_BASE_URL=http://localhost:8000`, already in `.env.example`).
- **CORS:** allows `http://localhost:5173` and `http://127.0.0.1:5173` (Vite dev). Override with `BG_CORS_ORIGINS`.
- **Auth:** none. Local demo only. Bind to localhost; do not expose publicly.
- **Host allowlist:** requests must use host `localhost`, `127.0.0.1` or `[::1]` (otherwise `400`). This blocks DNS-rebinding pages. Override with `BG_ALLOWED_HOSTS`.
- **Content type:** JSON, UTF-8.

## Conventions

- Timestamps: ISO 8601 **with timezone**, always UTC with microseconds, e.g. `"2026-11-08T03:30:12.000000Z"`. Parse with `new Date(...)`; don't compare as strings across formats.
- Unknown/unavailable values are `null`. The backend never invents defaults (no fake reporter, no fake time).
- `first_detected_at` is when our scan **first detected** the change, not when the change happened. Show it as "detected 03:30".
- `reporter` and `reason` are **self-reported**. Show "reported by X", never "verified".
- IDs are opaque strings (`rec_…`, `run_…`).
- `environment`: live records use `demo`. Hand-written demo data uses `demo-authored` and sanitized replays use `demo-replay`, so fixture data never mixes with live records. **Show `environment` and `evidence_source` when they aren't `demo` / `terraform-refresh-only`.**
- User text (`reason`, `reporter`, `note`) is plain text. Render it as text, never as HTML.

## Enums

| Name | Values |
|---|---|
| `Intent` | `unset` · `keep` · `revert` · `unsure` · `defer` |
| `Resolution` | `open` · `resolved` |
| `ResolutionReason` | `verified_aligned` · `superseded` · or `null` while open |
| `CheckStatus` | `current` · `stale` · `failed` · `unsupported` |
| `ChangeKind` | `added` (rule exists live, not in Terraform) · `removed` (rule in Terraform, gone live) · `modified` (same protocol+sources, port changed) |
| `AckOutcome` | `pending` · `no_changes` · `cancelled` · `kept` · `deferred` · `applied_no_warnings` · `reverted_applied` · `override_applied` · `unverified_bypass_applied` · `aborted_plan_changed` · `failed` |

Meaning of `last_check_status`: `current` = seen in the most recent successful scan; `stale` = not re-checked since an older scan; `failed` = the most recent check errored (treat as unknown, **not** as fine); `unsupported` = evidence could not be interpreted (unknown/sensitive values).

## Objects

### Rule
```json
{
  "protocol": "tcp",
  "port_range": "8443",
  "source_addresses": ["0.0.0.0/0", "::/0"],
  "source_tags": [],
  "source_droplet_ids": [],
  "source_load_balancer_uids": [],
  "source_kubernetes_ids": []
}
```
`protocol` and `port_range` may be `null` if unknown. Arrays are sorted and never `null`.

### Record
```json
{
  "id": "rec_7f3a9c2e1b",
  "environment": "demo",
  "resource_address": "digitalocean_firewall.web",
  "resource_type": "digitalocean_firewall",
  "attribute": "inbound_rule",
  "change_kind": "modified",
  "baseline_value": { "protocol": "tcp", "port_range": "8080", "source_addresses": ["0.0.0.0/0", "::/0"], "source_tags": [], "source_droplet_ids": [], "source_load_balancer_uids": [], "source_kubernetes_ids": [] },
  "observed_value": { "protocol": "tcp", "port_range": "8443", "source_addresses": ["0.0.0.0/0", "::/0"], "source_tags": [], "source_droplet_ids": [], "source_load_balancer_uids": [], "source_kubernetes_ids": [] },
  "summary": "inbound tcp port 8080 from 0.0.0.0/0, ::/0 changed live to port 8443",
  "first_detected_at": "2026-11-08T03:30:12.000000Z",
  "last_detected_at": "2026-11-08T03:45:02.000000Z",
  "reporter": "Paul",
  "reason": "payment webhook blocked, opened 8443",
  "reported_at": "2026-11-08T03:31:40.000000Z",
  "intent": "keep",
  "intent_note": null,
  "intent_updated_at": "2026-11-08T03:31:40.000000Z",
  "resolution": "open",
  "resolution_reason": null,
  "resolved_at": null,
  "superseded_by": null,
  "last_check_status": "current",
  "last_check_at": "2026-11-08T03:45:02.000000Z",
  "evidence_source": "terraform-refresh-only"
}
```
Nullable: `baseline_value` (null when `added`), `observed_value` (null when `removed`), `reporter`, `reason`, `reported_at`, `intent_note`, `intent_updated_at`, `resolution_reason`, `resolved_at`, `superseded_by`, `last_check_at`.
`evidence_source`: `terraform-refresh-only` (real scan) · `authored-fixture` (hand-written demo data) · `real-fixture` (sanitized capture replayed).

A record with `reason: null` is an **unexplained manual change**. Still show it and still warn.

### ApplyRun
```json
{
  "id": "run_41c0d8aa2f",
  "environment": "demo",
  "generated_at": "2026-11-08T09:12:00.000000Z",
  "plan_fingerprint": "sha256:5be1…",
  "proposed_changes": [
    { "resource_address": "digitalocean_firewall.web", "resource_type": "digitalocean_firewall", "actions": ["update"], "summary": "update inbound_rule: -tcp 8443, +tcp 8080" }
  ],
  "warnings": [
    {
      "record_id": "rec_7f3a9c2e1b",
      "resource_address": "digitalocean_firewall.web",
      "message": "This apply will remove the live rule 'inbound tcp port 8443 from 0.0.0.0/0, ::/0' and restore port 8080. Paul reported (self-reported; detected 2026-11-08 03:30 UTC): \"payment webhook blocked, opened 8443\".",
      "reason": "payment webhook blocked, opened 8443",
      "reporter": "Paul",
      "intent": "keep",
      "first_detected_at": "2026-11-08T03:30:12.000000Z"
    }
  ],
  "check_status": "current",
  "coverage_note": "Checked digitalocean_firewall inbound rules only. Other attributes, other resource types and OS-level changes are not covered.",
  "ack_outcome": "kept",
  "ack_note": null,
  "completed_at": "2026-11-08T09:12:40.000000Z"
}
```
Nullable: `plan_fingerprint` (null if planning failed), `ack_note`, `completed_at` (null while `pending`).
`check_status: "failed"` means **verification was unavailable**. The UI must not show that as "no conflicts".

## Endpoints

### `GET /api/health`
`200`:
```json
{ "status": "ok", "version": "0.1.0", "db": "ok", "environment": "demo", "terraform_dir_configured": true, "time": "2026-11-08T03:30:00.000000Z" }
```
If the DB cannot be opened: `503` with the **same body shape** (not the error envelope), `status: "degraded"`, `db: "error"`.

### `GET /api/records?resolution=open`
Query: `resolution` optional, `open` | `resolved`. Omit for all. Sorted newest `first_detected_at` first.
`200`: `{ "records": [Record, …] }` (empty list is `{ "records": [] }`).
`422` if `resolution` is not a valid value.

### `GET /api/records/{id}`
`200`: `Record`. `404` if unknown.

### `POST /api/records/{id}/report`
Body (unknown fields rejected):
```json
{ "reporter": "Paul", "reason": "payment webhook blocked, opened 8443", "intent": "keep" }
```
- `reason`: required, 1–500 chars, not whitespace-only (whitespace-only → 422).
- `reason`/`reporter`: control or formatting characters (ESC, CR, bidi overrides…) → 422.
- `reporter`: optional, ≤100 chars, `null` allowed.
- `intent`: optional `Intent`. If omitted, intent is unchanged.

`200`: updated `Record`. `404` unknown id. `409` if the record is `resolved`. `422` validation.
Reporting again overwrites the previous reason. Last report wins, and `reported_at` updates.

### `POST /api/records/{id}/decision`
Body:
```json
{ "intent": "revert", "note": "8443 no longer needed after hotfix" }
```
`200`: updated `Record`. `404` / `409` (resolved) / `422`.
A decision **does not resolve** the record and **does not apply anything**. Warnings keep firing until a verified re-check shows the live value and Terraform agree.

### `GET /api/apply-runs/{id}`
`200`: `ApplyRun`. `404` if unknown.

### `GET /api/apply-runs?limit=20`
`200`: `{ "apply_runs": [ApplyRun, …] }`, newest first. `limit` 1–100, default 20.

### Errors
All errors use this envelope:
```json
{ "error": { "code": "not_found", "message": "record rec_123 not found" } }
```
| HTTP | code |
|---|---|
| 404 | `not_found` |
| 405 | `method_not_allowed` |
| 409 | `conflict` |
| 422 | `validation_error` (message summarizes the failing fields) |
| 500 | `internal` (no internal details are returned) |

## Deliberately not in the HTTP API

Scan, apply, re-check and any Terraform execution are **CLI-only** (`breakglass scan|apply|recheck`). The HTTP API never runs Terraform and never accepts commands or paths. The browser is a read-and-annotate surface. Applying stays a human decision in the terminal.
