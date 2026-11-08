"""Guarded apply: the approved path for applying Terraform with emergency context.

The wrapper owns confirmation: `terraform apply <saved plan>` does not prompt,
so nothing is applied unless the human types an explicit confirmation here.
Running Terraform directly bypasses this wrapper (documented limitation).

PRD v3:
- R6/R10: every wrapper decision (keep, defer, cancel, revert, override, bypass)
  is appended to the events table; nothing earlier is overwritten.
- R7: the review decision, rationale, reviewer and exact plan fingerprint are
  persisted in ONE transaction BEFORE terraform runs. If that write fails,
  nothing is applied.
- R8: a run that never records completion is later shown as `unknown`.
"""

from __future__ import annotations

import getpass
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import matcher, service, suggest
from .db import Database, new_id, rule_from_json, ts
from .models import (
    AckOutcome,
    CheckStatus,
    Intent,
    ProposedChangeOut,
    utcnow,
)
from .textsafe import has_control, safe
from .tfrunner import APPLY_PLAN, SCAN_PLAN, Terraform, TerraformError

COVERAGE_NOTE = ("Checked digitalocean_firewall inbound rules only. Other attributes, other resource "
                 "types and OS-level changes are not covered.")
RACE_NOTE = ("Note: the cloud can still change between this plan and the apply. Terraform applies the "
             "saved plan exactly; it will fail if state changed, but not if live infrastructure changed.")
BYPASS_PHRASE = "unverified-bypass"
OS_USER_ASSURANCE = "local-os-user (not verified)"
SELF_REPORTED = "self-reported"


@dataclass
class ApplyOutcome:
    run_id: str
    outcome: AckOutcome
    check_status: CheckStatus
    warnings: list[str] = field(default_factory=list)
    applied: bool = False


Prompt = Callable[[str], str]
Out = Callable[[str], None]


def default_reviewer() -> tuple[str | None, str]:
    try:
        return getpass.getuser(), OS_USER_ASSURANCE
    except Exception:
        return None, SELF_REPORTED


@dataclass
class _Ctx:
    db: Database
    tf: Terraform
    environment: str
    run_id: str
    reviewer: str | None
    assurance: str
    prompt: Prompt
    out: Out
    plan_hash: str | None = None
    apply_started: bool = False   # set right before terraform apply runs
    finished: bool = False        # set once the final outcome is recorded
    result: "ApplyOutcome | None" = None

    def review(self, decision: str, rows, *, intent: Intent | None = None, rationale: str | None = None,
               start_run: bool = False) -> None:
        """Append review events (one per affected record) and, when starting the
        run, mark it running with reviewer/rationale, all in one transaction."""
        now_s = ts(utcnow())
        with self.db.tx() as conn:
            for r in rows:
                if intent is not None:
                    self.db.update_record(r["id"], {"intent": intent.value, "intent_updated_at": now_s,
                                                    "intent_note": rationale}, conn)
                service._event(self.db, conn, environment=self.environment, kind="review", record_id=r["id"],
                               run_id=self.run_id, actor=self.reviewer, assurance=self.assurance, now_s=now_s,
                               data={"decision": decision, "plan_fingerprint": self.plan_hash,
                                     "rationale": rationale, "source": "wrapper"})
            if start_run:
                self.db.update_apply_run(self.run_id, {
                    "ack_outcome": AckOutcome.RUNNING.value, "started_at": now_s, "reviewer": self.reviewer,
                    "reviewer_assurance": self.assurance, "rationale": rationale,
                    "plan_fingerprint": self.plan_hash}, conn)
                service._event(self.db, conn, environment=self.environment, kind="run_started", record_id=None,
                               run_id=self.run_id, actor=self.reviewer, assurance=self.assurance, now_s=now_s,
                               data={"decision": decision, "plan_fingerprint": self.plan_hash,
                                     "record_ids": [r["id"] for r in rows]})


def guarded_apply(db: Database, tf: Terraform, environment: str,
                  prompt: Prompt = input, out: Out = print,
                  reviewer: str | None = None) -> ApplyOutcome:
    if reviewer and reviewer.strip() and not has_control(reviewer):
        who, assurance = reviewer.strip()[:100], SELF_REPORTED
    else:
        who, assurance = default_reviewer()

    run_id = new_id("run")
    db.insert_apply_run({
        "id": run_id, "environment": environment, "generated_at": ts(utcnow()),
        "plan_fingerprint": None, "proposed_changes_json": "[]", "warnings_json": "[]",
        "check_status": CheckStatus.FAILED.value, "coverage_note": COVERAGE_NOTE,
        "ack_outcome": AckOutcome.PENDING.value, "ack_note": None, "completed_at": None,
        "reviewer": who, "reviewer_assurance": assurance,
    })
    # PRD R8: earlier runs that never recorded completion are unknown, not successful.
    for old in db.mark_unfinished_runs_unknown(environment, exclude_id=run_id):
        out(f"Note: earlier apply run {old} has no recorded completion; its outcome is marked unknown.")

    ctx = _Ctx(db, tf, environment, run_id, who, assurance, prompt, out)

    def finish(outcome: AckOutcome, check: CheckStatus, warnings: list[str], applied=False, note=None) -> ApplyOutcome:
        now_s = ts(utcnow())
        result = ApplyOutcome(run_id, outcome, check, warnings, applied)
        try:
            with db.tx() as conn:  # run row + run_finished event together
                db.update_apply_run(run_id, {"ack_outcome": outcome.value, "ack_note": note,
                                             "check_status": check.value, "completed_at": now_s}, conn)
                service._event(db, conn, environment=environment, kind="run_finished", record_id=None,
                               run_id=run_id, actor=who, assurance=assurance, now_s=now_s,
                               data={"outcome": outcome.value, "applied": applied, "note": note})
        except Exception as e:
            out(f"WARNING: outcome '{outcome.value}' could not be recorded ({type(e).__name__}). "
                + ("Terraform DID apply. " if applied else "")
                + "The run will show as unknown; run `breakglass scan` and `breakglass recheck`.")
        ctx.finished, ctx.result = True, result
        out(f"[apply run {run_id}] outcome: {outcome.value}")
        return result

    try:
        return _guarded_apply(ctx, finish)
    except (KeyboardInterrupt, EOFError):
        if ctx.finished and ctx.result is not None:
            out("\nInterrupted after the outcome was recorded; nothing changed.")
            return ctx.result
        if ctx.apply_started:
            out("\nINTERRUPTED after terraform apply started. Live state is unknown: "
                "run `breakglass scan` and `breakglass recheck`.")
            return finish(AckOutcome.FAILED, CheckStatus.FAILED, [],
                          note="interrupted after apply started; live state unknown")
        out("\nCancelled. Nothing applied.")
        return finish(AckOutcome.CANCELLED, CheckStatus.FAILED, [])
    finally:
        tf.cleanup()


def _age(iso: str) -> str:
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "age unknown"
    mins = int((datetime.now(timezone.utc) - then).total_seconds() // 60)
    if mins < 60:
        return f"detected {mins}m ago"
    return f"detected {mins // 60}h {mins % 60}m ago"


def _prior_decisions(db: Database, record_id: str, limit: int = 3) -> list[str]:
    lines = []
    for e in db.list_events(record_id=record_id):
        if e["kind"] not in ("decision", "review"):
            continue
        d = json.loads(e["data_json"])
        what = d.get("decision") or d.get("intent")
        who = safe(e["actor"]) if e["actor"] else "unnamed"
        why = f': "{safe(d.get("rationale") or d.get("note"))}"' if (d.get("rationale") or d.get("note")) else ""
        lines.append(f"{e['created_at'][:16].replace('T', ' ')} {what} by {who} ({e['actor_assurance']}){why}")
    return lines[-limit:]


def _ask_rationale(ctx: _Ctx) -> str | None:
    """Required rationale (PRD §6 step 7). None means the decision must not be saved."""
    text = ctx.prompt("Short rationale for this decision (required, saved with it): ").strip()
    if not text or has_control(text):
        ctx.out("A rationale is required for this decision (no control characters). Nothing applied.")
        return None
    return text[:500]


def _ask_cancel_rationale(ctx: _Ctx) -> str | None:
    """Cancel asks for a rationale but never requires one: cancelling is the safe
    default and must never be blocked. Closed input (EOF) also just cancels."""
    try:
        text = ctx.prompt("Short rationale for cancelling (Enter to skip): ").strip()
    except EOFError:
        return None
    if not text or has_control(text):
        return None
    return text[:500]


def _cancel(ctx: _Ctx, finish, affected, check, warn_texts, *, ask: bool = True, note: str | None = None):
    rationale = _ask_cancel_rationale(ctx) if (ask and affected) else None
    ctx.review("cancel", affected, rationale=rationale)
    ctx.out("Cancelled. Nothing applied.")
    return finish(AckOutcome.CANCELLED, check, warn_texts, note=note)


def _guarded_apply(ctx: _Ctx, finish) -> ApplyOutcome:
    db, tf, environment, out, prompt = ctx.db, ctx.tf, ctx.environment, ctx.out, ctx.prompt
    problems: list[str] = []
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
    ctx.plan_hash = tf.plan_hash(APPLY_PLAN)
    db.update_apply_run(ctx.run_id, {"plan_fingerprint": ctx.plan_hash})

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
        return _apply_exact(ctx, cfg_hash, workspace, finish, CheckStatus.CURRENT, [],
                            AckOutcome.APPLIED_NO_WARNINGS, decision="state-sync", rows=[],
                            note="state-only sync (no resource changes)")
    try:
        plan_json = tf.show_json(APPLY_PLAN)
    except TerraformError as e:
        problems.append(f"could not read plan JSON: {e}")

    # 4. Match against open records
    warn_rows: list = []
    unknown_rows: list = []
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
    affected = warn_rows + unknown_rows
    warning_objs = [service.warning_out(r) for r in affected]
    db.update_apply_run(ctx.run_id, {
        "plan_fingerprint": ctx.plan_hash,
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
    out(f"Reviewer: {safe(ctx.reviewer) if ctx.reviewer else 'unknown'} ({ctx.assurance})")
    out("")

    warn_texts = [w.message for w in warning_objs]
    nc_note = f"{len(not_checked)} change(s) outside coverage were NOT CHECKED" if not_checked else None

    if not verified:
        out("VERIFICATION UNAVAILABLE. This is NOT a 'no conflicts' result.")
        for p in problems:
            out(f"  - {safe(p)}")
        for w in warning_objs:
            out(f"  ! {safe(w.message)}")
        ans = prompt(f"Type '{BYPASS_PHRASE}' to apply this saved plan anyway (anything else cancels): ").strip()
        if ans != BYPASS_PHRASE:
            return _cancel(ctx, finish, affected, check, warn_texts)
        rationale = _ask_rationale(ctx)
        if rationale is None:
            ctx.review("cancel", affected)
            return finish(AckOutcome.CANCELLED, check, warn_texts, note="no rationale given")
        return _apply_exact(ctx, cfg_hash, workspace, finish, check, warn_texts,
                            AckOutcome.UNVERIFIED_BYPASS_APPLIED, decision="unverified-bypass",
                            rows=affected, rationale=rationale, note=nc_note)

    if warning_objs:
        out("WARNING: this apply would reverse manual emergency change(s):")
        for r, w in zip(affected, warning_objs):
            tag = "" if r in warn_rows else " [reversal could not be ruled out]"
            out(f"  ! {safe(w.message)}{tag}")
            out(f"    record {r['id']} | {_age(r['first_detected_at'])} | intent: {r['intent']} | "
                "reporter and reason are self-reported, not verified")
            for line in _prior_decisions(db, r["id"]):
                out(f"    prior: {line}")
        out("")
        choice = prompt("[k]eep change (no apply) / [r]evert it (apply) / [d]efer / [c]ancel / [o]verride: ").strip().lower()

        if choice in ("k", "keep"):
            rationale = _ask_rationale(ctx)
            if rationale is None:
                return _cancel(ctx, finish, affected, check, warn_texts, ask=False,
                               note="keep not saved: no rationale given")
            ctx.review("keep", affected, intent=Intent.KEEP, rationale=rationale)
            for r in affected:
                s = suggest.suggest_literal_edit(tf.tf_dir, r["resource_address"],
                                                 rule_from_json(r["baseline_json"]), rule_from_json(r["observed_json"]))
                out(s if s else f"No single literal edit found for {r['resource_address']}; update the Terraform rule by hand.")
            out("Kept. Nothing applied. Edit the Terraform config, then run `breakglass apply` "
                "(records the live value in state) and `breakglass recheck`.")
            return finish(AckOutcome.KEPT, check, warn_texts)
        if choice in ("d", "defer"):
            rationale = _ask_rationale(ctx)
            if rationale is None:
                return _cancel(ctx, finish, affected, check, warn_texts, ask=False,
                               note="defer not saved: no rationale given")
            ctx.review("defer", affected, intent=Intent.DEFER, rationale=rationale)
            out("Deferred. Nothing applied.")
            return finish(AckOutcome.DEFERRED, check, warn_texts)
        if choice in ("r", "revert"):
            ans = prompt("Type 'revert' to apply this exact saved plan and undo the live change(s): ").strip()
            if ans != "revert":
                ctx.review("revert-not-confirmed", affected, intent=Intent.REVERT)
                out("Revert intent saved. Nothing applied.")
                return finish(AckOutcome.CANCELLED, check, warn_texts, note="revert intent saved, apply not confirmed")
            rationale = _ask_rationale(ctx)
            if rationale is None:
                ctx.review("revert-not-confirmed", affected, intent=Intent.REVERT)
                return finish(AckOutcome.CANCELLED, check, warn_texts, note="no rationale given")
            return _apply_exact(ctx, cfg_hash, workspace, finish, check, warn_texts, AckOutcome.REVERTED_APPLIED,
                                decision="revert", rows=affected, rationale=rationale, intent=Intent.REVERT,
                                note=nc_note)
        if choice in ("o", "override"):
            ans = prompt("Type 'override' to apply despite the warning (this is recorded): ").strip()
            if ans != "override":
                return _cancel(ctx, finish, affected, check, warn_texts)
            rationale = _ask_rationale(ctx)
            if rationale is None:
                ctx.review("cancel", affected)
                return finish(AckOutcome.CANCELLED, check, warn_texts, note="no rationale given")
            return _apply_exact(ctx, cfg_hash, workspace, finish, check, warn_texts, AckOutcome.OVERRIDE_APPLIED,
                                decision="override", rows=affected, rationale=rationale, note=nc_note)
        return _cancel(ctx, finish, affected, check, warn_texts)

    if not_checked:
        out(f"No supported emergency changes are reversed by this plan, but {len(not_checked)} "
            "change(s) were NOT CHECKED (listed above).")
    else:
        out("No open emergency changes are reversed by this plan (within the coverage above).")
    ans = prompt("Type 'yes' to apply this exact saved plan: ").strip().lower()
    if ans != "yes":
        out("Cancelled. Nothing applied.")
        return finish(AckOutcome.CANCELLED, check, warn_texts, note=nc_note)
    return _apply_exact(ctx, cfg_hash, workspace, finish, check, warn_texts, AckOutcome.APPLIED_NO_WARNINGS,
                        decision="apply", rows=[], note=nc_note)


def _apply_exact(ctx: _Ctx, cfg_hash, workspace, finish, check, warn_texts, outcome: AckOutcome, *,
                 decision: str, rows, rationale: str | None = None, intent: Intent | None = None,
                 note: str | None = None) -> ApplyOutcome:
    tf, out = ctx.tf, ctx.out
    # Integrity: the artifact and context must be exactly what was reviewed.
    try:
        unchanged = (ctx.plan_hash is not None and tf.plan_hash(APPLY_PLAN) == ctx.plan_hash
                     and tf.config_hash() == cfg_hash and tf.workspace() == workspace)
    except (TerraformError, OSError):
        unchanged = False
    if not unchanged:
        out("ABORTED: plan file, config, or workspace changed since review. Re-run `breakglass apply` to replan.")
        return finish(AckOutcome.ABORTED_PLAN_CHANGED, check, warn_texts, note=note)

    # PRD R7: persist the decision (linked to this exact plan) BEFORE terraform runs.
    try:
        ctx.review(decision, rows, intent=intent, rationale=rationale, start_run=True)
    except Exception as e:
        out(f"ERROR: could not save the review decision ({type(e).__name__}). Nothing applied.")
        return finish(AckOutcome.FAILED, check, warn_texts, note="decision could not be persisted; not applied")

    out(RACE_NOTE)
    ctx.apply_started = True
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
