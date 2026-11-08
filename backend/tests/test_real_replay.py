"""Replay of REAL Terraform captures (tests/fixtures/real, sanitized; see its README).

These pin what the 2026-11-07 spike established on real DigitalOcean output, so the detector, matcher and recheck are
checked against real shapes and not only hand-written ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import memdb

from breakglass import detector, matcher, service

REAL = Path(__file__).parent / "fixtures" / "real"
ENV = "demo-replay"  # real captures never share an environment with live records
FIRE = "digitalocean_firewall.demo"


def real(name: str) -> dict:
    return json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def db():
    d = memdb()
    yield d
    d.close()


def ingest(db, name):
    return service.ingest_refresh_plan(db, ENV, real(name), evidence_source="real-fixture")


# ---- H1: direction of before/after in a refresh-only plan ------------------

def test_h1_added_console_rule_is_observed_not_baseline():
    r = detector.detect(real("refresh_added_8443"))
    assert r.errors == []
    obs = [o for o in r.observations if o.attribute == "inbound_rule"]
    assert len(obs) == 1
    o = obs[0]
    assert o.kind.value == "added" and o.baseline is None
    assert (o.observed.action, o.observed.protocol, o.observed.port_range) == ("allow", "tcp", "8443")
    assert o.observed.source_addresses == ("0.0.0.0/0", "::/0")
    assert o.check_status.value == "current" and o.resource_address == FIRE


def test_real_refresh_only_plan_has_no_resource_changes_key():
    assert "resource_changes" not in real("refresh_added_8443")


def test_real_rules_carry_action_allow():
    for entry in real("refresh_added_8443")["resource_drift"]:
        for rule in entry["change"]["after"]["inbound_rule"]:
            assert rule["action"] == "allow"


def test_noise_only_capture_has_no_rule_observations():
    r = detector.detect(real("refresh_noise_only"))
    assert r.errors == [] and r.observations == []


def test_provider_noise_null_vs_empty_is_not_reported_as_unsupported_drift():
    """Real capture: droplet_ids/tags go null -> []. That must not be reported (it blocked recheck)."""
    assert detector.detect(real("refresh_noise_only")).unsupported == []


def test_a_real_tag_change_in_the_same_capture_is_still_reported():
    plan = real("refresh_noise_only")
    plan["resource_drift"][0]["change"]["after"]["tags"] = ["prod"]
    assert any("drift in tags" in u for u in detector.detect(plan).unsupported)


def test_a_real_detach_in_the_same_capture_is_still_reported():
    plan = real("refresh_noise_only")
    change = plan["resource_drift"][0]["change"]
    change["before"]["droplet_ids"] = [111111111]  # was attached in state, empty live
    assert any("drift in droplet_ids" in u for u in detector.detect(plan).unsupported)


# ---- H2: the normal plan reverses the console rule -------------------------

def test_h2_real_plan_reverses_the_recorded_rule(db):
    rid = ingest(db, "refresh_added_8443").new_ids[0]
    cands = [service.candidate(db.get_record(rid))]
    m = matcher.match(real("plan_reverts_8443"), cands)
    assert m.errors == [] and m.reversed_ids == [rid] and m.unknown_ids == []
    assert [(c.resource_address, c.actions) for c in m.proposed_changes] == [(FIRE, ("update",))]
    assert "8443" in m.proposed_changes[0].summary


def test_real_no_change_plan_reverses_nothing(db):
    rid = ingest(db, "refresh_added_8443").new_ids[0]
    m = matcher.match(real("plan_no_changes"), [service.candidate(db.get_record(rid))])
    assert m.errors == [] and m.reversed_ids == [] and m.unknown_ids == []


# ---- R11: closure only after verification, on real shapes ------------------

def test_recheck_keeps_record_open_while_rule_is_still_live(db):
    rid = ingest(db, "refresh_added_8443").new_ids[0]
    out = service.recheck(db, ENV, real("refresh_added_8443"), real("plan_reverts_8443"))
    assert rid in out.still_open and db.get_record(rid)["resolution"] == "open"


def test_recheck_resolves_after_rule_removed_despite_provider_noise(db):
    """Spike finding: the null -> [] noise on droplet_ids/tags made recheck report the resource as
    'not interpretable', so a record could never be closed on real data."""
    rid = ingest(db, "refresh_added_8443").new_ids[0]
    out = service.recheck(db, ENV, real("refresh_noise_only"), real("plan_no_changes"))
    row = db.get_record(rid)
    assert row["resolution"] == "resolved" and row["resolution_reason"] == "verified_aligned", out.still_open
