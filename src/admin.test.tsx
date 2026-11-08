// @vitest-environment jsdom
// R9 admin dashboard. STUB-ADAPTER behavioral tests, plus a real-adapter test
// against a stubbed fetch for the wire contract (header, query, no token in URL).
// Not backend integration.
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
import {
  ApiError,
  api,
  fromWireAdminLog,
  fromWireTimeline,
  setAdapter,
} from "./api";
import type {
  AdminEvent,
  AdminFilters,
  AdminLog,
  Adapter,
  Timeline,
} from "./api";

const ev = (o: Partial<AdminEvent> = {}): AdminEvent => ({
  at: "2026-11-08T03:35:12Z",
  type: "review",
  environment: "demo",
  recordIds: ["rec_1"],
  runId: "run_1",
  resourceAddresses: ["digitalocean_firewall.demo"],
  actor: "Dana (demo)",
  actorAssurance: "self-reported",
  outcome: null,
  planFingerprint: "sha256:abc",
  detail: "decision: revert — webhook fixed upstream",
  ...o,
});
const LIMITS = [
  "Actors are not verified identities: test limitation text.",
  "Admin access uses one shared token: test limitation two.",
];
const log = (o: Partial<AdminLog> = {}): AdminLog => ({
  events: [ev()],
  totalMatching: 1,
  limitations: LIMITS,
  ...o,
});
const timeline = (o: Partial<Timeline> = {}): Timeline => ({
  recordId: "rec_1",
  events: [
    ev({
      type: "change_detected",
      actor: null,
      actorAssurance: "system",
      runId: null,
      planFingerprint: null,
      detail: "port 8443 added",
      at: "2026-11-08T03:30:00Z",
    }),
    ev({
      type: "explained",
      detail: "opened for webhook",
      at: "2026-11-08T03:31:00Z",
      runId: null,
      planFingerprint: null,
    }),
    ev({
      type: "run_unfinished",
      outcome: "unknown",
      detail: "No completion recorded",
      at: "2026-11-08T03:40:00Z",
    }),
  ],
  gaps: [
    {
      code: "no_decision_recorded",
      message: "No keep/revert/defer decision was recorded for this change.",
      runId: null,
    },
    {
      code: "run_outcome_unknown",
      message:
        "Run run_1 has no recorded completion; do not assume it succeeded.",
      runId: "run_1",
    },
  ],
  limitations: LIMITS,
  ...o,
});

function stub(o: Partial<Adapter>): Adapter {
  return {
    listRecords: async () => ({ records: [], health: null }),
    getRecord: async () => {
      throw new Error("unused");
    },
    adminOverview: async () => {
      throw new Error("unused");
    },
    me: async () => ({ signedIn: false, email: null, displayName: null, role: null, authMode: "none" as const }),
    recordEvents: async () => [],
    report: async () => {
      throw new Error("unused");
    },
    decide: async () => {
      throw new Error("unused");
    },
    getApplyRun: async () => {
      throw new Error("unused");
    },
    adminLog: async () => log(),
    adminTimeline: async () => timeline(),
    ...o,
  };
}

async function signIn(token = "s3cret") {
  // the gate appears once /api/me has answered "not an admin"
  fireEvent.change(await screen.findByLabelText(/admin token/i), {
    target: { value: token },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /unlock|sign in|continue/i }),
  );
}

beforeEach(() => (window.location.hash = "#/admin"));
afterEach(() => {
  cleanup();
  setAdapter(null);
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

test("wire mapping: admin log and timeline", () => {
  const l = fromWireAdminLog({
    events: [
      {
        at: "t",
        type: "run_unfinished",
        environment: "demo",
        record_ids: ["rec_1"],
        run_id: "run_1",
        resource_addresses: ["a.b"],
        actor: null,
        actor_assurance: "system",
        outcome: "unknown",
        plan_fingerprint: null,
        detail: "d",
      },
    ],
    total_matching: 7,
    limitations: ["x"],
  });
  expect(l.totalMatching).toBe(7);
  expect(l.events[0]).toMatchObject({
    recordIds: ["rec_1"],
    runId: "run_1",
    outcome: "unknown",
    actorAssurance: "system",
    planFingerprint: null,
  });
  const t = fromWireTimeline({
    record_id: "rec_1",
    events: [],
    gaps: [{ code: "run_outcome_unknown", message: "m", run_id: "run_1" }],
    limitations: ["x"],
  });
  expect(t.gaps[0]).toEqual({
    code: "run_outcome_unknown",
    message: "m",
    runId: "run_1",
  });
});

test("gate: no request is made and no data shown until a token is entered; token is a password field", async () => {
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => log());
  setAdapter(stub({ adminLog }));
  render(<App />);
  const input = await screen.findByLabelText(/admin token/i);
  expect(input).toHaveAttribute("type", "password");
  expect(adminLog).not.toHaveBeenCalled();
  expect(screen.queryByText(/webhook fixed upstream/)).toBeNull();
  await signIn("s3cret");
  await screen.findByText(/webhook fixed upstream/);
  expect(adminLog.mock.calls[0][0]).toBe("s3cret");
});

test("token never reaches the URL or browser storage", async () => {
  setAdapter(stub({}));
  render(<App />);
  await signIn("s3cret-token-value");
  await screen.findByText(/webhook fixed upstream/);
  expect(window.location.href).not.toContain("s3cret-token-value");
  expect(JSON.stringify({ ...localStorage })).not.toContain(
    "s3cret-token-value",
  );
  expect(JSON.stringify({ ...sessionStorage })).not.toContain(
    "s3cret-token-value",
  );
});

test("401: says the token was rejected and asks again; shows no data", async () => {
  setAdapter(
    stub({
      adminLog: async () => {
        throw new ApiError(
          "Missing or invalid admin credentials",
          401,
          "unauthorized",
        );
      },
    }),
  );
  render(<App />);
  await signIn("wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /rejected|invalid/i,
  );
  expect(screen.getByLabelText(/admin token/i)).toBeInTheDocument();
});

test("403: says admin access is not configured on the server, not 'wrong token'", async () => {
  setAdapter(
    stub({
      adminLog: async () => {
        throw new ApiError("Admin access is not configured", 403, "forbidden");
      },
    }),
  );
  render(<App />);
  await signIn();
  expect(await screen.findByRole("alert")).toHaveTextContent(/not configured/i);
});

test("backend unreachable is an error, not an empty log", async () => {
  setAdapter(
    stub({
      adminLog: async () => {
        throw new ApiError("Backend unreachable", 0);
      },
    }),
  );
  render(<App />);
  await signIn();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /unavailable|could not/i,
  );
  expect(screen.queryByText(/no events/i)).toBeNull();
});

test("log: actor with assurance label, unknown outcome stated plainly, limitations, counts, record link", async () => {
  setAdapter(
    stub({
      adminLog: async () =>
        log({
          totalMatching: 5,
          events: [
            ev({
              type: "run_unfinished",
              outcome: "unknown",
              actor: "alice",
              actorAssurance: "local-os-user (not verified)",
              detail: "No completion recorded",
            }),
            ev({
              type: "run_finished",
              outcome: "failed",
              actor: null,
              actorAssurance: "system",
            }),
          ],
        }),
    }),
  );
  render(<App />);
  await signIn();
  const rows = await screen.findAllByRole("listitem", { name: /event/i });
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("alice");
  expect(rows[0]).toHaveTextContent(/not verified/i);
  expect(rows[0]).toHaveTextContent(/outcome: unknown/i);
  expect(rows[0]).toHaveTextContent(/not the same as failed|not failed/i);
  expect(rows[1]).toHaveTextContent(/outcome: failed/i);
  expect(rows[1]).not.toHaveTextContent(/not the same as failed/i);
  expect(rows[1]).toHaveTextContent(/system/i);
  expect(screen.getByText(/showing 2 of 5/i)).toBeInTheDocument();
  expect(screen.getByText(/test limitation text/)).toBeInTheDocument();
  expect(screen.getByText(/test limitation two/)).toBeInTheDocument();
  const link = within(rows[0]).getByRole("link", { name: /timeline/i });
  expect(link).toHaveAttribute("href", "#/admin/records/rec_1");
});

test("log: an empty result is not claimed to mean nothing happened", async () => {
  setAdapter(
    stub({ adminLog: async () => log({ events: [], totalMatching: 0 }) }),
  );
  render(<App />);
  await signIn();
  expect(await screen.findByText(/no events match/i)).toBeInTheDocument();
  expect(screen.getByText(/test limitation text/)).toBeInTheDocument();
});

test("filters: engineer, resource, outcome, since and until (UTC) are passed to the backend", async () => {
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => log());
  setAdapter(stub({ adminLog }));
  render(<App />);
  await signIn();
  await screen.findByText(/webhook fixed upstream/);
  fireEvent.change(screen.getByLabelText(/engineer/i), {
    target: { value: "Dana (demo)" },
  });
  fireEvent.change(screen.getByLabelText(/resource/i), {
    target: { value: "digitalocean_firewall.demo" },
  });
  fireEvent.change(screen.getByLabelText(/outcome/i), {
    target: { value: "unknown" },
  });
  fireEvent.change(screen.getByLabelText(/^from/i), {
    target: { value: "2026-11-08T03:00" },
  });
  fireEvent.change(screen.getByLabelText(/^to/i), {
    target: { value: "2026-11-08T04:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: /apply filters/i }));
  await waitFor(() => expect(adminLog).toHaveBeenCalledTimes(2));
  expect(adminLog.mock.calls[1]).toEqual([
    "s3cret",
    {
      engineer: "Dana (demo)",
      resource: "digitalocean_firewall.demo",
      outcome: "unknown",
      since: "2026-11-08T03:00:00Z",
      until: "2026-11-08T04:00:00Z",
    },
  ]);
});

test("filters: blank fields are omitted, and the first call has no filters", async () => {
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => log());
  setAdapter(stub({ adminLog }));
  render(<App />);
  await signIn();
  await screen.findByText(/webhook fixed upstream/);
  expect(adminLog.mock.calls[0]).toEqual(["s3cret", {}]);
});

test("timeline: oldest first, gaps and unknown outcome visible, limitations shown, back link", async () => {
  window.location.hash = "#/admin/records/rec_1";
  const adminTimeline = vi.fn(async () => timeline());
  setAdapter(stub({ adminTimeline }));
  render(<App />);
  // direct navigation to a timeline still requires the token
  expect(adminTimeline).not.toHaveBeenCalled();
  await signIn("tok");
  await screen.findByText(/port 8443 added/);
  expect(adminTimeline).toHaveBeenCalledWith("tok", "rec_1");
  const items = screen.getAllByRole("listitem", { name: /event/i });
  expect(items.map((i) => i.textContent)).toEqual([
    expect.stringContaining("port 8443 added"),
    expect.stringContaining("opened for webhook"),
    expect.stringContaining("No completion recorded"),
  ]);
  expect(items[2]).toHaveTextContent(/outcome: unknown/i);
  const gaps = screen.getByRole("region", { name: /gaps/i });
  expect(gaps).toHaveTextContent(/no keep\/revert\/defer decision/i);
  expect(gaps).toHaveTextContent(/do not assume it succeeded/i);
  expect(screen.getByText(/test limitation text/)).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /back to (the )?log/i }),
  ).toHaveAttribute("href", "#/admin");
});

test("timeline: no gaps says what absence of gaps does and does not mean", async () => {
  window.location.hash = "#/admin/records/rec_1";
  setAdapter(stub({ adminTimeline: async () => timeline({ gaps: [] }) }));
  render(<App />);
  await signIn();
  await screen.findByText(/port 8443 added/);
  expect(screen.queryByRole("region", { name: /gaps/i })).toBeNull();
});

test("timeline 404 is 'not found', not an empty history", async () => {
  window.location.hash = "#/admin/records/nope";
  setAdapter(
    stub({
      adminTimeline: async () => {
        throw new ApiError("Record not found", 404, "not_found");
      },
    }),
  );
  render(<App />);
  await signIn();
  expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
});

test("the token is kept only in memory: it survives navigation between admin pages", async () => {
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => log());
  const adminTimeline = vi.fn(async () => timeline());
  setAdapter(stub({ adminLog, adminTimeline }));
  render(<App />);
  await signIn("tok");
  await screen.findByText(/webhook fixed upstream/);
  fireEvent.click(screen.getByRole("link", { name: /timeline/i }));
  await screen.findByText(/port 8443 added/);
  expect(screen.queryByLabelText(/admin token/i)).toBeNull();
  expect(adminTimeline).toHaveBeenCalledWith("tok", "rec_1");
});

test("a sign-out control forgets the token", async () => {
  setAdapter(stub({}));
  render(<App />);
  await signIn();
  await screen.findByText(/webhook fixed upstream/);
  fireEvent.click(screen.getByRole("button", { name: /sign out|lock/i }));
  expect(screen.getByLabelText(/admin token/i)).toBeInTheDocument();
  expect(screen.queryByText(/webhook fixed upstream/)).toBeNull();
});

test("real adapter: bearer header, filters in query, token never in URL; timeline path is encoded", async () => {
  const calls: { url: string; headers: Record<string, string> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, headers: init?.headers as Record<string, string> });
      const body = url.includes("/timeline")
        ? { record_id: "r/1", events: [], gaps: [], limitations: [] }
        : { events: [], total_matching: 0, limitations: [] };
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  await api.adminLog("tok123", {
    engineer: "A B",
    outcome: "unknown",
    since: "2026-11-08T03:00:00Z",
  });
  await api.adminTimeline("tok123", "r/1");
  expect(calls[0].url.startsWith("/api/admin/log?")).toBe(true);
  const q = new URL(calls[0].url, "http://x").searchParams;
  expect(q.get("engineer")).toBe("A B");
  expect(q.get("outcome")).toBe("unknown");
  expect(q.get("since")).toBe("2026-11-08T03:00:00Z");
  expect(q.get("resource")).toBeNull();
  expect(calls[0].headers.Authorization).toBe("Bearer tok123");
  expect(calls[1].url).toBe("/api/admin/records/r%2F1/timeline");
  expect(calls[1].headers.Authorization).toBe("Bearer tok123");
  for (const c of calls) expect(c.url).not.toContain("tok123");
});

test("the employee page shows no admin navigation and never reads the admin log", async () => {
  window.location.hash = "#/";
  const adminLog = vi.fn(async () => log());
  setAdapter(stub({ adminLog }));
  render(<App />);
  await screen.findByRole("heading", { name: "Manual changes" });
  expect(screen.queryByRole("link", { name: /admin/i })).toBeNull();
  expect(adminLog).not.toHaveBeenCalled();
});

const count = (haystack: string, needle: string) => haystack.split(needle).length - 1;

test("a finished run states its outcome once: the backend's 'outcome: X' detail prefix is not repeated", async () => {
  setAdapter(
    stub({
      adminLog: async () =>
        log({
          events: [
            ev({ type: "run_finished", outcome: "kept", detail: "outcome: kept" }),
            ev({ type: "run_finished", outcome: "failed", detail: "outcome: failed — terraform exited 1" }),
            ev({
              type: "run_finished",
              outcome: "cancelled",
              detail: "outcome: cancelled (from the stored record; predates event history)",
            }),
          ],
          totalMatching: 3,
        }),
    }),
  );
  render(<App />);
  await signIn();
  const rows = await screen.findAllByRole("listitem", { name: /event/i });
  expect(count(rows[0].textContent!, "outcome: kept")).toBe(1);
  // the human note after the prefix is kept
  expect(count(rows[1].textContent!, "outcome: failed")).toBe(1);
  expect(rows[1]).toHaveTextContent("terraform exited 1");
  // exactly the note: no dangling separator left behind
  expect(rows[1].querySelector(".msg")!.textContent).toBe("terraform exited 1");
  // the legacy label is evidence about data quality and must survive
  expect(count(rows[2].textContent!, "outcome: cancelled")).toBe(1);
  expect(rows[2]).toHaveTextContent("predates event history");
});

test("an unfinished run keeps its explanation text and shows 'outcome: unknown' once", async () => {
  setAdapter(
    stub({
      adminLog: async () =>
        log({
          events: [ev({ type: "run_unfinished", outcome: "unknown", detail: "No completion recorded; the run may have been interrupted." })],
        }),
    }),
  );
  render(<App />);
  await signIn();
  const row = (await screen.findAllByRole("listitem", { name: /event/i }))[0];
  expect(count(row.textContent!, "outcome: unknown")).toBe(1);
  expect(row).toHaveTextContent("may have been interrupted");
});

test("a detail that merely mentions the outcome elsewhere (not as its prefix) is not altered", async () => {
  setAdapter(stub({ adminLog: async () => log({ events: [ev({ type: "run_finished", outcome: "kept", detail: "retry after outcome: kept earlier" })] }) }));
  render(<App />);
  await signIn();
  expect((await screen.findAllByRole("listitem", { name: /event/i }))[0]).toHaveTextContent("retry after outcome: kept earlier");
});
