/**
 * DEVELOPMENT FIXTURE ADAPTER — NOT REAL DATA, NOT BACKEND EVIDENCE.
 * Enabled only with ?fixture or VITE_API_MODE=fixture.
 * Scenarios: ?fixture=empty | error | stale | failed
 * Fake names; in-memory; resets on reload.
 */
import type {
  AdminEvent,
  AdminFilters,
  AdminLog,
  Timeline,
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
  async adminLog(token, f: AdminFilters): Promise<AdminLog> {
    await gate();
    checkToken(token);
    const events = adminEvents().filter(
      (e) =>
        (!f.engineer || e.actor?.toLowerCase() === f.engineer.toLowerCase()) &&
        (!f.resource || e.resourceAddresses.includes(f.resource)) &&
        (!f.outcome || e.outcome === f.outcome) &&
        (!f.since || e.at >= f.since) &&
        (!f.until || e.at <= f.until),
    );
    return {
      events: events.reverse(),
      totalMatching: events.length,
      limitations: FIXTURE_LIMITATIONS,
    };
  },
  async adminTimeline(token, id): Promise<Timeline> {
    await gate();
    checkToken(token);
    find(id);
    const events = adminEvents().filter((e) => e.recordIds.includes(id));
    return {
      recordId: id,
      events,
      gaps: [
        {
          code: "run_outcome_unknown",
          message:
            "Run run_fixture_2 has no recorded completion; do not assume it succeeded.",
          runId: "run_fixture_2",
        },
      ],
      limitations: FIXTURE_LIMITATIONS,
    };
  },
};

/** Fixture admin token is "demo" (?fixture=admin-unconfigured simulates a server with no token set). */
function checkToken(token: string) {
  if (scenario() === "admin-unconfigured")
    throw new ApiError("Admin access is not configured", 403, "forbidden");
  if (token !== "demo")
    throw new ApiError(
      "Missing or invalid admin credentials",
      401,
      "unauthorized",
    );
}

const FIXTURE_LIMITATIONS = [
  "FIXTURE DATA — not from a backend.",
  "Actors are not verified identities: reporters are self-reported, and a wrapper reviewer is either self-reported or the local OS user (not verified).",
  "Admin access uses one shared token: it shows that an admin read the log, not which admin.",
  "A run with no recorded completion is shown as unknown: it may have been interrupted, crashed, or still be running. Unknown is not the same as failed, and never means success.",
];

function adminEvents(): AdminEvent[] {
  const e = (
    o: Partial<AdminEvent> & Pick<AdminEvent, "at" | "type">,
  ): AdminEvent => ({
    environment: "demo-authored",
    recordIds: ["rec_demo_1"],
    runId: null,
    resourceAddresses: ["digitalocean_firewall.web"],
    actor: null,
    actorAssurance: "system",
    outcome: null,
    planFingerprint: null,
    detail: null,
    ...o,
  });
  return [
    e({
      at: ago(26 * 60),
      type: "change_detected",
      detail: "inbound tcp port 8080 changed live to port 8443",
    }),
    e({
      at: ago(25 * 60),
      type: "explained",
      actor: "Paul (demo)",
      actorAssurance: "self-reported",
      detail: "payment webhook blocked, opened 8443",
    }),
    e({
      at: ago(120),
      type: "review",
      actor: "Dana (demo)",
      actorAssurance: "self-reported",
      runId: "run_fixture_1",
      planFingerprint: "sha256:fixture",
      detail: "decision: revert — webhook fixed upstream",
    }),
    e({
      at: ago(119),
      type: "run_started",
      actor: "Dana (demo)",
      actorAssurance: "self-reported",
      runId: "run_fixture_1",
      planFingerprint: "sha256:fixture",
      detail: "terraform apply started after decision: revert",
    }),
    e({
      at: ago(118),
      type: "run_finished",
      actor: "Dana (demo)",
      actorAssurance: "self-reported",
      runId: "run_fixture_1",
      outcome: "reverted_applied",
      detail: "outcome: reverted_applied",
    }),
    e({
      at: ago(40),
      type: "run_unfinished",
      actor: "alice",
      actorAssurance: "local-os-user (not verified)",
      runId: "run_fixture_2",
      outcome: "unknown",
      detail:
        "No completion recorded; the run may have been interrupted or crashed, or may still be running. Do not assume it succeeded.",
    }),
  ];
}
