import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, usingFixtures } from "./api";
import { useAuth } from "./auth";
import { useAsync } from "./useAsync";
import { AccountBar, AuthGate, AuthProvider } from "./components/AuthProvider";
import { AdminShell } from "./components/AdminShell";
import { AdminRecord } from "./components/AdminRecord";
import { AllRecords } from "./components/AllRecords";
import { Overview } from "./components/Overview";
import { ErrorState, Loading } from "./components/States";
import { ApplyRunView } from "./components/ApplyRunView";
import { PaletteProvider } from "./components/PaletteContext";
import { TopBar } from "./components/TopBar";
import { RecordsPage } from "./components/Records";
import "./App.css";
import "./argus.css";

function useHashPath() {
  const [h, setH] = useState(() => window.location.hash.slice(1) || "/");
  useEffect(() => {
    const f = () => setH(window.location.hash.slice(1) || "/");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return h;
}

/** The original layout, still used by the apply-run page. */
function LegacyLayout({
  crumb,
  children,
}: {
  crumb: string;
  children: ReactNode;
}) {
  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <a className="wordmark" href="#/" aria-label="Argus home">
          <img src="/argus-logo.svg" alt="" />
        </a>
        <div className="workspace-label">
          INCIDENT CONTEXT <span>01</span>
        </div>
        <nav aria-label="Main navigation">
          <button
            
            onClick={() => (window.location.hash = "#/")}
          >
            <span className="nav-icon" aria-hidden="true">
              ≡
            </span>
            Open records
          </button>
        </nav>
        <div className="sidebar-bottom">
          <span className="small-dot" /> READ-ONLY UI
          <p>Never runs Terraform. The CLI owns execution and approval.</p>
        </div>
      </aside>
      <div className="body">
        <header>
          <span>
            <span className="crumb-root">
              Argus <span className="slash">/</span>{" "}
            </span>
            <span className="crumb-current">{crumb}</span>
          </span>
          <span className="header-right">
            <span className="badge">
              {usingFixtures ? "DEV FIXTURE DATA — NOT A BACKEND" : "LIVE API"}
            </span>
            <AccountBar />
          </span>
        </header>
        <main id="main">
          {children}
        </main>
        <footer>
          <span>
            Explanations saved while signed in show which Google account
            submitted them, never who made the console change. Otherwise they
            are self-reported.
          </span>
          <span>Independent hackathon project. Not affiliated with NMC².</span>
        </footer>
      </div>
    </div>
  );
}

/**
 * #/admin. /api/me only picks the layout: an admin gets the admin screens;
 * anyone else is sent to the employee records page. The server still enforces
 * access on every admin route.
 */
function AdminHome({ path, search }: { path: string; search: string }) {
  const { user } = useAuth();
  const { s, reload } = useAsync(() => api.me(), [user?.email]);
  const notAdmin = s.state === "ok" && s.data.role !== "admin";
  useEffect(() => {
    if (notAdmin) window.location.hash = "#/";
  }, [notAdmin]);
  if (s.state === "error")
    return (
      <div className="ar">
        <main id="main" className="content">
          <ErrorState error={s.error} onRetry={reload} />
        </main>
      </div>
    );
  if (s.state === "loading" || notAdmin)
    return (
      <div className="ar">
        <main id="main" className="content">
          <Loading what="account" />
        </main>
      </div>
    );
  if (s.state === "ok" && s.data.role === "admin") {
    if (path === "/admin")
      return (
        <AdminShell active="overview">
          <Overview />
        </AdminShell>
      );
    const one = path.match(/^\/admin\/records\/([^/]+)$/);
    if (one)
      return (
        <AdminShell
          active="records"
          crumb={
            <>
              <a href="#/admin/records">All records</a> / <b>Record</b>
            </>
          }
        >
          <AdminRecord key={one[1]} id={decodeURIComponent(one[1])} />
        </AdminShell>
      );
    if (path === "/admin/records" || path === "/admin/events")
      return (
        <AdminShell active="records">
          <AllRecords
            view={path === "/admin/events" ? "events" : "records"}
            hour={new URLSearchParams(search).get("hour")}
          />
        </AdminShell>
      );
  }
  return null;
}

function App() {
  const hash = useHashPath();
  const q = hash.indexOf("?");
  const path = q === -1 ? hash : hash.slice(0, q);
  const search = q === -1 ? "" : hash.slice(q + 1);
  const rec = path.match(/^\/records\/([^/]+)$/);
  const run = path.match(/^\/apply\/([^/]+)$/);
  const admin =
    path === "/admin" ||
    path === "/admin/records" ||
    path === "/admin/events" ||
    /^\/admin\/records\/[^/]+$/.test(path);
  const employee = !admin && !run;
  if (admin)
    return (
      <AuthProvider>
        <AuthGate>
          <AdminHome path={path} search={search} />
        </AuthGate>
      </AuthProvider>
    );
  if (employee)
    return (
      <AuthProvider>
        <AuthGate>
          <PaletteProvider>
          <div className="ar">
            <a className="skip" href="#main">
              Skip to content
            </a>
            <TopBar />
            <main id="main" className="content" style={{ maxWidth: "none" }}>
              <RecordsPage routeId={rec ? decodeURIComponent(rec[1]) : null} />
            </main>
          </div>
          </PaletteProvider>
        </AuthGate>
      </AuthProvider>
    );
  return (
    <AuthProvider>
      <AuthGate>
        <LegacyLayout crumb="Apply warning">
          <ApplyRunView key={run![1]} id={decodeURIComponent(run![1])} />
        </LegacyLayout>
      </AuthGate>
    </AuthProvider>
  );
}
export default App;
