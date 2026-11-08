"""Two personas (employee, admin) for the redesigned web UI.

- GET /api/me tells the UI which persona to show; the role is decided server-side
  with the same allowlist that guards /api/admin/*.
- With Firebase configured, every read needs a signed-in employee or admin
  (or the shared admin token); /api/health stays open. Without Firebase, reads stay open.
- Records carry who explained them (with assurance) and their last activity.
- GET /api/admin/overview: counts for "before the next apply". Events, not
  incidents or downtime, and never per-person aggregates (PRD non-goal: blame scores).
- GET /api/admin/log?type=... narrows the log to one event type.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from helpers import ENV, load
from test_admin import AUTH as ADMIN_AUTH, TOKEN as ADMIN_TOKEN, add_event, add_run_row, at, seed
from test_firebase_auth import SHARED, bearer, make_client, rid_of

from breakglass import admin, auth, service
from breakglass.api import create_app
from breakglass.db import Database
from breakglass.models import ReportIn, RunOutcome


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "p.db")
    yield d
    d.close()


# ---------------------------------------------------------------- GET /api/me

def test_me_admin_email_is_admin(db):
    with make_client(db) as c:
        body = c.get("/api/me", headers=bearer("tok-admin")).json()
    assert body == {"signed_in": True, "email": "lead@example.com", "display_name": "Lead",
                    "role": "admin", "auth_mode": "firebase"}


def test_me_other_verified_email_is_employee(db):
    with make_client(db) as c:
        body = c.get("/api/me", headers=bearer("tok-dana")).json()
    assert (body["role"], body["email"], body["signed_in"]) == ("employee", "dana@example.com", True)


def test_me_without_token_is_not_signed_in(db):
    with make_client(db) as c:
        r = c.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"signed_in": False, "email": None, "display_name": None, "role": None,
                        "auth_mode": "firebase"}


@pytest.mark.parametrize("tok,status,code", [
    ("not-a-real-token", 401, "sign_in_invalid"),
    ("tok-unverified", 403, "email_unverified"),
])
def test_me_rejects_bad_or_unverified_tokens(db, tok, status, code):
    with make_client(db) as c:
        r = c.get("/api/me", headers=bearer(tok))
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_me_shared_token_is_admin_without_identity(db):
    with make_client(db) as c:
        body = c.get("/api/me", headers=bearer(SHARED)).json()
    assert body == {"signed_in": False, "email": None, "display_name": None, "role": "admin",
                    "auth_mode": "shared-token"}
    assert SHARED not in json.dumps(body)


def test_me_without_firebase_has_no_persona(db):
    with make_client(db, firebase=False) as c:
        body = c.get("/api/me").json()
    assert body["role"] is None and body["auth_mode"] == "none"


def test_me_never_admin_without_allowlist(db):
    with make_client(db, admins=()) as c:
        assert c.get("/api/me", headers=bearer("tok-admin")).json()["role"] == "employee"


def test_me_role_agrees_with_admin_enforcement(db):
    """The persona shown and the server-side gate must never disagree."""
    with make_client(db) as c:
        for tok in ("tok-admin", "tok-dana"):
            role = c.get("/api/me", headers=bearer(tok)).json()["role"]
            allowed = c.get("/api/admin/log", headers=bearer(tok)).status_code == 200
            assert (role == "admin") == allowed, tok


# ---------------------------------------------------------------- reads need sign-in

def _read_paths(db):
    rid = rid_of(db)
    run = add_run_row(db, generated=at(5), outcome="cancelled", completed=at(6), rec_ids=[rid])
    return [f"/api/records", f"/api/records/{rid}", f"/api/records/{rid}/events",
            "/api/apply-runs", f"/api/apply-runs/{run}", f"/api/apply-runs/{run}/events"]


def test_reads_require_sign_in_when_firebase_configured(db):
    paths = _read_paths(db)
    with make_client(db) as c:
        for p in paths:
            r = c.get(p)
            assert r.status_code == 401 and r.json()["error"]["code"] == "sign_in_required", p
            assert c.get(p, headers=bearer("not-a-real-token")).json()["error"]["code"] == "sign_in_invalid", p
            assert c.get(p, headers=bearer("tok-unverified")).status_code == 403, p


@pytest.mark.parametrize("tok", ["tok-dana", "tok-admin", SHARED])
def test_employee_admin_and_shared_token_can_read(db, tok):
    paths = _read_paths(db)
    with make_client(db) as c:
        for p in paths:
            assert c.get(p, headers=bearer(tok)).status_code == 200, (p, tok)


def test_reads_stay_open_without_firebase(db):
    paths = _read_paths(db)
    with make_client(db, firebase=False) as c:
        for p in paths:
            assert c.get(p).status_code == 200, p


def test_health_stays_open_and_reports_read_auth(db):
    with make_client(db) as c:
        r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["auth"]["reads_require_sign_in"] is True
    with make_client(db, firebase=False) as c:
        assert c.get("/api/health").json()["auth"]["reads_require_sign_in"] is False


def test_admin_can_still_submit_an_explanation(db):
    """Admins are read-only in the UI only; an admin who was on call can explain their own change."""
    rid = rid_of(db)
    with make_client(db) as c:
        r = c.post(f"/api/records/{rid}/report", json={"reason": "on call, opened 8443"}, headers=bearer("tok-admin"))
    assert r.status_code == 200


# ---------------------------------------------------------------- record enrichment

def _record(c, rid, headers=None):
    r = c.get(f"/api/records/{rid}", headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_unexplained_record_has_no_reporter_assurance_and_detection_as_last_activity(db):
    rid = seed(db)
    with make_client(db, firebase=False) as c:
        rec = _record(c, rid)
    assert rec["reporter_assurance"] is None
    assert rec["last_activity"]["type"] == "detected"
    assert rec["last_activity"]["at"] == rec["first_detected_at"]


def test_self_reported_explanation_is_labelled(db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"), source="cli")
    with make_client(db, firebase=False) as c:
        rec = _record(c, rid)
    assert rec["reporter_assurance"] == "self-reported"
    assert rec["last_activity"]["type"] == "report"


def test_verified_explanation_is_labelled_and_listed(db):
    rid = rid_of(db)
    with make_client(db) as c:
        c.post(f"/api/records/{rid}/report", json={"reason": "opened 8443"}, headers=bearer("tok-dana"))
        rows = c.get("/api/records", headers=bearer("tok-dana")).json()["records"]
    (rec,) = [r for r in rows if r["id"] == rid]
    assert rec["reporter_assurance"] == auth.VERIFIED_ASSURANCE


def test_last_activity_is_the_latest_event(db):
    rid = seed(db)
    add_event(db, "report", when=at(10), record_id=rid, actor="Paul", data={"reason": "r"})
    add_event(db, "decision", when=at(20), record_id=rid, actor="Paul", data={"intent": "keep"})
    with make_client(db, firebase=False) as c:
        act = _record(c, rid)["last_activity"]
    assert act["type"] == "decision" and act["at"].startswith("2026-11-08T03:50")


# ---------------------------------------------------------------- admin overview

NOW = at(60)


def _overview(db, window="24h", now=NOW, environment=ENV):
    return json.loads(admin.overview(db, window=window, now=now, environment=environment).model_dump_json())


def test_overview_counts_open_and_missing_reasons(db):
    a = seed(db)
    service.report(db, a, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    body = _overview(db)
    assert body["open_records"] == 1 and body["open_without_reason"] == 0
    assert body["needs_reason"] == []


def test_overview_lists_records_that_need_a_reason(db):
    rid = seed(db)
    body = _overview(db)
    assert body["open_without_reason"] == 1
    assert [n["record_id"] for n in body["needs_reason"]] == [rid]
    assert set(body["needs_reason"][0]) == {"record_id", "resource_address", "summary", "first_detected_at"}


def test_overview_last_run_unknown_is_never_success(db):
    rid = seed(db)
    add_run_row(db, generated=at(10), completed=at(11), outcome="applied_no_warnings", rec_ids=[rid])
    stuck = add_run_row(db, generated=at(30), started=at(30), outcome="running", rec_ids=[rid])
    body = _overview(db)
    assert body["last_run"]["run_id"] == stuck and body["last_run"]["outcome"] == "unknown"
    assert body["run_outcomes"] == {"applied_no_warnings": 1, "unknown": 1}


def test_overview_window_excludes_old_events(db):
    rid = seed(db)
    add_event(db, "report", when=NOW - timedelta(days=3), record_id=rid, actor="Paul", data={"reason": "old"})
    add_event(db, "report", when=NOW - timedelta(hours=2), record_id=rid, actor="Paul", data={"reason": "new"})
    assert _overview(db, "24h")["events_by_type"].get("explained") == 1
    assert _overview(db, "7d")["events_by_type"].get("explained") == 2


def test_overview_activity_is_hourly_utc_buckets(db):
    rid = seed(db)
    add_event(db, "report", when=NOW - timedelta(minutes=30), record_id=rid, actor="Paul", data={"reason": "r"})
    body = _overview(db, "24h")
    assert len(body["activity"]) == 24
    hours = [b["hour"] for b in body["activity"]]
    assert hours == sorted(hours) and all(h.endswith(":00:00Z") for h in hours)
    assert sum(b["counts"].get("explained", 0) for b in body["activity"]) == 1
    assert len(_overview(db, "7d")["activity"]) == 168


def test_overview_has_no_per_person_aggregates(db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paulina Example", reason="payment webhook blocked"))
    add_run_row(db, generated=at(10), started=at(10), outcome="running", rec_ids=[rid],
                reviewer="Reviewer Example", assurance="self-reported")
    text = json.dumps(_overview(db))
    assert "Paulina Example" not in text and "Reviewer Example" not in text


def test_overview_states_its_limits(db):
    lim = " ".join(_overview(db)["limitations"]).lower()
    assert "not incidents or downtime" in lim


def test_overview_reports_last_scan(db):
    service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443"))
    ls = _overview(db)["last_scan"]
    assert ls is not None and ls["status"] == "ok"


def test_overview_endpoint_is_admin_only(db):
    seed(db)
    with make_client(db) as c:
        assert c.get("/api/admin/overview").status_code == 401
        assert c.get("/api/admin/overview", headers=bearer("tok-dana")).status_code == 403
        r = c.get("/api/admin/overview", params={"window": "7d"}, headers=bearer("tok-admin"))
        assert r.status_code == 200 and len(r.json()["activity"]) == 168
        assert c.get("/api/admin/overview", params={"window": "1y"}, headers=bearer("tok-admin")).status_code == 422


# ---------------------------------------------------------------- admin log type filter

@pytest.fixture
def admin_client(db):
    with TestClient(create_app(db=db, allowed_hosts=["testserver"], admin_token=ADMIN_TOKEN)) as c:
        yield c


def test_log_type_filter(admin_client, db):
    rid = seed(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    r = admin_client.get("/api/admin/log", params={"type": "explained"}, headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert {e["type"] for e in r.json()["events"]} == {"explained"}
    assert admin_client.get("/api/admin/log", params={"type": "nonsense"}, headers=ADMIN_AUTH).status_code == 422
