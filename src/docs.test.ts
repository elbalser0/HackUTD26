// DOC CONTRACT tests. The PRD (docs/Break-Glass Handoff — PRD.md) is the source
// of truth. README/PROJECT must not describe the pre-pivot scaffold, must link
// the real docs, and must not overstate verification (PRD §8 "Enforcement and
// honesty", §9 "not executed verification").
import { expect, test } from "vitest";
import readme from "../README.md?raw";
import project from "../docs/PROJECT.md?raw";
import frontend from "../docs/FRONTEND.md?raw";
import apiDoc from "../docs/API.md?raw";
import backendDoc from "../docs/BACKEND.md?raw";
import adminPy from "../backend/breakglass/admin.py?raw";
import apiPy from "../backend/breakglass/api.py?raw";
import ci from "../.github/workflows/ci.yml?raw";
import handoff from "../docs/HANDOFF.md?raw";

const both = { README: readme, PROJECT: project };

test.each(Object.entries(both))("%s names the actual product", (_n, text) => {
  expect(text).toContain("Argus");
});

// The product is named Argus. Only the PRD *filename* and the infra/CLI identifiers keep the old name.
test.each(["README.md", "docs/API.md", "docs/BACKEND.md", "docs/FRONTEND.md", "docs/HANDOFF.md", "docs/PROJECT.md"])(
  "%s does not call the product Break-Glass",
  (f) => {
    const raw = import.meta.glob("../{README,docs/*}.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const text = raw[`../${f}`];
    expect(text, f).toBeTruthy();
    const prose = text
      .replace(/Break-Glass(%20| )Handoff(%20| )(—|%E2%80%94)(%20| )PRD\.md/g, "")
      .replace(/break-glass-(infra|demo)/g, "")
      .replace(/feat\/break-glass-backend/g, "");
    expect(prose).not.toMatch(/Break-Glass( Handoff)?(?![-\w])/);
  },
);

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

test("README and PROJECT point at break-glass-infra and record the real spike results", () => {
  for (const t of [readme, project]) {
    expect(t).toContain("break-glass-infra");
    expect(t).toMatch(/spike/i);
    expect(t).toContain("fixtures/real");
  }
  expect(readme).toMatch(/applied/i);
  expect(readme).toMatch(/not attached/i);
});

test("docs state what the real spike did NOT cover", () => {
  for (const t of [readme, project]) {
    expect(t).toMatch(/not (yet )?(run|exercised|verified)[^.]*(revert|override)/i);
  }
});

test("docs record the real closure (recheck resolved a real record) and no longer list it as a gap", () => {
  for (const t of [readme, project]) {
    expect(t).toMatch(/recheck[^.]*(resolved|verified_aligned)|(resolved|closed)[^.]*real[^.]*recheck/i);
  }
  expect(project).not.toMatch(/has not been re-run/i);
  expect(readme).not.toMatch(/closing a record with a real `recheck` after the fix/i);
});

test("PROJECT.md no longer calls detection, the pause and closure unverified on real Terraform", () => {
  expect(project).not.toContain("Direction of `before`/`after` unverified");
  expect(project).not.toContain("Never run against real Terraform");
  expect(project).not.toMatch(/R11[^\n]*authored fixtures\./);
  expect(project).toMatch(/null[^.]*empty/i); // the provider-noise finding is recorded
});

test("README says the admin dashboard UI ran against the real backend with a throwaway token, and what was not run live (PRD R9)", () => {
  expect(readme).toMatch(/admin log API/i);
  expect(readme).toContain("BG_ADMIN_TOKEN");
  expect(readme).toMatch(/admin dashboard UI[^|]*\| `src\/components\/AdminShell.tsx`/i);
  expect(readme).not.toMatch(/not yet run against the real backend/i);
  expect(readme).toMatch(/throwaway[^|]*token/i);
  expect(readme).toMatch(/Not yet run live:[^|]*Google[^|]*unknown[^|]*gaps/i);
  expect(readme).not.toMatch(/admin dashboard UI[^|]*\|[^|]*Not built/i);
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

// ---- Agent handoff contract: a fresh agent must be able to start from this file alone ----

test("README links the agent handoff and nothing links the removed spike handoff", () => {
  expect(readme).toContain("docs/HANDOFF.md");
  for (const t of [readme, project, handoff]) expect(t).not.toContain("HANDOFF-terraform-spike");
});

test("handoff names the source of truth and the working rules", () => {
  expect(handoff).toContain("Break-Glass Handoff — PRD.md");
  expect(handoff).toMatch(/never (read|open)[^.\n]*\.env/i);
  expect(handoff).toMatch(/test[- ]first|TDD/i);
  expect(handoff).toMatch(/team approval|explicit approval/i);
  expect(handoff).toMatch(/never[^.\n]*terraform apply/i);
  expect(handoff).toMatch(/only when (the user )?ask/i); // commit/push/merge only on request
});

test("handoff separates what is verified on real Terraform from what is not", () => {
  expect(handoff).toMatch(/verified on real/i);
  expect(handoff).toMatch(/not (yet )?(run|verified|exercised)[^.\n]*(revert|override)/i);
  expect(handoff).toMatch(/H5|keep-path/i);
  expect(handoff).toMatch(/drift-free/i);
});

test("handoff records the live admin dashboard check and what it did not cover", () => {
  const verified = handoff.slice(handoff.indexOf("## What is verified"), handoff.indexOf("## Running things"));
  expect(verified).toMatch(/admin dashboard[^\n]*real backend[^\n]*throwaway/i);
  expect(verified).toMatch(/not (yet )?(seen|run)[^\n]*live[^\n]*unknown[^\n]*gaps/i);
  expect(verified).not.toMatch(/verified with stubs and fixtures only/i);
});

test("FRONTEND.md evidence is current: no stale test count, and the admin dashboard live check is recorded", () => {
  expect(frontend).not.toMatch(/npm test`: 12 passed/);
  expect(frontend).not.toMatch(/not against the real backend/i);
  expect(frontend).toMatch(/admin dashboard[^\n]*real backend[^\n]*throwaway/i);
});

test("handoff lists next steps that name the admin dashboard follow-ups", () => {
  expect(handoff).toMatch(/## Next steps/i);
  expect(handoff).toMatch(/admin dashboard UI/i);
  expect(handoff).toMatch(/BG_ADMIN_TOKEN/);
});

test("handoff carries the practical gotchas that cost time this session", () => {
  expect(handoff).toMatch(/stdin|end-of-input|EOF/i);   // closed stdin = cancel, safe way to show the warning
  expect(handoff).toMatch(/first character|leading space/i); // the `!` shell-mode paste problem
  expect(handoff).toMatch(/python3\.12/);
  expect(handoff).toMatch(/--no-prompt/);
});

test("handoff does not contain secrets or real account values", () => {
  expect(handoff).not.toMatch(/dop_v1_|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?<!0\.0\.0\.0)(?<!127\.0\.0\.1)(?<!203\.0\.113\.10)/);
  expect(handoff).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?<!00000000-0000-4000-8000-000000000001)/);
});

// ---- docs vs code: guards that read the backend source so the reference docs cannot silently lag ----
const backendSources = import.meta.glob("../backend/breakglass/*.py", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

test("BACKEND.md documents every BG_* environment variable the backend reads", () => {
  const used = new Set<string>();
  for (const src of Object.values(backendSources))
    for (const m of src.matchAll(/\bBG_[A-Z][A-Z_]*[A-Z]\b/g)) used.add(m[0]);
  expect(used.size).toBeGreaterThan(8); // the scan itself works
  const missing = [...used].filter((v) => !backendDoc.includes(v));
  expect(missing).toEqual([]);
});

test("API.md has a section heading for every HTTP route in api.py", () => {
  const routes = [...apiPy.matchAll(/@app\.(get|post|put|delete|patch)\("([^"]+)"/g)].map((m) => [m[1].toUpperCase(), m[2]]);
  expect(routes.length).toBeGreaterThanOrEqual(11);
  const norm = (p: string) => p.replace(/\{[a-z_]+\}/g, "{id}");
  const missing = routes.filter(([method, path]) => !apiDoc.includes(`### \`${method} ${norm(path)}`)).map((r) => r.join(" "));
  expect(missing).toEqual([]);
});

test("API.md limitations match what the admin endpoints actually return", () => {
  const section = apiDoc.slice(apiDoc.indexOf("### Limitations"), apiDoc.indexOf("## Deliberately not in the HTTP API"));
  expect(section.length).toBeGreaterThan(100);
  for (const phrase of [
    "Only web actions made while signed in carry a verified account",
    "allowlisted email",
    "shared fallback token",
    "not who made the console change",
  ]) {
    expect(adminPy, `code no longer says: ${phrase}`).toContain(phrase);
    expect(section, `API.md limitations missing: ${phrase}`).toContain(phrase);
  }
  expect(section).not.toMatch(/no per-admin identity/i); // sign-in gives per-admin identity
  expect(section).not.toMatch(/A reporter is self-reported;/); // signed-in web actions are verified
});

// ---- the old B² mark must not survive anywhere ----
const appSources = import.meta.glob(["./**/*.{ts,tsx,css}", "!./**/*.test.*"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

test("no source file still draws the old B² mark", () => {
  expect(Object.keys(appSources).length).toBeGreaterThan(5); // the scan itself works
  const offenders = Object.entries(appSources).filter(([, src]) => /B²|B<span>/.test(src)).map(([f]) => f);
  expect(offenders).toEqual([]);
});

test("the old logo asset is gone and the docs do not describe a B² mark", () => {
  const assets = Object.keys(import.meta.glob("../public/*"));
  expect(assets).not.toContain("../public/hackutd.svg");
  expect(assets).toEqual(expect.arrayContaining(["../public/argus-logo.svg", "../public/argus-mark.svg"]));
  expect(readme).not.toMatch(/B²/);
});

// ---- handoff keeps the facts a fresh agent cannot get from the code alone ----
test("handoff describes the account menu and the logo, and is honest that real sign-in was not re-run after the menu change", () => {
  expect(handoff).toMatch(/account menu[^\n]*Sign out[^\n]*dropdown/i);
  expect(handoff).toMatch(/public\/argus-logo\.svg/);
  expect(handoff).toMatch(/public\/argus-mark\.svg/);
  const verified = handoff.slice(handoff.indexOf("## What is verified"), handoff.indexOf("## Running things"));
  expect(verified).toMatch(/not re-run[^\n]*(account menu|menu change)/i);
});

test("handoff carries the practical gotchas learned while building the UI", () => {
  expect(handoff).toMatch(/sed -i/); // macOS BSD sed: the Linux form fails silently
  expect(handoff).toMatch(/port 5173/i); // other projects' dev servers can hold it
  expect(handoff).toMatch(/pip install -e/); // stale venv after pulling backend changes
  expect(handoff).toMatch(/preview page[^\n]*fake/i); // visual check of signed-in UI without Firebase
  expect(handoff).toMatch(/docs-vs-code|read the backend source/i); // the guard tests
});
