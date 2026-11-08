"""Append-only history (R6/R10), decision persisted before execution (R7),
unknown outcomes (R8) and the additive apply_runs migration."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from helpers import ENV, FakeRunner, Script, load, make_tf, memdb

from breakglass import service, wrapper
from breakglass.api import apply_run_out, create_app
from breakglass.db import Database, new_id, ts
from breakglass.models import DecisionIn, Intent, ReportIn, utcnow
from breakglass.wrapper import OS_USER_ASSURANCE, SELF_REPORTED, guarded_apply

T0 = datetime(2026, 11, 8, 3, 30, 12, tzinfo=timezone.utc)


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.delenv("BG_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("BG_TF_DIR", raising=False)
    with TestClient(create_app(db=db, allowed_hosts=["testserver"])) as c:
        yield c


@pytest.fixture(autouse=True)
def os_user(monkeypatch):
    monkeypatch.setattr(wrapper.getpass, "getuser", lambda: "osuser")


def open_record(db, reason=True):
    rid = service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443"),
                                      evidence_source="authored-fixture", now=T0).new_ids[0]
    if reason:
        service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    return rid


def make(tmp_path, **runner_kw):
    runner = FakeRunner(**runner_kw)
    return runner, make_tf(tmp_path, runner)


def run(db, tmp_path, script, reviewer=None, **runner_kw):
    runner, tf = make(tmp_path, **runner_kw)
    res = guarded_apply(db, tf, ENV, prompt=script.prompt, out=script.out, reviewer=reviewer)
    return res, runner, tf


def events(db, **kw):
    return [service.event_out(e) for e in db.list_events(**kw)]


def reviews(db, rid):
    return [e for e in events(db, record_id=rid) if e.kind == "review"]


def insert_run(db, environment=ENV, ack_outcome="running", completed_at=None):
    run_id = new_id("run")
    db.insert_apply_run({
        "id": run_id, "environment": environment, "generated_at": ts(utcnow()),
        "plan_fingerprint": "sha256:abc", "proposed_changes_json": "[]", "warnings_json": "[]",
        "check_status": "current", "coverage_note": "note", "ack_outcome": "pending",
        "ack_note": None, "completed_at": None,
    })
    db.update_apply_run(run_id, {"ack_outcome": ack_outcome, "completed_at": completed_at,
                                 "started_at": ts(utcnow())})
    return run_id


# ---------------------------------------------------------------------------
# R6/R10 append-only
# ---------------------------------------------------------------------------

def test_two_reports_keep_both_events_in_order(db, client):
    rid = open_record(db, reason=False)
    r1 = client.post(f"/api/records/{rid}/report", json={"reporter": "Paul", "reason": "first reason"})
    r2 = client.post(f"/api/records/{rid}/report", json={"reporter": "Ana", "reason": "second reason"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert client.get(f"/api/records/{rid}").json()["reason"] == "second reason"

    resp = client.get(f"/api/records/{rid}/events")
    assert resp.status_code == 200
    evs = [e for e in resp.json()["events"] if e["kind"] == "report"]
    assert [e["data"]["reason"] for e in evs] == ["first reason", "second reason"]
    assert [e["actor"] for e in evs] == ["Paul", "Ana"]
    assert all(e["actor_assurance"] == "self-reported" for e in evs)
    assert all(e["data"]["source"] == "web" for e in evs)
    assert all(e["record_id"] == rid and e["run_id"] is None for e in evs)


def test_decide_via_api_appends_decision_event(db, client):
    rid = open_record(db)
    resp = client.post(f"/api/records/{rid}/decision", json={"intent": "keep", "note": "leave it for now"})
    assert resp.status_code == 200
    assert resp.json()["resolution"] == "open" and resp.json()["intent"] == "keep"
    evs = [e for e in client.get(f"/api/records/{rid}/events").json()["events"] if e["kind"] == "decision"]
    assert len(evs) == 1
    assert evs[0]["data"]["intent"] == "keep" and evs[0]["data"]["note"] == "leave it for now"
    assert evs[0]["data"]["source"] == "web"
    assert db.get_record(rid)["resolution"] == "open"


def test_cli_sourced_report_and_decide_store_source_cli(db):
    rid = open_record(db, reason=False)
    service.report(db, rid, ReportIn(reporter="Paul", reason="cli reason"), source="cli")
    service.decide(db, rid, DecisionIn(intent=Intent.DEFER, note="later"), source="cli", actor="Paul")
    evs = events(db, record_id=rid)
    assert [(e.kind, e.data["source"]) for e in evs] == [("report", "cli"), ("decision", "cli")]
    assert evs[1].actor == "Paul" and evs[1].actor_assurance == "self-reported"


def test_events_endpoints_404_for_unknown_ids(client):
    r = client.get("/api/records/rec_nope/events")
    assert r.status_code == 404 and r.json()["error"]["code"]
    r = client.get("/api/apply-runs/run_nope/events")
    assert r.status_code == 404 and r.json()["error"]["code"]


def test_reset_clears_events(db):
    rid = open_record(db)
    assert db.list_events(record_id=rid)
    db.reset()
    assert db.list_events() == []


# ---------------------------------------------------------------------------
# R7 decision persisted before execution
# ---------------------------------------------------------------------------

def spy_apply(db, tf, rid):
    """Wrap tf.apply_saved to snapshot the DB at the moment terraform would run."""
    seen = {}
    orig = tf.apply_saved

    def wrapped(plan_name):
        run = db.list_apply_runs(1)[0]
        seen["run"] = dict(run)
        seen["record_events"] = [service.event_out(e) for e in db.list_events(record_id=rid)]
        seen["run_events"] = [service.event_out(e) for e in db.list_events(run_id=run["id"])]
        return orig(plan_name)

    tf.apply_saved = wrapped
    return seen


def test_revert_review_and_running_state_persisted_before_apply(db, tmp_path):
    rid = open_record(db)
    runner, tf = make(tmp_path)
    seen = spy_apply(db, tf, rid)
    s = Script("r", "revert", "webhook fixed upstream")
    res = guarded_apply(db, tf, ENV, prompt=s.prompt, out=s.out, reviewer="Dana")
    assert len(runner.apply_calls) == 1 and seen, "apply was not reached"

    run = seen["run"]
    assert run["id"] == res.run_id
    assert run["plan_fingerprint"] and run["plan_fingerprint"].startswith("sha256:")
    assert run["ack_outcome"] == "running"
    assert run["started_at"] and run["completed_at"] is None
    assert run["reviewer"] == "Dana" and run["reviewer_assurance"] == SELF_REPORTED
    assert run["rationale"] == "webhook fixed upstream"

    revs = [e for e in seen["record_events"] if e.kind == "review"]
    assert len(revs) == 1
    rv = revs[0]
    assert rv.data["decision"] == "revert"
    assert rv.data["plan_fingerprint"] == run["plan_fingerprint"]
    assert rv.data["rationale"] == "webhook fixed upstream"
    assert rv.data["source"] == "wrapper"
    assert rv.actor == "Dana" and rv.actor_assurance == SELF_REPORTED and rv.run_id == res.run_id

    started = [e for e in seen["run_events"] if e.kind == "run_started"]
    assert len(started) == 1
    assert started[0].data["plan_fingerprint"] == run["plan_fingerprint"]
    assert started[0].data["record_ids"] == [rid]
    assert not any(e.kind == "run_finished" for e in seen["run_events"])


def test_revert_success_records_completion_and_run_finished(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("r", "revert", "webhook fixed upstream"))
    assert res.outcome == "reverted_applied" and res.applied
    row = db.get_apply_run(res.run_id)
    assert row["ack_outcome"] == "reverted_applied" and row["completed_at"]
    fin = [e for e in events(db, run_id=res.run_id) if e.kind == "run_finished"]
    assert len(fin) == 1
    assert fin[0].data["outcome"] == "reverted_applied" and fin[0].data["applied"] is True
    kinds = [e.kind for e in events(db, run_id=res.run_id)]
    assert kinds.index("run_started") < kinds.index("run_finished")


def test_persist_failure_means_nothing_applied(db, tmp_path, monkeypatch):
    rid = open_record(db)
    orig = db.insert_event

    def flaky(row, conn=None):
        if row.get("kind") == "run_started":
            raise sqlite3.OperationalError("disk I/O error")
        return orig(row, conn)

    monkeypatch.setattr(db, "insert_event", flaky)
    s = Script("r", "revert", "webhook fixed upstream")
    res, runner, _ = run(db, tmp_path, s)
    assert runner.apply_calls == []
    assert res.outcome == "failed" and not res.applied
    row = db.get_apply_run(res.run_id)
    assert row["ack_outcome"] == "failed" and "could not be persisted" in row["ack_note"]
    assert "Nothing applied" in s.output
    # whole review transaction rolled back: no partial review/run_started rows
    assert reviews(db, rid) == []
    assert row["started_at"] is None
    assert db.get_record(rid)["intent"] == "unset"


def test_persist_failure_via_review_raising(db, tmp_path, monkeypatch):
    open_record(db)
    orig = wrapper._Ctx.review

    def boom(self, decision, rows, **kw):
        if kw.get("start_run"):
            raise RuntimeError("db gone")
        return orig(self, decision, rows, **kw)

    monkeypatch.setattr(wrapper._Ctx, "review", boom)
    s = Script("o", "override", "approved by lead")
    res, runner, _ = run(db, tmp_path, s)
    assert runner.apply_calls == [] and res.outcome == "failed"
    assert "could not be persisted" in db.get_apply_run(res.run_id)["ack_note"]
    assert "Nothing applied" in s.output


@pytest.mark.parametrize("rationale", ["", "   "], ids=["empty", "blank"])
def test_revert_without_rationale_cancels(db, tmp_path, rationale):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("r", "revert", rationale))
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert [e.data["decision"] for e in reviews(db, rid)] == ["revert-not-confirmed"]
    assert db.get_record(rid)["intent"] == "revert"


def test_revert_eof_at_rationale_cancels(db, tmp_path):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("r", "revert"))
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert all(e.data["decision"] != "revert" for e in reviews(db, rid))


def test_override_without_rationale_cancels(db, tmp_path):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("o", "override", ""))
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert [e.data["decision"] for e in reviews(db, rid)] == ["cancel"]


@pytest.mark.parametrize("bad", ["ok\x1b[31m", "line\nbreak", "nul\x00"], ids=["esc", "newline", "nul"])
def test_rationale_with_control_chars_rejected(db, tmp_path, bad):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("r", "revert", bad))
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert not any(e.data.get("rationale") for e in reviews(db, rid))
    assert db.get_apply_run(res.run_id)["rationale"] is None


@pytest.mark.parametrize("choice,decision,intent", [
    ("k", "keep", "keep"), ("d", "defer", "defer"), ("c", "cancel", "unset"),
])
def test_keep_defer_cancel_append_one_review(db, tmp_path, choice, decision, intent):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script(choice))
    assert runner.apply_calls == []
    revs = reviews(db, rid)
    assert len(revs) == 1
    assert revs[0].data["decision"] == decision and revs[0].run_id == res.run_id
    assert revs[0].data["plan_fingerprint"] == db.get_apply_run(res.run_id)["plan_fingerprint"]
    assert db.get_record(rid)["intent"] == intent
    assert not any(e.kind == "run_started" for e in events(db, run_id=res.run_id))


def test_unverified_bypass_requires_rationale(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("unverified-bypass", ""), scan_exit=1)
    assert res.outcome == "cancelled" and runner.apply_calls == []


def test_unverified_bypass_records_review(db, tmp_path):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("unverified-bypass", "scan API down, reviewed by hand"), scan_exit=1)
    assert res.outcome == "unverified_bypass_applied" and len(runner.apply_calls) == 1
    run_evs = events(db, run_id=res.run_id)
    started = [e for e in run_evs if e.kind == "run_started"]
    assert len(started) == 1 and started[0].data["decision"] == "unverified-bypass"
    revs = [e for e in run_evs if e.kind == "review"]
    assert revs and all(e.data["decision"] == "unverified-bypass" for e in revs)
    assert all(e.data["rationale"] == "scan API down, reviewed by hand" for e in revs)
    assert rid in [e.record_id for e in revs]
    assert db.get_apply_run(res.run_id)["rationale"] == "scan API down, reviewed by hand"


def test_named_reviewer_is_self_reported(db, tmp_path):
    rid = open_record(db)
    s = Script("k")
    run(db, tmp_path, s, reviewer="Dana")
    rv = reviews(db, rid)[0]
    assert rv.actor == "Dana" and rv.actor_assurance == SELF_REPORTED
    assert "Reviewer: Dana (self-reported)" in s.output


def test_default_reviewer_is_os_user(db, tmp_path):
    rid = open_record(db)
    run(db, tmp_path, Script("k"))
    rv = reviews(db, rid)[0]
    assert rv.actor == "osuser" and rv.actor_assurance == OS_USER_ASSURANCE == "local-os-user (not verified)"


def test_reviewer_with_control_char_falls_back_to_os_user(db, tmp_path):
    rid = open_record(db)
    res, _, _ = run(db, tmp_path, Script("r", "revert", "fixed"), reviewer="Eve\x1b[2J")
    rv = reviews(db, rid)[0]
    assert rv.actor == "osuser" and rv.actor_assurance == OS_USER_ASSURANCE
    row = db.get_apply_run(res.run_id)
    assert row["reviewer"] == "osuser" and row["reviewer_assurance"] == OS_USER_ASSURANCE


def test_prior_decisions_displayed_on_next_run(db, tmp_path):
    open_record(db)
    run(db, tmp_path, Script("k"), reviewer="Dana")
    s = Script("c")
    run(db, tmp_path, s)
    prior = [line for line in s.lines if "prior:" in line]
    assert prior and any("keep" in line and "Dana" in line for line in prior)


# ---------------------------------------------------------------------------
# R8 unknown outcomes
# ---------------------------------------------------------------------------

def test_unfinished_run_marked_unknown_on_next_apply(db, tmp_path):
    open_record(db)
    stuck = insert_run(db, ack_outcome="running")
    done = insert_run(db, ack_outcome="kept", completed_at=ts(utcnow()))
    other_env = insert_run(db, environment="prod", ack_outcome="running")

    s = Script("c")
    res, _, _ = run(db, tmp_path, s)
    row = db.get_apply_run(stuck)
    assert row["ack_outcome"] == "unknown" and "no completion" in row["ack_note"]
    assert row["completed_at"] is None
    assert stuck in s.output and "unknown" in s.output
    assert db.get_apply_run(done)["ack_outcome"] == "kept"
    assert db.get_apply_run(other_env)["ack_outcome"] == "running"
    assert db.get_apply_run(res.run_id)["ack_outcome"] == "cancelled"


def test_api_apply_run_includes_new_fields_and_unknown(db, client):
    stuck = insert_run(db, ack_outcome="running")
    db.mark_unfinished_runs_unknown(ENV, exclude_id="none")
    body = client.get(f"/api/apply-runs/{stuck}").json()
    assert body["ack_outcome"] == "unknown"
    for k in ("started_at", "reviewer", "reviewer_assurance", "rationale"):
        assert k in body
    assert body["started_at"] is not None
    assert body["reviewer"] is None and body["rationale"] is None
    listed = client.get("/api/apply-runs").json()["apply_runs"]
    assert any(r["id"] == stuck and r["ack_outcome"] == "unknown" for r in listed)


def test_api_run_events_after_wrapper_run(db, tmp_path, client):
    open_record(db)
    res, _, _ = run(db, tmp_path, Script("r", "revert", "fixed"), reviewer="Dana")
    body = client.get(f"/api/apply-runs/{res.run_id}").json()
    assert body["reviewer"] == "Dana" and body["reviewer_assurance"] == SELF_REPORTED
    assert body["rationale"] == "fixed" and body["started_at"]
    kinds = [e["kind"] for e in client.get(f"/api/apply-runs/{res.run_id}/events").json()["events"]]
    assert kinds == ["review", "run_started", "run_finished"]


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

OLD_APPLY_RUNS = """
CREATE TABLE apply_runs (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    plan_fingerprint TEXT,
    proposed_changes_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    check_status TEXT NOT NULL,
    coverage_note TEXT NOT NULL,
    ack_outcome TEXT NOT NULL,
    ack_note TEXT,
    completed_at TEXT
);
"""


def test_migration_adds_columns_to_old_apply_runs(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_APPLY_RUNS)
    gen = ts(T0)
    conn.execute(
        "INSERT INTO apply_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("run_old", ENV, gen, "sha256:abc", "[]", "[]", "current", "note", "kept", None,
         ts(T0 + timedelta(seconds=5))))
    conn.commit()
    conn.close()

    d = Database(path)
    try:
        cols = {r["name"] for r in d._all("PRAGMA table_info(apply_runs)")}
        assert {"started_at", "reviewer", "reviewer_assurance", "rationale"} <= cols
        out = apply_run_out(d.get_apply_run("run_old"))
        assert out.ack_outcome == "kept"
        assert out.started_at is None and out.reviewer is None
        assert out.reviewer_assurance is None and out.rationale is None
        # reopening is idempotent
        d.close()
        d = Database(path)
        assert apply_run_out(d.get_apply_run("run_old")).id == "run_old"
        assert d.list_events() == []
    finally:
        d.close()


def test_marking_run_unknown_appends_history_event(tmp_path):
    from breakglass.db import Database, new_id, ts
    from breakglass.models import utcnow
    db = Database(tmp_path / "u.db")
    rid = new_id("run")
    db.insert_apply_run({"id": rid, "environment": "demo", "generated_at": ts(utcnow()), "plan_fingerprint": None,
                         "proposed_changes_json": "[]", "warnings_json": "[]", "check_status": "current",
                         "coverage_note": "x", "ack_outcome": "running", "ack_note": None, "completed_at": None})
    assert db.mark_unfinished_runs_unknown("demo", exclude_id="other") == [rid]
    evs = db.list_events(run_id=rid)
    assert [e["kind"] for e in evs] == ["run_finished"]
    assert '"unknown"' in evs[0]["data_json"] and evs[0]["actor_assurance"] == "system"
    db.close()


# ---- regressions for the second review (M1, M2, M3, L3) --------------------

def test_interrupt_after_apply_started_is_failed_not_cancelled(db, tmp_path):
    # M1: Ctrl+C while terraform is applying must never read "nothing applied".
    open_record(db)
    s = Script("r", "revert", "why")
    tf = make_tf(tmp_path, FakeRunner())

    def interrupted(name):
        raise KeyboardInterrupt
    tf.apply_saved = interrupted
    res = guarded_apply(db, tf, ENV, prompt=s.prompt, out=s.out)
    assert res.outcome == "failed" and "Nothing applied" not in s.output


def test_interrupt_after_outcome_recorded_keeps_outcome(db, tmp_path, monkeypatch):
    # M1: an interrupt after finish() must not overwrite a successful outcome.
    open_record(db)
    s = Script("r", "revert", "why")
    real_out = s.out
    state = {"armed": False}

    def out(line):
        real_out(line)
        if line.startswith("[apply run") and not state["armed"]:
            state["armed"] = True
            raise KeyboardInterrupt
    tf = make_tf(tmp_path, FakeRunner())
    res = guarded_apply(db, tf, ENV, prompt=s.prompt, out=out)
    assert res.outcome == "reverted_applied" and res.applied
    assert db.get_apply_run(res.run_id)["ack_outcome"] == "reverted_applied"
    kinds = [e["kind"] for e in db.list_events(run_id=res.run_id)]
    assert kinds.count("run_finished") == 1


def test_state_sync_run_has_plan_fingerprint(db, tmp_path):
    # M2: the UI treats a null fingerprint as "planning failed".
    open_record(db)
    s = Script("yes")
    res, runner, _ = run(db, tmp_path, s, apply_plan_exit=0)
    assert res.applied
    assert db.get_apply_run(res.run_id)["plan_fingerprint"]


def test_reviewer_stored_on_runs_that_do_not_apply(db, tmp_path):
    # M3
    open_record(db)
    res, _, _ = run(db, tmp_path, Script("k"), reviewer="Dana")
    row = db.get_apply_run(res.run_id)
    assert row["reviewer"] == "Dana" and row["reviewer_assurance"] == SELF_REPORTED
    assert row["started_at"] is None and row["rationale"] is None


def test_list_events_limit_keeps_newest(db):
    # L3: with a limit, the newest events are returned (oldest first).
    rid = open_record(db, reason=False)
    for i in range(5):
        service.report(db, rid, ReportIn(reason=f"r{i}"))
    evs = db.list_events(record_id=rid, limit=2)
    assert [json.loads(e["data_json"])["reason"] for e in evs] == ["r3", "r4"]
