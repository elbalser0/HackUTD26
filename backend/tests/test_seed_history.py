"""`breakglass seed-history`: a week of AUTHORED demo history for the presentation.

Offline. The data is labelled authored (evidence_source authored-fixture, its own
`<env>-authored` environment), never merges into live records, and never contains a
run without a recorded completion (an unknown outcome would be a real finding, not demo data).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from helpers import memdb

from breakglass import admin, cli, seed_history
from breakglass.db import Database
from breakglass.models import AckOutcome

NOW = datetime(2026, 11, 12, 15, 0, 0, tzinfo=timezone.utc)
ENV = "demo-authored"
TERMINAL = {o.value for o in AckOutcome} - {"pending", "running", "unknown"}


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


def _seed(db):
    return seed_history.seed_history(db, ENV, now=NOW)


def _events(db):
    return admin.log(db, limit=500).events


def test_summary_counts_match_the_database(db):
    s = _seed(db)
    rows = db.list_records(environment=ENV)
    assert s.records == len(rows)
    assert s.open == len([r for r in rows if r["resolution"] == "open"])
    assert s.needs_reason == len([r for r in rows if r["resolution"] == "open" and r["reason"] is None])
    assert s.runs == len(db.list_all_apply_runs())


def test_everything_is_labelled_authored_and_in_the_given_environment(db):
    _seed(db)
    rows = db.list_records()
    assert rows and all(r["environment"] == ENV and r["evidence_source"] == "authored-fixture" for r in rows)
    assert all(r["environment"] == ENV for r in db.list_all_apply_runs())


def test_a_week_of_history_with_a_realistic_mix(db):
    _seed(db)
    rows = db.list_records(environment=ENV)
    resolved = [r for r in rows if r["resolution"] == "resolved"]
    explained_open = [r for r in rows if r["resolution"] == "open" and r["reason"]]
    needs_reason = [r for r in rows if r["resolution"] == "open" and not r["reason"]]
    assert len(resolved) >= 4 and len(explained_open) >= 2 and len(needs_reason) >= 1
    assert len({r["resource_address"] for r in rows}) >= 3
    assert {r["change_kind"] for r in rows} >= {"added", "removed", "modified"}


def test_every_timestamp_is_inside_the_last_seven_days_and_spread_over_many_days(db):
    _seed(db)
    evs = _events(db)
    assert evs
    assert all(NOW - timedelta(days=7) <= e.at <= NOW for e in evs)
    assert len({e.at.date() for e in evs}) >= 5
    for r in db.list_records():
        for col in ("first_detected_at", "last_detected_at", "reported_at", "resolved_at"):
            if r[col]:
                assert NOW - timedelta(days=7) <= datetime.fromisoformat(r[col].replace("Z", "+00:00")) <= NOW


def test_runs_all_have_a_recorded_outcome_and_never_unknown(db):
    _seed(db)
    runs = db.list_all_apply_runs()
    assert len(runs) >= 4
    assert all(r["ack_outcome"] in TERMINAL and r["completed_at"] for r in runs)
    assert {r["ack_outcome"] for r in runs} >= {"kept", "cancelled"}
    assert any(r["ack_outcome"] in ("applied_no_warnings", "reverted_applied") for r in runs)
    evs = _events(db)
    assert not [e for e in evs if e.type == "run_unfinished"]
    assert not [e for e in evs if e.outcome is not None and e.outcome.value == "unknown"]


def test_no_timeline_reports_an_unknown_run(db):
    _seed(db)
    for r in db.list_records():
        tl = admin.timeline(db, r["id"])
        assert tl is not None
        assert not [g for g in tl.gaps if g.code == "run_outcome_unknown"]


def test_people_and_how_much_each_identity_can_be_trusted(db):
    _seed(db)
    evs = _events(db)
    actors = {e.actor for e in evs if e.actor}
    assert len(actors) >= 3
    assurances = {e.actor_assurance for e in evs if e.actor}
    assert any(a.startswith("google-account") for a in assurances)
    assert "self-reported" in assurances
    # no real people: verified accounts use the reserved example.com domain
    assert all(a.endswith("@example.com") for a in actors if "@" in a)


def test_a_second_run_refuses_and_writes_nothing(db):
    _seed(db)
    before = (len(db.list_records()), len(db.list_all_apply_runs()), len(_events(db)))
    with pytest.raises(seed_history.SeedHistoryRefused):
        _seed(db)
    assert (len(db.list_records()), len(db.list_all_apply_runs()), len(_events(db))) == before


def test_other_environments_are_untouched(db):
    from breakglass import service
    from helpers import load

    service.ingest_refresh_plan(db, "demo", load("refresh_drift_8443"))
    live = [dict(r) for r in db.list_records(environment="demo")]
    _seed(db)
    assert [dict(r) for r in db.list_records(environment="demo")] == live


def test_it_refuses_a_non_authored_environment(db):
    with pytest.raises(seed_history.SeedHistoryRefused):
        seed_history.seed_history(db, "demo", now=NOW)


# ---- CLI ---------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "cli.db"
    monkeypatch.setenv("BG_DB_PATH", str(p))
    monkeypatch.setenv("BG_NO_DOTENV", "1")
    monkeypatch.delenv("BG_DATABASE_URL", raising=False)
    return p


def test_cli_refuses_without_yes_and_says_where_it_would_write(db_path, capsys):
    assert cli.main(["seed-history"]) == 1
    out = capsys.readouterr().out
    assert "--yes" in out and str(db_path) in out
    d = Database(db_path)
    try:
        assert d.list_records() == []
    finally:
        d.close()


def test_cli_with_yes_seeds_and_prints_a_summary(db_path, capsys):
    assert cli.main(["seed-history", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "AUTHORED" in out and "records" in out
    d = Database(db_path)
    try:
        assert len(d.list_records()) >= 6
    finally:
        d.close()
    assert cli.main(["seed-history", "--yes"]) == 1  # already seeded
