terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

provider "digitalocean" {}

variable "droplet_id" {
  description = "Numeric ID of the existing demo Droplet"
  type        = number
}

variable "admin_ipv4_cidr" {
  description = "Your computer's public IPv4 address followed by /32"
  type        = string
}

variable "attach_firewall" {
  description = "Attach only after reviewing the firewall rules"
  type        = bool
  default     = false
}

resource "digitalocean_firewall" "demo" {
  name = "break-glass-demo"

  droplet_ids = var.attach_firewall ? [var.droplet_id] : []

  # Allow SSH only from your public IPv4 address.
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = [var.admin_ipv4_cidr]
  }

  # Allow outbound traffic for updates, DNS, and API requests.
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

output "firewall_id" {
  value = digitalocean_firewall.demo.id
}