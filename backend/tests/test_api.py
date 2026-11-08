import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from helpers import ENV, load, memdb, refresh_variant_9443

from breakglass import service
from breakglass.api import create_app
from breakglass.db import new_id, ts
from breakglass.models import utcnow

T0 = datetime(2026, 11, 8, 3, 30, 12, tzinfo=timezone.utc)
TZ_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


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


def seed(db, plan="refresh_drift_8443", now=T0):
    p = load(plan) if isinstance(plan, str) else plan
    return service.ingest_refresh_plan(db, ENV, p, evidence_source="authored-fixture", now=now)


def seed_one(db):
    return seed(db).new_ids[0]


def seed_run(db, rid=None):
    run_id = new_id("run")
    warnings = []
    if rid:
        warnings = [json.loads(service.warning_out(db.get_record(rid)).model_dump_json())]
    db.insert_apply_run({
        "id": run_id, "environment": ENV, "generated_at": ts(utcnow()),
        "plan_fingerprint": "sha256:abc", "proposed_changes_json": json.dumps([{
            "resource_address": "digitalocean_firewall.web", "resource_type": "digitalocean_firewall",
            "actions": ["update"], "summary": "update inbound_rule: -tcp 8443, +tcp 8080"}]),
        "warnings_json": json.dumps(warnings), "check_status": "current",
        "coverage_note": "note", "ack_outcome": "kept", "ack_note": None, "completed_at": ts(utcnow()),
    })
    return run_id


def assert_err(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)


def test_health_shape(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"status", "version", "db", "environment", "terraform_dir_configured", "time",
                      "last_scan_at", "last_scan_status"}
    assert b["status"] == "ok" and b["db"] == "ok"
    assert isinstance(b["terraform_dir_configured"], bool)
    assert TZ_RE.search(b["time"])


def test_records_empty(client):
    r = client.get("/api/records")
    assert r.status_code == 200 and r.json() == {"records": []}


def test_records_filter_by_resolution(client, db):
    old = seed_one(db)
    new = seed(db, refresh_variant_9443(), now=T0 + timedelta(minutes=1)).new_ids[0]
    open_ids = [x["id"] for x in client.get("/api/records?resolution=open").json()["records"]]
    resolved_ids = [x["id"] for x in client.get("/api/records?resolution=resolved").json()["records"]]
    all_ids = [x["id"] for x in client.get("/api/records").json()["records"]]
    assert open_ids == [new]
    assert resolved_ids == [old]
    assert set(all_ids) == {old, new}


def test_records_invalid_resolution_422(client):
    assert_err(client.get("/api/records?resolution=bogus"), 422, "validation_error")


def test_get_record_and_404(client, db):
    rid = seed_one(db)
    r = client.get(f"/api/records/{rid}")
    assert r.status_code == 200 and r.json()["id"] == rid
    assert_err(client.get("/api/records/rec_missing"), 404, "not_found")


def test_record_timestamps_have_timezone(client, db):
    rid = seed_one(db)
    client.post(f"/api/records/{rid}/report", json={"reason": "x", "intent": "keep"})
    b = client.get(f"/api/records/{rid}").json()
    for k in ("first_detected_at", "last_detected_at", "reported_at", "intent_updated_at", "last_check_at"):
        assert TZ_RE.search(b[k]), (k, b[k])


def test_report_200_and_persisted(client, db):
    rid = seed_one(db)
    r = client.post(f"/api/records/{rid}/report",
                    json={"reporter": "Paul", "reason": "payment webhook blocked", "intent": "keep"})
    assert r.status_code == 200
    b = r.json()
    assert b["reporter"] == "Paul" and b["reason"] == "payment webhook blocked" and b["intent"] == "keep"
    row = db.get_record(rid)
    assert row["reason"] == "payment webhook blocked" and row["reporter"] == "Paul"


def test_report_extra_field_422(client, db):
    rid = seed_one(db)
    assert_err(client.post(f"/api/records/{rid}/report", json={"reason": "x", "admin": True}),
               422, "validation_error")
    assert db.get_record(rid)["reason"] is None


def test_report_empty_reason_422(client, db):
    rid = seed_one(db)
    assert_err(client.post(f"/api/records/{rid}/report", json={"reason": ""}), 422, "validation_error")


def test_report_whitespace_reason_422(client, db):
    rid = seed_one(db)
    assert_err(client.post(f"/api/records/{rid}/report", json={"reason": "   "}), 422, "validation_error")


def test_report_reason_too_long_422(client, db):
    rid = seed_one(db)
    assert_err(client.post(f"/api/records/{rid}/report", json={"reason": "x" * 501}), 422, "validation_error")
    assert client.post(f"/api/records/{rid}/report", json={"reason": "x" * 500}).status_code == 200


def test_report_unknown_404(client):
    assert_err(client.post("/api/records/rec_missing/report", json={"reason": "x"}), 404, "not_found")


def test_decision_200_still_open(client, db):
    rid = seed_one(db)
    r = client.post(f"/api/records/{rid}/decision", json={"intent": "revert", "note": "done"})
    assert r.status_code == 200
    b = r.json()
    assert b["intent"] == "revert" and b["resolution"] == "open" and b["resolved_at"] is None


def test_report_on_resolved_409(client, db):
    old = seed_one(db)
    seed(db, refresh_variant_9443(), now=T0 + timedelta(minutes=1))
    assert_err(client.post(f"/api/records/{old}/report", json={"reason": "x"}), 409, "conflict")
    assert_err(client.post(f"/api/records/{old}/decision", json={"intent": "keep"}), 409, "conflict")


def test_apply_runs_list_get_404(client, db):
    assert client.get("/api/apply-runs").json() == {"apply_runs": []}
    rid = seed_one(db)
    run_id = seed_run(db, rid)
    lst = client.get("/api/apply-runs").json()["apply_runs"]
    assert [r["id"] for r in lst] == [run_id]
    r = client.get(f"/api/apply-runs/{run_id}")
    assert r.status_code == 200
    b = r.json()
    assert b["warnings"][0]["record_id"] == rid
    assert b["proposed_changes"][0]["actions"] == ["update"]
    assert TZ_RE.search(b["generated_at"]) and TZ_RE.search(b["completed_at"])
    assert TZ_RE.search(b["warnings"][0]["first_detected_at"])
    assert_err(client.get("/api/apply-runs/run_missing"), 404, "not_found")


def test_apply_runs_limit_validation(client):
    assert_err(client.get("/api/apply-runs?limit=0"), 422, "validation_error")
    assert_err(client.get("/api/apply-runs?limit=101"), 422, "validation_error")


def _preflight(client, origin):
    return client.options("/api/records", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type"})


def test_cors_allows_vite_dev_origin(client):
    r = _preflight(client, "http://localhost:5173")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_other_origin(client):
    r = _preflight(client, "http://evil.example")
    assert r.headers.get("access-control-allow-origin") != "http://evil.example"
    assert "evil.example" not in r.headers.get("access-control-allow-origin", "")
    r2 = client.get("/api/records", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r2.headers


@pytest.mark.parametrize("path", ["/api/scan", "/api/apply", "/api/recheck", "/api/terraform",
                                  "/api/records", "/api/apply-runs"])
def test_no_endpoint_runs_scans_or_apply(client, path):
    r = client.post(path, json={})
    assert r.status_code in (404, 405)
    assert "error" in r.json()


def test_openapi_has_no_scan_apply_routes(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    for p, ops in paths.items():
        assert not any(w in p for w in ("scan", "recheck", "terraform")), p
        if "post" in ops:
            assert p.endswith("/report") or p.endswith("/decision"), p


def test_untrusted_host_header_rejected(db):
    # DNS-rebinding defense: default allowlist is localhost/127.0.0.1/[::1] only.
    with TestClient(create_app(db=db)) as c:
        assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400
        assert c.get("/api/health", headers={"host": "localhost:8000"}).status_code == 200


def test_report_rejects_terminal_control_characters(client, db):
    rid = seed_one(db)
    r = client.post(f"/api/records/{rid}/report", json={"reason": "ok[2K[1Afake line"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.post(f"/api/records/{rid}/report", json={"reason": "fine", "reporter": "P‮aul"})
    assert r.status_code == 422


def test_health_reports_last_scan(client, db, monkeypatch):
    body = client.get("/api/health").json()
    assert body["last_scan_at"] is None and body["last_scan_status"] is None
    assert body["environment"] == ENV
    seed(db)  # scan into ENV
    body = client.get("/api/health").json()
    assert body["last_scan_status"] == "ok" and body["last_scan_at"].endswith("Z")
