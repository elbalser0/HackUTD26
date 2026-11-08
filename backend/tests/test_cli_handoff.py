"""End-to-end CLI handoff, offline: a reason captured at scan time must appear,
word for word, in the later guarded-apply warning (PRD §6 steps 3-6, R4/R5).
Authored fixtures and a fake Terraform runner only; nothing is applied."""

from __future__ import annotations

import io
import sys

import pytest

from helpers import ENV, FIX, FakeRunner, Script, load, make_tf, memdb

from breakglass import cli, service
from breakglass.db import Database
from breakglass.wrapper import guarded_apply

REASON = "payment webhook blocked during outage"
NAME = "Paul (demo)"
EXPLAINED = [REASON, NAME, "u"]  # scan-time answers: why, name, intent
SKIPPED = [""]


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


def _scan_and_answer(db, answers):
    rid = service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443"),
                                      evidence_source="authored-fixture").new_ids[0]
    it = iter(answers)
    cli.prompt_for_reasons(db, [rid], ask=lambda _: next(it), out=lambda _: None)
    return rid


def _apply_and_cancel(db, tmp_path):
    runner = FakeRunner()
    s = Script("c", "")  # cancel, no cancel rationale
    res = guarded_apply(db, make_tf(tmp_path, runner), ENV, prompt=s.prompt, out=s.out)
    return s, res, runner


def test_reason_from_scan_appears_in_apply_warning(db, tmp_path):
    rid = _scan_and_answer(db, EXPLAINED)
    s, res, runner = _apply_and_cancel(db, tmp_path)
    warn = [line for line in s.lines if line.strip().startswith("!")]
    assert any(REASON in line and NAME in line for line in warn), s.output
    assert runner.apply_calls == []
    kinds = [e["kind"] for e in db.list_events(record_id=rid)]
    assert "review" in kinds
    assert db.get_record(rid)["resolution"] == "open"


def test_skipped_reason_warns_no_reason_recorded(db, tmp_path):
    rid = _scan_and_answer(db, SKIPPED)
    s, res, runner = _apply_and_cancel(db, tmp_path)
    warn = [line for line in s.lines if line.strip().startswith("!")]
    assert any("no reason recorded" in line for line in warn), s.output
    assert runner.apply_calls == []
    row = db.get_record(rid)
    assert row["reason"] is None and row["resolution"] == "open"


class _Stdin(io.StringIO):
    def __init__(self, tty: bool, text: str = ""):
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "cli.db"
    monkeypatch.setenv("BG_DB_PATH", str(p))
    return p


def _scan_cmd():
    return ["scan", "--from-json", str(FIX / "refresh_drift_8443.json"), "--label", "authored-fixture"]


def test_scan_command_asks_for_reason_in_a_terminal(db_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=True, text="".join(a + "\n" for a in EXPLAINED)))
    assert cli.main(_scan_cmd()) == 0
    d = Database(db_path)
    try:
        (row,) = d.list_records(resolution="open")
    finally:
        d.close()
    assert row["reason"] == REASON and row["reporter"] == NAME


def test_scan_without_a_terminal_says_how_to_add_the_reason(db_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))
    assert cli.main(_scan_cmd()) == 0
    out = capsys.readouterr().out
    d = Database(db_path)
    try:
        (row,) = d.list_records(resolution="open")
    finally:
        d.close()
    assert row["reason"] is None
    assert "Not an interactive terminal" in out
    assert f"breakglass report {row['id']} --reason" in out


def test_no_prompt_flag_stays_quiet(db_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Stdin(tty=False))
    assert cli.main(_scan_cmd() + ["--no-prompt"]) == 0
    assert "Not an interactive terminal" not in capsys.readouterr().out
