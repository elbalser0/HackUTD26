import json

import pytest

from helpers import ENV, TF_BIN, FakeRunner, Script, load, load_text, make_tf, memdb

from breakglass import service
from breakglass.models import ReportIn
from breakglass.tfrunner import APPLY_PLAN, SCAN_PLAN
from breakglass.wrapper import guarded_apply

EXPECTED_APPLY_ARGS = [TF_BIN, "apply", "-input=false", "-lock-timeout=30s", APPLY_PLAN]


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


def open_record(db, reason=True):
    rid = service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443"), evidence_source="authored-fixture").new_ids[0]
    if reason:
        service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    return rid


def run(db, tmp_path, script, **runner_kw):
    runner = FakeRunner(**runner_kw)
    tf = make_tf(tmp_path, runner)
    res = guarded_apply(db, tf, ENV, prompt=script.prompt, out=script.out)
    return res, runner, tf


# ---- warnings path ---------------------------------------------------------

def test_keep_choice_kept_no_apply(db, tmp_path):
    rid = open_record(db)
    s = Script("k", "vendor still on 8443")
    res, runner, _ = run(db, tmp_path, s)
    assert res.outcome == "kept" and not res.applied
    assert runner.apply_calls == []
    assert db.get_record(rid)["intent"] == "keep"
    assert db.get_record(rid)["resolution"] == "open"
    assert "WARNING" in s.output and "payment webhook blocked" in s.output


def test_defer_choice_no_apply(db, tmp_path):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("d", "ask Paul tomorrow"))
    assert res.outcome == "deferred" and runner.apply_calls == []
    assert db.get_record(rid)["intent"] == "defer"


@pytest.mark.parametrize("answers", [("c",), ("zzz",), ()], ids=["cancel", "unknown", "eof"])
def test_cancel_unknown_eof_no_apply(db, tmp_path, answers):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script(*answers))
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert db.get_record(rid)["intent"] == "unset"


def test_revert_wrong_confirmation_saves_intent_no_apply(db, tmp_path):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("r", "yes"))
    assert res.outcome == "cancelled" and runner.apply_calls == []
    assert db.get_record(rid)["intent"] == "revert"
    assert db.get_apply_run(res.run_id)["ack_note"] == "revert intent saved, apply not confirmed"


def test_revert_confirmed_applies_once_with_exact_args(db, tmp_path):
    rid = open_record(db)
    res, runner, _ = run(db, tmp_path, Script("r", "revert", "webhook fixed upstream"))
    assert res.outcome == "reverted_applied" and res.applied
    assert runner.apply_calls == [EXPECTED_APPLY_ARGS]
    apply_call = [c for c in runner.calls if c[0][1] == "apply"][0]
    assert apply_call[1] == tmp_path and apply_call[3] is True  # cwd, stream
    assert db.get_record(rid)["resolution"] == "open"  # applying never resolves


def test_override_confirmed_applies_once(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("o", "override", "approved by lead"))
    assert res.outcome == "override_applied"
    assert runner.apply_calls == [EXPECTED_APPLY_ARGS]


def test_override_wrong_confirmation_cancels(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("o", "yes"))
    assert res.outcome == "cancelled" and runner.apply_calls == []


def test_missing_reason_still_warns(db, tmp_path):
    open_record(db, reason=False)
    s = Script("c")
    res, runner, _ = run(db, tmp_path, s)
    warn_lines = [line for line in s.lines if line.strip().startswith("!")]
    assert any("no reason recorded" in line for line in warn_lines)
    assert res.warnings and "no reason recorded" in res.warnings[0]


def test_apply_failure_exit_code(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("o", "override", "approved by lead"), apply_exit=1)
    assert res.outcome == "failed" and not res.applied
    assert len(runner.apply_calls) == 1


# ---- no-warning path -------------------------------------------------------

UNRELATED = dict(apply_json=load_text("plan_unrelated_same_resource"))


def test_unrelated_change_no_warning_no_cancels(db, tmp_path):
    open_record(db)
    s = Script("no")
    res, runner, _ = run(db, tmp_path, s, **UNRELATED)
    assert "WARNING" not in s.output
    assert "No open emergency changes" in s.output
    assert "'yes'" in s.prompts[-1]
    assert res.outcome == "cancelled" and runner.apply_calls == []


def test_unrelated_change_yes_applies(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("yes"), **UNRELATED)
    assert res.outcome == "applied_no_warnings" and res.warnings == []
    assert runner.apply_calls == [EXPECTED_APPLY_ARGS]


def test_plan_exit_0_no_changes(db, tmp_path):
    # No drift and no changes: nothing to do, no prompt.
    open_record(db)
    s = Script()
    res, runner, _ = run(db, tmp_path, s, apply_plan_exit=0, scan_exit=0, scan_json=load_text("refresh_no_drift"))
    assert res.outcome == "no_changes" and runner.apply_calls == []
    assert s.prompts == []


def test_no_changes_with_drift_offers_state_sync_declined(db, tmp_path):
    # 'keep' path: config already matches live, state still old. Declining applies nothing.
    open_record(db)
    s = Script("no")
    res, runner, _ = run(db, tmp_path, s, apply_plan_exit=0)
    assert res.outcome == "no_changes" and runner.apply_calls == []
    assert any("record the live values" in p for p in s.prompts)


def test_no_changes_with_drift_state_sync_confirmed_applies_exact_plan(db, tmp_path):
    open_record(db)
    s = Script("yes")
    res, runner, _ = run(db, tmp_path, s, apply_plan_exit=0)
    assert res.applied and len(runner.apply_calls) == 1
    assert runner.apply_calls[0][-1] == ".breakglass-apply.tfplan"


def test_plan_exit_1_failed(db, tmp_path):
    open_record(db)
    s = Script()
    res, runner, _ = run(db, tmp_path, s, apply_plan_exit=1)
    assert res.outcome == "failed" and runner.apply_calls == []
    assert s.prompts == []


# ---- verification unavailable ---------------------------------------------

def test_refresh_scan_fails_verification_unavailable_cancel(db, tmp_path):
    open_record(db)
    s = Script("yes")
    res, runner, _ = run(db, tmp_path, s, scan_exit=1)
    assert "VERIFICATION UNAVAILABLE" in s.output
    assert "No open emergency changes" not in s.output
    assert res.outcome == "cancelled" and res.check_status == "failed"
    assert runner.apply_calls == []


def test_refresh_scan_fails_bypass_applies(db, tmp_path):
    open_record(db)
    s = Script("unverified-bypass", "scan API down, change reviewed by hand")
    res, runner, _ = run(db, tmp_path, s, scan_exit=1)
    assert "VERIFICATION UNAVAILABLE" in s.output
    assert res.outcome == "unverified_bypass_applied" and res.check_status == "failed"
    assert runner.apply_calls == [EXPECTED_APPLY_ARGS]
    assert db.get_apply_run(res.run_id)["check_status"] == "failed"


def test_refresh_scan_malformed_json_verification_unavailable(db, tmp_path):
    open_record(db)
    s = Script("")
    res, runner, _ = run(db, tmp_path, s, scan_json=load_text("refresh_malformed"))
    assert "VERIFICATION UNAVAILABLE" in s.output
    assert res.outcome == "cancelled" and runner.apply_calls == []


def test_apply_plan_garbage_json_verification_unavailable(db, tmp_path):
    open_record(db)
    s = Script("yes")
    res, runner, _ = run(db, tmp_path, s, apply_json="this is not json{")
    assert "VERIFICATION UNAVAILABLE" in s.output
    assert "No open emergency changes" not in s.output
    assert res.outcome == "cancelled" and runner.apply_calls == []


# ---- integrity between review and apply -----------------------------------

def test_plan_file_modified_before_apply_aborts(db, tmp_path):
    open_record(db)

    def tamper():
        (tmp_path / APPLY_PLAN).write_bytes(b"TAMPERED")
        return "yes"

    res, runner, _ = run(db, tmp_path, Script(tamper), **UNRELATED)
    assert res.outcome == "aborted_plan_changed" and runner.apply_calls == []


def test_config_modified_before_apply_aborts(db, tmp_path):
    open_record(db)

    def edit_tf():
        (tmp_path / "main.tf").write_text("# edited\n", encoding="utf-8")
        return "yes"

    res, runner, _ = run(db, tmp_path, Script(edit_tf), **UNRELATED)
    assert res.outcome == "aborted_plan_changed" and runner.apply_calls == []


def test_workspace_changed_before_apply_aborts(db, tmp_path):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script("yes"), workspaces=["default", "prod"], **UNRELATED)
    assert res.outcome == "aborted_plan_changed" and runner.apply_calls == []


def test_non_tf_file_change_does_not_abort(db, tmp_path):
    open_record(db)

    def touch_readme():
        (tmp_path / "README.md").write_text("notes", encoding="utf-8")
        return "yes"

    res, runner, _ = run(db, tmp_path, Script(touch_readme), **UNRELATED)
    assert res.outcome == "applied_no_warnings" and len(runner.apply_calls) == 1


# ---- cleanup and persistence ----------------------------------------------

@pytest.mark.parametrize("answers", [("r", "revert", "why"), ("c",), ()])
def test_plan_files_deleted_after_run(db, tmp_path, answers):
    open_record(db)
    res, runner, _ = run(db, tmp_path, Script(*answers))
    assert runner.plan_files_seen  # plans were written during the run
    assert not (tmp_path / SCAN_PLAN).exists()
    assert not (tmp_path / APPLY_PLAN).exists()


def test_apply_run_row_persisted(db, tmp_path):
    rid = open_record(db)
    res, _, _ = run(db, tmp_path, Script("k", "vendor still on 8443"))
    row = db.get_apply_run(res.run_id)
    assert row["ack_outcome"] == "kept"
    assert row["completed_at"] is not None and row["completed_at"].endswith("Z")
    assert row["check_status"] == "current"
    assert row["plan_fingerprint"].startswith("sha256:")
    warnings = json.loads(row["warnings_json"])
    assert [w["record_id"] for w in warnings] == [rid]
    assert warnings[0]["reason"] == "payment webhook blocked"
    changes = json.loads(row["proposed_changes_json"])
    assert changes and changes[0]["resource_address"] == "digitalocean_firewall.web"
    assert changes[0]["actions"] == ["update"]
    assert "8443" in changes[0]["summary"]


def test_unsupported_drift_is_reported_not_checked(db, tmp_path):
    s = Script("no")
    res, runner, _ = run(db, tmp_path, s, scan_json=load_text("refresh_unrelated_attr"),
                         apply_json=load_text("plan_unrelated_same_resource"))
    assert "NOT CHECKED" in s.output
    assert "No open emergency changes are reversed" not in s.output
    assert runner.apply_calls == []


def test_interrupt_during_apply_is_failed_not_cancelled(db, tmp_path):
    open_record(db)
    s = Script("r", "revert", "why")
    runner = FakeRunner()
    tf = make_tf(tmp_path, runner)

    def boom(name):
        raise KeyboardInterrupt
    tf.apply_saved = boom
    res = guarded_apply(db, tf, ENV, prompt=s.prompt, out=s.out)
    assert res.outcome == "failed"
    assert "Nothing applied" not in s.output and "Live state is unknown" in s.output
    assert db.get_apply_run(res.run_id)["ack_note"].startswith("interrupted during apply")


def test_scan_failure_marks_open_records_failed(db, tmp_path):
    rid = open_record(db)
    s = Script()
    run(db, tmp_path, s, scan_exit=1)
    assert db.get_record(rid)["last_check_status"] == "failed"


def test_warning_output_strips_control_chars_from_legacy_rows(db, tmp_path):
    rid = open_record(db)
    db.update_record(rid, {"reason": "evil[2Kline"})  # row written before validation existed
    s = Script("c")
    run(db, tmp_path, s)
    assert "" not in s.output and "evil?[2Kline" in s.output
