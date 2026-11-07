import { useState } from "react";
import type { ReactNode } from "react";
import "./App.css";

type View = "Workspace" | "Challenge brief" | "Team";
const initialBrief = "";
function Panel({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="eyebrow">{label}</div>
      {children}
    </section>
  );
}
function App() {
  const [view, setView] = useState<View>("Workspace");
  const [brief, setBrief] = useState(() => {
    try {
      return localStorage.getItem("hackutd26.brief") ?? initialBrief;
    } catch {
      return initialBrief;
    }
  });
  const [message, setMessage] = useState("");
  function saveBrief() {
    try {
      localStorage.setItem("hackutd26.brief", brief);
      setMessage("Saved in this browser. Not shared with your team.");
    } catch {
      setMessage(
        "Could not save. Browser storage is unavailable; copy your notes before leaving.",
      );
    }
  }
  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="wordmark"
          href="#"
          onClick={() => setView("Workspace")}
          aria-label="HackUTD26 home"
        >
          H<span>²</span>
          <small>HACKUTD26</small>
        </a>
        <div className="workspace-label">
          TEAM WORKSPACE <span>01</span>
        </div>
        <nav aria-label="Main navigation">
          {(["Workspace", "Challenge brief", "Team"] as View[]).map(
            (item, i) => (
              <button
                key={item}
                aria-current={view === item ? "page" : undefined}
                onClick={() => setView(item)}
              >
                <span className="nav-icon" aria-hidden="true">
                  {["▦", "≡", "◇"][i]}
                </span>
                {item}
                <span className="nav-arrow" aria-hidden="true">
                  ↗
                </span>
              </button>
            ),
          )}
        </nav>
        <div className="sidebar-bottom">
          <span className="small-dot" /> FRONTEND ONLY
          <p>No infrastructure connected.</p>
          <a href="https://nmc2.com/" target="_blank" rel="noreferrer">
            Explore NMC² ↗
          </a>
        </div>
      </aside>
      <div className="body">
        <header>
          <span>
            HackUTD 2026 <span className="slash">/</span> {view}
          </span>
          <span className="badge">PRE-CHALLENGE</span>
        </header>
        <main id="main">
          {view === "Workspace" && (
            <>
              <section className="hero">
                <div className="hero-art" aria-hidden="true">
                  <div />
                  <div />
                  <div />
                </div>
                <div className="eyebrow">COMPUTE, WITH INTENT.</div>
                <h1>
                  Big infrastructure.
                  <br />
                  <span>Clear possibilities.</span>
                </h1>
                <p>
                  A starting point for what comes next.
                  <br />
                  Built to pivot when the challenge drops.
                </p>
                <button
                  className="primary"
                  onClick={() => setView("Challenge brief")}
                >
                  Capture the challenge <span aria-hidden="true">↗</span>
                </button>
                <div className="hero-foot">
                  <span>HACKUTD26</span>
                  <span>EXPERIMENT / 001</span>
                </div>
              </section>
              <div className="section-heading">
                <h2>Your starting line</h2>
                <span>CONTEXT BEFORE CODE</span>
              </div>
              <div className="panels">
                <Panel label="01 / THE BRIEF">
                  <h3>Open by design.</h3>
                  <p>
                    The official challenge hasn’t been announced. Keep the
                    solution flexible until we know the problem.
                  </p>
                  <button
                    className="text-button"
                    onClick={() => setView("Challenge brief")}
                  >
                    Open challenge notes ↗
                  </button>
                </Panel>
                <Panel label="02 / THE SIGNAL">
                  <h3>Infrastructure as code.</h3>
                  <p>
                    A direction mentioned at the NMC² booth—not a confirmed
                    requirement. Validate it against the published brief.
                  </p>
                  <span className="tag">UNCONFIRMED HINT</span>
                </Panel>
                <Panel label="03 / THE TEAM">
                  <h3>Three angles. One build.</h3>
                  <p>
                    Product and frontend. Backend. Infrastructure. Flexible
                    ownership, one shared demo.
                  </p>
                  <button
                    className="text-button"
                    onClick={() => setView("Team")}
                  >
                    Meet the team ↗
                  </button>
                </Panel>
              </div>
              <section className="connection">
                <div className="connection-icon" aria-hidden="true">
                  ⌁
                </div>
                <div>
                  <h3>A clean slate, not a pretend cluster.</h3>
                  <p>
                    No simulated usage, invented capacity, or provisioning
                    actions. Connect the real backend once the scope is clear.
                  </p>
                </div>
                <span className="tag">NOT CONNECTED</span>
              </section>
            </>
          )}
          {view === "Challenge brief" && (
            <section className="detail">
              <div className="eyebrow">DEFINE BEFORE YOU BUILD</div>
              <h1>Start with the problem.</h1>
              <p>
                The official brief is pending. Capture it here when it’s
                announced.
              </p>
              <Panel label="WORKING NOTES">
                <label htmlFor="brief">
                  Challenge, user, constraints, and judging criteria
                </label>
                <textarea
                  id="brief"
                  value={brief}
                  onChange={(e) => {
                    setBrief(e.target.value);
                    setMessage("Unsaved changes");
                  }}
                  placeholder="Paste the official challenge. Then identify: who has the problem, what they need to do, and how we will prove it works."
                  rows={12}
                />
                <div className="form-actions">
                  <button className="primary" onClick={saveBrief}>
                    Save notes <span aria-hidden="true">↗</span>
                  </button>
                  <span>Local to this browser. No backend connected.</span>
                </div>
                <p role="status">{message}</p>
              </Panel>
              <p className="caution">
                Booth hint: “infrastructure as code.” Treat this as a hypothesis
                until confirmed.
              </p>
            </section>
          )}
          {view === "Team" && (
            <section className="detail">
              <div className="eyebrow">FLEXIBLE OWNERSHIP</div>
              <h1>
                One team.
                <br />
                <span>Different strengths.</span>
              </h1>
              <p>
                Starting points, not silos. Everyone can flex as the challenge
                takes shape.
              </p>
              <div className="panels">
                {[
                  {
                    name: "Daniel",
                    area: "Product + frontend",
                    note: "Problem framing, user flow, interface, and demo narrative.",
                  },
                  {
                    name: "Samuel",
                    area: "Backend",
                    note: "Service design and API integration, aligned with the selected challenge.",
                  },
                  {
                    name: "Andrew",
                    area: "Infrastructure exploration",
                    note: "Hands-on server experience; home servers with 256 GB RAM. Availability and suitability still need validation.",
                  },
                ].map((person) => (
                  <Panel key={person.name} label={person.area}>
                    <h3>{person.name}</h3>
                    <p>{person.note}</p>
                  </Panel>
                ))}
              </div>
              <section className="connection">
                <div>
                  <h3>Agree on the seam early.</h3>
                  <p>
                    Once the brief is public, choose one end-to-end demo and
                    agree on request, response, and error states before building
                    separately.
                  </p>
                </div>
              </section>
            </section>
          )}
        </main>
        <footer>
          <span>HackUTD26 · Independent hackathon project</span>
          <span>Palette inspired by NMC². Not affiliated or endorsed.</span>
        </footer>
      </div>
    </div>
  );
}
export default App;
