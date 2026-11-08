// @vitest-environment jsdom
import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { ApiError } from "./api";
import { ErrorState } from "./components/States";

afterEach(cleanup);

// Seen against the real API (503 storage_unavailable): the heading and the message both said it.
test("an unavailable backend is named once, not 'Backend unavailable. Backend unavailable.'", () => {
  render(<ErrorState error={new ApiError("Backend unavailable", 503, "storage_unavailable")} />);
  const text = screen.getByRole("alert").textContent ?? "";
  expect(text.match(/Backend unavailable/g)).toHaveLength(1);
  expect(text).toMatch(/Nothing here should be read as “no changes”/);
});

test("other errors keep their own message after the heading", () => {
  render(<ErrorState error={new ApiError("Request failed (500)", 500)} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Could not load. Request failed (500).");
});

test("an unreachable backend with its own detail still shows that detail", () => {
  render(<ErrorState error={new ApiError("proxy timed out", 504)} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Backend unavailable. proxy timed out.");
});
