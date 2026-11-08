// @vitest-environment jsdom
// Role detection via GET /api/me. Stub adapter / stubbed fetch; not backend integration.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { api, fromWireMe, setAdapter, setTokenProvider } from "./api";
import type { Adapter, Me } from "./api";
import { fixtureAdapter } from "./fixtures";

const me = (o: Partial<Me> = {}): Me => ({
  signedIn: true,
  email: "dana@example.com",
  displayName: "Dana",
  role: "employee",
  authMode: "firebase",
  ...o,
});

function stub(meFn: Adapter["me"]): Adapter {
  return {
    ...fixtureAdapter,
    me: meFn,
    listRecords: async () => ({ records: [], health: null }),
  };
}
beforeEach(() => (window.location.hash = "#/"));
afterEach(() => {
  cleanup();
  setAdapter(null);
  setTokenProvider(null);
  vi.unstubAllGlobals();
});

test("wire mapping: /api/me", () => {
  expect(
    fromWireMe({
      signed_in: true,
      email: "a@b.c",
      display_name: "A",
      role: "admin",
      auth_mode: "firebase",
    }),
  ).toEqual({
    signedIn: true,
    email: "a@b.c",
    displayName: "A",
    role: "admin",
    authMode: "firebase",
  });
  expect(
    fromWireMe({ signed_in: false, role: null, auth_mode: "none" }),
  ).toMatchObject({ signedIn: false, email: null, role: null });
  // an unknown role string is never trusted as admin
  expect(fromWireMe({ signed_in: true, role: "root", auth_mode: "x" }).role).toBeNull();
});

test("api.me() calls /api/me with the ID token as a Bearer header, never in the URL", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify({
          signed_in: true,
          email: "a@b.c",
          display_name: null,
          role: "admin",
          auth_mode: "firebase",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
  setTokenProvider(async () => "idtok-me");
  const r = await api.me();
  expect(r.role).toBe("admin");
  expect(calls[0].url).toBe("/api/me");
  const headers = (calls[0].init?.headers ?? {}) as Record<string, string>;
  expect(headers.Authorization).toBe("Bearer idtok-me");
});

test("an admin sees a link to the admin area; the page itself still loads", async () => {
  setAdapter(stub(async () => me({ role: "admin" })));
  render(<App />);
  expect(await screen.findByRole("link", { name: "Admin" })).toHaveAttribute(
    "href",
    "#/admin",
  );
  expect(screen.getByRole("heading", { name: "Manual changes" })).toBeInTheDocument();
});

test.each([
  ["employee", me()],
  ["not signed in", me({ signedIn: false, role: null, email: null })],
])("%s: no admin link", async (_n, who) => {
  const fn = vi.fn(async () => who);
  setAdapter(stub(fn));
  render(<App />);
  await screen.findByRole("heading", { name: "Manual changes" });
  await waitFor(() => expect(fn).toHaveBeenCalled());
  expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
});

test("if /api/me fails the page still loads and no admin link appears", async () => {
  const fn = vi.fn(async () => {
    throw new Error("down");
  });
  setAdapter(stub(fn));
  render(<App />);
  await screen.findByRole("heading", { name: "Manual changes" });
  await waitFor(() => expect(fn).toHaveBeenCalled());
  expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
});
