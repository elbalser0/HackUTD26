import type { EmergencyRecord, Health } from "../api";
import { Notice } from "./States";

/** Banners for an unhealthy backend and for records the latest check did not confirm. */
export function Freshness({
  health,
  records,
}: {
  health: Health | null;
  records: EmergencyRecord[];
}) {
  const bad = records.filter((r) => r.lastCheckStatus !== "current").length;
  return (
    <>
      {(!health || health.status !== "ok") && (
        <Notice tone="warn">
          Backend health is{" "}
          {health ? `"${health.status}" (db: ${health.db})` : "unreachable"}.
          Records below may be incomplete.
        </Notice>
      )}
      {bad > 0 && (
        <Notice tone="warn">
          {bad} record{bad === 1 ? "" : "s"} not confirmed by the latest check
          (stale, failed or unsupported). Their live values may have changed.
        </Notice>
      )}
    </>
  );
}
