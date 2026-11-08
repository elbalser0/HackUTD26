/**
 * Admin "All records": a Records view (client-side filters over every record)
 * and an Events view (server-side filters over GET /api/admin/log). Read-only.
 */
import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { AdminEvent, AdminFilters, EmergencyRecord, RunOutcome } from "../api";
import { age } from "../format";
import {
  activityLabel,
  explainedByOptions,
  filterRecords,
  hourRange,
  INTENT_OPTIONS,
  intentLabel,
  rangeSince,
} from "../allRecords";
import type { RangeKey, RecordFilters, StatusFilter } from "../allRecords";
import {
  assuranceTag,
  EVENT_LABEL,
  isAlarming,
  outcomeText,
  shortUtc,
  withoutOutcomePrefix,
} from "../events";
import { humanize } from "../overview";
import { useAsync } from "../useAsync";
import { ErrorState, Loading } from "./States";

export function AllRecords({ view, hour }: { view: "records" | "events"; hour: string | null }) {
  const records = useAsync(() => api.listRecords(), []);
  return (
    <>
      <div className="head">
        <div>
          <div className="eyebrow">ALL RECORDS</div>
          <h1>Every manual change</h1>
        </div>
        <div className="seg" role="group" aria-label="View">
          <a href="#/admin/records" aria-current={view === "records" ? "true" : "false"}>
            Records
          </a>
          <a href="#/admin/events" aria-current={view === "events" ? "true" : "false"}>
            Events
          </a>
        </div>
      </div>
      {view === "records" ? (
        <>
          {records.s.state === "loading" && <Loading what="records" />}
          {records.s.state === "error" && (
            <ErrorState error={records.s.error} onRetry={records.reload} />
          )}
          {records.s.state === "ok" && <RecordsView records={records.s.data.records} />}
        </>
      ) : (
        <EventsView hour={hour} />
      )}
    </>
  );
}

// ---- Records ---------------------------------------------------------------

const STATUS: { value: StatusFilter; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

function RecordsView({ records }: { records: EmergencyRecord[] }) {
  const [f, setF] = useState<RecordFilters>({ search: "", explainedBy: "any", intent: "any", status: "open" });
  const set = (k: keyof RecordFilters) => (e: { target: { value: string } }) =>
    setF({ ...f, [k]: e.target.value });
  const rows = filterRecords(records, f);
  return (
    <>
      <form className="card" aria-label="Filters" style={{ gap: 12 }} onSubmit={(e) => e.preventDefault()}>
        <div className="filters">
          <div className="field">
            <label htmlFor="f-search">Search</label>
            <input className="input" id="f-search" placeholder="Resource or summary" value={f.search} onChange={set("search")} />
          </div>
          <div className="field">
            <label htmlFor="f-by">Explained by</label>
            <select className="input" id="f-by" value={f.explainedBy} onChange={set("explainedBy")}>
              {explainedByOptions(records).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-intent">Intent</label>
            <select className="input" id="f-intent" value={f.intent} onChange={set("intent")}>
              {INTENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-status">Status</label>
            <select className="input" id="f-status" value={f.status} onChange={set("status")}>
              {STATUS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </form>
      <section className="card" aria-label="Records">
        {rows.length === 0 ? (
          <p className="sub">
            No records match these filters. This is not proof nothing changed: the scanner only sees
            attributes Terraform&rsquo;s provider tracks.
          </p>
        ) : (
          <div className="scroll-x">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Resource</th>
                  <th scope="col">Status</th>
                  <th scope="col">Explained by</th>
                  <th scope="col">Intent</th>
                  <th scope="col">Detected</th>
                  <th scope="col">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <RecordRow key={r.id} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function RecordRow({ r }: { r: EmergencyRecord }) {
  const x = r.observed ?? r.baseline;
  const brief = `${x?.protocol ?? r.attribute} ${x?.portRange ?? ""} ${r.changeKind}`.replace(/\s+/g, " ").trim();
  const status =
    r.resolution === "resolved" ? (
      <span className="tag">Resolved</span>
    ) : r.reason === null ? (
      <span className="tag amber">No reason</span>
    ) : (
      <span className="tag green">Open</span>
    );
  const a = assuranceTag(r.reporterAssurance);
  const intent = intentLabel(r.intent);
  return (
    <tr>
      <td className="mono">
        <a className="link" style={{ minHeight: 0 }} href={`#/admin/records/${encodeURIComponent(r.id)}`}>
          {r.resourceAddress}
        </a>
        <div className="sub">{brief}</div>
      </td>
      <td>{status}</td>
      <td>
        {r.reason === null ? (
          "Nobody yet"
        ) : (
          <>
            <span>{r.reporter ?? "No name given"}</span>{" "}
            {a && <span className={`tag ${a.tone}`}>{a.label}</span>}
          </>
        )}
      </td>
      <td>{r.intent === "unset" || !intent ? "—" : <span className="tag blue">{intent}</span>}</td>
      <td>{age(r.firstDetectedAt)} ago</td>
      <td>
        {!r.lastActivity
          ? "—"
          : r.lastActivity.type === "detected"
            ? activityLabel("detected")
            : `${activityLabel(r.lastActivity.type)}, ${age(r.lastActivity.at)} ago`}
      </td>
    </tr>
  );
}

// ---- Events ----------------------------------------------------------------

const OUTCOMES: RunOutcome[] = [
  "unknown",
  "failed",
  "cancelled",
  "kept",
  "deferred",
  "no_changes",
  "applied_no_warnings",
  "reverted_applied",
  "override_applied",
  "unverified_bypass_applied",
  "aborted_plan_changed",
];

interface Applied {
  engineer: string;
  resource: string;
  outcome: string;
  range: RangeKey;
}
const FRESH: Applied = { engineer: "", resource: "", outcome: "", range: "24h" };

function EventsView({ hour }: { hour: string | null }) {
  const [draft, setDraft] = useState<Applied>(FRESH);
  const [applied, setApplied] = useState<Applied>(FRESH);
  const h = hourRange(hour);
  const { s, reload } = useAsync(() => {
    const f: AdminFilters = {};
    if (applied.engineer) f.engineer = applied.engineer;
    if (applied.resource) f.resource = applied.resource;
    if (applied.outcome) f.outcome = applied.outcome as RunOutcome;
    if (h) {
      f.since = h.since;
      f.until = h.until;
    } else {
      const since = rangeSince(applied.range, Date.now());
      if (since) f.since = since;
    }
    return api.adminEvents(f);
    // eslint-disable-next-line
  }, [applied, h?.since]);
  const set = (k: keyof Applied) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [k]: e.target.value });
  const apply = (e: FormEvent) => {
    e.preventDefault();
    setApplied({
      engineer: draft.engineer.trim(),
      resource: draft.resource.trim(),
      outcome: draft.outcome,
      range: draft.range,
    });
  };
  return (
    <>
      <form className="card" aria-label="Filters" style={{ gap: 12 }} onSubmit={apply}>
        <div className="filters">
          <div className="field">
            <label htmlFor="e-eng">Engineer</label>
            <input className="input" id="e-eng" placeholder="Name or email" value={draft.engineer} onChange={set("engineer")} />
          </div>
          <div className="field">
            <label htmlFor="e-res">Resource</label>
            <input className="input" id="e-res" placeholder="digitalocean_firewall.web" value={draft.resource} onChange={set("resource")} />
          </div>
          <div className="field">
            <label htmlFor="e-out">Outcome</label>
            <select className="input" id="e-out" value={draft.outcome} onChange={set("outcome")}>
              <option value="">Any</option>
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {humanize(o)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="e-range">Range</label>
            <select
              className="input"
              id="e-range"
              value={draft.range}
              onChange={set("range")}
              disabled={!!h}
              title={h ? "Clear the hour filter to choose a range" : undefined}
            >
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="all">All time</option>
            </select>
          </div>
          <button className="btn primary" type="submit">
            Apply
          </button>
        </div>
      </form>
      {h && (
        <div className="row" style={{ gap: 12, alignItems: "center" }} aria-label="Active filters">
          <span className="sub">Showing</span>
          <button
            className="chip live"
            style={{ minHeight: 44, cursor: "pointer" }}
            aria-label={`Clear hour filter: ${h.span}`}
            onClick={() => (window.location.hash = "#/admin/events")}
          >
            {h.label} <span aria-hidden="true">✕</span>
          </button>
          <span className="sub">Opened from the Overview chart</span>
        </div>
      )}
      {s.state === "loading" && <Loading what="events" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" && (
        <>
          <section className="card" aria-labelledby="ev">
            <div className="card-head">
              <h2 id="ev">Events</h2>
              <span className="sub">
                Newest first · {s.data.totalMatching} matching
                {s.data.events.length < s.data.totalMatching &&
                  ` · Showing ${s.data.events.length} of ${s.data.totalMatching}`}
              </span>
            </div>
            {s.data.events.length === 0 ? (
              <p className="sub">
                No events match these filters. This does not prove nothing happened: only changes the
                tool captured are recorded.
              </p>
            ) : (
              <div className="scroll-x">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Time (UTC)</th>
                      <th scope="col">Who</th>
                      <th scope="col">Event</th>
                      <th scope="col">Resource</th>
                      <th scope="col">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.data.events.map((e, i) => (
                      <EventRow key={i} e={e} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

function EventRow({ e }: { e: AdminEvent }) {
  const a = assuranceTag(e.actorAssurance);
  const detail = withoutOutcomePrefix(e.detail, e.outcome);
  const linked = e.recordIds.length === e.resourceAddresses.length;
  return (
    <tr>
      <td>{shortUtc(e.at)}</td>
      <td>
        {e.actor === null ? (
          "system"
        ) : (
          <>
            <span>{e.actor}</span> {a && <span className={`tag ${a.tone}`}>{a.label}</span>}
          </>
        )}
      </td>
      <td>
        <span className={`tag${isAlarming(e) ? " amber" : ""}`}>{EVENT_LABEL[e.type]}</span>
      </td>
      <td className="mono">
        {e.resourceAddresses.length === 0
          ? "—"
          : e.resourceAddresses.map((r, i) =>
              linked ? (
                <div key={r + i}>
                  <a className="link" style={{ minHeight: 0 }} href={`#/admin/records/${encodeURIComponent(e.recordIds[i])}`}>
                    {r}
                  </a>
                </div>
              ) : (
                <div key={r + i}>{r}</div>
              ),
            )}
      </td>
      <td>
        {detail && <div>{detail}</div>}
        {e.outcome && <div>{outcomeText(e.outcome)}</div>}
      </td>
    </tr>
  );
}
