"""SQLite persistence. One file, stdlib sqlite3, parameterized queries only.

Records hold FirewallRule values as JSON. All timestamps are stored as ISO 8601
UTC strings with offset.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import FirewallRule

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    resource_address TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    attribute TEXT NOT NULL,
    change_kind TEXT NOT NULL,
    baseline_json TEXT,
    observed_json TEXT,
    scope_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL,
    first_detected_at TEXT NOT NULL,
    last_detected_at TEXT NOT NULL,
    reporter TEXT,
    reason TEXT,
    reported_at TEXT,
    intent TEXT NOT NULL DEFAULT 'unset',
    intent_note TEXT,
    intent_updated_at TEXT,
    resolution TEXT NOT NULL DEFAULT 'open',
    resolution_reason TEXT,
    resolved_at TEXT,
    superseded_by TEXT,
    last_check_status TEXT NOT NULL,
    last_check_at TEXT,
    evidence_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_open_fp ON records(environment, fingerprint, resolution);
CREATE INDEX IF NOT EXISTS idx_records_scope ON records(environment, scope_key, resolution);

CREATE TABLE IF NOT EXISTS apply_runs (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    plan_fingerprint TEXT,
    proposed_changes_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    check_status TEXT NOT NULL,
    coverage_note TEXT NOT NULL,
    ack_outcome TEXT NOT NULL,
    ack_note TEXT,
    completed_at TEXT
);

-- Append-only history (PRD R6/R10). Rows are never updated or deleted by the app
-- (only `breakglass reset-db --yes` clears demo data).
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    record_id TEXT,
    run_id TEXT,
    kind TEXT NOT NULL,
    actor TEXT,
    actor_assurance TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_record ON events(record_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, created_at);

CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);
"""

RECORD_COLUMNS = (
    "id environment resource_address resource_type attribute change_kind baseline_json "
    "observed_json scope_key fingerprint summary first_detected_at last_detected_at reporter "
    "reason reported_at intent intent_note intent_updated_at resolution resolution_reason "
    "resolved_at superseded_by last_check_status last_check_at evidence_source"
).split()

UPDATABLE_RECORD_FIELDS = frozenset(RECORD_COLUMNS) - {"id", "environment", "fingerprint", "scope_key"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed")
    # Fixed width (always microseconds, always UTC 'Z') so text ORDER BY sorts chronologically.
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def rule_to_json(rule: FirewallRule | None) -> str | None:
    return None if rule is None else json.dumps(rule.to_dict(), sort_keys=True)


def rule_from_json(raw: str | None) -> FirewallRule | None:
    if raw is None:
        return None
    d = json.loads(raw)
    return FirewallRule(
        action=d.get("action") or "allow",  # rows written before action existed
        protocol=d.get("protocol"),
        port_range=d.get("port_range"),
        source_addresses=tuple(d.get("source_addresses", [])),
        source_tags=tuple(d.get("source_tags", [])),
        source_droplet_ids=tuple(d.get("source_droplet_ids", [])),
        source_load_balancer_uids=tuple(d.get("source_load_balancer_uids", [])),
        source_kubernetes_ids=tuple(d.get("source_kubernetes_ids", [])),
    )


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Additive column migrations for databases created by older versions."""
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(apply_runs)")}
        for col in ("started_at", "reviewer", "reviewer_assurance", "rationale"):
            if col not in have:
                try:
                    self._conn.execute(f"ALTER TABLE apply_runs ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():  # another process migrated first
                        raise

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        # One shared connection; the lock makes each transaction exclusive across threads.
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _x(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, args)

    def _all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _one(self, sql: str, args=()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def ping(self) -> bool:
        self._one("SELECT 1")
        return True

    # ---- records -------------------------------------------------------
    def insert_record(self, row: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        cols = [k for k in RECORD_COLUMNS if k in row]
        (conn.execute if conn else self._x)(
            f"INSERT INTO records ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[k] for k in cols],
        )

    def update_record(self, record_id: str, fields: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        bad = set(fields) - UPDATABLE_RECORD_FIELDS
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        (conn.execute if conn else self._x)(f"UPDATE records SET {assignments} WHERE id = ?", [*fields.values(), record_id])

    def get_record(self, record_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM records WHERE id = ?", (record_id,))

    def list_records(self, resolution: str | None = None, environment: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM records WHERE 1=1"
        args: list[Any] = []
        if resolution is not None:
            q += " AND resolution = ?"
            args.append(resolution)
        if environment is not None:
            q += " AND environment = ?"
            args.append(environment)
        q += " ORDER BY first_detected_at DESC, id DESC"
        return self._all(q, args)

    def find_open_by_fingerprint(self, environment: str, fingerprint: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
        sql = "SELECT * FROM records WHERE environment = ? AND fingerprint = ? AND resolution = 'open'"
        args = (environment, fingerprint)
        return conn.execute(sql, args).fetchone() if conn else self._one(sql, args)

    def find_open_by_scope(self, environment: str, scope_key: str, conn: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM records WHERE environment = ? AND scope_key = ? AND resolution = 'open'"
        args = (environment, scope_key)
        return conn.execute(sql, args).fetchall() if conn else self._all(sql, args)

    # ---- apply runs ----------------------------------------------------
    def insert_apply_run(self, row: dict[str, Any]) -> None:
        cols = list(row)
        self._x(
            f"INSERT INTO apply_runs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[k] for k in cols],
        )

    def update_apply_run(self, run_id: str, fields: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        allowed = {"plan_fingerprint", "proposed_changes_json", "warnings_json", "check_status",
                   "coverage_note", "ack_outcome", "ack_note", "completed_at", "started_at",
                   "reviewer", "reviewer_assurance", "rationale"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        (conn.execute if conn else self._x)(f"UPDATE apply_runs SET {assignments} WHERE id = ?", [*fields.values(), run_id])

    def get_apply_run(self, run_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM apply_runs WHERE id = ?", (run_id,))

    def list_apply_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM apply_runs ORDER BY generated_at DESC, id DESC LIMIT ?", (limit,))

    def mark_unfinished_runs_unknown(self, environment: str, exclude_id: str) -> list[str]:
        """PRD R8: a run with no recorded completion is shown as unknown, never as success."""
        with self.tx() as c:
            ids = [r["id"] for r in c.execute(
                "SELECT id FROM apply_runs WHERE environment = ? AND id != ? AND completed_at IS NULL "
                "AND ack_outcome IN ('pending', 'running')", (environment, exclude_id))]
            note = "no completion recorded (interrupted or crashed); outcome unknown"
            now_s = ts(datetime.now(timezone.utc))
            for rid in ids:
                c.execute("UPDATE apply_runs SET ack_outcome = 'unknown', ack_note = ? WHERE id = ?", (note, rid))
                # Keep the history complete: the change to "unknown" is itself an event.
                self.insert_event({"id": new_id("evt"), "environment": environment, "record_id": None,
                                   "run_id": rid, "kind": "run_finished", "actor": None,
                                   "actor_assurance": "system",
                                   "data_json": json.dumps({"outcome": "unknown", "applied": None, "note": note}),
                                   "created_at": now_s}, c)
        return ids

    # ---- events (append-only) ------------------------------------------
    def insert_event(self, row: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        cols = ["id", "environment", "record_id", "run_id", "kind", "actor", "actor_assurance",
                "data_json", "created_at"]
        sql = f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        (conn.execute if conn else self._x)(sql, [row.get(k) for k in cols])

    def list_events(self, record_id: str | None = None, run_id: str | None = None,
                    limit: int = 200) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM events WHERE 1=1", []
        if record_id is not None:
            q += " AND record_id = ?"
            args.append(record_id)
        if run_id is not None:
            q += " AND run_id = ?"
            args.append(run_id)
        q += " ORDER BY created_at DESC, rowid DESC LIMIT ?"  # rowid = insertion order within a tx
        args.append(limit)
        return list(reversed(self._all(q, args)))  # the newest `limit` events, oldest first

    def list_all_events(self) -> list[sqlite3.Row]:
        """Every event, oldest first (insertion order breaks timestamp ties). Unbounded on purpose:
        the admin log must not silently drop history."""
        return self._all("SELECT * FROM events ORDER BY created_at ASC, rowid ASC")

    def list_all_apply_runs(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM apply_runs ORDER BY generated_at ASC, id ASC")

    # ---- scans ---------------------------------------------------------
    def insert_scan(self, scan_id: str, environment: str, started_at: str, status: str, detail: str | None) -> None:
        self._x(
            "INSERT INTO scans (id, environment, started_at, status, detail) VALUES (?, ?, ?, ?, ?)",
            (scan_id, environment, started_at, status, detail),
        )

    def last_scan(self, environment: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT started_at, status FROM scans WHERE environment = ? ORDER BY started_at DESC, id DESC LIMIT 1",
            (environment,),
        )

    def reset(self) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM records")
            c.execute("DELETE FROM apply_runs")
            c.execute("DELETE FROM scans")
            c.execute("DELETE FROM events")
