// @vitest-environment jsdom
// Admin Record page (read-only): GET /api/records/{id} + GET /api/admin/records/{id}/timeline.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { ApiError, api, fromWireRecord, setAdapter, setTokenProvider } from "./api";
import type { AdminEvent, Adapter, EmergencyRecord, Me, Rule, Timeline } from "./api";
import { fixtureAdapter } from "./fixtures";
import { linkedRun } from "./events";

const rule = (port: string): Rule => ({
  protocol: "tcp",
  portRange: port,
  sourceAddresses: ["0.0.0.0/0", "::/0"],
  sourceTags: [],
  sourceDropletIds: [],
  sourceLoadBalancerUids: [],
  sourceKubernetesIds: [],
});
const rec = (o: Partial<EmergencyRecord> = {}): EmergencyRecord => ({
  id: "c",
  environment: "demo",
  resourceAddress: "digitalocean_firewall.web",
  attribute: "inbound_rule",
  changeKind: "modified",
  baseline: rule("8080"),
  observed: rule("8443"),
  summary: "inbound tcp port 8080 changed live to port 8443",
  firstDetectedAt: "2026-11-08T02:55:00Z",
  lastDetectedAt: "2026-11-08T07:00:00Z",
  reporter: "Paul",
  reason: "payment webhook blocked, opened 8443",
  reportedAt: "2026-11-08T02:55:30Z",
  intent: "keep",
  intentNote: null,
  resolution: "open",
  resolutionReason: null,
  lastCheckStatus: "current",
  lastCheckAt: "2026-11-08T07:00:00Z",
  evidenceSource: "terraform-refresh-only",
  reporterAssurance: "self-reported",
  intentUpdatedAt: "2026-11-08T02:55:40Z",
  lastActivity: { at: "2026-11-08T02:55:40Z", type: "decision" },
  ...o,
});
const ev = (o: Partial<AdminEvent>): AdminEvent => ({
  at: "2026-11-08T02:55:00Z",
  type: "change_detected",
  environment: "demo",
  recordIds: ["c"],
  runId: null,
  resourceAddresses: ["digitalocean_firewall.web"],
  actor: null,
  actorAssurance: "system",
  outcome: null,
  planFingerprint: null,
  detail: null,
  ...o,
});
const timeline = (o: Partial<Timeline> = {}): Timeline => ({
  recordId: "c",
  events: [
    ev({ at: "2026-11-08T02:55:00Z", type: "change_detected", detail: "tcp 8080 changed to 8443" }),
    ev({ at: "2026-11-08T02:55:30Z", type: "explained", actor: "Paul", actorAssurance: "self-reported", detail: "payment webhook blocked, opened 8443" }),
    ev({ at: "2026-11-08T02:55:40Z", type: "decision", actor: "Paul", actorAssurance: "self-reported", detail: "keep" }),
    ev({ at: "2026-11-08T03:10:00Z", type: "run_unfinished", runId: "run_a", outcome: "unknown", detail: "outcome: unknown" }),
    ev({ at: "2026-11-08T07:02:00Z", type: "explained", actor: "dana@example.com", actorAssurance: "google-account (verified sign-in)", detail: "<img src=x onerror=alert(1)>" }),
  ],
  gaps: [{ code: "run_outcome_unknown", message: "Run run_a has no recorded completion; do not assume it succeeded.", runId: "run_a" }],
  limitations: ["Actors are not verified identities."],
  ...o,
});

const admin: Me = { signedIn: true, email: "ada@example.com", displayName: "Ada", role: "admin", authMode: "firebase" };
function stub(o: Partial<Adapter> = {}, who: Me = admin): Adapter {
  return {
    ...fixtureAdapter,
    me: async () => who,
    getRecord: async () => rec(),
    adminRecordTimeline: async () => timeline(),
    listRecords: async () => ({ records: [rec()], health: null }),
    ...o,
  };
}
beforeEach(() => (window.location.hash = "#/admin/records/c"));
afterEach(() => {
  cleanup();
  setAdapter(null);
  setTokenProvider(null);
  vi.unstubAllGlobals();
});

const loaded = async () => {
  const h = await screen.findByRole("heading", { name: "digitalocean_firewall.web" });
  await screen.findByRole("region", { name: "Full history" });
  return h;
};
const kpi = (label: string) => screen.getByText(label).closest(".kpi") as HTMLElement;

// ---- wire / adapter / helpers ---------------------------------------------

test("wire mapping: intent_updated_at", () => {
  const r = fromWireRecord({
    id: "r", environment: "demo", resource_address: "a.b", attribute: "x", change_kind: "added",
    summary: "s", first_detected_at: "t", last_detected_at: "t", resolution: "open",
    last_check_status: "current", evidence_source: "e", intent_updated_at: "2026-11-08T02:55:40Z",
  });
  expect(r.intentUpdatedAt).toBe("2026-11-08T02:55:40Z");
  expect(fromWireRecord({ ...{ id: "r", resolution: "open" } }).intentUpdatedAt).toBeNull();
});

test("api.adminRecordTimeline calls the timeline route with the ID token as a Bearer header, id URL-encoded", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ record_id: "a/b", events: [], gaps: [], limitations: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  setTokenProvider(async () => "idtok-tl");
  await api.adminRecordTimeline("a/b");
  expect(calls[0].url).toBe("/api/admin/records/a%2Fb/timeline");
  const h = (calls[0].init?.headers ?? {}) as Record<string, string>;
  expect(h.Authorization).toBe("Bearer idtok-tl");
});

test("linkedRun: the latest run result among the events, or null", () => {
  const e = [
    ev({ at: "2026-11-08T03:00:00Z", type: "run_finished", runId: "r1", outcome: "failed" }),
    ev({ at: "2026-11-08T05:00:00Z", type: "run_unfinished", runId: "r2", outcome: "unknown" }),
    ev({ at: "2026-11-08T06:00:00Z", type: "explained" }),
    ev({ at: "2026-11-08T04:00:00Z", type: "run_started", runId: "r2" }),
  ];
  expect(linkedRun(e)?.runId).toBe("r2");
  expect(linkedRun([ev({ type: "explained" })])).toBeNull();
  expect(linkedRun([])).toBeNull();
});

// ---- who sees it -----------------------------------------------------------

test("an admin sees the record in the admin shell, read-only", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  expect(
    within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /All records/ }),
  ).toHaveAttribute("aria-current", "page");
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save report" })).toBeNull();
  expect(screen.getByText("Open", { selector: ".tag" })).toBeInTheDocument();
  expect(screen.getByText(/check current/i)).toBeInTheDocument();
});

test("an employee at an admin record URL is sent to the records page and no admin data is requested", async () => {
  const tl = vi.fn(async () => timeline());
  setAdapter(stub({ adminRecordTimeline: tl }, { ...admin, role: "employee" }));
  render(<App />);
  await waitFor(() => expect(window.location.hash).toBe("#/"));
  expect(tl).not.toHaveBeenCalled();
});

// ---- KPIs ------------------------------------------------------------------

test("explained by: a self-reported name is labelled not verified", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  expect(within(kpi("Explained by")).getByText("Paul")).toBeInTheDocument();
  expect(within(kpi("Explained by")).getByText(/self-reported, not verified/)).toBeInTheDocument();
});

test("explained by: a verified sign-in says it shows who submitted, not who made the change", async () => {
  setAdapter(stub({ getRecord: async () => rec({ reporter: "Dana", reporterAssurance: "google-account (verified sign-in)" }) }));
  render(<App />);
  await loaded();
  const k = within(kpi("Explained by"));
  expect(k.getByText("Dana")).toBeInTheDocument();
  expect(k.getByText(/verified sign-in: who submitted it, not who made the change/)).toBeInTheDocument();
});

test("explained by: nobody yet when there is no reason", async () => {
  setAdapter(stub({ getRecord: async () => rec({ reason: null, reporter: null, reporterAssurance: null, intent: "unset", intentUpdatedAt: null }) }));
  render(<App />);
  await loaded();
  expect(within(kpi("Explained by")).getByText("Nobody yet")).toBeInTheDocument();
  expect(within(kpi("Explained by")).getByText(/no reason recorded/)).toBeInTheDocument();
});

test("explained by: an explanation with no name says so, and is not 'Nobody yet'", async () => {
  setAdapter(stub({ getRecord: async () => rec({ reporter: null, reason: "from the CLI", reporterAssurance: "self-reported" }) }));
  render(<App />);
  await loaded();
  expect(within(kpi("Explained by")).getByText("No name given")).toBeInTheDocument();
  expect(within(kpi("Explained by")).queryByText("Nobody yet")).toBeNull();
});

test("intent: an unset intent never claims a time it was set", async () => {
  setAdapter(stub({ getRecord: async () => rec({ intent: "unset", intentUpdatedAt: "2026-11-08T02:55:40Z" }) }));
  render(<App />);
  await loaded();
  expect(within(kpi("Intent")).getByText("Not set")).toBeInTheDocument();
  expect(within(kpi("Intent")).queryByText(/set Nov 8/)).toBeNull();
  expect(within(kpi("Intent")).getByText(/no intent recorded/)).toBeInTheDocument();
});

test("intent: label and when it was set; not set says so", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  expect(within(kpi("Intent")).getByText("Keep")).toBeInTheDocument();
  expect(within(kpi("Intent")).getByText(/set Nov 8, 02:55 UTC/)).toBeInTheDocument();
  cleanup();
  setAdapter(stub({ getRecord: async () => rec({ intent: "unset", intentUpdatedAt: null }) }));
  render(<App />);
  await loaded();
  expect(within(kpi("Intent")).getByText("Not set")).toBeInTheDocument();
  expect(within(kpi("Intent")).getByText(/no intent recorded/)).toBeInTheDocument();
});

test("linked run: an unknown outcome is flagged and never called failed", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const k = kpi("Linked run");
  expect(within(k).getByText("Unknown")).toBeInTheDocument();
  expect(within(k).getByText(/no completion recorded/)).toBeInTheDocument();
  expect(k.classList.contains("warn")).toBe(true);
  expect(within(k).queryByText(/failed/i)).toBeNull();
});

test("linked run: a finished run shows its outcome; none says none", async () => {
  setAdapter(
    stub({
      adminRecordTimeline: async () =>
        timeline({ events: [ev({ at: "2026-11-08T03:10:00Z", type: "run_finished", runId: "run_b", outcome: "applied_no_warnings" })], gaps: [] }),
    }),
  );
  render(<App />);
  await loaded();
  expect(within(kpi("Linked run")).getByText("Applied no warnings")).toBeInTheDocument();
  expect(kpi("Linked run").classList.contains("warn")).toBe(false);
  cleanup();
  setAdapter(stub({ adminRecordTimeline: async () => timeline({ events: [], gaps: [] }) }));
  render(<App />);
  await loaded();
  expect(within(kpi("Linked run")).getByText("None")).toBeInTheDocument();
  expect(within(kpi("Linked run")).getByText(/no apply run linked/)).toBeInTheDocument();
});

// ---- what changed ----------------------------------------------------------

test("what changed: old and new rule, with the scanner caveat", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const card = within(screen.getByRole("region", { name: "What changed" }));
  expect(card.getByText("tcp 8080 from 0.0.0.0/0, ::/0")).toHaveClass("old");
  expect(card.getByText("tcp 8443 from 0.0.0.0/0, ::/0")).toHaveClass("new");
  expect(card.getByText(/Detected Nov 8, 02:55 UTC, when the scanner noticed/)).toBeInTheDocument();
});

test("what changed: an added rule has only the new side; a resolved record says why", async () => {
  setAdapter(
    stub({ getRecord: async () => rec({ changeKind: "added", baseline: null, resolution: "resolved", resolutionReason: "verified_aligned" }) }),
  );
  render(<App />);
  await loaded();
  const card = within(screen.getByRole("region", { name: "What changed" }));
  expect(card.queryByText(/absent from Terraform/)).toBeNull();
  expect(card.getByText("tcp 8443 from 0.0.0.0/0, ::/0")).toHaveClass("new");
  expect(screen.getByText("Resolved", { selector: ".tag" })).toBeInTheDocument();
  expect(screen.getByText(/verified_aligned/)).toBeInTheDocument();
});

// ---- history and gaps ------------------------------------------------------

test("full history: newest first, with who, assurance and detail as plain text", async () => {
  setAdapter(stub());
  const { container } = render(<App />);
  await loaded();
  const titles = [...container.querySelectorAll(".tl-item .t")].map((t) => t.textContent);
  expect(titles).toEqual(["Report", "Apply unfinished", "Decision", "Report", "Detected by scan"]);
  const first = within(container.querySelector(".tl-item") as HTMLElement);
  expect(first.getByText(/dana@example.com/)).toBeInTheDocument();
  expect(first.getByText("verified sign-in")).toBeInTheDocument();
  expect(first.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
  expect(container.querySelector("main img")).toBeNull();
  const decision = within(container.querySelectorAll<HTMLElement>(".tl-item")[2]);
  expect(decision.getByText("self-reported")).toBeInTheDocument();
});

test("history: an unfinished run is amber, says no completion was recorded, and system has no person", async () => {
  setAdapter(stub());
  const { container } = render(<App />);
  await loaded();
  const run = container.querySelectorAll<HTMLElement>(".tl-item")[1];
  expect(run.querySelector(".dot")).toHaveClass("amber");
  expect(within(run).getByText(/Outcome unknown, no completion recorded/)).toBeInTheDocument();
  expect(within(run).getByText(/system/)).toBeInTheDocument();
  expect(within(run).queryByText(/failed/i)).toBeNull();
});

test("history: a reviewed plan fingerprint is shown", async () => {
  setAdapter(
    stub({
      adminRecordTimeline: async () =>
        timeline({ events: [ev({ type: "review", actor: "Paul", actorAssurance: "self-reported", planFingerprint: "sha256:abc123" })], gaps: [] }),
    }),
  );
  render(<App />);
  await loaded();
  expect(screen.getByText(/reviewed plan: sha256:abc123/)).toBeInTheDocument();
});

test("gaps: the server's gaps with titles, plus the standing note that who made the change is never verified", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const g = within(screen.getByRole("region", { name: "Gaps" }));
  expect(g.getByText("Run outcome unknown")).toBeInTheDocument();
  expect(g.getByText(/Run run_a has no recorded completion/)).toBeInTheDocument();
  expect(g.getByText("Not verified who made the change")).toBeInTheDocument();
  expect(g.getByText(/Reports show who submitted them, never who changed the console/)).toBeInTheDocument();
});

test("gaps: no_reason_recorded and no_decision_recorded get plain titles", async () => {
  setAdapter(
    stub({
      adminRecordTimeline: async () =>
        timeline({
          gaps: [
            { code: "no_reason_recorded", message: "No reason was recorded for this change.", runId: null },
            { code: "no_decision_recorded", message: "No keep/revert/defer decision was recorded for this change.", runId: null },
            { code: "no_run_linked", message: "No wrapper run has reviewed this change.", runId: null },
          ],
        }),
    }),
  );
  render(<App />);
  await loaded();
  const g = within(screen.getByRole("region", { name: "Gaps" }));
  expect(g.getByText("No reason recorded")).toBeInTheDocument();
  expect(g.getByText("No decision recorded")).toBeInTheDocument();
  expect(g.getByText("No run linked")).toBeInTheDocument();
});

test("the limitations panel is not shown", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  expect(screen.queryByText(/Actors are not verified identities/)).toBeNull();
});

// ---- navigation and failure ------------------------------------------------

test("the crumb links back to All records", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const crumbs = document.querySelector(".crumbs") as HTMLElement;
  expect(within(crumbs).getByRole("link", { name: "All records" })).toHaveAttribute("href", "#/admin/records");
});

test("an unknown record is Not found, not a blank page", async () => {
  setAdapter(
    stub({
      getRecord: async () => {
        throw new ApiError("record x not found", 404, "not_found");
      },
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
});

test("if only the history fails, the record still shows and the history says it could not load", async () => {
  setAdapter(
    stub({
      adminRecordTimeline: async () => {
        throw new ApiError("Backend unavailable", 503, "storage_unavailable");
      },
    }),
  );
  render(<App />);
  await screen.findByRole("heading", { name: "digitalocean_firewall.web" });
  expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
  expect(screen.getByRole("region", { name: "What changed" })).toBeInTheDocument();
  expect(screen.queryByText("Run outcome unknown")).toBeNull();
  expect(screen.getByText("Not verified who made the change")).toBeInTheDocument();
});

test("a different record id loads that record", async () => {
  const getRecord = vi.fn(async (id: string) => rec({ id, resourceAddress: `digitalocean_firewall.${id}` }));
  setAdapter(stub({ getRecord }));
  window.location.hash = "#/admin/records/zzz";
  render(<App />);
  await screen.findByRole("heading", { name: "digitalocean_firewall.zzz" });
  expect(getRecord).toHaveBeenCalledWith("zzz");
});
