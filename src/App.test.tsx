// @vitest-environment jsdom
import { afterEach, expect, test } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
afterEach(() => {
  cleanup();
  localStorage.clear();
});
test("starts with honest disconnected workspace", () => {
  render(<App />);
  expect(
    screen.getByRole("heading", { name: /Big infrastructure/ }),
  ).toBeInTheDocument();
  expect(screen.getByText("NOT CONNECTED")).toBeInTheDocument();
  expect(screen.getByText("UNCONFIRMED HINT")).toBeInTheDocument();
});
test("challenge notes persist across remounts", () => {
  const app = render(<App />);
  fireEvent.click(
    screen.getByRole("button", { name: /Capture the challenge/ }),
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Official criteria go here" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Save notes/ }));
  expect(screen.getByRole("status")).toHaveTextContent("Saved in this browser");
  app.unmount();
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /Challenge brief/ }));
  expect(screen.getByRole("textbox")).toHaveValue("Official criteria go here");
});
test("team navigation works", () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /^.*Meet the team/ }));
  for (const name of ["Daniel", "Samuel", "Andrew"])
    expect(screen.getByRole("heading", { name })).toBeInTheDocument();
});
test("storage failure is reported rather than claiming success", () => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("Blocked");
  };
  try {
    render(<App />);
    fireEvent.click(
      screen.getByRole("button", { name: /Capture the challenge/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Save notes/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Could not save");
  } finally {
    Storage.prototype.setItem = original;
  }
});
