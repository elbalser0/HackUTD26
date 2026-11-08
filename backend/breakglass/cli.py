"""`breakglass` command-line interface.

Terraform-running commands (scan, apply, recheck) use only the server-configured
Terraform directory (BG_TF_DIR, default break-glass-infra/). `--from-json` options read
local plan JSON files for offline/fixture use and are labeled accordingly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import demo, service, wrapper
from .config import BACKEND_DIR, ConfigError, load_settings
from .db import Database
from .storage import StorageUnavailable, open_database
from .models import DecisionIn, Intent, ReportIn
from .textsafe import has_control, safe
from .tfrunner import SCAN_PLAN, APPLY_PLAN, Terraform, TerraformError

AUTHORED_DEMO_FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "authored" / "refresh_drift_8443.json"
INTENT_KEYS = {"k": Intent.KEEP, "r": Intent.REVERT, "u": Intent.UNSURE, "d": Intent.DEFER}


def env_for(settings, label: str) -> str:
    """Authored and replayed data never share an environment with live records,
    so fixture evidence can never merge into, explain, or resolve a live record."""
    return {"terraform-refresh-only": settings.environment,
            "authored-fixture": f"{settings.environment}-authored",
            "real-fixture": f"{settings.environment}-replay"}[label]


def _load_json(path: str) -> Any:
    p = Path(path)
    if p.stat().st_size > 50 * 1024 * 1024:
        raise SystemExit(f"{p}: refusing to read a plan JSON larger than 50 MB")
    return json.loads(p.read_text(encoding="utf-8"))


def _terraform(settings) -> Terraform:
    if settings.tf_dir is None:
        raise SystemExit("Terraform directory not found. Set BG_TF_DIR (must be inside the repo's break-glass-infra/).")
    return Terraform(settings.tf_dir, binary=settings.terraform_bin)


def _print_record(r, out: Callable[[str], None] = print) -> None:
    reason = f'"{safe(r.reason)}"' if r.reason else "(no reason recorded)"
    who = f"reported by {safe(r.reporter)}" if r.reporter else ("reporter not given" if r.reason else "")
    src = "" if r.evidence_source == "terraform-refresh-only" else f"  ({r.evidence_source.upper()})"
    out(f"{r.id}  [{r.resolution}{'/' + r.resolution_reason if r.resolution_reason else ''}]  "
        f"{r.environment}  {safe(r.resource_address)}{src}")
    out(f"    {safe(r.summary)}")
    out(f"    detected {r.first_detected_at:%Y-%m-%d %H:%M} UTC | last check {r.last_check_status}"
        f" | intent {r.intent}")
    out(f"    {reason} {who}".rstrip())


def prompt_for_reasons(db: Database, record_ids: list[str], ask: Callable[[str], str] = input,
                       out: Callable[[str], None] = print) -> None:
    """The handoff prompt (~10 seconds per record): show what Argus detected,
    then ask only why, who, and the intent. Skipping keeps the record unexplained."""
    for rid in record_ids:
        row = db.get_record(rid)
        if row is None or row["reason"] or row["resolution"] != "open":
            continue
        r = service.record_out(row)
        out("")
        out(f"Argus detected a manual change (detected {r.first_detected_at:%H:%M} UTC):")
        out(f"  {safe(r.resource_address)}: {safe(r.summary)}")
        reason = safe(ask("Why was this change needed? (Enter to skip): ")).strip()
        if not reason:
            out("Skipped. The apply-time warning will say 'no reason recorded'.")
            continue
        reporter = safe(ask("Your name (Enter to skip): ")).strip()[:80] or None
        key = ask("Keep it, revert it, or unsure? [k/r/u, Enter=skip]: ").strip().lower()[:1]
        service.report(db, rid, ReportIn(reporter=reporter, reason=reason[:500], intent=INTENT_KEYS.get(key)),
                       source="cli")
        out("Saved (self-reported). A later `breakglass apply` that would undo this change will show this reason.")


def _hint_unexplained(db: Database, record_ids: list[str], out: Callable[[str], None] = print) -> None:
    """Non-interactive scan: never skip the question silently."""
    for rid in record_ids:
        row = db.get_record(rid)
        if row is None or row["reason"] or row["resolution"] != "open":
            continue
        out(f"Not an interactive terminal, so no reason was asked for {rid}. Add one with: "
            f'breakglass report {rid} --reason "..." --reporter "..."')


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_scan(args, db: Database, settings) -> int:
    if args.from_json:
        if not args.label:
            raise SystemExit("--label authored-fixture|real-fixture is required with --from-json")
        plan = _load_json(args.from_json)
        label = args.label
    else:
        tf = _terraform(settings)
        try:
            tf.plan(SCAN_PLAN, refresh_only=True)
            plan = tf.show_json(SCAN_PLAN)
        except TerraformError as e:
            print(f"SCAN FAILED: {e}")
            print("Open records are marked last_check_status=failed. This is NOT 'no drift'.")
            service.ingest_refresh_plan(db, settings.environment, None)  # records the failure
            return 1
        finally:
            tf.cleanup()
        label = "terraform-refresh-only"

    res = service.ingest_refresh_plan(db, env_for(settings, label), plan, evidence_source=label)
    if res.status != "ok":
        print("SCAN FAILED: plan JSON could not be interpreted. This is NOT 'no drift'.")
        for e in res.errors:
            print(f"  - {e}")
        return 1
    print(f"Scan ok: {len(res.new_ids)} new, {len(res.seen_ids)} still present, "
          f"{len(res.superseded_ids)} superseded, {len(res.stale_ids)} no longer drifting (stale; run recheck).")
    for note in res.unsupported:
        print(f"  NOT CHECKED (outside supported coverage): {safe(note)}")
    if not args.no_prompt:
        if sys.stdin.isatty():
            prompt_for_reasons(db, res.new_ids + res.seen_ids)
        else:
            _hint_unexplained(db, res.new_ids + res.seen_ids)
    return 0


def cmd_list(args, db: Database, settings) -> int:
    resolution = None if args.all else ("resolved" if args.resolved else "open")
    rows = db.list_records(resolution=resolution)
    if not rows:
        print(f"No {resolution or ''} records.".replace("  ", " "))
    for row in rows:
        _print_record(service.record_out(row))
    return 0


def cmd_show(args, db: Database, settings) -> int:
    row = db.get_record(args.id)
    if row is None:
        print(f"record {args.id} not found")
        return 1
    print(service.record_out(row).model_dump_json(indent=2))
    return 0


def cmd_report(args, db: Database, settings) -> int:
    try:
        if args.reason is None:
            prompt_for_reasons(db, [args.id])
            return 0
        rec = service.report(db, args.id, ReportIn(reporter=args.reporter, reason=args.reason,
                                                   intent=Intent(args.intent) if args.intent else None))
    except (service.NotFound, service.Conflict, ValueError) as e:
        print(f"error: {e}")
        return 1
    _print_record(rec)
    return 0


def cmd_decide(args, db: Database, settings) -> int:
    if args.reviewer is not None:
        args.reviewer = args.reviewer.strip()[:100] or None
        if args.reviewer and has_control(args.reviewer):
            print("error: --reviewer must not contain control characters")
            return 1
    try:
        rec = service.decide(db, args.id, DecisionIn(intent=Intent(args.intent), note=args.note),
                             source="cli", actor=args.reviewer)
    except (service.NotFound, service.Conflict, ValueError) as e:
        print(f"error: {e}")
        return 1
    _print_record(rec)
    print("Intent saved. This does not apply anything and does not resolve the record.")
    return 0


def cmd_apply(args, db: Database, settings) -> int:
    tf = _terraform(settings)
    result = wrapper.guarded_apply(db, tf, settings.environment, reviewer=args.reviewer)
    return 0 if result.outcome.value not in ("failed", "aborted_plan_changed") else 1


def cmd_recheck(args, db: Database, settings) -> int:
    if bool(args.refresh_json) != bool(args.plan_json):
        raise SystemExit("--refresh-json and --plan-json must be given together")
    environment = settings.environment
    if args.refresh_json:
        if not args.label:
            raise SystemExit("--label authored-fixture|real-fixture is required with --refresh-json/--plan-json")
        refresh, plan = _load_json(args.refresh_json), _load_json(args.plan_json)
        environment = env_for(settings, args.label)
    else:
        tf = _terraform(settings)
        refresh = plan = None
        try:
            tf.plan(SCAN_PLAN, refresh_only=True)
            refresh = tf.show_json(SCAN_PLAN)
            tf.plan(APPLY_PLAN)
            plan = tf.show_json(APPLY_PLAN)
        except TerraformError as e:
            print(f"RECHECK FAILED: {e}")
        finally:
            tf.cleanup()  # the recheck plan is never applied
    res = service.recheck(db, environment, refresh, plan)
    if res.status != "ok":
        print("RECHECK FAILED: verification unavailable. Nothing was resolved.")
        for e in res.errors:
            print(f"  - {e}")
    for rid in res.resolved_ids:
        print(f"resolved (verified aligned): {rid}")
    for rid, why in res.still_open.items():
        print(f"still open: {rid} - {why}")
    if not res.resolved_ids and not res.still_open:
        print("No open records.")
    return 0 if res.status == "ok" else 1


def cmd_seed_demo(args, db: Database, settings) -> int:
    plan = _load_json(str(AUTHORED_DEMO_FIXTURE))
    res = service.ingest_refresh_plan(db, env_for(settings, "authored-fixture"), plan, evidence_source="authored-fixture")
    if res.status != "ok":
        print("seed failed:", res.errors)
        return 1
    ids = res.new_ids or res.seen_ids
    if args.with_report and ids:
        service.report(db, ids[0], ReportIn(reporter="Paul", reason="payment webhook blocked, opened 8443",
                                            intent=Intent.KEEP))
    print(f"Seeded AUTHORED demo data (environment={env_for(settings, 'authored-fixture')}, "
          f"evidence_source=authored-fixture): {', '.join(ids)}")
    return 0


def cmd_reset_db(args, db: Database, settings) -> int:
    if not args.yes:
        print("Refusing to delete all records without --yes.")
        return 1
    db.reset()
    print(f"Database reset: {settings.db_path if settings.database_url is None else 'configured PostgreSQL'}")
    return 0


def cmd_migrate_schema(args, db, settings) -> int:
    if settings.database_url is None:
        print("BG_DATABASE_URL is not set; nothing to migrate (SQLite migrates itself).")
        return 2
    from .postgres import migrate
    try:
        applied = migrate(settings.database_url)
    except StorageUnavailable as e:
        print(f"database error: {e}")
        return 3
    print("Applied migrations: " + (", ".join(f"{v:03d}" for v in applied) if applied else "none (already current)"))
    return 0


def cmd_import_sqlite(args, db, settings) -> int:
    from .migrate import ImportRefused, ImportVerificationFailed, import_sqlite
    if settings.database_url is None:
        print("import-sqlite writes into PostgreSQL: set BG_DATABASE_URL (the target) and run migrate-schema first.")
        return 2
    try:
        r = import_sqlite(args.source, db, dry_run=args.dry_run)
    except ImportRefused as e:
        print(f"import refused: {e}")
        return 1
    except ImportVerificationFailed as e:
        print(f"IMPORT VERIFICATION FAILED, do not cut over: {e}")
        return 4
    label = "would import" if r.dry_run else "imported"
    print(f"{label}: " + ", ".join(f"{k}={v}" for k, v in r.imported.items())
          + " | already present: " + ", ".join(f"{k}={v}" for k, v in r.already_present.items()))
    if not r.dry_run:
        print(f"verified against the source snapshot: {r.verified}; activity aggregate refreshed: {r.aggregate_refreshed}")
    for n in r.notes:
        print(n)
    return 0


def cmd_demo_reset(args, db: Database, settings) -> int:
    tf = None
    if settings.tf_dir is not None and not args.skip_cloud_check:
        tf = Terraform(settings.tf_dir, binary=settings.terraform_bin)
    return demo.demo_reset(db, settings, tf, yes=args.yes, check_cloud=not args.skip_cloud_check)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="breakglass", description="Argus: emergency-change context for Terraform applies.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="detect manual changes with a Terraform refresh-only plan (never applied)")
    s.add_argument("--from-json", help="read a saved `terraform show -json` refresh-only plan instead of running Terraform")
    s.add_argument("--label", choices=["authored-fixture", "real-fixture"],
                   help="required with --from-json; fixture data is kept in a separate environment")
    s.add_argument("--no-prompt", action="store_true", help="do not ask for reasons")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("list", help="list records (open by default)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true")
    g.add_argument("--resolved", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="show one record as JSON")
    s.add_argument("id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("report", help="record what changed and why (self-reported)")
    s.add_argument("id")
    s.add_argument("--reason")
    s.add_argument("--reporter")
    s.add_argument("--intent", choices=[i.value for i in Intent if i != Intent.UNSET])
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("decide", help="save an intent (does not apply or resolve)")
    s.add_argument("id")
    s.add_argument("intent", choices=[i.value for i in Intent if i != Intent.UNSET])
    s.add_argument("--note")
    s.add_argument("--reviewer", help="name recorded with this decision (self-reported)")
    s.set_defaults(func=cmd_decide)

    s = sub.add_parser("apply", help="plan, warn about reversed emergency changes, apply only after explicit confirmation")
    s.add_argument("--reviewer", help="name recorded with your decision (self-reported); default: your OS user name")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("recheck", help="resolve records only when live, state and config provably agree")
    s.add_argument("--refresh-json")
    s.add_argument("--plan-json")
    s.add_argument("--label", choices=["authored-fixture", "real-fixture"],
                   help="required with --refresh-json/--plan-json; only touches that fixture environment")
    s.set_defaults(func=cmd_recheck)

    s = sub.add_parser("seed-demo", help="load AUTHORED demo data for frontend integration")
    s.add_argument("--with-report", action="store_true", help="also add a sample self-reported reason")
    s.set_defaults(func=cmd_seed_demo)

    s = sub.add_parser("reset-db", help="delete all records and apply runs")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_reset_db)

    s = sub.add_parser("migrate-schema", help="create/upgrade the PostgreSQL (Tiger Cloud) schema; needs a DDL-capable BG_DATABASE_URL")
    s.set_defaults(func=cmd_migrate_schema)

    s = sub.add_parser("import-sqlite", help="copy a SQLite history into the configured PostgreSQL (read-only source)")
    s.add_argument("--source", required=True, help="path to the SQLite file (read through a snapshot, never modified)")
    s.add_argument("--dry-run", action="store_true", help="validate and count without writing")
    s.set_defaults(func=cmd_import_sqlite)

    s = sub.add_parser("demo-reset", help="wipe local demo data and run a read-only preflight (never changes the cloud)")
    s.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    s.add_argument("--skip-cloud-check", action="store_true", help="do not run the read-only refresh-only plan")
    s.set_defaults(func=cmd_demo_reset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"config error: {e}")
        return 2
    if args.func is cmd_migrate_schema:  # needs DDL rights and must work before the schema exists
        return cmd_migrate_schema(args, None, settings)
    try:
        db = open_database(settings)
    except StorageUnavailable as e:
        print(f"database error: {e}")
        return 3
    try:
        return args.func(args, db, settings)
    except StorageUnavailable as e:
        print(f"database error: {e}")
        return 3
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
