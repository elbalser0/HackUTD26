// @vitest-environment jsdom
// Employee command palette (client-side search). Stub adapter.
import { afterEach, beforeEach, expect, test } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { setAdapter } from "./api";
import type { Adapter, EmergencyRecord, Rule } from "./api";
import { fixtureAdapter } from "./fixtures";

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
const list = [
  rec({ id: "a", resourceAddress: "digitalocean_firewall.db" }),
  rec({ id: "b", resourceAddress: "digitalocean_firewall.cache", changeKind: "removed" }),
  rec({
    id: "c",
    resourceAddress: "digitalocean_firewall.web",
    summary: "inbound tcp port 8080 changed live to port 8443",
    reason: "webhook",
    reporter: "Paul",
    intent: "keep",
  }),
  rec({ id: "d", resourceAddress: "digitalocean_droplet.old", resolution: "resolved", reason: "done", reporter: "Sam" }),
];
const adapter: Adapter = {
  ...fixtureAdapter,
  me: async () => ({ signedIn: false, email: null, displayName: null, role: null, authMode: "none" }),
  listRecords: async () => ({ records: list, health: null }),
};
beforeEach(() => {
  window.location.hash = "#/";
  setAdapter(adapter);
});
afterEach(() => {
  cleanup();
  setAdapter(null);
});

const ready = () => screen.findByRole("heading", { name: "Manual changes" });
const trigger = () => screen.getByRole("button", { name: /search records/i });
const dialog = () => screen.getByRole("dialog", { name: "Search" });
const input = () => screen.getByRole("combobox", { name: "Search records and filters" });
const type = (v: string) => fireEvent.change(input(), { target: { value: v } });
const key = (k: string) => fireEvent.keyDown(input(), { key: k });
const selected = () => within(dialog()).getByRole("option", { selected: true });

test("the top bar has a search button; clicking it opens the palette with the input focused", async () => {
  render(<App />);
  await ready();
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(trigger());
  expect(dialog()).toBeInTheDocument();
  expect(input()).toHaveFocus();
});

test("Cmd+K and Ctrl+K open it and toggle it closed", async () => {
  render(<App />);
  await ready();
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  expect(dialog()).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  expect(dialog()).toBeInTheDocument();
});

test("a plain k keypress does not open it", async () => {
  render(<App />);
  await ready();
  fireEvent.keyDown(document, { key: "k" });
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("empty query: records and the three filters with counts; no events and no pages (employee scope)", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  const d = within(dialog());
  expect(d.getByText("RECORDS · 4")).toBeInTheDocument();
  expect(d.getByText("FILTERS")).toBeInTheDocument();
  expect(d.getByRole("option", { name: /Needs a reason · 2/ })).toBeInTheDocument();
  expect(d.getByRole("option", { name: /Explained · 1/ })).toBeInTheDocument();
  expect(d.getByRole("option", { name: /Resolved · 1/ })).toBeInTheDocument();
  expect(d.queryByText(/^EVENTS/)).toBeNull();
  expect(d.queryByText(/^GO TO/)).toBeNull();
});

test("typing filters records by resource, summary or who explained it, and highlights the match", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("cache");
  let d = within(dialog());
  expect(d.getByText("RECORDS · 1")).toBeInTheDocument();
  expect(dialog().querySelector("mark")).toHaveTextContent("cache");
  type("8443");
  d = within(dialog());
  expect(d.getByText("RECORDS · 1")).toBeInTheDocument();
  expect(d.getByRole("option", { name: /digitalocean_firewall\.web/ })).toBeInTheDocument();
  type("paul");
  d = within(dialog());
  expect(d.getByRole("option", { name: /digitalocean_firewall\.web/ })).toBeInTheDocument();
  expect(d.queryByRole("option", { name: /firewall\.db/ })).toBeNull();
});

test("the reason text is not searched (only resource, summary and who explained it)", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("webhook");
  expect(within(dialog()).queryByText(/^RECORDS/)).toBeNull();
});

test("filter rows match their label while typing", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("resolv");
  const d = within(dialog());
  expect(d.getByRole("option", { name: /Resolved · 1/ })).toBeInTheDocument();
  expect(d.queryByRole("option", { name: /Needs a reason/ })).toBeNull();
});

test("no match says so without claiming nothing changed", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("zzzz");
  expect(within(dialog()).getByText(/No matches/)).toBeInTheDocument();
  expect(within(dialog()).queryAllByRole("option")).toHaveLength(0);
});

test("regex characters in the query are plain text and do not throw", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("a(b[");
  expect(within(dialog()).getByText(/No matches/)).toBeInTheDocument();
});

test("arrow keys move the selection and wrap; typing resets it to the first result", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  expect(selected()).toHaveTextContent("digitalocean_firewall.db");
  key("ArrowDown");
  expect(selected()).toHaveTextContent("digitalocean_firewall.cache");
  key("ArrowUp");
  key("ArrowUp");
  // wrapped to the last row: the Resolved filter
  expect(selected()).toHaveTextContent("Resolved · 1");
  key("ArrowDown");
  expect(selected()).toHaveTextContent("digitalocean_firewall.db");
  key("ArrowDown");
  type("firewall");
  expect(selected()).toHaveTextContent("digitalocean_firewall.db");
  expect(input()).toHaveAttribute("aria-activedescendant", selected().id);
});

test("Enter on a record opens it (URL, tab and panel follow) and closes the palette", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("web");
  key("Enter");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(window.location.hash).toBe("#/records/c");
  expect(
    await screen.findByRole("region", { name: "digitalocean_firewall.web" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Explained · 1/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("clicking a record row opens it", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  fireEvent.click(within(dialog()).getByRole("option", { name: /digitalocean_droplet\.old/ }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    await screen.findByRole("region", { name: "digitalocean_droplet.old" }),
  ).toBeInTheDocument();
});

test("Enter on a filter switches the tab and closes the palette", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  type("resolved");
  key("Enter");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: /Resolved · 1/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("Esc closes and returns focus to the button that opened it", async () => {
  render(<App />);
  await ready();
  trigger().focus();
  fireEvent.click(trigger());
  key("Escape");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger()).toHaveFocus();
});

test("Tab stays inside the dialog", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
  input().dispatchEvent(ev);
  expect(ev.defaultPrevented).toBe(true);
  expect(dialog().contains(document.activeElement)).toBe(true);
});

test("clicking the backdrop closes it; clicking inside does not", async () => {
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  fireEvent.mouseDown(dialog());
  expect(dialog()).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByTestId("palette-backdrop"));
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a long result list is capped and says so", async () => {
  const many = Array.from({ length: 12 }, (_, i) =>
    rec({ id: `m${i}`, resourceAddress: `digitalocean_firewall.m${i}` }),
  );
  setAdapter({ ...adapter, listRecords: async () => ({ records: many, health: null }) });
  render(<App />);
  await ready();
  fireEvent.click(trigger());
  const d = within(dialog());
  expect(d.getByText("RECORDS · 12")).toBeInTheDocument();
  expect(d.getByText(/Showing the first 8/)).toBeInTheDocument();
  expect(d.getAllByRole("option").filter((o) => /firewall\.m/.test(o.textContent ?? ""))).toHaveLength(8);
});
