import json
from pathlib import Path

from breakglass.detector import detect, is_refresh_only_plan
from breakglass.models import ChangeKind, FirewallRule

FIX = Path(__file__).parent / "fixtures" / "authored"
ANY = ("0.0.0.0/0", "::/0")


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_all_authored_fixtures_are_labeled():
    for p in FIX.glob("*.json"):
        assert json.loads(p.read_text(encoding="utf-8"))["_fixture_note"].startswith("AUTHORED")


def test_authored_fixture_direction_baseline_8080_observed_8443():
    """Authored fixture direction: drift before = state (8080), after = live (8443)."""
    r = detect(load("refresh_drift_8443.json"))
    assert r.errors == [] and r.unsupported == []
    assert len(r.observations) == 1
    o = r.observations[0]
    assert o.resource_address == "digitalocean_firewall.web"
    assert o.resource_type == "digitalocean_firewall"
    assert o.attribute == "inbound_rule"
    assert o.kind == ChangeKind.MODIFIED
    assert o.baseline == FirewallRule("tcp", "8080", ANY)
    assert o.observed == FirewallRule("tcp", "8443", ANY)


def test_reordered_rules_produce_identical_observations():
    assert detect(load("refresh_drift_reordered.json")) == detect(load("refresh_drift_8443.json"))


def test_no_drift():
    r = detect(load("refresh_no_drift.json"))
    assert r.observations == [] and r.unsupported == [] and r.errors == []
    assert is_refresh_only_plan(load("refresh_no_drift.json"))


def test_unknown_and_sensitive_are_unsupported_not_observations():
    r = detect(load("refresh_unknown.json"))
    assert r.observations == [] and r.errors == []
    assert len(r.unsupported) == 2
    assert any("digitalocean_firewall.web" in u for u in r.unsupported)
    assert any("digitalocean_firewall.api" in u for u in r.unsupported)


def test_unrelated_attribute_drift_is_unsupported():
    r = detect(load("refresh_unrelated_attr.json"))
    assert r.observations == [] and r.errors == []
    assert sorted(r.unsupported) == [
        "digitalocean_firewall.web: drift in name not supported",
        "digitalocean_firewall.web: drift in tags not supported",
    ]


def test_malformed_entries_are_errors():
    r = detect(load("refresh_malformed.json"))
    assert len(r.errors) == 3 and r.observations == []


def test_malformed_top_level():
    assert detect([]).errors
    assert detect({"resource_drift": {"a": 1}}).errors
    assert detect({}).errors == [] and detect({"resource_drift": None}).errors == []


def test_other_resource_type_and_delete_are_unsupported():
    plan = load("refresh_drift_8443.json")
    drift = plan["resource_drift"][0]
    droplet = dict(drift, address="digitalocean_droplet.web", type="digitalocean_droplet")
    deleted = json.loads(json.dumps(drift))
    deleted["change"]["actions"] = ["delete"]
    deleted["change"]["after"] = None
    r = detect({"resource_drift": [droplet, deleted]})
    assert r.observations == [] and r.errors == []
    assert len(r.unsupported) == 2


def test_null_inbound_rule_after_is_unsupported():
    plan = load("refresh_drift_8443.json")
    plan["resource_drift"][0]["change"]["after"]["inbound_rule"] = None
    r = detect(plan)
    assert r.observations == [] and len(r.unsupported) == 1


def test_added_and_removed_observations():
    plan = load("refresh_drift_8443.json")
    after = plan["resource_drift"][0]["change"]["after"]
    after["inbound_rule"] = [r for r in after["inbound_rule"] if r["port_range"] != "22"] + [
        {"protocol": "udp", "port_range": "51820", "source_addresses": ["198.51.100.0/24"]}
    ]
    plan["resource_drift"][0]["change"]["before_sensitive"] = {}
    plan["resource_drift"][0]["change"]["after_sensitive"] = {}
    kinds = [o.kind for o in detect(plan).observations]
    assert kinds == [ChangeKind.MODIFIED, ChangeKind.REMOVED, ChangeKind.ADDED]


def test_is_refresh_only_plan():
    assert not is_refresh_only_plan(load("plan_reverts_8443.json"))
    assert not is_refresh_only_plan("x")
