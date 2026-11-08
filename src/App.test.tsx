// @vitest-environment jsdom
// STUB-ADAPTER behavioral tests + wire-mapping test. Not backend integration.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { ApiError, fromWireApplyRun, fromWireRecord, setAdapter } from "./api";
import type { Adapter, ApplyRun, EmergencyRecord, Rule } from "./api";

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
  resourceAddress: "digitalocean_firewall.web",
  attribute: "inbound_rule",
  changeKind: "modified",
  baseline: rule("8080"),
  observed: rule("8443"),
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
const run = (o: Partial<ApplyRun> = {}): ApplyRun => ({
  id: "x",
  environment: "demo",
  generatedAt: "2026-11-08T09:12:00.000000Z",
  planFingerprint: "sha256:a",
  proposedChanges: [
    { resourceAddress: "a.b", actions: ["update"], summary: "update x" },
  ],
  warnings: [],
  checkStatus: "current",
  coverageNote: "Checked firewall inbound rules only.",
  ackOutcome: "pending",
  ackNote: null,
  completedAt: null,
  ...o,
});

function stub(o: Partial<Adapter>): Adapter {
  return {
    listRecords: async () => ({ records: [rec()], health }),
    getRecord: async () => rec(),
    report: async (_i, b) =>
      rec({
        reporter: b.reporter,
        reason: b.reason,
        reportedAt: "2026-11-08T03:31:40Z",
      }),
    decide: async (_i, intent) => rec({ intent }),
    getApplyRun: async () => run(),
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

test("wire mapping: snake_case record and apply run", () => {
  const r = fromWireRecord({
    id: "rec_1",
    environment: "demo-authored",
    resource_address: "a.b",
    attribute: "inbound_rule",
    change_kind: "added",
    baseline_value: null,
    observed_value: {
      protocol: "tcp",
      port_range: "9",
      source_addresses: ["::/0"],
    },
    summary: "s",
    first_detected_at: "t1",
    last_detected_at: "t2",
    reporter: null,
    reason: null,
    reported_at: null,
    intent: "unset",
    resolution: "open",
    last_check_status: "failed",
    last_check_at: null,
    evidence_source: "authored-fixture",
  });
  expect(r.baseline).toBeNull();
  expect(r.observed?.portRange).toBe("9");
  expect(r.firstDetectedAt).toBe("t1");
  const a = fromWireApplyRun({
    id: "run_1",
    environment: "demo",
    generated_at: "g",
    plan_fingerprint: null,
    proposed_changes: [],
    warnings: [
      {
        record_id: "rec_1",
        resource_address: "a.b",
        message: "m",
        reason: null,
        reporter: null,
        intent: "unset",
        first_detected_at: "t",
      },
    ],
    check_status: "failed",
    coverage_note: "c",
    ack_outcome: "pending",
  });
  expect(a.warnings[0].recordId).toBe("rec_1");
  expect(a.planFingerprint).toBeNull();
});

test("list: detected-at, missing-reason tag, demo tag, failed check wording", async () => {
  setAdapter(
    stub({
      listRecords: async () => ({
        records: [
          rec({
            environment: "demo-authored",
            evidenceSource: "authored-fixture",
            lastCheckStatus: "failed",
          }),
        ],
        health,
      }),
    }),
  );
  render(<App />);
  expect(
    await screen.findByText(/detected at Nov 8, 03:30 UTC/),
  ).toBeInTheDocument();
  expect(screen.getByText("no reason recorded")).toBeInTheDocument();
  expect(
    screen.getByText(/DEMO DATA · demo-authored · authored-fixture/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/not confirmed by the latest check/),
  ).toBeInTheDocument();
});

test("list: backend failure is an error, not an empty list", async () => {
  setAdapter(
    stub({
      listRecords: async () => {
        throw new ApiError("Backend unavailable", 0);
      },
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Backend unavailable",
  );
  expect(screen.queryByText(/No open records/)).toBeNull();
});

test("empty list does not claim nothing changed", async () => {
  setAdapter(
    stub({ listRecords: async () => ({ records: [], health: null }) }),
  );
  render(<App />);
  expect(
    await screen.findByText(/not proof nothing changed/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Backend health is unreachable/)).toBeInTheDocument();
});

test("reason renders as plain text, not HTML", async () => {
  window.location.hash = "#/records/r1";
  setAdapter(
    stub({
      getRecord: async () =>
        rec({ reason: "<img src=x onerror=alert(1)>", reporter: "P" }),
    }),
  );
  const { container } = render(<App />);
  expect(await screen.findByText(/reported by P/)).toBeInTheDocument();
  // scoped to <main>: the sidebar wordmark legitimately contains the logo <img>
  expect(container.querySelector("main img")).toBeNull();
  expect(container.querySelector("blockquote")).toHaveTextContent(
    "<img src=x onerror=alert(1)>",
  );
});

test("detail: missing reason fallback; report saves and shows reported by", async () => {
  window.location.hash = "#/records/r1";
  setAdapter(stub({}));
  render(<App />);
  expect(
    await screen.findByText("Unexplained manual change — no reason recorded."),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Your name/), {
    target: { value: "Paul" },
  });
  fireEvent.change(screen.getByLabelText(/What did you change/), {
    target: { value: "webhook blocked" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  expect(await screen.findByText(/reported by Paul/)).toBeInTheDocument();
  expect(screen.getByText("Saved by the backend.")).toBeInTheDocument();
});

test("report save failure keeps text and says not saved", async () => {
  window.location.hash = "#/records/r1";
  setAdapter(
    stub({
      report: vi.fn().mockRejectedValue(new ApiError("reason too long", 422)),
    }),
  );
  render(<App />);
  await screen.findByLabelText(/Your name/);
  fireEvent.change(screen.getByLabelText(/What did you change/), {
    target: { value: "why" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Not saved: reason too long",
  );
  expect(screen.getByLabelText(/What did you change/)).toHaveValue("why");
});

test("intent does not resolve; keep shows manual suggestion", async () => {
  window.location.hash = "#/records/r1";
  setAdapter(stub({}));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Keep" }));
  expect(await screen.findByText(/Intent recorded/)).toHaveTextContent(
    "still open",
  );
  expect(screen.getByText(/by hand/)).toBeInTheDocument();
});

test("resolved record closes the forms", async () => {
  window.location.hash = "#/records/r1";
  setAdapter(
    stub({
      getRecord: async () =>
        rec({ resolution: "resolved", resolutionReason: "verified_aligned" }),
    }),
  );
  render(<App />);
  expect(
    await screen.findByText(/reports and intent changes are closed/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save report" })).toBeNull();
});

test("apply run: failed check = verification unavailable, never 'no conflicts'", async () => {
  window.location.hash = "#/apply/x";
  setAdapter(
    stub({
      getApplyRun: async () => run({ checkStatus: "failed", warnings: [] }),
    }),
  );
  render(<App />);
  expect(
    await screen.findByText(/Verification unavailable/),
  ).toBeInTheDocument();
  expect(screen.getByText(/bypasses it/)).toBeInTheDocument();
  expect(
    screen.queryByText(/no conflicts (found|detected)|safe to apply/i),
  ).toBeNull();
  expect(screen.queryByText(/No open record matched/)).toBeNull();
});

test("apply run: matched reason, missing-reason fallback, outcome", async () => {
  window.location.hash = "#/apply/x";
  setAdapter(
    stub({
      getApplyRun: async () =>
        run({
          ackOutcome: "kept",
          warnings: [
            {
              recordId: "a",
              resourceAddress: "a.b",
              message: "m1",
              reason: "webhook blocked",
              reporter: "Paul",
              intent: "keep",
              firstDetectedAt: "2026-11-08T03:30:12Z",
            },
            {
              recordId: "b",
              resourceAddress: "a.b",
              message: "m2",
              reason: null,
              reporter: null,
              intent: "unset",
              firstDetectedAt: "2026-11-08T03:30:12Z",
            },
          ],
        }),
    }),
  );
  render(<App />);
  expect(await screen.findByText("webhook blocked")).toBeInTheDocument();
  expect(
    screen.getByText(/reported by Paul \(self-reported\)/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Unexplained manual change — no reason recorded/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Kept — apply was not run/)).toBeInTheDocument();
});

test("apply run: null plan fingerprint is flagged", async () => {
  window.location.hash = "#/apply/x";
  setAdapter(stub({ getApplyRun: async () => run({ planFingerprint: null }) }));
  render(<App />);
  expect(await screen.findByText(/Planning failed/)).toBeInTheDocument();
});

test("header keeps the current page name apart from the product-name prefix so phones can hide only the prefix", () => {
  setAdapter(stub({}));
  window.location.hash = "#/apply/run_1";
  const { container } = render(<App />);
  const header = container.querySelector("header")!;
  const root = header.querySelector(".crumb-root");
  expect(root).toHaveTextContent("Argus");
  expect(root).not.toHaveTextContent("Apply warning");
  expect(header.querySelector(".crumb-current")).toHaveTextContent("Apply warning");
});

test("the product is named Argus everywhere a user sees it", async () => {
  setAdapter(stub({}));
  const { container } = render(<App />);
  const text = container.textContent ?? "";
  const labels = [...container.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label")).join(" ");
  expect(text + labels).toMatch(/Argus/i);
  expect(text + labels).not.toMatch(/break-?glass/i);
  const html = (await import("../index.html?raw")).default;
  expect(html).toMatch(/<title>Argus/);
  expect(html).not.toMatch(/break-?glass/i);
});

test("the Argus logo lockup is the wordmark image and the eye mark is the favicon; the image is decorative because the link is already named", async () => {
  setAdapter(stub({}));
  const { container } = render(<App />);
  const link = container.querySelector("a.wordmark")!;
  expect(link).toHaveAttribute("aria-label", "Argus home");
  const img = link.querySelector("img")!;
  expect(img).toHaveAttribute("src", "/argus-logo.svg");
  expect(img).toHaveAttribute("alt", "");
  expect(link.textContent).toBe(""); // the lockup is an image; the accessible name comes from aria-label
  const html = (await import("../index.html?raw")).default;
  expect(html).toMatch(/<link[^>]+rel="icon"[^>]+type="image\/svg\+xml"[^>]+href="\/argus-mark\.svg"/);
  const files = import.meta.glob("../public/*.svg", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
  for (const f of ["../public/argus-logo.svg", "../public/argus-mark.svg"]) {
    expect(files[f], f).toMatch(/^<svg /);
    expect(files[f], f).not.toMatch(/<script|<foreignObject|href=|onload|<style/i); // static artwork only
  }
  expect(files["../public/argus-logo.svg"]).toContain("ARGUS");
  expect(files["../public/argus-mark.svg"]).not.toContain("ARGUS");
});
