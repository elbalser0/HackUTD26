"""PostgreSQL / TimescaleDB (Tiger Cloud) repository with the same interface as db.Database.

Rows come back as dicts shaped like the SQLite ones: timestamps are fixed-width UTC strings,
JSON stays a string. A connection is opened per transaction/read (no shared state between
threads or processes); every failure to reach or write the database surfaces as
StorageUnavailable with no DSN or driver detail, and nothing here ever falls back to SQLite.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Iterator
from urllib.parse import urlsplit

import psycopg
from psycopg import errors as pgerr
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .db import RECORD_COLUMNS, UPDATABLE_RECORD_FIELDS, new_id, ts
from .storage import StorageUnavailable

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_EVENT_COLS = ["id", "environment", "record_id", "run_id", "kind", "actor", "actor_assurance",
               "data_json", "created_at"]
_RUN_UPDATABLE = {"plan_fingerprint", "proposed_changes_json", "warnings_json", "check_status",
                  "coverage_note", "ack_outcome", "ack_note", "completed_at", "started_at",
                  "reviewer", "reviewer_assurance", "rationale"}
_MIGRATION_LOCK = 7_240_001  # advisory lock key for schema migrations


def _migration_files() -> list[tuple[int, str, str]]:
    out = []
    for f in resources.files("breakglass").joinpath("migrations/postgres").iterdir():
        m = re.match(r"^(\d+)_.*\.sql$", f.name)
        if m:
            out.append((int(m.group(1)), f.name, f.read_text(encoding="utf-8")))
    return sorted(out)


def latest_version() -> int:
    return max(v for v, _, _ in _migration_files())


def _conninfo(url: str, schema: str | None, statement_timeout_ms: int, connect_timeout: int) -> str:
    host = urlsplit(url).hostname or ""
    extra: dict[str, Any] = {"connect_timeout": connect_timeout, "application_name": "argus"}
    if host not in _LOOPBACK and "sslmode=" not in url:
        extra["sslmode"] = "require"  # never a plaintext link to a cloud host by omission
    path = f"{schema},public" if schema else "public"
    extra["options"] = (f"-c search_path={path} -c statement_timeout={statement_timeout_ms} "
                        f"-c lock_timeout={statement_timeout_ms} -c idle_in_transaction_session_timeout=60000")
    return make_conninfo(url, **extra)


def _url_connect_timeout(url: str) -> int | None:
    from urllib.parse import parse_qs
    try:
        return int(parse_qs(urlsplit(url).query).get("connect_timeout", [""])[0])
    except ValueError:
        return None


def _to_dt(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _arg(col: str, v: Any) -> Any:
    return _to_dt(v) if col.endswith("_at") and isinstance(v, str) else v


def _out(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: (ts(v) if isinstance(v, datetime) else v) for k, v in row.items()}


@contextmanager
def _guard() -> Iterator[None]:
    """Translate connectivity/read-only/disk failures into StorageUnavailable (no driver detail)."""
    try:
        yield
    except StorageUnavailable:
        raise
    except (psycopg.OperationalError, psycopg.InterfaceError, pgerr.ReadOnlySqlTransaction,
            pgerr.DiskFull, pgerr.InsufficientResources, pgerr.QueryCanceled) as e:
        raise StorageUnavailable(f"database unavailable or read-only ({type(e).__name__})") from None


class PostgresDatabase:
    def __init__(self, url: str, schema: str | None = None, *, connect_timeout: int = 10,
                 statement_timeout_ms: int = 15000, verify_schema: bool = True, max_connections: int = 8):
        if schema is not None and not _SCHEMA_NAME.match(schema):
            raise ValueError("invalid schema name")
        self._info = _conninfo(url, schema, statement_timeout_ms, connect_timeout)
        # A URL-level connect_timeout (seconds) also bounds how long a caller waits for a connection.
        wait = min(connect_timeout, _url_connect_timeout(url) or connect_timeout)
        # check=: a connection dropped by the server/NAT while idle is replaced, not handed to a caller.
        self._pool = ConnectionPool(self._info, min_size=1, max_size=max_connections, timeout=wait,
                                    max_idle=300, kwargs={"row_factory": dict_row},
                                    check=ConnectionPool.check_connection, open=False)
        self._pool.open()
        try:
            with _guard():
                self._pool.wait(timeout=wait)  # fail fast if unreachable; keeps the pool at its minimum size
            if verify_schema:
                self._verify_schema()
        except BaseException:
            self._pool.close()
            raise

    # ---- connections ---------------------------------------------------
    def _verify_schema(self) -> None:
        with _guard():
            with self._pool.connection() as c:
                try:
                    row = c.execute("SELECT max(version) AS v FROM schema_migrations").fetchone()
                except pgerr.UndefinedTable:
                    row = {"v": None}
        if row["v"] is None or row["v"] < latest_version():
            raise StorageUnavailable("database schema is not migrated; run `breakglass migrate-schema`")

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def tx(self) -> Iterator[psycopg.Connection]:
        # The pool commits on normal exit and rolls back on any exception; a failed or
        # unacknowledged commit raises here, so the caller never believes a lost write was durable.
        with _guard(), self._pool.connection() as conn:
            yield conn

    def _read(self, sql: str, args=(), one: bool = False):
        with _guard(), self._pool.connection() as c:
            cur = c.execute(sql, args)
            return _out(cur.fetchone()) if one else [_out(r) for r in cur.fetchall()]

    def _write(self, sql: str, args, conn) -> None:
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.tx() as c:
            c.execute(sql, args)

    def ping(self) -> bool:
        self._read("SELECT 1 AS ok", one=True)
        return True

    def lock_environment(self, conn, environment: str) -> None:
        """Transaction-scoped advisory lock: scans/guarded workflows on one environment run one at a time."""
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"argus:env:{environment}",))

    # ---- records -------------------------------------------------------
    def insert_record(self, row: dict[str, Any], conn=None) -> None:
        cols = [k for k in RECORD_COLUMNS if k in row]
        self._write(f"INSERT INTO records ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [_arg(k, row[k]) for k in cols], conn)

    def update_record(self, record_id: str, fields: dict[str, Any], conn=None) -> None:
        bad = set(fields) - UPDATABLE_RECORD_FIELDS
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        if not fields:
            return
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._write(f"UPDATE records SET {sets} WHERE id = %s",
                    [*(_arg(k, v) for k, v in fields.items()), record_id], conn)

    def get_record(self, record_id: str, conn=None, for_update: bool = False):
        sql = "SELECT * FROM records WHERE id = %s" + (" FOR UPDATE" if for_update and conn else "")
        if conn is not None:
            return _out(conn.execute(sql, (record_id,)).fetchone())
        return self._read(sql, (record_id,), one=True)

    def list_records(self, resolution: str | None = None, environment: str | None = None):
        q, args = "SELECT * FROM records WHERE true", []
        if resolution is not None:
            q += " AND resolution = %s"
            args.append(resolution)
        if environment is not None:
            q += " AND environment = %s"
            args.append(environment)
        return self._read(q + " ORDER BY first_detected_at DESC, id DESC", args)

    def find_open_by_fingerprint(self, environment: str, fingerprint: str, conn=None):
        sql = "SELECT * FROM records WHERE environment = %s AND fingerprint = %s AND resolution = 'open'"
        if conn is not None:
            return _out(conn.execute(sql, (environment, fingerprint)).fetchone())
        return self._read(sql, (environment, fingerprint), one=True)

    def find_open_by_scope(self, environment: str, scope_key: str, conn=None):
        sql = "SELECT * FROM records WHERE environment = %s AND scope_key = %s AND resolution = 'open'"
        if conn is not None:
            return [_out(r) for r in conn.execute(sql, (environment, scope_key)).fetchall()]
        return self._read(sql, (environment, scope_key))

    def open_record_ids(self, environment: str, conn=None) -> list[str]:
        sql = "SELECT id FROM records WHERE environment = %s AND resolution = 'open' ORDER BY id"
        rows = conn.execute(sql, (environment,)).fetchall() if conn is not None else self._read(sql, (environment,))
        return [r["id"] for r in rows]

    def record_environment(self, record_id: str, conn=None) -> str | None:
        sql = "SELECT environment FROM records WHERE id = %s"
        row = conn.execute(sql, (record_id,)).fetchone() if conn is not None else self._read(sql, (record_id,), one=True)
        return None if row is None else row["environment"]

    # ---- apply runs ----------------------------------------------------
    def insert_apply_run(self, row: dict[str, Any], conn=None) -> None:
        cols = list(row)
        self._write(f"INSERT INTO apply_runs ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [_arg(k, row[k]) for k in cols], conn)

    def update_apply_run(self, run_id: str, fields: dict[str, Any], conn=None) -> None:
        bad = set(fields) - _RUN_UPDATABLE
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._write(f"UPDATE apply_runs SET {sets} WHERE id = %s",
                    [*(_arg(k, v) for k, v in fields.items()), run_id], conn)

    def get_apply_run(self, run_id: str):
        return self._read("SELECT * FROM apply_runs WHERE id = %s", (run_id,), one=True)

    def list_apply_runs(self, limit: int = 20):
        return self._read("SELECT * FROM apply_runs ORDER BY generated_at DESC, id DESC LIMIT %s", (limit,))

    def list_all_apply_runs(self):
        return self._read("SELECT * FROM apply_runs ORDER BY generated_at ASC, id ASC")

    def mark_unfinished_runs_unknown(self, environment: str, exclude_id: str) -> list[str]:
        """PRD R8: a run with no recorded completion is shown as unknown, never as success."""
        note = "no completion recorded (interrupted or crashed); outcome unknown"
        with self.tx() as c:
            ids = [r["id"] for r in c.execute(
                "SELECT id FROM apply_runs WHERE environment = %s AND id != %s AND completed_at IS NULL "
                "AND ack_outcome IN ('pending', 'running') ORDER BY id FOR UPDATE", (environment, exclude_id))]
            now_s = ts(datetime.now(timezone.utc))
            for rid in ids:
                c.execute("UPDATE apply_runs SET ack_outcome = 'unknown', ack_note = %s WHERE id = %s", (note, rid))
                self.insert_event({"id": new_id("evt"), "environment": environment, "record_id": None,
                                   "run_id": rid, "kind": "run_finished", "actor": None,
                                   "actor_assurance": "system",
                                   "data_json": json.dumps({"outcome": "unknown", "applied": None, "note": note}),
                                   "created_at": now_s}, c)
        return ids

    # ---- events (append-only) ------------------------------------------
    def insert_event(self, row: dict[str, Any], conn=None) -> None:
        if conn is None:
            with self.tx() as c:
                self.insert_event(row, c)
            return
        vals = {k: row.get(k) for k in _EVENT_COLS}
        created = _to_dt(vals["created_at"])
        try:
            data = json.loads(vals["data_json"])
        except (TypeError, ValueError):
            data = {}
        dim = lambda k: data.get(k) if isinstance(data, dict) and isinstance(data.get(k), str) else None  # noqa: E731
        # Global ID idempotency: event_keys.id is a plain primary key; same transaction as the event.
        conn.execute("INSERT INTO event_keys (id, created_at) VALUES (%s, %s)", (vals["id"], created))
        conn.execute(
            "INSERT INTO events (id, created_at, environment, record_id, run_id, kind, actor, actor_assurance, "
            "data_json, intent, decision, outcome) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (vals["id"], created, vals["environment"], vals["record_id"], vals["run_id"], vals["kind"],
             vals["actor"], vals["actor_assurance"], vals["data_json"], dim("intent"), dim("decision"),
             dim("outcome")))

    def list_events(self, record_id: str | None = None, run_id: str | None = None, limit: int = 200):
        q, args = "SELECT * FROM events WHERE true", []
        if record_id is not None:
            q += " AND record_id = %s"
            args.append(record_id)
        if run_id is not None:
            q += " AND run_id = %s"
            args.append(run_id)
        args.append(limit)
        rows = self._read(q + " ORDER BY created_at DESC, seq DESC LIMIT %s", args)
        return list(reversed(rows))

    def list_all_events(self):
        """Every event, oldest first (seq breaks timestamp ties). Unbounded on purpose; see admin history task."""
        return self._read("SELECT * FROM events ORDER BY created_at ASC, seq ASC")

    # ---- scans ---------------------------------------------------------
    def insert_scan(self, scan_id: str, environment: str, started_at: str, status: str, detail: str | None,
                    conn=None) -> None:
        self._write("INSERT INTO scans (id, environment, started_at, status, detail) VALUES (%s,%s,%s,%s,%s)",
                    (scan_id, environment, _to_dt(started_at), status, detail), conn)

    def list_scans(self):
        return self._read("SELECT * FROM scans ORDER BY started_at ASC, id ASC")

    def last_scan(self, environment: str):
        return self._read("SELECT started_at, status FROM scans WHERE environment = %s "
                          "ORDER BY started_at DESC, id DESC LIMIT 1", (environment,), one=True)

    backend_name = "timescaledb"

    def activity_counts(self, environment: str, since: datetime, until: datetime) -> list[dict[str, Any]]:
        """Hourly counts for [since, until) read from the real-time continuous aggregate."""
        rows = self._read(
            "SELECT bucket, kind, intent, decision, outcome, sum(n)::bigint AS n FROM activity_hourly "
            "WHERE environment = %s AND bucket >= %s AND bucket < %s GROUP BY 1, 2, 3, 4, 5",
            (environment, since, until))
        return rows

    def refresh_activity(self, since: datetime, until: datetime) -> None:
        """Explicitly (re)materialize [since, until). Required after a backfill behind the watermark."""
        with _guard(), psycopg.connect(self._info, autocommit=True) as c:
            c.execute("CALL refresh_continuous_aggregate('activity_hourly', %s, %s)", (since, until))

    def activity_source_is_cagg(self) -> bool:
        row = self._read("SELECT count(*) AS n FROM timescaledb_information.continuous_aggregates "
                         "WHERE view_name = 'activity_hourly' AND view_schema = current_schema()", one=True)
        return bool(row and row["n"] == 1)

    def reset(self) -> None:
        with self.tx() as c:
            for t in ("records", "apply_runs", "scans", "events", "event_keys"):
                c.execute(f"DELETE FROM {t}")


# ---- migrations (run explicitly, never at app start) ----------------------------------------
def migrate(url: str, schema: str | None = None) -> list[int]:
    """Apply pending migrations under an advisory lock. Needs a role with DDL rights, unlike the app."""
    if schema is not None and not _SCHEMA_NAME.match(schema):
        raise ValueError("invalid schema name")
    info = _conninfo(url, schema, 600_000, 15)
    applied: list[int] = []
    with _guard(), psycopg.connect(info, row_factory=dict_row) as c:
        c.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK,))
        try:
            c.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            if schema:
                c.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                      "(version INT PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            c.commit()
            done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
            for version, name, sql in _migration_files():
                if version in done:
                    continue
                c.execute(sql)
                c.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)", (version, name))
                c.commit()  # each migration is its own transaction
                applied.append(version)
        finally:
            c.rollback()
            c.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK,))
    return applied
