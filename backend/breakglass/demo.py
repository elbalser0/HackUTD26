"""`argus demo-reset`: start each rehearsal from a known-clean state.

1. Wipes local demo data (records, history events, apply runs, scans) after an
   explicit confirmation.
2. Preflight: Terraform directory, DigitalOcean token *presence* (never read or
   printed here), admin token configured, API reachable.
3. Read-only cloud check: a refresh-only plan, shown through the detector but
   NEVER applied and NEVER ingested, so the database stays empty. Leftover
   drift (e.g. the 8443 rule from the last rehearsal) is listed with an
   instruction to remove it in the DigitalOcean console. Removing it is a human
   action; this command changes nothing in the cloud.

Exit codes: 0 = reset and clean (warnings allowed); 1 = not confirmed or the
cloud check could not verify; 2 = reset done but drift is still present.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Callable

from . import config, detector, rules
from .config import Settings
from .db import Database
from .textsafe import safe
from .tfrunner import DEFAULT_TOKEN_FILE, SCAN_PLAN, TOKEN_ENV, Terraform, TerraformError

CONFIRM_PHRASE = "reset"


def _token_present() -> bool:
    """Presence only: the value is never read or printed by this module."""
    if os.environ.get(TOKEN_ENV):
        return True
    token_file = Path(config.bg_env("BG_DO_TOKEN_FILE") or DEFAULT_TOKEN_FILE).expanduser()
    try:
        return token_file.is_file() and token_file.stat().st_size > 0
    except OSError:
        return False


def default_api_health(url: str | None = None) -> bool:
    url = url or config.bg_env("BG_API_URL", "http://127.0.0.1:8000") + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 (fixed local URL)
            return resp.status == 200
    except Exception:
        return False


def demo_reset(db: Database, settings: Settings, tf: Terraform | None, *,
               prompt: Callable[[str], str] | None = None, out: Callable[[str], None] = print,
               yes: bool = False, check_cloud: bool = True,
               api_health: Callable[[], bool] = default_api_health) -> int:
    prompt = prompt or (lambda text: input(text))  # resolved at call time
    # 1. Confirm, then wipe local data.
    if not yes:
        try:
            ans = prompt(f"Type '{CONFIRM_PHRASE}' to delete ALL local records, history and apply runs: ").strip()
        except EOFError:
            ans = ""
        if ans != CONFIRM_PHRASE:
            out("Not confirmed. Nothing deleted.")
            return 1
    db.reset()
    out(f"[ok]   Local demo data deleted ({settings.db_path}).")

    # 2. Preflight (warnings never fail the reset).
    out(f"[{'ok' if settings.tf_dir else 'FAIL'}]   Terraform directory: "
        f"{settings.tf_dir if settings.tf_dir else 'not found (set BG_TF_DIR)'}")
    out("[ok]   DIGITALOCEAN_TOKEN available (value not shown)." if _token_present()
        else "[warn] DIGITALOCEAN_TOKEN not found: load it before scanning (e.g. read -rsp, or your .env).")
    out("[ok]   BG_ADMIN_TOKEN is set (admin log enabled)." if settings.admin_token
        else "[warn] BG_ADMIN_TOKEN is not set: the admin log will answer 403.")
    out("[ok]   API is answering on /api/health." if api_health()
        else "[warn] API not reachable: start it with `uvicorn breakglass.api:app --port 8000`.")

    # 3. Read-only cloud check.
    if not check_cloud:
        out("[skip] Cloud check skipped (--skip-cloud-check). Firewall state NOT verified.")
        return 0 if settings.tf_dir else 1
    if tf is None:
        out("[FAIL] Could not verify the firewall: no Terraform directory.")
        return 1
    try:
        tf.plan(SCAN_PLAN, refresh_only=True)
        plan = tf.show_json(SCAN_PLAN)
    except (TerraformError, OSError) as e:
        out(f"[FAIL] Could not verify the firewall (refresh-only plan failed): {safe(e)}")
        return 1
    finally:
        tf.cleanup()  # the scan plan is never applied

    result = detector.detect(plan)
    if result.errors:
        out("[FAIL] Could not verify the firewall: the plan JSON was not interpretable.")
        for e in result.errors:
            out(f"         - {safe(e)}")
        return 1
    if not result.observations and not result.unsupported:
        out("[ok]   Firewall matches Terraform: clean. Ready for the demo.")
        return 0
    for o in result.observations:
        rule = o.observed if o.observed is not None else o.baseline
        what = rules.describe_rule(rule) if rule is not None else "a rule"
        out(f"[DRIFT] {o.kind.value}: {safe(what)} on {safe(o.resource_address)}")
    for note in result.unsupported:
        out(f"[DRIFT] not checked: {safe(note)}")
    out("Remove the leftover change in the DigitalOcean console (Networking -> Firewalls -> break-glass-demo), "
        "then run `argus demo-reset --yes` again. This command never changes the cloud.")
    return 2
