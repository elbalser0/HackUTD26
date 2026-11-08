// @vitest-environment jsdom
// Employee Records page (redesign). Stub adapter; not backend integration.
import { afterEach, beforeEach, expect, test } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { ApiError, fromWireRecordEvent, setAdapter } from "./api";
import type { Adapter, EmergencyRecord, RecordEvent, Rule } from "./api";
import { bucketOf } from "./records";

const rule = (port: string): Rule => ({
  protocol: "tcp",
  portRange: port,
  sourceAddresses: ["0.0.0.0/0"],
  sourceTags: [],
  sourceDropletIds: [],
  sourceLoadBalancerUids: [],
  sourceKubernetesIds: [],
});
const rec = (o: Partial<EmergencyRecord> = {}): EmergencyRecord => ({
  id: "r1",
  environment: "demo",
  resourceAddress: "digitalocean_firewall.db",
  attribute: "inbound_rule",
  changeKind: "added",
  baseline: null,
  observed: rule("5432"),
  summary: "s",
  firstDetectedAt: "2026-11-08T03:30:12.000000Z",
  lastDetectedAt: "2026-11-08T03:45:02.000000Z",
  reporter: null,
  reason: null,
  reportedAt: null,
  intent: "unset",
  intentNote: null,
  resolution: "open",
  resolutionReason: null,
  lastCheckStatus: "current",
  lastCheckAt: new Date().toISOString(),
  evidenceSource: "terraform-refresh-only",
  ...o,
});
const health = { status: "ok", db: "ok", environment: "demo", time: "" };
const four = () => [
  rec({ id: "a", resourceAddress: "digitalocean_firewall.db" }),
  rec({ id: "b", resourceAddress: "digitalocean_firewall.cache" }),
  rec({
    id: "c",
    resourceAddress: "digitalocean_firewall.api",
    reason: "migration window",
    reporter: "Paul",
    reportedAt: "2026-11-08T04:00:00Z",
  }),
  rec({
    id: "d",
    resourceAddress: "digitalocean_firewall.old",
    resolution: "resolved",
    reason: "done",
  }),
];
function stub(o: Partial<Adapter> = {}, list = four()): Adapter {
  const store = new Map(list.map((r) => [r.id, r]));
  return {
    listRecords: async () => ({ records: [...store.values()], health }),
    getRecord: async (id) => store.get(id)!,
    report: async (id, b) => {
      const r = {
        ...store.get(id)!,
        reporter: b.reporter,
        reason: b.reason,
        reportedAt: "2026-11-08T05:00:00Z",
        intent: b.intent ?? store.get(id)!.intent,
      };
      store.set(id, r);
      return r;
    },
    decide: async (id, intent) => ({ ...store.get(id)!, intent }),
    me: async () => ({ signedIn: false, email: null, displayName: null, role: null, authMode: "none" as const }),
    recordEvents: async () => [],
    getApplyRun: async () => {
      throw new Error("unused");
    },
    adminLog: async () => ({ events: [], totalMatching: 0, limitations: [] }),
    adminTimeline: async () => {
      throw new Error("unused");
    },
    ...o,
  };
}
beforeEach(() => (window.location.hash = "#/"));
afterEach(() => {
  cleanup();
  setAdapter(null);
});

const tab = (name: RegExp) => screen.getByRole("button", { name });
const records = () => within(screen.getByRole("navigation", { name: "Records" }));

test("bucketOf: open without a reason needs one; open with a reason is explained; resolved wins", () => {
  expect(bucketOf(rec())).toBe("needs");
  expect(bucketOf(rec({ reason: "x" }))).toBe("explained");
  expect(bucketOf(rec({ resolution: "resolved" }))).toBe("resolved");
  expect(bucketOf(rec({ resolution: "resolved", reason: null }))).toBe(
    "resolved",
  );
});

test("wire mapping: record event", () => {
  const e = fromWireRecordEvent({
    id: "e1",
    environment: "demo",
    record_id: "r1",
    run_id: null,
    kind: "report",
    actor: "Paul",
    actor_assurance: "self-reported",
    data: { reason: "x" },
    created_at: "2026-11-08T04:00:00Z",
  });
  expect(e).toMatchObject({
    id: "e1",
    kind: "report",
    actor: "Paul",
    actorAssurance: "self-reported",
    at: "2026-11-08T04:00:00Z",
  });
});

test("tabs show counts, default to Needs a reason and filter the list", async () => {
  setAdapter(stub());
  render(<App />);
  await screen.findByRole("heading", { name: "Manual changes" });
  expect(tab(/Needs a reason · 2/)).toHaveAttribute("aria-pressed", "true");
  expect(tab(/Explained · 1/)).toBeInTheDocument();
  expect(tab(/Resolved · 1/)).toBeInTheDocument();
  expect(records().getByText("digitalocean_firewall.db")).toBeInTheDocument();
  expect(records().getByText("digitalocean_firewall.cache")).toBeInTheDocument();
  expect(records().queryByText("digitalocean_firewall.api")).toBeNull();
  fireEvent.click(tab(/Explained/));
  expect(records().getByText("digitalocean_firewall.api")).toBeInTheDocument();
  expect(records().queryByText("digitalocean_firewall.db")).toBeNull();
  fireEvent.click(tab(/Resolved/));
  expect(records().getByText("digitalocean_firewall.old")).toBeInTheDocument();
});

test("the first record of the tab is selected and its change is shown with the scanner caveat", async () => {
  setAdapter(stub());
  render(<App />);
  const panel = await screen.findByRole("region", {
    name: "digitalocean_firewall.db",
  });
  expect(within(panel).getByText(/tcp 5432 from 0\.0\.0\.0\/0/)).toBeInTheDocument();
  expect(
    within(panel).getByText(/when the scanner noticed, not when the change was made/i),
  ).toBeInTheDocument();
});

test("selecting a row opens that record and puts its id in the URL", async () => {
  setAdapter(stub());
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  fireEvent.click(records().getByText("digitalocean_firewall.cache"));
  expect(
    await screen.findByRole("region", { name: "digitalocean_firewall.cache" }),
  ).toBeInTheDocument();
  expect(window.location.hash).toBe("#/records/b");
});

test("a deep link opens its record on the matching tab", async () => {
  window.location.hash = "#/records/c";
  setAdapter(stub());
  render(<App />);
  expect(
    await screen.findByRole("region", { name: "digitalocean_firewall.api" }),
  ).toBeInTheDocument();
  expect(tab(/Explained/)).toHaveAttribute("aria-pressed", "true");
});

test("the report form has no name field; saving sends the reason and intent, then moves the record to Explained", async () => {
  let sent: unknown;
  setAdapter(
    stub({
      report: async (id, b) => {
        sent = b;
        return rec({ id, reason: b.reason, reporter: null, intent: "keep" });
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  expect(screen.queryByLabelText(/your name/i)).toBeNull();
  fireEvent.change(screen.getByLabelText("What did you change and why?"), {
    target: { value: "one-off migration" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Keep" }));
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  await waitFor(() => expect(sent).toBeDefined());
  expect(sent).toEqual({
    reporter: null,
    reason: "one-off migration",
    intent: "keep",
  });
  await waitFor(() =>
    expect(tab(/Explained · 2/)).toHaveAttribute("aria-pressed", "true"),
  );
  expect(tab(/Needs a reason · 1/)).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "digitalocean_firewall.db" }),
  ).toBeInTheDocument();
});

test("Undecided is sent as the 'unsure' intent; an unpicked intent is not sent", async () => {
  const sent: unknown[] = [];
  setAdapter(
    stub({
      report: async (id, b) => {
        sent.push(b);
        return rec({ id, reason: b.reason });
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  fireEvent.change(screen.getByLabelText("What did you change and why?"), {
    target: { value: "x" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Undecided" }));
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toMatchObject({ intent: "unsure" });
  cleanup();
  window.location.hash = "#/";
  setAdapter(
    stub({
      report: async (id, b) => {
        sent.push(b);
        return rec({ id, reason: b.reason });
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  fireEvent.change(screen.getByLabelText("What did you change and why?"), {
    target: { value: "y" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  await waitFor(() => expect(sent).toHaveLength(2));
  expect(sent[1]).not.toHaveProperty("intent");
});

test("an empty reason is refused before any request", async () => {
  let called = false;
  setAdapter(
    stub({
      report: async () => {
        called = true;
        return rec();
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /enter what you changed and why/i,
  );
  expect(called).toBe(false);
});

test("a failed save says not saved and keeps the typed text", async () => {
  setAdapter(
    stub({
      report: async () => {
        throw new ApiError("Backend unavailable", 503, "storage_unavailable");
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  const box = screen.getByLabelText("What did you change and why?");
  fireEvent.change(box, { target: { value: "keep me" } });
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/not saved/i);
  expect(box).toHaveValue("keep me");
  expect(tab(/Needs a reason · 2/)).toHaveAttribute("aria-pressed", "true");
});

test("a 401 on save tells the user to sign in again", async () => {
  setAdapter(
    stub({
      report: async () => {
        throw new ApiError("no", 401, "sign_in_required");
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  fireEvent.change(screen.getByLabelText("What did you change and why?"), {
    target: { value: "x" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/sign in/i);
});

test("a resolved record shows no form", async () => {
  window.location.hash = "#/records/d";
  setAdapter(stub());
  render(<App />);
  const panel = await screen.findByRole("region", {
    name: "digitalocean_firewall.old",
  });
  expect(within(panel).queryByRole("button", { name: "Save report" })).toBeNull();
  expect(
    within(panel).getByText(/reports and intent changes are closed/i),
  ).toBeInTheDocument();
});

test("History is collapsed and loads the record's events when opened", async () => {
  let calls = 0;
  const ev: RecordEvent = {
    id: "e1",
    kind: "report",
    actor: "Paul",
    actorAssurance: "self-reported",
    at: "2026-11-08T04:00:00Z",
    data: {},
  };
  setAdapter(
    stub({
      recordEvents: async () => {
        calls++;
        return [ev];
      },
    }),
  );
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.db" });
  expect(calls).toBe(0);
  fireEvent.click(screen.getByRole("button", { name: /History/ }));
  expect(await screen.findByText(/Paul/)).toBeInTheDocument();
  expect(screen.getByText(/self-reported/)).toBeInTheDocument();
  expect(calls).toBe(1);
});

test("keeping a change shows the manual Terraform suggestion, and says nothing was patched", async () => {
  window.location.hash = "#/records/c";
  setAdapter(stub({}, [rec({ id: "c", reason: "r", intent: "keep" })]));
  render(<App />);
  expect(await screen.findByText(/Nothing is patched automatically/)).toBeInTheDocument();
});

test("backend failure is an error with retry, not an empty list", async () => {
  setAdapter(
    stub({
      listRecords: async () => {
        throw new ApiError("Backend unavailable", 503);
      },
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
  expect(screen.queryByText(/no records/i)).toBeNull();
});

test("an empty tab does not claim nothing changed", async () => {
  setAdapter(stub({}, []));
  render(<App />);
  expect(await screen.findByText(/not proof nothing changed/i)).toBeInTheDocument();
});

test("the top bar has the Argus mark and no sidebar for employees", async () => {
  setAdapter(stub());
  render(<App />);
  await screen.findByRole("heading", { name: "Manual changes" });
  expect(screen.getByRole("link", { name: "Argus home" })).toBeInTheDocument();
  expect(document.querySelector("aside")).toBeNull();
});
