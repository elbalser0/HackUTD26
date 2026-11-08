"""Backend-neutral repository contract. Every test runs against SQLite and, when
BG_TEST_DATABASE_URL points at a disposable TimescaleDB, PostgreSQL.

CI sets BG_TEST_DATABASE_URL; locally the postgres cases are reported as skipped
(not passed) when it is absent.
"""

from __future__ import annotations

import json
import os

import pytest

from breakglass.db import Database, new_id

PG_URL = os.environ.get("BG_TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, tmp_path):
    if request.param == "sqlite":
        d = Database(tmp_path / "c.db")
        yield d
        d.close()
        return
    if not PG_URL:
        pytest.skip("BG_TEST_DATABASE_URL not set")
    from breakglass.postgres import PostgresDatabase
    from pg_helpers import drop_test_schema, migrate_test_schema

    schema = migrate_test_schema(PG_URL)
    d = PostgresDatabase(PG_URL, schema=schema)
    yield d
    d.close()
    drop_test_schema(PG_URL, schema)


def rec(i="rec_a", env="demo", fp="fp1", scope="s1", **kw):
    row = dict(
        id=i, environment=env, resource_address="digitalocean_firewall.web", resource_type="digitalocean_firewall",
        attribute="inbound_rule", change_kind="added", baseline_json=None,
        observed_json=json.dumps({"action": "allow", "protocol": "tcp", "port_range": "8443"}),
        scope_key=scope, fingerprint=fp, summary="s", first_detected_at="2026-01-01T00:00:00.000000Z",
        last_detected_at="2026-01-01T00:00:00.000000Z", last_check_status="confirmed", evidence_source="t",
    )
    row.update(kw)
    return row


def evt(i, ts_, kind="report", env="demo", record_id="rec_a", run_id=None):
    return {"id": i, "environment": env, "record_id": record_id, "run_id": run_id, "kind": kind,
            "actor": "a@b.c", "actor_assurance": "verified", "data_json": json.dumps({"k": i}), "created_at": ts_}


T0 = "2026-01-01T00:00:00.000000Z"


def test_record_roundtrip_and_updates(db):
    db.insert_record(rec())
    r = db.get_record("rec_a")
    assert r["id"] == "rec_a" and r["intent"] == "unset" and r["resolution"] == "open"
    assert r["first_detected_at"] == T0  # fixed-width UTC string at the repository boundary
    assert json.loads(r["observed_json"])["port_range"] == "8443"
    db.update_record("rec_a", {"reporter": "x", "reported_at": "2026-01-02T03:04:05.123456Z"})
    assert db.get_record("rec_a")["reported_at"] == "2026-01-02T03:04:05.123456Z"
    with pytest.raises(ValueError):
        db.update_record("rec_a", {"fingerprint": "nope"})
    assert db.get_record("missing") is None


def test_open_lookups_and_new_helpers(db):
    db.insert_record(rec("rec_a", fp="f1", scope="s1"))
    db.insert_record(rec("rec_b", fp="f2", scope="s1"))
    db.insert_record(rec("rec_c", env="prod", fp="f3", scope="s9"))
    db.update_record("rec_b", {"resolution": "resolved"})
    assert db.find_open_by_fingerprint("demo", "f1")["id"] == "rec_a"
    assert db.find_open_by_fingerprint("demo", "f2") is None
    assert [r["id"] for r in db.find_open_by_scope("demo", "s1")] == ["rec_a"]
    assert sorted(db.open_record_ids("demo")) == ["rec_a"]
    assert db.record_environment("rec_c") == "prod"
    assert db.record_environment("nope") is None
    assert [r["id"] for r in db.list_records(resolution="open", environment="demo")] == ["rec_a"]


def test_tx_rollback_discards_everything(db):
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            db.insert_record(rec(), c)
            db.insert_event(evt("evt_1", T0), c)
            raise RuntimeError("boom")
    assert db.get_record("rec_a") is None
    assert db.list_all_events() == []


def test_events_order_is_stable_across_timestamp_ties(db):
    db.insert_record(rec())
    with db.tx() as c:
        for n in ("evt_z", "evt_a", "evt_m"):  # ids deliberately not sorted
            db.insert_event(evt(n, T0), c)
    db.insert_event(evt("evt_0", "2025-12-31T23:59:59.000000Z"))
    assert [e["id"] for e in db.list_all_events()] == ["evt_0", "evt_z", "evt_a", "evt_m"]
    assert [e["id"] for e in db.list_events(record_id="rec_a")] == ["evt_0", "evt_z", "evt_a", "evt_m"]
    assert [e["id"] for e in db.list_events(record_id="rec_a", limit=2)] == ["evt_a", "evt_m"]
    assert db.list_all_events()[1]["created_at"] == T0


def test_event_id_is_globally_idempotent_key(db):
    db.insert_event(evt("evt_1", T0))
    with pytest.raises(Exception):
        db.insert_event(evt("evt_1", "2026-06-01T00:00:00.000000Z"))  # same id, different time
    assert len(db.list_all_events()) == 1


def test_apply_run_lifecycle_and_unknown_marking(db):
    base = dict(environment="demo", generated_at=T0, proposed_changes_json="[]", warnings_json="[]",
                check_status="confirmed", coverage_note="n", ack_outcome="running")
    db.insert_apply_run({"id": "run_old", **base})
    db.insert_apply_run({"id": "run_new", **base})
    db.update_apply_run("run_new", {"reviewer": "r", "rationale": "why", "plan_fingerprint": "abc"})
    assert db.get_apply_run("run_new")["rationale"] == "why"
    assert db.mark_unfinished_runs_unknown("demo", exclude_id="run_new") == ["run_old"]
    old = db.get_apply_run("run_old")
    assert old["ack_outcome"] == "unknown" and old["completed_at"] is None
    evs = db.list_events(run_id="run_old")
    assert [e["kind"] for e in evs] == ["run_finished"]
    assert json.loads(evs[0]["data_json"])["outcome"] == "unknown"
    assert [r["id"] for r in db.list_all_apply_runs()] == ["run_new", "run_old"] or \
        [r["id"] for r in db.list_all_apply_runs()] == ["run_old", "run_new"]
    with pytest.raises(ValueError):
        db.update_apply_run("run_new", {"environment": "x"})


def test_scans_and_reset(db):
    db.insert_scan(new_id("scan"), "demo", T0, "ok", None)
    db.insert_scan(new_id("scan"), "demo", "2026-01-02T00:00:00.000000Z", "failed", "[]")
    assert db.last_scan("demo")["status"] == "failed"
    assert [(r["started_at"], r["status"]) for r in db.list_scans()] == [
        (T0, "ok"), ("2026-01-02T00:00:00.000000Z", "failed")]
    assert db.last_scan("other") is None
    db.insert_record(rec())
    db.insert_event(evt("evt_1", T0))
    db.reset()
    assert db.list_records() == [] and db.list_all_events() == [] and db.last_scan("demo") is None
    db.insert_event(evt("evt_1", T0))  # key table is cleared too
    assert db.ping() is True
