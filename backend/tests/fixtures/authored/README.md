# Authored fixtures

Every JSON file here is **hand-written**, not captured from real Terraform.
Each one carries `"_fixture_note": "AUTHORED — not captured from real Terraform; shape is a hypothesis"`;
the parsers ignore unknown top-level keys.

They follow Terraform's documented plan JSON format (`format_version`,
`resource_drift[]`, `resource_changes[]` with `address`, `mode`, `type`, `name`,
`provider_name`, `change{actions, before, after, after_unknown, before_sensitive, after_sensitive}`).
IPs are RFC 5737 / documentation ranges; IDs are fake.

## Direction hypothesis (unverified)

- **Refresh-only plan, `resource_drift[]`:** `before` = Terraform state (baseline),
  `after` = refreshed live value (observed). In `refresh_drift_8443.json` the
  baseline is tcp 8080 and the observed value is tcp 8443.
- **Normal plan, `resource_changes[]`:** `before` = current refreshed object,
  `after` = desired value from config. In `plan_reverts_8443.json` before has
  8443 and after has 8080, i.e. apply would revert the console change.

Once a sanitized real capture exists, compare it with these files. If the
direction or shape differs, fix `breakglass/detector.py` / `breakglass/matcher.py`
and these fixtures together.

| File | Scenario |
|---|---|
| refresh_drift_8443.json | 8080 -> 8443 drift; ssh 22 from 203.0.113.10/32 unchanged; nested all-false sensitivity masks |
| refresh_drift_reordered.json | Same drift, rules and source_addresses in a different order |
| refresh_no_drift.json | No drift |
| refresh_unknown.json | inbound_rule unknown (after_unknown) on one firewall, sensitive (nested true) on another |
| refresh_unrelated_attr.json | Drift only in name and tags |
| refresh_malformed.json | Entries with bad address / non-object / bad change |
| plan_reverts_8443.json | Normal plan updates 8443 back to 8080 |
| plan_unrelated_same_resource.json | Firewall update renames it; 8443 stays |
| plan_no_changes.json | All no-op |
| plan_other_resource.json | Only a droplet resize |
| plan_replace_firewall.json | Firewall replaced (`["delete","create"]`); new object has 8080 |
| plan_after_unknown.json | inbound_rule unknown after apply |

Regenerating: these were produced once by a throwaway script and are now
maintained by hand. Edit them directly.

## Update after first real plan (2026-11-07)

Real `terraform plan` output (provider v2.107) includes `"action": "allow"` on every firewall rule. All authored fixtures were updated to carry it, and `action` is part of rule identity. The before/after direction is still unverified until a real refresh-only capture lands in `../real/`.
