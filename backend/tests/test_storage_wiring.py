"""API/CLI wiring for the configured backend, plus fail-closed behaviour around Terraform."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from helpers import ENV, FakeRunner, Script, load, make_tf, memdb

from breakglass import cli, service
from breakglass.api import create_app
from breakglass.models import DecisionIn, Intent, ReportIn
from breakglass.storage import StorageUnavailable
from breakglass.wrapper import guarded_apply

SECRET = "pw-secret-123"


class _Down:
    """A database that is unreachable for every call."""

    def __getattr__(self, name):
        def boom(*a, **k):
            raise StorageUnavailable("database unavailable or read-only (OperationalError)")
        return boom


def test_api_returns_503_when_storage_unavailable():
    with TestClient(create_app(db=_Down(), allowed_hosts=["testserver"])) as c:
        r = c.get("/api/records")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "storage_unavailable"
        assert c.get("/api/health").status_code == 503


def test_cli_unreachable_database_exits_nonzero_without_secret(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BG_DB_PATH", str(tmp_path / "fallback.db"))
    monkeypatch.setenv("BG_DATABASE_URL", f"postgresql://u:{SECRET}@127.0.0.1:1/db?connect_timeout=1")
    assert cli.main(["list"]) == 3
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    assert "database" in (out.out + out.err).lower()
    assert not (tmp_path / "fallback.db").exists()


def test_cli_migrate_schema_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("BG_DATABASE_URL", raising=False)
    assert cli.main(["migrate-schema"]) == 2
    assert "BG_DATABASE_URL" in capsys.readouterr().out


# ---- fail closed: Terraform must not apply unless the review is durable -----------------------

def _open_reported(db):
    rid = service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443"), evidence_source="authored-fixture").new_ids[0]
    service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    return rid


class _FailOn:
    """Delegates to a real db but raises when an event of `kind` is written."""

    def __init__(self, inner, kind, exc):
        self._inner, self._kind, self._exc = inner, kind, exc

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def insert_event(self, row, conn=None):
        if row["kind"] == self._kind:
            raise self._exc
        return self._inner.insert_event(row, conn)


def test_control_same_script_applies_when_storage_is_healthy(tmp_path):
    db = memdb()
    _open_reported(db)
    runner = FakeRunner()
    s = Script("r", "revert", "webhook fixed upstream")
    res = guarded_apply(db, make_tf(tmp_path, runner), ENV, prompt=s.prompt, out=s.out)
    assert res.applied and len(runner.apply_calls) == 1
    db.close()


@pytest.mark.parametrize("exc", [StorageUnavailable("down"), RuntimeError("commit outcome unknown")])
def test_review_persistence_failure_never_applies(tmp_path, exc):
    inner = memdb()
    _open_reported(inner)
    db = _FailOn(inner, "run_started", exc)
    runner = FakeRunner()
    tf = make_tf(tmp_path, runner)
    s = Script("r", "revert", "webhook fixed upstream")
    try:
        res = guarded_apply(db, tf, ENV, prompt=s.prompt, out=s.out)
        assert not res.applied
    except Exception:
        pass  # raising is also a fail-closed outcome
    assert runner.apply_calls == [], "terraform apply must not run when the review was not recorded"
    inner.close()


def test_review_not_durable_when_commit_fails(tmp_path):
    inner = memdb()
    _open_reported(inner)

    class CommitFails:
        def __getattr__(self, name):
            return getattr(inner, name)

        def tx(self):
            from contextlib import contextmanager

            @contextmanager
            def broken():
                with inner.tx() as c:
                    yield c
                    raise StorageUnavailable("commit not acknowledged")
            return broken()

    runner = FakeRunner()
    tf = make_tf(tmp_path, runner)
    s = Script("r", "revert", "webhook fixed upstream")
    try:
        guarded_apply(CommitFails(), tf, ENV, prompt=s.prompt, out=s.out)
    except Exception:
        pass
    assert runner.apply_calls == []
    inner.close()


# ---- PostgreSQL concurrency: two real connections ---------------------------------------------

import os  # noqa: E402

PG_URL = os.environ.get("BG_TEST_DATABASE_URL")


@pytest.fixture
def pg_pair():
    if not PG_URL:
        pytest.skip("BG_TEST_DATABASE_URL not set")
    from breakglass.postgres import PostgresDatabase
    from pg_helpers import drop_test_schema, migrate_test_schema
    schema = migrate_test_schema(PG_URL)
    a, b = PostgresDatabase(PG_URL, schema=schema), PostgresDatabase(PG_URL, schema=schema)
    yield a, b
    a.close()
    b.close()
    drop_test_schema(PG_URL, schema)


def test_two_connections_see_same_state(pg_pair):
    a, b = pg_pair
    rid = service.ingest_refresh_plan(a, ENV, load("refresh_drift_8443"), evidence_source="authored-fixture").new_ids[0]
    service.report(b, rid, ReportIn(reporter="P", reason="because"))
    assert a.get_record(rid)["reason"] == "because"
    assert [e["kind"] for e in a.list_events(record_id=rid)] == ["report"]


def test_concurrent_scans_of_same_evidence_open_one_record(pg_pair):
    a, b = pg_pair
    plan = load("refresh_drift_8443")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def go(db):
        try:
            barrier.wait()
            results.append(service.ingest_refresh_plan(db, ENV, plan, evidence_source="authored-fixture"))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts_ = [threading.Thread(target=go, args=(d,)) for d in (a, b)]
    [t.start() for t in ts_]
    [t.join() for t in ts_]
    assert not errors
    assert len(a.list_records(resolution="open")) == 1
    assert sum(len(r.new_ids) for r in results) == 1


def test_concurrent_decisions_on_a_record_that_gets_resolved(pg_pair):
    """A writer must not pass a stale 'open' check after another connection resolved the record."""
    a, b = pg_pair
    rid = service.ingest_refresh_plan(a, ENV, load("refresh_drift_8443"), evidence_source="authored-fixture").new_ids[0]
    with a.tx() as conn:
        service._require_open(a, rid, conn)       # a holds the row lock
        started = threading.Event()
        out = {}

        def other():
            started.set()
            try:
                service.decide(b, rid, DecisionIn(intent=Intent.KEEP, note="x"))
                out["ok"] = True
            except Exception as e:
                out["err"] = e

        t = threading.Thread(target=other)
        t.start()
        started.wait()
        t.join(0.5)
        assert t.is_alive(), "second writer must wait for the row lock, not race past it"
        a.update_record(rid, {"resolution": "resolved", "resolution_reason": "verified-aligned",
                              "resolved_at": "2026-01-01T00:00:00.000000Z"}, conn)
    t.join(10)
    assert isinstance(out.get("err"), service.Conflict)


def test_connections_are_pooled_and_bounded(pg_pair):
    a, _ = pg_pair
    pids = {a._read("SELECT pg_backend_pid() AS p", one=True)["p"] for _ in range(6)}
    assert len(pids) == 1, "sequential reads must reuse one pooled connection"
    count = ("SELECT count(*) AS n FROM pg_stat_activity WHERE application_name = 'argus' "
             "AND datname = current_database()")
    before = a._read(count, one=True)["n"]
    barrier, seen, errs = threading.Barrier(4), [], []

    def go():
        try:
            barrier.wait()
            for _ in range(5):
                a.ping()
            seen.append(1)
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ts_ = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts_]
    [t.join() for t in ts_]
    assert not errs and len(seen) == 4
    grown = a._read(count, one=True)["n"] - before
    assert grown <= 7  # 20 operations from 4 threads never open more than the pool cap (8) in total


def test_pool_survives_a_killed_connection(pg_pair):
    a, _ = pg_pair
    pid = a._read("SELECT pg_backend_pid() AS p", one=True)["p"]
    with __import__("psycopg").connect(PG_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
    assert a.ping() is True  # stale connection is detected and replaced
