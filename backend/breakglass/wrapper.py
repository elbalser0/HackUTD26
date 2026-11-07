"""Guarded apply: the approved path for applying Terraform with emergency context.

The wrapper owns confirmation: `terraform apply <saved plan>` does not prompt,
so nothing is applied unless the human types an explicit confirmation here.
Running Terraform directly bypasses this wrapper (documented limitation).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from . import matcher, service, suggest
from .db import Database, new_id, rule_from_json, ts
from .models import (
    AckOutcome,
    CheckStatus,
    DecisionIn,
    Intent,
    ProposedChangeOut,
    utcnow,
)
from .textsafe import safe
from .tfrunner import APPLY_PLAN, SCAN_PLAN, Terraform, TerraformError

COVERAGE_NOTE = ("Checked digitalocean_firewall inbound rules only. Other attributes, other resource "
                 "types and OS-level changes are not covered.")
RACE_NOTE = ("Note: the cloud can still change between this plan and the apply. Terraform applies the "
             "saved plan exactly; it will fail if state changed, but not if live infrastructure changed.")
BYPASS_PHRASE = "unverified-bypass"


@dataclass
class ApplyOutcome:
    run_id: str
    outcome: AckOutcome
    check_status: CheckStatus
    warnings: list[str] = field(default_factory=list)
    applied: bool = False


Prompt = Callable[[str], str]
Out = Callable[[str], None]


def guarded_apply(db: Database, tf: Terraform, environment: str,
                  prompt: Prompt = input, out: Out = print) -> ApplyOutcome:
    run_id = new_id("run")
    db.insert_apply_run({
        "id": run_id, "environment": environment, "generated_at": ts(utcnow()),
        "plan_fingerprint": None, "proposed_changes_json": "[]", "warnings_json": "[]",
        "check_status": CheckStatus.FAILED.value, "coverage_note": COVERAGE_NOTE,
        "ack_outcome": AckOutcome.PENDING.value, "ack_note": None, "completed_at": None,
    })

    def finish(outcome: AckOutcome, check: CheckStatus, warnings: list[str], applied=False, note=None) -> ApplyOutcome:
        db.update_apply_run(run_id, {"ack_outcome": outcome.value, "ack_note": note,
                                     "check_status": check.value, "completed_at": ts(utcnow())})
        out(f"[apply run {run_id}] outcome: {outcome.value}")
        return ApplyOutcome(run_id, outcome, check, warnings, applied)

    try:
        return _guarded_apply(db, tf, environment, run_id, prompt, out, finish)
    except (KeyboardInterrupt, EOFError):
        out("\nCancelled. Nothing applied.")
        return finish(AckOutcome.CANCELLED, CheckStatus.FAILED, [])
    finally:
        tf.cleanup()


def _guarded_apply(db, tf: Terraform, environment, run_id, prompt, out, finish) -> ApplyOutcome:
    problems: list[str] = []
    workspace = cfg_hash = None
    has_changes = None
    plan_json = None

    # 1. Context: workspace + config fingerprint
    try:
        workspace = tf.workspace()
        cfg_hash = tf.config_hash()
    except (TerraformError, OSError) as e:
        out(f"ERROR: {e}")
        return finish(AckOutcome.FAILED, CheckStatus.FAILED, [], note="workspace/config check failed")

    # 2. Fresh live observation (refresh-only plan; never applied)
    scan_ok = False
    not_checked: list[str] = []
    drift_seen = False
    try:
        tf.plan(SCAN_PLAN, refresh_only=True)
        scan = service.ingest_refresh_plan(db, environment, tf.show_json(SCAN_PLAN))
        scan_ok = scan.status == "ok"
        if not scan_ok:
            problems.extend(scan.errors)
        not_checked = list(scan.unsupported)
        drift_seen = bool(scan.new_ids or scan.seen_ids or scan.unsupported)
        for n in scan.new_ids:
            out(f"New manual change detected: {safe(db.get_record(n)['summary'])} (record {n}, no reason recorded yet)")
    except (TerraformError, OSError) as e:
        problems.append(f"refresh-only scan failed: {e}")
        service.ingest_refresh_plan(db, environment, None)  # marks open records last_check_status=failed

    for note in not_checked:
        out(f"NOT CHECKED (outside supported coverage): {safe(note)}")

    # 3. Normal saved plan
    try:
        has_changes = tf.plan(APPLY_PLAN)
    except (TerraformError, OSError) as e:
        out(f"ERROR: {e}")
        return finish(AckOutcome.FAILED, CheckStatus.FAILED, [], note="plan failed")
    plan_hash = tf.plan_hash(APPLY_PLAN)

    if not has_changes:
        if not (scan_ok and drift_seen):
            out("Terraform reports no changes. Nothing to apply.")
            return finish(AckOutcome.NO_CHANGES, CheckStatus.CURRENT if scan_ok else CheckStatus.FAILED, [])
        # Config already matches live (e.g. after a 'keep' + IaC edit), but state still holds
        # the old value. Applying the empty saved plan records the refreshed live values in state.
        out("Terraform proposes no resource changes, but live values differ from state "
            "(config already matches live).")
        ans = prompt("Type 'yes' to apply this saved plan and record the live values in Terraform state: ").strip().lower()
        if ans != "yes":
            out("Cancelled. Nothing applied.")
            return finish(AckOutcome.NO_CHANGES, CheckStatus.CURRENT, [], note="state sync declined")
        return _apply_exact(tf, plan_hash, cfg_hash, workspace, out, finish, CheckStatus.CURRENT, [],
                            AckOutcome.APPLIED_NO_WARNINGS, note="state-only sync (no resource changes)")
    try:
        plan_json = tf.show_json(APPLY_PLAN)
    except TerraformError as e:
        problems.append(f"could not read plan JSON: {e}")

    # 4. Match against open records
    warn_rows = []
    unknown_rows = []
    m = None
    if plan_json is not None:
        rows = db.list_records(resolution="open", environment=environment)
        m = matcher.match(plan_json, [service.candidate(r) for r in rows])
        problems.extend(m.errors)
        by_id = {r["id"]: r for r in rows}
        warn_rows = [by_id[i] for i in m.reversed_ids if i in by_id]
        unknown_rows = [by_id[i] for i in m.unknown_ids if i in by_id]

    verified = scan_ok and plan_json is not None and m is not None and not m.errors
    check = CheckStatus.CURRENT if verified else CheckStatus.FAILED
    warning_objs = [service.warning_out(r) for r in warn_rows + unknown_rows]
    db.update_apply_run(run_id, {
        "plan_fingerprint": plan_hash,
        "proposed_changes_json": json.dumps([ProposedChangeOut(
            resource_address=c.resource_address, resource_type=c.resource_type,
            actions=list(c.actions), summary=c.summary).model_dump() for c in (m.proposed_changes if m else [])]),
        "warnings_json": json.dumps([json.loads(w.model_dump_json()) for w in warning_objs]),
        "check_status": check.value,
    })

    out("")
    out("Proposed changes:")
    for c in (m.proposed_changes if m else []):
        out(f"  {', '.join(c.actions):>14}  {safe(c.resource_address)}  {safe(c.summary)}")
    if m is None:
        out("  (unavailable)")
    out(f"Coverage: {COVERAGE_NOTE}")
    out("")

    warn_texts = [w.message for w in warning_objs]
    pending_outcome = AckOutcome.APPLIED_NO_WARNINGS
    nc_note = f"{len(not_checked)} change(s) outside coverage were NOT CHECKED" if not_checked else None

    if not verified:
        out("VERIFICATION UNAVAILABLE. This is NOT a 'no conflicts' result.")
        for p in problems:
            out(f"  - {safe(p)}")
        for w in warning_objs:
            out(f"  ! {safe(w.message)}")
        ans = prompt(f"Type '{BYPASS_PHRASE}' to apply this saved plan anyway (anything else cancels): ").strip()
        if ans != BYPASS_PHRASE:
            out("Cancelled. Nothing applied.")
            return finish(AckOutcome.CANCELLED, check, warn_texts)
        pending_outcome = AckOutcome.UNVERIFIED_BYPASS_APPLIED

    elif warning_objs:
        out("WARNING: this apply would reverse manual emergency change(s):")
        for r, w in zip(warn_rows + unknown_rows, warning_objs):
            tag = "" if r in warn_rows else " [reversal could not be ruled out]"
            out(f"  ! {safe(w.message)}{tag}")
            out(f"    record {r['id']} | intent: {r['intent']} | reporter and reason are self-reported, not verified")
        out("")
        choice = prompt("[k]eep change (no apply) / [r]evert it (apply) / [d]efer / [c]ancel / [o]verride: ").strip().lower()
        ids = [r["id"] for r in warn_rows + unknown_rows]

        if choice in ("k", "keep"):
            for i in ids:
                service.decide(db, i, DecisionIn(intent=Intent.KEEP))
            for r in warn_rows + unknown_rows:
                s = suggest.suggest_literal_edit(tf.tf_dir, r["resource_address"],
                                                 rule_from_json(r["baseline_json"]), rule_from_json(r["observed_json"]))
                out(s if s else f"No single literal edit found for {r['resource_address']}; update the Terraform rule by hand.")
            out("Kept. Nothing applied. Edit the Terraform config, then run `breakglass apply` "
                "(records the live value in state) and `breakglass recheck`.")
            return finish(AckOutcome.KEPT, check, warn_texts)
        if choice in ("d", "defer"):
            for i in ids:
                service.decide(db, i, DecisionIn(intent=Intent.DEFER))
            out("Deferred. Nothing applied.")
            return finish(AckOutcome.DEFERRED, check, warn_texts)
        if choice in ("r", "revert"):
            for i in ids:
                service.decide(db, i, DecisionIn(intent=Intent.REVERT))
            ans = prompt("Type 'revert' to apply this exact saved plan and undo the live change(s): ").strip()
            if ans != "revert":
                out("Revert intent saved. Nothing applied.")
                return finish(AckOutcome.CANCELLED, check, warn_texts, note="revert intent saved, apply not confirmed")
            pending_outcome = AckOutcome.REVERTED_APPLIED
        elif choice in ("o", "override"):
            ans = prompt("Type 'override' to apply despite the warning (this is recorded): ").strip()
            if ans != "override":
                out("Cancelled. Nothing applied.")
                return finish(AckOutcome.CANCELLED, check, warn_texts)
            pending_outcome = AckOutcome.OVERRIDE_APPLIED
        else:
            out("Cancelled. Nothing applied.")
            return finish(AckOutcome.CANCELLED, check, warn_texts)

    else:
        if not_checked:
            out(f"No supported emergency changes are reversed by this plan, but {len(not_checked)} "
                "change(s) were NOT CHECKED (listed above).")
        else:
            out("No open emergency changes are reversed by this plan (within the coverage above).")
        ans = prompt("Type 'yes' to apply this exact saved plan: ").strip().lower()
        if ans != "yes":
            out("Cancelled. Nothing applied.")
            return finish(AckOutcome.CANCELLED, check, warn_texts, note=nc_note)

    return _apply_exact(tf, plan_hash, cfg_hash, workspace, out, finish, check, warn_texts,
                        pending_outcome, note=nc_note)


def _apply_exact(tf: Terraform, plan_hash, cfg_hash, workspace, out, finish, check, warn_texts,
                 outcome: AckOutcome, note: str | None = None) -> ApplyOutcome:
    # Integrity: the artifact and context must be exactly what was reviewed.
    try:
        unchanged = (plan_hash is not None and tf.plan_hash(APPLY_PLAN) == plan_hash
                     and tf.config_hash() == cfg_hash and tf.workspace() == workspace)
    except (TerraformError, OSError):
        unchanged = False
    if not unchanged:
        out("ABORTED: plan file, config, or workspace changed since review. Re-run `breakglass apply` to replan.")
        return finish(AckOutcome.ABORTED_PLAN_CHANGED, check, warn_texts, note=note)

    out(RACE_NOTE)
    try:
        code = tf.apply_saved(APPLY_PLAN)
    except (KeyboardInterrupt, TerraformError, OSError) as e:
        out(f"INTERRUPTED/FAILED DURING APPLY ({type(e).__name__}). Live state is unknown: "
            "run `breakglass scan` and `breakglass recheck`.")
        return finish(AckOutcome.FAILED, check, warn_texts, note="interrupted during apply; live state unknown")
    if code != 0:
        out(f"terraform apply failed (exit {code}). Live state may be partially changed; run `breakglass scan`.")
        return finish(AckOutcome.FAILED, check, warn_texts, note=f"apply exit {code}")
    out("Applied. Run `breakglass recheck` to verify and resolve records.")
    return finish(outcome, check, warn_texts, applied=True, note=note)
