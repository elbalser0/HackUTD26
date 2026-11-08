"""Orchestration: scans -> records (dedup/supersede), report/decision, warnings,
and verified resolution. No subprocess here: callers pass parsed plan JSON.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import detector, matcher, rules
from .db import Database, new_id, rule_from_json, rule_to_json, ts
from .models import (
    LastActivityOut,
    ChangeKind,
    CheckStatus,
    DecisionIn,
    FirewallRule,
    Intent,
    MatchCandidate,
    Observation,
    RecordOut,
    ReportIn,
    Resolution,
    ResolutionReason,
    RuleOut,
    WarningOut,
    utcnow,
)


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    pass


class BadInput(ValueError):
    """Client input rejected by business rules; message is safe to return."""


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def _rule_key(rule: FirewallRule | None) -> str:
    return rule_to_json(rule) or "null"


def scope_key(obs: Observation) -> str:
    """What the record is *about*: the declared rule that was changed/removed,
    or the live rule that was added. Same scope + different evidence = supersede."""
    anchor = obs.observed if obs.kind == ChangeKind.ADDED else obs.baseline
    return f"{obs.resource_address}|{obs.attribute}|{obs.kind.value if obs.kind == ChangeKind.ADDED else 'declared'}|{_rule_key(anchor)}"


def fingerprint(environment: str, obs: Observation) -> str:
    raw = "|".join([
        environment, obs.resource_address, obs.attribute, obs.kind.value,
        _rule_key(obs.baseline), _rule_key(obs.observed),
    ])
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def summarize(obs_kind: ChangeKind, baseline: FirewallRule | None, observed: FirewallRule | None) -> str:
    if obs_kind == ChangeKind.MODIFIED and baseline and observed:
        return (f"{rules.describe_rule(baseline)} changed live to port {observed.port_range or 'unknown'}"
                if baseline.protocol == observed.protocol else
                f"{rules.describe_rule(baseline)} -> {rules.describe_rule(observed)}")
    if obs_kind == ChangeKind.ADDED and observed:
        return f"added live: {rules.describe_rule(observed)}"
    if obs_kind == ChangeKind.REMOVED and baseline:
        return f"removed live: {rules.describe_rule(baseline)}"
    return "unrecognized change"


# ---------------------------------------------------------------------------
# row <-> API
# ---------------------------------------------------------------------------

def _rule_out(rule: FirewallRule | None) -> RuleOut | None:
    return None if rule is None else RuleOut(**rule.to_dict())


def record_out(row) -> RecordOut:
    return RecordOut(
        id=row["id"],
        environment=row["environment"],
        resource_address=row["resource_address"],
        resource_type=row["resource_type"],
        attribute=row["attribute"],
        change_kind=row["change_kind"],
        baseline_value=_rule_out(rule_from_json(row["baseline_json"])),
        observed_value=_rule_out(rule_from_json(row["observed_json"])),
        summary=row["summary"],
        first_detected_at=row["first_detected_at"],
        last_detected_at=row["last_detected_at"],
        reporter=row["reporter"],
        reason=row["reason"],
        reported_at=row["reported_at"],
        intent=row["intent"],
        intent_note=row["intent_note"],
        intent_updated_at=row["intent_updated_at"],
        resolution=row["resolution"],
        resolution_reason=row["resolution_reason"],
        resolved_at=row["resolved_at"],
        superseded_by=row["superseded_by"],
        last_check_status=row["last_check_status"],
        last_check_at=row["last_check_at"],
        evidence_source=row["evidence_source"],
    )


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def records_out(db: Database, rows) -> list[RecordOut]:
    """Records for the web UI, with who explained them (assurance) and their last activity.
    Derived from the append-only events table; nothing is written."""
    by_record: dict[str, list] = {}
    for e in db.list_all_events():  # oldest first
        if e["record_id"]:
            by_record.setdefault(e["record_id"], []).append(e)
    out = []
    for row in rows:
        rec = record_out(row)
        evs = by_record.get(row["id"], [])
        reports = [e for e in evs if e["kind"] == "report"]
        assurance = None
        if row["reason"]:
            assurance = reports[-1]["actor_assurance"] if reports else "self-reported"
        candidates = [(_parse_ts(row["first_detected_at"]), "detected")]
        candidates += [(_parse_ts(e["created_at"]), e["kind"]) for e in evs]
        if row["resolution"] == "resolved":
            candidates.append((_parse_ts(row["resolved_at"]), "resolved"))
        last = None
        for t, k in candidates:  # later entries win ties: events are in insertion order
            if t is not None and (last is None or t >= last[0]):
                last = (t, k)
        out.append(rec.model_copy(update={
            "reporter_assurance": assurance,
            "last_activity": LastActivityOut(at=last[0], type=last[1]) if last else None}))
    return out


def candidate(row) -> MatchCandidate:
    return MatchCandidate(
        record_id=row["id"],
        resource_address=row["resource_address"],
        kind=ChangeKind(row["change_kind"]),
        baseline=rule_from_json(row["baseline_json"]),
        observed=rule_from_json(row["observed_json"]),
    )


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

@dataclass
class ScanOutcome:
    status: str  # "ok" | "failed"
    new_ids: list[str] = field(default_factory=list)
    seen_ids: list[str] = field(default_factory=list)
    superseded_ids: list[str] = field(default_factory=list)
    stale_ids: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _mark_open(db: Database, environment: str, status: CheckStatus, now: str, conn) -> list[str]:
    ids = db.open_record_ids(environment, conn)
    for rid in ids:
        db.update_record(rid, {"last_check_status": status.value, "last_check_at": now}, conn)
    return ids


def ingest_refresh_plan(
    db: Database,
    environment: str,
    plan: Any,
    evidence_source: str = "terraform-refresh-only",
    now: datetime | None = None,
) -> ScanOutcome:
    """Turn a refresh-only plan JSON into records. Idempotent for identical evidence."""
    now_s = ts(now or utcnow())
    result = detector.detect(plan)
    out = ScanOutcome(status="ok", unsupported=list(result.unsupported), errors=list(result.errors))

    with db.tx() as conn:
        db.lock_environment(conn, environment)
        if result.errors:
            out.status = "failed"
            _mark_open(db, environment, CheckStatus.FAILED, now_s, conn)
            db.insert_scan(new_id("scan"), environment, now_s, "failed", json.dumps(result.errors)[:2000], conn)
            return out

        seen: set[str] = set()
        for obs in result.observations:
            fp = fingerprint(environment, obs)
            existing = db.find_open_by_fingerprint(environment, fp, conn)
            if existing is not None:
                db.update_record(existing["id"], {
                    "last_detected_at": now_s,
                    "last_check_status": obs.check_status.value,
                    "last_check_at": now_s,
                }, conn)
                out.seen_ids.append(existing["id"])
                seen.add(existing["id"])
                continue

            rid = new_id("rec")
            db.insert_record({
                "id": rid,
                "environment": environment,
                "resource_address": obs.resource_address,
                "resource_type": obs.resource_type,
                "attribute": obs.attribute,
                "change_kind": obs.kind.value,
                "baseline_json": rule_to_json(obs.baseline),
                "observed_json": rule_to_json(obs.observed),
                "scope_key": scope_key(obs),
                "fingerprint": fp,
                "summary": summarize(obs.kind, obs.baseline, obs.observed),
                "first_detected_at": now_s,
                "last_detected_at": now_s,
                "intent": Intent.UNSET.value,
                "resolution": Resolution.OPEN.value,
                "last_check_status": obs.check_status.value,
                "last_check_at": now_s,
                "evidence_source": evidence_source,
            }, conn)
            out.new_ids.append(rid)
            seen.add(rid)

            # Changed evidence for the same declared rule supersedes the old record.
            # The old explanation stays on the old record; it is NOT copied forward.
            for old in db.find_open_by_scope(environment, scope_key(obs), conn):
                if old["id"] == rid:
                    continue
                db.update_record(old["id"], {
                    "resolution": Resolution.RESOLVED.value,
                    "resolution_reason": ResolutionReason.SUPERSEDED.value,
                    "resolved_at": now_s,
                    "superseded_by": rid,
                }, conn)
                out.superseded_ids.append(old["id"])

        # Open records not observed in this successful scan: no longer drifting
        # vs state. That is NOT resolution (IaC may still disagree) -> stale until recheck.
        for open_id in db.open_record_ids(environment, conn):
            if open_id not in seen:
                db.update_record(open_id, {"last_check_status": CheckStatus.STALE.value, "last_check_at": now_s}, conn)
                out.stale_ids.append(open_id)

        db.insert_scan(new_id("scan"), environment, now_s, "ok",
                       json.dumps({"new": len(out.new_ids), "seen": len(out.seen_ids),
                                   "unsupported": out.unsupported})[:2000], conn)
    return out


# ---------------------------------------------------------------------------
# report / decision
# ---------------------------------------------------------------------------

def _require_open(db: Database, record_id: str, conn=None):
    # Inside a transaction the row is locked so two concurrent writers cannot both pass the open check.
    row = db.get_record(record_id, conn, for_update=conn is not None)
    if row is None:
        raise NotFound(f"record {record_id} not found")
    if row["resolution"] != Resolution.OPEN.value:
        raise Conflict(f"record {record_id} is resolved ({row['resolution_reason']})")
    return row


def _event(db: Database, conn, *, environment: str, kind: str, record_id: str | None, run_id: str | None,
           actor: str | None, assurance: str, data: dict, now_s: str) -> str:
    eid = new_id("evt")
    db.insert_event({"id": eid, "environment": environment, "record_id": record_id, "run_id": run_id,
                     "kind": kind, "actor": actor, "actor_assurance": assurance,
                     "data_json": json.dumps(data, sort_keys=True), "created_at": now_s}, conn)
    return eid


def event_out(row) -> "EventOut":
    from .models import EventOut
    return EventOut(id=row["id"], environment=row["environment"], record_id=row["record_id"],
                    run_id=row["run_id"], kind=row["kind"], actor=row["actor"],
                    actor_assurance=row["actor_assurance"], data=json.loads(row["data_json"]),
                    created_at=row["created_at"])


def report(db: Database, record_id: str, body: ReportIn, now: datetime | None = None,
           source: str = "web", account: str | None = None, account_name: str | None = None,
           assurance: str = "self-reported") -> RecordOut:
    """`account` is a verified sign-in (email) when present. The typed reporter name
    stays the self-reported name; without one, the account's display name is used."""
    now_s = ts(now or utcnow())
    with db.tx() as conn:
        _require_open(db, record_id, conn)
        fields: dict[str, Any] = {
            "reporter": (body.reporter.strip() if body.reporter and body.reporter.strip()
                         else (account_name or account)),
            "reason": body.reason.strip(),
            "reported_at": now_s,
        }
        if not fields["reason"]:
            raise BadInput("reason must not be blank")
        if body.intent is not None:
            fields.update(intent=body.intent.value, intent_updated_at=now_s)
        db.update_record(record_id, fields, conn)
        environment = db.record_environment(record_id, conn)
        # Append-only history: a later report never erases an earlier one (PRD R6/R10).
        _event(db, conn, environment=environment, kind="report", record_id=record_id, run_id=None,
               actor=account or fields["reporter"], assurance=assurance, now_s=now_s,
               data={"reason": fields["reason"], "intent": body.intent.value if body.intent else None,
                     "source": source, "reporter_name": fields["reporter"]})
    return record_out(db.get_record(record_id))


def decide(db: Database, record_id: str, body: DecisionIn, now: datetime | None = None,
           source: str = "web", actor: str | None = None, assurance: str = "self-reported") -> RecordOut:
    """Store intent. Never resolves, never applies."""
    now_s = ts(now or utcnow())
    with db.tx() as conn:
        _require_open(db, record_id, conn)
        note = body.note.strip() if body.note and body.note.strip() else None
        db.update_record(record_id, {
            "intent": body.intent.value,
            "intent_note": note,
            "intent_updated_at": now_s,
        }, conn)
        env = db.record_environment(record_id, conn)
        _event(db, conn, environment=env, kind="decision", record_id=record_id, run_id=None,
               actor=actor, assurance=assurance, now_s=now_s,
               data={"intent": body.intent.value, "note": note, "source": source})
    return record_out(db.get_record(record_id))


# ---------------------------------------------------------------------------
# warnings
# ---------------------------------------------------------------------------

def _detected_label(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def warning_message(row) -> str:
    kind = ChangeKind(row["change_kind"])
    observed = rule_from_json(row["observed_json"])
    baseline = rule_from_json(row["baseline_json"])
    if kind in (ChangeKind.ADDED, ChangeKind.MODIFIED) and observed is not None:
        effect = f"This apply will remove the live rule '{rules.describe_rule(observed)}'"
        if kind == ChangeKind.MODIFIED and baseline is not None:
            effect += f" and restore port {baseline.port_range or 'unknown'}"
    elif baseline is not None:
        effect = f"This apply will re-add '{rules.describe_rule(baseline)}', which was removed live"
    else:
        effect = "This apply touches a manually changed rule"
    detected = _detected_label(row["first_detected_at"])
    if row["reason"]:
        who = f"{row['reporter']} reported" if row["reporter"] else "Someone (no name given) reported"
        return f"{effect}. {who} (self-reported; detected {detected}): \"{row['reason']}\"."
    return f"{effect}. Unexplained manual change, no reason recorded (detected {detected})."


def warning_out(row) -> WarningOut:
    return WarningOut(
        record_id=row["id"],
        resource_address=row["resource_address"],
        message=warning_message(row),
        reason=row["reason"],
        reporter=row["reporter"],
        intent=row["intent"],
        first_detected_at=row["first_detected_at"],
    )


# ---------------------------------------------------------------------------
# resolution re-check
# ---------------------------------------------------------------------------

def _plan_addresses(plan: Any) -> set[str]:
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        return set()
    return {rc.get("address") for rc in plan["resource_changes"] if isinstance(rc, dict) and isinstance(rc.get("address"), str)}


@dataclass
class RecheckOutcome:
    status: str  # "ok" | "failed"
    resolved_ids: list[str] = field(default_factory=list)
    still_open: dict[str, str] = field(default_factory=dict)  # id -> why
    errors: list[str] = field(default_factory=list)


def recheck(
    db: Database,
    environment: str,
    refresh_plan: Any,
    normal_plan: Any,
    now: datetime | None = None,
) -> RecheckOutcome:
    """Resolve a record only if BOTH:
    1. a fresh refresh-only plan shows no discrepancy for it (live == state), and
    2. a fresh normal plan covers the resource and does not reverse it (IaC == live).
    Any failed/unknown evidence keeps the record open.
    """
    now_s = ts(now or utcnow())
    det = detector.detect(refresh_plan)
    open_rows = db.list_records(resolution="open", environment=environment)
    out = RecheckOutcome(status="ok")

    if det.errors:
        out.status = "failed"
        out.errors = list(det.errors)
        with db.tx() as conn:
            _mark_open(db, environment, CheckStatus.FAILED, now_s, conn)
        out.still_open = {r["id"]: "refresh-only check failed" for r in open_rows}
        return out

    cands = [candidate(r) for r in open_rows]
    m = matcher.match(normal_plan, cands)
    if m.errors:
        out.status = "failed"
        out.errors = list(m.errors)
        with db.tx() as conn:
            _mark_open(db, environment, CheckStatus.FAILED, now_s, conn)
        out.still_open = {r["id"]: "normal plan check failed" for r in open_rows}
        return out

    drifting = {fingerprint(environment, o) for o in det.observations}
    drifting_scopes = {scope_key(o) for o in det.observations}
    unsupported_text = " ".join(det.unsupported)
    covered = _plan_addresses(normal_plan)

    with db.tx() as conn:
        db.lock_environment(conn, environment)
        for r in open_rows:
            rid = r["id"]
            if r["fingerprint"] in drifting:
                why, status = "live value still differs from Terraform state", CheckStatus.CURRENT
            elif r["scope_key"] in drifting_scopes:
                why, status = "live value changed again; run `argus scan` to record the new evidence", CheckStatus.STALE
            elif r["resource_address"] in unsupported_text:
                why, status = "refresh-only evidence for this resource was not interpretable", CheckStatus.UNSUPPORTED
            elif rid in m.unknown_ids:
                why, status = "normal plan reversal could not be determined", CheckStatus.UNSUPPORTED
            elif rid in m.reversed_ids:
                why, status = "Terraform config would still reverse the live value", CheckStatus.CURRENT
            elif r["resource_address"] not in covered:
                why, status = "resource not present in the normal plan; alignment unproven", CheckStatus.UNSUPPORTED
            else:
                db.update_record(rid, {
                    "resolution": Resolution.RESOLVED.value,
                    "resolution_reason": ResolutionReason.VERIFIED_ALIGNED.value,
                    "resolved_at": now_s,
                    "last_check_status": CheckStatus.CURRENT.value,
                    "last_check_at": now_s,
                }, conn)
                out.resolved_ids.append(rid)
                continue
            db.update_record(rid, {"last_check_status": status.value, "last_check_at": now_s}, conn)
            out.still_open[rid] = why
    return out
