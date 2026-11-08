// CSS contract for the admin/employee phone layout in argus.css (<= 720px). jsdom applies no
// stylesheets, so this reads the file as text. Real layout is checked in a browser at 375 and 320.
import { expect, test } from "vitest";
import css from "./argus.css?raw";

function mobileBlocks(): string {
  let out = "";
  let from = 0;
  for (;;) {
    const start = css.indexOf("@media (max-width: 720px)", from);
    if (start === -1) return out;
    let depth = 0;
    let i = css.indexOf("{", start);
    const bodyStart = i + 1;
    for (; i < css.length; i++) {
      if (css[i] === "{") depth++;
      if (css[i] === "}" && --depth === 0) break;
    }
    out += css.slice(bodyStart, i);
    from = i;
  }
}

const rule = (selector: string): string => {
  let out = "";
  for (const m of mobileBlocks().matchAll(/([^{}]+)\{([^{}]*)\}/g))
    if (m[1].split(",").map((x) => x.trim()).includes(selector)) out += m[2] + ";";
  return out;
};

test.each([".crumbs a", ".top .chip", ".top .brand", "a.item", ".nav a"])(
  "phone: %s has a tap target of at least 44px",
  (sel) => {
    expect(rule(sel)).toMatch(/min-height:\s*44px/);
  },
);

// Found on real Tiger data (2026-11-08): `digitalocean_firewall.demo` in a monospace h1 does not
// wrap, so the admin Record page scrolled sideways at 375 px (page width 552). Fixtures used a shorter name.
test.each([".mono", "h1.mono", ".m", ".sub"])("phone: %s wraps long unbroken text (resource names, plan hashes)", (sel) => {
  expect(rule(sel)).toMatch(/overflow-wrap:\s*anywhere/);
});

// Found on real data at 320 px: the legacy `header { height: 58px }` in App.css (phone block) clipped the
// wrapped top bar, so its chips overlapped the page heading. And the DEMO DATA tag ran off the right edge.
test(".top grows with its wrapped content on phones (beats the legacy fixed header height)", () => {
  expect(rule(".top")).toMatch(/height:\s*auto/);
});
test(".tag may wrap instead of running off the screen", () => {
  expect(rule(".tag")).toMatch(/white-space:\s*normal/);
  expect(rule(".tag")).toMatch(/max-width:\s*100%/);
});
