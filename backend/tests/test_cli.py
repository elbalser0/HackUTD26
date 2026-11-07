"""CLI tests. All offline: authored fixtures only, temp DB, no Terraform."""

from __future__ import annotations

from pathlib import Path

import pytest

from breakglass import cli, service
from breakglass.db import Database

FIX = Path(__file__).parent / "fixtures" / "authored"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "cli.db"
    monkeypatch.setenv("BG_DB_PATH", str(p))
    return p


def _open_rows(db_path):
    db = Database(db_path)
    try:
        return db.list_records(resolution="open")
    finally:
        db.close()


@pytest.mark.parametrize("line,expected", [
    ("Paul: payment webhook blocked", ("Paul", "payment webhook blocked")),
    ("Paul Smith: opened 8443", ("Paul Smith", "opened 8443")),
    ("opened 8443 for webhook", (None, "opened 8443 for webhook")),
    ("changed the firewall because of the outage: webhooks failing", (None, "changed the firewall because of the outage: webhooks failing")),
])
def test_one_line_parsing(line, expected):
    assert cli._parse_one_line(line) == expected


def test_seed_demo_is_labeled_authored(db_path, capsys):
    assert cli.main(["seed-demo"]) == 0
    rows = _open_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["evidence_source"] == "authored-fixture"
    assert rows[0]["reason"] is None
    assert "AUTHORED" in capsys.readouterr().out


def test_seed_demo_with_report(db_path):
    assert cli.main(["seed-demo", "--with-report"]) == 0
    row = _open_rows(db_path)[0]
    assert row["reporter"] == "Paul" and row["intent"] == "keep"


def test_scan_from_json_dedups(db_path):
    assert cli.main(["scan", "--from-json", str(FIX / "refresh_drift_8443.json"), "--label", "authored-fixture", "--no-prompt"]) == 0
    assert cli.main(["scan", "--from-json", str(FIX / "refresh_drift_reordered.json"), "--label", "authored-fixture", "--no-prompt"]) == 0
    assert len(_open_rows(db_path)) == 1


def test_scan_malformed_fails_loudly(db_path, capsys):
    code = cli.main(["scan", "--from-json", str(FIX / "refresh_malformed.json"), "--label", "authored-fixture", "--no-prompt"])
    out = capsys.readouterr().out
    assert code == 1
    assert "SCAN FAILED" in out and "NOT 'no drift'" in out


def test_prompt_for_reasons_one_line(tmp_path):
    db = Database(tmp_path / "p.db")
    res = service.ingest_refresh_plan(db, "demo", cli._load_json(str(FIX / "refresh_drift_8443.json")))
    answers = iter(["Paul: payment webhook blocked", "k"])
    lines: list[str] = []
    cli.prompt_for_reasons(db, res.new_ids, ask=lambda _: next(answers), out=lines.append)
    row = db.get_record(res.new_ids[0])
    assert (row["reporter"], row["reason"], row["intent"]) == ("Paul", "payment webhook blocked", "keep")
    assert any("8080" in l and "8443" in l for l in lines), "prompt must be pre-filled with the change"


def test_prompt_skip_leaves_reason_null(tmp_path):
    db = Database(tmp_path / "p.db")
    res = service.ingest_refresh_plan(db, "demo", cli._load_json(str(FIX / "refresh_drift_8443.json")))
    lines: list[str] = []
    cli.prompt_for_reasons(db, res.new_ids, ask=lambda _: "", out=lines.append)
    assert db.get_record(res.new_ids[0])["reason"] is None
    assert any("no reason recorded" in l for l in lines)


def test_decide_does_not_resolve(db_path):
    cli.main(["seed-demo"])
    rid = _open_rows(db_path)[0]["id"]
    assert cli.main(["decide", rid, "revert"]) == 0
    row = _open_rows(db_path)[0]
    assert row["intent"] == "revert" and row["resolution"] == "open"


def test_recheck_requires_both_jsons(db_path):
    with pytest.raises(SystemExit):
        cli.main(["recheck", "--refresh-json", str(FIX / "refresh_no_drift.json")])


def test_reset_requires_yes(db_path):
    cli.main(["seed-demo"])
    assert cli.main(["reset-db"]) == 1
    assert len(_open_rows(db_path)) == 1
    assert cli.main(["reset-db", "--yes"]) == 0
    assert _open_rows(db_path) == []


def test_tf_dir_outside_infra_rejected(db_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BG_TF_DIR", str(tmp_path))
    monkeypatch.delenv("BG_ALLOW_TF_DIR_OUTSIDE_REPO", raising=False)
    assert cli.main(["list"]) == 2
    assert "config error" in capsys.readouterr().out


def test_from_json_requires_label(db_path):
    with pytest.raises(SystemExit):
        cli.main(["scan", "--from-json", str(FIX / "refresh_drift_8443.json"), "--no-prompt"])
    with pytest.raises(SystemExit):
        cli.main(["recheck", "--refresh-json", str(FIX / "refresh_no_drift.json"),
                  "--plan-json", str(FIX / "plan_reverts_8443.json")])


def test_authored_seed_never_merges_into_live_records(db_path):
    # Security review H1: identical authored and live evidence must stay separate,
    # so authored "Paul" text can never explain a real console change.
    assert cli.main(["seed-demo", "--with-report"]) == 0
    db = Database(db_path)
    try:
        live = service.ingest_refresh_plan(db, "demo", cli._load_json(str(FIX / "refresh_drift_8443.json")),
                                           evidence_source="terraform-refresh-only")
        assert len(live.new_ids) == 1, "live scan must create its own record"
        row = db.get_record(live.new_ids[0])
        assert row["reason"] is None and row["evidence_source"] == "terraform-refresh-only"
        authored = [r for r in db.list_records() if r["evidence_source"] == "authored-fixture"]
        assert len(authored) == 1 and authored[0]["environment"] == "demo-authored"
    finally:
        db.close()


def test_offline_recheck_only_touches_fixture_environment(db_path):
    db = Database(db_path)
    try:
        live = service.ingest_refresh_plan(db, "demo", cli._load_json(str(FIX / "refresh_drift_8443.json")))
    finally:
        db.close()
    assert cli.main(["recheck", "--refresh-json", str(FIX / "refresh_no_drift.json"),
                     "--plan-json", str(FIX / "plan_no_changes.json"), "--label", "authored-fixture"]) == 0
    db = Database(db_path)
    try:
        assert db.get_record(live.new_ids[0])["resolution"] == "open"
    finally:
        db.close()
