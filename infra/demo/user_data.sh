#!/bin/bash
# cloud-init user data: a tiny "payment-webhook" service on port 8443 (plain HTTP).
# Nothing listens on 8080 — Terraform's firewall permits 8080, but the service
# is on 8443. That mismatch is the demo "incident".
set -euo pipefail

mkdir -p /opt/webhook
echo "payment-webhook OK" > /opt/webhook/index.html

cat > /etc/systemd/system/payment-webhook.service <<'UNIT'
[Unit]
Description=Demo payment-webhook (python http.server on 8443)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 -m http.server 8443 --directory /opt/webhook
Restart=always
DynamicUser=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now payment-webhook.service
