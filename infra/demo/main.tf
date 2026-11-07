data "digitalocean_ssh_key" "demo" {
  name = var.ssh_key_name
}

resource "digitalocean_droplet" "demo" {
  name       = "${var.name_prefix}-web"
  image      = "ubuntu-24-04-x64"
  size       = var.droplet_size
  region     = var.region
  ssh_keys   = [data.digitalocean_ssh_key.demo.id]
  tags       = [] # intentionally empty: the token may lack tag scopes
  user_data  = file("${path.module}/user_data.sh")
  monitoring = false
  ipv6       = false
}

# The backend matches this exact address: digitalocean_firewall.web
resource "digitalocean_firewall" "web" {
  name        = "${var.name_prefix}-web"
  droplet_ids = [digitalocean_droplet.demo.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.ssh_allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "8080" # declared app port — the break-glass demo changes this to 8443 in the console
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
