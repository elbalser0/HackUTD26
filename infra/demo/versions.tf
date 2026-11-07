terraform {
  required_version = ">= 1.6"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.107"
    }
  }
}

# Token is read from the DIGITALOCEAN_TOKEN environment variable.
# Never put a token in this configuration or in tfvars.
provider "digitalocean" {}
