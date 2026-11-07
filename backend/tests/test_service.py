from datetime import datetime, timedelta, timezone

import pytest

from helpers import ENV, load, memdb, refresh_other_address, refresh_variant_9443

from breakglass import service
from breakglass.db import Database
from breakglass.models import DecisionIn, Intent, ReportIn

T0 = datetime(2026, 11, 8, 3, 30, 12, tzinfo=timezone.utc)


def scan(db, name_or_plan, now=None, source="authored-fixture"):
    plan = load(name_or_plan) if isinstance(name_or_plan, str) else name_or_plan
    return service.ingest_refresh_plan(db, ENV, plan, evidence_source=source, now=now)


def all_rows(db):
    return db.list_records()


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


def test_scan_8443_creates_one_open_modified_record(db):
    out = scan(db, "refresh_drift_8443", now=T0)
    assert out.status == "ok" and len(out.new_ids) == 1
    rows = all_rows(db)
    assert len(rows) == 1
    rec = service.record_out(rows[0])
    assert rec.resolution == "open"
    assert rec.change_kind == "modified"
    assert rec.baseline_value.port_range == "8080"
    assert rec.observed_value.port_range == "8443"
    assert rec.reason is None and rec.reporter is None and rec.reported_at is None
    assert rec.intent == "unset"
    assert rec.evidence_source == "authored-fixture"
    assert rec.last_check_status == "current"
    assert rec.resource_address == "digitalocean_firewall.web"


def test_duplicate_scan_dedups_and_updates_last_detected(db):
    scan(db, "refresh_drift_8443", now=T0)
    out2 = scan(db, "refresh_drift_8443", now=T0 + timedelta(minutes=15))
    assert out2.new_ids == [] and len(out2.seen_ids) == 1
    rows = all_rows(db)
    assert len(rows) == 1
    assert rows[0]["first_detected_at"] == "2026-11-08T03:30:12.000000Z"
    assert rows[0]["last_detected_at"] == "2026-11-08T03:45:12.000000Z"


def test_reordered_fixture_dedups_across_provider_ordering(db):
    scan(db, "refresh_drift_8443", now=T0)
    out = scan(db, "refresh_drift_reordered", now=T0 + timedelta(minutes=1))
    assert out.new_ids == []
    assert len(all_rows(db)) == 1


def test_persistence_across_reopen(tmp_path):
    path = tmp_path / "bg.db"
    d1 = Database(path)
    scan(d1, "refresh_drift_8443", now=T0)
    rid = all_rows(d1)[0]["id"]
    service.report(d1, rid, ReportIn(reporter="Paul", reason="webhook blocked", intent=Intent.KEEP), now=T0)
    before = dict(d1.get_record(rid))
    d1.close()

    d2 = Database(path)
    try:
        row = d2.get_record(rid)
        assert row is not None
        assert dict(row) == before
        assert row["reason"] == "webhook blocked" and row["intent"] == "keep"
    finally:
        d2.close()


def test_superseding_changed_evidence_creates_new_record_and_resolves_old(db):
    scan(db, "refresh_drift_8443", now=T0)
    old_id = all_rows(db)[0]["id"]
    service.report(db, old_id, ReportIn(reporter="Paul", reason="opened 8443"), now=T0)

    # CRAFTED variant: live port 9443 instead of 8443 (same declared 8080 rule).
    out = scan(db, refresh_variant_9443(), now=T0 + timedelta(minutes=5))
    assert len(out.new_ids) == 1 and out.superseded_ids == [old_id]
    new_id = out.new_ids[0]

    old = db.get_record(old_id)
    assert old["resolution"] == "resolved"
    assert old["resolution_reason"] == "superseded"
    assert old["superseded_by"] == new_id
    assert old["reason"] == "opened 8443"  # stays on old record

    new = service.record_out(db.get_record(new_id))
    assert new.resolution == "open"
    assert new.observed_value.port_range == "9443"
    assert new.reason is None and new.reporter is None  # NOT copied forward


def test_malformed_scan_fails_marks_open_failed_no_new_records(db):
    scan(db, "refresh_drift_8443", now=T0)
    out = scan(db, "refresh_malformed", now=T0 + timedelta(minutes=1))
    assert out.status == "failed" and out.errors
    assert out.new_ids == []
    rows = all_rows(db)
    assert len(rows) == 1
    assert rows[0]["last_check_status"] == "failed"
    assert rows[0]["resolution"] == "open"


def test_record_not_drifting_later_goes_stale_not_resolved(db):
    scan(db, "refresh_drift_8443", now=T0)
    out = scan(db, "refresh_no_drift", now=T0 + timedelta(minutes=1))
    assert out.status == "ok" and len(out.stale_ids) == 1
    row = all_rows(db)[0]
    assert row["resolution"] == "open"
    assert row["last_check_status"] == "stale"
    assert row["resolution_reason"] is None


# ---- report / decide -----------------------------------------------------

def _one(db):
    scan(db, "refresh_drift_8443", now=T0)
    return all_rows(db)[0]["id"]


def test_report_sets_reporter_reason_reported_at(db):
    rid = _one(db)
    rec = service.report(db, rid, ReportIn(reporter="  Paul ", reason=" webhook blocked "), now=T0)
    assert rec.reporter == "Paul"
    assert rec.reason == "webhook blocked"
    assert rec.reported_at == T0
    assert rec.intent == "unset"  # intent optional, unchanged


def test_report_blank_reporter_is_null(db):
    rid = _one(db)
    rec = service.report(db, rid, ReportIn(reporter="   ", reason="x"))
    assert rec.reporter is None


def test_report_with_intent_sets_intent(db):
    rid = _one(db)
    rec = service.report(db, rid, ReportIn(reason="x", intent=Intent.KEEP))
    assert rec.intent == "keep" and rec.intent_updated_at is not None


def test_report_on_resolved_conflict(db):
    rid = _one(db)
    scan(db, refresh_variant_9443(), now=T0 + timedelta(minutes=1))  # supersedes rid
    with pytest.raises(service.Conflict):
        service.report(db, rid, ReportIn(reason="x"))


def test_report_unknown_not_found(db):
    with pytest.raises(service.NotFound):
        service.report(db, "rec_nope", ReportIn(reason="x"))


def test_decide_sets_intent_and_does_not_resolve(db):
    rid = _one(db)
    rec = service.decide(db, rid, DecisionIn(intent=Intent.REVERT, note=" done "))
    assert rec.intent == "revert" and rec.intent_note == "done"
    assert rec.resolution == "open" and rec.resolution_reason is None and rec.resolved_at is None


def test_warning_message_without_reason(db):
    rid = _one(db)
    msg = service.warning_message(db.get_record(rid))
    assert "no reason recorded" in msg
    assert "8443" in msg


def test_warning_message_with_reason(db):
    rid = _one(db)
    service.report(db, rid, ReportIn(reporter="Paul", reason="payment webhook blocked"))
    msg = service.warning_message(db.get_record(rid))
    assert "Paul" in msg
    assert "self-reported" in msg
    assert "payment webhook blocked" in msg
    assert "no reason recorded" not in msg


def test_list_records_newest_first_with_subsecond_timestamps(db):
    scan(db, "refresh_drift_8443", now=T0)  # microsecond == 0 -> "...:12.000000Z"
    later = T0 + timedelta(milliseconds=500)  # -> "...:12.500000Z"
    out = scan(db, refresh_other_address(), now=later)
    newest = out.new_ids[0]
    assert all_rows(db)[0]["id"] == newest
