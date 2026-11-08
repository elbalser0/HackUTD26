import type { AdminEvent } from "./api";
import { humanize } from "./overview";

export const EVENT_LABEL: Record<AdminEvent["type"], string> = {
  change_detected: "Detected",
  explained: "Report",
  decision: "Decision",
  review: "Review",
  run_started: "Apply started",
  run_finished: "Apply finished",
  run_unfinished: "Apply unfinished",
  resolved: "Resolved",
};

/** A run that ended unknown or failed (or never finished) is drawn as a warning. */
export function isAlarming(e: AdminEvent): boolean {
  if (e.type === "run_unfinished") return true;
  return e.type === "run_finished" && (e.outcome === "unknown" || e.outcome === "failed");
}

/** How reliable "who" is. Never claims more than the server said. */
export function assuranceTag(assurance: string | null): { label: string; tone: string } | null {
  if (!assurance || assurance === "system") return null;
  if (assurance === "self-reported") return { label: "self-reported", tone: "" };
  if (assurance.startsWith("google-account")) return { label: "verified sign-in", tone: "green" };
  if (assurance.startsWith("local-os-user")) return { label: "local user, not verified", tone: "" };
  return { label: assurance, tone: "" };
}

/**
 * The backend starts a run's detail with "outcome: X" (optionally "— note").
 * The outcome is stated on its own line, so drop only that leading prefix.
 */
export function withoutOutcomePrefix(detail: string | null, outcome: string | null): string | null {
  if (!detail || !outcome) return detail;
  const prefix = `outcome: ${outcome}`;
  if (!detail.startsWith(prefix)) return detail;
  return detail.slice(prefix.length).replace(/^\s*—\s*/, "").trim() || null;
}

export function outcomeText(outcome: string): string {
  return outcome === "unknown"
    ? "Outcome unknown, no completion recorded"
    : `Outcome: ${humanize(outcome)}`;
}

/** "Nov 8, 02:55" (UTC) */
export function shortUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown time";
  const day = d.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return `${day}, ${d.toISOString().slice(11, 16)}`;
}

/** The most recent run result linked to a record, or null when no run touched it. */
export function linkedRun(events: AdminEvent[]): AdminEvent | null {
  const runs = events.filter((e) => e.type === "run_finished" || e.type === "run_unfinished");
  if (runs.length === 0) return null;
  return runs.reduce((a, b) => (Date.parse(b.at) >= Date.parse(a.at) ? b : a));
}

export const HISTORY_TITLE: Record<AdminEvent["type"], string> = {
  change_detected: "Detected by scan",
  explained: "Report",
  decision: "Decision",
  review: "Reviewed at apply",
  run_started: "Apply started",
  run_finished: "Apply finished",
  run_unfinished: "Apply unfinished",
  resolved: "Resolved",
};

const GAP_TITLE: Record<string, string> = {
  no_reason_recorded: "No reason recorded",
  no_decision_recorded: "No decision recorded",
  no_run_linked: "No run linked",
  run_outcome_unknown: "Run outcome unknown",
};
export const gapTitle = (code: string) => GAP_TITLE[code] ?? humanize(code);
