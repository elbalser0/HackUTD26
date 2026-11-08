/**
 * Employee "Manual changes" page: filter tabs, then one connected panel with the
 * record list on the left and the selected record on the right.
 * Reports save through the existing report endpoint (reason + optional intent).
 */
import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../api";
import type { EmergencyRecord, Intent, RecordEvent } from "../api";
import { useAuth } from "../auth";
import {
  age,
  baselineText,
  CHECK_LABEL,
  demoTag,
  formatDetected,
  observedText,
  terraformSuggestion,
} from "../format";
import { BUCKETS, bucketOf } from "../records";
import type { Bucket } from "../records";
import { useAsync } from "../useAsync";
import { ErrorState, Loading, Notice } from "./States";
import { Freshness } from "./Freshness";
import { Palette } from "./Palette";
import { usePalette } from "../paletteContext";

export function RecordsPage({ routeId }: { routeId: string | null }) {
  const { s, reload } = useAsync(() => api.listRecords(), []);
  return (
    <>
      <div className="head">
        <div>
          <div className="eyebrow">RECORDS</div>
          <h1>Manual changes</h1>
        </div>
      </div>
      {s.state === "loading" && <Loading what="records" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" && (
        <Workspace
          initial={s.data.records}
          health={s.data.health}
          routeId={routeId}
        />
      )}
    </>
  );
}

function firstNonEmpty(records: EmergencyRecord[]): Bucket {
  for (const b of BUCKETS)
    if (records.some((r) => bucketOf(r) === b.id)) return b.id;
  return "needs";
}

function Workspace({
  initial,
  health,
  routeId,
}: {
  initial: EmergencyRecord[];
  health: Parameters<typeof Freshness>[0]["health"];
  routeId: string | null;
}) {
  const { user } = useAuth();
  const palette = usePalette();
  const [records, setRecords] = useState(initial);
  const [sel, setSel] = useState<string | null>(routeId);
  const [tab, setTab] = useState<Bucket>(() => {
    const routed = initial.find((r) => r.id === routeId);
    return routed ? bucketOf(routed) : firstNonEmpty(initial);
  });

  // Back/forward or a pasted link changes the route: follow it. This adjusts
  // state during render (React's pattern for state derived from props).
  const [seenRoute, setSeenRoute] = useState(routeId);
  if (routeId !== seenRoute) {
    setSeenRoute(routeId);
    setSel(routeId);
    const r = records.find((x) => x.id === routeId);
    if (r) setTab(bucketOf(r));
  }

  const inTab = records.filter((r) => bucketOf(r) === tab);
  const chosen = records.find((r) => r.id === sel);
  const current =
    chosen && bucketOf(chosen) === tab ? chosen : (inTab[0] ?? null);

  const open = (id: string) => {
    setSel(id);
    window.location.hash = `#/records/${encodeURIComponent(id)}`;
  };
  const saved = (r: EmergencyRecord) => {
    setRecords((all) => all.map((x) => (x.id === r.id ? r : x)));
    setSel(r.id);
    setTab(bucketOf(r));
  };

  return (
    <>
      {palette.open && (
        <Palette
          records={records}
          onRecord={(r) => {
            setTab(bucketOf(r));
            open(r.id);
          }}
          onFilter={setTab}
          onClose={() => palette.setOpen(false)}
        />
      )}
      <Freshness health={health} records={records} />
      {health?.auth?.writesRequireSignIn && !user && (
        <Notice tone="info">
          Sign in with Google to add explanations: this server records which
          account submitted each one.
        </Notice>
      )}
      <div className="head">
        <div className="seg" role="group" aria-label="Filter">
          {BUCKETS.map((b) => (
            <button
              key={b.id}
              aria-pressed={tab === b.id}
              onClick={() => setTab(b.id)}
            >
              {b.label} · {records.filter((r) => bucketOf(r) === b.id).length}
            </button>
          ))}
        </div>
      </div>
      <div className="split">
        <nav className="split-list" aria-label="Records">
          <div className="rows">
            {inTab.map((r) => (
              <a
                key={r.id}
                className="rrow"
                href={`#/records/${encodeURIComponent(r.id)}`}
                aria-current={current?.id === r.id ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  open(r.id);
                }}
              >
                <div className="line">
                  <span className="name">{r.resourceAddress}</span>
                  <StatusTag r={r} />
                </div>
                <div className="what">
                  {brief(r)} · {age(r.firstDetectedAt)} ago
                </div>
              </a>
            ))}
          </div>
        </nav>
        {current ? (
          <Panel key={current.id} r={current} onSaved={saved} />
        ) : (
          <section className="split-detail">
            <p className="state">
              {tab === "needs"
                ? "No records need a reason."
                : tab === "explained"
                  ? "No explained records."
                  : "No resolved records."}{" "}
              This is not proof nothing changed: the scanner only sees
              attributes Terraform&rsquo;s provider tracks.
            </p>
          </section>
        )}
      </div>
    </>
  );
}

function brief(r: EmergencyRecord): string {
  const x = r.observed ?? r.baseline;
  return `${x?.protocol ?? r.attribute} ${x?.portRange ?? ""} ${r.changeKind}`
    .replace(/\s+/g, " ")
    .trim();
}

function StatusTag({ r }: { r: EmergencyRecord }) {
  const b = bucketOf(r);
  return (
    <span className={`tag ${b === "needs" ? "amber" : b === "resolved" ? "green" : "blue"}`}>
      {b === "needs" ? "Needs a reason" : b === "resolved" ? "Resolved" : "Explained"}
    </span>
  );
}

function Panel({
  r,
  onSaved,
}: {
  r: EmergencyRecord;
  onSaved: (r: EmergencyRecord) => void;
}) {
  const demo = demoTag(r.environment, r.evidenceSource);
  const closed = r.resolution === "resolved";
  const [history, setHistory] = useState(false);
  return (
    <section className="split-detail" aria-labelledby="record-title">
      <div className="stack-sm">
        <div className="card-head">
          <h2 id="record-title" className="mono title">
            {r.resourceAddress}
          </h2>
          <StatusTag r={r} />
        </div>
        {demo && <span className="tag amber">{demo}</span>}
        <div className="sub">
          Detected {formatDetected(r.firstDetectedAt)} (open{" "}
          {age(r.firstDetectedAt)}), when the scanner noticed, not when the
          change was made. {CHECK_LABEL[r.lastCheckStatus]}.
        </div>
      </div>

      <div className="box">
        <div className="diff">
          <span>
            {r.attribute} · {r.changeKind}
          </span>
          {r.baseline && <span className="old">{baselineText(r)}</span>}
          {r.observed && <span className="new">{observedText(r)}</span>}
        </div>
      </div>

      {closed ? (
        <Notice tone="info">
          This record is resolved
          {r.resolutionReason ? ` (${r.resolutionReason})` : ""}; reports and
          intent changes are closed.
        </Notice>
      ) : (
        <ReportForm r={r} onSaved={onSaved} />
      )}

      <div>
        <button
          className="fold"
          aria-expanded={history}
          onClick={() => setHistory((h) => !h)}
        >
          <span>History</span>
          <span className="sub">{history ? "Hide" : "Show"}</span>
        </button>
        {history && <History r={r} />}
      </div>
    </section>
  );
}

/** Explains sign-in failures; anything else falls back to the server message. */
function writeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401)
      return "Sign-in required or expired. Sign in with Google again, then retry.";
    if (err.status === 403 && err.code === "email_unverified")
      return "This Google account's email isn't verified, so the server refused it.";
  }
  return err instanceof Error ? err.message : "unknown error";
}

const INTENTS: { label: string; value: Intent }[] = [
  { label: "Keep", value: "keep" },
  { label: "Revert", value: "revert" },
  { label: "Undecided", value: "unsure" },
];

function ReportForm({
  r,
  onSaved,
}: {
  r: EmergencyRecord;
  onSaved: (r: EmergencyRecord) => void;
}) {
  const { user } = useAuth();
  const [reason, setReason] = useState(r.reason ?? "");
  const [intent, setIntent] = useState<Intent | null>(
    r.intent === "keep" || r.intent === "revert" || r.intent === "unsure"
      ? r.intent
      : null,
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      setMsg({ ok: false, text: "Enter what you changed and why." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const saved = await api.report(r.id, {
        reporter: null,
        reason: reason.trim(),
        ...(intent ? { intent } : {}),
      });
      setMsg({ ok: true, text: "Saved." });
      onSaved(saved);
    } catch (err) {
      setMsg({
        ok: false,
        text: `Not saved: ${writeError(err)} Your text is still here.`,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit} aria-label="Report this change">
      <div className="field">
        <label htmlFor="reason">What did you change and why?</label>
        <textarea
          className="textarea"
          id="reason"
          maxLength={500}
          value={reason}
          placeholder="For example: opened for a one-off migration, closing by Friday"
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
      <div className="row between">
        <div className="seg" role="group" aria-label="Intent">
          {INTENTS.map((i) => (
            <button
              type="button"
              key={i.value}
              aria-pressed={intent === i.value}
              onClick={() => setIntent(intent === i.value ? null : i.value)}
            >
              {i.label}
            </button>
          ))}
        </div>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save report"}
        </button>
      </div>
      <div className="sub">
        {user ? `Saving as ${user.email}. ` : ""}
        This shows who submitted it, not who made the change. Recording an
        intent does not resolve the record or change anything.
      </div>
      {r.reportedAt && (
        <div className="sub">
          Last saved {formatDetected(r.reportedAt)}
          {r.reporter ? ` by ${r.reporter}` : ""} (self-reported).
        </div>
      )}
      {msg && (
        <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "ok" : "bad"}>
          {msg.text}
        </p>
      )}
      {r.intent === "keep" && <Notice tone="info">{terraformSuggestion(r)}</Notice>}
    </form>
  );
}

const KIND_LABEL: Record<string, string> = {
  report: "Explained",
  decision: "Intent recorded",
  review: "Reviewed at apply",
  run_started: "Apply started",
  run_finished: "Apply finished",
};

function History({ r }: { r: EmergencyRecord }) {
  const { s, reload } = useAsync(() => api.recordEvents(r.id), [r.id]);
  return (
    <div className="tl" aria-label="History">
      <div className="tl-item">
        <i className="dot blue" />
        <div className="b">
          <div>Detected by scan</div>
          <div className="sub">{formatDetected(r.firstDetectedAt)}</div>
        </div>
      </div>
      {s.state === "loading" && <Loading what="history" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" &&
        s.data.map((e: RecordEvent) => (
          <div className="tl-item" key={e.id}>
            <i className="dot" />
            <div className="b">
              <div>{KIND_LABEL[e.kind] ?? e.kind}</div>
              <div className="sub">
                {e.actor ?? "system"} · {e.actorAssurance} ·{" "}
                {formatDetected(e.at)}
              </div>
            </div>
          </div>
        ))}
    </div>
  );
}
