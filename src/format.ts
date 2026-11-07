import type { CheckStatus, EmergencyRecord, Rule } from "./api";

/** "Nov 8, 03:30 UTC" — backend timestamps are UTC. */
export function formatDetected(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown time";
  const day = d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  return `${day}, ${d.toISOString().slice(11, 16)} UTC`;
}

export function age(iso: string, now = Date.now()): string {
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (Number.isNaN(min)) return "unknown age";
  if (min < 1) return "under a minute";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h} h`;
  return `${Math.floor(h / 24)} days`;
}

/** "tcp 8443 from 0.0.0.0/0, ::/0" */
export function formatRule(r: Rule | null, empty: string): string {
  if (!r) return empty;
  const src = [
    ...r.sourceAddresses,
    ...r.sourceTags.map((t) => `tag:${t}`),
    ...r.sourceDropletIds.map((d) => `droplet:${d}`),
    ...r.sourceLoadBalancerUids.map((d) => `lb:${d}`),
    ...r.sourceKubernetesIds.map((d) => `k8s:${d}`),
  ];
  return `${r.protocol ?? "?"} ${r.portRange ?? "?"} from ${src.length ? src.join(", ") : "?"}`;
}

export const baselineText = (r: EmergencyRecord) =>
  formatRule(r.baseline, "absent from Terraform");
export const observedText = (r: EmergencyRecord) =>
  formatRule(r.observed, "removed live");

/** Demo/fixture data must be visibly tagged. */
export function demoTag(env: string, evidence?: string): string | null {
  const parts: string[] = [];
  if (env !== "demo") parts.push(env);
  if (evidence && evidence !== "terraform-refresh-only") parts.push(evidence);
  return parts.length ? `DEMO DATA · ${parts.join(" · ")}` : null;
}

/** Narrow suggestion only; never patches anything. */
export function terraformSuggestion(r: EmergencyRecord): string {
  return `In the Terraform for ${r.resourceAddress}, edit ${r.attribute} by hand to match the live value (${observedText(r)}; Terraform currently has: ${baselineText(r)}), then review the plan. Nothing is patched automatically.`;
}

export const CHECK_LABEL: Record<CheckStatus, string> = {
  current: "check current",
  stale: "check STALE",
  failed: "check FAILED — treat as unknown",
  unsupported: "check UNSUPPORTED — evidence not interpretable",
};
