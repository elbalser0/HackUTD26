"""Activity analytics: hourly counts of audit events. Same contract on SQLite (bounded SQL) and
TimescaleDB (real-time continuous aggregate). Fixed UTC timestamps throughout."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from breakglass.api import create_app
from breakglass.db import Database
from breakglass.storage import StorageUnavailable

PG_URL = os.environ.get("BG_TEST_DATABASE_URL")
TOKEN = "test-admin-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
_n = 0


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, tmp_path):
    if request.param == "sqlite":
        d = Database(tmp_path / "a.db")
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
    drop_test_schema(PG_URL, schema)


@pytest.fixture
def client(db):
    with TestClient(create_app(db=db, allowed_hosts=["testserver"], admin_token=TOKEN)) as c:
        yield c


def add(db, ts_, kind="report", env="demo", **data):
    global _n
    _n += 1
    db.insert_event({"id": f"evt_{_n}", "environment": env, "record_id": "rec_x", "run_id": None, "kind": kind,
                     "actor": "a", "actor_assurance": "verified", "data_json": json.dumps(data), "created_at": ts_})


def get(client, **p):
    q = {"environment": "demo", "since": "2026-03-01T10:00:00Z", "until": "2026-03-01T13:00:00Z", **p}
    q = {k: v for k, v in q.items() if v is not None}
    return client.get("/api/admin/analytics", params=q, headers=AUTH)


def test_empty_window_is_zero_filled_hourly_series(client, db):
    body = get(client).json()
    assert [b["start"] for b in body["buckets"]] == [
        "2026-03-01T10:00:00Z", "2026-03-01T11:00:00Z", "2026-03-01T12:00:00Z"]
    assert all(b["total"] == 0 and b["by_kind"] == {} for b in body["buckets"])
    assert body["bucket_size"] == "1 hour" and body["environment"] == "demo"
    assert body["backend"] in ("sqlite", "timescaledb")
    assert body["generated_at"].endswith("Z") and body["freshness"]["mode"]


def test_counts_by_hour_and_kind_with_env_separation(client, db):
    add(db, "2026-03-01T10:05:00.000000Z", "report", intent="keep")
    add(db, "2026-03-01T10:59:59.999999Z", "report", intent="revert")
    add(db, "2026-03-01T11:00:00.000000Z", "decision", intent="keep")
    add(db, "2026-03-01T11:30:00.000000Z", "report", env="prod", intent="keep")  # other environment
    add(db, "2026-03-01T13:00:00.000000Z", "report", intent="keep")              # == until, excluded
    add(db, "2026-03-01T09:59:59.999999Z", "report", intent="keep")              # before since
    b = {x["start"]: x for x in get(client).json()["buckets"]}
    assert b["2026-03-01T10:00:00Z"]["by_kind"] == {"report": 2} and b["2026-03-01T10:00:00Z"]["total"] == 2
    assert b["2026-03-01T11:00:00Z"]["by_kind"] == {"decision": 1}
    assert b["2026-03-01T12:00:00Z"]["total"] == 0
    t = get(client).json()["totals"]
    assert t["by_kind"] == {"report": 2, "decision": 1} and t["by_intent"] == {"keep": 1 + 1, "revert": 1}


def test_unknown_outcome_is_not_failed_and_reviews_are_not_incidents(client, db):
    add(db, "2026-03-01T10:10:00.000000Z", "run_finished", outcome="unknown")
    add(db, "2026-03-01T10:11:00.000000Z", "run_finished", outcome="failed")
    add(db, "2026-03-01T10:12:00.000000Z", "run_finished", outcome="unknown")
    add(db, "2026-03-01T10:13:00.000000Z", "review", decision="revert")
    add(db, "2026-03-01T10:14:00.000000Z", "decision", intent="keep")
    t = get(client).json()["totals"]
    assert t["by_outcome"] == {"unknown": 2, "failed": 1}
    assert t["by_decision"] == {"revert": 1}
    assert t["by_kind"] == {"run_finished": 3, "review": 1, "decision": 1}  # kinds stay separate


def test_unaligned_window_is_widened_to_whole_hours_and_reported(client, db):
    add(db, "2026-03-01T10:15:00.000000Z", intent="keep")
    body = get(client, since="2026-03-01T10:30:00Z", until="2026-03-01T12:10:00Z").json()
    assert body["since"] == "2026-03-01T10:00:00Z" and body["until"] == "2026-03-01T13:00:00Z"
    assert body["buckets"][0]["total"] == 1  # the 10:15 event is inside the widened first hour


def test_offsets_are_normalized_to_utc(client, db):
    body = get(client, since="2026-03-01T05:00:00-05:00", until="2026-03-01T08:00:00-05:00").json()
    assert body["since"] == "2026-03-01T10:00:00Z" and body["until"] == "2026-03-01T13:00:00Z"


@pytest.mark.parametrize("params", [
    {"since": "2026-03-01T13:00:00Z", "until": "2026-03-01T10:00:00Z"},   # reversed
    {"since": "2026-03-01T10:00:00Z", "until": "2026-03-01T10:00:00Z"},   # empty
    {"since": "2026-01-01T00:00:00Z", "until": "2026-03-01T00:00:00Z"},   # > 31 days
    {"since": "2026-03-01T10:00:00", "until": "2026-03-01T13:00:00Z"},    # naive
    {"since": "garbage"},
    {"environment": None},                                                   # required
    {"since": None}, {"until": None},
])
def test_invalid_windows_rejected(client, params):
    assert get(client, **params).status_code == 422


def test_requires_admin(client):
    q = {"environment": "demo", "since": "2026-03-01T10:00:00Z", "until": "2026-03-01T13:00:00Z"}
    assert client.get("/api/admin/analytics", params=q).status_code == 401
    assert client.get("/api/admin/analytics", params=q, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/admin/analytics", params={**q, "token": TOKEN}).status_code == 401


def test_database_failure_is_503_never_zero_activity():
    class Down:
        backend_name = "x"

        def __getattr__(self, n):
            def boom(*a, **k):
                raise StorageUnavailable("down")
            return boom

    with TestClient(create_app(db=Down(), allowed_hosts=["testserver"], admin_token=TOKEN)) as c:
        r = get(c)
        assert r.status_code == 503 and r.json()["error"]["code"] == "storage_unavailable"


# ---- TimescaleDB only: the real continuous aggregate -------------------------------------------

def test_cagg_is_real_time_for_new_events_and_backfill_needs_refresh(db, client):
    if getattr(db, "backend_name", "") != "timescaledb":
        pytest.skip("continuous aggregate is TimescaleDB-only")
    day = datetime(2026, 3, 1, tzinfo=timezone.utc)
    nxt = datetime(2026, 3, 2, tzinfo=timezone.utc)
    cutoff = datetime(2026, 3, 1, 10, tzinfo=timezone.utc)
    assert db.activity_source_is_cagg() is True
    add(db, "2026-03-01T09:30:00.000000Z", intent="keep")
    db.refresh_activity(day, cutoff)                       # watermark = 10:00
    add(db, "2026-03-01T10:05:00.000000Z", intent="keep")  # after the watermark: raw tail
    add(db, "2026-03-01T10:20:00.000000Z", intent="keep")
    # newly appended events are counted without any refresh (real-time aggregation)
    assert get(client).json()["totals"]["by_kind"] == {"report": 2}
    assert get(client, since="2026-03-01T09:00:00Z").json()["totals"]["by_kind"] == {"report": 3}
    db.refresh_activity(day, nxt)                          # watermark moves past everything
    add(db, "2026-03-01T10:50:00.000000Z", intent="keep")  # backfill BEHIND the watermark
    assert get(client).json()["totals"]["by_kind"] == {"report": 2}, "behind the watermark: not visible yet"
    db.refresh_activity(day, nxt)                          # explicit refresh fixes it
    assert get(client).json()["totals"]["by_kind"] == {"report": 3}
