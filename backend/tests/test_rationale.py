"""Every wrapper decision carries a rationale (PRD §6 step 7, R6).

Keep REQUIRES one: without it the keep is not saved and the run
is cancelled (nothing applied either way). Cancel ASKS for one but never
requires it: cancelling is the safe default and must never be blocked.
"""

from __future__ import annotations

import json

import pytest

from helpers import ENV, FakeRunner, Script, load, make_tf

from breakglass import service
from breakglass.db import Database
from breakglass.models import ReportIn
from breakglass.wrapper import guarded_apply


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "r.db")
    yield d
    d.close()


def open_record(db):
    rid = service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443")).new_ids[0]
    service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    return rid


def run(db, tmp_path, *answers):
    runner = FakeRunner()
    s = Script(*answers)
    res = guarded_apply(db, make_tf(tmp_path, runner), ENV, prompt=s.prompt, out=s.out, reviewer="Dana")
    return res, runner, s


def reviews(db, rid):
    return [json.loads(e["data_json"]) for e in db.list_events(record_id=rid) if e["kind"] == "review"]


@pytest.mark.parametrize("choice,decision,intent,outcome", [
    ("k", "keep", "keep", "kept"),
])
def test_keep_saves_the_rationale(db, tmp_path, choice, decision, intent, outcome):
    rid = open_record(db)
    res, runner, s = run(db, tmp_path, choice, "vendor still on 8443 until Friday")
    assert res.outcome == outcome and runner.apply_calls == []
    assert any("rationale" in p.lower() for p in s.prompts)
    rv = reviews(db, rid)
    assert [(r["decision"], r["rationale"]) for r in rv] == [(decision, "vendor still on 8443 until Friday")]
    assert db.get_record(rid)["intent"] == intent


@pytest.mark.parametrize("choice", ["k"])
@pytest.mark.parametrize("rationale", ["", "   ", "bad\x1b[2Kline"])
def test_keep_without_valid_rationale_is_not_saved(db, tmp_path, choice, rationale):
    rid = open_record(db)
    res, runner, s = run(db, tmp_path, choice, rationale)
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert db.get_record(rid)["intent"] == "unset", "keep must not be saved without a rationale"
    assert [r["decision"] for r in reviews(db, rid)] == ["cancel"]
    assert "rationale is required" in s.output


def test_cancel_asks_for_rationale_and_saves_it(db, tmp_path):
    rid = open_record(db)
    res, runner, s = run(db, tmp_path, "c", "need to ask Paul first")
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert [(r["decision"], r["rationale"]) for r in reviews(db, rid)] == [("cancel", "need to ask Paul first")]


def test_cancel_never_requires_a_rationale(db, tmp_path):
    rid = open_record(db)
    res, runner, s = run(db, tmp_path, "c", "")
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert [(r["decision"], r["rationale"]) for r in reviews(db, rid)] == [("cancel", None)]
    assert "rationale is required" not in s.output


def test_cancel_with_closed_input_still_cancels(db, tmp_path):
    # EOF at the rationale prompt (e.g. `< /dev/null`) must cancel, never block or apply.
    open_record(db)
    res, runner, _ = run(db, tmp_path, "c")
    assert res.outcome == "cancelled" and runner.apply_calls == []


def test_rationale_shown_in_prior_decisions(db, tmp_path):
    open_record(db)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    run(db, tmp_path / "a", "k", "vendor still on 8443")
    _, _, s = run(db, tmp_path / "b", "c", "")
    assert any("prior:" in l and "keep" in l and "vendor still on 8443" in l for l in s.lines)
