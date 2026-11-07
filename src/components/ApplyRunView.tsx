import { api } from "../api";
import type { AckOutcome, ApplyRun, ApplyWarning } from "../api";
import { age, demoTag, formatDetected } from "../format";
import { useAsync } from "../useAsync";
import { BYPASS_NOTE, ErrorState, Loading, Notice } from "./States";

const OUTCOME: Record<AckOutcome, string> = {
  pending: "Awaiting a decision in the terminal",
  no_changes: "Plan had no changes",
  cancelled: "Cancelled in the terminal",
  kept: "Kept — apply was not run",
  deferred: "Deferred — apply was not run",
  applied_no_warnings: "Applied (no emergency records matched)",
  reverted_applied: "Applied (revert chosen)",
  override_applied: "Applied after an explicit override",
  unverified_bypass_applied: "Applied WITHOUT verification",
  aborted_plan_changed: "Aborted — the plan changed after review",
  failed: "Failed",
};

export function ApplyRunView({ id }: { id: string }) {
  const { s, reload } = useAsync(() => api.getApplyRun(id), [id]);
  return (
    <section className="detail">
      <a href="#/">← Open records</a>
      <div className="eyebrow">APPLY WARNING</div>
      <h1>Before you approve.</h1>
      {s.state === "loading" && <Loading what="apply run" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" && <Run run={s.data} />}
      <Notice tone="info">{BYPASS_NOTE}</Notice>
    </section>
  );
}

function Run({ run }: { run: ApplyRun }) {
  const demo = demoTag(run.environment);
  return (
    <>
      {demo && <span className="tag tag-demo">{demo}</span>}
      <p className="meta">
        Generated {formatDetected(run.generatedAt)} · terminal outcome:{" "}
        <strong>{OUTCOME[run.ackOutcome] ?? run.ackOutcome}</strong>
        {run.ackNote && ` — ${run.ackNote}`}
      </p>
      {run.planFingerprint === null && (
        <Notice tone="warn">
          Planning failed, so there is no plan to compare. Nothing below is
          evidence about what an apply would do.
        </Notice>
      )}
      <h2>Proposed changes</h2>
      {run.proposedChanges.length === 0 ? (
        <p className="state">No proposed changes were reported.</p>
      ) : (
        <ul className="cards">
          {run.proposedChanges.map((c, i) => (
            <li key={i} className="card panel">
              <div className="card-top">
                <code>{c.resourceAddress}</code>
                <span className="tag">{c.actions.join(", ")}</span>
              </div>
              <div className="diff">{c.summary}</div>
            </li>
          ))}
        </ul>
      )}
      <h2>Emergency changes this would affect</h2>
      {run.warnings.length === 0 ? (
        <p className="state">
          {run.checkStatus === "current"
            ? "No open record matched this plan, within the coverage below."
            : "No matches were reported, but the check did not complete cleanly (see coverage). This is not confirmation that nothing would be undone."}
        </p>
      ) : (
        <ul className="cards">
          {run.warnings.map((w) => (
            <li key={w.recordId}>
              <Warning w={w} />
            </li>
          ))}
        </ul>
      )}
      <Coverage run={run} />
    </>
  );
}

function Warning({ w }: { w: ApplyWarning }) {
  return (
    <div className="card panel">
      <div className="card-top">
        <code>{w.resourceAddress}</code>
        <a href={`#/records/${encodeURIComponent(w.recordId)}`}>view record</a>
      </div>
      <p className="msg">{w.message}</p>
      {w.reason !== null ? (
        <blockquote>
          {w.reason}
          <footer>
            reported by {w.reporter ?? "unknown"} (self-reported) · detected at{" "}
            {formatDetected(w.firstDetectedAt)} · record age{" "}
            {age(w.firstDetectedAt)} · intent: {w.intent}
          </footer>
        </blockquote>
      ) : (
        <Notice tone="warn">
          Unexplained manual change — no reason recorded. Detected at{" "}
          {formatDetected(w.firstDetectedAt)} · record age{" "}
          {age(w.firstDetectedAt)} · intent: {w.intent}.
        </Notice>
      )}
    </div>
  );
}

function Coverage({ run }: { run: ApplyRun }) {
  return (
    <div>
      <h2>Check coverage</h2>
      {run.checkStatus === "current" ? (
        <p className="meta">Check status: current.</p>
      ) : run.checkStatus === "failed" ? (
        <Notice tone="warn">
          Verification unavailable: the check failed. This is not “no
          conflicts”; treat the matches above as incomplete.
        </Notice>
      ) : (
        <Notice tone="warn">
          Check status: {run.checkStatus}.{" "}
          {run.checkStatus === "stale"
            ? "Records were not re-checked recently; live values may differ."
            : "Evidence could not be interpreted."}{" "}
          Coverage is partial.
        </Notice>
      )}
      <p className="meta">{run.coverageNote}</p>
    </div>
  );
}
