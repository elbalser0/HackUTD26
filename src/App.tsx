import { useEffect, useState } from "react";
import { usingFixtures } from "./api";
import { AccountBar, AuthGate, AuthProvider } from "./components/AuthProvider";
import { AdminArea } from "./components/Admin";
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

function App() {
  const path = useHashPath();
  const rec = path.match(/^\/records\/([^/]+)$/);
  const run = path.match(/^\/apply\/([^/]+)$/);
  const admin = path === "/admin" || /^\/admin\/records\/[^/]+$/.test(path);
  const employee = !admin && !run;
  const crumb = admin
    ? "Admin log"
    : run
      ? "Apply warning"
      : rec
        ? "Record"
        : "Open records";
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
            aria-current={!run && !admin ? "page" : undefined}
            onClick={() => (window.location.hash = "#/")}
          >
            <span className="nav-icon" aria-hidden="true">
              ≡
            </span>
            Open records
          </button>
          <a
            className="nav-admin"
            href="#/admin"
            aria-current={admin ? "page" : undefined}
          >
            <span className="nav-icon" aria-hidden="true">
              ◷
            </span>
            Admin log
          </a>
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
          {admin ? (
            <AdminArea path={path} />
          ) : (
            <ApplyRunView key={run![1]} id={decodeURIComponent(run![1])} />
          )}
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
    </AuthGate>
    </AuthProvider>
  );
}
export default App;
