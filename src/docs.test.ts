// DOC CONTRACT tests. The PRD (docs/Break-Glass Handoff — PRD.md) is the source
// of truth. README/PROJECT must not describe the pre-pivot scaffold, must link
// the real docs, and must not overstate verification (PRD §8 "Enforcement and
// honesty", §9 "not executed verification").
import { expect, test } from "vitest";
import readme from "../README.md?raw";
import project from "../docs/PROJECT.md?raw";

const both = { README: readme, PROJECT: project };

test.each(Object.entries(both))("%s names the actual product", (_n, text) => {
  expect(text).toContain("Break-Glass Handoff");
});

test.each([
  "makes no API calls",
  "four component tests",
  "No backend framework",
  "No simulated cluster metrics or API calls",
  "Frontend shell has workspace, browser-local challenge notes",
  "Nothing is publicly deployed",
  "Official challenge pending",
  "challenge notes",
])("README/PROJECT no longer contain stale scaffold claim: %s", (stale) => {
  expect(readme).not.toContain(stale);
  expect(project).not.toContain(stale);
});

test("README links the PRD and the backend, API and frontend docs", () => {
  for (const f of ["API.md", "BACKEND.md", "FRONTEND.md"]) {
    expect(readme).toContain(`docs/${f}`);
  }
  expect(readme).toMatch(/Break-Glass(%20| )Handoff(%20| )(—|%E2%80%94)(%20| )PRD\.md/);
});

test("README explains how to run backend and frontend together", () => {
  expect(readme).toMatch(/uvicorn breakglass\.api:app/);
  expect(readme).toMatch(/npm run dev/);
  expect(readme).toMatch(/seed-demo/);
});

test("README states the UI is read-only and never runs Terraform", () => {
  expect(readme).toMatch(/never runs Terraform/i);
});

test("README is honest about what is NOT verified", () => {
  expect(readme).toMatch(/not (yet )?provisioned/i);
  expect(readme).toMatch(/authored fixtures?|hand-written/i);
  expect(readme).toMatch(/real Terraform/i);
});

test("README does not claim the admin dashboard or analytics exist (PRD R9, §7)", () => {
  expect(readme).toMatch(/admin dashboard[^.]*not (yet )?(built|implemented)/i);
  expect(readme).toMatch(/analytics[^.]*(not (yet )?(built|implemented)|proposed)/i);
});

test("PROJECT.md records the break-glass decisions and the real next gate", () => {
  expect(project).toMatch(/Terraform/);
  expect(project).toMatch(/SQLite/);
  expect(project).toMatch(/FastAPI/);
  expect(project).toMatch(/spike/i);
});

test("PROJECT.md points at the PRD as source of truth", () => {
  expect(project).toMatch(/source of truth/i);
  expect(project).toContain("Break-Glass Handoff — PRD.md");
});
