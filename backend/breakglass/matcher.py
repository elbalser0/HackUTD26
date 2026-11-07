"""Decide whether a NORMAL Terraform plan (`terraform show -json <planfile>`)
would reverse open emergency-change records.

DIRECTION HYPOTHESIS (unverified until a real captured fixture confirms it):
for each `resource_changes[]` entry of a normal plan,
  - change.before = the current (refreshed) object -> what is live now
  - change.after  = the desired object from config -> what apply would leave
So a record is reversed when its emergency value is live (in before) and
apply would remove it (absent from after), or, for REMOVED records, when the
rule someone removed is absent now and apply would re-add it.

Address equality alone never counts as a reversal: the plan must provably
remove (or re-add) the specific rule. When that cannot be determined
(unknown/sensitive values, unparsable rules, odd actions) the record goes to
unknown_ids. A malformed plan yields errors and no claims at all.

Pure: no I/O.
"""

from __future__ import annotations

from typing import Any

from .detector import FIREWALL_TYPE, attr_marked, changed_attrs
from .models import ChangeKind, FirewallRule, MatchCandidate, MatchResult, ProposedChange
from .rules import rule_set, rule_sort_key, short_rule

ATTRIBUTE = "inbound_rule"

_REVERSED = "reversed"
_UNKNOWN = "unknown"
_NO = "no"


def _valid_actions(actions: Any) -> bool:
    return isinstance(actions, list) and bool(actions) and all(isinstance(a, str) for a in actions)


def _parse_changes(plan: Any) -> tuple[list[dict], list[str]]:
    """Validate resource_changes[]; returns (entries, errors)."""
    if not isinstance(plan, dict):
        return [], ["plan JSON is not an object"]
    changes = plan.get("resource_changes", [])
    if changes is None:
        changes = []
    if not isinstance(changes, list):
        return [], ["resource_changes is not a list"]
    entries: list[dict] = []
    errors: list[str] = []
    for i, entry in enumerate(changes):
        if not isinstance(entry, dict):
            errors.append(f"resource_changes[{i}] is not an object")
            continue
        address = entry.get("address")
        change = entry.get("change")
        if not isinstance(address, str) or not address:
            errors.append(f"resource_changes[{i}] has no address")
            continue
        if not isinstance(change, dict):
            errors.append(f"{address}: entry has no change object")
            continue
        if not _valid_actions(change.get("actions")):
            errors.append(f"{address}: change.actions is missing or malformed")
            continue
        if not isinstance(entry.get("type"), str):
            errors.append(f"{address}: entry has no resource type")
            continue
        entries.append(entry)
    return entries, errors


def _is_noop(actions: list[str]) -> bool:
    return all(a in ("no-op", "read") for a in actions)


def _verb(actions: list[str]) -> str:
    s = set(actions)
    if "delete" in s and "create" in s:
        return "replace"
    for v in ("update", "create", "delete"):
        if v in s:
            return v
    return "/".join(actions)


def _rules_marked(change: dict) -> bool:
    return (
        attr_marked(change.get("after_unknown"), ATTRIBUTE)
        or attr_marked(change.get("before_sensitive"), ATTRIBUTE)
        or attr_marked(change.get("after_sensitive"), ATTRIBUTE)
    )


def _side_rules(obj: Any) -> tuple[frozenset[FirewallRule], bool]:
    if not isinstance(obj, dict):
        return frozenset(), False
    return rule_set(obj.get(ATTRIBUTE))


def _summarize(entry: dict) -> ProposedChange:
    change = entry["change"]
    actions = change["actions"]
    verb = _verb(actions)
    summary = verb
    if entry["type"] == FIREWALL_TYPE and verb in ("update", "replace"):
        before, after = change.get("before"), change.get("after")
        parts: list[str] = []
        if _rules_marked(change):
            parts.append(f"{ATTRIBUTE} (values unknown or sensitive)")
        else:
            b, ok_b = _side_rules(before)
            a, ok_a = _side_rules(after)
            if ok_b and ok_a:
                removed = sorted(b - a, key=rule_sort_key)
                added = sorted(a - b, key=rule_sort_key)
                if removed or added:
                    items = [f"-{short_rule(r)}" for r in removed] + [f"+{short_rule(r)}" for r in added]
                    parts.append(f"{ATTRIBUTE}: " + ", ".join(items))
            elif isinstance(before, dict) and isinstance(after, dict):
                parts.append(f"{ATTRIBUTE} (could not interpret)")
        if isinstance(before, dict) and isinstance(after, dict):
            unknown = change.get("after_unknown")
            unknown = unknown if isinstance(unknown, dict) else {}
            ignore = frozenset({ATTRIBUTE, "pending_changes", "status"} | {k for k, v in unknown.items() if v})
            parts.extend(changed_attrs(before, after, ignore))
        if parts:
            summary = f"{verb} " + "; ".join(parts)
    return ProposedChange(
        resource_address=entry["address"],
        resource_type=entry["type"],
        actions=tuple(actions),
        summary=summary,
    )


def summarize_changes(plan: dict) -> list[ProposedChange]:
    """Summaries of non-no-op resource_changes, in plan order. Malformed
    entries are skipped here; match() reports them as errors."""
    entries, _ = _parse_changes(plan)
    return [_summarize(e) for e in entries if not _is_noop(e["change"]["actions"])]


def _evaluate(entry: dict, cand: MatchCandidate) -> str:
    change = entry["change"]
    actions: list[str] = change["actions"]
    if _is_noop(actions):
        return _NO

    # The rule that must disappear (ADDED/MODIFIED) or reappear (REMOVED).
    if cand.kind in (ChangeKind.ADDED, ChangeKind.MODIFIED):
        target = cand.observed
    elif cand.kind == ChangeKind.REMOVED:
        target = cand.baseline
    else:
        return _UNKNOWN
    if target is None:
        return _UNKNOWN

    if entry.get("type") != FIREWALL_TYPE:
        return _UNKNOWN  # record says firewall but plan disagrees: don't guess
    if _rules_marked(change):
        return _UNKNOWN

    is_delete = "delete" in actions
    is_create = "create" in actions
    is_update = "update" in actions

    if is_delete:
        # Delete or replace: the current object (and every rule on it) goes away.
        before, ok_b = _side_rules(change.get("before"))
        if not ok_b:
            return _UNKNOWN
        if is_create:
            # Replace: the new object is built from config (after).
            after, ok_a = _side_rules(change.get("after"))
            if not ok_a:
                return _UNKNOWN
        else:
            after = frozenset()  # pure delete leaves nothing
        if cand.kind == ChangeKind.REMOVED:
            return _REVERSED if (target not in before and target in after) else _NO
        # Emergency rule is live and will not exist afterwards. (A replace that
        # keeps it in `after` still drops it briefly; we don't call that a
        # reversal of the record.)
        return _REVERSED if (target in before and target not in after) else _NO

    if is_update and not is_create:
        before, ok_b = _side_rules(change.get("before"))
        after, ok_a = _side_rules(change.get("after"))
        if not (ok_b and ok_a):
            return _UNKNOWN
        if cand.kind == ChangeKind.REMOVED:
            return _REVERSED if (target not in before and target in after) else _NO
        return _REVERSED if (target in before and target not in after) else _NO

    # create-only (object missing live) or unrecognized actions.
    return _UNKNOWN


def match(plan: dict, candidates: list[MatchCandidate]) -> MatchResult:
    result = MatchResult()
    entries, errors = _parse_changes(plan)
    if errors:
        result.errors = errors
        return result

    by_address: dict[str, list[dict]] = {}
    for e in entries:
        by_address.setdefault(e["address"], []).append(e)

    for cand in candidates:
        if not isinstance(cand, MatchCandidate):
            result.errors.append("invalid match candidate")
            continue
        # Several entries can share an address (e.g. deposed objects).
        verdicts = {_evaluate(e, cand) for e in by_address.get(cand.resource_address, [])}
        if _REVERSED in verdicts:
            if cand.record_id not in result.reversed_ids:
                result.reversed_ids.append(cand.record_id)
        elif _UNKNOWN in verdicts:
            if cand.record_id not in result.unknown_ids:
                result.unknown_ids.append(cand.record_id)

    if result.errors:
        result.reversed_ids, result.unknown_ids = [], []
        return result
    result.proposed_changes = [_summarize(e) for e in entries if not _is_noop(e["change"]["actions"])]
    return result
