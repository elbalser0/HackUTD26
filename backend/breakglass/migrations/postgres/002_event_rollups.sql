-- Hourly activity rollup over the events hypertable. Counts audit events; it does not infer
-- incidents, downtime or root cause. Real-time aggregation is disabled by default in modern
-- TimescaleDB, so it is switched on explicitly: queries see materialized buckets plus the raw tail.
-- WITH NO DATA: the history is materialized by an explicit, bounded refresh (see `refresh_activity`),
-- because a backfill behind the watermark is invisible until its window is refreshed.
CREATE MATERIALIZED VIEW activity_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', created_at) AS bucket,
       environment, kind, intent, decision, outcome,
       count(*) AS n
FROM events
GROUP BY 1, 2, 3, 4, 5, 6
WITH NO DATA;

SELECT add_continuous_aggregate_policy('activity_hourly',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes');
