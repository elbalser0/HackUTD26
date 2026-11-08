import type { EmergencyRecord } from "./api";

/** The three employee tabs. Resolved wins; an open record is explained once it has a reason. */
export type Bucket = "needs" | "explained" | "resolved";

export const BUCKETS: { id: Bucket; label: string }[] = [
  { id: "needs", label: "Needs a reason" },
  { id: "explained", label: "Explained" },
  { id: "resolved", label: "Resolved" },
];

export function bucketOf(r: EmergencyRecord): Bucket {
  if (r.resolution === "resolved") return "resolved";
  return r.reason === null ? "needs" : "explained";
}
