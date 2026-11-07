"""Normalization and set-diffing of digitalocean_firewall inbound rules.

Pure functions only. Input is untrusted JSON (from `terraform show -json`), so
every value is type-checked; malformed rule objects normalize to None rather
than raising.

Identity: two rules are equal iff action, protocol, port_range and every source
collection are equal after normalization. Source collections are sorted and
de-duplicated, so provider ordering never matters, and rules are always
compared as sets, never by list index.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import ChangeKind, FirewallRule

_SOURCE_KEYS = (
    "source_addresses",
    "source_tags",
    "source_droplet_ids",
    "source_load_balancer_uids",
    "source_kubernetes_ids",
)

_MALFORMED = object()


def _scalar_str(value: Any) -> str | None | object:
    """Return a stripped string for str/int values, None for null/empty,
    and _MALFORMED for anything else (bool, float, dict, list...)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return _MALFORMED
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return _MALFORMED


def _source_tuple(value: Any) -> tuple[str, ...] | object:
    if value is None:
        return ()
    if not isinstance(value, list):
        return _MALFORMED
    out: set[str] = set()
    for item in value:
        s = _scalar_str(item)
        if s is _MALFORMED:
            return _MALFORMED
        if s is not None:
            out.add(s)  # type: ignore[arg-type]
    return tuple(sorted(out))


def normalize_rule(raw: dict) -> FirewallRule | None:
    """Normalize one provider inbound_rule object.

    Returns None if `raw` is not a dict or if any known field has an
    impossible type (e.g. protocol is a dict, source_addresses is a string),
    so callers never compare half-parsed rules. Missing/null fields are
    treated as unknown (protocol/port_range -> None) or empty (sources).
    An empty port_range string (as the provider stores for icmp) becomes None.
    """
    if not isinstance(raw, dict):
        return None
    protocol = _scalar_str(raw.get("protocol"))
    port_range = _scalar_str(raw.get("port_range"))
    action = _scalar_str(raw.get("action"))
    if protocol is _MALFORMED or port_range is _MALFORMED or action is _MALFORMED:
        return None
    sources: dict[str, tuple[str, ...]] = {}
    for key in _SOURCE_KEYS:
        t = _source_tuple(raw.get(key))
        if t is _MALFORMED:
            return None
        sources[key] = t  # type: ignore[assignment]
    return FirewallRule(
        # A missing action means "allow": DigitalOcean rules without the field predate
        # deny support. Treating it as None would make old state and new live output
        # look like different rules (false records, missed warnings, false resolution).
        action=action.lower() if isinstance(action, str) else "allow",
        protocol=protocol.lower() if isinstance(protocol, str) else None,
        port_range=port_range if isinstance(port_range, str) else None,
        **sources,
    )


def rule_set(raw_rules: object) -> tuple[frozenset[FirewallRule], bool]:
    """Normalize a provider inbound_rule list into a set.

    ok=False when raw_rules is not a list (null, unknown, dict...) or any
    element fails to normalize; the returned set is then empty and must not
    be used for comparisons.
    """
    if not isinstance(raw_rules, list):
        return frozenset(), False
    rules: set[FirewallRule] = set()
    for raw in raw_rules:
        rule = normalize_rule(raw)
        if rule is None:
            return frozenset(), False
        rules.add(rule)
    return frozenset(rules), True


def rule_sort_key(rule: FirewallRule | None) -> tuple:
    """Total, deterministic ordering key (None sorts first)."""
    if rule is None:
        return (0,)
    return (
        1,
        rule.action or "",
        rule.protocol or "",
        rule.port_range or "",
        rule.sources_key(),
    )


def _port_phrase(rule: FirewallRule) -> str | None:
    port = rule.port_range
    if port is None:
        # The provider stores no port for icmp; don't call that "unknown".
        return None if rule.protocol == "icmp" else "port unknown"
    if port.lower() in ("all", "0", "1-65535"):
        return "all ports"
    if "-" in port:
        return f"ports {port}"
    return f"port {port}"


def _sources_phrase(rule: FirewallRule) -> str:
    parts: list[str] = list(rule.source_addresses)
    parts += [f"tag:{t}" for t in rule.source_tags]
    parts += [f"droplet:{d}" for d in rule.source_droplet_ids]
    parts += [f"load_balancer:{u}" for u in rule.source_load_balancer_uids]
    parts += [f"kubernetes:{k}" for k in rule.source_kubernetes_ids]
    return ", ".join(parts) if parts else "no sources"


def describe_rule(rule: FirewallRule) -> str:
    """Human-readable, e.g. "inbound tcp port 8443 from 0.0.0.0/0, ::/0"."""
    proto = rule.protocol or "unknown protocol"
    port = _port_phrase(rule)
    verb = "inbound" if rule.action in (None, "allow") else f"inbound {rule.action.upper()}"
    head = f"{verb} {proto}" + (f" {port}" if port else "")
    return f"{head} from {_sources_phrase(rule)}"


def short_rule(rule: FirewallRule) -> str:
    """Compact form for plan summaries, e.g. "tcp 8443"."""
    proto = rule.protocol or "unknown"
    prefix = "" if rule.action in (None, "allow") else f"{rule.action} "
    if rule.port_range is None:
        return prefix + (proto if rule.protocol == "icmp" else f"{proto} ?")
    return f"{prefix}{proto} {rule.port_range}"


_KIND_ORDER = {ChangeKind.MODIFIED: 0, ChangeKind.REMOVED: 1, ChangeKind.ADDED: 2}


def diff_rules(
    before: frozenset[FirewallRule], after: frozenset[FirewallRule]
) -> list[tuple[ChangeKind, FirewallRule | None, FirewallRule | None]]:
    """Set difference of two rule sets.

    removed = before - after, added = after - before. A removed and an added
    rule are paired into MODIFIED (baseline=removed, observed=added) only when
    they share protocol and sources_key() and that group contains exactly one
    removed and exactly one added rule. Any other situation (ambiguous groups,
    unmatched rules) yields separate REMOVED / ADDED entries.

    Output order is deterministic.
    """
    removed = before - after
    added = after - before

    def group_key(r: FirewallRule) -> tuple:
        return (r.action or "", r.protocol or "", r.sources_key())

    rem_groups: dict[tuple, list[FirewallRule]] = defaultdict(list)
    add_groups: dict[tuple, list[FirewallRule]] = defaultdict(list)
    for r in removed:
        rem_groups[group_key(r)].append(r)
    for r in added:
        add_groups[group_key(r)].append(r)

    out: list[tuple[ChangeKind, FirewallRule | None, FirewallRule | None]] = []
    paired_rem: set[FirewallRule] = set()
    paired_add: set[FirewallRule] = set()
    for key, rems in rem_groups.items():
        adds = add_groups.get(key, [])
        if len(rems) == 1 and len(adds) == 1:
            out.append((ChangeKind.MODIFIED, rems[0], adds[0]))
            paired_rem.add(rems[0])
            paired_add.add(adds[0])
    for r in removed - paired_rem:
        out.append((ChangeKind.REMOVED, r, None))
    for r in added - paired_add:
        out.append((ChangeKind.ADDED, None, r))

    out.sort(key=lambda t: (_KIND_ORDER[t[0]], rule_sort_key(t[1]), rule_sort_key(t[2])))
    return out
