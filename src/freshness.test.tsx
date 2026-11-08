// @vitest-environment jsdom
import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { Freshness } from "./components/Freshness";

afterEach(cleanup);
const ok = { status: "ok", db: "ok", environment: "demo", time: "" };

test("healthy backend and no stale records: no banner", () => {
  const { container } = render(<Freshness health={ok} records={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("a degraded backend is stated with its db status", () => {
  render(<Freshness health={{ ...ok, status: "degraded", db: "down" }} records={[]} />);
  expect(screen.getByText(/Backend health is/)).toHaveTextContent('"degraded" (db: down)');
});

test("no health at all is stated as unreachable, not as fine", () => {
  render(<Freshness health={null} records={[]} />);
  expect(screen.getByText(/unreachable/)).toBeInTheDocument();
});
