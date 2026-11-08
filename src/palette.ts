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
