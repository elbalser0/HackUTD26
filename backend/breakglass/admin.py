"""R9 admin views: a team-wide event log and a per-record timeline.

Read-side derivation only; it never writes. Sources:
- `events` (append-only): reports, decisions, wrapper reviews, run start/finish.
- `records`: detection and resolution times (not stored as events).
- `apply_runs`: only to (a) name the resources and records a run touched, (b) surface runs that
  never recorded a completion, and (c) show runs from before the events table existed.
Nothing is invented. Whatever the data cannot show is declared in `limitations` and `gaps`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .db import Database
from .models import (
    ActivityBucketOut,
    AdminEventOut,
    AdminLogOut,
    LastRunOut,
    LastScanOut,
    NeedsReasonOut,
    OverviewOut,
    RunOutcome,
    TimelineGap,
    TimelineOut,
)

LIMITATIONS = [
    "Only web actions made while signed in carry a verified account (Google sign-in); everything else is "
    "self-reported, and a wrapper reviewer is either self-reported or the local OS user (not verified). "
    "A verified account shows who submitted an explanation, not who made the console change.",
    "Admin access is a Firebase sign-in from an allowlisted email, or the shared fallback token; the shared "
    "token shows that an admin read the log, not which admin.",
    "A run with no recorded completion is shown as unknown: it may have been interrupted, crashed, or still be "
    "running. Unknown is not the same as failed, and never means success.",
    "Records and runs from before the events table existed show only their latest stored values and are labelled "
    "as predating event history.",
    "A successful apply does not prove the service is healthy.",
]

EVENT_TYPES = ("change_detected", "explained", "decision", "review", "run_started", "run_finished",
               "run_unfinished", "resolved")
WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}
OVERVIEW_LIMITATION = ("Counts are events in the window, not incidents or downtime. Downtime attribution is "
                       "unavailable: no incident or health evidence is linked.")

_RANK = {"change_detected": 0, "explained": 1, "decision": 2, "review": 3, "run_started": 4,
         "run_unfinished": 5, "run_finished": 5, "resolved": 6}
_LEGACY = " (from the stored record; predates event history)"
_TERMINAL = {o.value for o in RunOutcome} - {"unknown"}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _outcome(raw: str | None) -> RunOutcome:
    return RunOutcome(raw) if raw in _TERMINAL or raw == "unknown" else RunOutcome.UNKNOWN


def _ev(at, type_, environment, *, record_ids=(), run_id=None, addresses=(), actor=None,
        assurance="system", outcome=None, plan=None, detail=None) -> AdminEventOut:
    return AdminEventOut(at=at, type=type_, environment=environment, record_ids=list(record_ids), run_id=run_id,
                         resource_addresses=list(addresses), actor=actor, actor_assurance=assurance,
                         outcome=outcome, plan_fingerprint=plan, detail=detail)


def _decision_text(intent: str | None, note: str | None) -> str:
    return f"intent: {intent}" + (f" — {note}" if note else "")


class _View:
    """One consistent snapshot of everything the admin pages derive from."""

    def __init__(self, db: Database):
        self.records = {r["id"]: r for r in db.list_records()}
        self.runs = {r["id"]: r for r in db.list_all_apply_runs()}
        self.raw_events = list(db.list_all_events())
        # run -> record ids / resource addresses, from the run row, review events and run_started
        self.run_records: dict[str, set[str]] = {}
        self.run_addresses: dict[str, set[str]] = {}
        for rid, row in self.runs.items():
            warns = json.loads(row["warnings_json"] or "[]")
            changes = json.loads(row["proposed_changes_json"] or "[]")
            self.run_records[rid] = {w["record_id"] for w in warns}
            self.run_addresses[rid] = {w["resource_address"] for w in warns} | {c["resource_address"] for c in changes}
        for e in self.raw_events:
            data = json.loads(e["data_json"])
            if e["run_id"] and e["kind"] == "review" and e["record_id"]:
                self.run_records.setdefault(e["run_id"], set()).add(e["record_id"])
            if e["run_id"] and e["kind"] == "run_started":
                self.run_records.setdefault(e["run_id"], set()).update(data.get("record_ids", []))
        self.events = self._build()

    def _addr(self, record_id: str | None, run_id: str | None) -> list[str]:
        if record_id and record_id in self.records:
            return [self.records[record_id]["resource_address"]]
        if run_id:
            return sorted(self.run_addresses.get(run_id, set()))
        return []

    def _build(self) -> list[AdminEventOut]:
        out: list[AdminEventOut] = []
        by_record: dict[str, set[str]] = {}
        finished_runs: set[str] = set()
        for e in self.raw_events:
            kind, data = e["kind"], json.loads(e["data_json"])
            rec, run = e["record_id"], e["run_id"]
            by_record.setdefault(rec or "", set()).add(kind)
            at, env = _dt(e["created_at"]), e["environment"]
            common = dict(actor=e["actor"], assurance=e["actor_assurance"])
            if kind == "report":
                out.append(_ev(at, "explained", env, record_ids=[rec], addresses=self._addr(rec, None),
                               detail=data.get("reason"), **common))
                if data.get("intent"):
                    by_record[rec or ""].add("decision")
                    out.append(_ev(at, "decision", env, record_ids=[rec], addresses=self._addr(rec, None),
                                   detail=_decision_text(data["intent"], None), **common))
            elif kind == "decision":
                out.append(_ev(at, "decision", env, record_ids=[rec], addresses=self._addr(rec, None),
                               detail=_decision_text(data.get("intent"), data.get("note")), **common))
            elif kind == "review":
                detail = f"decision: {data.get('decision')}" + (f" — {data['rationale']}" if data.get("rationale") else "")
                out.append(_ev(at, "review", env, record_ids=[rec] if rec else [], run_id=run,
                               addresses=self._addr(rec, run), plan=data.get("plan_fingerprint"),
                               detail=detail, **common))
            elif kind == "run_started":
                out.append(_ev(at, "run_started", env, record_ids=sorted(self.run_records.get(run, set())),
                               run_id=run, addresses=self._addr(None, run), plan=data.get("plan_fingerprint"),
                               detail=f"terraform apply started after decision: {data.get('decision')}", **common))
            elif kind == "run_finished":
                finished_runs.add(run)
                oc = _outcome(data.get("outcome"))
                detail = f"outcome: {oc.value}" + (f" — {data['note']}" if data.get("note") else "")
                out.append(_ev(at, "run_finished", env, record_ids=sorted(self.run_records.get(run, set())),
                               run_id=run, addresses=self._addr(None, run), outcome=oc, detail=detail, **common))
        for rid, r in self.records.items():
            env, addr = r["environment"], [r["resource_address"]]
            out.append(_ev(_dt(r["first_detected_at"]), "change_detected", env, record_ids=[rid], addresses=addr,
                           detail=r["summary"]))
            kinds = by_record.get(rid, set())
            if r["reported_at"] and "report" not in kinds:
                out.append(_ev(_dt(r["reported_at"]), "explained", env, record_ids=[rid], addresses=addr,
                               actor=r["reporter"], assurance="self-reported", detail=(r["reason"] or "") + _LEGACY))
            if r["intent_updated_at"] and not ({"decision", "review"} & kinds):
                out.append(_ev(_dt(r["intent_updated_at"]), "decision", env, record_ids=[rid], addresses=addr,
                               assurance="self-reported",
                               detail=_decision_text(r["intent"], r["intent_note"]) + _LEGACY))
            if r["resolution"] == "resolved" and r["resolved_at"]:
                detail = r["resolution_reason"] or "resolved"
                if r["superseded_by"]:
                    detail += f" (superseded by {r['superseded_by']})"
                out.append(_ev(_dt(r["resolved_at"]), "resolved", env, record_ids=[rid], addresses=addr, detail=detail))
        for rid, r in self.runs.items():
            if rid in finished_runs:
                continue
            env, who = r["environment"], dict(actor=r["reviewer"], assurance=r["reviewer_assurance"] or "system")
            common = dict(record_ids=sorted(self.run_records.get(rid, set())), run_id=rid,
                          addresses=sorted(self.run_addresses.get(rid, set())))
            if r["completed_at"]:  # finished before the events table existed
                oc = _outcome(r["ack_outcome"])
                out.append(_ev(_dt(r["completed_at"]), "run_finished", env, outcome=oc, **common, **who,
                               detail=f"outcome: {oc.value}" + (f" — {r['ack_note']}" if r["ack_note"] else "") + _LEGACY))
            else:
                out.append(_ev(_dt(r["started_at"] or r["generated_at"]), "run_unfinished", env,
                               outcome=RunOutcome.UNKNOWN, **common, **who,
                               detail="No completion recorded; the run may have been interrupted or crashed, "
                                      "or may still be running. Do not assume it succeeded."))
        # stable sort: equal (time, rank) keep insertion order, so a review precedes its run_started
        out.sort(key=lambda e: (e.at, _RANK[e.type]))
        return out


def log(db: Database, *, engineer: str | None = None, resource: str | None = None,
        since: datetime | None = None, until: datetime | None = None,
        outcome: RunOutcome | None = None, event_type: str | None = None, limit: int = 100) -> AdminLogOut:
    events = _View(db).events
    if engineer is not None:
        events = [e for e in events if e.actor and e.actor.casefold() == engineer.casefold()]
    if resource is not None:
        events = [e for e in events if resource in e.resource_addresses]
    if since is not None:
        events = [e for e in events if e.at >= since]
    if until is not None:
        events = [e for e in events if e.at <= until]
    if outcome is not None:
        events = [e for e in events if e.outcome == outcome]
    if event_type is not None:
        events = [e for e in events if e.type == event_type]
    events = events[::-1]  # newest first
    return AdminLogOut(events=events[:limit], total_matching=len(events), limitations=LIMITATIONS)


def timeline(db: Database, record_id: str) -> TimelineOut | None:
    v = _View(db)
    if record_id not in v.records:
        return None
    linked_runs = {rid for rid, recs in v.run_records.items() if record_id in recs}
    events = [e for e in v.events if record_id in e.record_ids or (e.run_id in linked_runs and e.type in (
        "run_started", "run_finished", "run_unfinished"))]
    kinds = {e.type for e in events}
    gaps: list[TimelineGap] = []
    if "explained" not in kinds:
        gaps.append(TimelineGap(code="no_reason_recorded", message="No reason was recorded for this change."))
    if not ({"decision", "review"} & kinds):
        gaps.append(TimelineGap(code="no_decision_recorded",
                                message="No keep/revert/defer decision was recorded for this change."))
    if not linked_runs:
        gaps.append(TimelineGap(code="no_run_linked", message="No wrapper run has reviewed this change."))
    for e in events:
        if e.type in ("run_finished", "run_unfinished") and e.outcome is RunOutcome.UNKNOWN:
            gaps.append(TimelineGap(code="run_outcome_unknown", run_id=e.run_id,
                                    message=f"Run {e.run_id} has no recorded completion; do not assume it succeeded."))
    return TimelineOut(record_id=record_id, events=events, gaps=gaps, limitations=LIMITATIONS)


def overview(db: Database, *, window: str, now: datetime, environment: str) -> OverviewOut:
    """Admin overview: "manual changes, before the next apply". Read-only.
    Counts are by event type and run outcome only, never by person (PRD non-goal: blame scores)."""
    span = WINDOWS[window]
    view = _View(db)
    since = now - span
    open_rows = [r for r in view.records.values() if r["resolution"] == "open"]
    missing = sorted((r for r in open_rows if not r["reason"]), key=lambda r: r["first_detected_at"], reverse=True)
    in_window = [e for e in view.events if since <= e.at <= now]

    by_type: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    for e in in_window:
        by_type[e.type] = by_type.get(e.type, 0) + 1
        if e.type in ("run_finished", "run_unfinished") and e.outcome is not None:
            outcomes[e.outcome.value] = outcomes.get(e.outcome.value, 0) + 1

    start = (now - span).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    hours = int(span / timedelta(hours=1))
    buckets = [ActivityBucketOut(hour=start + timedelta(hours=i), counts={}) for i in range(hours)]
    for e in in_window:
        i = int((e.at.astimezone(timezone.utc) - start) // timedelta(hours=1))
        if 0 <= i < hours:
            b = buckets[i].counts
            b[e.type] = b.get(e.type, 0) + 1

    runs = [e for e in view.events if e.type in ("run_finished", "run_unfinished") and e.run_id and e.at <= now]
    last_run = None
    if runs:
        lr = runs[-1]
        last_run = LastRunOut(run_id=lr.run_id, outcome=lr.outcome or RunOutcome.UNKNOWN, at=lr.at)

    scan = db.last_scan(environment)
    last_scan = None
    if scan is not None:
        try:
            last_scan = LastScanOut(at=_dt(scan["started_at"]), status=scan["status"])
        except (ValueError, TypeError):
            last_scan = None

    return OverviewOut(
        window=window, generated_at=now, open_records=len(open_rows), open_without_reason=len(missing),
        needs_reason=[NeedsReasonOut(record_id=r["id"], resource_address=r["resource_address"],
                                     summary=r["summary"], first_detected_at=_dt(r["first_detected_at"]))
                      for r in missing],
        last_scan=last_scan, last_run=last_run, events_by_type=by_type, run_outcomes=outcomes,
        activity=buckets, limitations=LIMITATIONS + [OVERVIEW_LIMITATION])
