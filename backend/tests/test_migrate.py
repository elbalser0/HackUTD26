"""SQLite -> configured database import. Runs against a SQLite target always and PostgreSQL when
BG_TEST_DATABASE_URL is set. The source is only ever read through a snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3

import pytest

from helpers import ENV, load

from breakglass import cli, service
from breakglass.db import Database
from breakglass.migrate import ImportRefused, import_sqlite
from breakglass.models import DecisionIn, Intent, ReportIn

PG_URL = os.environ.get("BG_TEST_DATABASE_URL")
T = "2026-02-03T04:05:06.123456Z"


@pytest.fixture(params=["sqlite", "postgres"])
def target(request, tmp_path):
    if request.param == "sqlite":
        d = Database(tmp_path / "target.db")
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


def make_source(path):
    """A realistic history: scan, report, decision, a run with unknown outcome, equal-time events."""
    d = Database(path)
    rid = service.ingest_refresh_plan(d, ENV, load("refresh_drift_8443"), evidence_source="authored-fixture").new_ids[0]
    service.report(d, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    service.decide(d, rid, DecisionIn(intent=Intent.KEEP, note="vendor"))
    d.insert_apply_run({"id": "run_a", "environment": ENV, "generated_at": T, "proposed_changes_json": "[]",
                        "warnings_json": "[]", "check_status": "confirmed", "coverage_note": "n",
                        "ack_outcome": "running", "reviewer": "r", "reviewer_assurance": "os-user"})
    d.mark_unfinished_runs_unknown(ENV, exclude_id="run_none")
    for i, name in enumerate(["evt_tie_z", "evt_tie_a", "evt_tie_m"]):  # equal timestamps, unsorted ids
        d.insert_event({"id": name, "environment": ENV, "record_id": rid, "run_id": None, "kind": "report",
                        "actor": "x", "actor_assurance": "self-reported",
                        "data_json": json.dumps({"i": i}), "created_at": T})
    d.insert_event({"id": "evt_early", "environment": ENV, "record_id": rid, "run_id": None, "kind": "report",
                    "actor": "x", "actor_assurance": "self-reported", "data_json": "{}",
                    "created_at": "2020-01-01T00:00:00.000000Z"})  # inserted last, happened first
    d.close()
    return rid


def canon(db):
    return {
        "records": [dict(r) for r in db.list_records()],
        "runs": [dict(r) for r in db.list_all_apply_runs()],
        "scans": [dict(r) for r in db.list_scans()],
        "events": [{k: v for k, v in dict(e).items() if k not in ("seq", "intent", "decision", "outcome")}
                   for e in db.list_all_events()],
    }


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_complete_import_preserves_everything_in_order(tmp_path, target):
    src = tmp_path / "src.db"
    make_source(src)
    before = sha(src)
    report = import_sqlite(src, target)
    s = Database(src)
    try:
        want = canon(s)
    finally:
        s.close()
    got = canon(target)
    for k in ("records", "runs", "scans"):
        assert sorted(got[k], key=lambda r: r["id"]) == sorted(want[k], key=lambda r: r["id"]), k
    assert [e["id"] for e in got["events"]] == [e["id"] for e in want["events"]]  # ties keep source order
    assert got["events"] == want["events"]
    assert report.imported == {"records": 1, "apply_runs": 1, "scans": 1, "events": len(want["events"])}
    assert report.verified is True and report.dry_run is False
    assert sha(src) == before  # source untouched


def test_dry_run_validates_and_writes_nothing(tmp_path, target):
    src = tmp_path / "src.db"
    make_source(src)
    report = import_sqlite(src, target, dry_run=True)
    assert report.dry_run and report.imported["records"] == 1 and report.imported["events"] >= 6
    assert target.list_records() == [] and target.list_all_events() == [] and target.list_scans() == []


def test_rerun_is_idempotent(tmp_path, target):
    src = tmp_path / "src.db"
    make_source(src)
    import_sqlite(src, target)
    first = canon(target)
    again = import_sqlite(src, target)
    assert again.imported == {"records": 0, "apply_runs": 0, "scans": 0, "events": 0}
    assert again.already_present["records"] == 1 and again.verified
    assert canon(target) == first


def test_conflicting_id_is_refused_and_target_untouched(tmp_path, target):
    src = tmp_path / "src.db"
    rid = make_source(src)
    import_sqlite(src, target)
    target.update_record(rid, {"reason": "tampered"})
    with pytest.raises(ImportRefused, match="conflict"):
        import_sqlite(src, target)
    assert target.get_record(rid)["reason"] == "tampered"  # never silently overwritten


def test_target_with_unrelated_rows_is_refused(tmp_path, target):
    src = tmp_path / "src.db"
    make_source(src)
    target.insert_scan("scan_other", "prod", T, "ok", None)
    with pytest.raises(ImportRefused, match="not empty"):
        import_sqlite(src, target)
    assert target.list_records() == []


def test_incompatible_source_schema_is_refused(tmp_path, target):
    src = tmp_path / "bad.db"
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE records (id TEXT PRIMARY KEY)")
    c.commit()
    c.close()
    with pytest.raises(ImportRefused, match="schema"):
        import_sqlite(src, target)


def test_missing_source_file_is_refused_not_created(tmp_path, target):
    with pytest.raises(ImportRefused, match="not found"):
        import_sqlite(tmp_path / "nope.db", target)
    assert not (tmp_path / "nope.db").exists()


def test_bad_timestamp_is_refused_before_any_write(tmp_path, target):
    src = tmp_path / "src.db"
    make_source(src)
    c = sqlite3.connect(src)
    c.execute("UPDATE events SET created_at = 'yesterday-ish' WHERE id = 'evt_tie_a'")
    c.commit()
    c.close()
    with pytest.raises(ImportRefused, match="timestamp"):
        import_sqlite(src, target)
    assert target.list_records() == []


def test_failure_midway_rolls_back_everything(tmp_path, target, monkeypatch):
    src = tmp_path / "src.db"
    make_source(src)
    real, n = target.insert_event, {"n": 0}

    def flaky(row, conn=None):
        n["n"] += 1
        if n["n"] == 3:
            raise RuntimeError("boom")
        return real(row, conn)

    monkeypatch.setattr(target, "insert_event", flaky)
    with pytest.raises(RuntimeError):
        import_sqlite(src, target)
    monkeypatch.undo()
    assert target.list_records() == [] and target.list_all_events() == [] and target.list_scans() == []


def test_older_source_without_newer_apply_run_columns(tmp_path, target):
    src = tmp_path / "old.db"
    make_source(src)
    c = sqlite3.connect(src)
    for col in ("started_at", "reviewer", "reviewer_assurance", "rationale"):
        c.execute(f"ALTER TABLE apply_runs DROP COLUMN {col}")
    c.commit()
    c.close()
    import_sqlite(src, target)
    run = target.get_apply_run("run_a")
    assert run["reviewer"] is None and run["rationale"] is None and run["ack_outcome"] == "unknown"


def test_snapshot_works_while_source_is_open_with_wal(tmp_path, target):
    src = tmp_path / "src.db"
    make_source(src)
    live = Database(src)  # a running writer holding the WAL open
    try:
        live.insert_scan("scan_live", ENV, T, "ok", None)
        import_sqlite(src, target)
    finally:
        live.close()
    assert "scan_live" in {r["id"] for r in target.list_scans()}  # backup API saw the WAL contents


def test_cli_refuses_without_configured_postgres(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src.db"
    make_source(src)
    monkeypatch.delenv("BG_DATABASE_URL", raising=False)
    monkeypatch.setenv("BG_DB_PATH", str(tmp_path / "t.db"))
    assert cli.main(["import-sqlite", "--source", str(src)]) == 2
    assert "BG_DATABASE_URL" in capsys.readouterr().out
