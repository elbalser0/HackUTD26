"""R9 admin log over the append-only history: server-side authorization, a
team-wide event log with the PRD filters, and the linked change -> explanation ->
decision -> run timeline.

Sources: the `events` table (reports, decisions, wrapper reviews, run start/finish),
plus `records` (detection and resolution times) and `apply_runs` (to surface runs
that never recorded a completion). Nothing is invented: what the data cannot show
is reported in `limitations` / `gaps`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from helpers import ENV, FakeRunner, Script, load, make_tf, memdb, refresh_other_address

from breakglass import service, wrapper
from breakglass.api import create_app
from breakglass.db import Database, new_id, ts
from breakglass.models import DecisionIn, ReportIn, utcnow
from breakglass.wrapper import OS_USER_ASSURANCE, SELF_REPORTED, guarded_apply

TOKEN = "test-admin-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
T0 = datetime(2026, 11, 8, 3, 30, 12, tzinfo=timezone.utc)
APPLIED = {"applied_no_warnings", "reverted_applied", "override_applied", "unverified_bypass_applied"}


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("BG_ADMIN_TOKEN", "BG_CORS_ORIGINS", "BG_TF_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(wrapper.getpass, "getuser", lambda: "osuser")


@pytest.fixture
def client(db):
    with TestClient(create_app(db=db, allowed_hosts=["testserver"], admin_token=TOKEN)) as c:
        yield c


def seed(db, plan="refresh_drift_8443", now=None):
    p = load(plan) if isinstance(plan, str) else plan
    now = now or at(0)
    return service.ingest_refresh_plan(db, ENV, p, evidence_source="authored-fixture", now=now).new_ids[0]


def recent_record(db, plan="refresh_drift_8443", reporter="Paul", reason="payment webhook blocked"):
    """A record detected an hour ago, so wall-clock wrapper events sort after it."""
    rid = seed(db, plan, now=utcnow() - timedelta(hours=1))
    if reason:
        service.report(db, rid, ReportIn(reporter=reporter, reason=reason))
    return rid


def add_event(db, kind, *, when, record_id=None, run_id=None, actor=None, assurance="self-reported", data=None):
    db.insert_event({"id": new_id("evt"), "environment": ENV, "record_id": record_id, "run_id": run_id,
                     "kind": kind, "actor": actor, "actor_assurance": assurance,
                     "data_json": json.dumps(data or {}), "created_at": ts(when)})


def add_run_row(db, *, generated, outcome="pending", completed=None, started=None, rec_ids=(),
                reviewer=None, assurance=None, run_id=None):
    run_id = run_id or new_id("run")
    addrs = sorted({db.get_record(r)["resource_address"] for r in rec_ids})
    db.insert_apply_run({
        "id": run_id, "environment": ENV, "generated_at": ts(generated), "plan_fingerprint": "sha256:abc",
        "proposed_changes_json": json.dumps([{"resource_address": a, "resource_type": "digitalocean_firewall",
                                              "actions": ["update"], "summary": "s"} for a in addrs]),
        "warnings_json": json.dumps([{"record_id": r, "resource_address": db.get_record(r)["resource_address"],
                                      "message": "m", "reason": None, "reporter": None, "intent": "unset",
                                      "first_detected_at": ts(T0)} for r in rec_ids]),
        "check_status": "current", "coverage_note": "c", "ack_outcome": "pending", "ack_note": None,
        "completed_at": None, "reviewer": reviewer, "reviewer_assurance": assurance})
    fields = {"ack_outcome": outcome}
    if completed:
        fields["completed_at"] = ts(completed)
    if started:
        fields["started_at"] = ts(started)
    db.update_apply_run(run_id, fields)
    return run_id


def wrapper_run(db, tmp_path, *answers, reviewer=None, **runner_kw):
    s = Script(*answers)
    return guarded_apply(db, make_tf(tmp_path, FakeRunner(**runner_kw)), ENV, prompt=s.prompt, out=s.out,
                         reviewer=reviewer)


def log(client, **params):
    r = client.get("/api/admin/log", params=params, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def timeline(client, rid):
    r = client.get(f"/api/admin/records/{rid}/timeline", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def types(body):
    return [e["type"] for e in body["events"]]


# ---------------------------------------------------------------- authorization

ADMIN_PATHS = ["/api/admin/log", "/api/admin/records/rec_x/timeline"]


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_no_token_configured_fails_closed(db, path):
    with TestClient(create_app(db=db, allowed_hosts=["testserver"])) as c:
        assert c.get(path, headers=AUTH).status_code == 403
        assert c.get(path).status_code == 403


def test_blank_configured_token_is_not_a_token(db):
    with TestClient(create_app(db=db, allowed_hosts=["testserver"], admin_token="")) as c:
        assert c.get("/api/admin/log", headers={"Authorization": "Bearer "}).status_code == 403


@pytest.mark.parametrize("path", ADMIN_PATHS)
@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": "Bearer " + TOKEN[:-1]},
    {"Authorization": "Bearer " + TOKEN + "x"},
    {"Authorization": TOKEN},
    {"Authorization": "Basic " + TOKEN},
    {"Authorization": "Bearer"},
], ids=["missing", "wrong", "prefix", "suffix", "no-scheme", "basic", "empty-bearer"])
def test_bad_credentials_rejected(client, path, headers):
    r = client.get(path, headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].lower().startswith("bearer")
    assert r.json()["error"]["code"] == "unauthorized"
    assert TOKEN not in r.text


def test_token_in_query_string_is_not_accepted(client):
    assert client.get("/api/admin/log", params={"token": TOKEN}).status_code == 401
    assert client.get("/api/admin/log", params={"access_token": TOKEN}).status_code == 401


def test_correct_token_allowed(client):
    assert client.get("/api/admin/log", headers=AUTH).status_code == 200


def test_unauthorized_response_leaks_no_log_data(client, db):
    seed(db)
    r = client.get("/api/admin/log")
    assert r.status_code == 401
    assert "digitalocean_firewall" not in r.text and "events" not in r.json()


def test_token_comes_from_environment_when_not_passed(db, monkeypatch):
    monkeypatch.setenv("BG_ADMIN_TOKEN", TOKEN)
    with TestClient(create_app(db=db, allowed_hosts=["testserver"])) as c:
        assert c.get("/api/admin/log", headers=AUTH).status_code == 200
        assert c.get("/api/admin/log").status_code == 401


def test_cors_preflight_allows_authorization_header(db, monkeypatch):
    monkeypatch.setenv("BG_CORS_ORIGINS", "http://localhost:5173")
    with TestClient(create_app(db=db, allowed_hosts=["testserver"], admin_token=TOKEN)) as c:
        r = c.options("/api/admin/log", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization"})
        assert r.status_code == 200
        assert "authorization" in r.headers["access-control-allow-headers"].lower()


def test_admin_routes_are_read_only(client):
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/admin/log", headers=AUTH).status_code == 405


def test_existing_annotate_endpoints_unchanged_and_still_open(client, db):
    """Documents current behavior: only /api/admin/* is gated. The pre-existing
    records/apply-runs endpoints remain unauthenticated (open question, see docs)."""
    seed(db)
    assert client.get("/api/records").status_code == 200
    assert client.get("/api/apply-runs").status_code == 200


# ---------------------------------------------------------------- log content

def test_empty_database_returns_empty_log(client):
    body = log(client)
    assert body["events"] == [] and body["total_matching"] == 0


def test_detected_change_without_reason_is_visible_as_missing(client, db):
    rid = seed(db)
    body = log(client)
    assert types(body) == ["change_detected"]
    e = body["events"][0]
    assert e["record_ids"] == [rid] and e["resource_addresses"] == [db.get_record(rid)["resource_address"]]
    assert e["actor"] is None and e["run_id"] is None and e["outcome"] is None
    assert e["at"].startswith("2026-11-08T03:30:12")


def test_every_report_is_kept_not_just_the_latest(client, db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="first guess"), now=at(5))
    service.report(db, rid, ReportIn(reporter="Quinn", reason="corrected reason"), now=at(7))
    ex = [e for e in log(client)["events"] if e["type"] == "explained"]
    assert [(e["actor"], e["detail"]) for e in ex] == [("Quinn", "corrected reason"), ("Paul", "first guess")]
    assert all(e["actor_assurance"] == "self-reported" for e in ex)


def test_decision_event_carries_intent_note_and_actor(client, db):
    rid = seed(db)
    service.decide(db, rid, DecisionIn(intent="keep", note="fix in code"), now=at(9), actor="Dana")
    de = next(e for e in log(client)["events"] if e["type"] == "decision")
    assert de["actor"] == "Dana" and "keep" in de["detail"] and "fix in code" in de["detail"]


def test_intent_given_while_reporting_is_also_a_decision(client, db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="r", intent="defer"), now=at(5))
    body = timeline(client, rid)
    assert types(body) == ["change_detected", "explained", "decision"]
    assert "no_decision_recorded" not in {g["code"] for g in body["gaps"]}
    dec = next(e for e in body["events"] if e["type"] == "decision")
    assert dec["actor"] == "Paul" and "defer" in dec["detail"]
    assert "predates event history" not in dec["detail"]  # real event, not the pre-history fallback


def test_wrapper_review_is_linked_to_run_plan_and_reviewer(client, db, tmp_path):
    rid = recent_record(db)
    res = wrapper_run(db, tmp_path, "r", "revert", "webhook fixed upstream", reviewer="Dana")
    body = log(client)
    rv = next(e for e in body["events"] if e["type"] == "review")
    assert rv["run_id"] == res.run_id and rv["record_ids"] == [rid]
    assert rv["actor"] == "Dana" and rv["actor_assurance"] == SELF_REPORTED
    assert "revert" in rv["detail"] and "webhook fixed upstream" in rv["detail"]
    assert rv["plan_fingerprint"] == db.get_apply_run(res.run_id)["plan_fingerprint"] != None  # noqa: E711
    started = next(e for e in body["events"] if e["type"] == "run_started")
    assert started["plan_fingerprint"] == rv["plan_fingerprint"]  # executed plan == reviewed plan
    fin = next(e for e in body["events"] if e["type"] == "run_finished")
    assert fin["outcome"] == "reverted_applied" and fin["run_id"] == res.run_id


def test_default_reviewer_is_labelled_unverified_os_user(client, db, tmp_path):
    recent_record(db)
    wrapper_run(db, tmp_path, "k", "test rationale")
    rv = next(e for e in log(client)["events"] if e["type"] == "review")
    assert rv["actor"] == "osuser" and rv["actor_assurance"] == OS_USER_ASSURANCE
    assert "not verified" in rv["actor_assurance"]


def test_log_is_newest_first_and_limit_applies(client, db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="r"), now=at(5))
    service.decide(db, rid, DecisionIn(intent="defer"), now=at(9))
    body = log(client)
    ats = [e["at"] for e in body["events"]]
    assert ats == sorted(ats, reverse=True)
    small = log(client, limit=1)
    assert len(small["events"]) == 1 and small["total_matching"] == 3
    assert small["events"][0]["type"] == "decision"


@pytest.mark.parametrize("limit", [0, -1, 501, "abc"])
def test_invalid_limit_rejected(client, limit):
    assert client.get("/api/admin/log", params={"limit": limit}, headers=AUTH).status_code == 422


def test_resolved_record_history_remains(client, db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="r"), now=at(5))
    db.update_record(rid, {"resolution": "resolved", "resolution_reason": "verified_aligned",
                           "resolved_at": ts(at(30))})
    body = log(client)
    assert set(types(body)) == {"change_detected", "explained", "resolved"}
    res = next(e for e in body["events"] if e["type"] == "resolved")
    assert "verified_aligned" in res["detail"] and res["at"].startswith("2026-11-08T04:00:12")


def test_pre_history_record_columns_still_show_explanation_without_duplicates(client, db):
    """Records written before the events table existed have reason/intent columns but no
    events. They must still appear; and a record WITH events must not be doubled."""
    legacy = seed(db)
    db.update_record(legacy, {"reporter": "Old", "reason": "from before", "reported_at": ts(at(2)),
                              "intent": "keep", "intent_updated_at": ts(at(3))})
    modern = seed(db, plan=refresh_other_address(), now=at(1))
    service.report(db, modern, ReportIn(reporter="New", reason="with events"), now=at(4))
    legacy_t = timeline(client, legacy)
    assert types(legacy_t) == ["change_detected", "explained", "decision"]
    assert "predates event history" in legacy_t["events"][1]["detail"]
    modern_t = timeline(client, modern)
    assert types(modern_t).count("explained") == 1


# ---------------------------------------------------------------- filters

def two_engineers(db):
    a = seed(db)
    b = seed(db, plan=refresh_other_address(), now=at(1))
    service.report(db, a, ReportIn(reporter="Paul", reason="a reason"), now=at(5))
    service.report(db, b, ReportIn(reporter="Quinn", reason="b reason"), now=at(6))
    return a, b


def test_engineer_filter_matches_actor_case_insensitively(client, db):
    a, b = two_engineers(db)
    body = log(client, engineer="paul")
    assert types(body) == ["explained"] and body["events"][0]["record_ids"] == [a]
    assert [e["record_ids"] for e in log(client, engineer="QUINN")["events"]] == [[b]]


def test_engineer_filter_is_exact_not_substring_and_unknown_is_empty(client, db):
    two_engineers(db)
    assert log(client, engineer="Pau")["events"] == []
    assert log(client, engineer="nobody")["events"] == []


def test_engineer_filter_includes_wrapper_reviewer_activity(client, db, tmp_path):
    recent_record(db, reporter="Paul")
    res = wrapper_run(db, tmp_path, "r", "revert", "why", reviewer="Dana")
    body = log(client, engineer="Dana")
    assert {"review", "run_started", "run_finished"} <= set(types(body))
    assert all(e["actor"] == "Dana" and e["run_id"] == res.run_id for e in body["events"])
    assert "explained" not in types(body)


def test_resource_filter_exact_for_record_and_run_events(client, db):
    a, b = two_engineers(db)
    addr_a, addr_b = (db.get_record(x)["resource_address"] for x in (a, b))
    assert addr_a != addr_b
    run_b = add_run_row(db, generated=at(10), rec_ids=[b], outcome="kept", completed=at(11))
    add_event(db, "run_finished", when=at(11), run_id=run_b, actor="Dana", data={"outcome": "kept"})
    body = log(client, resource=addr_b)
    assert body["events"] and all(addr_b in e["resource_addresses"] for e in body["events"])
    assert run_b in {e["run_id"] for e in body["events"]}
    assert a not in {r for e in body["events"] for r in e["record_ids"]}
    assert log(client, resource="digitalocean_firewall.none")["events"] == []
    assert log(client, resource="digitalocean_firewall")["events"] == []  # exact, not substring


def test_time_filter_inclusive_bounds(client, db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="r"), now=at(5))
    service.decide(db, rid, DecisionIn(intent="keep"), now=at(9))
    assert types(log(client, since=ts(at(5)), until=ts(at(5)))) == ["explained"]
    assert types(log(client, since=ts(at(6)))) == ["decision"]
    assert types(log(client, until=ts(at(4)))) == ["change_detected"]


@pytest.mark.parametrize("bad", ["2026-11-08T03:30:12", "yesterday", "2026-13-40T00:00:00Z"])
def test_time_filter_rejects_naive_or_garbage(client, bad):
    for p in ("since", "until"):
        assert client.get("/api/admin/log", params={p: bad}, headers=AUTH).status_code == 422


def test_outcome_filter_selects_run_results_only(client, db):
    a, b = two_engineers(db)
    r1 = add_run_row(db, generated=at(10), rec_ids=[a], outcome="kept", completed=at(11))
    r2 = add_run_row(db, generated=at(12), rec_ids=[b], outcome="cancelled", completed=at(13))
    add_event(db, "run_finished", when=at(11), run_id=r1, actor="D", data={"outcome": "kept"})
    add_event(db, "run_finished", when=at(13), run_id=r2, actor="D", data={"outcome": "cancelled"})
    body = log(client, outcome="kept")
    assert [e["run_id"] for e in body["events"]] == [r1] and types(body) == ["run_finished"]


def test_outcome_filter_rejects_unknown_value(client):
    for bad in ("success", "pending", "running"):
        assert client.get("/api/admin/log", params={"outcome": bad}, headers=AUTH).status_code == 422


def test_filters_combine_with_and(client, db):
    a, b = two_engineers(db)
    for rid, mins in ((a, 10), (b, 12)):
        run = add_run_row(db, generated=at(mins), rec_ids=[rid], outcome="kept", completed=at(mins + 1))
        add_event(db, "run_finished", when=at(mins + 1), run_id=run, actor="Dana", data={"outcome": "kept"})
    body = log(client, engineer="Dana", resource=db.get_record(b)["resource_address"], outcome="kept")
    assert len(body["events"]) == 1 and body["events"][0]["record_ids"] == [b]
    assert log(client, engineer="Quinn", outcome="kept")["events"] == []


# ---------------------------------------------------------------- missing / interrupted outcomes

def test_run_that_never_recorded_completion_is_unknown_never_success(client, db):
    rid = seed(db)
    stuck = add_run_row(db, generated=at(10), started=at(10), rec_ids=[rid], outcome="running",
                        reviewer="Dana", assurance=SELF_REPORTED)
    ev = next(e for e in log(client)["events"] if e["run_id"] == stuck and e["outcome"])
    assert ev["type"] == "run_unfinished" and ev["outcome"] == "unknown"
    assert ev["outcome"] not in APPLIED and ev["actor"] == "Dana"
    assert "no completion" in ev["detail"].lower()


def test_never_reviewed_pending_run_is_also_unknown(client, db):
    stuck = add_run_row(db, generated=at(10), outcome="pending")
    ev = next(e for e in log(client)["events"] if e["run_id"] == stuck)
    assert ev["outcome"] == "unknown" and ev["type"] == "run_unfinished"


def test_outcome_filter_finds_both_derived_and_recorded_unknown(client, db, tmp_path):
    recent_record(db)
    stuck = add_run_row(db, generated=utcnow() - timedelta(minutes=30), outcome="running")
    wrapper_run(db, tmp_path, "c")  # next apply marks `stuck` unknown and appends a system event
    fresh = add_run_row(db, generated=utcnow() - timedelta(minutes=5), outcome="running")
    body = log(client, outcome="unknown")
    got = {(e["run_id"], e["type"]) for e in body["events"]}
    assert (stuck, "run_finished") in got and (fresh, "run_unfinished") in got


def test_interrupted_apply_is_failed_not_nothing_applied(client, db, tmp_path):
    recent_record(db)
    s = Script("r", "revert", "why")
    tf = make_tf(tmp_path, FakeRunner())

    def interrupted(name):
        raise KeyboardInterrupt
    tf.apply_saved = interrupted
    res = guarded_apply(db, tf, ENV, prompt=s.prompt, out=s.out)
    fin = next(e for e in log(client)["events"] if e["type"] == "run_finished" and e["run_id"] == res.run_id)
    assert fin["outcome"] == "failed" and fin["outcome"] not in APPLIED
    assert "interrupted" in fin["detail"].lower() or "unknown" in fin["detail"].lower()


def test_run_with_completion_but_no_events_still_shown_from_run_record(client, db):
    done = add_run_row(db, generated=at(10), outcome="kept", completed=at(11), reviewer="Dana",
                       assurance=SELF_REPORTED)
    ev = next(e for e in log(client)["events"] if e["run_id"] == done)
    assert ev["type"] == "run_finished" and ev["outcome"] == "kept" and ev["at"].startswith("2026-11-08T03:41")
    assert "predates event history" in ev["detail"]


def test_run_without_linked_records_still_in_team_log(client, db):
    rr = add_run_row(db, generated=at(10), outcome="no_changes", completed=at(11))
    add_event(db, "run_finished", when=at(11), run_id=rr, actor="D", data={"outcome": "no_changes"})
    ev = next(e for e in log(client)["events"] if e["run_id"] == rr)
    assert ev["record_ids"] == [] and ev["outcome"] == "no_changes"


def test_limitations_are_declared(client, db):
    seed(db)
    text = " ".join(log(client)["limitations"]).lower()
    assert "not verified" in text or "unverified" in text  # reviewer/actor identity
    assert "self-reported" in text                          # reporter
    assert "shared" in text                                 # one admin token, no per-admin identity
    assert "unknown" in text                                # unknown != failed


# ---------------------------------------------------------------- timeline

def test_timeline_links_change_explanation_decision_run_in_order(client, db, tmp_path):
    rid = recent_record(db)
    res = wrapper_run(db, tmp_path, "r", "revert", "webhook fixed", reviewer="Dana")
    db.update_record(rid, {"resolution": "resolved", "resolution_reason": "verified_aligned",
                           "resolved_at": ts(utcnow() + timedelta(minutes=1))})
    body = timeline(client, rid)
    assert body["record_id"] == rid
    assert types(body) == ["change_detected", "explained", "review", "run_started", "run_finished", "resolved"]
    ats = [e["at"] for e in body["events"]]
    assert ats == sorted(ats)
    assert {e["run_id"] for e in body["events"] if e["run_id"]} == {res.run_id}
    assert next(e for e in body["events"] if e["type"] == "run_finished")["outcome"] == "reverted_applied"
    assert body["gaps"] == []


def test_timeline_excludes_runs_linked_only_to_other_records(client, db):
    a, b = two_engineers(db)
    mine = add_run_row(db, generated=at(10), rec_ids=[a], outcome="kept", completed=at(11))
    theirs = add_run_row(db, generated=at(12), rec_ids=[b], outcome="cancelled", completed=at(13))
    both = add_run_row(db, generated=at(14), rec_ids=[a, b], outcome="deferred", completed=at(15))
    for run, mins, out in ((mine, 11, "kept"), (theirs, 13, "cancelled"), (both, 15, "deferred")):
        add_event(db, "run_finished", when=at(mins), run_id=run, actor="D", data={"outcome": out})
    body = timeline(client, a)
    assert [e["run_id"] for e in body["events"] if e["type"] == "run_finished"] == [mine, both]
    assert theirs not in {e["run_id"] for e in body["events"]}


def test_timeline_reports_missing_reason_decision_and_run(client, db):
    rid = seed(db)
    body = timeline(client, rid)
    assert types(body) == ["change_detected"]
    assert {"no_reason_recorded", "no_decision_recorded", "no_run_linked"} <= {g["code"] for g in body["gaps"]}


def test_timeline_flags_unknown_run_outcome(client, db):
    rid = seed(db)
    rr = add_run_row(db, generated=at(10), started=at(10), rec_ids=[rid], outcome="running")
    body = timeline(client, rid)
    gap = next(g for g in body["gaps"] if g["code"] == "run_outcome_unknown")
    assert gap["run_id"] == rr


def test_timeline_unknown_record_is_404(client):
    r = client.get("/api/admin/records/rec_nope/timeline", headers=AUTH)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_timeline_with_multiple_runs_over_time(client, db):
    rid = seed(db)
    r1 = add_run_row(db, generated=at(10), rec_ids=[rid], outcome="cancelled", completed=at(11))
    r2 = add_run_row(db, generated=at(20), rec_ids=[rid], outcome="override_applied", completed=at(22))
    add_event(db, "run_finished", when=at(11), run_id=r1, actor="D", data={"outcome": "cancelled"})
    add_event(db, "run_finished", when=at(22), run_id=r2, actor="D", data={"outcome": "override_applied"})
    body = timeline(client, rid)
    assert [e["run_id"] for e in body["events"] if e["type"] == "run_finished"] == [r1, r2]


# ---------------------------------------------------------------- persistence

def test_history_survives_restart_and_closure(tmp_path):
    path = tmp_path / "bg.db"
    d1 = Database(path)
    rid = recent_record(d1)
    guarded_apply(d1, make_tf(tmp_path, FakeRunner()), ENV, prompt=Script("r", "revert", "why").prompt,
                  out=Script().out, reviewer="Dana")
    d1.update_record(rid, {"resolution": "resolved", "resolution_reason": "verified_aligned",
                           "resolved_at": ts(utcnow() + timedelta(minutes=1))})
    with TestClient(create_app(db=d1, allowed_hosts=["testserver"], admin_token=TOKEN)) as c:
        before = c.get("/api/admin/log", headers=AUTH).json()
    d1.close()
    d2 = Database(path)  # new process, same file
    try:
        with TestClient(create_app(db=d2, allowed_hosts=["testserver"], admin_token=TOKEN)) as c:
            after = c.get("/api/admin/log", headers=AUTH).json()
    finally:
        d2.close()
    assert after["events"] == before["events"]
    assert {"change_detected", "explained", "review", "run_started", "run_finished", "resolved"} <= {
        e["type"] for e in after["events"]}
