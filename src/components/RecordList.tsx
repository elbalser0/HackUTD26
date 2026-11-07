import { api } from "../api";
import type { EmergencyRecord, Health } from "../api";
import {
  age,
  CHECK_LABEL,
  baselineText,
  demoTag,
  formatDetected,
  observedText,
} from "../format";
import { useAsync } from "../useAsync";
import { ErrorState, Loading, Notice } from "./States";

export function RecordList() {
  const { s, reload } = useAsync(() => api.listRecords(), []);
  return (
    <section className="detail">
      <div className="eyebrow">OPEN RECORDS</div>
      <h1>
        Manual changes,
        <br />
        <span>before the next apply.</span>
      </h1>
      <p className="lede">
        Manual changes the scanner detected that Terraform would undo.
      </p>
      {s.state === "loading" && <Loading what="records" />}
      {s.state === "error" && <ErrorState error={s.error} onRetry={reload} />}
      {s.state === "ok" && (
        <>
          <Freshness health={s.data.health} records={s.data.records} />
          {s.data.records.length === 0 ? (
            <p className="state">
              No open records. This is not proof nothing changed: the scanner
              only sees attributes Terraform's provider tracks, and this
              response carries no scan time.
            </p>
          ) : (
            <ul className="cards">
              {s.data.records.map((r) => (
                <li key={r.id}>
                  <Card r={r} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function Card({ r }: { r: EmergencyRecord }) {
  const demo = demoTag(r.environment, r.evidenceSource);
  return (
    <a className="card panel" href={`#/records/${encodeURIComponent(r.id)}`}>
      <div className="card-top">
        <code>{r.resourceAddress}</code>
        <span>
          {demo && <span className="tag tag-demo">{demo}</span>}{" "}
          {r.reason !== null ? (
            <span className="tag">reported by {r.reporter ?? "unknown"}</span>
          ) : (
            <span className="tag tag-warn">no reason recorded</span>
          )}
        </span>
      </div>
      <div className="diff">
        <span>
          {r.attribute} · {r.changeKind}
        </span>
        <del>{baselineText(r)}</del> → <ins>{observedText(r)}</ins>
      </div>
      <div className="meta">
        detected at {formatDetected(r.firstDetectedAt)} · open{" "}
        {age(r.firstDetectedAt)} · intent: {r.intent} ·{" "}
        {CHECK_LABEL[r.lastCheckStatus]}
        {r.lastCheckAt && ` (${age(r.lastCheckAt)} ago)`}
      </div>
    </a>
  );
}

export function Freshness({
  health,
  records,
}: {
  health: Health | null;
  records: EmergencyRecord[];
}) {
  const bad = records.filter((r) => r.lastCheckStatus !== "current").length;
  return (
    <>
      {(!health || health.status !== "ok") && (
        <Notice tone="warn">
          Backend health is{" "}
          {health ? `"${health.status}" (db: ${health.db})` : "unreachable"}.
          Records below may be incomplete.
        </Notice>
      )}
      {bad > 0 && (
        <Notice tone="warn">
          {bad} record{bad === 1 ? "" : "s"} not confirmed by the latest check
          (stale, failed or unsupported). Their live values may have changed.
        </Notice>
      )}
    </>
  );
}
