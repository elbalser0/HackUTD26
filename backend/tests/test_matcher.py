import json
from pathlib import Path

from breakglass.matcher import match, summarize_changes
from breakglass.models import ChangeKind, FirewallRule, MatchCandidate

FIX = Path(__file__).parent / "fixtures" / "authored"
ANY = ("0.0.0.0/0", "::/0")
ADDR = "digitalocean_firewall.web"
R8080 = FirewallRule("tcp", "8080", ANY, action="allow")
R8443 = FirewallRule("tcp", "8443", ANY, action="allow")
SSH = FirewallRule("tcp", "22", ("203.0.113.10/32",), action="allow")


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


MODIFIED = MatchCandidate("rec_mod", ADDR, ChangeKind.MODIFIED, R8080, R8443)
ADDED = MatchCandidate("rec_add", ADDR, ChangeKind.ADDED, None, R8443)


def test_true_reversal():
    r = match(load("plan_reverts_8443.json"), [MODIFIED, ADDED])
    assert r.errors == []
    assert r.reversed_ids == ["rec_mod", "rec_add"] and r.unknown_ids == []
    assert [(c.resource_address, c.actions, c.summary) for c in r.proposed_changes] == [
        (ADDR, ("update",), "update inbound_rule: -tcp 8443, +tcp 8080")
    ]


def test_same_resource_unrelated_change_not_reversed():
    r = match(load("plan_unrelated_same_resource.json"), [MODIFIED])
    assert r.reversed_ids == [] and r.unknown_ids == [] and r.errors == []
    assert r.proposed_changes[0].summary == "update name"


def test_other_resource_not_reversed():
    r = match(load("plan_other_resource.json"), [MODIFIED])
    assert r.reversed_ids == [] and r.unknown_ids == [] and r.errors == []
    assert [c.resource_address for c in r.proposed_changes] == ["digitalocean_droplet.web"]
    assert r.proposed_changes[0].summary == "update"


def test_no_changes():
    r = match(load("plan_no_changes.json"), [MODIFIED])
    assert r.reversed_ids == [] and r.unknown_ids == [] and r.proposed_changes == []


def test_replace_reverses():
    r = match(load("plan_replace_firewall.json"), [MODIFIED])
    assert r.reversed_ids == ["rec_mod"]
    pc = r.proposed_changes[0]
    assert pc.actions == ("delete", "create")
    assert pc.summary == "replace inbound_rule: -tcp 8443, +tcp 8080"


def test_replace_keeping_rule_is_not_reversed():
    plan = load("plan_replace_firewall.json")
    plan["resource_changes"][0]["change"]["after"]["inbound_rule"].append(
        {"action": "allow", "protocol": "tcp", "port_range": "8443", "source_addresses": list(ANY)})
    assert match(plan, [MODIFIED]).reversed_ids == []


def test_pure_delete_reverses():
    plan = load("plan_reverts_8443.json")
    ch = plan["resource_changes"][0]["change"]
    ch["actions"], ch["after"] = ["delete"], None
    assert match(plan, [MODIFIED]).reversed_ids == ["rec_mod"]


def test_after_unknown_is_unknown():
    r = match(load("plan_after_unknown.json"), [MODIFIED])
    assert r.reversed_ids == [] and r.unknown_ids == ["rec_mod"] and r.errors == []


def test_removed_kind_reversal():
    # Someone removed the ssh rule in the console; the plan re-adds it.
    plan = load("plan_reverts_8443.json")
    ch = plan["resource_changes"][0]["change"]
    ch["before"]["inbound_rule"] = [r for r in ch["before"]["inbound_rule"] if r["port_range"] != "22"]
    cand = MatchCandidate("rec_rm", ADDR, ChangeKind.REMOVED, SSH, None)
    assert match(plan, [cand]).reversed_ids == ["rec_rm"]
    # Without the removal being live, re-adding isn't a reversal.
    assert match(load("plan_reverts_8443.json"), [cand]).reversed_ids == []


def test_address_mismatch_never_counts():
    cand = MatchCandidate("rec_x", "module.edge.digitalocean_firewall.web", ChangeKind.MODIFIED, R8080, R8443)
    r = match(load("plan_reverts_8443.json"), [cand])
    assert r.reversed_ids == [] and r.unknown_ids == []


def test_malformed_plan_claims_nothing():
    for bad in ([], {"resource_changes": "x"}, {"resource_changes": [{"address": ADDR}]},
                {"resource_changes": [{"address": ADDR, "type": "digitalocean_firewall",
                                       "change": {"actions": "update"}}]}):
        r = match(bad, [MODIFIED])
        assert r.errors and r.reversed_ids == [] and r.unknown_ids == [] and r.proposed_changes == []


def test_unparsable_rules_are_unknown():
    plan = load("plan_reverts_8443.json")
    plan["resource_changes"][0]["change"]["after"]["inbound_rule"] = [{"protocol": ["tcp"]}]
    assert match(plan, [MODIFIED]).unknown_ids == ["rec_mod"]


def test_summarize_skips_noop_and_malformed():
    assert summarize_changes(load("plan_no_changes.json")) == []
    assert summarize_changes("nope") == []
