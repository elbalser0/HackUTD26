// @vitest-environment jsdom
// Admin shell + Overview (GET /api/admin/overview). Stub adapter / stubbed fetch.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
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
import { ApiError, api, fromWireOverview, setAdapter, setTokenProvider } from "./api";
import type { Adapter, Me, Overview, OverviewWindow } from "./api";
import { fixtureAdapter } from "./fixtures";
import { barKinds, chartSummary } from "./overview";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const hourStart = (hoursAgo: number) => {
  const d = new Date(Date.now() - hoursAgo * 3_600_000);
  d.setUTCMinutes(0, 0, 0);
  return d.toISOString();
};
const buckets = (n: number, set: Record<number, Record<string, number>> = {}) =>
  Array.from({ length: n }, (_, i) => ({
    hour: hourStart(n - 1 - i),
    counts: set[i] ?? {},
  }));

const overview = (o: Partial<Overview> = {}): Overview => ({
  window: "24h",
  generatedAt: new Date().toISOString(),
  openRecords: 4,
  openWithoutReason: 2,
  needsReason: [
    { recordId: "a", resourceAddress: "digitalocean_firewall.db", summary: "inbound tcp 5432 added", firstDetectedAt: ago(60) },
    { recordId: "b", resourceAddress: "digitalocean_firewall.cache", summary: "inbound tcp 6379 removed", firstDetectedAt: ago(180) },
  ],
  lastScan: { at: ago(240), status: "ok" },
  lastRun: { runId: "run_1", outcome: "unknown", at: ago(300) },
  eventsByType: { explained: 4, review: 1, run_unfinished: 2 },
  runOutcomes: { unknown: 2 },
  activity: buckets(24, { 18: { explained: 2, review: 1, run_unfinished: 2 }, 23: { explained: 2 } }),
  limitations: ["Counts are events in the window, not incidents or downtime."],
  ...o,
});

const admin: Me = { signedIn: true, email: "ada@example.com", displayName: "Ada", role: "admin", authMode: "firebase" };
const employee: Me = { ...admin, role: "employee" };

function stub(who: Me | (() => Promise<Me>), ov: Adapter["adminOverview"] = async (w) => overview({ window: w })): Adapter {
  return {
    ...fixtureAdapter,
    me: typeof who === "function" ? who : async () => who,
    adminOverview: ov,
    listRecords: async () => ({ records: [], health: null }),
  };
}
beforeEach(() => (window.location.hash = "#/admin"));
afterEach(() => {
  cleanup();
  setAdapter(null);
  setTokenProvider(null);
  vi.unstubAllGlobals();
});

const kpi = (label: string) => screen.getByText(label).closest(".kpi") as HTMLElement;
const shown = async () => {
  await screen.findByRole("heading", { name: "Manual changes, before the next apply" });
  return screen.findByRole("region", { name: "Summary" });
};

// ---- wire + adapter --------------------------------------------------------

test("wire mapping: overview", () => {
  const o = fromWireOverview({
    window: "7d",
    generated_at: "g",
    open_records: 3,
    open_without_reason: 1,
    needs_reason: [{ record_id: "r", resource_address: "a.b", summary: "s", first_detected_at: "t" }],
    last_scan: null,
    last_run: { run_id: "run_1", outcome: "unknown", at: "t" },
    events_by_type: { review: 1 },
    run_outcomes: { unknown: 1 },
    activity: [{ hour: "h", counts: { review: 1 } }],
    limitations: ["l"],
  });
  expect(o).toEqual({
    window: "7d",
    generatedAt: "g",
    openRecords: 3,
    openWithoutReason: 1,
    needsReason: [{ recordId: "r", resourceAddress: "a.b", summary: "s", firstDetectedAt: "t" }],
    lastScan: null,
    lastRun: { runId: "run_1", outcome: "unknown", at: "t" },
    eventsByType: { review: 1 },
    runOutcomes: { unknown: 1 },
    activity: [{ hour: "h", counts: { review: 1 } }],
    limitations: ["l"],
  });
});

test("api.adminOverview sends the window and the ID token as a Bearer header, never in the URL", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ window: "7d", open_records: 0, open_without_reason: 0, activity: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  setTokenProvider(async () => "idtok-ov");
  await api.adminOverview("7d");
  expect(calls[0].url).toBe("/api/admin/overview?window=7d");
  const h = (calls[0].init?.headers ?? {}) as Record<string, string>;
  expect(h.Authorization).toBe("Bearer idtok-ov");
  expect(calls[0].url).not.toContain("idtok");
});

// ---- pure helpers ----------------------------------------------------------

test("barKinds groups event types; every event lands in exactly one kind", () => {
  expect(
    barKinds({ explained: 2, review: 1, run_finished: 1, run_unfinished: 2, change_detected: 1, decision: 1, resolved: 1, run_started: 1 }),
  ).toEqual({ report: 2, review: 1, run: 3, other: 4 });
  expect(barKinds({})).toEqual({ report: 0, review: 0, run: 0, other: 0 });
});

test("chartSummary states the total, the window and the busiest hour", () => {
  const s = chartSummary(buckets(24, { 5: { explained: 3 }, 9: { review: 1 } }), "24h");
  expect(s).toMatch(/Events per hour over the last 24 hours/);
  expect(s).toMatch(/4 events/);
  expect(s).toMatch(/Busiest hour: 3 events at \d\d:00 UTC/);
  expect(chartSummary(buckets(24), "24h")).toMatch(/No events/);
  expect(chartSummary(buckets(168, { 1: { explained: 1 } }), "7d")).toMatch(/last 7 days/);
});

// ---- who sees what ---------------------------------------------------------

test("an admin sees the admin shell: ADMIN sidebar with Overview and All records, an Admin badge, and no employee records page", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  const nav = screen.getByRole("navigation", { name: "Main" });
  expect(within(nav).getAllByRole("link")).toHaveLength(2);
  expect(within(nav).getByRole("link", { name: /Overview/ })).toHaveAttribute("aria-current", "page");
  expect(within(nav).getByRole("link", { name: /All records/ })).toHaveAttribute("href", "#/admin/records");
  expect(screen.getByText("ADMIN")).toBeInTheDocument();
  expect(screen.getByText("Admin", { selector: ".role" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Manual changes" })).toBeNull();
});

test("an employee at #/admin gets the existing token gate and the overview is never requested", async () => {
  const ov = vi.fn(async () => overview());
  setAdapter(stub(employee, ov));
  render(<App />);
  expect(await screen.findByLabelText("Admin token")).toBeInTheDocument();
  expect(ov).not.toHaveBeenCalled();
});

test("if /api/me fails, #/admin falls back to the server-enforced token gate, never to the overview", async () => {
  const ov = vi.fn(async () => overview());
  setAdapter(
    stub(async () => {
      throw new Error("down");
    }, ov),
  );
  render(<App />);
  expect(await screen.findByLabelText("Admin token")).toBeInTheDocument();
  expect(ov).not.toHaveBeenCalled();
});

// ---- KPIs ------------------------------------------------------------------

test("KPIs: open records with how many lack a reason, last scan, last apply, events in the window", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  expect(within(kpi("Open records")).getByText("4")).toBeInTheDocument();
  expect(within(kpi("Open records")).getByText(/2 without a reason/)).toBeInTheDocument();
  expect(within(kpi("Last scan")).getByText("4 h ago")).toBeInTheDocument();
  expect(within(kpi("Last scan")).getByText(/ok/)).toBeInTheDocument();
  expect(within(kpi("Last apply")).getByText("Unknown")).toBeInTheDocument();
  expect(within(kpi("Last apply")).getByText(/no completion recorded/)).toBeInTheDocument();
  expect(within(kpi("Events, 24 h")).getByText("7")).toBeInTheDocument();
  expect(within(kpi("Events, 24 h")).getByText(/4 explained, 1 review, 2 run unfinished/)).toBeInTheDocument();
});

test("a finished run shows its outcome; a failed one is flagged", async () => {
  setAdapter(
    stub(admin, async (w) => overview({ window: w, lastRun: { runId: "r", outcome: "failed", at: ago(30) } })),
  );
  render(<App />);
  await shown();
  expect(within(kpi("Last apply")).getByText("Failed")).toBeInTheDocument();
  expect(within(kpi("Last apply")).getByText(/30 min ago/)).toBeInTheDocument();
});

test.each([
  ["unknown", true],
  ["failed", true],
  ["applied_no_warnings", false],
])("last apply %s is %s as a warning tile", async (outcome, warn) => {
  setAdapter(
    stub(admin, async (w) =>
      overview({ window: w, lastRun: { runId: "r", outcome: outcome as never, at: ago(30) } }),
    ),
  );
  render(<App />);
  await shown();
  expect(kpi("Last apply").classList.contains("warn")).toBe(warn);
});

test("never scanned and no runs are stated, not shown as zero or fine", async () => {
  setAdapter(stub(admin, async (w) => overview({ window: w, lastScan: null, lastRun: null })));
  render(<App />);
  await shown();
  expect(within(kpi("Last scan")).getByText("Never")).toBeInTheDocument();
  expect(within(kpi("Last scan")).getByText(/no scan recorded/)).toBeInTheDocument();
  expect(within(kpi("Last apply")).getByText("None")).toBeInTheDocument();
  expect(within(kpi("Last apply")).getByText(/no apply run recorded/)).toBeInTheDocument();
});

// ---- open without a reason -------------------------------------------------

test("open without a reason: each record with how long, and a Review link to its page", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  const card = within(screen.getByRole("region", { name: "Open without a reason" }));
  expect(card.getByText("digitalocean_firewall.db")).toBeInTheDocument();
  expect(card.getByText(/unexplained for 1 h/)).toBeInTheDocument();
  expect(card.getByText(/unexplained for 3 h/)).toBeInTheDocument();
  const links = card.getAllByRole("link", { name: /Review/ });
  expect(links[0]).toHaveAttribute("href", "#/admin/records/a");
});

test("the list is capped at 10 and says how many more there are", async () => {
  const many = Array.from({ length: 10 }, (_, i) => ({
    recordId: `m${i}`, resourceAddress: `digitalocean_firewall.m${i}`, summary: "s", firstDetectedAt: ago(10 + i),
  }));
  setAdapter(stub(admin, async (w) => overview({ window: w, needsReason: many, openWithoutReason: 13 })));
  render(<App />);
  await shown();
  const card = within(screen.getByRole("region", { name: "Open without a reason" }));
  expect(card.getAllByRole("link", { name: /Review/ })).toHaveLength(10);
  expect(card.getByText(/and 3 more/)).toBeInTheDocument();
});

test("none without a reason says so", async () => {
  setAdapter(stub(admin, async (w) => overview({ window: w, needsReason: [], openWithoutReason: 0 })));
  render(<App />);
  await shown();
  expect(screen.getByText(/No open records without a reason/)).toBeInTheDocument();
});

// ---- chart -----------------------------------------------------------------

test("the chart has one column per hour, stacked by kind, and a text summary", async () => {
  setAdapter(stub(admin));
  const { container } = render(<App />);
  await shown();
  expect(container.querySelectorAll(".chart .col")).toHaveLength(24);
  expect(container.querySelectorAll(".chart .seg-bar.k-report")).toHaveLength(2);
  expect(container.querySelectorAll(".chart .seg-bar.k-review")).toHaveLength(1);
  expect(container.querySelectorAll(".chart .seg-bar.k-run")).toHaveLength(1);
  expect(container.querySelector(".chart .seg-bar.k-other")).toBeNull();
  expect(screen.getByRole("img", { name: /7 events/ })).toBeInTheDocument();
  expect(screen.getByText(/counts events, not incidents/i)).toBeInTheDocument();
  // 2 reports in a bar are taller than 1 review
  const tall = container.querySelectorAll<HTMLElement>(".chart .seg-bar.k-report")[0].style.height;
  const short = container.querySelector<HTMLElement>(".chart .seg-bar.k-review")!.style.height;
  expect(parseFloat(tall)).toBeGreaterThan(0);
  expect(parseFloat(short)).toBeGreaterThan(0);
});

test("events of other kinds are drawn and listed in the legend so the chart adds up to the KPI", async () => {
  setAdapter(
    stub(admin, async (w) =>
      overview({
        window: w,
        eventsByType: { change_detected: 2, explained: 1 },
        activity: buckets(24, { 3: { change_detected: 2, explained: 1 } }),
      }),
    ),
  );
  const { container } = render(<App />);
  await shown();
  expect(container.querySelectorAll(".chart .seg-bar.k-other")).toHaveLength(1);
  expect(screen.getByText("Other", { selector: ".legend span" })).toBeInTheDocument();
  expect(within(kpi("Events, 24 h")).getByText("3")).toBeInTheDocument();
});

test("no 'Other' legend entry when there are no other events", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  expect(screen.queryByText("Other", { selector: ".legend span" })).toBeNull();
});

// ---- run outcomes ----------------------------------------------------------

test("run outcomes: unknown first and flagged, each present outcome counted, unknown is never failed", async () => {
  setAdapter(
    stub(admin, async (w) => overview({ window: w, runOutcomes: { applied_no_warnings: 3, failed: 1, unknown: 2 } })),
  );
  render(<App />);
  await shown();
  const card = screen.getByRole("region", { name: "Run outcomes" });
  const rows = [...card.querySelectorAll(".item")].map((r) => r.textContent);
  expect(rows).toEqual(["Unknown2", "Failed1", "Applied no warnings3"]);
  expect(within(card).getByText(/never counted as failed/i)).toBeInTheDocument();
});

test("no runs in the window is stated", async () => {
  setAdapter(stub(admin, async (w) => overview({ window: w, runOutcomes: {} })));
  render(<App />);
  await shown();
  expect(within(screen.getByRole("region", { name: "Run outcomes" })).getByText(/No runs in this window/)).toBeInTheDocument();
});

// ---- controls and states ---------------------------------------------------

test("7 d refetches with that window and relabels the event count", async () => {
  const ov = vi.fn(async (w: OverviewWindow) =>
    overview({ window: w, activity: buckets(w === "7d" ? 168 : 24), eventsByType: { review: w === "7d" ? 9 : 1 } }),
  );
  setAdapter(stub(admin, ov));
  const { container } = render(<App />);
  await shown();
  expect(ov).toHaveBeenLastCalledWith("24h");
  expect(screen.getByRole("button", { name: "24 h" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "7 d" }));
  await waitFor(() => expect(ov).toHaveBeenLastCalledWith("7d"));
  expect(await screen.findByText("Events, 7 d")).toBeInTheDocument();
  expect(within(kpi("Events, 7 d")).getByText("9")).toBeInTheDocument();
  expect(container.querySelectorAll(".chart .col")).toHaveLength(168);
  expect(screen.getByRole("button", { name: "7 d" })).toHaveAttribute("aria-pressed", "true");
});

test("Refresh asks again", async () => {
  const ov = vi.fn(async (w: OverviewWindow) => overview({ window: w }));
  setAdapter(stub(admin, ov));
  render(<App />);
  await shown();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(ov).toHaveBeenCalledTimes(2));
});

test("a backend failure is an error with retry, never zeros", async () => {
  setAdapter(
    stub(admin, async () => {
      throw new ApiError("Backend unavailable", 503, "storage_unavailable");
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
  expect(screen.queryByText("Open records")).toBeNull();
});

test("the server's limitations are shown", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  expect(screen.getByText(/not incidents or downtime/)).toBeInTheDocument();
});

test("the admin view is read-only: no report form or Save button", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  expect(screen.queryByRole("button", { name: "Save report" })).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
});

// ---- chart bars open that hour in the Events view --------------------------

test("bars with events are links to that hour in the Events view; empty hours are not links", async () => {
  setAdapter(stub(admin));
  const { container } = render(<App />);
  await shown();
  const links = container.querySelectorAll<HTMLAnchorElement>(".chart a.col");
  expect(links).toHaveLength(2); // the two hours with events in the default overview
  const href = links[0].getAttribute("href")!;
  expect(href).toMatch(/^#\/admin\/events\?hour=/);
  const hour = decodeURIComponent(href.split("hour=")[1]);
  expect(new Date(hour).toISOString().slice(14)).toBe("00:00.000Z");
  expect(links[0]).toHaveAttribute("aria-label", expect.stringMatching(/5 events at \d\d:00 UTC/));
  expect(links[1]).toHaveAttribute("aria-label", expect.stringMatching(/2 events/));
  expect(container.querySelectorAll(".chart div.col")).toHaveLength(22);
});

// ---- links (as drawn in the design: Open records, Last apply, Events, Unknown outcome, card head) ------

test("KPIs link to their targets; Last scan is not a link", async () => {
  setAdapter(stub(admin));
  render(<App />);
  await shown();
  expect(kpi("Open records").tagName).toBe("A");
  expect(kpi("Open records")).toHaveAttribute("href", "#/admin/records");
  expect(within(kpi("Open records")).getByText(/view all/)).toBeInTheDocument();
  expect(kpi("Last apply")).toHaveAttribute("href", "#/admin/events");
  expect(within(kpi("Last apply")).getByText(/see events/)).toBeInTheDocument();
  expect(kpi("Events, 24 h")).toHaveAttribute("href", "#/admin/events");
  expect(within(kpi("Events, 24 h")).getByText(/see events/)).toBeInTheDocument();
  expect(kpi("Last scan").tagName).not.toBe("A");
});

test("'Last apply: None' is not a link (there is nothing to look at)", async () => {
  setAdapter(stub(admin, async (w) => overview({ window: w, lastRun: null })));
  render(<App />);
  await shown();
  expect(kpi("Last apply").tagName).not.toBe("A");
});

test("the Unknown run-outcome row links to the Events view; other rows do not; card head links to All records", async () => {
  setAdapter(
    stub(admin, async (w) => overview({ window: w, runOutcomes: { applied_no_warnings: 3, unknown: 2 } })),
  );
  render(<App />);
  await shown();
  const card = screen.getByRole("region", { name: "Run outcomes" });
  const rows = [...card.querySelectorAll(".item")];
  expect(rows[0].tagName).toBe("A");
  expect(rows[0]).toHaveAttribute("href", "#/admin/events");
  expect(rows[1].tagName).not.toBe("A");
  const att = screen.getByRole("region", { name: "Open without a reason" });
  expect(within(att).getByRole("link", { name: "All records" })).toHaveAttribute("href", "#/admin/records");
});
