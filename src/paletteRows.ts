import type { EmergencyRecord } from "./api";
import { bucketOf } from "./records";

const INTENT_LABEL: Record<string, string> = {
  keep: "Keep",
  revert: "Revert",
  unsure: "Undecided",
};

export function tagFor(r: EmergencyRecord): { label: string; tone: string } {
  const b = bucketOf(r);
  if (b === "needs") return { label: "Needs a reason", tone: "amber" };
  if (b === "resolved") return { label: "Resolved", tone: "green" };
  return { label: INTENT_LABEL[r.intent] ?? "Explained", tone: "blue" };
}

export function metaFor(r: EmergencyRecord, withWho = true): string {
  const x = r.observed ?? r.baseline;
  const what = `${x?.protocol ?? r.attribute} ${x?.portRange ?? ""} ${r.changeKind}`
    .replace(/\s+/g, " ")
    .trim();
  const b = bucketOf(r);
  const who =
    b === "needs" ? "needs a reason" : b === "resolved" ? "resolved" : (r.reporter ?? "unknown");
  return withWho ? `${what} · ${who}` : what;
}

