"""`breakglass demo-reset`: wipe local demo data and run a read-only preflight.

Guarantees under test:
- nothing is deleted without explicit confirmation;
- the cloud check is a refresh-only plan that is never applied and never
  ingested (the database stays empty after a reset);
- a failed check is reported as "could not verify", never as clean;
- the token is only checked for presence, never printed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from helpers import ENV, FakeRunner, Script, load, load_text, make_tf

from breakglass import demo, service
from breakglass.config import load_settings
from breakglass.db import Database
from breakglass.models import ReportIn


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "demo.db")
    yield d
    d.close()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("BG_TF_DIR", raising=False)
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "dop_v1_fake_for_tests")
    return replace(load_settings(), environment=ENV, admin_token="admin-test-token")


def populated(db):
    rid = service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443")).new_ids[0]
    service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    return rid


def reset(db, settings, tmp_path, *answers, yes=False, check_cloud=True, api_ok=True, **runner_kw):
    runner = FakeRunner(**runner_kw)
    tf = make_tf(tmp_path, runner)
    s = Script(*answers)
    code = demo.demo_reset(db, settings, tf, prompt=s.prompt, out=s.out, yes=yes, check_cloud=check_cloud,
                           api_health=(lambda: api_ok))
    return code, runner, s


def counts(db):
    c = db._conn
    return tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("records", "events", "apply_runs"))


def test_declining_confirmation_deletes_nothing_and_runs_no_terraform(db, settings, tmp_path):
    populated(db)
    before = counts(db)
    code, runner, s = reset(db, settings, tmp_path, "no")
    assert code == 1 and counts(db) == before
    assert runner.calls == []
    assert "Nothing deleted" in s.output


def test_typing_reset_wipes_records_history_and_runs(db, settings, tmp_path):
    populated(db)
    code, _, _ = reset(db, settings, tmp_path, "reset", scan_exit=0, scan_json=load_text("refresh_no_drift"))
    assert counts(db) == (0, 0, 0)
    assert code == 0


def test_clean_firewall_reports_clean(db, settings, tmp_path):
    code, runner, s = reset(db, settings, tmp_path, yes=True, scan_exit=0, scan_json=load_text("refresh_no_drift"))
    assert code == 0 and "clean" in s.output.lower()
    assert runner.apply_calls == []


def test_leftover_drift_is_listed_with_console_instruction_and_not_ingested(db, settings, tmp_path):
    code, runner, s = reset(db, settings, tmp_path, yes=True)  # default scan = refresh_drift_8443
    assert code == 2
    assert "8443" in s.output and "console" in s.output.lower()
    assert counts(db) == (0, 0, 0), "the preflight scan must not create records"
    assert runner.apply_calls == []


def test_refresh_only_plan_is_used_and_never_applied(db, settings, tmp_path):
    _, runner, _ = reset(db, settings, tmp_path, yes=True, scan_exit=0, scan_json=load_text("refresh_no_drift"))
    plans = [c[0] for c in runner.calls if len(c[0]) > 1 and c[0][1] == "plan"]
    assert plans and all("-refresh-only" in p for p in plans)
    assert runner.apply_calls == []
    assert not any((tmp_path / n).exists() for n in (".breakglass-scan.tfplan", ".breakglass-apply.tfplan"))


def test_failed_cloud_check_is_could_not_verify_not_clean(db, settings, tmp_path):
    code, _, s = reset(db, settings, tmp_path, yes=True, scan_exit=1)
    assert code == 1
    assert "could not verify" in s.output.lower() and "clean" not in s.output.lower()


def test_malformed_scan_is_could_not_verify(db, settings, tmp_path):
    code, _, s = reset(db, settings, tmp_path, yes=True, scan_json=load_text("refresh_malformed"))
    assert code == 1 and "could not verify" in s.output.lower()


def test_skip_cloud_check_runs_no_terraform(db, settings, tmp_path):
    code, runner, s = reset(db, settings, tmp_path, yes=True, check_cloud=False)
    assert runner.calls == [] and code == 0
    assert "skipped" in s.output.lower()


def test_missing_admin_token_and_api_are_warnings(db, settings, tmp_path):
    no_admin = replace(settings, admin_token=None)
    code, _, s = reset(db, no_admin, tmp_path, yes=True, api_ok=False,
                       scan_exit=0, scan_json=load_text("refresh_no_drift"))
    out = s.output
    assert "BG_ADMIN_TOKEN" in out and "API" in out
    assert code == 0, "warnings alone do not fail the reset"


def test_missing_do_token_is_reported_and_value_never_printed(db, settings, tmp_path, monkeypatch):
    _, _, s = reset(db, settings, tmp_path, yes=True, scan_exit=0, scan_json=load_text("refresh_no_drift"))
    assert "dop_v1_fake_for_tests" not in s.output
    monkeypatch.delenv("DIGITALOCEAN_TOKEN")
    monkeypatch.setenv("BG_DO_TOKEN_FILE", str(tmp_path / "missing_token"))
    _, _, s2 = reset(db, settings, tmp_path, yes=True, check_cloud=False)
    assert "DIGITALOCEAN_TOKEN" in s2.output and "not found" in s2.output.lower()
