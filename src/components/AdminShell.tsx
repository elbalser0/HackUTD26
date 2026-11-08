import type { ReactNode } from "react";
import { AccountBar } from "./AuthProvider";

/** Admin layout: ADMIN sidebar and an Admin badge. Read-only by design. */
export function AdminShell({
  active,
  children,
}: {
  active: "overview" | "records";
  children: ReactNode;
}) {
  return (
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
          <div className="side-foot">Read-only. Admins review; they do not edit reports.</div>
        </aside>
        <div className="main">
          <header className="top">
            <div className="crumbs">
              {active === "overview" ? (
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
  );
}
