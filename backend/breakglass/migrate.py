"""Import a SQLite history into the configured database (Tiger Cloud).

Safety rules: the source is read through a SQLite backup-API snapshot (never a raw file copy, safe
with a live WAL) and is never modified; the target must be empty or already hold exactly some of
the same rows; a conflicting row is a refusal, never an overwrite; everything is written in one
transaction; the result is re-read and compared value by value before it is reported as verified.
Original IDs, timestamps, actors and evidence sources are preserved. Nothing is invented.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import RECORD_COLUMNS, ts

RUN_REQUIRED = ["id", "environment", "generated_at", "plan_fingerprint", "proposed_changes_json", "warnings_json",
                "check_status", "coverage_note", "ack_outcome", "ack_note", "completed_at"]
RUN_OPTIONAL = ["started_at", "reviewer", "reviewer_assurance", "rationale"]  # added by later versions
SCAN_COLS = ["id", "environment", "started_at", "status", "detail"]
EVENT_COLS = ["id", "environment", "record_id", "run_id", "kind", "actor", "actor_assurance", "data_json",
              "created_at"]
SPEC = {  # table -> (required columns, optional columns)
    "records": (RECORD_COLUMNS, []),
    "apply_runs": (RUN_REQUIRED, RUN_OPTIONAL),
    "scans": (SCAN_COLS, []),
    "events": (EVENT_COLS, []),
}
ORDER = {"records": "rowid", "apply_runs": "rowid", "scans": "rowid", "events": "rowid"}


class ImportRefused(Exception):
    """The import was not performed (or was rolled back); the message says why."""


class ImportVerificationFailed(RuntimeError):
    """Rows were written but the re-read did not match the source. Do not cut over."""


@dataclass
class ImportReport:
    dry_run: bool
    imported: dict[str, int]
    already_present: dict[str, int]
    verified: bool = False
    aggregate_refreshed: bool = False
    notes: list[str] = field(default_factory=list)


def _snapshot(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ImportRefused(f"source not found: {path}")
    try:
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        mem = sqlite3.connect(":memory:")
        src.backup(mem)  # consistent snapshot, includes committed WAL content
        src.close()
    except sqlite3.Error as e:
        raise ImportRefused(f"source is not a readable SQLite database ({type(e).__name__})") from None
    mem.row_factory = sqlite3.Row
    return mem


def _norm_ts(table: str, row: dict[str, Any], col: str) -> None:
    v = row.get(col)
    if v is None:
        return
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        row[col] = ts(dt)  # raises ValueError for naive values
    except (ValueError, TypeError):
        raise ImportRefused(f"invalid timestamp in {table} id={row.get('id')} column {col}") from None


def _read_source(snap: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for table, (required, optional) in SPEC.items():
        have = {r["name"] for r in snap.execute(f"PRAGMA table_info({table})")}
        missing = [c for c in required if c not in have]
        if missing or not have:
            raise ImportRefused(f"incompatible source schema: table {table} "
                                + ("is missing" if not have else f"lacks columns {missing}"))
        cols = required + [c for c in optional if c in have]
        rows = []
        for r in snap.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {ORDER[table]}"):
            d = {c: r[c] for c in cols}
            for c in optional:
                d.setdefault(c, None)
            for c in d:
                if c.endswith("_at"):
                    _norm_ts(table, d, c)
            rows.append(d)
        ids = [r["id"] for r in rows]
        if len(ids) != len(set(ids)):
            raise ImportRefused(f"source has duplicate ids in {table}")
        out[table] = rows
    return out


def _target_rows(target) -> dict[str, list[dict[str, Any]]]:
    return {"records": [dict(r) for r in target.list_records()],
            "apply_runs": [dict(r) for r in target.list_all_apply_runs()],
            "scans": [dict(r) for r in target.list_scans()],
            "events": [dict(r) for r in target.list_all_events()]}


def _same(src: dict[str, Any], tgt: dict[str, Any]) -> bool:
    return all(tgt.get(k) == v for k, v in src.items())  # compare on the source's columns only


def import_sqlite(source: Path | str, target, *, dry_run: bool = False) -> ImportReport:
    snap = _snapshot(Path(source))
    try:
        data = _read_source(snap)
    finally:
        snap.close()

    existing = _target_rows(target)
    imported, present, to_write = {}, {}, {}
    for table, rows in data.items():
        have = {r["id"]: r for r in existing[table]}
        conflicts = [r["id"] for r in rows if r["id"] in have and not _same(r, have[r["id"]])]
        if conflicts:
            raise ImportRefused(f"conflict: {table} ids differ between source and target: {conflicts[:5]}")
        src_ids = {r["id"] for r in rows}
        extras = [i for i in have if i not in src_ids]
        if extras:
            raise ImportRefused(f"target is not empty: {len(extras)} {table} row(s) are not in the source "
                                "(use a dedicated empty database/schema)")
        to_write[table] = [r for r in rows if r["id"] not in have]
        imported[table] = len(to_write[table])
        present[table] = len(rows) - len(to_write[table])
    if dry_run:
        return ImportReport(True, imported, present, notes=["dry run: nothing was written"])

    with target.tx() as conn:  # all or nothing
        for r in to_write["records"]:
            target.insert_record(r, conn)
        for r in to_write["apply_runs"]:
            target.insert_apply_run(r, conn)
        for r in to_write["scans"]:
            target.insert_scan(r["id"], r["environment"], r["started_at"], r["status"], r["detail"], conn)
        for r in to_write["events"]:  # original insertion order keeps tie-breaking identical
            target.insert_event(r, conn)

    after = _target_rows(target)
    for table, rows in data.items():
        got = {r["id"]: r for r in after[table]}
        if len(got) != len(rows) or not all(r["id"] in got and _same(r, got[r["id"]]) for r in rows):
            raise ImportVerificationFailed(f"{table}: target does not match the source after import")
    # target order is (created_at, seq); the source equivalent is (created_at, rowid) = a stable sort
    expected = sorted(data["events"], key=lambda e: e["created_at"])
    if [e["id"] for e in after["events"]] != [e["id"] for e in expected]:
        raise ImportVerificationFailed("events: order differs from the source")

    report = ImportReport(False, imported, present, verified=True)
    if data["events"] and hasattr(target, "refresh_activity"):
        times = [datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) for e in data["events"]]
        lo = min(times).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        target.refresh_activity(lo, max(times) + timedelta(hours=1))  # backfills need an explicit refresh
        report.aggregate_refreshed = True
    report.notes.append("Detection/resolution events are not backfilled; history for those stays record-derived.")
    return report
