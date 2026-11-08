# Real Terraform captures (sanitized)

These are `terraform show -json` outputs from a **real** run against DigitalOcean (Terraform 1.17.1, provider `~> 2.0`,
captured 2026-11-07) of `break-glass-infra/` (firewall `break-glass-demo`). They are labelled `real-fixture` and replay in
environment `<env>-replay`, so they can never merge with or resolve live records.

Sanitized by replacement only. Keys and structure are unchanged; nothing else was edited to fit the code.

| Replaced | With |
|---|---|
| firewall id | `00000000-0000-4000-8000-000000000001` |
| the operator's public IPv4 | `203.0.113.10` (TEST-NET-3, documentation range) |
| the demo droplet id | `111111111` |

| File | What it is |
|---|---|
| `refresh_noise_only.json` | `plan -refresh-only` with the firewall exactly as Terraform expects, apart from provider noise: `droplet_ids` and `tags` go from `null` (stored state) to `[]` (live). No rule drift. |
| `refresh_added_8443.json` | `plan -refresh-only` after tcp/8443 from `0.0.0.0/0, ::/0` was added in the console. The 8443 `inbound_rule` is in `after`, not `before`. |
| `plan_reverts_8443.json` | normal `plan` in that state: an in-place `update` that would remove the 8443 rule (`before` has 22 and 8443, `after` has 22). |
| `plan_no_changes.json` | normal `plan` after the rule was deleted again: no resource changes. |

Facts these captures established (see `test_real_replay.py`): in a refresh-only plan `change.before` is the prior state and
`change.after` is the live value; `resource_changes` is absent from a refresh-only plan; every rule carries `action = "allow"`.
