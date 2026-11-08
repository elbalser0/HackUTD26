import type { EmergencyRecord, Intent } from "./api";
import { allTermsIn, termsOf } from "./palette";

export type StatusFilter = "open" | "resolved" | "all";
export interface RecordFilters {
  search: string;
  /** "any" | "none" (no reason yet) | "unnamed" (explained, no name) | a reporter name */
  explainedBy: string;
  /** "any" | an intent value ("unset" included) */
  intent: string;
  status: StatusFilter;
}
export const UNNAMED = "unnamed";

export function filterRecords(records: EmergencyRecord[], f: RecordFilters): EmergencyRecord[] {
  const terms = termsOf(f.search);
  return records
    .filter((r) => {
      if (f.status !== "all" && r.resolution !== f.status) return false;
      if (!allTermsIn(`${r.resourceAddress} ${r.summary}`, terms)) return false;
      if (f.explainedBy === "none" && r.reason !== null) return false;
      if (f.explainedBy === UNNAMED && !(r.reason !== null && r.reporter === null)) return false;
      if (f.explainedBy !== "any" && f.explainedBy !== "none" && f.explainedBy !== UNNAMED && r.reporter !== f.explainedBy)
        return false;
      if (f.intent !== "any" && r.intent !== f.intent) return false;
      return true;
    })
    .sort((a, b) => b.firstDetectedAt.localeCompare(a.firstDetectedAt));
}

export function explainedByOptions(records: EmergencyRecord[]): { value: string; label: string }[] {
  const names = [...new Set(records.map((r) => r.reporter).filter((n): n is string => !!n))].sort();
  const unnamed = records.some((r) => r.reason !== null && r.reporter === null);
  return [
    { value: "any", label: "Anyone" },
    { value: "none", label: "Nobody yet" },
    ...names.map((n) => ({ value: n, label: n })),
    ...(unnamed ? [{ value: UNNAMED, label: "No name given" }] : []),
  ];
}

export const INTENT_OPTIONS: { value: string; label: string }[] = [
  { value: "any", label: "Any" },
  { value: "keep", label: "Keep" },
  { value: "revert", label: "Revert" },
  { value: "unsure", label: "Undecided" },
  { value: "defer", label: "Deferred" },
  { value: "unset", label: "Not set" },
];

export function intentLabel(i: Intent): string | null {
  return INTENT_OPTIONS.find((o) => o.value === i)?.label ?? null;
}

const LAST_ACTIVITY: Record<string, string> = {
  detected: "Detected by scan",
  report: "Report",
  decision: "Decision",
  review: "Review",
  run_started: "Apply started",
  run_finished: "Apply finished",
  resolved: "Resolved",
};
export const activityLabel = (type: string) => LAST_ACTIVITY[type] ?? type.replace(/_/g, " ");

export type RangeKey = "24h" | "7d" | "all";
/** ISO lower bound for a range, or undefined for all time. */
export function rangeSince(range: RangeKey, now: number): string | undefined {
  if (range === "all") return undefined;
  return new Date(now - (range === "24h" ? 24 : 168) * 3_600_000).toISOString();
}

const hh = (d: Date) => String(d.getUTCHours()).padStart(2, "0");
/** One whole UTC hour from the URL (`?hour=`), inclusive end; null when missing or not a date. */
export function hourRange(
  hour: string | null,
): { since: string; until: string; span: string; label: string } | null {
  if (!hour) return null;
  const t = Date.parse(hour);
  if (Number.isNaN(t)) return null;
  const start = new Date(t - (t % 3_600_000));
  const end = new Date(start.getTime() + 3_600_000);
  const day = start.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  const span = `${day}, ${hh(start)}:00–${hh(end)}:00 UTC`;
  return {
    since: start.toISOString(),
    until: new Date(end.getTime() - 1).toISOString(),
    span,
    label: `Hour: ${span}`,
  };
}
