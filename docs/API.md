# Argus API — v0.1 contract

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
- **Auth:** optional Firebase (Google) sign-in; see [Sign-in](#sign-in-firebase). Without it, engineer endpoints are open. Local demo only: bind to localhost and do not expose publicly.
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
| `EventKind` | `report` · `decision` · `review` · `run_started` · `run_finished` |
| `AckOutcome` | `pending` · `running` (decision saved, apply started) · `unknown` (no completion recorded; interrupted or crashed) · `no_changes` · `cancelled` · `kept` · `deferred` · `applied_no_warnings` · `reverted_applied` · `override_applied` · `unverified_bypass_applied` · `aborted_plan_changed` · `failed` |

Meaning of `last_check_status`: `current` = seen in the most recent successful scan; `stale` = not re-checked since an older scan; `failed` = the most recent check errored (treat as unknown, **not** as fine); `unsupported` = evidence could not be interpreted (unknown/sensitive values).

## Objects

### Rule
```json
{
  "action": "allow",
  "protocol": "tcp",
  "port_range": "8443",
  "source_addresses": ["0.0.0.0/0", "::/0"],
  "source_tags": [],
  "source_droplet_ids": [],
  "source_load_balancer_uids": [],
  "source_kubernetes_ids": []
}
```
`action` (`"allow"` / `"deny"`; added after real provider output showed it; a missing value is reported as `"allow"`), `protocol` and `port_range` may be `null` if unknown. Arrays are sorted and never `null`. A deny rule's summary reads "inbound DENY tcp …".

### Record
The example below is a `modified` rule. **In the live demo the console edit *adds* a rule** (`change_kind: "added"`, `baseline_value: null`, summary `"added live: inbound tcp port 8443 from 0.0.0.0/0, ::/0"`, resource `digitalocean_firewall.demo`).
```json
{
  "id": "rec_7f3a9c2e1b",
  "environment": "demo",
  "resource_address": "digitalocean_firewall.demo",
  "resource_type": "digitalocean_firewall",
  "attribute": "inbound_rule",
  "change_kind": "modified",
  "baseline_value": { "action": "allow", "protocol": "tcp", "port_range": "8080", "source_addresses": ["0.0.0.0/0", "::/0"], "source_tags": [], "source_droplet_ids": [], "source_load_balancer_uids": [], "source_kubernetes_ids": [] },
  "observed_value": { "action": "allow", "protocol": "tcp", "port_range": "8443", "source_addresses": ["0.0.0.0/0", "::/0"], "source_tags": [], "source_droplet_ids": [], "source_load_balancer_uids": [], "source_kubernetes_ids": [] },
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
    { "resource_address": "digitalocean_firewall.demo", "resource_type": "digitalocean_firewall", "actions": ["update"], "summary": "update inbound_rule: -tcp 8443, +tcp 8080" }
  ],
  "warnings": [
    {
      "record_id": "rec_7f3a9c2e1b",
      "resource_address": "digitalocean_firewall.demo",
      "message": "This apply will remove the live rule 'inbound tcp port 8443 from 0.0.0.0/0, ::/0' and restore port 8080. Paul reported (self-reported; detected 2026-11-08 03:30 UTC): \"payment webhook blocked, opened 8443\".",
      "reason": "payment webhook blocked, opened 8443",
      "reporter": "Paul",
      "intent": "keep",
      "first_detected_at": "2026-11-08T03:30:12.000000Z"
    }
  ],
  "check_status": "current",
  "coverage_note": "Checked digitalocean_firewall inbound rules only. Other attributes, other resource types and OS-level changes are not covered.",
  "ack_outcome": "reverted_applied",
  "ack_note": null,
  "completed_at": "2026-11-08T09:12:40.000000Z",
  "started_at": "2026-11-08T09:12:31.000000Z",
  "reviewer": "Dana",
  "reviewer_assurance": "self-reported",
  "rationale": "webhook fixed upstream; 8443 no longer needed"
}
```
Nullable: `plan_fingerprint` (null if planning failed), `ack_note`, `completed_at` (null while `pending` or `running`, and for `unknown`), `started_at` (null unless Terraform was started), `reviewer`, `reviewer_assurance`, `rationale`.
`reviewer` and `reviewer_assurance` are set on every wrapper run. `reviewer_assurance` is `"self-reported"` (typed with `--reviewer`) or `"local-os-user (not verified)"` (the operator's OS account). Neither is verified identity. `started_at` and `rationale` are set only when Terraform was started.
Show `unknown` as **outcome unknown / interrupted**, never as success.
`check_status: "failed"` means **verification was unavailable**. The UI must not show that as "no conflicts".

## Endpoints

### `GET /api/health`
`200`:
```json
{ "status": "ok", "version": "0.1.0", "db": "ok", "environment": "demo", "terraform_dir_configured": true, "time": "2026-11-08T03:30:00.000000Z",
  "last_scan_at": "2026-11-08T03:29:41.512000Z", "last_scan_status": "ok" }
```
`last_scan_at` / `last_scan_status` (`"ok"` | `"failed"`) describe the most recent scan of this environment. Both are `null` if it was never scanned, so the UI can show scan age even with an empty record list.
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
Reporting again updates the record's displayed `reason`/`reporter` (latest wins), but **every report is kept** as an event (`GET /api/records/{id}/events`). Nothing is erased.

### `POST /api/records/{id}/decision`
Body:
```json
{ "intent": "revert", "note": "8443 no longer needed after hotfix" }
```
`200`: updated `Record`. `404` / `409` (resolved) / `422`.
A decision **does not resolve** the record and **does not apply anything**. Warnings keep firing until a verified re-check shows the live value and Terraform agree.

### `GET /api/records/{id}/events`
Append-only history for one record, oldest first: `report`, `decision` (web/CLI intent), and `review` (wrapper decision on a specific plan).
`200`: `{ "events": [Event, …] }`. `404` if unknown.

### `GET /api/apply-runs/{id}/events`
Events for one wrapper run: `review` (one per affected record), `run_started`, `run_finished`. `200` / `404`.

### Event
```json
{
  "id": "evt_3b1f09c2aa",
  "environment": "demo",
  "record_id": "rec_7f3a9c2e1b",
  "run_id": "run_41c0d8aa2f",
  "kind": "review",
  "actor": "Dana",
  "actor_assurance": "self-reported",
  "data": { "decision": "revert", "plan_fingerprint": "sha256:5be1…", "rationale": "webhook fixed upstream", "source": "wrapper" },
  "created_at": "2026-11-08T09:12:31.000000Z"
}
```
`record_id` is null for run-level events, and `run_id` is null for web/CLI reports and decisions. The fields in `data` depend on `kind`:
- `report`: `reason`, `intent`, `source`.
- `decision`: `intent`, `note`, `source`.
- `review`: `decision` (`keep` · `defer` · `cancel` · `revert` · `revert-not-confirmed` · `override` · `unverified-bypass`), `plan_fingerprint`, `rationale`, `source`. There is one per affected record. A run with no affected records has no review events.
- `run_started`: `decision` (any of the above, or `state-sync` / `apply` for runs with no affected records), `plan_fingerprint`, `record_ids`.
- `run_finished`: `outcome`, `applied` (`null` when the outcome is `unknown`), `note`.

`actor_assurance` is `"self-reported"`, `"local-os-user (not verified)"`, or `"system"` (the backend itself, e.g. marking an unfinished run `unknown`).

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

## Sign-in (Firebase)

Enabled when the server sets `BG_FIREBASE_PROJECT_ID` (a public identifier, not a secret). The browser signs in with the Firebase JS SDK (Google provider) and sends the Firebase **ID token** on writes as `Authorization: Bearer <id token>`. Never put it in a URL.

| Endpoint | Firebase not configured | Firebase configured |
|---|---|---|
| `GET` records, apply runs, events, health | open | open (localhost only) |
| `POST /api/records/{id}/report`, `/decision` | open (actor self-reported) | **sign-in required**: `401` without or with an invalid/expired token, `403` if the email is unverified |
| `/api/admin/*` | shared `BG_ADMIN_TOKEN` | shared token **or** a Firebase sign-in whose verified email is in `BG_ADMIN_EMAILS`. A signed-in non-admin gets `403` |

- **Signed-in writes:** the event's `actor` is the account email, and `actor_assurance` is `"google-account (verified sign-in)"`.
  - A typed `reporter` is kept as the self-reported display name, saved as `data.reporter_name`. Without one, the account's display name is used.
- **What it proves:** who submitted the explanation, **not** who made the console change.
- **Health:** `GET /api/health` includes `auth: {firebase_project_id, writes_require_sign_in, admin_via_firebase, admin_via_shared_token}`. No secrets are included.
- **Tokens:** the server verifies the token's signature, expiry, audience (the project id) and issuer with Google's public keys. Token values are never echoed in errors.
- **Error codes** (`error.code`), so the UI can explain each case:

| Status | Code | Meaning |
|---|---|---|
| 401 | `sign_in_required` | Write sent with no Bearer token while sign-in is required |
| 401 | `sign_in_invalid` | Bad, expired or forged ID token |
| 401 | `unauthorized` | Admin call with missing or wrong credentials |
| 403 | `email_unverified` | Valid sign-in, but the Google account's email isn't verified |
| 403 | `not_admin` | Valid sign-in, but the email isn't in `BG_ADMIN_EMAILS` |
| 403 | `admin_not_configured` | No shared token and no Firebase admins are configured |

## Admin log (R9)

Read-only views for an authorized operations lead. They are derived from the append-only `events`, plus `records` (detection and resolution times) and `apply_runs` (to surface runs that never recorded a completion, and runs from before the events table existed). Nothing is invented.

**Authorization (server-side).** Send `Authorization: Bearer <credential>`, where the credential is either a Firebase ID token from an admin email (`BG_ADMIN_EMAILS`, case-insensitive, verified email required) or the shared `BG_ADMIN_TOKEN`, kept as an offline fallback. A credential in the URL is never accepted.
- Neither configured: `403 forbidden` (fails closed). A Firebase project with an empty admin list grants admin to no one.
- Missing or invalid credentials: `401 unauthorized` with `WWW-Authenticate: Bearer`.
- A valid sign-in that isn't an admin, or has an unverified email: `403 forbidden`.
- The shared token shows that *an* admin read the log, not which admin. The older `/api/records` and `/api/apply-runs` reads stay open.

### AdminEvent
```json
{ "at": "2026-11-08T03:35:12Z", "type": "review", "environment": "demo",
  "record_ids": ["rec_..."], "run_id": "run_...", "resource_addresses": ["digitalocean_firewall.demo"],
  "actor": "Dana", "actor_assurance": "self-reported", "outcome": null,
  "plan_fingerprint": "sha256:...", "detail": "decision: revert — webhook fixed upstream" }
```
`type`: `change_detected` · `explained` · `decision` · `review` · `run_started` · `run_finished` · `run_unfinished` · `resolved`. `actor_assurance` is `self-reported`, `local-os-user (not verified)`, `system`, or `google-account (verified sign-in)` for web actions made while signed in. The last one verifies who submitted an action, never who made the console change. `outcome` is set on `run_finished` and `run_unfinished` only. `run_unfinished` is derived for a run that has no recorded completion, and its outcome is **`unknown`**, never success. `plan_fingerprint` on `review` and `run_started` is the exact plan that was reviewed and then executed.

### `GET /api/admin/log`
Newest first. Filters (all optional, AND): `engineer` (case-insensitive exact match on the event actor), `resource` (exact address), `since` / `until` (ISO 8601 **with timezone**, inclusive), `outcome` (a terminal run outcome or `unknown`; selects run results only), `limit` (1-500, default 100). Returns `{events, total_matching, limitations}`. Invalid filters are `422`.

### `GET /api/admin/records/{id}/timeline`
Oldest first: change, every explanation, every decision and review, each wrapper run that touched the record (start, and finish or unfinished), and resolution. Also returns `gaps` (`no_reason_recorded`, `no_decision_recorded`, `no_run_linked`, `run_outcome_unknown` with `run_id`) so missing evidence is visible. `404` for an unknown record.

### Limitations (also returned in every response)
- Actors are not verified identities. A reporter is self-reported; a wrapper reviewer is self-reported or the local OS user.
- One shared admin token; no per-admin identity or audit of admin reads.
- `unknown` is not `failed`: the run may have been interrupted, crashed, or still be running.
- Records and runs from before the events table existed show only their stored values, labelled "predates event history".

## Deliberately not in the HTTP API

Scan, apply, re-check and any Terraform execution are **CLI-only** (`breakglass scan|apply|recheck`). The HTTP API never runs Terraform and never accepts commands or paths. The browser is a read-and-annotate surface. Applying stays a human decision in the terminal.
