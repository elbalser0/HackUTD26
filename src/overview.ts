import type { Overview } from "./api";

type Activity = Overview["activity"];

export interface BarKinds {
  report: number;
  review: number;
  run: number;
  other: number;
}

/** Every event type lands in exactly one chart kind, so the bars add up to the event count. */
export function barKinds(counts: Record<string, number>): BarKinds {
  const k: BarKinds = { report: 0, review: 0, run: 0, other: 0 };
  for (const [type, n] of Object.entries(counts)) {
    if (type === "explained") k.report += n;
    else if (type === "review") k.review += n;
    else if (type === "run_finished" || type === "run_unfinished") k.run += n;
    else k.other += n;
  }
  return k;
}

export const totalOf = (counts: Record<string, number>) =>
  Object.values(counts).reduce((a, b) => a + b, 0);

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const hh = (iso: string) => String(new Date(iso).getUTCHours()).padStart(2, "0");
const day = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** Text alternative for the chart. */
export function chartSummary(activity: Activity, window: "24h" | "7d"): string {
  const span = window === "7d" ? "7 days" : "24 hours";
  const head = `Events per hour over the last ${span}.`;
  const totals = activity.map((b) => totalOf(b.counts));
  const total = totals.reduce((a, b) => a + b, 0);
  if (total === 0) return `${head} No events.`;
  const max = Math.max(...totals);
  const at = activity[totals.indexOf(max)].hour;
  const when = window === "7d" ? `${day(at)}, ${hh(at)}:00 UTC` : `${hh(at)}:00 UTC`;
  return `${head} ${plural(total, "event")} in total. Busiest hour: ${plural(max, "event")} at ${when}.`;
}

/** "applied_no_warnings" -> "Applied no warnings" */
export function humanize(code: string): string {
  const t = code.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

const EVENT_ORDER = [
  "change_detected",
  "explained",
  "decision",
  "review",
  "run_started",
  "run_finished",
  "run_unfinished",
  "resolved",
];

/** "4 explained, 1 review, 2 run unfinished": canonical order, zero counts left out. */
export function eventBreakdown(byType: Record<string, number>): string {
  const known = EVENT_ORDER.filter((t) => (byType[t] ?? 0) > 0);
  const extra = Object.keys(byType).filter((t) => !EVENT_ORDER.includes(t) && byType[t] > 0).sort();
  return [...known, ...extra].map((t) => `${byType[t]} ${t.replace(/_/g, " ")}`).join(", ");
}

/** Run outcomes present in the window: unknown first, then failed, then the rest A to Z. */
export function outcomeRows(outcomes: Record<string, number>): { code: string; count: number }[] {
  const rank = (c: string) => (c === "unknown" ? 0 : c === "failed" ? 1 : 2);
  return Object.entries(outcomes)
    .filter(([, n]) => n > 0)
    .map(([code, count]) => ({ code, count }))
    .sort((a, b) => rank(a.code) - rank(b.code) || a.code.localeCompare(b.code));
}

export function axisLabel(hour: string, index: number, window: "24h" | "7d"): string {
  if (window === "24h") return index % 3 === 0 ? hh(hour) : "";
  return hh(hour) === "00" ? day(hour) : "";
}

/** "5 events at 02:00 UTC" (with the date in the 7 d view) */
export function barLabel(b: Activity[number], window: "24h" | "7d"): string {
  const n = totalOf(b.counts);
  const when = window === "7d" ? `${day(b.hour)}, ${hh(b.hour)}:00 UTC` : `${hh(b.hour)}:00 UTC`;
  return `${plural(n, "event")} at ${when}`;
}
