import pytest

from helpers import ENV, load, memdb, plan_noop_with_firewall, plan_without_firewall, refresh_variant_9443

from breakglass import service
from breakglass.models import DecisionIn, Intent


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


@pytest.fixture
def rid(db):
    return service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443")).new_ids[0]


def recheck(db, refresh, normal):
    r = load(refresh) if isinstance(refresh, str) else refresh
    n = load(normal) if isinstance(normal, str) else normal
    return service.recheck(db, ENV, r, n)


def test_drift_still_present_not_resolved(db, rid):
    out = recheck(db, "refresh_drift_8443", "plan_reverts_8443")
    assert out.status == "ok" and out.resolved_ids == []
    assert rid in out.still_open
    row = db.get_record(rid)
    assert row["resolution"] == "open" and row["last_check_status"] == "current"


def test_no_drift_but_config_still_reverses_not_resolved(db, rid):
    # State was updated (refresh-only apply) to 8443, but IaC still says 8080.
    out = recheck(db, "refresh_no_drift", "plan_reverts_8443")
    assert out.resolved_ids == []
    assert "reverse" in out.still_open[rid]
    row = db.get_record(rid)
    assert row["resolution"] == "open" and row["last_check_status"] == "current"


def test_no_drift_and_noop_plan_with_address_resolves(db, rid):
    # CRAFTED no-op normal plan: firewall.web present, before == after with 8443.
    out = recheck(db, "refresh_no_drift", plan_noop_with_firewall("8443"))
    assert out.status == "ok" and out.resolved_ids == [rid]
    row = db.get_record(rid)
    assert row["resolution"] == "resolved"
    assert row["resolution_reason"] == "verified_aligned"
    assert row["resolved_at"] is not None and row["last_check_status"] == "current"


def test_no_drift_and_authored_no_changes_plan_resolves(db, rid):
    out = recheck(db, "refresh_no_drift", "plan_no_changes")
    assert out.resolved_ids == [rid]


def test_no_drift_plan_without_address_unsupported(db, rid):
    # CRAFTED: normal plan containing only the droplet.
    out = recheck(db, "refresh_no_drift", plan_without_firewall())
    assert out.resolved_ids == []
    row = db.get_record(rid)
    assert row["resolution"] == "open" and row["last_check_status"] == "unsupported"


def test_refresh_malformed_failed_not_resolved(db, rid):
    out = recheck(db, "refresh_malformed", plan_noop_with_firewall())
    assert out.status == "failed" and out.resolved_ids == []
    row = db.get_record(rid)
    assert row["resolution"] == "open" and row["last_check_status"] == "failed"


def test_normal_plan_malformed_failed_not_resolved(db, rid):
    out = recheck(db, "refresh_no_drift", load("refresh_malformed") | {"resource_changes": [5, "x"]})
    assert out.status == "failed" and out.resolved_ids == []
    row = db.get_record(rid)
    assert row["resolution"] == "open" and row["last_check_status"] == "failed"


def test_normal_plan_not_object_failed(db, rid):
    out = service.recheck(db, ENV, load("refresh_no_drift"), "garbage")
    assert out.status == "failed" and db.get_record(rid)["resolution"] == "open"


def test_unknown_refresh_evidence_unsupported(db, rid):
    out = recheck(db, "refresh_unknown", plan_noop_with_firewall())
    assert out.resolved_ids == []
    assert db.get_record(rid)["last_check_status"] == "unsupported"


def test_after_unknown_plan_not_resolved(db, rid):
    out = recheck(db, "refresh_no_drift", "plan_after_unknown")
    assert out.resolved_ids == []
    assert db.get_record(rid)["resolution"] == "open"


@pytest.mark.parametrize("intent", [Intent.KEEP, Intent.REVERT])
def test_intent_alone_never_resolves(db, rid, intent):
    service.decide(db, rid, DecisionIn(intent=intent))
    # Evidence unchanged: drift still present and plan still reverses.
    out = recheck(db, "refresh_drift_8443", "plan_reverts_8443")
    assert out.resolved_ids == []
    row = db.get_record(rid)
    assert row["resolution"] == "open" and row["intent"] == intent.value


def test_rechanged_live_value_is_not_verified_aligned(db, rid):
    # CRAFTED refresh: declared 8080 now live as 9443. CRAFTED normal plan: no-op
    # over the current object (whatever config is, 8443 is not reversed).
    out = recheck(db, refresh_variant_9443(), plan_noop_with_firewall("9443"))
    row = db.get_record(rid)
    assert rid not in out.resolved_ids
    assert row["resolution_reason"] != "verified_aligned"
