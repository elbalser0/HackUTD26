import { useState } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import type { EmergencyRecord, Intent } from "../api";
import {
  age,
  baselineText,
  CHECK_LABEL,
  demoTag,
  formatDetected,
  observedText,
  terraformSuggestion,
} from "../format";
import { useAsync } from "../useAsync";
import { ErrorState, Loading, Notice } from "./States";

export function RecordDetail({ id }: { id: string }) {
  const { s, reload, set } = useAsync(() => api.getRecord(id), [id]);
  return (
    <section className="detail">
      <a href="#/">← Open records</a>
      {s.state === "loading" && <Loading what="record" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" && <Detail r={s.data} onChange={set} />}
    </section>
  );
}

function Detail({
  r,
  onChange,
}: {
  r: EmergencyRecord;
  onChange: (r: EmergencyRecord) => void;
}) {
  const demo = demoTag(r.environment, r.evidenceSource);
  const closed = r.resolution === "resolved";
  return (
    <>
      <div className="eyebrow">RECORD</div>
      <h1 className="resource">{r.resourceAddress}</h1>
      {demo && <span className="tag tag-demo">{demo}</span>}
      <div className="diff big">
        <span>
          {r.attribute} · {r.changeKind}
        </span>
        <del>{baselineText(r)}</del> → <ins>{observedText(r)}</ins>
      </div>
      <p className="meta">
        detected at {formatDetected(r.firstDetectedAt)} (open{" "}
        {age(r.firstDetectedAt)}); last seen {formatDetected(r.lastDetectedAt)}.
        This is when the scanner noticed, not when the change was made.
      </p>
      <p className="meta">
        Resolution: {r.resolution}
        {r.resolutionReason && ` (${r.resolutionReason})`} ·{" "}
        {CHECK_LABEL[r.lastCheckStatus]}
        {r.lastCheckAt && ` · ${formatDetected(r.lastCheckAt)}`}
      </p>

      <h2>What happened</h2>
      {r.reason !== null ? (
        <blockquote>
          {r.reason}
          <footer>
            reported by {r.reporter ?? "unknown"} (self-reported, not verified)
            {r.reportedAt && ` · ${formatDetected(r.reportedAt)}`}
          </footer>
        </blockquote>
      ) : (
        <Notice tone="warn">
          Unexplained manual change — no reason recorded.
        </Notice>
      )}
      {closed ? (
        <Notice tone="info">
          This record is resolved; reports and intent changes are closed.
        </Notice>
      ) : (
        <>
          <ReportForm r={r} onSaved={onChange} />
          <Decision r={r} onChange={onChange} />
        </>
      )}
    </>
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

function SavingAs() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <p className="meta">
      Saving as <strong>{user.email}</strong> (verified Google sign-in; not
      proof of who made the change).
    </p>
  );
}

function ReportForm({
  r,
  onSaved,
}: {
  r: EmergencyRecord;
  onSaved: (r: EmergencyRecord) => void;
}) {
  const [name, setName] = useState(r.reporter ?? "");
  const [reason, setReason] = useState(r.reason ?? "");
  const [intent, setIntent] = useState<Intent | "">("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      setMsg({ ok: false, text: "Enter what you changed and why." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const saved = await api.report(r.id, {
        reporter: name.trim() || null,
        reason: reason.trim(),
        intent: intent || undefined,
      });
      onSaved(saved);
      setMsg({ ok: true, text: "Saved by the backend." });
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
    <form onSubmit={submit} className="form" aria-label="Report this change">
      <h3>{r.reason !== null ? "Update your report" : "Report this change"}</h3>
      <SavingAs />
      <label>
        Your name (optional)
        <input
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        What did you change and why?
        <textarea
          rows={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label>
        Your intent (optional)
        <select
          value={intent}
          onChange={(e) => setIntent(e.target.value as Intent | "")}
        >
          <option value="">—</option>
          <option value="keep">Keep</option>
          <option value="revert">Revert</option>
          <option value="unsure">Not sure</option>
        </select>
      </label>
      <button className="btn primary" disabled={busy}>
        {busy ? "Saving…" : "Save report"}
      </button>
      {msg && (
        <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "ok" : "bad"}>
          {msg.text}
        </p>
      )}
    </form>
  );
}

function Decision({
  r,
  onChange,
}: {
  r: EmergencyRecord;
  onChange: (r: EmergencyRecord) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function choose(i: Intent) {
    setBusy(true);
    setErr("");
    try {
      onChange(await api.decide(r.id, i));
    } catch (e) {
      setErr(writeError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="decision">
      <h2>Intent</h2>
      <p className="meta">
        Recording an intent does not resolve this record or change anything. The
        record closes only when a verified re-check shows live and Terraform
        agree.
      </p>
      <div className="row">
        {(["keep", "revert", "defer"] as Intent[]).map((i) => (
          <button
            key={i}
            className="btn"
            aria-pressed={r.intent === i}
            disabled={busy}
            onClick={() => choose(i)}
          >
            {i[0].toUpperCase() + i.slice(1)}
          </button>
        ))}
      </div>
      {r.intent !== "unset" && (
        <p role="status">
          Intent recorded: <strong>{r.intent}</strong> · record still{" "}
          {r.resolution}.
        </p>
      )}
      {err && (
        <p role="alert" className="bad">
          Intent not saved: {err}
        </p>
      )}
      {r.intent === "keep" && (
        <Notice tone="info">{terraformSuggestion(r)}</Notice>
      )}
    </div>
  );
}
