"""Hourly activity counts over the audit event history.

This counts events. A decision made on the web and a review in the wrapper are different events,
not two incidents; an unknown run outcome is never counted as a failure; nothing here estimates
downtime, MTTR or root cause.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from .models import ActivityBucket, ActivityOut, ActivityTotals, utcnow
from .service import BadInput

MAX_WINDOW = timedelta(days=31)
HOUR = timedelta(hours=1)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_bucket(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def align_window(since: datetime, until: datetime) -> tuple[datetime, datetime]:
    """Widen outward to whole UTC hours so no bucket is partial; the widened window is returned to the caller."""
    s = since.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    u = until.astimezone(timezone.utc)
    u_floor = u.replace(minute=0, second=0, microsecond=0)
    u = u_floor if u_floor == u else u_floor + HOUR
    if u <= s:
        raise BadInput("until must be after since")
    if u - s > MAX_WINDOW:
        raise BadInput(f"window too large (max {MAX_WINDOW.days} days)")
    return s, u


def activity(db, environment: str, since: datetime, until: datetime) -> ActivityOut:
    environment = environment.strip()
    if not environment:
        raise BadInput("environment is required")
    s, u = align_window(since, until)
    rows = db.activity_counts(environment, s, u)  # raises StorageUnavailable -> 503, never zero activity

    per_bucket: dict[datetime, Counter] = {}
    by_kind, by_intent, by_decision, by_outcome = Counter(), Counter(), Counter(), Counter()
    for r in rows:
        n = int(r["n"])
        per_bucket.setdefault(_parse_bucket(r["bucket"]), Counter())[r["kind"]] += n
        by_kind[r["kind"]] += n
        if r.get("intent"):
            by_intent[r["intent"]] += n
        if r.get("decision"):
            by_decision[r["decision"]] += n
        if r.get("outcome"):
            by_outcome[r["outcome"]] += n

    buckets, t = [], s
    while t < u:
        c = per_bucket.get(t, Counter())
        buckets.append(ActivityBucket(start=_z(t), total=sum(c.values()), by_kind=dict(c)))
        t += HOUR

    cagg = db.backend_name == "timescaledb"
    return ActivityOut(
        backend=db.backend_name, bucket_size="1 hour", environment=environment, since=_z(s), until=_z(u),
        generated_at=_z(utcnow()), buckets=buckets,
        totals=ActivityTotals(by_kind=dict(by_kind), by_intent=dict(by_intent),
                              by_decision=dict(by_decision), by_outcome=dict(by_outcome)),
        freshness={
            "mode": "real-time continuous aggregate" if cagg else "computed on request from SQLite (offline mode)",
            "refresh_policy": "every 15 minutes over the last 3 days" if cagg else None,
            "historical_backfills_need_explicit_refresh": cagg,
        },
        limitations=[
            "Counts audit events, not incidents; a web decision and a wrapper review are separate events.",
            "Run outcomes marked unknown are counted as unknown, never as failed.",
            "Detection and resolution are derived from records today and are not counted here.",
            "Not a measure of downtime or time to recovery.",
        ],
    )
