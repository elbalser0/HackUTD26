# Break-Glass Handoff — demo infrastructure

Terraform for the live demo: one small DigitalOcean droplet running a fake
"payment-webhook" service, plus the firewall the break-glass "incident" edits.

> **No cloud operation in this directory runs without explicit team approval.**
> Every step below that talks to DigitalOcean (`plan`, `apply`, `destroy`,
> console edits) needs a "yes" from the team first.

## What it creates

| Resource | Address | Notes |
|---|---|---|
| Droplet | `digitalocean_droplet.demo` | Ubuntu 24.04 (`ubuntu-24-04-x64`), size `s-1vcpu-512mb-10gb`, region `nyc3`. No tags, no monitoring, no IPv6. |
| Firewall | `digitalocean_firewall.web` | **The backend matches this exact address.** Inbound: tcp/22 from `ssh_allowed_cidrs`; tcp/8080 from anywhere (the *declared* app port). Outbound: all tcp/udp/icmp. |
| SSH key | `data.digitalocean_ssh_key.demo` | Lookup only — the key must already be uploaded to the account. |

`user_data.sh` starts a `python3 -m http.server` on **8443** that returns
`payment-webhook OK`. Nothing listens on 8080. So after `apply`, Terraform
believes 8080 is the app port, but the real service on 8443 is blocked by the
firewall — that is the "incident".

## Cost

Uses the smallest droplet size (`s-1vcpu-512mb-10gb`, a few dollars/month,
billed hourly). Firewalls are free. Destroy it as soon as the spike/demo is done.

## Prerequisites

- Terraform >= 1.6 (tested with 1.17.0).
- An SSH key uploaded to the DigitalOcean account (pass its **name** as `ssh_key_name`).
- A DigitalOcean API token with **custom scopes** (least privilege):
  - droplet: create, read, delete
  - firewall: create, read, update, delete
  - read-only: regions, sizes, image, snapshot, vpc, actions
  - ssh_key: read
  - (No tag scopes needed — the config intentionally sets `tags = []`.)

## Supplying the token

The provider reads `DIGITALOCEAN_TOKEN` from the environment; there is no token
variable in this config. Keep the token in a file outside the repo
(`~/.secrets/digitalocean_token`) and load it **per command**:

```bash
DIGITALOCEAN_TOKEN="$(cat ~/.secrets/digitalocean_token)" terraform -chdir=infra/demo plan ...
```

- Never `echo`/print the token, never `export` it into a shared shell history you will paste.
- Never commit `terraform.tfvars`, `*.tfstate*`, `*.tfplan`, or `raw/` (all gitignored).
- **The state file contains sensitive data** (IPs, IDs, and user data). Treat it as secret.

## Setup

```bash
cp infra/demo/terraform.tfvars.example infra/demo/terraform.tfvars
# edit: ssh_key_name, ssh_allowed_cidrs (your own IP as /32 — 0.0.0.0/0 is rejected)
```

## Spike procedure (each cloud step REQUIRES TEAM APPROVAL)

Goal: confirm a refresh-only plan reports a console firewall edit, and capture
real plan JSON for backend fixtures. Commands assume the repo root; prefix every
cloud command with the per-command token loading shown above (`TOK=...` below is
shorthand for `DIGITALOCEAN_TOKEN="$(cat ~/.secrets/digitalocean_token)"`).

- [ ] **1. Init** — `terraform -chdir=infra/demo init`
- [ ] **2. Plan** *(approval)* — `TOK terraform -chdir=infra/demo plan -input=false`
      Review: 1 droplet + 1 firewall to add, nothing else.
- [ ] **3. Apply** *(approval)* — `TOK terraform -chdir=infra/demo apply -input=false`
- [ ] **4. Verify the incident** — wait ~1–2 min for cloud-init, then
      `curl -m 5 "$(terraform -chdir=infra/demo output -raw service_url)"`
      should **time out**: the firewall only allows 8080, so 8443 is blocked.
      (Optionally SSH in and `curl localhost:8443` to confirm the service itself is up.)
- [ ] **5. Console edit** *(approval)* — in the DigitalOcean control panel, edit
      the firewall's inbound rule tcp **8080 → 8443**. Re-run the curl: it should
      now return `payment-webhook OK`.
- [ ] **6. Refresh-only scan** *(approval)*:
      ```bash
      mkdir -p infra/demo/raw
      TOK terraform -chdir=infra/demo plan -refresh-only -input=false -out=scan.tfplan
      terraform -chdir=infra/demo show -json scan.tfplan > infra/demo/raw/scan.json
      ```
- [ ] **7. Normal plan (the would-revert plan)** *(approval)*:
      ```bash
      TOK terraform -chdir=infra/demo plan -input=false -out=apply.tfplan
      terraform -chdir=infra/demo show -json apply.tfplan > infra/demo/raw/apply.json
      ```
      Expect an in-place update of `digitalocean_firewall.web` that would put 8080 back
      (i.e. close 8443).
- [ ] **8. Do NOT apply the refresh-only plan** (`scan.tfplan`) — it would write the
      drift into state and hide it. Do not apply `apply.tfplan` either unless the team
      decides to.
- [ ] **9. Sanitize fixtures** before copying anything to
      `backend/tests/fixtures/real/`: remove/replace droplet ids, firewall ids, IP
      addresses, `created_at`, `urn`, and any other account identifiers. Diff-check
      the result for leftovers. Never copy the raw files directly.
- [ ] **10. Destroy** *(approval)* — `TOK terraform -chdir=infra/demo destroy -input=false`
      and confirm in the console that the droplet and firewall are gone. Delete
      local `*.tfplan` files and `raw/` when done.

`raw/` is gitignored (`infra/demo/raw/`), as are `*.tfplan`, `*.tfstate*`, and `*.tfvars`.
