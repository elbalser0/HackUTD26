import type { EmergencyRecord } from "./api";

/** Lowercased, whitespace-split search terms. Every term must match (AND). */
export function termsOf(query: string): string[] {
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean);
}

export function allTermsIn(haystack: string, terms: string[]): boolean {
  const h = haystack.toLowerCase();
  return terms.every((t) => h.includes(t));
}

/** Employee scope: the resource, its summary, or who explained it. Not the reason text. */
export function recordMatches(r: EmergencyRecord, terms: string[]): boolean {
  return allTermsIn(
    [r.resourceAddress, r.summary, r.reporter ?? ""].join(" "),
    terms,
  );
}

/** Rows shown for records before the list is capped (the group label still shows the full count). */
export const MAX_RECORDS = 8;

import type { AdminEvent } from "./api";
import { EVENT_LABEL } from "./events";

/** Admin scope: who did it, which resources, the detail text, or the event's label. */
export function eventMatches(e: AdminEvent, terms: string[]): boolean {
  return allTermsIn(
    [EVENT_LABEL[e.type], e.actor ?? "", ...e.resourceAddresses, e.detail ?? ""].join(" "),
    terms,
  );
}

export const MAX_EVENTS = 5;

/** Admin "Go to" pages. */
export const GO_TO: { label: string; hash: string }[] = [
  { label: "Overview", hash: "#/admin" },
  { label: "All records", hash: "#/admin/records" },
];

/** Where an event leads: its record, or the Events view at its hour when no record is linked. */
export function eventHash(e: AdminEvent): string {
  return e.recordIds.length > 0
    ? `#/admin/records/${encodeURIComponent(e.recordIds[0])}`
    : `#/admin/events?hour=${encodeURIComponent(e.at)}`;
}
