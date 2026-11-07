from breakglass.models import ChangeKind, FirewallRule
from breakglass.rules import describe_rule, diff_rules, normalize_rule, rule_set

ANY = ["0.0.0.0/0", "::/0"]


def R(port, proto="tcp", addrs=("0.0.0.0/0", "::/0"), **kw):
    return FirewallRule(protocol=proto, port_range=port, source_addresses=tuple(sorted(addrs)), **kw)


def test_normalize_basic_and_types():
    r = normalize_rule({
        "protocol": " TCP ", "port_range": 8080, "source_addresses": ["::/0", "0.0.0.0/0", "::/0"],
        "source_droplet_ids": [3, 1], "source_tags": None,
    })
    assert r == FirewallRule("tcp", "8080", ("0.0.0.0/0", "::/0"), (), ("1", "3"), (), ())


def test_normalize_rejects_non_dict_and_bad_fields():
    assert normalize_rule(None) is None
    assert normalize_rule(["tcp"]) is None
    assert normalize_rule({"protocol": {"x": 1}}) is None
    assert normalize_rule({"protocol": "tcp", "source_addresses": "0.0.0.0/0"}) is None
    assert normalize_rule({"protocol": "tcp", "port_range": True}) is None


def test_normalize_missing_fields_are_unknown():
    r = normalize_rule({})
    assert r.protocol is None and r.port_range is None and r.source_addresses == ()


def test_rule_set_order_invariance_and_dedup():
    a = [{"protocol": "tcp", "port_range": "22", "source_addresses": ["203.0.113.10/32"]},
         {"protocol": "tcp", "port_range": "8443", "source_addresses": ANY}]
    b = [{"protocol": "tcp", "port_range": "8443", "source_addresses": list(reversed(ANY))},
         {"protocol": "TCP", "port_range": "22", "source_addresses": ["203.0.113.10/32", "203.0.113.10/32"]},
         {"protocol": "tcp", "port_range": "8443", "source_addresses": ANY}]
    sa, oka = rule_set(a)
    sb, okb = rule_set(b)
    assert oka and okb and sa == sb and len(sb) == 2


def test_rule_set_not_ok():
    assert rule_set(None) == (frozenset(), False)
    assert rule_set({"protocol": "tcp"})[1] is False
    assert rule_set([{"protocol": "tcp"}, "junk"])[1] is False
    assert rule_set([]) == (frozenset(), True)


def test_describe_rule():
    assert describe_rule(R("8443")) == "inbound tcp port 8443 from 0.0.0.0/0, ::/0"
    assert describe_rule(FirewallRule(None, None)) == "inbound unknown protocol port unknown from no sources"
    s = describe_rule(FirewallRule("tcp", "8000-9000", (), ("web",), ("42",)))
    assert s == "inbound tcp ports 8000-9000 from tag:web, droplet:42"
    assert describe_rule(FirewallRule("icmp", None, ("192.0.2.0/24",))) == "inbound icmp from 192.0.2.0/24"


def test_diff_modified_pairing():
    ssh = R("22", addrs=("203.0.113.10/32",))
    d = diff_rules(frozenset({R("8080"), ssh}), frozenset({R("8443"), ssh}))
    assert d == [(ChangeKind.MODIFIED, R("8080"), R("8443"))]


def test_diff_ambiguous_pairing_is_not_modified():
    d = diff_rules(frozenset({R("8080"), R("9090")}), frozenset({R("8443")}))
    assert [k for k, _, _ in d] == [ChangeKind.REMOVED, ChangeKind.REMOVED, ChangeKind.ADDED]
    assert d[0][1] == R("8080") and d[1][1] == R("9090") and d[2][2] == R("8443")


def test_diff_different_sources_not_paired():
    d = diff_rules(frozenset({R("8080")}), frozenset({R("8443", addrs=("198.51.100.0/24",))}))
    assert [k for k, _, _ in d] == [ChangeKind.REMOVED, ChangeKind.ADDED]
    assert d[0][2] is None and d[1][1] is None


def test_diff_no_change():
    s = frozenset({R("8080")})
    assert diff_rules(s, s) == []
