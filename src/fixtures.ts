/**
 * DEVELOPMENT FIXTURE ADAPTER — NOT REAL DATA, NOT BACKEND EVIDENCE.
 * Enabled only with ?fixture or VITE_API_MODE=fixture.
 * Scenarios: ?fixture=empty | error | stale | failed
 * Fake names; in-memory; resets on reload.
 */
import type {
  Adapter,
  ApplyRun,
  EmergencyRecord,
  Intent,
  RecordList,
  Rule,
} from "./api";
import { ApiError } from "./api";

const scenario = () =>
  new URLSearchParams(window.location.search).get("fixture") ?? "";
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const rule = (port: string, src = ["0.0.0.0/0", "::/0"]): Rule => ({
  protocol: "tcp",
  portRange: port,
  sourceAddresses: src,
  sourceTags: [],
  sourceDropletIds: [],
  sourceLoadBalancerUids: [],
  sourceKubernetesIds: [],
});
const base = {
  environment: "demo-authored",
  resourceAddress: "digitalocean_firewall.web",
  attribute: "inbound_rule",
  evidenceSource: "authored-fixture",
  resolution: "open" as const,
  resolutionReason: null,
  intentNote: null,
  lastCheckStatus: "current" as const,
};

const records: EmergencyRecord[] = [
  {
    ...base,
    id: "rec_demo_1",
    changeKind: "modified",
    baseline: rule("8080"),
    observed: rule("8443"),
    summary: "inbound tcp port 8080 changed live to port 8443",
    firstDetectedAt: ago(26 * 60),
    lastDetectedAt: ago(2),
    reporter: "Paul (demo)",
    reason: "payment webhook blocked, opened 8443",
    reportedAt: ago(25 * 60),
    intent: "keep",
    lastCheckAt: ago(2),
  },
  {
    ...base,
    id: "rec_demo_2",
    changeKind: "added",
    baseline: null,
    observed: rule("9100", ["10.0.0.0/8"]),
    summary:
      "inbound tcp port 9100 from 10.0.0.0/8 exists live, not in Terraform",
    firstDetectedAt: ago(90),
    lastDetectedAt: ago(2),
    reporter: null,
    reason: null,
    reportedAt: null,
    intent: "unset",
    lastCheckAt: ago(2),
  },
];

const clone = <T>(x: T): T => structuredClone(x);
const find = (id: string) => {
  const r = records.find((x) => x.id === id);
  if (!r) throw new ApiError(`record ${id} not found`, 404, "not_found");
  return r;
};
const gate = async () => {
  await new Promise((r) => setTimeout(r, 250));
  if (scenario() === "error") throw new ApiError("Backend unavailable", 0);
};

export const fixtureAdapter: Adapter = {
  async listRecords(): Promise<RecordList> {
    await gate();
    const s = scenario();
    const recs = s === "empty" ? [] : clone(records);
    if (s === "stale") recs.forEach((r) => (r.lastCheckStatus = "stale"));
    if (s === "failed") recs.forEach((r) => (r.lastCheckStatus = "failed"));
    return {
      records: recs,
      health: { status: "ok", db: "ok", environment: "demo", time: ago(0) },
    };
  },
  async getRecord(id) {
    await gate();
    return clone(find(id));
  },
  async report(id, b) {
    await gate();
    const r = find(id);
    r.reporter = b.reporter;
    r.reason = b.reason;
    r.reportedAt = new Date().toISOString();
    if (b.intent) r.intent = b.intent;
    return clone(r);
  },
  async decide(id, intent: Intent) {
    await gate();
    const r = find(id);
    r.intent = intent; // intent only — resolution untouched
    return clone(r);
  },
  async getApplyRun(id): Promise<ApplyRun> {
    await gate();
    return {
      id,
      environment: "demo-authored",
      generatedAt: ago(1),
      planFingerprint: id === "run_noplan" ? null : "sha256:fixture",
      proposedChanges: [
        {
          resourceAddress: "digitalocean_firewall.web",
          actions: ["update"],
          summary: "update inbound_rule: -tcp 8443, +tcp 8080",
        },
      ],
      warnings: records.map((r) => ({
        recordId: r.id,
        resourceAddress: r.resourceAddress,
        message: `This apply will undo: ${r.summary}.`,
        reason: r.reason,
        reporter: r.reporter,
        intent: r.intent,
        firstDetectedAt: r.firstDetectedAt,
      })),
      checkStatus: id === "run_failed" ? "failed" : "current",
      coverageNote:
        "Checked digitalocean_firewall inbound rules only. Other attributes, other resource types and OS-level changes are not covered.",
      ackOutcome: "pending",
      ackNote: null,
      completedAt: null,
    };
  },
};
