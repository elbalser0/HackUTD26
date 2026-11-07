from breakglass.models import FirewallRule
from breakglass.suggest import suggest_literal_edit

ANY = ("0.0.0.0/0", "::/0")
B = FirewallRule("tcp", "8080", ANY)
O = FirewallRule("tcp", "8443", ANY)

TF = '''resource "digitalocean_droplet" "web" {
  name = "bg-demo-web"
}

resource "digitalocean_firewall" "web" {
  name        = "bg-demo-web"
  droplet_ids = [digitalocean_droplet.web.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["203.0.113.10/32"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "8080" # app
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "8080"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
'''


def test_finds_unique_line(tmp_path):
    (tmp_path / "main.tf").write_text(TF, encoding="utf-8")
    s = suggest_literal_edit(tmp_path, "digitalocean_firewall.web", B, O)
    assert s is not None
    assert "main.tf line 17" in s
    assert '-    port_range       = "8080" # app' in s
    assert '+    port_range       = "8443" # app' in s
    assert (tmp_path / "main.tf").read_text(encoding="utf-8") == TF  # never writes


def test_ambiguous_returns_none(tmp_path):
    dup = TF.replace('  outbound_rule {', '  inbound_rule {\n    port_range = "8080"\n  }\n\n  outbound_rule {')
    (tmp_path / "main.tf").write_text(dup, encoding="utf-8")
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.web", B, O) is None


def test_duplicate_across_files_returns_none(tmp_path):
    (tmp_path / "a.tf").write_text(TF, encoding="utf-8")
    (tmp_path / "b.tf").write_text(TF, encoding="utf-8")
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.web", B, O) is None


def test_module_and_indexed_addresses_return_none(tmp_path):
    (tmp_path / "main.tf").write_text(TF, encoding="utf-8")
    assert suggest_literal_edit(tmp_path, "module.edge.digitalocean_firewall.web", B, O) is None
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.web[0]", B, O) is None


def test_other_resource_name_or_non_port_change_returns_none(tmp_path):
    (tmp_path / "main.tf").write_text(TF, encoding="utf-8")
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.api", B, O) is None
    other_src = FirewallRule("tcp", "8443", ("198.51.100.0/24",))
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.web", B, other_src) is None
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.web", None, O) is None


def test_ignores_subdirectories_and_missing_dir(tmp_path):
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "main.tf").write_text(TF, encoding="utf-8")
    assert suggest_literal_edit(tmp_path, "digitalocean_firewall.web", B, O) is None
    assert suggest_literal_edit(tmp_path / "nope", "digitalocean_firewall.web", B, O) is None
