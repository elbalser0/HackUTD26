// DOC CONTRACT tests. The PRD (docs/Break-Glass Handoff — PRD.md) is the source
// of truth. README/PROJECT must not describe the pre-pivot scaffold, must link
// the real docs, and must not overstate verification (PRD §8 "Enforcement and
// honesty", §9 "not executed verification").
import { expect, test } from "vitest";
import readme from "../README.md?raw";
import project from "../docs/PROJECT.md?raw";
import ci from "../.github/workflows/ci.yml?raw";

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
  "infra/demo",
  "Not provisioned",
  "not provisioned",
  "Real Terraform spike** | n/a | **Pending",
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
  expect(readme).toMatch(/authored fixtures?|hand-written/i);
  expect(readme).toMatch(/real Terraform/i);
});

test("README and PROJECT point at break-glass-infra and describe the partial spike", () => {
  for (const t of [readme, project]) {
    expect(t).toContain("break-glass-infra");
    expect(t).toMatch(/partial/i);
  }
  expect(readme).toMatch(/applied/i);
  expect(readme).toMatch(/not attached/i);
});

test("README says the admin log API exists but the dashboard UI is not built (PRD R9)", () => {
  expect(readme).toMatch(/admin log API/i);
  expect(readme).toContain("BG_ADMIN_TOKEN");
  expect(readme).toMatch(/admin dashboard UI[^.]*not (yet )?(built|implemented)/i);
  expect(readme).toMatch(/analytics[^.]*(not (yet )?(built|implemented)|proposed)/i);
});

test("PROJECT.md status matches the code: R6-R8 no longer listed as open gaps; R9 limits stated", () => {
  expect(project).not.toMatch(/in progress/i);
  expect(project).not.toMatch(/last report wins/i);
  expect(project).toMatch(/shared (admin )?token/i);
  expect(project).toMatch(/not verified|unverified/i);
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

// ---- CI contract: the backend suite must run in CI, offline and without secrets ----

test("CI runs the backend pytest suite on the supported Python", () => {
  expect(ci).toMatch(/python-version:\s*["']?3\.12/);
  expect(ci).toContain('pip install -e ".[dev]"');
  expect(ci).toMatch(/python -m pytest -q/);
  expect(ci).toMatch(/working-directory:\s*backend/);
});

test("CI backend job stays offline and keeps the frontend job", () => {
  expect(ci).toMatch(/npm test/);
  expect(ci).not.toMatch(/secrets\./i);
  expect(ci).not.toMatch(/DIGITALOCEAN|terraform (apply|plan)|BG_ADMIN_TOKEN/i);
});
