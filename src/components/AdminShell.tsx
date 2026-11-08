import type { ReactNode } from "react";
import { AccountBar } from "./AuthProvider";
import { AdminPalette } from "./AdminPalette";
import { PaletteProvider } from "./PaletteContext";
import { usePalette } from "../paletteContext";

const SHORTCUT =
  typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.platform)
    ? "⌘K"
    : "Ctrl K";

function SearchButton() {
  const palette = usePalette();
  return (
    <>
      <button
        className="chip search-btn"
        aria-haspopup="dialog"
        onClick={() => palette.setOpen(true)}
      >
        Search records and events <span className="kbd">{SHORTCUT}</span>
      </button>
      {palette.open && <AdminPalette onClose={() => palette.setOpen(false)} />}
    </>
  );
}

/** Admin layout: ADMIN sidebar and an Admin badge. Read-only by design. */
export function AdminShell({
  active,
  crumb,
  children,
}: {
  active: "overview" | "records";
  /** Replaces the default breadcrumb (used by the record page). */
  crumb?: ReactNode;
  children: ReactNode;
}) {
  return (
    <PaletteProvider>
    <div className="ar">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <aside className="side">
          <a className="brand" href="#/admin" aria-label="Argus home">
            <img src="/argus-logo.svg" alt="" />
          </a>
          <div>
            <div className="nav-label">ADMIN</div>
            <nav className="nav" aria-label="Main">
              <a href="#/admin" aria-current={active === "overview" ? "page" : undefined}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="3" y="3" width="7" height="9" rx="1" />
                  <rect x="14" y="3" width="7" height="5" rx="1" />
                  <rect x="14" y="12" width="7" height="9" rx="1" />
                  <rect x="3" y="16" width="7" height="5" rx="1" />
                </svg>
                Overview
              </a>
              <a href="#/admin/records" aria-current={active === "records" ? "page" : undefined}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M4 6h16M4 12h16M4 18h10" />
                </svg>
                All records
              </a>
            </nav>
          </div>
          <div>
            <div className="nav-label">SWITCH VIEW</div>
            <nav className="nav" aria-label="Switch view">
              <a href="#/">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="8" r="4" />
                  <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
                </svg>
                Employee view
              </a>
            </nav>
          </div>
        </aside>
        <div className="main">
          <header className="top">
            <div className="crumbs">
              {crumb ? (
                crumb
              ) : active === "overview" ? (
                <>
                  Argus / <b>Overview</b>
                </>
              ) : (
                <>
                  <a href="#/admin">Overview</a> / <b>All records</b>
                </>
              )}
            </div>
            <div className="top-right">
              <SearchButton />
              <span className="role">Admin</span>
              <AccountBar />
            </div>
          </header>
          <main id="main" className="content">
            {children}
          </main>
        </div>
      </div>
    </div>
    </PaletteProvider>
  );
}
