// @vitest-environment jsdom
// Admin command palette: records, events (client-side over the loaded admin log), and "Go to" pages.
import { afterEach, beforeEach, expect, test } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { setAdapter } from "./api";
import type { AdminEvent, Adapter, EmergencyRecord, Me } from "./api";
import { fixtureAdapter } from "./fixtures";
import { eventMatches, termsOf } from "./palette";

const rec = (o: Partial<EmergencyRecord>): EmergencyRecord => ({
  id: "x",
  environment: "demo",
  resourceAddress: "digitalocean_firewall.x",
  attribute: "inbound_rule",
  changeKind: "added",
  baseline: null,
  observed: null,
  summary: "inbound tcp port 5432 added",
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
  reporterAssurance: null,
  intentUpdatedAt: null,
  lastActivity: null,
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
const records = [
  rec({ id: "a", resourceAddress: "digitalocean_firewall.db" }),
  rec({
    id: "c",
    resourceAddress: "digitalocean_firewall.web",
    summary: "inbound tcp port 8080 changed live to port 8443",
    reason: "webhook",
    reporter: "Paul",
    intent: "keep",
  }),
];
const events = [
  ev({ type: "decision", actor: "Paul", actorAssurance: "self-reported", detail: "keep" }),
  ev({
    type: "explained",
    actor: "Paul",
    actorAssurance: "self-reported",
    detail: "payment webhook blocked, opened 8443",
  }),
  ev({ type: "change_detected", recordIds: ["a"], resourceAddresses: ["digitalocean_firewall.db"] }),
  ev({ type: "run_started", recordIds: [], resourceAddresses: [], runId: "run_1", at: "2026-11-08T04:00:00Z" }),
];

const admin: Me = { signedIn: true, email: "ada@example.com", displayName: "Ada", role: "admin", authMode: "firebase" };
const employee: Me = { signedIn: true, email: "e@example.com", displayName: "E", role: "employee", authMode: "firebase" };
let eventCalls = 0;
function stub(o: Partial<Adapter> = {}, who: Me = admin): Adapter {
  return {
    ...fixtureAdapter,
    me: async () => who,
    listRecords: async () => ({ records, health: null }),
    adminEvents: async () => {
      eventCalls++;
      return { events, totalMatching: events.length, limitations: [] };
    },
    adminOverview: fixtureAdapter.adminOverview,
    ...o,
  };
}
beforeEach(() => {
  eventCalls = 0;
  window.location.hash = "#/admin";
  setAdapter(stub());
});
afterEach(() => {
  cleanup();
  setAdapter(null);
});

const ready = () => screen.findByRole("heading", { name: /manual changes, before the next apply/i });
const trigger = () => screen.getByRole("button", { name: /search records and events/i });
const dialog = () => screen.getByRole("dialog", { name: "Search" });
const input = () => screen.getByRole("combobox", { name: /search records, people and events/i });
const type = (v: string) => fireEvent.change(input(), { target: { value: v } });
const key = (k: string) => fireEvent.keyDown(input(), { key: k });
const selected = () => within(dialog()).getByRole("option", { selected: true });
const open = async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  // wait for both loads
  await waitFor(() => expect(within(dialog()).queryByText(/loading/i)).toBeNull());
};

test("eventMatches covers actor, resource, detail and type label; every term must match", () => {
  const e = events[1];
  expect(eventMatches(e, termsOf("paul"))).toBe(true);
  expect(eventMatches(e, termsOf("firewall.web"))).toBe(true);
  expect(eventMatches(e, termsOf("webhook 8443"))).toBe(true);
  expect(eventMatches(e, termsOf("report"))).toBe(true);
  expect(eventMatches(e, termsOf("paul nobody"))).toBe(false);
});

test("the admin top bar has the search button; click and Cmd+K both open the palette, input focused", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  expect(input()).toHaveFocus();
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  expect(dialog()).toBeInTheDocument();
});

test("the events are fetched only when the palette opens", async () => {
  render(<App />);
  await ready();
  const before = eventCalls;
  fireEvent.click(trigger());
  await waitFor(() => expect(eventCalls).toBe(before + 1));
});

test("typing a name shows Records, Events and Go to groups with counts, and highlights the match", async () => {
  await open();
  type("paul");
  const d = within(dialog());
  expect(d.getByText("RECORDS · 1")).toBeInTheDocument();
  expect(d.getByText("EVENTS · 2")).toBeInTheDocument();
  expect(d.getByText("Decision")).toBeInTheDocument();
  expect(d.getByText("Report")).toBeInTheDocument();
  expect(dialog().querySelector("mark")).toHaveTextContent(/paul/i);
  // "Go to" rows only show when they match the text
  expect(d.queryByText("GO TO")).toBeNull();
});

test("empty query lists Go to: Overview and All records", async () => {
  await open();
  const d = within(dialog());
  expect(d.getByText("GO TO")).toBeInTheDocument();
  expect(d.getByRole("option", { name: "Overview" })).toBeInTheDocument();
  expect(d.getByRole("option", { name: "All records" })).toBeInTheDocument();
});

test("typing 'overview' offers only the page row", async () => {
  await open();
  type("overview");
  const d = within(dialog());
  expect(d.getByRole("option", { name: "Overview" })).toBeInTheDocument();
  expect(d.queryByRole("option", { name: "All records" })).toBeNull();
  expect(d.queryByText(/^RECORDS/)).toBeNull();
});

test("Enter on a record opens its admin Record page and closes the palette", async () => {
  await open();
  type("firewall.web");
  expect(selected()).toHaveTextContent("digitalocean_firewall.web");
  key("Enter");
  expect(window.location.hash).toBe("#/admin/records/c");
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("Enter on an event opens its record; an event with no record opens the Events view at that hour", async () => {
  await open();
  type("paul");
  key("ArrowDown"); // record -> first event
  key("Enter");
  expect(window.location.hash).toBe("#/admin/records/c");

  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await waitFor(() => expect(within(dialog()).queryByText(/loading/i)).toBeNull());
  type("apply started");
  key("Enter");
  expect(window.location.hash).toBe(`#/admin/events?hour=${encodeURIComponent("2026-11-08T04:00:00Z")}`);
});

test("arrows wrap, Enter on Go to navigates, Esc closes and returns focus to the button", async () => {
  await open();
  type("all rec");
  expect(selected()).toHaveTextContent("All records");
  key("ArrowUp");
  expect(selected()).toHaveTextContent("All records"); // one row: wraps onto itself
  key("Enter");
  expect(window.location.hash).toBe("#/admin/records");

  trigger().focus();
  fireEvent.click(trigger());
  expect(dialog()).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger()).toHaveFocus();
});

test("Tab keeps focus in the input", async () => {
  await open();
  fireEvent.keyDown(input(), { key: "Tab" });
  expect(input()).toHaveFocus();
});

test("no match says it only covers what was loaded; the events note states how many were searched", async () => {
  setAdapter(
    stub({
      adminEvents: async () => ({ events, totalMatching: 250, limitations: [] }),
    }),
  );
  await open();
  type("zzzz");
  expect(within(dialog()).getByText(/does not mean nothing happened/i)).toBeInTheDocument();
  type("paul");
  expect(within(dialog()).getByText(/latest 4 of 250 events/i)).toBeInTheDocument();
});

test("if events fail to load, records and Go to still work and the failure is stated", async () => {
  setAdapter(
    stub({
      adminEvents: async () => {
        throw new Error("boom");
      },
    }),
  );
  await open();
  type("firewall");
  const d = within(dialog());
  expect(d.getByText(/events could not be loaded/i)).toBeInTheDocument();
  expect(d.getByText("RECORDS · 2")).toBeInTheDocument();
});

test("an employee never gets the admin palette or its groups", async () => {
  setAdapter(stub({}, employee));
  window.location.hash = "#/";
  render(<App />);
  await screen.findByRole("heading", { name: "Manual changes" });
  expect(screen.queryByRole("button", { name: /search records and events/i })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /search records/i }));
  const d = within(dialog());
  expect(d.queryByText(/^EVENTS/)).toBeNull();
  expect(d.queryByText("GO TO")).toBeNull();
  expect(eventCalls).toBe(0);
});

test("ArrowDown moves forward through groups; ArrowUp goes back and wraps from the first row to the last", async () => {
  await open();
  type("paul");
  expect(selected()).toHaveTextContent("digitalocean_firewall.web"); // record
  key("ArrowDown");
  expect(selected()).toHaveTextContent("Decision"); // first event
  key("ArrowUp");
  expect(selected()).toHaveTextContent("digitalocean_firewall.web");
  key("ArrowUp"); // wraps to the last row (second event)
  expect(selected()).toHaveTextContent("Report");
});
