output "droplet_ipv4" {
  description = "Public IPv4 address of the demo droplet."
  value       = digitalocean_droplet.demo.ipv4_address
}

output "firewall_id" {
  description = "ID of the demo firewall."
  value       = digitalocean_firewall.web.id
}

output "firewall_address" {
  description = "Terraform resource address the backend matches on."
  value       = "digitalocean_firewall.web"
}

output "service_url" {
  description = "URL of the payment-webhook service (port 8443, blocked until the console edit)."
  value       = "http://${digitalocean_droplet.demo.ipv4_address}:8443/"
}
