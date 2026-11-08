"""`argus seed-history`: one week of AUTHORED demo history for the presentation.

Writes records, explanations, decisions, apply runs and scans through the same
service and wrapper code paths real data uses, with timestamps spread over the last
seven days, so the Overview chart, All records, Events and Record pages have something
to show. Everything is labelled authored (evidence_source ``authored-fixture``, its
own ``<environment>-authored`` environment) and never merges into live records.

It never writes a run without a recorded completion: an unknown outcome is a real
finding about a real run, so it must never come from demo data. People are made up;
verified accounts use the reserved example.com domain.

Refuses to run twice (it would duplicate history) and refuses a non-authored environment.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import service
from .db import Database, new_id, ts
from .models import AckOutcome, CheckStatus, Intent, ReportIn, Resolution, ResolutionReason, utcnow
from .wrapper import OS_USER_ASSURANCE, SELF_REPORTED

VERIFIED = "google-account (verified sign-in)"
_FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "authored" / "refresh_drift_8443.json"
MARKER = "seed-history"


class SeedHistoryRefused(RuntimeError):
    pass


@dataclass
class Summary:
    records: int
    open: int
    needs_reason: int
    runs: int
    scans: int


def _rule(port: str, sources: list[str] | None = None) -> dict:
    return {"protocol": "tcp", "port_range": port, "source_addresses": sources or ["0.0.0.0/0", "::/0"],
            "source_droplet_ids": [], "source_kubernetes_ids": [], "source_load_balancer_uids": [],
            "source_tags": [], "action": "allow"}


def _plan(address: str, before_ports: list[str], after_ports: list[str]) -> dict:
    """A refresh-only plan (authored shape) where `address` drifted from before_ports to after_ports."""
    p = copy.deepcopy(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    ssh = _rule("22", ["203.0.113.10/32"])
    d = p["resource_drift"][0]
    d["address"], d["name"] = address, address.split(".")[-1]
    d["change"]["before"]["inbound_rule"] = [_rule(x) for x in before_ports] + [ssh]
    d["change"]["after"]["inbound_rule"] = [_rule(x) for x in after_ports] + [ssh]
    p["resource_changes"] = []
    return p


def _event(db: Database, conn, env: str, kind: str, at: datetime, *, record_id: str | None = None,
           run_id: str | None = None, actor: str | None = None, assurance: str = "system", data: dict) -> None:
    service._event(db, conn, environment=env, kind=kind, record_id=record_id, run_id=run_id, actor=actor,
                   assurance=assurance, data=data, now_s=ts(at))


def _run(db: Database, env: str, *, at: datetime, reviewer: str, assurance: str, outcome: AckOutcome,
         records: list[str], decision: str | None, intent: Intent | None, rationale: str | None,
         note: str | None = None) -> str:
    """One finished apply run, written the way the wrapper writes it (review, run_started, run_finished)."""
    run_id = new_id("run")
    addrs = sorted({db.get_record(r)["resource_address"] for r in records})
    fp = "sha256:" + new_id("plan").split("_")[1] * 6
    started, finished = at, at + timedelta(minutes=3)
    started_run = outcome not in (AckOutcome.CANCELLED, AckOutcome.NO_CHANGES)
    db.insert_apply_run({
        "id": run_id, "environment": env, "generated_at": ts(at - timedelta(minutes=2)),
        "plan_fingerprint": fp,
        "proposed_changes_json": json.dumps([{"resource_address": a, "resource_type": "digitalocean_firewall",
                                              "actions": ["update"], "summary": "update inbound_rule"} for a in addrs]),
        "warnings_json": json.dumps([{"record_id": r, "resource_address": db.get_record(r)["resource_address"],
                                      "message": "This apply would reverse a manual change.", "reason": None,
                                      "reporter": None, "intent": "unset",
                                      "first_detected_at": db.get_record(r)["first_detected_at"]} for r in records]),
        "check_status": CheckStatus.CURRENT.value, "coverage_note": "Authored demo history.",
        "ack_outcome": AckOutcome.PENDING.value, "ack_note": None, "completed_at": None,
        "reviewer": reviewer, "reviewer_assurance": assurance})
    with db.tx() as conn:
        for rid in records:
            if intent is not None:
                db.update_record(rid, {"intent": intent.value, "intent_updated_at": ts(started),
                                       "intent_note": rationale}, conn)
            _event(db, conn, env, "review", started, record_id=rid, run_id=run_id, actor=reviewer,
                   assurance=assurance, data={"decision": decision, "plan_fingerprint": fp,
                                              "rationale": rationale, "source": "wrapper"})
        fields: dict[str, Any] = {"ack_outcome": outcome.value, "ack_note": note,
                                  "check_status": CheckStatus.CURRENT.value, "completed_at": ts(finished),
                                  "plan_fingerprint": fp}
        if started_run:
            fields.update(started_at=ts(started), reviewer=reviewer, reviewer_assurance=assurance,
                          rationale=rationale)
            _event(db, conn, env, "run_started", started, run_id=run_id, actor=reviewer, assurance=assurance,
                   data={"decision": decision, "plan_fingerprint": fp, "record_ids": records})
        db.update_apply_run(run_id, fields, conn)
        _event(db, conn, env, "run_finished", finished, run_id=run_id, actor=reviewer, assurance=assurance,
               data={"outcome": outcome.value, "applied": outcome.value.endswith("applied"), "note": note})
    return run_id


def _resolve(db: Database, rid: str, at: datetime) -> None:
    db.update_record(rid, {"resolution": Resolution.RESOLVED.value,
                           "resolution_reason": ResolutionReason.VERIFIED_ALIGNED.value,
                           "resolved_at": ts(at), "last_check_status": CheckStatus.CURRENT.value,
                           "last_check_at": ts(at)})


def seed_history(db: Database, environment: str, *, now: datetime | None = None) -> Summary:
    if not environment.endswith("-authored"):
        raise SeedHistoryRefused(
            f"refusing environment {environment!r}: authored history must use an '<env>-authored' "
            "environment so it can never merge into live records")
    if any(MARKER in (s["detail"] or "") for s in db.list_scans() if s["environment"] == environment):
        raise SeedHistoryRefused("authored history is already seeded here; refusing to duplicate it")

    now = now or utcnow()
    day = lambda d, h, m=0: now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=d) + timedelta(hours=h, minutes=m)  # noqa: E731

    def detect(address: str, before: list[str], after: list[str], at: datetime) -> str:
        out = service.ingest_refresh_plan(db, environment, _plan(address, before, after),
                                          evidence_source="authored-fixture", now=at)
        assert out.new_ids, f"seed plan for {address} produced no record: {out.errors}"
        return out.new_ids[0]

    def web_report(rid: str, who: str, reason: str, intent: Intent, at: datetime) -> None:
        service.report(db, rid, ReportIn(reporter=who, reason=reason, intent=intent), now=at, source="web")

    def verified_report(rid: str, who: str, email: str, reason: str, intent: Intent, at: datetime) -> None:
        service.report(db, rid, ReportIn(reporter=who, reason=reason, intent=intent), now=at, source="web",
                       account=email, account_name=who, assurance=VERIFIED)

    resolved: list[tuple[str, datetime]] = []
    open_ids: list[str] = []

    # 6 days ago: db opened for a contractor; reported, reverted, resolved.
    a = detect("digitalocean_firewall.db", [], ["5432"], day(6, 9, 20))
    verified_report(a, "Priya", "priya@example.com", "contractor needed temporary DB access for the migration",
                    Intent.REVERT, day(6, 9, 48))
    _run(db, environment, at=day(6, 11, 5), reviewer="priya", assurance=SELF_REPORTED,
         outcome=AckOutcome.REVERTED_APPLIED, records=[a], decision="revert", intent=Intent.REVERT,
         rationale="migration finished, closing the port")
    resolved.append((a, day(6, 11, 30)))

    # 5 days ago: web port moved 8080 -> 8443; kept; aligned in config two days later.
    b = detect("digitalocean_firewall.web", ["8080"], ["8443"], day(5, 14, 10))
    web_report(b, "Paul", "payment webhook blocked, opened 8443", Intent.KEEP, day(5, 14, 32))
    _run(db, environment, at=day(5, 16, 0), reviewer="dcc", assurance=OS_USER_ASSURANCE,
         outcome=AckOutcome.KEPT, records=[b], decision="keep", intent=Intent.KEEP,
         rationale="webhook provider only supports 8443")
    resolved.append((b, day(3, 10, 0)))

    # 4 days ago: cache port removed; kept.
    c = detect("digitalocean_firewall.cache", ["6379"], [], day(4, 8, 45))
    web_report(c, "Sam", "removed the unused Redis port after the cache moved internal", Intent.KEEP, day(4, 9, 10))
    _run(db, environment, at=day(4, 10, 0), reviewer="sam", assurance=SELF_REPORTED,
         outcome=AckOutcome.KEPT, records=[c], decision="keep", intent=Intent.KEEP,
         rationale="port is no longer needed")
    resolved.append((c, day(3, 9, 0)))

    # 3 days ago: api metrics port; reverted.
    d = detect("digitalocean_firewall.api", [], ["9090"], day(3, 13, 25))
    verified_report(d, "Priya", "priya@example.com", "metrics scraper needed 9090 during a load test",
                    Intent.REVERT, day(3, 13, 50))
    _run(db, environment, at=day(3, 15, 30), reviewer="dcc", assurance=OS_USER_ASSURANCE,
         outcome=AckOutcome.REVERTED_APPLIED, records=[d], decision="revert", intent=Intent.REVERT,
         rationale="load test is over")
    resolved.append((d, day(3, 16, 0)))

    # 2 days ago: a routine apply with nothing to warn about.
    _run(db, environment, at=day(2, 9, 0), reviewer="dcc", assurance=OS_USER_ASSURANCE,
         outcome=AckOutcome.APPLIED_NO_WARNINGS, records=[], decision="apply", intent=None, rationale=None)

    # 2 days ago evening: web debug port; Sam is unsure, the apply is cancelled; still open.
    e = detect("digitalocean_firewall.web", [], ["3000"], day(2, 17, 40))
    web_report(e, "Sam", "debugging the staging frontend, will close it tomorrow", Intent.UNSURE, day(2, 17, 55))
    _run(db, environment, at=day(2, 18, 30), reviewer="dcc", assurance=OS_USER_ASSURANCE,
         outcome=AckOutcome.CANCELLED, records=[e], decision="cancel", intent=None,
         rationale="waiting for Sam to confirm", note="cancelled at review")
    open_ids.append(e)

    # yesterday: db port with no explanation yet.
    f = detect("digitalocean_firewall.db", [], ["5433"], day(1, 11, 15))
    open_ids.append(f)

    # today: cache exporter, explained and deferred.
    g = detect("digitalocean_firewall.cache", [], ["9100"], now - timedelta(hours=3))
    verified_report(g, "Priya", "priya@example.com", "node exporter for the new dashboard", Intent.DEFER,
                    now - timedelta(hours=2))
    open_ids.append(g)

    for rid, at in resolved:
        _resolve(db, rid, at)
    fresh = now - timedelta(hours=1)
    for rid in open_ids:
        db.update_record(rid, {"last_detected_at": ts(fresh), "last_check_status": CheckStatus.CURRENT.value,
                               "last_check_at": ts(fresh)})

    # Scans through the week (the detections above already recorded theirs); the marker makes a rerun refuse.
    scans = 0
    with db.tx() as conn:
        for hours in range(6, 24 * 7, 12):
            at = now - timedelta(hours=hours)
            db.insert_scan(new_id("scan"), environment, ts(at), "ok",
                           json.dumps({"new": 0, "seen": 0, "unsupported": [], "source": MARKER}), conn)
            scans += 1

    rows = db.list_records(environment=environment)
    return Summary(
        records=len(rows),
        open=len([r for r in rows if r["resolution"] == "open"]),
        needs_reason=len([r for r in rows if r["resolution"] == "open" and not r["reason"]]),
        runs=len(db.list_all_apply_runs()),
        scans=scans,
    )
