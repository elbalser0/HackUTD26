// @vitest-environment jsdom
// Google sign-in (Firebase) UI. A FAKE AuthClient stands in for Firebase; no
// network, no real Google account. Wire tests stub fetch to check headers.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { ApiError, api, setAdapter, setTokenProvider } from "./api";
import type { Adapter, AdminFilters, EmergencyRecord, Health } from "./api";
import { setAuthClient } from "./auth";
import type { AuthClient, AuthUser } from "./auth";

const DANA: AuthUser = { email: "dana@example.com", name: "Dana" };

function fakeAuth(start: AuthUser | null = null) {
  let user = start;
  let n = 0;
  const subs = new Set<(u: AuthUser | null) => void>();
  const emit = () => subs.forEach((f) => f(user));
  const client: AuthClient & {
    signIn: ReturnType<typeof vi.fn>;
    signOut: ReturnType<typeof vi.fn>;
    getIdToken: ReturnType<typeof vi.fn>;
  } = {
    onChange(cb) {
      subs.add(cb);
      cb(user);
      return () => {
        subs.delete(cb);
      };
    },
    signIn: vi.fn(async () => {
      user = DANA;
      emit();
    }),
    signOut: vi.fn(async () => {
      user = null;
      emit();
    }),
    getIdToken: vi.fn(async () => (user ? `idtok-${++n}` : null)),
  };
  return client;
}

const rec = (o: Partial<EmergencyRecord> = {}): EmergencyRecord => ({
  id: "r1",
  environment: "demo",
  resourceAddress: "digitalocean_firewall.demo",
  attribute: "inbound_rule",
  changeKind: "added",
  baseline: null,
  observed: {
    protocol: "tcp",
    portRange: "8443",
    sourceAddresses: ["0.0.0.0/0"],
    sourceTags: [],
    sourceDropletIds: [],
    sourceLoadBalancerUids: [],
    sourceKubernetesIds: [],
  },
  summary: "added live: inbound tcp port 8443 from 0.0.0.0/0",
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
  lastCheckAt: "2026-11-08T03:45:02.000000Z",
  evidenceSource: "terraform-refresh-only",
  ...o,
});
const health = (signIn = false): Health => ({
  status: "ok",
  db: "ok",
  environment: "demo",
  time: "2026-11-08T03:30:00Z",
  auth: {
    writesRequireSignIn: signIn,
    adminViaFirebase: signIn,
    adminViaSharedToken: true,
  },
});
function stub(o: Partial<Adapter> = {}): Adapter {
  return {
    listRecords: async () => ({ records: [rec()], health: health() }),
    getRecord: async () => rec(),
    report: async (_i, b) => rec({ reporter: b.reporter, reason: b.reason }),
    decide: async (_i, intent) => rec({ intent }),
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

beforeEach(() => {
  window.location.hash = "#/";
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  setAdapter(null);
  setAuthClient(undefined);
  setTokenProvider(null);
  vi.unstubAllGlobals();
});

// ---- configuration --------------------------------------------------------

test("not configured: no sign-in UI at all", async () => {
  setAuthClient(null);
  setAdapter(stub());
  render(<App />);
  await screen.findByRole("region", { name: "digitalocean_firewall.demo" });
  expect(screen.queryByRole("button", { name: /sign in with google/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /sign out/i })).toBeNull();
});

// ---- sign in / out --------------------------------------------------------

test("configured and signed out: a full sign-in page, and no app data is loaded", async () => {
  const auth = fakeAuth();
  setAuthClient(auth);
  const listRecords = vi.fn(async () => ({ records: [rec()], health: health(true) }));
  setAdapter(stub({ listRecords }));
  render(<App />);
  expect(screen.getByRole("heading", { name: /manual changes/i })).toBeInTheDocument();
  expect(screen.queryByText("digitalocean_firewall.demo")).toBeNull();
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(listRecords).not.toHaveBeenCalled();
});

test("the sign-in page shows the Argus logo, not the old B² text mark", () => {
  setAuthClient(fakeAuth());
  setAdapter(stub());
  const { container } = render(<App />);
  const logo = screen.getByRole("img", { name: "Argus" });
  expect(logo).toHaveAttribute("src", "/argus-logo.svg");
  expect(container.querySelector(".signin-page")).toContainElement(logo);
  expect(container.textContent).not.toContain("B²");
  // the lockup already spells the name, so no second ARGUS label under it
  expect(container.querySelector(".signin-card .eyebrow")).toBeNull();
});

test("signing in from the sign-in page opens the app with the account bar", async () => {
  const auth = fakeAuth();
  setAuthClient(auth);
  setAdapter(stub());
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /sign in with google/i }));
  expect(auth.signIn).toHaveBeenCalledTimes(1);
  expect(
    await screen.findByRole("region", { name: "digitalocean_firewall.demo" }),
  ).toBeInTheDocument();
  expect(screen.getByText("dana@example.com")).toBeInTheDocument();
  expect(screen.queryByText(/verified google account/i)).toBeNull();
});

test("while Firebase restores the session: a checking state, not the sign-in page", () => {
  setAuthClient({
    onChange: () => () => {},
    signIn: async () => {},
    signOut: async () => {},
    getIdToken: async () => null,
  });
  setAdapter(stub());
  render(<App />);
  expect(screen.getByRole("status")).toHaveTextContent(/checking sign-in/i);
  expect(screen.queryByRole("button", { name: /sign in with google/i })).toBeNull();
});

const openAccountMenu = () =>
  fireEvent.click(screen.getByRole("button", { name: /account menu/i }));

test("signed in: one account button shows name and email, with no verified badge and no sign-out until opened", () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(stub());
  render(<App />);
  const trigger = screen.getByRole("button", { name: /account menu/i });
  expect(trigger).toHaveTextContent("Dana");
  expect(trigger).toHaveTextContent("dana@example.com");
  expect(trigger).toHaveAttribute("aria-haspopup", "menu");
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText(/verified google account/i)).toBeNull();
  expect(screen.queryByRole("button", { name: /^sign out$/i })).toBeNull();
});

test("signed in: opening the account button drops down Sign out, which returns to the sign-in page", async () => {
  const auth = fakeAuth(DANA);
  setAuthClient(auth);
  setAdapter(stub());
  render(<App />);
  openAccountMenu();
  expect(screen.getByRole("button", { name: /account menu/i })).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("menuitem", { name: /^sign out$/i }));
  expect(auth.signOut).toHaveBeenCalledTimes(1);
  expect(
    await screen.findByRole("button", { name: /sign in with google/i }),
  ).toBeInTheDocument();
  expect(screen.queryByText("digitalocean_firewall.demo")).toBeNull();
});

test("account menu closes on a second click, on Escape (returning focus), and on an outside click", () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(stub());
  render(<App />);
  const trigger = screen.getByRole("button", { name: /account menu/i });
  const signOut = () => screen.queryByRole("menuitem", { name: /^sign out$/i });
  fireEvent.click(trigger);
  expect(signOut()).not.toBeNull();
  fireEvent.click(trigger);
  expect(signOut()).toBeNull();
  fireEvent.click(trigger);
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  expect(signOut()).toBeNull();
  expect(trigger).toHaveFocus();
  fireEvent.click(trigger);
  fireEvent.mouseDown(document.body);
  expect(signOut()).toBeNull();
});

test("clicking inside the open menu does not count as an outside click", () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(stub());
  render(<App />);
  openAccountMenu();
  fireEvent.mouseDown(screen.getByRole("menu"));
  expect(screen.queryByRole("menuitem", { name: /^sign out$/i })).not.toBeNull();
});

test("sign-in errors are explained (blocked popup)", async () => {
  const auth = fakeAuth();
  auth.signIn.mockRejectedValueOnce(new Error("Firebase: Error (auth/popup-blocked)."));
  setAuthClient(auth);
  setAdapter(stub());
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /sign in with google/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/blocked the google popup/i);
});

test("offline admin access: the shared-token admin page is reachable without Google", async () => {
  setAuthClient(fakeAuth());
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => ({ events: [], totalMatching: 0, limitations: [] }));
  setAdapter(stub({ adminLog }));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /admin offline access/i }));
  fireEvent.change(await screen.findByLabelText(/admin token/i), { target: { value: "shared-secret" } });
  fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
  await waitFor(() => expect(adminLog).toHaveBeenCalled());
  expect(adminLog.mock.calls[0][0]).toBe("shared-secret");
  expect(screen.getByText(/not signed in/i)).toBeInTheDocument();
});

test("list: hint to sign in when the server requires it and nobody is signed in (offline mode)", async () => {
  setAuthClient(fakeAuth());
  setAdapter(
    stub({ listRecords: async () => ({ records: [rec()], health: health(true) }) }),
  );
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /admin offline access/i }));
  window.location.hash = "#/";
  expect(
    await screen.findByText(/sign in with google to add explanations/i),
  ).toBeInTheDocument();
});

// ---- report form ----------------------------------------------------------

test("report form: says which verified account will save it", async () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(stub());
  window.location.hash = "#/records/r1";
  render(<App />);
  const line = await screen.findByText(/^Saving as dana@example\.com/);
  expect(line).toHaveTextContent(/not who made the change/i);
});

test("401 on report (expired sign-in): asks to sign in again and keeps the text", async () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(
    stub({
      report: async () => {
        throw new ApiError("sign-in required", 401, "sign_in_required");
      },
    }),
  );
  window.location.hash = "#/records/r1";
  render(<App />);
  const box = await screen.findByLabelText(/what did you change and why/i);
  fireEvent.change(box, { target: { value: "opened 8443 for the webhook" } });
  fireEvent.click(screen.getByRole("button", { name: /save report/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/sign in .*again/i);
  expect(box).toHaveValue("opened 8443 for the webhook");
});

test("403 email_unverified on report: explains it", async () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(
    stub({
      report: async () => {
        throw new ApiError("a verified email is required", 403, "email_unverified");
      },
    }),
  );
  window.location.hash = "#/records/r1";
  render(<App />);
  fireEvent.change(await screen.findByLabelText(/what did you change and why/i), {
    target: { value: "x" },
  });
  fireEvent.click(screen.getByRole("button", { name: /save report/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/email isn.t verified/i);
});

// ---- wire: Authorization header, fresh token per request -------------------

function fetchStub() {
  const calls: { url: string; init?: RequestInit }[] = [];
  const body = {
    id: "r1",
    environment: "demo",
    resource_address: "digitalocean_firewall.demo",
    attribute: "inbound_rule",
    change_kind: "added",
    baseline_value: null,
    observed_value: null,
    summary: "s",
    first_detected_at: "t",
    last_detected_at: "t",
    intent: "unset",
    resolution: "open",
    last_check_status: "current",
    evidence_source: "terraform-refresh-only",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}
const authHeader = (c: { init?: RequestInit }) =>
  new Headers(c.init?.headers).get("Authorization");

test("writes send a fresh Firebase ID token as a Bearer header, never in the URL", async () => {
  const calls = fetchStub();
  let n = 0;
  setTokenProvider(async () => `idtok-${++n}`);
  await api.report("r1", { reporter: null, reason: "x" });
  await api.decide("r1", "keep");
  expect(calls.map(authHeader)).toEqual(["Bearer idtok-1", "Bearer idtok-2"]);
  expect(calls.every((c) => !c.url.includes("idtok"))).toBe(true);
});

test("reads send the ID token too (the server requires sign-in for reads), never in the URL", async () => {
  const calls = fetchStub();
  let n = 0;
  setTokenProvider(async () => `idtok-read-${++n}`);
  await api.getRecord("r1");
  await api.getApplyRun("r1");
  const records = calls.filter((c) => c.url.startsWith("/api/records"));
  expect(records.map(authHeader)).toEqual(["Bearer idtok-read-1"]);
  expect(calls.map(authHeader)).toContain("Bearer idtok-read-2");
  expect(calls.every((c) => !c.url.includes("idtok"))).toBe(true);
});

test("listRecords sends the ID token on the records read but not on the open health check", async () => {
  const calls = fetchStub();
  setTokenProvider(async () => "idtok-list");
  await api.listRecords();
  const rec = calls.find((c) => c.url.startsWith("/api/records"));
  const health = calls.find((c) => c.url.startsWith("/api/health"));
  expect(rec && authHeader(rec)).toBe("Bearer idtok-list");
  expect(health && authHeader(health)).toBeNull();
});

test("a record's history read sends the ID token, never in the URL", async () => {
  const calls = fetchStub();
  setTokenProvider(async () => "idtok-events");
  await api.recordEvents("r1");
  const c = calls.find((x) => x.url.startsWith("/api/records/r1/events"));
  expect(c && authHeader(c)).toBe("Bearer idtok-events");
  expect(calls.every((x) => !x.url.includes("idtok"))).toBe(true);
});

test("signed out (no token): reads send no Authorization header", async () => {
  const calls = fetchStub();
  setTokenProvider(async () => null);
  await api.getRecord("r1");
  expect(authHeader(calls[0])).toBeNull();
});

test("signed out (no token): writes send no Authorization header", async () => {
  const calls = fetchStub();
  setTokenProvider(async () => null);
  await api.report("r1", { reporter: null, reason: "x" });
  expect(authHeader(calls[0])).toBeNull();
});

test("the app wires the signed-in user's token into writes", async () => {
  const calls = fetchStub();
  const auth = fakeAuth(DANA);
  setAuthClient(auth);
  render(<App />);
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  await api.report("r1", { reporter: null, reason: "x" });
  const post = calls.find((c) => c.init?.method === "POST");
  expect(authHeader(post!)).toMatch(/^Bearer idtok-\d+$/);
  expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("idtok");
});

test("the app's wiring fetches a NEW token for every write (never caches one)", async () => {
  const calls = fetchStub();
  const auth = fakeAuth(DANA);
  setAuthClient(auth);
  render(<App />);
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  const before = auth.getIdToken.mock.calls.length; // the initial records read also asks for a token
  await api.report("r1", { reporter: null, reason: "first" });
  await api.decide("r1", "keep");
  const posts = calls.filter((c) => c.init?.method === "POST").map(authHeader);
  expect(posts).toHaveLength(2);
  expect(new Set(posts).size).toBe(2);
  expect(auth.getIdToken.mock.calls.length - before).toBe(2);
});

// ---- admin page ---------------------------------------------------------------

test("admin: continue as the signed-in Google account, fresh token per call", async () => {
  const auth = fakeAuth(DANA);
  setAuthClient(auth);
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => ({ events: [], totalMatching: 0, limitations: [] }));
  setAdapter(stub({ adminLog }));
  window.location.hash = "#/admin";
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: /continue as dana@example\.com/i }),
  );
  await waitFor(() => expect(adminLog).toHaveBeenCalled());
  expect(adminLog.mock.calls[0][0]).toMatch(/^idtok-\d+$/);
  expect(auth.getIdToken).toHaveBeenCalled();
});

test("admin: a signed-in non-admin is told so (not 'not configured')", async () => {
  setAuthClient(fakeAuth(DANA));
  setAdapter(
    stub({
      adminLog: async () => {
        throw new ApiError("this account is not an admin", 403, "not_admin");
      },
    }),
  );
  window.location.hash = "#/admin";
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: /continue as dana@example\.com/i }),
  );
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(/not an admin/i);
  expect(alert).not.toHaveTextContent(/not configured/i);
});

test("admin: shared-token fallback is still offered and works", async () => {
  setAuthClient(fakeAuth(DANA));
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => ({ events: [], totalMatching: 0, limitations: [] }));
  setAdapter(stub({ adminLog }));
  window.location.hash = "#/admin";
  render(<App />);
  expect(await screen.findByRole("heading", { name: /offline fallback/i })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/admin token/i), {
    target: { value: "shared-secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
  await waitFor(() => expect(adminLog).toHaveBeenCalled());
  expect(adminLog.mock.calls[0][0]).toBe("shared-secret");
});

test("admin: signing out leaves the admin view for the sign-in page", async () => {
  const auth = fakeAuth(DANA);
  setAuthClient(auth);
  const adminLog = vi.fn(async (_t: string, _f: AdminFilters) => ({ events: [], totalMatching: 0, limitations: [] }));
  setAdapter(stub({ adminLog }));
  window.location.hash = "#/admin";
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: /continue as dana@example.com/i }),
  );
  await waitFor(() => expect(adminLog).toHaveBeenCalled());
  openAccountMenu();
  fireEvent.click(screen.getByRole("menuitem", { name: /^sign out$/i }));
  expect(await screen.findByRole("button", { name: /sign in with google/i })).toBeInTheDocument();
  expect(screen.queryByText(/admin log/i, { selector: ".eyebrow" })).toBeNull();
});
