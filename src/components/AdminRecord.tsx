/**
 * Admin Record page. Read-only: who explained it and how reliable that is,
 * intent, the linked run, the change, the full history and the gaps in the
 * evidence. There is deliberately no form here.
 */
import { api } from "../api";
import type { AdminEvent, EmergencyRecord, Timeline } from "../api";
import { intentLabel } from "../allRecords";
import {
  assuranceTag,
  gapTitle,
  HISTORY_TITLE,
  isAlarming,
  linkedRun,
  outcomeText,
  withoutOutcomePrefix,
} from "../events";
import { baselineText, CHECK_LABEL, demoTag, formatDetected, observedText } from "../format";
import { humanize } from "../overview";
import { useAsync } from "../useAsync";
import type { Async } from "../useAsync";
import { ErrorState, Loading } from "./States";

export function AdminRecord({ id }: { id: string }) {
  const rec = useAsync(() => api.getRecord(id), [id]);
  const tl = useAsync(() => api.adminRecordTimeline(id), [id]);
  if (rec.s.state === "loading") return <Loading what="record" />;
  if (rec.s.state === "error") return <ErrorState error={rec.s.error} onRetry={rec.reload} />;
  const r = rec.s.data;
  const demo = demoTag(r.environment, r.evidenceSource);
  return (
    <>
      <div className="head">
        <div>
          <div className="eyebrow">RECORD</div>
          <h1 className="mono">{r.resourceAddress}</h1>
        </div>
        <div className="top-right">
          <span className={`tag${r.resolution === "open" ? " green" : ""}`}>
            {r.resolution === "open" ? "Open" : "Resolved"}
          </span>
          <span className="tag">{CHECK_LABEL[r.lastCheckStatus]}</span>
          {demo && <span className="tag amber">{demo}</span>}
        </div>
      </div>

      <Kpis r={r} timeline={tl.s} />

      <section className="card" aria-labelledby="chg">
        <div className="card-head">
          <h2 id="chg">What changed</h2>
          <span className="sub">
            {`Detected ${formatDetected(r.firstDetectedAt)}, when the scanner noticed, not when the change was made.`}
          </span>
        </div>
        <div className="sub">
          {r.attribute} · {r.changeKind}
        </div>
        <div className="diff">
          {r.baseline && <span className="old">{baselineText(r)}</span>}
          {r.baseline && r.observed && <span aria-hidden="true">→</span>}
          {r.observed && <span className="new">{observedText(r)}</span>}
        </div>
        {r.resolution === "resolved" && (
          <p className="sub">Resolved{r.resolutionReason ? `: ${r.resolutionReason}` : ""}.</p>
        )}
      </section>

      <div className="row">
        <section className="card grow2" aria-labelledby="tl">
          <h2 id="tl">Full history</h2>
          {tl.s.state === "loading" && <Loading what="history" />}
          {tl.s.state === "error" && <ErrorState error={tl.s.error} onRetry={tl.reload} />}
          {tl.s.state === "ok" && (
            <div className="tl">
              {newestFirst(tl.s.data.events).map((e, i) => (
                <HistoryItem key={i} e={e} />
              ))}
            </div>
          )}
        </section>
        <section className="card grow1" aria-labelledby="gaps" style={{ alignSelf: "flex-start" }}>
          <h2 id="gaps">Gaps</h2>
          <div className="list">
            {tl.s.state === "ok" &&
              tl.s.data.gaps.map((g, i) => (
                <div className="item" key={i}>
                  <div className="grow">
                    <div className="t">{gapTitle(g.code)}</div>
                    <div className="m">{g.message}</div>
                  </div>
                </div>
              ))}
            <div className="item">
              <div className="grow">
                <div className="t">Not verified who made the change</div>
                <div className="m">Reports show who submitted them, never who changed the console.</div>
              </div>
            </div>
          </div>
        </section>
      </div>

    </>
  );
}

/** The API sends oldest first; show newest first, ties in reverse of arrival. */
function newestFirst(events: AdminEvent[]): AdminEvent[] {
  return [...events].reverse().sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

function Kpis({
  r,
  timeline,
}: {
  r: EmergencyRecord;
  timeline: Async<Timeline>;
}) {
  const a = assuranceTag(r.reporterAssurance);
  const assuranceNote =
    r.reporterAssurance === "self-reported"
      ? "self-reported, not verified"
      : a?.label === "verified sign-in"
        ? "verified sign-in: who submitted it, not who made the change"
        : (a?.label ?? "no assurance recorded");
  const intent = r.intent === "unset" ? null : intentLabel(r.intent);
  const run = timeline.state === "ok" ? linkedRun(timeline.data.events) : null;
  const runBad = run !== null && (run.outcome === "unknown" || run.outcome === "failed");
  return (
    <div className="kpis">
      <div className="kpi">
        <span className="label">Explained by</span>
        <span className="value" style={{ fontSize: 24 }}>
          {r.reason === null ? "Nobody yet" : (r.reporter ?? "No name given")}
        </span>
        <span className="note">{r.reason === null ? "no reason recorded" : assuranceNote}</span>
      </div>
      <div className="kpi">
        <span className="label">Intent</span>
        <span className="value" style={{ fontSize: 24 }}>
          {intent ?? "Not set"}
        </span>
        <span className="note">
          {intent && r.intentUpdatedAt ? `set ${formatDetected(r.intentUpdatedAt)}` : "no intent recorded"}
        </span>
      </div>
      <div className={`kpi${runBad ? " warn" : ""}`}>
        <span className="label">Linked run</span>
        <span className="value" style={{ fontSize: 24 }}>
          {timeline.state === "ok" ? (run ? humanize(run.outcome ?? "unknown") : "None") : "Unavailable"}
        </span>
        <span className="note">
          <span className={`dot${runBad ? " amber" : ""}`} />
          {timeline.state !== "ok"
            ? timeline.state === "loading"
              ? "loading history"
              : "history could not be loaded"
            : run === null
              ? "no apply run linked"
              : run.outcome === "unknown"
                ? "no completion recorded"
                : formatDetected(run.at)}
        </span>
      </div>
    </div>
  );
}

function HistoryItem({ e }: { e: AdminEvent }) {
  const a = assuranceTag(e.actorAssurance);
  const detail = withoutOutcomePrefix(e.detail, e.outcome);
  const tone = isAlarming(e) ? "amber" : e.actor ? "blue" : "";
  return (
    <div className="tl-item">
      <span className={`dot ${tone}`} />
      <div className="b">
        <div className="t">{HISTORY_TITLE[e.type]}</div>
        <div className="m sub">
          {`${detail ? `${detail} · ` : ""}${e.actor ?? "system"} · ${formatDetected(e.at)}`}{" "}
          {a && <span className={`tag ${a.tone}`}>{a.label}</span>}
        </div>
        {e.outcome && <div className="m sub">{outcomeText(e.outcome)}</div>}
        {e.planFingerprint && <div className="m sub">reviewed plan: {e.planFingerprint}</div>}
      </div>
    </div>
  );
}
