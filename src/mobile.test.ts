// CSS CONTRACT tests for the phone layout (<= 760px). jsdom applies no
// stylesheets, so these read App.css as text. They guard the rules found in a
// real 375px browser pass (2026-11-07): sub-44px tap targets, a breadcrumb that
// wrapped mid-phrase, and a back link jammed against the eyebrow label.
// Layout itself is still verified in a real browser, not here.
import { expect, test } from "vitest";
import css from "./App.css?raw";

const MOBILE = "@media (max-width: 760px)";

/** Declarations of every rule whose selector list contains `selector`, across all mobile media blocks. */
function mobileDecls(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  let from = 0;
  for (;;) {
    const start = css.indexOf(MOBILE, from);
    if (start === -1) break;
    let depth = 0;
    let i = css.indexOf("{", start);
    const bodyStart = i + 1;
    for (; i < css.length; i++) {
      if (css[i] === "{") depth++;
      if (css[i] === "}" && --depth === 0) break;
    }
    const body = css.slice(bodyStart, i);
    for (const m of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const sels = m[1].split(",").map((s) => s.trim());
      if (!sels.includes(selector)) continue;
      for (const d of m[2].split(";")) {
        const [k, ...v] = d.split(":");
        if (k && v.length) out[k.trim()] = v.join(":").trim();
      }
    }
    from = i;
  }
  return out;
}

const px = (v: string | undefined) => (v?.endsWith("px") ? parseFloat(v) : NaN);

test.each([
  "nav button",
  "nav a",
  ".btn",
  ".wordmark",
  ".detail > a:first-child",
  ".card-top a",
  "input",
])("tap target %s is at least 44px tall on phones", (sel) => {
  expect(px(mobileDecls(sel)["min-height"])).toBeGreaterThanOrEqual(44);
});

test.each([".detail > a:first-child", ".card-top a"])(
  "%s can actually take a min-height (not a plain inline box)",
  (sel) => {
    expect(mobileDecls(sel)["display"]).toMatch(/flex|inline-block/);
  },
);

test("back link keeps clear space above the eyebrow label", () => {
  expect(px(mobileDecls(".detail > a:first-child")["margin-bottom"])).toBeGreaterThanOrEqual(
    8,
  );
});

test("header breadcrumb truncates instead of wrapping mid-phrase", () => {
  const d = mobileDecls("header > span:first-child");
  expect(d["white-space"]).toBe("nowrap");
  expect(d["overflow"]).toBe("hidden");
  expect(d["text-overflow"]).toBe("ellipsis");
  expect(d["min-width"]).toBe("0");
});

test("header badge never shrinks its text into a cramped box", () => {
  expect(mobileDecls(".badge")["flex-shrink"]).toBe("0");
});

test("phones hide the product-name breadcrumb prefix (the sidebar wordmark already names it) so the current page stays visible", () => {
  expect(mobileDecls(".crumb-root")["display"]).toBe("none");
});
