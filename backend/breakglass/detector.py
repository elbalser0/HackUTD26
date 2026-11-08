"""Detect manual digitalocean_firewall inbound_rule changes from the JSON of a
Terraform refresh-only plan (`terraform show -json <planfile>`).

DIRECTION HYPOTHESIS (unverified until a real captured fixture confirms it):
for each `resource_drift[]` entry,
  - change.before = the object as recorded in Terraform STATE  -> baseline
  - change.after  = the object as REFRESHED from the live API  -> observed
So "8080 in before, 8443 in after" means someone changed 8080 -> 8443 by hand.
The authored fixtures in tests/fixtures/authored/ encode this same hypothesis;
if a real capture shows the opposite, flip it here and in the fixtures.

Honesty rules:
  - Unknown or sensitive inbound_rule values are never interpreted; they
    produce a note in DetectionResult.unsupported.
  - Drift in other attributes / resource types produces a note, never an
    Observation.
  - Malformed input produces DetectionResult.errors (verification failed).

Pure: no I/O. Plan JSON is untrusted; nothing here raises on odd shapes.
"""

from __future__ import annotations

import json
from typing import Any

from .models import DetectionResult, Observation
from .rules import diff_rules, rule_set

FIREWALL_TYPE = "digitalocean_firewall"
ATTRIBUTE = "inbound_rule"

# Computed attributes whose churn on refresh is not a manual change signal.
_IGNORED_ATTRS = frozenset({ATTRIBUTE, "pending_changes", "status"})


def any_true(mask: Any) -> bool:
    """True if a Terraform unknown/sensitive mask contains any `true` leaf."""
    if mask is True:
        return True
    if isinstance(mask, dict):
        return any(any_true(v) for v in mask.values())
    if isinstance(mask, list):
        return any(any_true(v) for v in mask)
    return False


def attr_marked(mask: Any, attr: str) -> bool:
    """Whether `attr` is (wholly or partly) marked in an unknown/sensitive mask.
    A bare `true` mask marks the whole object, including `attr`."""
    if mask is True:
        return True
    if isinstance(mask, dict):
        return any_true(mask.get(attr))
    return False


def _canon(value: Any) -> Any:
    """Order-insensitive canonical form for comparing non-rule attributes
    (the provider models droplet_ids, tags, outbound_rule as sets)."""
    if isinstance(value, list):
        return sorted(json.dumps(_canon(v), sort_keys=True) for v in value)
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    return value


def _empty_is_none(value: Any) -> Any:
    """null, [] and {} compare equal. The provider reports an unset collection as null in older state and as an
    empty collection live (seen for a firewall's droplet_ids and tags in the 2026-11-07 spike); Terraform treats
    them the same, so this is normalization, not drift. Deliberately narrow: only empty collections. A string,
    number or boolean never equals null, and [] never equals a non-empty list (a detach is still drift)."""
    return None if value is None or value == [] or value == {} else value


def changed_attrs(before: dict, after: dict, ignore: frozenset[str] = _IGNORED_ATTRS) -> list[str]:
    keys = (set(before) | set(after)) - ignore
    return sorted(
        k for k in keys
        if _empty_is_none(_canon(before.get(k))) != _empty_is_none(_canon(after.get(k)))
    )


def _valid_actions(actions: Any) -> bool:
    return isinstance(actions, list) and all(isinstance(a, str) for a in actions)


def detect(plan: dict) -> DetectionResult:
    result = DetectionResult()
    if not isinstance(plan, dict):
        result.errors.append("plan JSON is not an object")
        return result
    drift = plan.get("resource_drift", [])
    if drift is None:
        drift = []
    if not isinstance(drift, list):
        result.errors.append("resource_drift is not a list")
        return result

    for i, entry in enumerate(drift):
        if not isinstance(entry, dict):
            result.errors.append(f"resource_drift[{i}] is not an object")
            continue
        address = entry.get("address")
        change = entry.get("change")
        if not isinstance(address, str) or not address:
            result.errors.append(f"resource_drift[{i}] has no address")
            continue
        if not isinstance(change, dict):
            result.errors.append(f"{address}: drift entry has no change object")
            continue
        rtype = entry.get("type")
        if not isinstance(rtype, str):
            result.errors.append(f"{address}: drift entry has no resource type")
            continue
        actions = change.get("actions")
        if not _valid_actions(actions):
            result.errors.append(f"{address}: change.actions is missing or malformed")
            continue

        if rtype != FIREWALL_TYPE:
            result.unsupported.append(f"{address}: drift in resource type {rtype} not supported")
            continue
        mode = entry.get("mode", "managed")
        if mode != "managed":
            result.unsupported.append(f"{address}: drift in {mode} resource not supported")
            continue

        before = change.get("before")
        after = change.get("after")
        if "delete" in actions or after is None:
            result.unsupported.append(
                f"{address}: resource appears deleted outside Terraform; not supported"
            )
            continue
        if before is None or "create" in actions:
            result.unsupported.append(f"{address}: resource has no prior state; not supported")
            continue
        if not isinstance(before, dict) or not isinstance(after, dict):
            result.errors.append(f"{address}: change.before/after is not an object")
            continue

        for attr in changed_attrs(before, after):
            result.unsupported.append(f"{address}: drift in {attr} not supported")

        if (
            attr_marked(change.get("after_unknown"), ATTRIBUTE)
            or attr_marked(change.get("before_sensitive"), ATTRIBUTE)
            or attr_marked(change.get("after_sensitive"), ATTRIBUTE)
        ):
            result.unsupported.append(
                f"{address}: {ATTRIBUTE} is unknown or sensitive; cannot compare"
            )
            continue

        has_b, has_a = ATTRIBUTE in before, ATTRIBUTE in after
        if not has_b and not has_a:
            continue
        base_set, ok_b = rule_set(before.get(ATTRIBUTE))
        live_set, ok_a = rule_set(after.get(ATTRIBUTE))
        if not (has_b and has_a and ok_b and ok_a):
            result.unsupported.append(
                f"{address}: {ATTRIBUTE} could not be interpreted; cannot compare"
            )
            continue

        for kind, baseline, observed in diff_rules(base_set, live_set):
            result.observations.append(
                Observation(
                    resource_address=address,
                    resource_type=rtype,
                    attribute=ATTRIBUTE,
                    kind=kind,
                    baseline=baseline,
                    observed=observed,
                )
            )

    result.observations.sort(key=lambda o: o.resource_address)  # stable: keeps diff order
    return result


def is_refresh_only_plan(plan: Any) -> bool:
    """Heuristic only: True if the plan proposes no resource changes (every
    resource_changes entry is no-op/read). Terraform's JSON may not expose the
    plan mode directly, so do not rely on this for safety decisions."""
    if not isinstance(plan, dict):
        return False
    changes = plan.get("resource_changes") or []
    if not isinstance(changes, list):
        return False
    for entry in changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("change"), dict):
            return False
        actions = entry["change"].get("actions")
        if not _valid_actions(actions):
            return False
        if any(a not in ("no-op", "read") for a in actions):
            return False
    return True
