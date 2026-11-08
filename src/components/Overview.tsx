/**
 * Admin Overview ("Manual changes, before the next apply"), from
 * GET /api/admin/overview. Read-only; counts events, not incidents.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { Overview as OverviewData, OverviewWindow } from "../api";
import { age } from "../format";
import {
  axisLabel,
  barKinds,
  barLabel,
  chartSummary,
  eventBreakdown,
  humanize,
  outcomeRows,
  totalOf,
} from "../overview";
import { useAsync } from "../useAsync";
import { ErrorState, Loading, Notice } from "./States";

const MAX_LISTED = 10;
const CHART_PX = 170;
const MAX_UNIT_PX = 30;

export function Overview() {
  const [win, setWin] = useState<OverviewWindow>("24h");
  const { s, reload } = useAsync(() => api.adminOverview(win), [win]);
  return (
    <>
      <div className="head">
        <div>
          <div className="eyebrow">OVERVIEW</div>
          <h1>Manual changes, before the next apply</h1>
        </div>
        <div className="top-right">
          <div className="seg" role="group" aria-label="Time range">
            {(["24h", "7d"] as const).map((w) => (
              <button key={w} aria-pressed={win === w} onClick={() => setWin(w)}>
                {w === "24h" ? "24 h" : "7 d"}
              </button>
            ))}
          </div>
          <button className="btn" onClick={reload}>
            Refresh
          </button>
        </div>
      </div>
      {s.state === "loading" && <Loading what="overview" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" && <Body o={s.data} />}
    </>
  );
}

function Kpi({ className, href, children }: { className: string; href?: string; children: ReactNode }) {
  const cls = `kpi${className ? " " + className : ""}`;
  return href ? (
    <a className={cls} href={href}>
      {children}
    </a>
  ) : (
    <div className={cls}>{children}</div>
  );
}

function Body({ o }: { o: OverviewData }) {
  const label = o.window === "7d" ? "7 d" : "24 h";
  const events = totalOf(o.eventsByType);
  const run = o.lastRun;
  const runBad = run !== null && (run.outcome === "unknown" || run.outcome === "failed");
  const scanBad = o.lastScan === null || o.lastScan.status !== "ok";
  return (
    <>
      <section className="kpis" aria-label="Summary">
        <a className={`kpi${o.openWithoutReason > 0 ? " warn" : ""}`} href="#/admin/records">
          <span className="label">Open records</span>
          <span className="value">{o.openRecords}</span>
          <span className="note">
            <span className={`dot${o.openWithoutReason > 0 ? " amber" : ""}`} />
            {o.openWithoutReason} without a reason · view all
          </span>
        </a>
        <div className={`kpi${scanBad ? " warn" : ""}`}>
          <span className="label">Last scan</span>
          <span className="value">{o.lastScan ? `${age(o.lastScan.at)} ago` : "Never"}</span>
          <span className="note">
            <span className={`dot${scanBad ? " amber" : ""}`} />
            {o.lastScan ? `scan ${o.lastScan.status}` : "no scan recorded"}
          </span>
        </div>
        <Kpi className={runBad ? "warn" : ""} href={run ? "#/admin/events" : undefined}>
          <span className="label">Last apply</span>
          <span className="value">{run ? humanize(run.outcome) : "None"}</span>
          <span className="note">
            <span className={`dot${runBad ? " amber" : ""}`} />
            {run === null
              ? "no apply run recorded"
              : run.outcome === "unknown"
                ? `no completion recorded, ${age(run.at)} ago · see events`
                : `${age(run.at)} ago · see events`}
          </span>
        </Kpi>
        <a className="kpi" href="#/admin/events">
          <span className="label">Events, {label}</span>
          <span className="value">{events}</span>
          <span className="note">
            {eventBreakdown(o.eventsByType) || "none in this window"} · see events
          </span>
        </a>
      </section>

      <section className="card" aria-labelledby="att">
        <div className="card-head">
          <h2 id="att">Open without a reason</h2>
          <a className="link" href="#/admin/records">
            All records
          </a>
        </div>
        {o.needsReason.length === 0 ? (
          <p className="sub">No open records without a reason.</p>
        ) : (
          <div className="list">
            {o.needsReason.slice(0, MAX_LISTED).map((n) => (
              <div className="item" key={n.recordId}>
                <div className="grow">
                  <div className="t mono">{n.resourceAddress}</div>
                  <div className="m">
                    {n.summary} · unexplained for {age(n.firstDetectedAt)}
                  </div>
                </div>
                <span className="tag amber">No reason</span>
                <a
                  className="btn"
                  href={`#/admin/records/${encodeURIComponent(n.recordId)}`}
                  aria-label={`Review ${n.resourceAddress}`}
                >
                  Review
                </a>
              </div>
            ))}
          </div>
        )}
        {o.openWithoutReason > Math.min(o.needsReason.length, MAX_LISTED) && (
          <p className="sub">
            and {o.openWithoutReason - Math.min(o.needsReason.length, MAX_LISTED)} more
          </p>
        )}
      </section>

      <div className="row">
        <Chart o={o} />
        <section className="card grow1" aria-labelledby="out">
          <h2 id="out">Run outcomes</h2>
          {outcomeRows(o.runOutcomes).length === 0 ? (
            <p className="sub">No runs in this window.</p>
          ) : (
            <div className="list">
              {outcomeRows(o.runOutcomes).map((r) => {
                const body = (
                  <>
                    <div className="grow t">{humanize(r.code)}</div>
                    <span className={`tag${r.code === "unknown" || r.code === "failed" ? " amber" : ""}`}>
                      {r.count}
                    </span>
                  </>
                );
                return r.code === "unknown" ? (
                  <a className="item" key={r.code} href="#/admin/events">
                    {body}
                  </a>
                ) : (
                  <div className="item" key={r.code}>
                    {body}
                  </div>
                );
              })}
            </div>
          )}
          <p className="sub">
            Unknown means no completion was recorded. It is never counted as failed.
          </p>
        </section>
      </div>

      {o.limitations.length > 0 && (
        <Notice tone="info">
          <strong>What this view cannot tell you</strong>
          <ul>
            {o.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Notice>
      )}
    </>
  );
}

function Chart({ o }: { o: OverviewData }) {
  const bars = o.activity.map((b) => ({ ...b, kinds: barKinds(b.counts), total: totalOf(b.counts) }));
  const peak = Math.max(1, ...bars.map((b) => b.total));
  const unit = Math.min(MAX_UNIT_PX, CHART_PX / peak);
  const hasOther = bars.some((b) => b.kinds.other > 0);
  const seg = (n: number, cls: string) =>
    n > 0 ? <div className={`seg-bar ${cls}`} style={{ height: `${n * unit}px` }} /> : null;
  return (
    <section className="card grow2" aria-labelledby="act">
      <div className="card-head">
        <h2 id="act">Activity per hour</h2>
        <span className="sub">UTC</span>
      </div>
      <div
        className={`chart${o.window === "7d" ? " dense" : ""}`}
        role="img"
        aria-label={chartSummary(o.activity, o.window)}
      >
        {bars.map((b) => {
          const inner = (
            <>
              {seg(b.kinds.other, "k-other")}
              {seg(b.kinds.run, "k-run")}
              {seg(b.kinds.review, "k-review")}
              {seg(b.kinds.report, "k-report")}
            </>
          );
          // only hours with events are links, so keyboard users are not sent through 168 empty stops
          return b.total > 0 ? (
            <a
              className="col"
              key={b.hour}
              href={`#/admin/events?hour=${encodeURIComponent(b.hour)}`}
              aria-label={barLabel(b, o.window)}
            >
              {inner}
            </a>
          ) : (
            <div className="col" key={b.hour}>
              {inner}
            </div>
          );
        })}
      </div>
      <div className={`axis${o.window === "7d" ? " dense" : ""}`} aria-hidden="true">
        {bars.map((b, i) => (
          <span key={b.hour}>{axisLabel(b.hour, i, o.window)}</span>
        ))}
      </div>
      <div className="legend">
        <span>
          <i className="k-report" />
          Report
        </span>
        <span>
          <i className="k-review" />
          Review
        </span>
        <span>
          <i className="k-run" />
          Run
        </span>
        {hasOther && (
          <span>
            <i className="k-other" />
            Other
          </span>
        )}
        <span style={{ marginLeft: "auto" }}>Select a bar to see that hour&rsquo;s events · counts events, not incidents</span>
      </div>
    </section>
  );
}
