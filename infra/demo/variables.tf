variable "region" {
  description = "DigitalOcean region slug for the demo droplet."
  type        = string
  default     = "nyc3"
}

variable "droplet_size" {
  description = "Droplet size slug (smallest available by default)."
  type        = string
  default     = "s-1vcpu-512mb-10gb"
}

variable "ssh_key_name" {
  description = "Name of an SSH key ALREADY uploaded to the DigitalOcean account."
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "CIDRs allowed to reach SSH (tcp/22). Must not be open to the world."
  type        = list(string)

  validation {
    condition     = length(var.ssh_allowed_cidrs) > 0
    error_message = "ssh_allowed_cidrs must contain at least one CIDR."
  }

  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs : can(cidrhost(c, 0))])
    error_message = "Every entry in ssh_allowed_cidrs must be a valid CIDR (e.g. 203.0.113.10/32)."
  }

  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs : !contains(["0.0.0.0/0", "::/0"], c)])
    error_message = "ssh_allowed_cidrs must not include 0.0.0.0/0 or ::/0; restrict SSH to your own IP."
  }

  # Blocks "split" world-open ranges such as 0.0.0.0/1 + 128.0.0.0/1.
  validation {
    condition = alltrue([
      for c in var.ssh_allowed_cidrs :
      can(regex(":", c)) ? tonumber(split("/", c)[1]) >= 48 : tonumber(split("/", c)[1]) >= 24
    ])
    error_message = "ssh_allowed_cidrs entries must be narrow: IPv4 prefix /24 or longer, IPv6 /48 or longer."
  }
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "breakglass-demo"
}
