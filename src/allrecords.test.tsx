// @vitest-environment jsdom
// Admin "All records": Records view (client-side filters) and Events view (server-side filters).
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
import { ApiError, setAdapter } from "./api";
import type { AdminEvent, AdminFilters, AdminLog, Adapter, EmergencyRecord, Me, Rule } from "./api";
import { fixtureAdapter } from "./fixtures";
import { explainedByOptions, filterRecords, hourRange, rangeSince, UNNAMED } from "./allRecords";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const rule = (port: string): Rule => ({
  protocol: "tcp",
  portRange: port,
  sourceAddresses: ["0.0.0.0/0"],
  sourceTags: [],
  sourceDropletIds: [],
  sourceLoadBalancerUids: [],
  sourceKubernetesIds: [],
});
const rec = (o: Partial<EmergencyRecord>): EmergencyRecord => ({
  id: "x",
  environment: "demo",
  resourceAddress: "digitalocean_firewall.x",
  attribute: "inbound_rule",
  changeKind: "added",
  baseline: null,
  observed: rule("5432"),
  summary: "inbound tcp port 5432 added",
  firstDetectedAt: ago(60),
  lastDetectedAt: ago(5),
  reporter: null,
  reason: null,
  reportedAt: null,
  intent: "unset",
  intentNote: null,
  resolution: "open",
  resolutionReason: null,
  lastCheckStatus: "current",
  lastCheckAt: ago(5),
  evidenceSource: "terraform-refresh-only",
  reporterAssurance: null,
  intentUpdatedAt: null,
  lastActivity: { at: ago(60), type: "detected" },
  ...o,
});
const list: EmergencyRecord[] = [
  rec({ id: "a", resourceAddress: "digitalocean_firewall.db", firstDetectedAt: ago(60) }),
  rec({ id: "b", resourceAddress: "digitalocean_firewall.cache", summary: "inbound tcp port 6379 removed", changeKind: "removed", firstDetectedAt: ago(180) }),
  rec({
    id: "c", resourceAddress: "digitalocean_firewall.web", summary: "inbound tcp port 8080 changed live to port 8443",
    firstDetectedAt: ago(240), reason: "webhook", reporter: "Paul", reportedAt: ago(200), intent: "keep",
    reporterAssurance: "self-reported", lastActivity: { at: ago(200), type: "report" },
  }),
  rec({
    id: "d", resourceAddress: "digitalocean_firewall.api", firstDetectedAt: ago(360), reason: "ssh", reporter: "Sam",
    intent: "revert", reporterAssurance: "google-account (verified sign-in)", lastActivity: { at: ago(240), type: "decision" },
  }),
  rec({ id: "e", resourceAddress: "digitalocean_droplet.old", firstDetectedAt: ago(900), resolution: "resolved", reason: "done", reporter: "Sam", intent: "defer" }),
];

const ev = (o: Partial<AdminEvent> = {}): AdminEvent => ({
  at: "2026-11-08T02:55:00Z",
  type: "explained",
  environment: "demo",
  recordIds: ["c"],
  runId: null,
  resourceAddresses: ["digitalocean_firewall.web"],
  actor: "Paul",
  actorAssurance: "self-reported",
  outcome: null,
  planFingerprint: null,
  detail: "payment webhook blocked",
  ...o,
});
const log = (o: Partial<AdminLog> = {}): AdminLog => ({
  events: [ev()],
  totalMatching: 1,
  limitations: ["Actors are not verified identities."],
  ...o,
});

const admin: Me = { signedIn: true, email: "ada@example.com", displayName: "Ada", role: "admin", authMode: "firebase" };
function stub(o: Partial<Adapter> = {}, who: Me = admin): Adapter {
  return {
    ...fixtureAdapter,
    me: async () => who,
    listRecords: async () => ({ records: list, health: null }),
    adminEvents: async () => log(),
    ...o,
  };
}
beforeEach(() => (window.location.hash = "#/admin/records"));
afterEach(() => {
  cleanup();
  setAdapter(null);
});

const table = () => within(screen.getByRole("region", { name: "Records" }));
const rowFor = (name: string) => table().getByText(name).closest("tr") as HTMLElement;
const pick = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const loaded = async () => {
  await screen.findByRole("heading", { name: "Every manual change" });
  return screen.findByRole("region", { name: "Records" });
};
const lastCall = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls.at(-1)![0] as AdminFilters;

// ---- pure helpers ----------------------------------------------------------

test("filterRecords: open by default, search, explained-by, intent; newest detection first", () => {
  const base = { search: "", explainedBy: "any", intent: "any", status: "open" } as const;
  expect(filterRecords(list, base).map((r) => r.id)).toEqual(["a", "b", "c", "d"]);
  expect(filterRecords(list, { ...base, status: "resolved" }).map((r) => r.id)).toEqual(["e"]);
  expect(filterRecords(list, { ...base, status: "all" })).toHaveLength(5);
  expect(filterRecords(list, { ...base, search: "6379" }).map((r) => r.id)).toEqual(["b"]);
  expect(filterRecords(list, { ...base, search: "FIREWALL.WEB" }).map((r) => r.id)).toEqual(["c"]);
  expect(filterRecords(list, { ...base, explainedBy: "none" }).map((r) => r.id)).toEqual(["a", "b"]);
  expect(filterRecords(list, { ...base, explainedBy: "Sam" }).map((r) => r.id)).toEqual(["d"]);
  expect(filterRecords(list, { ...base, intent: "keep" }).map((r) => r.id)).toEqual(["c"]);
  expect(filterRecords(list, { ...base, intent: "unset" }).map((r) => r.id)).toEqual(["a", "b"]);
  const shuffled = [list[3], list[0], list[2], list[1]];
  expect(filterRecords(shuffled, base).map((r) => r.id)).toEqual(["a", "b", "c", "d"]);
});

test("a record explained without a name is neither 'Nobody yet' nor a named person", () => {
  const anon = rec({ id: "z", reason: "from the CLI", reporter: null });
  const all = [...list, anon];
  const base = { search: "", explainedBy: "any", intent: "any", status: "open" } as const;
  expect(filterRecords(all, { ...base, explainedBy: "none" }).map((r) => r.id)).not.toContain("z");
  expect(filterRecords(all, { ...base, explainedBy: UNNAMED }).map((r) => r.id)).toEqual(["z"]);
  expect(explainedByOptions(all).at(-1)).toEqual({ value: UNNAMED, label: "No name given" });
  expect(explainedByOptions(list).some((o) => o.value === UNNAMED)).toBe(false);
});

test("hourRange: whole hour, inclusive end; invalid values are ignored", () => {
  const h = hourRange("2026-11-08T02:00:00Z")!;
  expect(h.since).toBe("2026-11-08T02:00:00.000Z");
  expect(h.until).toBe("2026-11-08T02:59:59.999Z");
  expect(h.label).toBe("Hour: Nov 8, 02:00–03:00 UTC");
  expect(hourRange("2026-11-08T02:17:41Z")!.since).toBe("2026-11-08T02:00:00.000Z");
  expect(hourRange("garbage")).toBeNull();
  expect(hourRange(null)).toBeNull();
});

test("rangeSince: 24 h, 7 d, or no lower bound", () => {
  const now = Date.parse("2026-11-08T12:00:00Z");
  expect(rangeSince("24h", now)).toBe("2026-11-07T12:00:00.000Z");
  expect(rangeSince("7d", now)).toBe("2026-11-01T12:00:00.000Z");
  expect(rangeSince("all", now)).toBeUndefined();
});

// ---- shell / navigation ----------------------------------------------------

test("the sidebar has Overview and All records; All records is current on both views", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const nav = screen.getByRole("navigation", { name: "Main" });
  expect(within(nav).getAllByRole("link")).toHaveLength(2);
  expect(within(nav).getByRole("link", { name: /All records/ })).toHaveAttribute("aria-current", "page");
  expect(within(nav).getByRole("link", { name: /Overview/ })).not.toHaveAttribute("aria-current");
  cleanup();
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("heading", { name: "Every manual change" });
  expect(
    within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /All records/ }),
  ).toHaveAttribute("aria-current", "page");
});

test("the view switch links Records and Events, with a record count once known", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const sw = within(screen.getByRole("group", { name: "View" }));
  expect(sw.getByRole("link", { name: "Records" })).toHaveAttribute("href", "#/admin/records");
  expect(sw.getByRole("link", { name: "Records" })).toHaveAttribute("aria-current", "true");
  expect(sw.getByRole("link", { name: "Events" })).toHaveAttribute("href", "#/admin/events");
});

test("an employee at #/admin/records or #/admin/events gets the token gate and no admin data is requested", async () => {
  const adminEvents = vi.fn(async () => log());
  setAdapter(stub({ adminEvents }, { ...admin, role: "employee" }));
  render(<App />);
  expect(await screen.findByLabelText("Admin token")).toBeInTheDocument();
  cleanup();
  window.location.hash = "#/admin/events";
  render(<App />);
  expect(await screen.findByLabelText("Admin token")).toBeInTheDocument();
  expect(adminEvents).not.toHaveBeenCalled();
});

// ---- Records view ----------------------------------------------------------

test("records table: columns, link to the record page, status, explained by with assurance, intent, detected, last activity", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const heads = [...document.querySelectorAll("thead th")].map((t) => t.textContent);
  expect(heads).toEqual(["Resource", "Status", "Explained by", "Intent", "Detected", "Last activity"]);
  const db = within(rowFor("digitalocean_firewall.db"));
  expect(db.getByRole("link", { name: "digitalocean_firewall.db" })).toHaveAttribute("href", "#/admin/records/a");
  expect(db.getByText("No reason")).toBeInTheDocument();
  expect(db.getByText("Nobody yet")).toBeInTheDocument();
  expect(db.getByText("1 h ago")).toBeInTheDocument();
  expect(db.getByText("Detected by scan")).toBeInTheDocument();
  const web = within(rowFor("digitalocean_firewall.web"));
  expect(web.getByText("Paul")).toBeInTheDocument();
  expect(web.getByText("self-reported")).toBeInTheDocument();
  expect(web.getByText("Keep")).toBeInTheDocument();
  expect(web.getByText("Open")).toBeInTheDocument();
  expect(web.getByText(/Report, 3 h ago/)).toBeInTheDocument();
  const api = within(rowFor("digitalocean_firewall.api"));
  expect(api.getByText("verified sign-in")).toBeInTheDocument();
  expect(api.getByText("Revert")).toBeInTheDocument();
  expect(api.getByText(/Decision, 4 h ago/)).toBeInTheDocument();
});

test("rows are newest detection first, and resolved records are hidden until Status allows them", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const names = [...document.querySelectorAll("tbody tr .mono a")].map((a) => a.textContent);
  expect(names).toEqual([
    "digitalocean_firewall.db",
    "digitalocean_firewall.cache",
    "digitalocean_firewall.web",
    "digitalocean_firewall.api",
  ]);
  pick("Status", "resolved");
  expect(table().getByText("digitalocean_droplet.old")).toBeInTheDocument();
  expect(table().queryByText("digitalocean_firewall.db")).toBeNull();
  pick("Status", "all");
  expect(document.querySelectorAll("tbody tr")).toHaveLength(5);
});

test("search matches resource or summary as you type", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "6379" } });
  expect(document.querySelectorAll("tbody tr")).toHaveLength(1);
  expect(table().getByText("digitalocean_firewall.cache")).toBeInTheDocument();
});

test("Explained by lists Anyone, Nobody yet and each name; choosing one filters", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  const opts = [...screen.getByLabelText("Explained by").querySelectorAll("option")].map((o) => o.textContent);
  expect(opts).toEqual(["Anyone", "Nobody yet", "Paul", "Sam"]);
  pick("Explained by", "none");
  expect(document.querySelectorAll("tbody tr")).toHaveLength(2);
  pick("Explained by", "Sam");
  expect(table().getByText("digitalocean_firewall.api")).toBeInTheDocument();
  expect(document.querySelectorAll("tbody tr")).toHaveLength(1);
});

test("Intent filter, including a deferred and a not-set intent", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  pick("Intent", "keep");
  expect(document.querySelectorAll("tbody tr")).toHaveLength(1);
  pick("Intent", "unset");
  expect(document.querySelectorAll("tbody tr")).toHaveLength(2);
  pick("Status", "all");
  pick("Intent", "defer");
  expect(table().getByText("digitalocean_droplet.old")).toBeInTheDocument();
});

test("no match says so without claiming nothing changed", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "zzz" } });
  expect(screen.getByText(/No records match these filters/)).toBeInTheDocument();
  expect(screen.getByText(/not proof nothing changed/i)).toBeInTheDocument();
});

test("a failed records load is an error with retry, not an empty table", async () => {
  setAdapter(
    stub({
      listRecords: async () => {
        throw new ApiError("Backend unavailable", 503, "storage_unavailable");
      },
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
  expect(document.querySelector("tbody")).toBeNull();
});

test("the records view is read-only: no report form", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  expect(screen.queryByRole("button", { name: "Save report" })).toBeNull();
  expect(screen.queryByLabelText("What did you change and why?")).toBeNull();
});

// ---- Events view -----------------------------------------------------------

test("events: first load asks for the last 24 hours with no other filters, then shows who, event, resource, detail", async () => {
  const adminEvents = vi.fn(async (_f: AdminFilters) => log());
  setAdapter(stub({ adminEvents }));
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  const f = lastCall(adminEvents);
  expect(Object.keys(f).sort()).toEqual(["since"]);
  expect(Date.now() - Date.parse(f.since!)).toBeGreaterThan(24 * 3600_000 - 60_000);
  expect(Date.now() - Date.parse(f.since!)).toBeLessThan(24 * 3600_000 + 60_000);
  const row = within(document.querySelector("tbody tr") as HTMLElement);
  expect(row.getByText("Nov 8, 02:55")).toBeInTheDocument();
  expect(row.getByText("Paul")).toBeInTheDocument();
  expect(row.getByText("self-reported")).toBeInTheDocument();
  expect(row.getByText("Report")).toBeInTheDocument();
  expect(row.getByRole("link", { name: "digitalocean_firewall.web" })).toHaveAttribute("href", "#/admin/records/c");
  expect(row.getByText("payment webhook blocked")).toBeInTheDocument();
  expect(screen.getByText(/Newest first · 1 matching/)).toBeInTheDocument();
});

test("an unknown run outcome is flagged and never called failed; system events have no person", async () => {
  setAdapter(
    stub({
      adminEvents: async () =>
        log({
          events: [
            ev({ type: "run_unfinished", actor: null, actorAssurance: "system", outcome: "unknown", recordIds: [], resourceAddresses: [], detail: "outcome: unknown" }),
            ev({ type: "run_finished", actor: "Paul", outcome: "failed", detail: "outcome: failed — terraform exited 1" }),
          ],
          totalMatching: 2,
        }),
    }),
  );
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  const rows = document.querySelectorAll<HTMLElement>("tbody tr");
  const unknown = within(rows[0]);
  expect(unknown.getByText("system")).toBeInTheDocument();
  expect(unknown.getByText(/Outcome unknown, no completion recorded/)).toBeInTheDocument();
  expect(unknown.queryByText(/failed/i)).toBeNull();
  expect(unknown.getByText("Apply unfinished")).toHaveClass("amber");
  expect(unknown.getByText("—")).toBeInTheDocument(); // no resource
  const failed = within(rows[1]);
  expect(failed.getByText(/Outcome: Failed/)).toBeInTheDocument();
  expect(failed.getByText(/terraform exited 1/)).toBeInTheDocument();
  // the backend's "outcome: X" prefix is not repeated
  expect(failed.queryByText(/outcome: failed/)).toBeNull();
});

test("Apply sends engineer, resource, outcome and the chosen range", async () => {
  const adminEvents = vi.fn(async (_f: AdminFilters) => log());
  setAdapter(stub({ adminEvents }));
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  fireEvent.change(screen.getByLabelText("Engineer"), { target: { value: " Paul " } });
  fireEvent.change(screen.getByLabelText("Resource"), { target: { value: "digitalocean_firewall.web" } });
  pick("Outcome", "unknown");
  pick("Range", "7d");
  expect(adminEvents).toHaveBeenCalledTimes(1); // nothing is sent until Apply
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(adminEvents).toHaveBeenCalledTimes(2));
  const f = lastCall(adminEvents);
  expect(f).toMatchObject({ engineer: "Paul", resource: "digitalocean_firewall.web", outcome: "unknown" });
  expect(Date.now() - Date.parse(f.since!)).toBeGreaterThan(7 * 24 * 3600_000 - 60_000);
  pick("Range", "all");
  pick("Outcome", "");
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(adminEvents).toHaveBeenCalledTimes(3));
  expect(lastCall(adminEvents).since).toBeUndefined();
  expect(lastCall(adminEvents).outcome).toBeUndefined();
});

test("an hour from the URL filters to that hour and shows a chip; clearing it goes back to the range", async () => {
  const adminEvents = vi.fn(async (_f: AdminFilters) => log());
  setAdapter(stub({ adminEvents }));
  window.location.hash = "#/admin/events?hour=2026-11-08T02%3A00%3A00Z";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  expect(lastCall(adminEvents)).toEqual({ since: "2026-11-08T02:00:00.000Z", until: "2026-11-08T02:59:59.999Z" });
  const chip = screen.getByRole("button", { name: /Clear hour filter: Nov 8, 02:00–03:00 UTC/ });
  expect(chip).toHaveTextContent("Hour: Nov 8, 02:00–03:00 UTC");
  expect(screen.getByText(/Opened from the Overview chart/)).toBeInTheDocument();
  fireEvent.click(chip);
  expect(window.location.hash).toBe("#/admin/events");
  await waitFor(() => expect(screen.queryByRole("button", { name: /Clear hour filter/ })).toBeNull());
  await waitFor(() => expect(Object.keys(lastCall(adminEvents))).toEqual(["since"]));
});

test("Range is disabled while an hour filter is active, so it is never silently ignored", async () => {
  setAdapter(stub());
  window.location.hash = "#/admin/events?hour=2026-11-08T02%3A00%3A00Z";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  expect(screen.getByLabelText("Range")).toBeDisabled();
  cleanup();
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  expect(screen.getByLabelText("Range")).toBeEnabled();
});

test("an invalid hour in the URL is ignored", async () => {
  const adminEvents = vi.fn(async (_f: AdminFilters) => log());
  setAdapter(stub({ adminEvents }));
  window.location.hash = "#/admin/events?hour=nonsense";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  expect(screen.queryByRole("button", { name: /Clear hour filter/ })).toBeNull();
  expect(Object.keys(lastCall(adminEvents))).toEqual(["since"]);
});

test("a truncated list says how many are shown", async () => {
  setAdapter(stub({ adminEvents: async () => log({ totalMatching: 340 }) }));
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  expect(screen.getByText(/Showing 1 of 340/)).toBeInTheDocument();
});

test("no events says so without claiming nothing happened", async () => {
  setAdapter(stub({ adminEvents: async () => log({ events: [], totalMatching: 0 }) }));
  window.location.hash = "#/admin/events";
  render(<App />);
  expect(await screen.findByText(/No events match these filters/)).toBeInTheDocument();
  expect(screen.getByText(/does not prove nothing happened/i)).toBeInTheDocument();
});

test("a failed events load is an error with retry, and the server's limitations show on success", async () => {
  const adminEvents = vi
    .fn<Adapter["adminEvents"]>()
    .mockRejectedValueOnce(new ApiError("Backend unavailable", 503, "storage_unavailable"))
    .mockResolvedValue(log());
  setAdapter(stub({ adminEvents }));
  window.location.hash = "#/admin/events";
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText(/Actors are not verified identities/)).toBeInTheDocument();
});

test("switching views keeps you in the admin shell", async () => {
  setAdapter(stub());
  render(<App />);
  await loaded();
  fireEvent.click(screen.getByRole("link", { name: "Events" }));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(await screen.findByRole("region", { name: "Events" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
});

test("an event whose record ids do not line up with its resources shows plain text, never a guessed link", async () => {
  setAdapter(
    stub({
      adminEvents: async () =>
        log({
          events: [ev({ recordIds: ["a", "b"], resourceAddresses: ["digitalocean_firewall.web"] })],
        }),
    }),
  );
  window.location.hash = "#/admin/events";
  render(<App />);
  await screen.findByRole("region", { name: "Events" });
  const row = within(document.querySelector("tbody tr") as HTMLElement);
  expect(row.getByText("digitalocean_firewall.web")).toBeInTheDocument();
  expect(row.queryByRole("link")).toBeNull();
});
